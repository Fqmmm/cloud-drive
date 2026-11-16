# 实验一进度

2026-11-16，组长/C 授权执行 E1，另授权加入 20 MiB 扩展。开发分支 feat/e1-performance，起点 7f55913。

- 不含故障注入的功能冒烟 86/86 通过，结果在忽略的 artifacts/functional/20261116T040732Z/。
- 基础矩阵 36 轮；扩展 20 MiB 上传/下载各 5 VU、三次，共 42 轮。
- 正式参数为每轮 30 秒预热、120 秒测量、至少 30 秒冷却，固定窗口最少 126 分钟，准备/收尾另计。
- 工具为 Windows 宿主 Python 封闭负载，独立 Engine API one-shot 采集进程，约 1 秒读取六个容器。
- 工具链试跑过程保留：pilot 首次长连接采样缺三容器；pilot2/pilot3 在 P2 收尾 SQL 缺默认库时中止。
  修正后 pilot4 的 P2/P3/P4/P5U/P5D 五轮完整通过，53 个正式短窗口请求零失败；P1 已在 pilot3 通过。
  试跑与失败记录均不进入正式性能汇总。
- 统计已知答案测试两项通过：窗口后成功完成不计窗口 RPS，超时仍计失败；三轮 P95 使用中位数与范围。
- 前后 SHA-256、私有数据、配额恢复、物理对象清理和六容器采样均已试跑核验。
- 正式环境：Docker 4 CPU、4107522048 字节内存，Windows 主机 Intel Core Ultra 9 285H、16 逻辑 CPU、约 31.50 GiB 内存。
  业务使用 WSL2 命名卷，只有初始化脚本绑定 Windows 路径。应用镜像沿用本地部署已验证版本，不重建镜像。

下一步：冻结工具提交并推送后，执行 `python -u scripts/performance/run.py --batch 20261116-e1-formal`。
实际进度持久保存在 experiments/E1/20261116-e1-formal-summary/matrix.json，逐轮 execution.log 可查当前阶段。
凭证仅保存在被忽略的 artifacts/e1/<batch>/fixtures.local；公开原始数据不包含密码、JWT、分享 token/提取码。
正式矩阵完成后复算、绘图、检查缺样/错误/清理，再提交实验结果与报告。
