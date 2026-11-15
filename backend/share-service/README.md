# 课程版分享服务

独立 Java 17 / Spring Boot 3.5.11 Maven 工程，只加载 com.jiayuan.drive.shares。
当前完成独立构建、配置、健康接口和文件元数据客户端；分享创建、本人列表和取消已实现，匿名访问将在下一功能接入。

```powershell
mvn -f backend/share-service/pom.xml verify
docker build -f backend/share-service/Dockerfile -t cloud-drive-share:course backend
pwsh -NoProfile -File backend/tests/health_smoke.ps1 -Service share-service
```

宿主 Java 默认 25，本轮在已验证的 Maven 3.9.9 / Temurin 17 构建容器执行 verify。
构建与运行基础镜像固定为认证服务相同的已验证 digest，backend/ 为构建上下文。
数据库配置 SHARE_DB_URL/SHARE_DB_USER/SHARE_DB_PASSWORD 对应 auth-service 的数据库配置，
默认 mysql:3306/share_db、share_user，密码必填；UTC，连接 3000 ms、socket 5000 ms，Hikari 借用 3000 ms。
SERVER_PORT 默认 8080。live 为 200/UP，ready 在本库 SELECT 1 成功时 200/UP，失败 503/DOWN，
不以文件服务状态决定就绪。数据库恢复后自行重连，健康响应不暴露连接和凭证。

| 配置 | 必填/默认 | 单位和作用 |
|---|---|---|
| FILE_SERVICE_URL | 默认 http://file-service:8080 | HTTP 基础地址，禁止 userinfo/query/fragment，不跟随重定向 |
| INTERNAL_API_TOKEN | 必填非空，必须不同于 JWT_SECRET | 只经 X-Internal-Token 传递，不向浏览器暴露 |
| JWT_SECRET | 必填 | 至少 32 个 UTF-8 字节，与认证/文件服务相同 |
| FILE_CONNECT_TIMEOUT_MS | 默认 3000，正整数 | ms，文件 HTTP 连接上限 |
| FILE_METADATA_TIMEOUT_MS | 默认 5000，正整数 | ms，元数据读取上限 |

元数据读取只调用内部文件 HTTP 接口，限定 ownerId/fileId 为正数十进制 BIGINT，
复核响应 ID/归属/类型/大小，限制 JSON 为 64 KiB。下游 404 映射 SHARE_FILE_UNAVAILABLE，
其他失败、错凭证、错误结构、连接故障映射 503/DEPENDENCY_UNAVAILABLE；不返回下游原始正文。
本阶段不进行自动重试；传输与提取码功能将在后续提交接入。

2026-11-15 Java 17 verify 的 5 项测试通过：健康独立、恢复与连接释放，内部凭证传递、归属复核、
404/503 映射及不可达依赖有界失败。旧规范明确扫描 8 Java 文件，ApiResult record 跳过，其余无问题。
共享健康自测脚本位于 backend/tests/health_smoke.ps1，原 auth 脚本改为兼容入口，命令保持可用。

真实 MySQL 健康自测通过：ready 在数据库未启动和中断时分别 3.15/3.11 秒返回 503，live 不受影响，恢复后自动返回 200，应用无重启。

## 分享管理

`POST /api/v1/shares`（JWT）接收 fileId 字符串、accessType 0/1、expireDays 1/7/30/null。
创建前核验文件归属和普通文件类型。返回 id/shareToken/shareUrl/extractCode/expireTime，
提取码为固定六位数字字符串，仅在创建时返回一次；数据库保存 BCrypt(12) 随机盐散列。
分享 token 使用 SecureRandom 的 128 位随机数和 Base64url，数据库唯一索引兜底。
`PUBLIC_BASE_URL`（默认 http://localhost:8080，无凭证/query/fragment）生成 `/#/s/{token}` 的 hash 前端链接。

`GET /api/v1/shares` 返回本人记录，包含 id/fileId/fileName/shareToken/shareUrl/accessType/expireTime/createTime/status，
不返回提取码或散列；状态 ACTIVE/CANCELLED/EXPIRED，文件名为创建快照，源文件状态在实际访问时核验。
`DELETE /api/v1/shares/{id}` 仅取消本人记录，重复取消 200，越权或不存在 404 / SHARE_NOT_FOUND。
SQL status=0 表示未取消、1 表示取消，过期由 UTC expire_time 比较，不改变 B 初版表结构。
同一文件可多次分享，取消以分享 ID 为单位。列表和取消不访问文件服务，ready 只检查 share_db。

JWT 验证与 auth-service 对齐（HS256、UTF-8 原始密钥、sub/accountId/iat/exp/iss/aud、0 秒偏差、未来 iat 拒绝），
由 JWT_SECRET/JWT_ISSUER/JWT_AUDIENCE 配置；分享服务不提供签发入口、不查询 auth_db。
`python -u backend/tests/course_smoke.py --share-management` 执行真实 AB 开发自测，包含前序认证/文件回归。

2026-11-15 分享管理真实 AB 自测通过，涵盖归属、目录拒绝、快照、散列、过期、本人列表、重复取消及下游停机隔离；旧规范 12 文件中 2 文件因现代语法跳过，其余无问题。
