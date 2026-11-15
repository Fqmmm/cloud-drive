# A 开发与 AB 验收记录

日期：2026-11-15。执行范围为 A 的 frontend、auth-service、share-service 和必要的 B 接口联调。
A 功能与运行交付完成，真实 AB 开发核验通过。C、D 的根编排、正式实验、实验数据与报告未执行；未合并 main。

## 1. 环境与版本

| 项目 | 实际验证环境 |
|---|---|
| 宿主 | Windows 11 / PowerShell 7，Docker Desktop 4.50.0 / Linux Engine 28.5.1，context=desktop-linux |
| Java 构建/运行 | Maven 3.9.9 / Temurin 17.0.15 构建，Temurin JRE 17.0.21 运行；宿主默认 Java 25 未改动 |
| Java 工程 | 三个独立 Maven 工程；Spring Boot 3.5.11；JWT 0.12.6；源码编译目标 Java 17 |
| 前端 | Node 24.11.0 / pnpm 10.32.1，提交 pnpm-lock.yaml；Nginx 1.28.3 |
| 浏览器 | Playwright 1.65.1 / Chromium 159，替身 API 与真实后端用例分开执行 |
| 数据库 | MySQL 8.0.29，B 的三库初始化脚本，UTC 会话与各库独立账号 |
| 存储 | MinIO RELEASE.2025-09-07T16-13-09Z，本机固定身份标签，详见运行交付说明 |
| 测试隔离 | 随机容器名和独立网络、回环随机端口、tmpfs MySQL/MinIO；未操作已有课程卷 |

构建基础镜像 digest 在 Dockerfile 固定。最终浏览器使用 cloud-drive-auth:course、cloud-drive-share:course、
cloud-drive-file:course、cloud-drive-frontend:course 的实际源码镜像，MySQL 与已验证的 MinIO 镜像，共六个容器。
测试完成后专用容器和网络已清理，Maven 依赖缓存保留，无业务数据。

## 2. 检查与实际结果

命令除前端检查外均从仓库根目录执行；Maven 在 Java 17 构建容器内执行。

| 验证 | 命令/范围 | 结果 |
|---|---|---|
| 独立构建 | `mvn -f backend/auth-service/pom.xml verify`，share/file 对应工程；A 镜像构建阶段执行相同检查 | 通过；auth 5 项、share 6 项测试，file 无单元测试，其业务证据来自真实接口核验 |
| 前端静态与构建 | frontend 中 `pnpm exec vue-tsc --noEmit`、`pnpm exec vite build`；课程改动 ESLint/Prettier/Stylelint | 通过；保留 Element Plus 大 chunk 提示 |
| 前端浏览器契约 | `pnpm exec playwright test --config playwright.course.config.ts` | 8 项替身 API 测试通过；最后错误码调整后补跑 3 项分享测试通过 |
| 认证/文件/分享 API | `python -u backend/tests/course_smoke.py --shares` | 真实双用户/匿名 API 正反向闭环通过 |
| JWT 互操作 | `python -u backend/tests/jwt_contract.py` | 12 组请求三服务结果一致：合法 200；未来 iat、exp 早于 iat、过期、错 issuer/audience、缺字段、非法 ID/算法均 401 |
| 健康与依赖 | `health_smoke.ps1`，auth 兼容入口及 `backend/tests/health_smoke.ps1 -Service share-service` | 数据库未启动/停止时 live 200，ready 约 3 秒返回 503；恢复后自行就绪，无应用重启 |
| A 成品镜像 | A 三镜像源码 build、`nginx -t`、`python -u backend/tests/runtime_smoke.py` | 健康命令、完整 API 路径/查询、内部/后台健康/未知 API 404、观测头、POST SHA-256、日志脱敏通过 |
| 故障钩子 | 上述成品镜像开发契约检查 | 默认路由不存在；启用后错凭证 403、正确凭证 JVM 退出 17；Nginx 始终拒绝内部路径；未进行正式恢复测量 |
| 开发配置 | `docker compose --env-file backend/docker/a-services/.env.example -p course-a-dev-check -f backend/docker/a-services/compose.yaml config --quiet` | 通过；未把配置校验当作正式 Compose 部署验收 |
| 最终真实浏览器 | `python -u backend/tests/ab_browser.py` | 1 条完整 Chromium 业务链路通过（最后一轮 8.1 秒）；后置数据库和存储恢复检查通过 |

