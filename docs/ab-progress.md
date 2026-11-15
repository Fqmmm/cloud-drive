# A 开发与 AB 联调交接记录

更新时间为 2026-11-15。记录依据本地仓库核对结果，后续接手先重新检查 Git 和环境，再更新此文件。

## 1. 任务和已确认决定

项目路径为 `D:\Secret\Courses\Sem5\CCVT\PJ\cloud-drive`，课程选题指南在上一级 `26-27秋季学期_云计算与虚拟化技术课程设计Project.pdf`。

选题为第 12 题，基于 Docker Compose 构建多服务微服务应用并一键部署。原软件工程网盘作为改造基础，课程版保留个人账户、个人文件和单文件分享，目标为 frontend、auth-service、file-service、share-service、mysql、minio 六个容器。

用户为 A（肖国扬），负责 frontend、auth-service、share-service。B（狄东琛）已提交 file-service、MySQL、MinIO 的实现。当前仅做 A 开发和必要的 AB 联调。C、D 的整体编排、实验脚本、原始数据、正式实验和报告按原分工负责。

用户已明确接受以下决定，无需重复征询。

- 三个课程后端采用独立 Maven 工程，与 B 当前结构一致。原 `backend/pom.xml` 保留作为旧单体入口。
- 按功能开发、验证、更新文档，然后单独 commit 和 push，再进入下一功能。避免一次提交或推送多个积攒的功能。
- 使用开发分支，合并主分支另按用户授权。已授权开展 A 部分开发和按功能推送。
- 原网盘功能精简为个人账户、个人文件、固定配额、单文件分享。团队、邀请、会员、私密空间、回收站、Flowable、Redis、SSE 等不在首版范围。

## 2. Git 实际状态

- 当前开发分支：`feat/share-management`，从已推送的 `f02c0bb` 创建。
- `5f66bab`（工作规范和计划）和 `20e8b7f`（独立交接文档）已依次推送至 `origin/course/a-services`。
- 本功能提交包含 auth-service 骨架及对应 README、接口进度、分支命名规范和本文。最终提交号和上游状态以 `git log -1`、`git status --short --branch` 核对，避免文档自引用提交号。
- 远端：`https://github.com/Fqmmm/cloud-drive.git`。未合并 main，未重写历史，未改动 B 的 SQL 或服务。
- 后续新分支按用户要求使用类型与简短说明，如 `feat/auth-service-bootstrap`、`fix/download-errors`。Git 名称不支持空格，说明用连字符。

## 3. 当前阶段及实际验证

plan 第 2.5 节第 1 项（auth-service 独立构建、配置与健康接口）：自测通过。

| 检查 | 实际执行与结果 |
|---|---|
| 独立构建 | 仓库根目录以 Docker 挂载服务目录，在 Maven 3.9.9 / Temurin 17.0.15 下执行 `mvn -B -f auth-service/pom.xml verify`，BUILD SUCCESS |
| 自动化测试 | `HealthControllerTest` 3 项，0 失败、0 错误、0 跳过；验证 live 不访问数据库、ready 失败后恢复、异常时资源释放 |
| 真实 MySQL 开发自测 | `pwsh -NoProfile -File backend/auth-service/tests/health-smoke.ps1` 通过。数据库未启动时 live=200，ready=503（3.06 秒）；数据库启动后 ready=200；停止后 live=200，ready=503（2.97 秒）；恢复后 ready=200，认证容器重启次数为 0 |
| 源码镜像 | `docker build -f backend/auth-service/Dockerfile -t cloud-drive-auth:bootstrap backend` 成功，构建阶段执行 verify，基础镜像固定为已验证 digest；运行镜像只带 jar 和 JRE |
| 镜像运行 | 使用 `health-smoke.ps1 -ApplicationImage cloud-drive-auth:bootstrap` 通过，默认 ENTRYPOINT 可运行；ready 从 503（3.02 秒）恢复 200，停库后 503（3.00 秒），再次恢复 200，应用无重启 |
| 旧规范检查 | 原命令缺 javalang；安装到宿主临时目录后，通过 Python 导入仓库检查器并仅固定 `_discover_project_root` 为 auth-service 路径，保留原规则配置。明确扫描 3 个 Java 文件，No problems found，无解析跳过。直接执行旧 CLI 会向上选中 backend/src，不能将该范围的通过作为新服务通过 |
| 文档与差异 | Git 空白检查通过；相对 Markdown 文件引用存在；暂存仅含本功能的 11 个文件 |

