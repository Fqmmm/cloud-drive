# 实验工具离线验证

这些结果验证新工具的调度、超时、权限隔离、证据判断与统计逻辑，使用临时本机 HTTP 服务及合成数据。不属于 E3/E4 的真实故障或持久化测量，不进入论文的实验结果表。

`result.json` 保存最终测试命令、UTC 和退出码，`unittest.log` 保存该次输出。Python AST/compileall、四个入口 `--help`、PowerShell AST 检查通过；已有 `scripts/smoke/test_context.py` 的 1 项上下文回归也通过。

验证中一次输出采集器错误地按 UTF-8 解码系统默认编码的子进程 stderr，导致采集器自身 UnicodeDecodeError。保留其原因说明，不据此认定业务结果。设置 `PYTHONUTF8=1` 后完整重跑通过；PowerShell 正式入口设置该变量并在结束时恢复原值。

真实六容器仍由用户本机 PowerShell 运行：当前 Codex 会话无 Docker 管道访问权限。执行与交接状态见 [docs/liu-progress.md](../../../docs/liu-progress.md)。
