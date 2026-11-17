# E4 正式结果批次

MySQL、MinIO 各三次保留卷重建完成，另有永久删除一致性及独立项目/新卷恢复。结果报告见 [E4-results.md](../../../docs/exp/E4-results.md)，完成状态见 `manifest.json`。

六轮中目标容器 ID 均改变，原卷和挂载目标保持不变；稳定元数据、记录数、对象键和大小一致。每轮 18/18 次个人与两种分享下载的字节数/SHA-256 匹配，共 108/108，权限检查通过。基线、收尾及恢复系统另外各有 18 次下载核验，均通过。

`baseline/`、逐轮 `before/after/verification/`、`deletion/` 和 `backup-restore/` 保存完整证据。`persistence-summary.csv` 给出容器 ID、原卷、挂载路径与校验汇总；`evidence-index.json` 覆盖正式 E3/E4、原验收和样本记录，保存规范化公开文件的字节数与 SHA-256。

备份恢复使用同一停写窗口的三库和对象副本，在不同项目及新卷上导入、设置私有桶后核验。公开备份清单仅含对象键、大小及哈希，SQL/对象备份与凭证留在私有 `artifacts/liu/20261117-154613/`。恢复耗时包括目标环境启动及业务校验，不作为自动重启时间。

`delivery-audit.json` 保存独立交付复核结果；对应逻辑见 `audit_delivery.py`。该审计脚本同时核对原本机的私有备份，需要原私有目录；其他组员离线复算公开指标使用 `scripts/experiments/analyze.py`。审计报告中的服务状态截止时间为实验收尾时刻，审计时间不代表另一次实时 Docker 巡检。
