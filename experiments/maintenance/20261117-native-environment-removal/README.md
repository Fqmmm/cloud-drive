# E1 非容器环境补充清理

日期：2026 年 11 月 17 日。用户指出资源管理器 Linux 中仍显示 `CloudDrive-E1-Native`，要求继续清理该实验环境。

上一轮按 C 盘范围清理 Docker 资源时，保留了位于 D 盘的非容器环境。本次注销 `CloudDrive-E1-Native`，并删除其专用目录 `D:\CloudDriveLab\E1Native`，包括虚拟磁盘、导出镜像、程序及本机配置。清理前目录文件共约 11.81 GiB，实际磁盘空闲变化见 [result.json](result.json)。

原有 `Ubuntu-24.04`、`docker-desktop` 的注册项、安装路径和默认发行版设置保持不变，见 [registry-verification.json](registry-verification.json)。注销命令及输出见 [unregister.json](unregister.json)，最终发行版列表见 [wsl-state-after.txt](wsl-state-after.txt)。资源管理器可能需要按 F5 刷新列表。

## 日志与实验结果保留

删除前核对了完整目录边界及重解析点，确认目标只包含本次专用环境。[plan.json](plan.json)记录原路径、占用和日志保留映射。

原专用目录中的 11 份日志及诊断 JSON 已复制到本机 `artifacts/cleanup/20261117-native-environment-removal/lab-records/`，复制前后 SHA-256 一致；对应公开脱敏副本仍在 [20261116-main-integration 归档](../../log-archive/20261116-main-integration/README.md)。WSL 内三份 Nginx 日志的原文此前已导出到 `artifacts/log-archive/20261116-main-integration/native-linux/`，本次再次核对哈希。

`artifacts/native/` 中原有的各批次服务日志、仓库中的原始请求/资源 CSV、JSON、图表和论文报告均保留。E1 非容器正式数据仍见 [批次清单](../../E1/20261116-e1-native-formal-summary/matrix.json)。本次删除的是运行环境，后续重跑需重新准备环境；已有指标可直接从仓库原始记录复算。
