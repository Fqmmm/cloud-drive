#!/bin/sh
# Read-only host-captured database evidence. Never print passwords or row data.
set -eu
MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -u root -N -B <<'SQL'
SELECT JSON_OBJECT(
  'name_collation', (SELECT COLLATION_NAME FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA='file_db' AND TABLE_NAME='sys_file' AND COLUMN_NAME='active_name'),
  'cleanup_count', (SELECT COUNT(*) FROM file_db.object_cleanup));
SQL
