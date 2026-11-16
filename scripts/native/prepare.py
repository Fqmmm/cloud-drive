"""Prepare a dedicated D-backed WSL environment from immutable baseline images."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
LAB = Path("D:/CloudDriveLab/E1Native")
DISTRO = "CloudDrive-E1-Native"


def command(args, timeout=600):
    result = subprocess.run(args, cwd=ROOT, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError("Preparation command failed: " + args[0])
    return result.stdout.decode("utf-8", errors="replace").strip()


def main():
    if LAB.exists():
        raise RuntimeError("Dedicated lab already exists; inspect it rather than overwrite")
    LAB.mkdir(parents=True)
    exports = LAB / "exports"
    exports.mkdir()
    baseline = json.loads((ROOT / "experiments/E1/20261116-e1-formal-ipv4-summary/environment.json").read_text())
    images = {entry["service"]: entry["image_id"] for entry in baseline["containers"]}
    provenance = dict(distro=DISTRO, install_location=str(LAB / "wsl"), image_ids=images,
        method="Export immutable filesystem from newly-created, never-started helper containers; WSL direct processes during measurement")
    for service in ["auth-service", "file-service", "share-service", "frontend", "mysql", "minio"]:
        name = "e1-native-export-" + service
        command(["docker", "create", "--name", name, "--entrypoint", "/bin/true", images[service]])
        try:
            if service in ["auth-service", "file-service", "frontend", "mysql"]:
                target = exports / (service + ".tar")
                command(["docker", "export", "-o", str(target), name])
                print("Exported " + service + " (" + str(round(target.stat().st_size / 2**20, 1)) + " MiB)", flush=True)
            elif service == "share-service":
                command(["docker", "cp", name + ":/app/app.jar", str(exports / "share-service.jar")])
                command(["docker", "cp", name + ":/app/probe/com/jiayuan/drive/shares/HealthProbe.class", str(exports / "ShareHealthProbe.class")])
            else:
                for binary in ["minio", "mc"]:
                    command(["docker", "cp", name + ":/usr/bin/" + binary, str(exports / binary)])
        finally:
            # -v removes only anonymous volumes allocated to this never-started helper.
            command(["docker", "rm", "-v", name])
    command(["wsl.exe", "--import", DISTRO, str(LAB / "wsl"), str(exports / "auth-service.tar"), "--version", "2"])
    provenance["export_sha256"] = {p.name: hashlib.file_digest(p.open("rb"), "sha256").hexdigest() for p in exports.iterdir()}
    (LAB / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    command(["wsl.exe", "-d", DISTRO, "-u", "root", "--exec", "bash", "-c",
        "mkdir -p /opt/e1-native/{bin,apps,pids,logs,mysql-image,nginx-image}; /opt/java/openjdk/bin/java -version"])
    print("Dedicated native WSL environment imported on D; existing distributions unchanged.", flush=True)


if __name__ == "__main__":
    main()
