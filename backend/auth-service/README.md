# 课程版认证服务

独立 Maven 工程，构建目标 Java 17，Spring Boot 3.5.11 与 file-service 保持一致。
当前完成 plan 第 2.5 节第 1 项：独立构建、数据库配置、健康接口。
注册、登录、JWT 和基础资料将在后续功能提交中实现；目前没有业务 API。
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
