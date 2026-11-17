# 实验结束后的 C 盘清理记录

日期：2026 年 11 月 17 日。用户授权清理本次实验占用 C 盘的运行资源，不要求恢复业务数据。清理前代码提交为 `07a08a5`。

## 清理结果

| 项目 | 结果 |
| --- | --- |
| 实验容器 | 删除 `cloud-drive-course`、`cloud-drive-e2-20261116` 两个项目的全部 12 个容器 |
| 业务数据卷 | 删除两项目的 MySQL、MinIO 共 4 个命名卷，业务数据库及上传文件随之删除 |
| 实验镜像 | 删除 11 个镜像：两项目的四应用镜像、实验使用的 MySQL/MinIO，以及 Node 构建镜像 |
| 构建缓存 | 核对 63 条均创建于 2026-11-16 后清理，剩余 0 条 |
| 最终日志 | 删除前正常停止服务，保留全部 12 个容器的最终脱敏日志，含此前停止的 E2 容器 |
| Docker 数据盘 | 离线压缩从 44.53 GiB 降到 5.05 GiB，回收约 39.48 GiB；压缩前后字节数见 `compaction.json` |
| C 盘空闲 | 清理开始约 19.95 GiB，完成重启校验后约 59.41 GiB；宿主空闲会随其他程序活动变化 |

保留原有 `test_mysql_data` 卷及 `nginx:latest`、`mysql:latest`、`mysql:8.4` 三个无关旧镜像。它们不属于本轮实验。原 Ubuntu、原有 Playwright、D 盘代码、实验数据、报告和非容器环境均保留。

## 执行与验证

先核对容器标签、卷归属、镜像引用和缓存创建时间，形成 [plan.json](plan.json)。保存日志后，按精确 ID/名称删除目标资源；没有执行全局容器、镜像或数据卷清空。

Docker 环境未提供独立的 `fstrim` 命令，初次尝试失败记录见 [trim-attempt.json](trim-attempt.json)。随后使用 Docker 内置 BusyBox 的 `fstrim` 成功回收空闲块，见 [trim-result.json](trim-result.json)。

正常退出 Docker Desktop 后，确认数据盘可独占访问。用户确认 Windows UAC 管理员授权后，DiskPart 仅对已核对的 `docker_data.vhdx` 执行离线 `compact vdisk`，输入命令保存在 [diskpart-commands.txt](diskpart-commands.txt)。未执行全局 `wsl --shutdown`，未请求停止或删除原 Ubuntu。最终 WSL 列表显示各发行版均已停止，见 [wsl-state-after.txt](wsl-state-after.txt)；原 Ubuntu 虚拟盘及文件保留。压缩结果见 [compaction.json](compaction.json)及 [DiskPart 输出](diskpart-output.log)。

压缩后短暂启动 Docker，验证引擎可读取虚拟盘：容器为 0、实验卷及镜像均已移除、缓存为 0，无关旧卷及三个旧镜像身份保持一致。验证后再次正常退出 Docker Desktop，见 [verification.json](verification.json)。最终结果见 [result.json](result.json)。

## 日志与论文资料

[log-manifest.json](log-manifest.json)列出 12 份最终日志的来源、原文与脱敏副本 SHA-256、字节数和行数。日志位于 `sources/docker-final/`，原文保留在本机 D 盘的 `artifacts/cleanup/20261117-c-drive/`，公开副本完成凭证脱敏和格式归一。

[deletion-journal.json](deletion-journal.json)保留每步删除命令、执行时间和输出；[docker-df-after-deletion.txt](docker-df-after-deletion.txt)记录删除后的引擎空间占用。第一次命令失败及后续成功结果分别保留。

E1/E2 的原始 CSV、JSON、图表及结果报告保持原样。报告中“实验结束后恢复六容器健康”的描述对应实验当时；本记录说明随后按用户要求删除了运行环境。后续重新部署会拉取/构建镜像并初始化新的业务数据。论文指标仍可直接从已提交原始记录复算。
