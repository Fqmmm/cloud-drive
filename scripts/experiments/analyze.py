"""Recompute E3/E4 summaries from measured CSV/JSON only; incomplete stays incomplete."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import statistics

from probes import recovery
from support import ROOT, csv_write, digest, save, utc


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def summarize_round(folder):
    result, events = read(folder / "result.json"), read(folder / "events.json")
    if not result["completed"]:
        raise ValueError("Cannot summarize an incomplete fault round")
    times = {r["name"]: r["epoch"] for r in events}
    t0, t3 = times["t0-inject"], times.get("t3-start-command")
    with (folder / "probe.csv").open(encoding="utf-8", newline="") as stream:
        probes = list(csv.DictReader(stream))
    names = sorted({r["probe"] for r in probes})
    recovered = recovery(probes, t3 or t0, names)
    if set(recovered) != set(names):
        raise ValueError("Missing three consecutive successes after fault")
    common_t5 = max(recovered.values())
    rows = []
    for name in names:
        records = [r for r in probes if r["probe"] == name]
        fault_records = [r for r in records if t0 <= float(r["planned_epoch"]) < common_t5]
        # A queued probe may be planned before injection but actually sent after
        # it. Use actual send/return times for t1; planned time only assigns the
        # scheduled-request success-rate window.
        failed = [r for r in records if r["sent_epoch"] and float(r["sent_epoch"]) >= t0 and r["category"] != "ok"]
        first = min((float(r["sent_epoch"]) for r in failed if r["sent_epoch"]), default=None)
        observed = min((float(r["returned_epoch"]) for r in failed if r.get("returned_epoch")), default=None)
        errors = Counter(r["category"] for r in fault_records if r["category"] != "ok")
        rows.append(dict(fault=result["fault"], repeat=result["repeat"], probe=name, t0=t0, t3=t3, t5=recovered[name],
            first_failed_sent_epoch=first, first_failed_returned_epoch=observed,
            failure_window_seconds=max(0, recovered[name] - first) if first is not None else None,
            recovery_seconds=recovered[name] - (t3 or t0), window_scheduled=len(fault_records),
            window_success=sum(r["category"] == "ok" for r in fault_records),
            window_success_rate=sum(r["category"] == "ok" for r in fault_records) / len(fault_records) if fault_records else None,
            errors=json.dumps(errors, sort_keys=True), max_schedule_lag_ms=max(float(r["schedule_lag_ms"]) for r in records),
            max_elapsed_ms=max(float(r["elapsed_ms"]) for r in records)))
    service = next(r["service"] for r in events if r["name"] == "t0-inject")
    before = next(r for r in read(folder / "before" / "containers.json") if r["service"] == service)
    after = next(r for r in read(folder / "after" / "containers.json") if r["service"] == service)
    auto = result["fault"] == "F5"
    exit_events = []
    for line in (folder / "docker-events.jsonl").read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event.get("Action") == "die" and event.get("Actor", {}).get("ID") == before["id"]:
            exit_events.append(event)
    if auto and not any(e["Actor"]["Attributes"].get("exitCode") == "17" for e in exit_events):
        raise ValueError("Automatic recovery has no Docker die event with exitCode 17")
    from datetime import datetime
    t4 = datetime.fromisoformat(after["started"].replace("Z", "+00:00")).timestamp()
    t2 = min((e.get("timeNano", e.get("time", 0) * 1e9) / 1e9 for e in exit_events), default=times.get("t2-stop-confirmed"))
    t1 = min((r["first_failed_returned_epoch"] for r in rows if r["first_failed_returned_epoch"] is not None), default=None)
    return rows, dict(fault=result["fault"], repeat=result["repeat"], recovery_mode="automatic" if auto else "manual-start",
        t0=t0, t1=t1, t2=t2, t3=t3, t4=t4, common_t5=common_t5,
        recovery_seconds=common_t5 - (t3 or t0), stopped_seconds=(t3 - times["t2-stop-confirmed"]) if t3 else None,
        restart_count_before=before["restart_count"] if auto else None,
        restart_count_after=after["restart_count"] if auto else None,
        exit_to_start_seconds=_exit_to_start(exit_events, after) if auto else None,
        exit_to_business_seconds=common_t5 - t2 if auto and t2 is not None else None)


def _exit_to_start(events, container):
    from datetime import datetime
    exits = [e for e in events if e["Actor"]["Attributes"].get("exitCode") == "17"]
    if not exits:
        return None
    exited = exits[0].get("timeNano", exits[0].get("time", 0) * 1e9) / 1e9
    started = datetime.fromisoformat(container["started"].replace("Z", "+00:00")).timestamp()
    return started - exited


def report_e3(folder, output):
    manifest = read(folder / "manifest.json")
    if manifest["status"] != "complete" or manifest["kind"] != "formal" or manifest["repeats"] != 3:
        raise ValueError("E3 report requires a complete formal batch with three repeats")
    expected = {f"{f}-r{n}" for f in manifest["faults"] for n in range(1, 4)}
    if set(manifest["completed"]) != expected or not {"F1", "F2", "F3", "F4", "F5"} <= set(manifest["faults"]):
        raise ValueError("Formal E3 matrix is incomplete")
    rows, times = [], []
    for name in sorted(expected):
        probes, timeline = summarize_round(folder / name)
        rows.extend(probes)
        times.append(timeline)
    csv_write(folder / "impact.csv", rows)
    csv_write(folder / "recovery.csv", times)
    aggregate = []
    for fault in manifest["faults"]:
        values = [r["recovery_seconds"] for r in times if r["fault"] == fault]
        aggregate.append(dict(fault=fault, r1=values[0], r2=values[1], r3=values[2],
            median=statistics.median(values), minimum=min(values), maximum=max(values)))
    csv_write(folder / "recovery-summary.csv", aggregate)
    lines = ["# E3 服务故障影响与恢复实测报告", "", "负责人：刘骐语。数据批次：`" + folder.name + "`。",
        "", "## 恢复时间", "", "人工停服使用启动命令时刻 t3 为起点；JVM 异常退出使用注入时刻 t0 为起点。终点为每条探针连续三次成功的第一次发出时刻，再取全部业务恢复的最晚值。", "",
        "| 故障 | 第一次/s | 第二次/s | 第三次/s | 中位数/s | 最小—最大/s |", "|---|---:|---:|---:|---:|---:|"]
    for row in aggregate:
        lines.append(f"| {row['fault']} | {row['r1']:.3f} | {row['r2']:.3f} | {row['r3']:.3f} | {row['median']:.3f} | {row['minimum']:.3f}—{row['maximum']:.3f} |")
    lines.extend(["", "## 故障影响", "", "下表汇总三轮中从 t0 到共同稳定恢复 t5 的探测；调度时间决定窗口归属。原始业务码、错误类别和调度偏差见 impact.csv/probe.csv。", "",
        "| 故障 | 业务 | 窗口成功/计划请求 | 成功率 |", "|---|---|---:|---:|"])
    for fault in manifest["faults"]:
        for name in sorted({r["probe"] for r in rows}):
            selected = [r for r in rows if r["fault"] == fault and r["probe"] == name]
            count = sum(r["window_scheduled"] for r in selected)
            success = sum(r["window_success"] for r in selected)
            lines.append(f"| {fault} | {name} | {success}/{count} | {success/count:.2%} |" if count else f"| {fault} | {name} | 0/0 | 无样本 |")
    lines.extend(["", "F1 分享服务停止；F2 认证服务停止；F3 文件服务停止；F4 MinIO 停止；F5 分享 JVM halt(17)；F6 为可选 MySQL 停止。",
        "", "## 方法与证据", "", "每轮基线 30 秒，停服确认后维持 30 秒，F1—F5 各三轮。私有文件探针整轮使用注入前的同一 JWT；登录探针不会补发其凭证。普通请求 5 秒、下载 15 秒绝对期限，由独立子进程执行，超时终止。1 Hz 探测给出约一秒的采样分辨率，实际调度偏差已逐请求记录。",
        "", "F5 的 Docker die 事件必须包含 exitCode=17，并验证同一容器 RestartCount 增加。运行状态、健康状态、业务稳定恢复分开记录；F5 启用/关闭故障开关所需重建和 Nginx reload 在计时窗口之外。所有恢复后样本经过个人及两种分享下载校验。",
        "", "MinIO 故障轮次额外验证失败上传不增加容量，删除产生持久待清理任务；恢复后等待任务自然重试并确认对象消失。没有手工删除队列或修改重试时间。",
        "", f"原始数据：[批次目录](../../experiments/E3/{folder.name}/)。每轮 events.json、states.jsonl、docker-events.jsonl、execution.jsonl、probe.csv、容器快照、服务日志和 verification/ 为对应证据。实验结束关闭故障钩子并保存 404 验证。",
        "", "单机服务级实验不能说明宿主机或磁盘故障下的高可用性。没有观察到失败的探针按实际采样报告，不能推出零停机。", ""])
    output.write_text("\n".join(lines), encoding="utf-8")


def report_e4(folder, output):
    manifest = read(folder / "manifest.json")
    if manifest["status"] != "complete" or set(manifest["completed"]) != {f"{s}-r{n}" for s in ("mysql", "minio") for n in range(1, 4)}:
        raise ValueError("E4 report requires six completed infrastructure replacements")
    rows = []
    for name in manifest["completed"]:
        result = read(folder / name / "result.json")
        if not result["completed"]:
            raise ValueError("Incomplete E4 round")
        before = next(r for r in read(folder / name / "before" / "containers.json") if r["service"] == result["service"])
        after = next(r for r in read(folder / name / "after" / "containers.json") if r["service"] == result["service"])
        with (folder / name / "verification" / "checksums.csv").open(encoding="utf-8") as stream:
            checks = list(csv.DictReader(stream))
        rows.append(dict(service=result["service"], repeat=result["repeat"], container_before=before["id"], container_after=after["id"],
            retained_volume=result["container_changed_volume_retained"], metadata_equal=all(result["metadata_equal"].values()),
            objects_equal=result["object_keys_sizes_equal"], downloads=len(checks),
            hashes_passed=sum(r["passed"] == "True" for r in checks),
            manual_restart_seconds=next(r["seconds"] for r in result["steps"] if r["name"] == "manual-application-restart")))
    csv_write(folder / "persistence-summary.csv", rows)
    lines = ["# E4 数据持久化与文件完整性实测报告", "", f"负责人：刘骐语。数据批次：`{folder.name}`。", "",
        "两个用户各上传 1 KiB、1 MiB、20 MiB 样本，文件名包含中文及空格；每份文件分别创建公开及提取码分享。样本在六轮基础实验中不重新上传。", "",
        "| 服务 | 重复 | 容器替换且卷不变 | 元数据一致 | 对象键/大小一致 | 下载哈希通过/总数 |", "|---|---:|---|---|---|---:|"]
    for row in rows:
        lines.append(f"| {row['service']} | {row['repeat']} | {row['retained_volume']} | {row['metadata_equal']} | {row['objects_equal']} | {row['hashes_passed']}/{row['downloads']} |")
    deletion = read(folder / "deletion" / "result.json")
    lines.extend(["", f"额外文件永久删除检查：{'通过' if deletion['passed'] else '失败'}。检查重复删除、容量、旧分享、活动列表和对象最终清理。版本为一文件一对象，不启用去重。", "",
        "每轮等待被替换基础服务就绪后，按固定步骤人工重启三个业务服务、等待健康并验证 Nginx 配置后 reload；这些操作及耗时单列，不作为自动恢复能力。每轮个人及两种原分享下载全部六个样本，同时检查跨用户拒绝访问、错误提取码拒绝、桶拒绝匿名列举和直接读取对象。", "",
        "元数据比较包含用户、账户、目录、文件、容量、分享、记录数及清理队列；比较稳定字段，密码哈希和分享令牌未公开。对象键与大小清单与下载 SHA-256 分别提供存储映射和实际内容证据。容器 ID、挂载卷名和目标路径见逐轮快照。"])
    restore = folder / "backup-restore" / "result.json"
    if restore.exists():
        result = read(restore)
        lines.extend(["", "## 新卷备份恢复扩展", "", f"完成：{result['completed']}；新卷独立：{result.get('new_volumes')}；备份 {result.get('backup_bytes')} 字节；备份用时 {result.get('backup_seconds', 0):.3f} 秒；恢复并完成业务校验用时 {result.get('restore_seconds', 0):.3f} 秒。",
            "", "数据库和对象在同一个停止写入窗口内备份；另一个项目和前端端口导入 SQL、恢复对象并设置私有策略。原用户、目录、容量、原分享 token 路径及所有样本下载重新验证，原项目保留作对照。备份文件包含敏感信息，留在 artifacts/；公开 SHA-256 清单和校验结果随批次归档。"])
    else:
        lines.extend(["", "新卷备份恢复扩展未执行，不据此作出备份可恢复结论。"])
    lines.extend(["", f"原始数据：[批次目录](../../experiments/E4/{folder.name}/)。基线、每次重建前后快照、只读元数据、对象清单、权限和哈希检查、执行命令及日志均保留。", "",
        "实验只验证这些命名卷在容器替换后保留数据，不能说明卷被删除、磁盘损坏或宿主机故障时的数据安全。", ""])
    output.write_text("\n".join(lines), encoding="utf-8")


def audit_public(paths, private):
    from support import Context
    ctx = Context(private / ".env")
    # Acceptance generated additional short-lived secrets; its public copies
    # are redacted at capture. These explicit checks cover retained credentials.
    forbidden = [v.encode() for v in ctx.sensitive if v and len(v) >= 12]
    violations = []
    for folder in paths:
        for path in folder.rglob("*"):
            if path.is_file():
                content = path.read_bytes()
                if any(secret in content for secret in forbidden) or __import__("re").search(rb"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", content):
                    violations.append(str(path.relative_to(ROOT)))
                if __import__("re").search(rb'"extractCode"\s*:\s*"[0-9]{6}"', content):
                    violations.append(str(path.relative_to(ROOT)))
    if violations:
        raise ValueError("Public evidence contains sensitive values: " + ", ".join(violations))


def normalize_public(paths):
    """Hash the same UTF-8/LF bytes that Git stores on a Windows checkout."""
    for folder in paths:
        for path in folder.rglob("*"):
            if path.is_file() and path.suffix in (".csv", ".json", ".jsonl", ".log", ".md", ".txt"):
                original = path.read_bytes()
                canonical = original.replace(b"\r\n", b"\n")
                if canonical != original:
                    path.write_bytes(canonical)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    if not __import__("re").fullmatch(r"[a-z0-9-]{1,24}", args.run_id):
        parser.error("Invalid run ID")
    e3, e4 = ROOT / "experiments" / "E3" / args.run_id, ROOT / "experiments" / "E4" / args.run_id
    accepted = read(ROOT / "experiments" / "acceptance" / args.run_id / "results.json")
    if not accepted["completed"]:
        raise ValueError("Functional acceptance not complete")
    report_e3(e3, ROOT / "docs" / "exp" / "E3-results.md")
    report_e4(e4, ROOT / "docs" / "exp" / "E4-results.md")
    paths = [e3, e4, ROOT / "experiments" / "acceptance" / args.run_id,
             ROOT / "experiments" / "acceptance" / (args.run_id + "-deployment"), ROOT / "experiments" / "datasets" / args.run_id]
    normalize_public(paths)
    audit_public(paths, ROOT / "artifacts" / "liu" / args.run_id)
    files = [p for folder in paths for p in folder.rglob("*") if p.is_file() and p.name != "evidence-index.json"]
    save(e4 / "evidence-index.json", dict(generated=utc(), files=[dict(path=str(p.relative_to(ROOT)), bytes=p.stat().st_size,
         sha256=digest(p.read_bytes())) for p in sorted(files)]))
    print("Reports and SHA-256 evidence index generated from completed batches.")


if __name__ == "__main__":
    main()
