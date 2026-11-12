# 课程版文件服务

使用 Java 17。仓库根目录执行 `mvn -f backend/file-service/pom.xml package` 单独构建。课程后端父工程和公共 JWT 模块由小组统一接入前，本模块按已定 JWT 契约独立验证，原后端的 Maven 入口仍可用。

## 本地联调

设置 MySQL 的四个密码、`MINIO_ROOT_USER`、`MINIO_ROOT_PASSWORD`、`JWT_SECRET`、`JWT_ISSUER`、`JWT_AUDIENCE`、`INTERNAL_API_TOKEN`。JWT 密钥按 UTF-8 原始字节使用，至少 32 字节，身份取 HS256 JWT 的 `sub`，同时检查 `accountId`、签发时间、过期时间、发行者与受众。内部令牌用独立值。随后在仓库根目录运行：

```powershell
docker compose -f backend/docker/file-service/compose.yaml up --build -d --wait
```

此配置供 B 独立联调。C 接入根编排时复用三个服务片段及两个命名卷。默认均使用容器网络。调试覆盖文件可绑定文件服务端口和 MinIO 控制台至本机回环地址。文件大小上限修改时同步调整 `MAX_REQUEST_SIZE` 与 Nginx 限制。

## MinIO 管理和恢复

文件服务自动准备专用私有桶 `cloud-drive`。既有同名桶若带公开策略，初始化时会清除桶策略。请给课程服务使用专用实例。默认固定发布标签，拉取后可用 `docker image inspect --format '{{json .RepoDigests}}' <镜像>` 记录 digest，再由 `MINIO_IMAGE` 指定经过验证的镜像引用。

用 `docker compose -f backend/docker/file-service/compose.yaml exec minio sh` 进入容器。以下命令在容器里执行，`KEY` 替换为 `file_db.sys_file.object_key`。不要把终端凭证记录到实验日志。

```sh
mc alias set course http://127.0.0.1:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"
mc stat --json "course/cloud-drive/$KEY"
mc ls --recursive --json course/cloud-drive > /tmp/object-list.jsonl
mc mirror course/cloud-drive /tmp/course-objects
```

备份时先停止业务写入，和 MySQL 导出使用同一批次。用 `docker compose cp` 将清单和备份目录复制到宿主机。恢复时用独立项目与新卷，启动文件服务准备桶后暂时停止业务写入，将备份复制到目标 MinIO 容器，再执行 `mc mirror /tmp/course-objects course/cloud-drive`。保留卷重建直接复用原 `minio_data`，恢复后用文件 API 下载并核对 SHA-256。

## 文件与对象状态

公开接口带 Bearer JWT。上传使用 multipart 字段 `file` 和查询参数 `parentId`，目录创建使用 JSON `{name,parentId}`，重命名使用 `{name}`。分享服务带 `X-Internal-Token` 调用 `GET /internal/v1/files/{id}?ownerId=…` 或同路径的 `/content`。详情响应以 `data.isDirectory` 标明目录，内容接口只接受活动普通文件。

同一用户的目录变更、配额和文件提交通过配额行锁串行化。文件流传输发生在事务之外。上传先登记待清理对象，提交成功时原子删除该登记。文件删除先让元数据失效并归还容量，再由后台清理对象。后台任务每 15 秒扫描一次，失败后至少等 1 分钟再试。此版本按方案以单实例运行。

在 `file_db` 中查看待清理记录或让指定对象立即进入下一轮重试：

```sql
SELECT object_key, reason, attempts, last_error, next_attempt_at FROM object_cleanup;
UPDATE object_cleanup SET next_attempt_at = CURRENT_TIMESTAMP WHERE object_key = '<对象键>';
```

对应脚本位于 [ops 目录](../sql/course-mysql/ops)。执行重试脚本前，在同一 MySQL 会话设置 `@object_key`。

MinIO 中断时仍可读取数据库里的文件列表，上传和下载报告依赖不可用，恢复后后台继续处理清理。详见 [MySQL 接入说明](../sql/course-mysql/README.md)。