### 真实浏览器样本及断言

使用两个临时个人账户和独立匿名浏览器上下文。用户 ID、账户 ID、目录 ID 从 `9007199254740993` 起，
验证 JSON 字符串不会被 JavaScript 数值精度破坏。文件为 65536 字节确定性二进制，初始名称含中文和空格。
样本 SHA-256：`4b640d85ab3ba30fd02c9fc9db4a8928f416322ad27022ea58a65aaee68a4df2`。

- UI 注册、登录、刷新、退出；根目录和面包屑、新建目录、容量可用。
- 上传、本人下载、重命名；本人、公开分享、提取码分享三次下载的 SHA-256 均等于样本值。
- 第二用户浏览他人目录、下载、重命名、删除、创建分享均 404。
- 公开/保护分享创建；保护分享验证前无文件详情，错码留在匿名页；verify 后换错码下载仍拒绝。
- 文件/目录重命名后原分享仍指向同一文件，下载取当前名称，本人列表保持创建时名称快照。
- 非空目录删除拒绝；取消一个分享不影响另一个；永久删除源文件后有效保护分享提示文件失效，无下载入口。
- 最终两用户 usedBytes 合计 0，活动文件/目录 0，两个分享历史记录保留；浏览器 API 请求始终同源。
- 三个服务账号各自读取本库成功，查询其他两个库均被拒绝。
- 额外临时存储样本验证：MinIO 中断时下载/上传 503，失败上传不增加容量；删除立即扣额并持久登记清理。
  恢复后依照 B 已有重试 SQL 处理测试记录，清理队列归零，容量保持 0。

API 开发自测还覆盖并发注册仅一次成功、失败注册无孤立用户、邮箱/账户重复、禁用账户、密码散列、
认证进程停止后已有 JWT 可用、同名冲突、单文件 413、1 MiB 配额下三个并发 400000 字节上传仅两个成功、
重复删除不重复扣额、提取码共用错误窗口/正确码绕过、取消/过期/文件失效检查顺序和文件依赖恢复。

## 3. 联调差异与恢复

1. 文件服务 JWT 原先接受未来 iat 或 exp 早于 iat，而 auth/share 拒绝。已以两项条件最小修复，
   正常令牌兼容，HTTP/业务码、SQL 和路径均未改变；提交 `d32a17f`。
2. 文件服务重复删除已失效记录返回 404，与其既有“不可见资源 404”规则一致。验证配额不重复扣减，未改业务契约。
3. Quay 固定 MinIO 标签返回 401，Docker Hub 同发布标签也拒绝拉取。远端问题仍存在；本机同版本缓存已核验并固定标签，
   A 开发配置使用已有 MINIO_IMAGE 覆盖。纯镜像离线归档和 SHA-256 已导出到忽略目录，新机器可导入；提交 `0972227`。
4. Docker Desktop 曾停止，正常 start 恢复；测试重启容器可能改变随机宿主端口，脚本已重读端口。
5. Windows GBK 不能输出 Playwright 符号，真实浏览器包装器已使用 UTF-8，并在输出前脱敏。

## 4. 检查范围与限制

课程前端只加载 src/course 和课程入口；原完整源码保留但不在运行链路或本轮类型检查范围。
全量旧前端自定义检查仍有 11 项遗留错误，位于未改动的旧 BpmnViewer/share/config/invitation/team 页面；
新增课程目录无自定义检查问题，未新增忽略规则掩盖旧问题。

后端旧规范工具通过 `check_course_style.py` 明确固定服务根路径；auth 16 个、share 19 个、file 7 个 Java 文件，
各有 3 个文件因 javalang 不支持 record/text block 等语法而跳过，其余未报问题。
Java 17 构建覆盖全部源码；不能将旧规范零退出码等同于全部源码均被规则解析。

ready 确认本库连接，不执行表结构/迁移版本校验。错码限制按 token、按实例统计，不提供跨副本累计锁定。
退出不即时吊销 JWT，未过期凭证按两小时基线继续有效。上述均与课程需求约定一致。
本轮未做正式性能/扩容/故障恢复/持久化实验，不替代 C、D 的验收和实验交付。

## 5. 接手入口

最新进度与逐功能提交索引见 [ab-progress.md](ab-progress.md)，构建与本机/离线启动方法见
[A 运行交付](../backend/docker/a-services/README.md)。主分支合并仍需用户另行授权。
