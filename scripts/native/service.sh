#!/bin/bash
set -euo pipefail
root=/opt/e1-native
source "$root/runtime.env.sh"
service=$1
case "$service" in mysql|minio|auth-service|file-service|share-service|frontend) ;; *) exit 2;; esac
group=/sys/fs/cgroup/cloud-drive-e1-native/$service
mkdir -p "$group"
echo $$ > "$group/cgroup.procs"
echo $$ > "$root/pids/$service.pid"
java=/opt/java/openjdk/bin/java
mysql_loader=("$root/mysql-image/lib64/ld-linux-x86-64.so.2" --library-path "$root/mysql-image/lib64:$root/mysql-image/usr/lib64/mysql/private")
nginx_loader=("$root/nginx-image/lib/ld-musl-x86_64.so.1" --library-path "$root/nginx-image/lib:$root/nginx-image/usr/lib")
interval=10
case "$service" in
  mysql)
    interval=5
    "${mysql_loader[@]}" "$root/mysql-image/usr/sbin/mysqld" --no-defaults \
      --basedir="$root/mysql-image/usr" --datadir="$root/data/mysql" --socket="$root/data/mysql/mysql.sock" \
      --pid-file="$root/data/mysql/mysqld.pid" --port=13306 --bind-address=127.0.0.1 --user=mysql \
      --mysqlx-port=13360 --mysqlx-bind-address=127.0.0.1 --mysqlx-socket="$root/data/mysql/mysqlx.sock" \
      --lc-messages-dir="$root/mysql-image/usr/share/mysql-8.0" --plugin-dir="$root/mysql-image/usr/lib64/mysql/plugin" \
      --secure-file-priv="$root/data/mysql-files" --skip-host-cache --skip-name-resolve --default-time-zone=+00:00 &
    ;;
  minio)
    interval=5
    "$root/bin/minio" server "$root/data/minio" --address 127.0.0.1:19000 --console-address 127.0.0.1:19001 &
    ;;
  auth-service)
    export SERVER_PORT=18081
    "$java" -jar "$root/apps/auth-service/app.jar" &
    ;;
  file-service)
    export SERVER_PORT=18082
    "${FILE_JAVA_HOME:-$root/apps/file-service/opt/java/openjdk}/bin/java" -jar "$root/apps/file-service/app/app.jar" &
    ;;
  share-service)
    export SERVER_PORT=18083
    "$java" -jar "$root/apps/share-service/app.jar" &
    ;;
  frontend)
    "${nginx_loader[@]}" "$root/nginx-image/usr/sbin/nginx" -p "$root/nginx/" -c "$root/nginx/nginx.conf" -g 'daemon off;' &
    ;;
esac
child=$!
echo "$child" > "$root/pids/$service.app.pid"
probe() {
  case "$service" in
    mysql) "$root/mysql-client.sh" -e 'SELECT 1 FROM file_db.schema_version WHERE version=1' >/dev/null 2>&1 ;;
    minio) curl -fsS --max-time 2 http://127.0.0.1:19000/minio/health/ready >/dev/null 2>&1 ;;
    auth-service) "$java" -cp /app/probe com.jiayuan.drive.auth.HealthProbe ;;
    share-service) "$java" -cp "$root/probe" com.jiayuan.drive.shares.HealthProbe ;;
    file-service) (exec 3<>/dev/tcp/127.0.0.1/18082; printf 'GET /health/ready HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n' >&3; read -r protocol status rest <&3; test "$status" = 200) ;;
    frontend) curl -fsS --max-time 3 http://127.0.0.1:18080/healthz >/dev/null 2>&1 ;;
  esac
}
(while kill -0 "$child" 2>/dev/null; do sleep "$interval"; probe >/dev/null 2>&1 || true; done) &
health=$!
cleanup() { kill -TERM "$child" "$health" 2>/dev/null || true; wait "$child" 2>/dev/null || true; }
trap cleanup EXIT
trap 'exit 0' TERM INT
wait "$child"
