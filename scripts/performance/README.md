# E1 核心业务性能与资源开销

按 [实验一要求](../../docs/phase2/01-performance.md)执行，入口为当前根 Compose 的同源 Nginx。
本工具使用 Python 封闭负载模型，输出与要求等价的逐请求延迟、HTTP/业务成功率、RPS、迭代吞吐及字节吞吐。
默认负载入口为 http://127.0.0.1:8080，仍经过同一 Nginx；PUBLIC_BASE_URL 的浏览器分享地址保持 localhost。
本机 localhost 新建连接存在约 3 秒等待，IPv4 回环约 3 毫秒，故正式完整批次显式固定 IPv4。
请求入口写入 environment/workload；更换入口后的数据另开批次，不与旧部分批次混算。
依赖已在本机具备：Python 3.13.5、requests 2.32.4、psutil 7.2.1、NumPy 2.3.3、Matplotlib。
资源采集器面向 Windows Docker Desktop 的 desktop-linux 命名管道，Docker Engine API v1.56。

## 顺序与命令

确保六容器 healthy，停止其他压测、镜像构建、故障注入和卷重建。先执行无故障冒烟和短试跑：

```powershell
python -u scripts/smoke/functional.py --api-only
python -m unittest discover -s scripts/performance -p test_metrics.py
python -u scripts/performance/run.py --pilot
```

试跑单独标记 pilot，不进入正式结果。试跑使用 2 VU、3 秒预热/5 秒测量/至少 3 秒冷却，仅检查工具链。
正式工具和应用源码提交冻结后执行：

```powershell
python -u scripts/performance/run.py --batch <唯一批次名>
python scripts/performance/analyze.py <同一批次名>
```

暂停后的正式矩阵使用新批次继续，保留原批次与已完成轮次。例：

```powershell
python -u scripts/performance/run.py --batch 20261116-e1-continuation --continue-from 20261116-e1-formal-ipv4 --fixtures artifacts/e1/20261116-e1-formal/fixtures.local
```

续跑只选择原矩阵未完成的规格，保留原始顺序、并发和重复数；要求复用原私有 fixtures。
开始前校验原轮次完整性、预热/测量/冷却参数、入口与上传上限，以及镜像、脱敏 Compose、Docker CPU/内存预算和测量/清理脚本哈希。
新批次重新记录环境与空闲样本，每轮重新登录；旧批次保持原暂停状态，后续汇总须注明两个批次的边界。
测试命令为 `python -m unittest discover -s scripts/performance -p 'test_*.py'`。

数据准备和清理也有独立入口，凭证路径必须在忽略目录中：

```powershell
python scripts/performance/data.py prepare --credentials artifacts/e1/<新批次>/fixtures.local
python scripts/performance/data.py cleanup-uploads --credentials artifacts/e1/<批次>/fixtures.local
python scripts/performance/data.py cleanup-all --credentials artifacts/e1/<批次>/fixtures.local --result <公开清理结果JSON路径>
```

cleanup-all 验证账户归属后清理实验源文件和目录、取消实验分享、等待清理队列，核对配额归零及物理对象不存在；
账号及历史元数据保留。不要在正式矩阵未完成时运行该命令。

基础矩阵 P1/P2/P3/P4 × 5/10/20 VU × 3 次，每轮 30 秒预热、120 秒正式窗口、至少 30 秒冷却。
三个重复按 [5,10,20]、[10,20,5]、[20,5,10] 轮换并发顺序。
经用户授权加入 P5U/P5D：20 MiB 上传/下载分开，5 VU，各三次，不与 1 MiB 汇总。
共 42 轮，固定窗口最少 126 分钟，加上登录、校验和清理会更长。
文件生成随机种子固定为 20261116 + 字节大小；每次上传使用独立名称，文件服务生成独立随机对象键。
每个 VU 有独立个人账号和数据区；列表为 99 个目录记录与一个 1 MiB 文件，共 100 条直接记录。
前五个账号另有单独目录中的 20 MiB 下载源，列表数据不受影响。

