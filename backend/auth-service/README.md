# 课程版认证服务

独立 Maven 工程，构建目标 Java 17，Spring Boot 3.5.11 与 file-service 保持一致。
当前完成 plan 第 2.5 节第 1 项：独立构建、数据库配置、健康接口。
注册、登录、JWT 与基础资料已实现。
服务只扫描 `com.jiayuan.drive.auth`，不加载原单体、Redis、MinIO 或其他课程服务。

## 构建和运行

仓库根目录执行，宿主构建须先将 `JAVA_HOME` 指向 JDK 17：

```powershell
mvn -f backend/auth-service/pom.xml verify
# 在当前终端安全注入 AUTH_DB_PASSWORD，并配置实际 AUTH_DB_URL 后运行：
java -jar backend/auth-service/target/auth-service.jar
```

本机 Maven 默认 Java 25，已验证的 Java 17 构建路径为 Docker：

```powershell
docker run --rm --mount "type=bind,source=$((Get-Location).Path)\backend\auth-service,target=/workspace/auth-service" --mount type=volume,source=course-a-maven-cache,target=/root/.m2 -w /workspace maven:3.9.9-eclipse-temurin-17 mvn -B -f auth-service/pom.xml verify
docker build -f backend/auth-service/Dockerfile -t cloud-drive-auth:bootstrap backend
```

Dockerfile 使用 `backend/` 构建上下文，只复制认证工程源码，在构建阶段执行测试；运行阶段以 exec 形式启动 Java。
运行镜像不包含构建工具。总编排由 C、D 按既定分工接入，本服务不修改根 Compose。
Docker 运行时用 `--env AUTH_DB_PASSWORD` 等从当前进程传递配置，避免将真实凭证写在命令行或仓库中。

## 当前配置

| 环境变量/配置 | 必填性与默认值 | 单位及作用 |
|---|---|---|
| `SERVER_PORT` | 可选，8080 | HTTP 监听端口 |
| `AUTH_DB_URL` | 可选，见 application.yaml，连接 `mysql:3306/auth_db` | JDBC URL；UTC 会话；连接超时 3000 ms，socket 超时 5000 ms |
| `AUTH_DB_USER` | 可选，`auth_user` | 仅具备 auth_db 权限的数据库账户 |
| `AUTH_DB_PASSWORD` | 必填，无默认值 | 数据库密码，由环境注入 |
| Hikari connection/validation timeout | 固定 3000/1000 | ms；借用连接和校验连接的等待上限 |
| Hikari maximum-pool-size/minimum-idle | 固定 5/0 | 连接数；初始化失败不退出，按请求恢复连接 |
| JdbcTemplate query timeout | 固定 5 | 秒；后续业务查询的默认上限 |
| ready 查询超时 | 固定 2 | 秒；当前 `SELECT 1` 查询 |

覆盖 JDBC URL 时须保留有限的 `connectTimeout`、`socketTimeout` 与 UTC 配置。
本阶段不消费 JWT、内部令牌或其他服务的配置。数据库结构沿用 B 提供的
[auth_db.sql](../sql/course-mysql/schema/auth_db.sql)，本次未改表。

## 健康接口和开发验证

| 接口 | 成功 | 失败行为 |
|---|---|---|
| `GET /health/live` | HTTP 200，`{"status":"UP"}` | 不访问外部依赖 |
| `GET /health/ready` | 数据库 `SELECT 1` 成功时 HTTP 200/UP | 连接或查询失败时 HTTP 503，`{"status":"DOWN"}` |

健康响应不返回连接信息、异常详情或凭证。Hikari 日志关闭以避免连接池异常输出 JDBC URL；
数据库故障通过 ready 状态观察。ready 当前确认数据库可连接，不检查尚未实现的业务表映射。
恢复数据库后应用自行恢复，无需重启。健康路径由容器网络直接探测，前端 Nginx 不应转发。

`mvn verify` 包含 3 项 MVC 测试：live 不接触数据库；ready 在连接失败后恢复；
查询失败时释放借用的连接。以下真实 MySQL 自测要求 PowerShell 7、Docker Linux 引擎及已构建 jar：

```powershell
pwsh -NoProfile -File backend/auth-service/tests/health-smoke.ps1
# 验证从源码构建的镜像及其默认 ENTRYPOINT：
pwsh -NoProfile -File backend/auth-service/tests/health-smoke.ps1 -ApplicationImage cloud-drive-auth:bootstrap
```

脚本创建随机命名的独立网络和两个容器，MySQL 数据只写入临时内存文件系统，不使用课程卷，
仅将认证端口随机绑定至回环地址。测试先于数据库启动认证服务，再启动、停止、恢复测试数据库，
检查 200/503、响应时间和认证容器重启次数。凭证随机生成，不输出或落盘；结束清理仅限本次测试容器和网络。
这属于 A 的开发自测，正式故障实验由原分工执行。

