# 课程版文件服务

使用 Java 17。仓库根目录执行 `mvn -f backend/file-service/pom.xml package` 单独构建。课程后端已确认采用三个独立 Maven 工程，JWT 按统一契约实现并验证互操作。原后端的 Maven 入口保留供原单体使用，课程构建约定见 [总体方案](../../docs/plan.md#24-工程拆分与构建边界)。

## 本地联调

设置 MySQL 的四个密码、`MINIO_ROOT_USER`、`MINIO_ROOT_PASSWORD`、`JWT_SECRET`、`JWT_ISSUER`、`JWT_AUDIENCE`、`INTERNAL_API_TOKEN`。JWT 密钥按 UTF-8 原始字节使用，至少 32 字节，身份取 HS256 JWT 的 `sub`，同时检查 `accountId`、签发时间、过期时间、发行者与受众。内部令牌用独立值。随后在仓库根目录运行：

```powershell
docker compose -f backend/docker/file-service/compose.yaml up --build -d --wait
```

此配置供 狄东琛 独立联调。范骐鸣 接入根编排时复用三个服务片段及两个命名卷。默认均使用容器网络。调试覆盖文件可绑定文件服务端口和 MinIO 控制台至本机回环地址。文件大小上限修改时同步调整 `MAX_REQUEST_SIZE` 与 Nginx 限制。

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

2026-11-17 刘骐语的无故障诊断观察到下载 503，日志定位为打开 MinIO 对象流时的 IOException。下载改用独立 GET 客户端，启用响应头前的连接恢复；上传客户端保持原设置。对象流返回应用后不重放，部分传输中断仍报错。新增两项测试分别模拟复用连接失效和部分响应中断，实际容器验证保存到诊断批次。这不调整授权、对象键、容量、SQL 或外部 API。

下载异常只记录经校验的请求 ID、阶段和异常类别，不记录对象键、URL 或凭证。分享服务向文件服务透传请求 ID，Nginx 在响应头回传其生成的 ID，探针据此关联实际服务记录。

## AB JWT 时间契约核验

2026-11-15 A 联调发现文件服务曾接受未来 iat，以及 exp 早于 iat 但尚未过期的签名令牌，
而 auth/share 已拒绝。已最小补齐 iat 不晚于当前时刻、exp 必须晚于 iat，三者时钟偏差统一为 0 秒。
正常 auth-service 签发的 HS256 JWT 不受影响；非法令牌继续统一 401/UNAUTHORIZED，公共路径和 SQL 不变。
`python -u backend/tests/jwt_contract.py` 用独立测试网络比较三个服务的正常、时间、身份、发行者、受众、算法行为，
不输出令牌。file-service 独立 verify 本身没有单元测试，实际业务证据以这组真实接口检查为准。

2026-11-15 AB 环境发现固定 MinIO 标签的远端拉取拒绝，本机同版本缓存可用。A 提供经过身份核验的本机标签与离线镜像恢复方法，见 [A 运行交付](../docker/a-services/README.md#minio-镜像来源恢复)；未修改 B 默认配置或现有数据卷。
