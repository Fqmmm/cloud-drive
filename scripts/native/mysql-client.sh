#!/bin/bash
set -euo pipefail
root=/opt/e1-native
source "$root/runtime.env.sh"
export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"
database=(file_db)
if [[ ${1:-} == --bootstrap ]]; then unset MYSQL_PWD; database=(); shift
elif [[ ${1:-} == --init ]]; then database=(); shift; fi
exec "$root/mysql-image/lib64/ld-linux-x86-64.so.2" \
  --library-path "$root/mysql-image/lib64:$root/mysql-image/usr/lib64/mysql/private" \
  "$root/mysql-image/usr/bin/mysql" --no-defaults --protocol=socket \
  --socket="$root/data/mysql/mysql.sock" -u root -N -B "${database[@]}" "$@"