详细构建、配置、健康响应和可重复自测命令见 [auth-service README](../backend/auth-service/README.md)。
ready 当前确认数据库可连接，不检查尚未实现的业务表映射。服务扫描仅覆盖自身包，不加载原单体。
注册、登录、JWT、基础资料自测通过；真实 JWT 与 B 文件服务互操作通过。前端适配及 share-service 待开始。

第 2 项注册自测通过：Java 17 verify 共 4 项测试通过；真实 MySQL 校验字段、归一、邮箱/账户冲突、4 并发注册仅一个成功、用户事务回滚、散列存储和跨库权限均通过。沿用 B 的 SQL，无迁移。旧规范扫描 11 文件，ApiResult/Registration 两个 record 跳过，其余无问题。下一项为登录/JWT/基础资料与 B 的 JWT 互操作。

## 4. 环境与已解决故障

- 受限执行推送仍报 DNS 线程错误；受限环境外可连接。此前远端 permission denied 在用户接受仓库邀请后解决，两个文档提交均已推送。Git Credential Manager 列出的账户为 `Scoyn-X`，未输出或更换凭证。
- Docker Desktop 4.50.0，context=`desktop-linux`，客户端及 Linux Engine 28.5.1；需在受限环境外访问引擎管道。原有 trek、MinIO 容器和已有卷保持不动。
- 健康自测使用随机命名网络和容器、临时 MySQL 内存文件系统、随机凭证、回环随机 HTTP 端口。结束仅移除本次临时容器和网络，不操作课程卷。
- 宿主 Maven 3.9.9 默认 Temurin 25.0.3；本次使用容器 Java 17 完成构建和运行验证，没有修改系统 JAVA_HOME。运行 JRE 为 17.0.21，MySQL 为 8.0.29。镜像 digest 见服务 README。
- Docker 命名卷 `course-a-maven-cache` 只作 Maven 依赖缓存保留，无业务数据。javalang 0.13.0/six 1.17.0 安装在宿主临时目录 `cloud-drive-check-deps`，未改全局 Python 环境。Node/pnpm 留待前端阶段验证。

## 5. 接手阅读顺序

1. 根 `AGENTS.md` 和 `docs/development-workflow.md`。
2. 本交接记录和 `docs/plan.md`，尤其第 2.4、2.5 节。
3. `docs/functional-requirements.md`。
4. `docs/phase1/auth-service.md`、`frontend.md`、`share-service.md`、`file-service.md`。
5. `backend/file-service/README.md`、`backend/sql/course-mysql/README.md`。
6. 新文件服务的 AccessConfiguration、FileController、FileCatalog、ObjectStorage、application.yaml，以及课程三库 SQL。

原项目规范位于 `backend/script/RULES.md` 和 `frontend/script/RULES.md`。原规则按技术与目录适用，新课程服务采用适量的职责划分，可使用 Java record、JdbcTemplate，详细边界已在工作规范说明。

## 6. 与 B 对接必须遵守的事实

