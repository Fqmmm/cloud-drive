# E1、E2 实验记录与补充日志索引

本次归档为合并到 main 后的论文资料核对。原有 1,698 个实验文件全部已受 Git 管理，另补充 55 份本机保存的日志和诊断记录，共约 39.57 MiB，其中 42 份为日志、11 份为 JSON、2 份为 CSV。8 份空日志也保留。

## 来源与位置

| 内容 | 本次归档位置 | 说明 |
| --- | --- | --- |
| 原生服务日志 | `sources/artifacts/native/` | formal、pilot、pilot2、pilot3 各六服务，共 24 份；另保留采样器试验数据 |
| 原生 Nginx 文件日志 | `sources/native-wsl/opt/e1-native/logs/` | access、error、nginx-main 共三份，来自专用 WSL 内部 |
| 原生初次启动与诊断 | `sources/native-lab/` | bootstrap 的八份日志、smoke 结果、镜像来源与原容器快照 |
| 六容器保留日志 | `sources/docker-retained/` | frontend、三个后端、MySQL、MinIO 的完整现存日志快照 |
| API 验收与连接诊断 | `sources/artifacts/functional/`、`sources/artifacts/e1/` | 包含早期失败与后来通过的记录，按源目录保留 |

[manifest.json](manifest.json)逐文件记录源路径、原文 SHA-256、归档 SHA-256、字节数、行数、源文件修改时间与容器日志配置。原文留在本机，公开副本只做凭证脱敏、UTF-8/LF 归一和行尾空白清理；时间、状态、耗时及业务编号保留。

[existing-records.json](existing-records.json)索引此前已提交的全部实验文件，保存仓库路径、Git blob 标识和大小，参照提交为 `3246a73`。Git blob 对应仓库中的标准字节内容，不受 Windows 检出时换行转换影响。例如可用 `git show 3246a73:experiments/E1/20261116-e1-native-formal-summary/matrix.json` 取回当时的记录。

[audit.json](audit.json)记录归档核验：55 份源文与副本哈希通过、42 份日志行数保留、1,698 个原有 Git 文件标识一致，已核对本机现存文本来源的覆盖情况。

## 论文引用范围

正式结果仍以 [E1 报告](../../../docs/exp/E1-results.md)和 [E2 报告](../../../docs/exp/E2-results.md)指定的批次为准：容器 E1 为 `20261116-e1-formal-ipv4` 与 continuation 的 P4，原生 E1 为 `20261116-e1-native-formal`，E2 为 `20261116-e2-formal`。本轮排除 P5，已产生的两轮上传与暂停记录继续保留。

试跑、初始化失败、localhost 中断批次和 API 早期失败记录用于解释准备过程，与正式性能数据分开引用。原生 Nginx 文件日志累计覆盖多个原生批次，沿用源格式，其中 access 日志原本不含时间戳。容器快照截至 UTC `2026-11-16T14:05:02.800653+00:00`，包含启动、实验和恢复后的活动，不能整体当作某一轮的测量窗口。

快照只包含 Docker 当前仍保留的日志；已移除容器或已经轮转丢弃的内容无法补回。E2 已移除测试容器的证据以此前保存在 `experiments/E2/20261116-e2-formal/` 的各阶段日志为准。本索引没有补造缺失日志。

## 归档工具与核验

```powershell
python -m unittest discover -s scripts/deployment -p test_archive_experiment_logs.py
python scripts/deployment/archive_experiment_logs.py --name <新的唯一归档名> --native-wsl
```

先提交 `experiments/` 中已有记录，再使用全新的归档名。工具只读采集业务日志；`--native-wsl` 用于已停止的专用原生环境，读取文件后关闭该发行版。检测到原生实验进程仍在运行时会拒绝采集，保留其运行状态。其他环境可省略该参数。

私有账号文件、JWT、提取码、内部凭证不入库；归档副本中的对应内容统一遮蔽。镜像导出包、VHDX、编译缓存和数据库数据文件不属于本日志归档。每次归档生成新快照，不覆盖已有证据。
