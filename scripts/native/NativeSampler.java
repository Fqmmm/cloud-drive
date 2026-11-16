import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.*;

/** One-Hz cgroup-v2 accounting for direct Linux processes; no container runtime. */
public final class NativeSampler {
    static Map<String, Long> fields(Path path) throws Exception {
        Map<String, Long> values = new HashMap<>();
        for (String line : Files.readAllLines(path)) {
            String[] parts = line.trim().split("\\s+");
            if (parts.length == 2) values.put(parts[0], Long.parseLong(parts[1]));
        }
        return values;
    }

    static long[] processMemory(String pid) {
        long rss = 0, pss = 0;
        try {
            for (String line : Files.readAllLines(Path.of("/proc", pid, "smaps_rollup"))) {
                String[] parts = line.trim().split("\\s+");
                if (parts[0].equals("Rss:")) rss = Long.parseLong(parts[1]) * 1024;
                if (parts[0].equals("Pss:")) pss = Long.parseLong(parts[1]) * 1024;
            }
        } catch (Exception vanished) { }
        return new long[]{rss, pss};
    }

    public static void main(String[] args) throws Exception {
        Path base = Path.of("/sys/fs/cgroup/cloud-drive-e1-native");
        Path stop = Path.of(args[0]);
        String[] names = {"auth-service", "file-service", "frontend", "minio", "mysql", "share-service"};
        Map<String, Long> previous = new HashMap<>();
        long prior = System.nanoTime(), ownPrior = 0, target = prior;
        boolean first = true;
        System.out.println("linux_epoch,linux_utc,service,cpu_percent,memory_usage_bytes,memory_working_set_bytes,memory_rss_bytes,memory_pss_bytes,block_read_bytes,block_write_bytes,interval_seconds");
        while (!Files.exists(stop)) {
            long now = System.nanoTime();
            double gap = (now - prior) / 1e9;
            double epoch = System.currentTimeMillis() / 1000.0;
            for (String name : names) {
                try {
                    Path group = base.resolve(name);
                    long usage = fields(group.resolve("cpu.stat")).get("usage_usec");
                    Long before = previous.put(name, usage);
                    String cpu = before == null ? "" : Double.toString((usage - before) / 1e6 / gap * 100);
                    long memory = Long.parseLong(Files.readString(group.resolve("memory.current")).trim());
                    long inactive = fields(group.resolve("memory.stat")).getOrDefault("inactive_file", 0L);
                    long rss = 0, pss = 0, read = 0, written = 0;
                    for (String pid : Files.readAllLines(group.resolve("cgroup.procs"))) {
                        long[] values = processMemory(pid.trim()); rss += values[0]; pss += values[1];
                    }
                    for (String line : Files.readAllLines(group.resolve("io.stat"))) {
                        for (String item : line.split(" ")) {
                            if (item.startsWith("rbytes=")) read += Long.parseLong(item.substring(7));
                            if (item.startsWith("wbytes=")) written += Long.parseLong(item.substring(7));
                        }
                    }
                    System.out.println(epoch + "," + Instant.now() + "," + name + "," + cpu + "," + memory + ","
                        + Math.max(0, memory - inactive) + "," + rss + "," + pss + "," + read + "," + written + "," + gap);
                } catch (Exception error) {
                    System.err.println(Instant.now() + " service=" + name + " error=" + error.getClass().getSimpleName());
                }
            }
            long own = ProcessHandle.current().info().totalCpuDuration().orElse(java.time.Duration.ZERO).toNanos();
            long[] mem = processMemory(Long.toString(ProcessHandle.current().pid()));
            System.out.println(epoch + "," + Instant.now() + ",__collector," + (first ? 0 : ((own - ownPrior) / 1e9 / gap * 100))
                + "," + mem[0] + "," + mem[0] + "," + mem[0] + "," + mem[1] + ",0,0," + gap);
            System.out.flush();
            ownPrior = own; prior = now; target += 1_000_000_000L;
            first = false;
            long delay = target - System.nanoTime();
            if (delay > 0) Thread.sleep(delay / 1_000_000L);
        }
    }
}