- 服务端口为容器内 8080，公共接口前缀 `/api/v1`。JSON 使用 `{code,msg,data}`，成功码为字符串 `00000`。
- JSON 业务 ID 为十进制字符串，根目录为 `"0"`，`isDirectory` 为布尔值，容量为 `totalBytes`、`usedBytes`。
- JWT 使用 HS256，JWT_SECRET 为至少 32 字节的 UTF-8 原始值。B 校验 sub、accountId、iat、exp、iss、aud，身份从已验证的 sub 读取。默认两小时有效期，时钟偏差应明确一致。
- 内部接口为 `GET /internal/v1/files/{id}?ownerId=...` 与 `GET /internal/v1/files/{id}/content?ownerId=...`，携带 `X-Internal-Token`。内部令牌与 JWT 密钥不同。
- 内部元数据可以返回目录，A 的分享服务须依据 isDirectory 拒绝目录分享。内容接口只接受活动普通文件。
- MySQL 为 auth_db、file_db、share_db，各账号只访问自己的库。A 使用 auth_user 和 share_user，文件与配额归 B。
- B 已提供 `backend/sql/course-mysql/schema/auth_db.sql` 和 `share_db.sql` 初版，A 要核对映射、状态和时间含义。已有卷改表须提供迁移，不能仅改初始化 SQL。
- 分享服务通过 HTTP 获取元数据和流，不能直接查文件库或读取 MinIO。本人分享列表使用文件名快照。
- 新文件服务通过用户配额行锁协调写入，以持久化清理记录处理失败上传和永久删除。文件服务当前按单实例设计。

## 7. 推荐继续步骤

既有文档和初次交接记录均已分别推送。当前从 auth-service 最小骨架开始逐功能交付，每步只暂存对应文件并检查差异。

```powershell
git status --short --branch
git log -4 --oneline
git push -u origin feat/auth-service-bootstrap
```

推送成功后，按 plan 第 2.5 节顺序执行。

| 顺序 | 功能 | 关键验证 |
|---|---|---|
| 1 | auth-service 独立构建、配置与健康接口 | 构建、live/ready，依赖失败有界 |
| 2 | 个人账户注册 | 校验、散列、唯一约束、事务和并发重复注册 |
| 3 | 登录、JWT、基础资料 | 正反向认证，真实 JWT 访问 B 文件接口 |
| 4 | 前端登录注册与导航精简 | 类型、构建、刷新、已移出功能请求清理 |
| 5 | 个人文件列表、目录与配额 | 字符串 ID、布尔类型、目录归属 |
| 6 | 上传下载、重命名与永久删除 | 内容 SHA-256、冲突、超限、容量刷新 |
| 7 | share-service 构建、配置、健康和文件 HTTP 客户端 | 内部凭证、超时与下游错误 |
| 8 | 分享创建、本人列表和取消 | 文件归属、快照、有效期、幂等 |
| 9 | 匿名验证和流式下载 | 提取码、限流、失效、流关闭和完整性 |
| 10 | 前端分享管理和匿名访问 | hash 分享链接、POST 下载与错误处理 |
| 11 | A 镜像、Nginx 和运行交付补齐 | 源码构建、公共路由、内部接口阻断 |
| 12 | AB 开发联调修复 | 每个问题复现、修复、验证并单独推送 |

功能所需的测试、SQL、配置及文档跟随对应功能提交。镜像可随服务首次可运行时交付，第 11 步补齐 A 的运行交付。开发联调可使用独立配置，C、D 的整体编排和正式实验保持原职责。

## 8. 检查和交接注意事项

- 原后端自定义检查器基于 javalang，解析失败会警告并跳过，默认扫描范围也不自动覆盖新服务。增量基线默认 master，本仓库使用 main，应显式传有效基线。未跟踪文件需另行覆盖。
- 前端现有 build 用 `vue-tsc --noEmit & vite build`，类型检查和构建要分别顺序执行。lint 脚本包含全项目自动修改，优先对相关文件执行检查模式。
- 前端当前忽略 pnpm 锁文件，固定依赖时同步处理。前端仍有数字 ID、数字目录标识、旧配额、团队状态及 SSE 下载逻辑，不能只删菜单。
- A 的注册不能初始化 B 配额，用户资料不能聚合团队、会员和私密空间。原单体中的业务依赖不能直接复制到新服务。
- 健康检查、构建成功、业务可用和 AB 联调通过分别记录。真实凭证不得提交或输出。
- 每完成一项更新本进度文件，保留准确的分支、提交、验证结论和下一步，确保新对话可据此继续。

## 连续交付记录

