#!/bin/bash
# The MySQL entrypoint can source non-executable .sh files.
(
set -euo pipefail

: "${AUTH_DB_PASSWORD:?set AUTH_DB_PASSWORD}"
: "${FILE_DB_PASSWORD:?set FILE_DB_PASSWORD}"
: "${SHARE_DB_PASSWORD:?set SHARE_DB_PASSWORD}"

mysql_root() {
    MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --protocol=socket -u root --binary-mode
}

create_database_and_user() {
    local database="$1" username="$2" password="$3"
    # NO_BACKSLASH_ESCAPES makes doubled quotes the only escaping needed here.
    password=${password//\'/\'\'}
    printf "CREATE DATABASE \`%s\` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_as_cs;\n" "$database"
    printf "CREATE USER '%s'@'%%' IDENTIFIED BY '%s';\n" "$username" "$password"
    printf "GRANT SELECT, INSERT, UPDATE, DELETE ON \`%s\`.* TO '%s'@'%%';\n" "$database" "$username"
}

{
    printf "SET SESSION sql_mode = 'NO_BACKSLASH_ESCAPES';\n"
    create_database_and_user auth_db auth_user "$AUTH_DB_PASSWORD"
    create_database_and_user file_db file_user "$FILE_DB_PASSWORD"
    create_database_and_user share_db share_user "$SHARE_DB_PASSWORD"
} | mysql_root 2>/dev/null || { echo 'Course database or account initialization failed.' >&2; exit 1; }

for schema in auth_db file_db share_db; do
    mysql_root < "/opt/course-schema/$schema.sql"
done

mysql_root <<'SQL'
SELECT 1 FROM auth_db.sys_user LIMIT 0;
SELECT 1 FROM auth_db.sys_account LIMIT 0;
SELECT 1 FROM file_db.sys_file LIMIT 0;
SELECT 1 FROM file_db.user_quota LIMIT 0;
SELECT 1 FROM file_db.object_cleanup LIMIT 0;
SELECT 1 FROM share_db.sys_share LIMIT 0;
CREATE TABLE file_db.schema_version (
    version INT PRIMARY KEY,
    applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;
INSERT INTO file_db.schema_version (version) VALUES (1);
SQL
)
