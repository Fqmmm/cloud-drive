# 课程版 MySQL 接入

## A、B、C 的接口约定

- 文件服务在容器内监听 `8080`，本地验证 A 的 JWT，从已验证的用户 ID 判断文件归属。用户 ID、账户 ID 和文件 ID 在 SQL 中使用有符号 `BIGINT`，JSON 用十进制字符串传输，避免前端精度损失。
- 公共文件接口为 `/api/v1/files`、`/api/v1/directories` 和 `/api/v1/quota`。普通响应使用 `{code, msg, data}`，下载返回文件流。分享服务通过 `/internal/v1/files/{id}` 和 `/internal/v1/files/{id}/content` 传入 `ownerId`，请求携带独立配置的 `X-Internal-Token`。Nginx 仅转发公共接口。
- 文件服务连接 `mysql:3306/file_db` 和 `http://minio:9000` 的私有桶 `cloud-drive`。`DEFAULT_QUOTA_BYTES` 默认 `10737418240`，`MAX_FILE_BYTES` 默认 `104857600`。Nginx 和 Spring 的整请求上限须为 multipart 开销留出余量。

## 启动与交接

为 `MYSQL_ROOT_PASSWORD`、`AUTH_DB_PASSWORD`、`FILE_DB_PASSWORD` 和 `SHARE_DB_PASSWORD` 设置各自的环境值。从仓库根目录执行以下命令可单独启动数据库。

```powershell
docker compose -f backend/docker/mysql/compose.yaml up -d --wait
```

Compose 片段暂用原仓库的 `mysql:8.0.29`。联调验证后可通过 `MYSQL_IMAGE` 固定为带 digest 的引用。应用账号分别为 `auth_user`、`file_user` 和 `share_user`，每个账号只具备所属库的 CRUD 权限。MySQL 默认使用 UTC，应用的数据库会话也应使用 UTC。

C 接入根目录 Compose 时，从根目录解析两个挂载路径 `./backend/sql/course-mysql/init` 和 `./backend/sql/course-mysql/schema`，保留 `mysql_data:/var/lib/mysql` 和健康检查，并让三个业务服务等待 `mysql` 达到 `service_healthy`。独立调试和整套部署要复用已有卷时，使用相同项目名和卷名。

## 表结构和版本

- `auth_db.sql` 与 `share_db.sql` 是按现有代码和课程需求整理的初版，待 A 在服务落地时核对映射与字段。`file_db.sql` 由 B 维护。
- `sys_file.object_key` 直接保存一对一对象映射，目录的键为空。活动名称唯一索引覆盖文件和目录，删除后可以重用名称。排序规则区分大小写和重音。`user_quota` 按用户唯一，容量按字节计。`object_cleanup` 按对象键跟踪待清理记录，也能登记数据库提交失败后留下的对象。
- 空卷按建库授权、导入三库、检查表、记录版本 1 的顺序初始化。保留卷重建时，MySQL 会复用现有数据。已有课程卷后续升级时，停写并备份，先核对 `file_db.schema_version`，按版本顺序以运维账号执行对应迁移，校验后登记目标版本。当前只有版本 1。旧项目整库数据若要导入，应先备份并按业务表和对象键映射单独迁移。
