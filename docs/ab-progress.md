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

| 项目 | 本次核对结果 |
|---|---|
| 当前分支 | `course/a-services` |
| 当前 HEAD | `5f66bab` |
| HEAD 提交标题 | `docs(ab): establish development workflow and incremental delivery plan` |
| main 与本地 origin/main | `dde9c6f` |
| B 的数据库交付 | `4dbc492` |
| B 的文件与 MinIO 交付 | `be3e3f1` |
| 原方案基线 | `eef0ad1` |
| 远端 | `https://github.com/Fqmmm/cloud-drive.git` |
| 分支上游 | `origin/course/a-services`，2026-11-15 设置成功 |
| 首个文档提交的推送 | 用户接受协作者邀请后，2026-11-15 推送 `5f66bab` 成功 |

本轮开始时唯一工作区变更为未跟踪的本文。用户接受仓库协作者邀请后，已有文档提交推送成功。本文作为下一项独立文档提交；提交号及最终工作区状态请用 Git 核对。

`5f66bab` 包含根 `AGENTS.md`、`docs/development-workflow.md`、更新后的 `docs/plan.md` V3.3 和 B 文件服务 README 中构建约定的同步说明。该提交只有文档。

## 3. 已完成及尚未开始

已阅读课程要求、原项目主要调用关系、B 新增实现及规范工具。已制定工作规范并把独立工程与逐功能提交推送的决定写入计划。

A 的课程服务尚未开始编码。`backend/auth-service/` 和 `backend/share-service/` 当前不存在。前端仍是原完整网盘实现，本轮尚未修改。未执行应用构建、镜像构建、数据库初始化或业务联调，B 的实现也尚未经本对话运行验证。

## 4. 推送与运行环境阻塞

2026-11-15 本轮实际诊断：

- 普通受限执行中的 `git push -u origin course/a-services` 再现 `getaddrinfo() thread failed to start`。在受限环境外执行后可连接 GitHub，但远端返回 `remote rejected ... (permission denied)`；使用 `git -c http.version=HTTP/1.1 push -u origin course/a-services` 重试得到相同拒绝。网络已可达，写入权限或凭证授权仍受阻，不能报告推送成功。
- `git ls-remote --heads origin` 成功，仅返回 `main`，指向 `dde9c6f55429e033cac3fcf62152ab902cca96a1`；远端尚无开发分支。凭证 helper 为 Git Credential Manager，`git credential-manager github list` 列出的账户为 `Scoyn-X`；没有输出令牌，也未清除或替换既有凭证。需核对该账户对 `Fqmmm/cloud-drive` 的写权限及凭证仓库授权。GitHub CLI 未安装。
- Docker 普通受限执行报管道访问被拒绝；受限环境外 `docker version` 成功。实际 context 为 `desktop-linux`，Docker Desktop 4.50.0，客户端和 Linux Engine 均为 28.5.1。无需重启引擎，也未启动、停止或删除容器/卷。
- Maven 3.9.9 默认使用 Temurin Java 25.0.3；已发现 JDK 21.0.7，常见安装目录未发现 JDK 17。本机 Docker 镜像列表没有 Java/Maven 构建镜像。Java 17 构建与运行仍待验证，未执行应用构建。Node、pnpm 及前端依赖尚未验证。

恢复结果：用户接受仓库邀请后，`git push -u origin course/a-services` 成功，既有文档 `5f66bab` 已推送并设置上游。此前拒绝记录保留用于诊断追溯。下一步单独提交推送本文，再开展 plan 第 2.5 节第 1 项；尚未开始业务功能。

用户本轮要求后续分支采用“类型 + 简短改动说明”。Git 分支名不支持空格，后续使用 `feat/short-description`、`fix/short-description`、`docs/short-description` 等形式；当前 `course/a-services` 保留以恢复已有提交推送，未重写历史或合并 main。

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

先恢复文档提交的推送，再将本交接记录作为单独文档提交并推送。每步只暂存对应文件，检查差异，不把交接文件混入后续功能提交。

```powershell
git status --short --branch
git log -4 --oneline
git push -u origin course/a-services
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
