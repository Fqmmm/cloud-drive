"""Direct Linux service deployment, scoped SQL and experiment-only cleanup."""
import hashlib
import json
from pathlib import Path
import re
import secrets
import shlex
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/performance"))
from common import Client, MIB, checksum, payload, save, utc

DISTRO = "CloudDrive-E1-Native"
LAB = Path("D:/CloudDriveLab/E1Native")
LINUX = "/opt/e1-native"
SERVICES = ["mysql", "minio", "auth-service", "file-service", "share-service", "frontend"]


def linux_path(path):
    value = str(Path(path).resolve()).replace("\\", "/")
    if not re.match(r"^[CD]:/", value):
        raise ValueError("Expected a verified C or D mounted path")
    return "/mnt/" + value[0].lower() + value[2:]


class Runtime:
    def __init__(self, private):
        self.private = private
        self.env_file = LAB / "env.local"
        self.values = {}
        self.processes = {}
        self.handles = []
        self.base = "http://127.0.0.1:18080"

    def wsl(self, *args, data=None, check=True, timeout=120):
        result = subprocess.run(["wsl.exe", "-d", DISTRO, "-u", "root", "--exec", *args],
            input=data.encode() if isinstance(data, str) else data, capture_output=True, timeout=timeout)
        if check and result.returncode:
            raise RuntimeError("Native operation failed; command=" + args[0] + "; exit=" + str(result.returncode))
        return result

    def shell(self, text, **kwargs):
        return self.wsl("bash", "-c", text, **kwargs)

    def sql(self, statement, initial=False, bootstrap=False):
        args = [LINUX + "/mysql-client.sh"] + (["--bootstrap"] if bootstrap else ["--init"] if initial else [])
        return self.wsl(*args, data=statement).stdout.decode().strip()

    def install(self):
        if self.env_file.exists():
            self.values = dict(x.split("=", 1) for x in self.env_file.read_text().splitlines() if "=" in x and not x.startswith("#"))
        else:
            values = dict(x.split("=", 1) for x in (ROOT / ".env.example").read_text().splitlines() if "=" in x and not x.startswith("#"))
            for k in ["MYSQL_ROOT_PASSWORD", "AUTH_DB_PASSWORD", "FILE_DB_PASSWORD", "SHARE_DB_PASSWORD", "MINIO_ROOT_PASSWORD", "JWT_SECRET", "INTERNAL_API_TOKEN"]:
                values[k] = secrets.token_hex(32)
            values.update(MINIO_ROOT_USER="native-storage", APP_VERSION="course-v1")
            for service, database in [("AUTH", "auth"), ("FILE", "file"), ("SHARE", "share")]:
                values[service + "_DB_URL"] = "jdbc:mysql://127.0.0.1:3306/" + database + "_db?connectionTimeZone=UTC&forceConnectionTimeZoneToSession=true&connectTimeout=3000&socketTimeout=5000"
            values["MINIO_ENDPOINT"] = "http://127.0.0.1:9000"
            self.values = values
        self.values.update(FILE_SERVICE_URL="http://127.0.0.1:18082", PUBLIC_BASE_URL=self.base,
                           MINIO_ENDPOINT="http://127.0.0.1:19000",HTTP_PORT="18080",TZ="UTC",LANG="en_US.UTF-8",SERVER_ADDRESS="127.0.0.1")
        if self.wsl('diff','-qr','/opt/java/openjdk',LINUX+'/apps/file-service/opt/java/openjdk',check=False).returncode==0:
            self.values['FILE_JAVA_HOME']='/opt/java/openjdk'
        for service in ["AUTH", "FILE", "SHARE"]:
            self.values[service + "_DB_URL"] = self.values[service + "_DB_URL"].replace(":3306/", ":13306/")
        self.env_file.write_text("\n".join(k + "=" + v for k, v in self.values.items()) + "\n", encoding="utf-8")
        script = "\n".join("export " + k + "=" + shlex.quote(v) for k, v in self.values.items()) + "\n"
        self.shell("umask 077; cat > " + LINUX + "/runtime.env.sh", data=script)
        for name in ["mysql-client.sh", "service.sh"]:
            self.shell("cat > " + LINUX + "/" + name + "; chmod 700 " + LINUX + "/" + name,
                       data=(ROOT / "scripts/native" / name).read_text())
        self.shell("mkdir -p " + LINUX + "/{data/mysql,data/mysql-files,data/minio,nginx,probe/com/jiayuan/drive/shares,tools}; "
            "cp /mnt/d/CloudDriveLab/E1Native/exports/ShareHealthProbe.class " + LINUX + "/probe/com/jiayuan/drive/shares/HealthProbe.class; "
            "if ! id mysql >/dev/null 2>&1; then useradd --system --user-group --no-create-home mysql; fi; "
            "if ! id nginx >/dev/null 2>&1; then useradd --system --user-group --no-create-home nginx; fi; "
            "mkdir -p /var/cache/nginx /var/log/nginx; chown nginx:nginx /var/cache/nginx /var/log/nginx; "
            "chown -R mysql:mysql " + LINUX + "/data/mysql " + LINUX + "/data/mysql-files; "
            "chmod 755 " + LINUX + "/data; echo '+cpu +memory +io +pids' > /sys/fs/cgroup/cgroup.subtree_control; "
            "mkdir -p /sys/fs/cgroup/cloud-drive-e1-native; "
            "echo '+cpu +memory +io +pids' > /sys/fs/cgroup/cloud-drive-e1-native/cgroup.subtree_control")
        public_config = (ROOT / "frontend/nginx/default.conf").read_text()
        for old, new in [("auth-service:8080", "127.0.0.1:18081"), ("file-service:8080", "127.0.0.1:18082"), ("share-service:8080", "127.0.0.1:18083")]:
            public_config = public_config.replace(old, new)
        public_config = public_config.replace("listen 80;", "listen 127.0.0.1:18080;")
        public_config = public_config.replace("/usr/share/nginx/html", LINUX + "/nginx-image/usr/share/nginx/html")
        public_config = public_config.replace("    resolver 127.0.0.11 valid=5s ipv6=off;\n", "")
        public_config = public_config.replace("/var/log/nginx/", LINUX + "/logs/")
        public_config = public_config.replace("/etc/nginx/course-proxy.conf", LINUX + "/nginx/course-proxy.conf")
        # Resolve fixed loopback upstream addresses directly; API routes/buffering/timeouts remain unchanged.
        self.shell("cat > " + LINUX + "/nginx/default.conf", data=public_config)
        self.shell("cat > " + LINUX + "/nginx/course-proxy.conf", data=(ROOT / "frontend/nginx/course-proxy.conf").read_text())
        main = "user nginx;\nworker_processes auto;\npid " + LINUX + "/pids/nginx.pid;\nerror_log " + LINUX + "/logs/nginx-main.log crit;\nevents { worker_connections 1024; }\nhttp {\ninclude " + LINUX + "/nginx-image/etc/nginx/mime.types;\ndefault_type application/octet-stream;\nsendfile on;\nkeepalive_timeout 65;\ninclude " + LINUX + "/nginx/default.conf;\n}\n"
        self.shell("cat > " + LINUX + "/nginx/nginx.conf", data=main)
        classes = self.private / "classes"
        classes.mkdir(exist_ok=True)
        subprocess.run(["javac", "--release", "17", "-d", str(classes), str(ROOT / "scripts/native/NativeSampler.java")], check=True, capture_output=True)
        self.shell("cp " + shlex.quote(linux_path(classes / "NativeSampler.class")) + " " + LINUX + "/tools/")

    def start_service(self, service):
        if service not in SERVICES:
            raise ValueError("Unknown native service")
        output = (self.private / (service + ".log")).open("wb")
        self.handles.append(output)
        self.processes[service] = subprocess.Popen(["wsl.exe", "-d", DISTRO, "-u", "root", "--exec", "bash", LINUX + "/service.sh", service], stdout=output, stderr=output)

    def start(self):
        initialized = self.shell("test -d " + LINUX + "/data/mysql/mysql", check=False).returncode == 0
        configured = self.shell("test -f " + LINUX + "/data/configured.marker", check=False).returncode == 0
        if not initialized:
            result = self.shell(LINUX + "/mysql-image/lib64/ld-linux-x86-64.so.2 --library-path " + LINUX + "/mysql-image/lib64:" + LINUX + "/mysql-image/usr/lib64/mysql/private " + LINUX + "/mysql-image/usr/sbin/mysqld --no-defaults --initialize-insecure --user=mysql --basedir=" + LINUX + "/mysql-image/usr --datadir=" + LINUX + "/data/mysql --lc-messages-dir=" + LINUX + "/mysql-image/usr/share/mysql-8.0 --default-time-zone=+00:00", timeout=120)
            (self.private / "mysql-initialize.log").write_bytes(result.stdout + result.stderr)
        self.start_service("mysql")
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if self.wsl(LINUX + "/mysql-client.sh", "--init" if configured else "--bootstrap", data="SELECT 1", check=False).returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("Native MySQL did not become available")
        if not configured:
            # Initialize the isolated new database with the same schema and grants.
            statements = ["SET SESSION sql_mode='NO_BACKSLASH_ESCAPES';"]
            for db in ["auth", "file", "share"]:
                password = self.values[db.upper() + "_DB_PASSWORD"]
                statements += [f"CREATE DATABASE {db}_db CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_as_cs;",
                    f"CREATE USER '{db}_user'@'%' IDENTIFIED BY '{password}';", f"GRANT SELECT,INSERT,UPDATE,DELETE ON {db}_db.* TO '{db}_user'@'%';",
                    (ROOT / "backend/sql/course-mysql/schema" / (db + "_db.sql")).read_text()]
            statements += ["CREATE TABLE file_db.schema_version(version INT PRIMARY KEY, applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP) ENGINE=InnoDB; INSERT INTO file_db.schema_version(version) VALUES(1);"]
            self.sql("\n".join(statements), bootstrap=True)
            self.sql("ALTER USER 'root'@'localhost' IDENTIFIED BY '" + self.values["MYSQL_ROOT_PASSWORD"] + "';", bootstrap=True)
            self.shell("touch " + LINUX + "/data/configured.marker")
        for service in SERVICES[1:]:
            self.start_service(service)
        self.ready()

    def ready(self):
        import requests
        client = requests.Session(); client.trust_env = False
        deadline = time.monotonic() + 180
        try:
            while time.monotonic() < deadline:
                if any(p.poll() is not None for p in self.processes.values()):
                    raise RuntimeError("A native service exited; inspect private startup logs")
                try:
                    if all(client.get("http://127.0.0.1:" + str(port) + path, timeout=2).status_code == 200 for port, path in [(18081,"/health/ready"),(18082,"/health/ready"),(18083,"/health/ready"),(18080,"/healthz")]):
                        return
                except requests.RequestException:
                    pass
                time.sleep(1)
        finally:
            client.close()
        raise RuntimeError("Native HTTP services did not become ready")

    def stop(self):
        for service in reversed(SERVICES):
            self.shell("p=" + LINUX + "/pids/" + service + ".pid; if test -f \"$p\"; then n=$(cat \"$p\"); if grep -Fq 'cloud-drive-e1-native/" + service + "' /proc/\"$n\"/cgroup 2>/dev/null; then kill -TERM \"$n\" 2>/dev/null || true; fi; fi", check=False)
        for process in self.processes.values():
            try: process.wait(timeout=15)
            except subprocess.TimeoutExpired: pass
        for service in SERVICES:
            self.shell("test ! -f /sys/fs/cgroup/cloud-drive-e1-native/" + service + "/cgroup.kill || echo 1 > /sys/fs/cgroup/cloud-drive-e1-native/" + service + "/cgroup.kill", check=False)
        for process in self.processes.values():
            if process.poll() is None: process.terminate()
        for handle in self.handles: handle.close()

    def cleanup_uploads(self, fixtures):
        keys, count = [], 0
        for f in fixtures:
            owner, directory = int(f["userId"]), int(f["uploadDirectory"])
            client = Client(self.base); client.login(f)
            if int(client.data('/users/me')['userId']) != owner:
                raise RuntimeError('Fixture owner verification failed before cleanup')
            found = self.sql("SELECT f.object_key FROM file_db.sys_file f LEFT JOIN file_db.object_cleanup c ON c.object_key=f.object_key " + f"WHERE f.user_id={owner} AND f.parent_id={directory} AND f.is_directory=0 AND (f.is_deleted=0 OR c.object_key IS NOT NULL)")
            keys.extend(k for k in found.splitlines() if re.fullmatch(r"[0-9a-f-]{36}", k))
            for item in client.data("/files?parentId=" + str(directory))["items"]:
                client.data("/files/" + item["id"], "DELETE"); count += 1
            if client.data("/quota")["usedBytes"] != f["baselineBytes"]:
                raise RuntimeError("Native test quota did not return to baseline")
            client.session.close()
        keys = sorted(set(keys))
        alias = "source " + LINUX + "/runtime.env.sh; " + LINUX + '/bin/mc alias set e1 http://127.0.0.1:19000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" </dev/null >/dev/null; '
        if keys:
            removed = self.shell(alias + LINUX + "/bin/mc rm --force --stdin --json", data="\n".join("e1/cloud-drive/" + k for k in keys) + "\n", check=False)
            listing = self.shell(alias + LINUX + "/bin/mc ls --recursive --json e1/cloud-drive").stdout.decode()
            present = {json.loads(line).get("key") for line in listing.splitlines() if line.startswith("{")}
            if present.intersection(keys): raise RuntimeError("Native test objects remain after scoped cleanup")
            for offset in range(0, len(keys), 500):
                quoted = ",".join("'" + k + "'" for k in keys[offset:offset+500])
                self.sql("DELETE c FROM file_db.object_cleanup c JOIN file_db.sys_file f ON c.object_key=f.object_key WHERE f.is_deleted=1 AND c.object_key IN (" + quoted + ")")
        owners = ",".join(str(int(f["userId"])) for f in fixtures)
        directories = ",".join(str(int(f["uploadDirectory"])) for f in fixtures)
        pending = self.sql("SELECT COUNT(*) FROM file_db.object_cleanup c JOIN file_db.sys_file f ON c.object_key=f.object_key WHERE f.user_id IN (" + owners + ") AND f.parent_id IN (" + directories + ")")
        if pending != "0": raise RuntimeError("Native experiment cleanup queue not empty")
        return dict(logical_files_deleted=count, object_keys_checked=len(keys), remaining_objects=0,
            removal_exit_code=removed.returncode if keys else 0, quota_restored=True, pending_cleanup=0, maintenance_outside_measurement=True)

    def cleanup_fixtures(self, fixtures):
        self.cleanup_uploads(fixtures)
        owners=','.join(str(int(f['userId'])) for f in fixtures)
        keys=self.sql('SELECT object_key FROM file_db.sys_file WHERE user_id IN ('+owners+') AND object_key IS NOT NULL').splitlines()
        keys=[k for k in keys if re.fullmatch(r'[0-9a-f-]{36}',k)]
        for f in fixtures:
            client=Client(self.base);client.login(f)
            client.data('/shares/'+f['shareId'],'DELETE')
            for name in ['fileId','largeFileId']:
                if f.get(name):client.data('/files/'+f[name],'DELETE')
            for item in client.data('/files?parentId='+f['listDirectory'])['items']:
                client.data('/directories/'+item['id'],'DELETE')
            for name in ['listDirectory','uploadDirectory','largeDirectory']:
                client.data('/directories/'+f[name],'DELETE')
            if client.data('/quota')['usedBytes']!=0:raise RuntimeError('Pilot quota cleanup failed')
            client.session.close()
        alias='source '+LINUX+'/runtime.env.sh; '+LINUX+'/bin/mc alias set e1 http://127.0.0.1:19000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" </dev/null >/dev/null; '
        if keys:
            self.shell(alias+LINUX+'/bin/mc rm --force --stdin --json',data='\n'.join('e1/cloud-drive/'+k for k in keys)+'\n',check=False)
            listing=self.shell(alias+LINUX+'/bin/mc ls --recursive --json e1/cloud-drive').stdout.decode()
            present={json.loads(x).get('key') for x in listing.splitlines() if x.startswith('{')}
            if present.intersection(keys):raise RuntimeError('Pilot objects remain')
            for offset in range(0,len(keys),500):
                quoted=','.join("'"+k+"'" for k in keys[offset:offset+500])
                self.sql('DELETE c FROM file_db.object_cleanup c JOIN file_db.sys_file f ON c.object_key=f.object_key WHERE f.is_deleted=1 AND f.user_id IN ('+owners+') AND c.object_key IN ('+quoted+')')
        return dict(accounts_retained=len(fixtures),active_files_and_directories=0,quota_bytes=0,experiment_objects_remaining=0)
