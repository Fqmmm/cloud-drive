# A 独立运行与 AB 开发联调

此目录交付 A 的 auth-service、share-service、frontend 配置，复用 B 的局部文件/MySQL/MinIO 配置。
这是独立开发联调入口，未修改根 Compose；C、D 仍负责正式整体编排、实验脚本、数据和报告。

从仓库根目录执行，先确认 Docker context 为 desktop-linux，并核对项目/卷，避免复用他人数据：

```powershell
docker context show
docker compose ls
docker volume ls
pwsh -NoProfile -File backend/docker/a-services/prepare-minio.ps1
Copy-Item backend/docker/a-services/.env.example backend/docker/a-services/secrets.local
# 在本机编辑 secrets.local，替换所有凭证，PUBLIC_BASE_URL 与 A_DEV_HTTP_PORT 对应。
docker compose --env-file backend/docker/a-services/secrets.local -p course-a-dev -f backend/docker/a-services/compose.yaml config --quiet
docker compose --env-file backend/docker/a-services/secrets.local -p course-a-dev -f backend/docker/a-services/compose.yaml up --build -d --wait
```

`*.local` 已忽略。不要将实际环境文件、完整 `compose config` 输出或 inspect 环境变量输出提交/分享。
项目名 course-a-dev 使 MySQL/MinIO 命名卷与原项目隔离；默认仅 frontend 的 8080 绑定至宿主回环地址。
停止使用 `docker compose ... down`，保留数据卷；清空数据库或删除卷另行取得针对对象的明确授权。

三个 A 镜像都从源码构建。Java 构建时 verify，JRE 运行且 Java 为 PID 1；独立 HealthProbe 类只依赖 JRE，
探测 localhost 的 /health/ready，不要求 curl/bash。前端在 Node 24.11.0 / pnpm 10.32.1 下锁定依赖、
顺序进行类型检查与构建，Nginx 1.28.3 仅携带静态产物；healthz 由镜像中的 wget 探测。
基础镜像均固定实际验证的 digest，具体见 Dockerfile。修改 MAX_FILE_BYTES 时，前端构建参数自动同步，
同时按 B README 调整 MAX_REQUEST_SIZE；Nginx 当前整请求上限为 105 MiB，大于基线 100 MiB 单文件。

## 路由、恢复与观测

- Nginx 精确匹配 auth/users、files/directories/quota、shares 和 s 路径，完整保留 /api/v1 和查询参数。
- /internal、后台 /health 与未知 /api 路径返回 404，不回退到 SPA；页面 /healthz 为静态 200。
- Docker DNS 每 5 秒更新解析，后端重建后无需固定容器 IP；若排查部署问题，可显式 reload Nginx。
- 连接超时 3 秒，普通读取 15 秒，上传/下载读取和发送 120 秒；下载关闭代理缓冲。
- APP_VERSION（Compose 中 AUTH_APP_VERSION / SHARE_APP_VERSION）默认 course-v1，INSTANCE_ID 缺省采用容器 HOSTNAME。
  值限制为 1–80 位字母数字、点、下划线、连字符；响应带 X-App-Version、X-Instance-Id、X-Request-Id。
- A 请求日志记录安全请求 ID、类别、HTTP 状态、耗时和实例；分享下游记录操作类别/耗时。Nginx 访问日志无 URL、query、body 或授权头，
  error 日志限定 crit，避免常见代理错误输出完整分享 token。凭证和完整分享地址不进入日志。

## 故障入口与开发验证

share-service 默认无 /internal/test/exit 路由。仅 EXPERIMENT_FAULTS_ENABLED=true 时注册 POST 路由，
校验 X-Internal-Token 后记录请求 ID 并以 17 终止 JVM；错误凭证 403。Nginx 始终阻断内部路径。
正式退出/恢复测量及工具容器调用按刘骐语的实验方案执行，结束关闭开关。

```powershell
docker build -f backend/auth-service/Dockerfile -t cloud-drive-auth:course backend
docker build -f backend/share-service/Dockerfile -t cloud-drive-share:course backend
docker build -t cloud-drive-frontend:course frontend
docker run --rm --entrypoint nginx cloud-drive-frontend:course -t
python -u backend/tests/runtime_smoke.py
```

2026-11-15 上述三个源码镜像构建、Nginx -t 和成品镜像自测通过。开发 Compose 的 config --quiet 通过，
本轮成品验收使用独立 Docker 网络/tmpfs 数据库/存储，未将开发 Compose 启动记录当作正式六容器编排验收。
自测覆盖三个健康命令、路径/查询转发、内部/健康/未知 API 阻断、观测头、POST 下载 SHA-256、
默认关闭/错误凭证/启用后的退出码 17，以及内存中检查日志不含本次凭证、JWT、分享 token 和提取码。
只进行一次故障钩子契约检查，未采集正式恢复时间或实验数据。测试容器和网络已清理，未操作现有课程卷。

## MinIO 镜像来源恢复

2026-11-15 实测：B 配置中的 Quay 固定标签返回 401，Docker Hub 同发布标签也拒绝拉取。
本机缓存的 minio/minio:latest 经 `--version` 确认恰为 B 指定的 RELEASE.2025-09-07T16-13-09Z，
镜像 ID/本机 RepoDigest 为 `sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e`。
prepare-minio.ps1 仅接受这个不可变身份，核验版本，再创建明确的 `cloud-drive-minio:release-2025-09-07` 本机标签。
A 的示例通过 B 已有 MINIO_IMAGE 配置覆盖来源，不修改 B 默认配置、存储协议或既有容器/数据卷。
开发 API 自测使用相同标签，可用 COURSE_TEST_MINIO_IMAGE 显式覆盖测试镜像。

```powershell
# 本机已有已验证缓存时：
pwsh -NoProfile -File backend/docker/a-services/prepare-minio.ps1
# 导出镜像本身用于其他开发机器；不导出运行容器或业务数据：
pwsh -NoProfile -File backend/docker/a-services/prepare-minio.ps1 -Export -ArchivePath <new-archive-path>
# 其他开发机先核对随附 .sha256，再导入：
pwsh -NoProfile -File backend/docker/a-services/prepare-minio.ps1 -ArchivePath <verified-archive-path>
```

本机已保留被 Git 忽略的 `artifacts/minio-release-2025-09-07.tar` 和 `.sha256`：
归档 SHA-256 为 `42de43b672a8322db7e9d69d6f3aeb93e6cc19acf761f4678075590549aca567`。
真实本机标签启动、B 的 curl readiness 命令和归档重载均已验证通过。
远端拉取拒绝尚未消失；新机器可用此已验证归档恢复，不能将本机恢复描述为远端权限已恢复。

完整真实浏览器验收由 `python -u backend/tests/ab_browser.py` 执行，须先构建 cloud-drive-file:course；两个用户、匿名访问、下载哈希、权限、最终配额及存储恢复已通过，详见 [AB 验收记录](../../../docs/ab-validation.md)。
