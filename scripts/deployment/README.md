# E2 编排与独立部署实验

依据 [实验二](../../docs/phase2/02-orchestration.md)，在仓库根目录运行。依赖本机 Python、requests、psutil、NumPy、Docker Desktop、PowerShell 7；性能部分复用已验证的 E1 测量代码。

```powershell
python -m unittest discover -s scripts/deployment -p test_e2_support.py
python -m unittest discover -s scripts/smoke -p test_context.py
python -u scripts/deployment/e2.py --batch 20261116-e2-formal --project cloud-drive-e2-20261116
python scripts/deployment/e2_analyze.py 20261116-e2-formal
```

每次正式执行使用新的批次和项目名。默认含双副本扩展；`--basic-only` 只执行基础部分。
入口固定本机 IPv4 8080，开始前要求 C/D 盘各至少 8 GiB 可用。脚本创建独立随机凭证、专用镜像标签、专用网络和两个新卷。
私有环境、持久样本凭证和负载账号只保存在被忽略的 `artifacts/e2/<batch>/`；公开记录位于 `experiments/E2/<batch>/`。
不执行卷删除、镜像清理或虚拟磁盘压缩。E1 原项目停止以避免争用，结束或异常后使用原容器恢复运行并核验原种子文件。

## 基础实验

首次要求该项目没有容器或同名卷，记录现有镜像和缓存。执行 `up -d --build`，观察器约每 0.5 秒保存状态变化。
分别记录 up 返回、全部容器健康和 FR-01—FR-12 的完整 86 项 API 冒烟通过时刻。冒烟清理、关闭时间单列。
已有镜像场景执行不带 `-v` 的 down/up，重复三次，核对原卷、固定样本和原分享。

分享更新通过独立构建参数和运行环境把 e2-v1 改为 e2-v2；只构建和替换 share-service。
三条独立探测线程以 1 秒为目标间隔检查登录、文件列表和有效公开分享，保留失败和跨恢复窗口的在途请求。
使用已交付的 `reload-nginx.ps1` 先检查配置再重载。检查镜像 ID、版本标签、响应版本和其余五容器 ID/启动时间不变。

## 双副本扩展

扩容后重载 Nginx，连续 100 次请求记录 X-Instance-Id。使用已有 MinIO 容器内的 curl 作为一次性内部客户端，
配置和凭证仅从 stdin 注入，不增加容器。定向在 A 创建分享、B 验证和下载并取消、A 验证取消状态。
每实例各六次错码验证，记录 5 次 403 后 1 次 429；正确提取码仍可通过。这只是每实例限制，不代表全局限流。

使用与 E1 相同的 20 VU P4：每 VU 独立数据，验证和下载均匿名，迭代后思考 1 秒。
每轮预热 30 秒、测量 120 秒、冷却至少 30 秒，一/二副本各三轮；交替顺序为 1→2、2→1、1→2。
复用独立资源采集器，两个分享副本分别记录。轮前后 SHA-256 校验，失败保留，迟完成请求按 E1 口径处理。
Docker 总 CPU/内存预算不变，不新增单容器配额。结束恢复一副本、重载 Nginx 并再次完整冒烟。

公开记录不包含原始请求 URL、请求体、JWT、密码或提取码。失败批次原样保留，代码修正后另开批次。
`e2_analyze.py` 从各轮原始请求、迭代和资源 CSV 重新计算指标，导出部署表、副本对照表及 PNG/SVG 图。
论文使用的结果报告位于 [docs/exp](../../docs/exp/README.md)。
原 Java/前端代码规范检查器不覆盖本轮 Python/PowerShell 新脚本，不能用它们证明实验脚本通过；验证见单元测试、配置解析、实际构建和实验原始记录。

## 论文日志归档

`archive_experiment_logs.py` 索引已提交的 `experiments/` 文件，脱敏归档本机实验日志、诊断 JSON/CSV，
并只读保存原六容器截至固定时刻仍保留的日志。`--native-wsl` 另采集已停止的专用原生环境内的文件日志，
发现活跃实验会拒绝操作。源文保留，输出附 SHA-256、原文/归档行数和来源路径；已移除或轮转的日志按实际覆盖情况说明。

```powershell
python -m unittest discover -s scripts/deployment -p test_archive_experiment_logs.py
python scripts/deployment/archive_experiment_logs.py --name <新的唯一归档名> --native-wsl
```

先提交已有实验目录，再创建新归档。当前完整索引见 [日志归档](../../experiments/log-archive/20261116-main-integration/README.md)。
