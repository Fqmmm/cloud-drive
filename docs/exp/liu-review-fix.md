# 刘骐语审查问题修正与补充验收

2026-11-17 对提交 `1f3eb29` 的审查发现一项统计口径错误、两项验收证据缺口。本次三项均已修正并验证，不重新注入 E3 故障或重建 E4 容器。

## 失败窗口统计

`failure_window_seconds` 改为 `max(0, t5 - first_failed_returned_epoch)`，与方案中的 t1 定义一致。三次恢复时间、成功率、错误分布及其他字段保持原值。60 行修订，最大减少 3.322687 秒。

原分析器、旧 impact.csv、旧图表来源说明与旧证据索引留在 [统计修订目录](../../experiments/E3/20261117-154613-c1/analysis-revisions/20261117-failure-window-v2/)。[逐行差异](../../experiments/E3/20261117-154613-c1/analysis-revisions/20261117-failure-window-v2/differences.csv)列出旧值、新值和差值。[修订清单](../../experiments/E3/20261117-154613-c1/analysis-revisions/20261117-failure-window-v2/revision.json)保存源码及原始探针哈希。

图表只使用成功计数、恢复时间和原始时间线，未使用该字段。因此保留原 14 份 PNG/PDF 字节，只更新来源说明中的 CSV 哈希，并注明绘图数值不变。原始 probe.csv 未改写。相应回归现在明确校验发出时刻、回包时刻和 0.9 秒失败窗口，避免原测试把错误公式写成预期值。

## 补充验收

采用原项目 `cloud-drive-liu-20261117-154613` 和原六个镜像，新建专用测试账号及目录。北京时间 19:27:30—19:27:43 完成 HTTP 用例，19:29:21 完成前后 Docker 证据核对。原 [121 条验收](../../experiments/acceptance/20261117-154613/results.json)保留，本次 [9 条补充断言](../../experiments/acceptance/20261117-review-supp2/results.json)独立列出，不声称重新跑完浏览器或 E3/E4。

| 项目 | 预期 | 实测 |
|---|---|---|
| 数据库名称比较规则 | 查询实际排序规则 | `utf8mb4_0900_as_cs`，区分大小写 |
| 同目录 Case 与 case 同时存在 | 创建成功、ID 不同、列表同时包含 | 200，ID 为 28/29，列表符合 |
| 原名称仍存在时再创建 Case | 拒绝完全同名 | 409 |
| 255 字符目录名 | 原名完整保存 | 长度 255，符合 |
| 恰好 100 MiB 文件上传 | 104,857,600 字节成功 | 200 |
| 上传容量 | 增加实际字节数一次 | 0 → 104,857,600 |
| 下载内容 | 大小、SHA-256 与源一致 | 200，104,857,600 字节，SHA-256 相同 |
| 删除及重复删除 | 200/404，容量归还一次 | 200/404，容量回到 0 |
| 100 MiB + 1 字节 | 413，无成功记录、无容量增加 | 全部符合 |

100 MiB 样本 SHA-256 为 `4cbf988462cc3ba2e10e3aae9f5268546aa79016359fb45be7dd199c073125c0`。源内容由 0—255 字节序列重复构成，临时文件使用完即关闭；账号密码只留在忽略目录。请求逐条记录方法、路径、时间、HTTP/业务码及实际服务请求 ID，不记录请求正文、JWT 或密码。

结束后原六份样本重新通过 18 次个人/分享下载和 6 项权限检查。测试前后六个容器 ID、镜像 ID 保持一致，均 running/healthy，清理队列为 0。[前置证据](../../experiments/acceptance/20261117-review-supp2/host-before.json)、[结束证据](../../experiments/acceptance/20261117-review-supp2/host-after.json)、[请求日志](../../experiments/acceptance/20261117-review-supp2/api-events.jsonl)和 [原样本复验](../../experiments/acceptance/20261117-review-supp2/original-fixtures-verification/)随批归档。

首个 [补充批次](../../experiments/acceptance/20261117-review-supp/)因 Python 子进程无法访问 Docker 管道，在任何业务用例执行前停止，结果为 0/0、未完成。它保留为失败准备记录，不计入 9 条成功断言。直接 Docker 命令可用，因此后续用直接命令采集只读基础设施证据，以 HTTP 执行业务检查，最后核对后置证据后才将补充批次标为完成。工具支持该两阶段方式，也支持在本机具有正常 Docker 权限时一次执行。

## 后续复算与验证

本轮工具回归 32/32 通过，用时 15.949 秒，见 [回归日志](../../experiments/tool-validation/20261117-liu-review-fix/unittest.log)。新增拒绝错项目、非空队列、缺少服务、过期后置证据、镜像变化及 HTTP 失败被错误提升为完成的检查。

仓库根目录执行：

```powershell
.\artifacts\liu-tools\Scripts\python.exe scripts/experiments/analyze.py --run-id 20261117-154613-c1 --context-run-id 20261117-154613 --supplement-run-id 20261117-review-supp2
```

新环境安装 requests 后也可用普通 Python 复算。此次统计修订入口 `revise_failure_window.py` 只用于一次性修订，已完成时会拒绝再次覆盖修订记录；后续使用普通分析器复算即可。

新增名称/文件边界检查已经接入 `scripts/smoke/functional.py`，未来完整验收会自动覆盖。只运行补充验收可用：

```powershell
.\artifacts\liu-tools\Scripts\python.exe scripts/experiments/supplement.py --env-file artifacts/liu/20261117-154613/.env --run-id <新的批次编号>
```

本轮原业务镜像未重新构建，新增源码和环境工作区状态按补充批次记录。正式发布状态以本轮 Git 提交为准。