2026-11-15 已验证：Maven 3.9.9 / Temurin 17.0.15 构建，Temurin JRE 17.0.21 运行，
MySQL 8.0.29；3 项测试通过，真实 MySQL 故障与恢复自测通过。
构建镜像 digest：`sha256:f58d59b6273e785ac0a4477f6e9b5ba1d7731c75b906c0f7b34076f1851318cc`；
运行镜像 digest：`sha256:0b6521287f850ec1c4b31c9074c5a1ae1d67c5922c3fefd21065c7c32e244d4a`。

## 个人账户注册

`POST /api/v1/auth/register` 接收 `accountName,password,nickname,email,accountType?`。
账户名 3–32 位英文字母数字下划线，密码 8–64 字符，昵称 1–32 字符，邮箱必填且最长 254 字符；
accountType 缺省为 personal，显式值只接受 personal。账户名和邮箱按小写保存。
成功为 HTTP 200 / `00000` / 空 data，格式错误 400 / `INVALID_REQUEST`，
账户重复 409 / `ACCOUNT_EXISTS`，邮箱重复 409 / `EMAIL_EXISTS`，数据库不可用 503 / `DEPENDENCY_UNAVAILABLE`。
密码先 SHA-256/Base64，再 BCrypt(12) 加随机盐，保存为 `{bcrypt-sha256}` 前缀的散列，
避免 BCrypt 72 字节上限截断 Unicode 密码；不兼容直接导入旧单体的 BCrypt 密码，本课程使用新 auth_db。
用户/账户同事务插入，唯一约束兜底并发冲突，不创建文件配额，不改 B 的建表 SQL。

开发自测：先执行 Maven verify，再在仓库根目录执行 `python backend/tests/course_smoke.py`。
脚本以随机凭证、独立网络和 tmpfs MySQL 初始化 B 的三库，运行 auth jar，完成字段校验、
账户名归一、邮箱重复、四并发同名注册、失败事务无孤立用户、强散列存储、跨库权限拒绝。
测试结束清理其专用容器/网络，不操作既有课程卷。2026-11-15 上述真实 MySQL 自测通过。
旧规范检查可在提供 javalang 的 Python 环境运行 `python backend/tests/check_course_style.py auth-service`；
本次明确覆盖 11 个 Java 文件，其中 2 个 record 被旧解析器跳过，其余无问题；record 由 Java 17 编译验证。

## 登录、JWT 与基础资料

`POST /api/v1/auth/login` 接收 `accountName,password`，成功返回 `token,userId,accountId,nickname,accountName`；
错误账户、密码、禁用账户统一 401 / INVALID_CREDENTIALS。`GET /api/v1/users/me` 需要 Bearer JWT，
只返回 `userId,accountId,nickname,accountName,email`，ID 为十进制字符串。非法 JWT 为 401 / UNAUTHORIZED。

JWT 配置 `JWT_SECRET`（必填，至少 32 个 UTF-8 字节）、`JWT_ISSUER`、`JWT_AUDIENCE`（均必填非空），
`JWT_TTL_SECONDS`（正整数秒，默认 7200）。HS256 签发 sub、accountId、iat、exp、iss、aud；
接受时钟偏差 0 秒，拒绝未来 iat、过期、缺失字段、错误签名/算法/发行者/受众。各服务本地验证，
退出由浏览器清除凭证，不提供即时吊销；B 文件服务在认证进程停止后仍接受未过期 JWT。
用户或账户 status=1 且 is_deleted=false 才允许新登录及资料读取；B 的本地 JWT 不实时查询禁用状态。
新账号密码散列格式同上，三个服务独立构建，不依赖共享 Maven 模块。

`python backend/tests/course_smoke.py --auth` 在注册回归后启动独立 B 文件服务/MinIO，
验证真实 JWT 访问 quota、错误凭证、最小资料、禁用账户，以及认证服务停止后的已有 JWT。
JWT 单测另覆盖篡改、过期、未来 iat、缺少 accountId/iat、错误 issuer/audience 和大整数 ID。

## 成品镜像运行交付

已补齐只依赖 JRE 的容器健康命令、APP_VERSION/INSTANCE_ID 与请求 ID 观测头、脱敏类别/状态/耗时日志。
Java 构建阶段 verify，运行阶段只带 jar/JRE/独立探测 class，Java 为 PID 1。
配置片段、镜像构建和实际成品自测见 [A 运行交付](../docker/a-services/README.md)。
2026-11-15 三个 A 镜像、Nginx 路由边界、真实 POST 下载 SHA-256 与日志检查通过。
