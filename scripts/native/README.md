# 非容器 E1

专用环境为 `CloudDrive-E1-Native`，存放于 `D:\CloudDriveLab\E1Native`。P1—P4 的业务代码和二进制来自既有 E1 冻结镜像，测量时六个服务以普通进程运行。

```powershell
python scripts/native/prepare.py
```

准备命令要求目标目录全新，不覆盖现有发行版。它从未启动的临时容器导出原镜像文件系统，再用 WSL 导入到 D 盘；
原数据库/MinIO 卷不参与导出。临时容器及其本轮新建匿名卷在导出后移除，原有容器、卷和凭证保留。
参照 [Microsoft 自定义 WSL 导入流程](https://learn.microsoft.com/en-us/windows/wsl/use-custom-distro)。

本轮不运行 P5。最终报告与对照解释放在 docs/exp，原始请求和资源记录放在 experiments/E1。

```powershell
python -m unittest discover -s scripts/native -p test_runtime.py
python scripts/native/experiment.py --pilot --batch <新的短试跑名>
python scripts/native/experiment.py --batch <新的正式批次名>
python scripts/performance/analyze.py <正式批次名>
python scripts/native/analyze_compare.py --native <正式批次名>
python scripts/native/capture_evidence.py <正式批次名>
```

对比工具要求两侧各有完整的 P1—P4 × 5/10/20 VU × 三次重复，检查 120 秒窗口、1 MiB 参数、
840 次种子校验和上传清理，再生成逐轮表、资源表、三次重复范围与 PNG/SVG 图表。
默认容器参照为 `20261116-e1-combined`，其中 P5 自动排除。完整的单轮均值、P50、P95/P99 保留在 metrics.json。
证据采集在正式矩阵完成且原 Docker 服务恢复后执行，脱敏配置并核对六个程序及全部前端文件的 SHA-256；
Docker 二进制通过只读复制流计算哈希，兼容没有 shell/校验工具的最小镜像。私有配置不参与指标复算。

运行前原 Docker 项目停止，正式测量期间 Docker Desktop 不运行。恢复原环境由正式控制器收尾执行，
使用 `docker compose start` 保留原容器 ID、镜像和卷，最后验证原 25 份文件。
原生凭证保存在 D 盘专用目录和忽略的 artifacts/native 中，不用于根 Compose。
Windows 通过 --exec 调用 WSL，避免变量被外层 shell 展开；专用清理验证账号身份、配额和对象作用域。
CPU 为 cgroup 用量增量/单调时钟，内存为 memory.current 减 inactive_file，另存 RSS/PSS；
采样器本身的 CPU/内存、Windows 负载端资源和供电状态单独记录。
原 Java/前端规则检查器不覆盖本轮 Python/shell/Java 采样工具，验证以 Java 17 编译、shell 解析、实际功能与采样试跑及相关回归为准。