- `8fd5c7f` 注册功能已单独推送。
- 第 3 项登录/JWT/资料：Java 17 verify 5 项测试通过；`python backend/tests/course_smoke.py --auth` 通过，覆盖注册回归、归一登录、错误密码/未知/禁用账户、资料字段、真实 JWT 访问 B quota、篡改令牌拒绝，以及认证容器停止后 B 仍接受已有 JWT。独立测试环境已清理。
- 旧规范扫描 14 Java 文件，AccountLogin（text block/record）、ApiResult、Registration 共 3 文件被旧解析器跳过，其余无问题；Java 17 构建覆盖全部源码。JWT 配置和错误码已同步服务 README。
- 下一项：前端登录注册与课程导航精简，按第 2.5 节逐项提交推送。

- `f09076a` 登录/JWT/资料已推送。
- 第 4 项前端登录/导航：Node 24.11.0、pnpm 10.32.1；锁文件提交，保留原依赖范围。课程入口仅加载 src/course，原源码留在旧目录。类型检查、生产构建通过（Element Plus 大 chunk 提示）；相关 ESLint/Prettier/Stylelint 和课程自定义检查通过。全量 src 检查 11 项遗留错误，均非本轮新增。2 项 Chromium 替身 API 测试通过；实际服务 API 已在上一项通过，最终浏览器真实闭环留待 AB 联调。
- 开发/浏览器测试使用 5173，避开已有 3000 端口服务。下一项：个人文件列表、目录和容量。

- `8cfc112` 前端登录导航已推送。
- 第 5 项个人文件浏览/目录/容量：类型与构建、相关 ESLint/Prettier、课程自定义检查通过。目录浏览器测试通过，导航定位因新增面包屑产生歧义后已收窄并补跑 2 项登录测试通过。`python -u backend/tests/course_smoke.py --files` 通过，覆盖真实双用户目录归属、根面包屑、布尔目录类型、BIGINT 字符串 9007199254740993、同名/非法名称、固定配额。
- 修复开发测试脚本：Docker 重启可能改变随机宿主端口，重启后重新读取端口；最初等待脚本已停止且其专用容器/网络已清理，修复后全套 API 回归通过。下一项：上传、下载、重命名与永久删除。

- `3080ecc` 文件列表/目录/容量已推送。
- 第 6 项文件操作：类型、构建、相关 ESLint/Prettier、课程自定义检查通过；3 项文件 Chromium 测试通过（上传、重命名、下载内容和文件名、永久删除、JSON 错误不落盘）。真实 `course_smoke.py --files` 通过：两个用户归属、中文与空格、SHA-256、冲突、非空目录、413、三个并发 400000 字节上传仅两个成功，容量准确，重复删除不重复扣额。
- 契约核对：第二次删除已失效记录返回 404（符合 B 文档统一不可见资源规则），测试不再误要求 200，容量保持不变；未修改 B 实现或业务要求。下一项：share-service 独立骨架、健康与文件 HTTP 客户端。

- `bf65a0a` 文件操作已推送。
- 第 7 项分享骨架/客户端：Java 17 verify 5 项测试通过，元数据内部凭证、归属复核、404/503 和连接失败有界验证通过。真实 MySQL 健康自测通过：未启动/中断数据库时 live 200、ready 503（3.15/3.11 秒），恢复后 200，无应用重启；无需启动 file-service。共享健康脚本提至 backend/tests，auth 原入口兼容。旧规范扫描 8 Java 文件，1 record 跳过，其余无问题。下一项：分享创建、本人列表和取消。

- `f02c0bb` 分享独立骨架已推送。
- 第 8 项分享管理：Java 17 verify 5 项回归通过；`course_smoke.py --share-management` 真实 AB 自测通过，包含前序认证和文件回归、两个账户隔离、拒绝目录/越权、六位提取码与 BCrypt 存储、128 位 token、文件名快照、过期、取消幂等、文件服务停机时列表/取消/ready 可用而创建 503。沿用 B SQL，无迁移。
- 旧规范扫描 12 Java 文件，ApiResult/ShareStore 两文件因 record/text block 跳过，其余无问题，全部源码由 Java 17 构建覆盖。下一项：匿名分享验证、错误码与流式下载。
