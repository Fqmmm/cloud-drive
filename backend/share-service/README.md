# 课程版分享服务

独立 Java 17 / Spring Boot 3.5.11 Maven 工程，只加载 com.jiayuan.drive.shares。
当前完成独立构建、配置、健康接口和文件元数据客户端；分享创建、本人列表和取消已实现，匿名访问与流式下载已实现。

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
不进行自动重试；文件正文采用有界读取超时的流式转发，不将整文件装入 Java 堆。

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

## 匿名分享和下载

`GET /api/v1/s/{token}`：公开分享返回详情；提取码分享只返回 requiresCode=true、到期时间和空文件详情。
`POST /api/v1/s/{token}/verify`：请求体 extractCode 为字符串，公开分享允许空体；成功返回 fileName/fileSize/expireTime/requiresCode。
`POST /api/v1/s/{token}/download`：自身重新执行全部检查，不认可先前 verify 为长期授权，成功为二进制。
检查顺序固定为不存在、取消、过期、提取码、文件；错误码按 docs/phase1/share-service.md，不使用 401 表示错码。

提取码错误仅在当前实例、当前分享 token 计数；SHARE_CODE_MAX_FAILURES 默认 5，
SHARE_CODE_WINDOW_SECONDS 默认 60 秒（1–86400）。verify/download 共用计数，前 5 次错码 403，随后 429；
窗口结束重置；正确码和公开请求不受错误次数限制。多副本不提供全局累计锁定。
FILE_CONTENT_TIMEOUT_MS 默认 120000 ms；连接仍默认 3000 ms，元数据默认 5000 ms。
下载前核对文件活动状态；正文通过受信内部凭证转发，保留受控下载文件名，不暴露私有地址。
浏览器断开时关闭下游连接；输出开始后中断连接，不把 JSON 拼到二进制末尾，不自动重放。
取消/删除阻止后续请求，已开始传输按当前连接结束。

`python -u backend/tests/course_smoke.py --shares` 验证完整 API 开发闭环。
Java 17 verify 共 6 项测试，增加错码窗口与重置；现代语法导致旧规范 16 文件中 3 文件跳过，余下无问题。

2026-11-15 完整匿名分享 AB 自测通过：错码/正确码/限流、POST 流式 SHA-256、权限替换拒绝、取消/过期/源文件失效和依赖恢复；独立测试容器不使用既有课程卷。

## 成品镜像运行交付

已补齐只依赖 JRE 的容器健康命令、APP_VERSION/INSTANCE_ID 与请求 ID 观测头、脱敏类别/状态/耗时日志。
Java 构建阶段 verify，运行阶段只带 jar/JRE/独立探测 class，Java 为 PID 1。
配置片段、镜像构建和实际成品自测见 [A 运行交付](../docker/a-services/README.md)。
2026-11-15 三个 A 镜像、Nginx 路由边界、真实 POST 下载 SHA-256 与日志检查通过。
