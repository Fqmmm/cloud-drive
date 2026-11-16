# 非容器 E1 进度

2026-11-16，用户要求开始非容器 E1，不清理 C 盘，P5 本轮不考虑。分支 `feat/e1-native`，起点 `7001ec2`。

方案为 `D:\CloudDriveLab\E1Native` 下的独立 WSL2 发行版 `CloudDrive-E1-Native`，六个服务作为普通 Linux 进程运行。
从 E1 冻结镜像提取同一份 JAR、前端产物、JRE、MySQL、MinIO 和 Nginx，正式测量时不用 Docker 启动业务。
已确认当前六个镜像 ID 与 E1 容器基线逐项一致；JRE 为 Temurin 17.0.21，MySQL 8.0.29，Nginx 1.28.3，MinIO RELEASE.2025-09-07T16-13-09Z。
C/D 同属物理磁盘 0，但容器数据盘在 C、非容器数据盘在 D，报告保留存储位置差异，不将全部差异归因于容器开销。

P1—P4 共 36 轮，5/10/20 VU 各三次，30 秒预热、120 秒正式、至少 30 秒冷却、1 秒思考时间。
复用 Windows 闭环负载与统计口径。非容器进程资源采用独立采样，记录 CPU、RSS/PSS 和采样开销；
内存口径与既有容器 working-set 区分。结果统一写入 docs/exp，原始记录保留 experiments/E1。

已导出相同镜像并导入专用 WSL，验证 JRE、MySQL、MinIO 和 Nginx 可直接运行。
新环境内核为 WSL2 6.6.87.2，4 CPU、MemTotal 4,107,522,048 字节，与原环境一致。
导出包和新 VHDX 均在 D 盘；C 盘仍约 18.08 GiB 可用，没有修改现有 Ubuntu、容器数据卷或真实应用凭证。
现有 cgroup v2 控制器已启用，可为六个直接进程服务建立独立记账组，不改变其他组或添加单服务配额。
计划用 memory.current 减 inactive_file 统一工作集口径，同时附加进程 RSS/PSS；保留 CPU 估算方法说明。
