# 刘骐语：端到端验收、E3 和 E4

范围对应 [分工](../../docs/plan.md)、[功能需求](../../docs/functional-requirements.md)、[E3 要求](../../docs/phase2/03-failure-recovery.md)、[E4 要求](../../docs/phase2/04-persistence.md)。复用同伴交付的六容器和 `scripts/smoke/functional.py`，不修改业务需求。

## 运行

Windows PowerShell 5.1 或 7，Python 3.11+、Git、Docker Desktop Linux 引擎。让 Docker Desktop 保持运行，停止其他压测与镜像构建。默认占用回环端口 8088，恢复环境 8089；原课程项目不参与操作。

```powershell
Set-Location 'C:\Users\25979\Desktop\云计算与虚拟化\小组PJ'
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\experiments\run.ps1
```

入口自动准备忽略目录内的 Python 虚拟环境及 Chromium，运行工具测试，从源码构建六容器，然后按顺序执行：

1. FR-01—FR-12 API 与真实浏览器验收：两个用户及匿名上下文，真实文件/MinIO 依赖中断，上传中断/截断下载使用受控注入。
2. 两用户各三份文件：1 KiB、1 MiB、20 MiB，含中文和空格文件名，每份公开/提取码分享；源字节保存在私有目录，可按固定 Python 种子复现。
3. E3：F1 分享停服、F2 认证停服、F3 文件停服、F4 MinIO 停服、F5 JVM halt(17)，各三轮。每轮 30 秒基线；人工停服确认后保持 30 秒，恢复后每条探针连续三次成功。F5 单独启用钩子并在计时外重建/重载，结束后关闭并验证内部路由 404。
4. E4：MySQL、MinIO 各三次保留卷替换。固定人工恢复步骤、同一批样本、每轮全部 18 次个人/分享下载及权限、元数据、对象、桶策略检查；另测额外文件永久删除。
5. 备份恢复扩展：暂停业务写入，同窗口备份三库和对象，在另一个项目及新卷恢复并校验原账号、原分享和全部样本。
6. 从实测 CSV/JSON 生成报告、汇总表和文件 SHA-256 索引。缺轮次、失败轮次和试跑不会生成完整正式报告。

首次构建需要下载镜像和构建依赖；整个流程通常需要数十分钟，具体以实测日志为准。`-RunId` 可指定新批次，`-Port` / `-RestorePort` 可改端口，`-IncludeMysql` 加入 F6 三轮，`-SkipRestore` 跳过新卷扩展。该开关会在报告中注明未执行。

构建期间的脱敏输出实时写入 `experiments/acceptance/<run-id>-deployment/build.live.log`，原始字节仅保存在私有 `artifacts/liu/<run-id>/command-*.raw.log`。Docker 命令结束后仍保存完整执行记录与退出码。网络错误会保留失败批次，不自动把失败算作一次成功实验。

前端构建支持 `-NpmRegistry https://registry.npmmirror.com`，默认仍使用 npm 官方源；来源写入专用 `.env`、Compose 参数和环境快照。pnpm 版本和锁文件保持固定。下载增加 5 次网络重试，参数依据 [npm 配置文档](https://docs.npmjs.com/cli/v11/using-npm/config/)及 [pnpm 10 配置文档](https://github.com/pnpm/pnpm.io/blob/main/versioned_docs/version-10.x/settings.md)。更换来源时新建批次，不覆盖既有环境。

需要额外查看 Docker 的当前状态时，可在第二个 PowerShell 窗口执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\experiments\watch.ps1 -RunId <批次>
```

该工具每 15 秒读取本仓库构建历史和实验项目容器状态，保存到私有 `live-status.json/jsonl`，不启停服务；Ctrl+C 仅停止监控。

源码应先提交冻结，再采正式数据。每个环境快照保存 Git 提交和工作区状态；源码或工具变更后另建批次。失败立即停止，保存失败目录，不覆盖旧记录。不要在同一环境同时启动两套实验。收尾保留全部容器、卷和私有备份；脚本不删除卷。

## 输出与凭证

| 路径 | 内容 |
|---|---|
| `experiments/acceptance/<run-id>-deployment/` | 构建/启动日志与版本快照 |
| `experiments/acceptance/<run-id>/` | FR 逐项结果、API/浏览器输出、服务日志 |
| `experiments/datasets/<run-id>/` | 基线文件/分享 ID、对象键、大小、SHA-256、元数据与环境 |
| `experiments/E3/<run-id>/` | 各轮 `probe.csv`、命令日志、事件、状态观察、退出事件、容器快照和下载验证 |
| `experiments/E4/<run-id>/` | 基线、重建前后卷/容器、元数据、对象清单、校验、删除和备份恢复结果 |
| `docs/exp/E3-results.md`、`E4-results.md` | 完整正式批次的派生报告 |
| `artifacts/liu/<run-id>/` | 私有 `.env`、fixture 凭证、源样本、SQL 和对象备份、控制台原文，不提交 |

分享 token、提取码、密码和 JWT 在采集公开日志时脱敏。数据库原始备份可能含账户散列和分享能力，留在忽略目录；公开清单只列稳定业务字段和内容哈希。运行结束再次扫描公开证据，敏感值命中则终止归档。不要直接提交 `artifacts/`。

## 方法和复算

E3 普通请求绝对期限 5 秒，下载 15 秒。每个请求运行在独立子进程，主调度器每秒发出全部探针，超时终止子进程；单个慢请求不会延后其他业务。额外观察前端 HTML、已有 JWT 的本人分享列表、公开/提取码校验及下载。`probe.csv` 保存计划/实际发出/返回时刻、HTTP/业务码、错误类别、调度偏差、耗时、下载大小和哈希；未实际发出的请求不虚构发出时间。

恢复按**发出顺序**的连续三个成功 tick 判断，首个成功请求的发出时间为 t5；迟返回不改变顺序。人工恢复为 t5−t3，自动为 t5−t0；共同恢复取各探针最晚的 t5。业务失败窗口另按首次失败到该业务 t5 计算，未观察失败时保持缺测。1 Hz 采样和实际调度偏差限制时间精度。保留原始状态/退出事件，不把 healthy 当作业务成功。

E4 比较容器 ID 改变且原命名卷/目标路径不变，稳定业务字段和记录数逐项相等，对象键/大小相等，所有下载字节数/SHA-256 一致，以及授权关系和私有桶策略。MySQL 或 MinIO 就绪后人工重启三个应用、等待健康、验证 Nginx 配置并 reload，步骤用时单独记录。原始 SQL 备份留在本机，公开元数据排除密码、JWT、提取码散列和分享 token。

```powershell
# 本地工具回归；只访问本机临时 HTTP 服务，不访问真实 Docker
python -m unittest discover -s scripts/experiments -p test_experiments.py -v
# 使用运行入口生成的虚拟环境复算完整批次
.\artifacts\liu-tools\Scripts\python.exe scripts/experiments/analyze.py --run-id <批次>
```

分阶段入口见 `python scripts/experiments/run.py --help`。独立重跑 E3/E4 时，显式传同一私有环境和新的结果批次，不复用已有输出目录。新批次报告只能引用其实际完成的数据；分析器默认要求验收、E3 和 E4 同一批次编号。

## 验证范围

离线回归验证项目隔离、凭证保留、日志脱敏、私有备份隔离、容器与卷判断、Unicode CSV、内容损坏识别、绝对超时、独立调度和连续恢复统计。它不代替六容器实测。实际完成状态见 [交接记录](../../docs/liu-progress.md)。