## 时序与统计口径

- 每轮在预热前重新登录，检查 JWT 剩余寿命至少 600 秒；不延长产品默认寿命，测量中不登录/刷新。
- 每个 VU 发起一轮业务后等待 1 秒；初始请求按 VU/VUs 秒错开，所有档位同一策略。
- P4 每个迭代先验码再下载，两步均匿名、用正确保护码；分别标记 share_verify/share_download。
- 正式 HTTP 样本以请求开始时间落在精确 120 秒窗口内为准，最后的在途请求等待完成，超时仍计失败。
  成功率和延迟使用上述请求队列；RPS 与字节吞吐只计在窗口结束前成功完成的请求。
  在窗口后才开始的 P4 第二步标为 measure_drain，不混入正式 HTTP 样本；业务迭代另按开始时间归属。
- 延迟从已准备好请求体后的 send 到响应正文接收完成；业务校验随后决定成功与否。
  报告主延迟包含失败请求，另保存成功请求延迟；正文编码、验码校验、哈希和 1 秒等待进入业务迭代时间。
- 每轮独立计算均值/P50/P95/P99，NumPy 线性分位数；三轮展示各轮值的中位数与最小—最大范围。
  三轮 P95 的汇总不称为整体 P95；保留请求数并将 P99 作为辅助指标。
- 独立资源采集进程每秒依次读取六个容器的 one-shot 统计，保留实际时戳、间隔、丢样和错误。
  CPU 100% 代表一个 Docker 逻辑核，四核总预算约 400%；内存为 usage 减 inactive_file 的工作集口径。
  另记录负载进程、采集进程 CPU/RSS 及宿主总 CPU/可用内存。原始网络与块 I/O 累计计数在可得时保存。
- 冷却最少 30 秒，再检查最近约 10 秒的六容器总 CPU 是否低于 80%（四核预算的 20%）；
  未稳定最多追加 120 秒，实际状态保留，不能据此声称长期稳态。

## 配额与清理边界

上传每 VU 上限 150 次（包含预热），按此上限预检剩余配额；5 VU × 150 × 20 MiB 最多约 14.65 GiB。
启动每个上传轮次前要求 C:/D: 剩余空间都大于该轮最坏上传量的 1.5 倍。实际触及上限与否写入 workload.json。

收尾先按账号经业务 API 删除专属 E1-uploads 目录内的本轮文件，核对 usedBytes 回到源样本基线。
为避免业务后台“每 15 秒处理 20 对象”的队列拖延整个实验，测量结束后使用现有 mc 按确定的对象键批量删除，
列举桶验证这些键全部不存在，再仅确认对应已软删除记录的清理队列。此维护阶段不计入测量，未改业务代码或调度参数，
不删除其他账号对象、活动下载源、桶或数据卷。软删除元数据保留，因此数据库历史行数会随实验累积。
所有下载源每轮前后进行 SHA-256 校验。登录、上述维护和校验都在正式窗口之外。

账号密码、JWT、分享 token/提取码只保存在 Git 忽略的 artifacts/e1/<batch>/fixtures.local。
公开 workload/请求/错误 CSV 不含 URL、请求体、凭证或文件对象键；Compose 环境字段已脱敏。

## 交付目录

每轮为 experiments/E1/<batch>-<场景>-vu<并发>-r<重复>/，保存：
environment.json、compose.redacted.json、workload.json、requests.csv、iterations.csv、errors.csv、
resources.csv、load-generator.csv、collector.json、checksum.json、cleanup.json、execution.log、metrics.json。
downstream.csv 仅从分享日志提取白名单内的 request ID、类别、状态与耗时，不保存原始请求或未知日志文本。
<batch>-summary/ 包含实际矩阵、空闲样本、每轮汇总、三轮中位数/范围、资源表及 PNG/SVG 图。
原始数据允许复算；失败试跑与正式批次分别保留，代码/配置修复后使用新批次名。
