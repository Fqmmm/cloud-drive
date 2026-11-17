# 无故障 I/O 异常复现

该批不是正式 E3/E4。重建带分类日志的文件/分享服务后，使用原测试样本进行相同的 1 Hz 并行探测，没有注入故障。

共 1,062 条记录，1,061 成功；`personal_download` 第 116 个 tick 返回 HTTP 503 / DEPENDENCY_UNAVAILABLE，用时约 33 ms，检测后停止探测并核验样本。结束后的文件校验通过。

文件服务 UTC `2026-11-17T07:17:08.011Z` 的 `storage_failure operation=open errorType=IOException`，与 Nginx 同时刻 GET 503 对应，定位为打开 MinIO 对象流的异常。该版探针自发请求 ID 被 Nginx 重写；因此旧批按请求时间区间、方法和状态匹配，不声称两个不同 ID 相等。后续修正由响应头回传实际服务 ID。

`result.json`、`probe.csv`、容器/源码快照、重建日志、服务日志与校验结果保留。工作区含尚未提交的观测代码，具体输入哈希和 Git 状态见 before/；对应 Java 单元测试在构建中执行，分享服务 7 项通过。后续 GET 连接恢复修正使用新诊断编号，保留本次现场。
