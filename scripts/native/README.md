# 非容器 E1

专用环境为 `CloudDrive-E1-Native`，存放于 `D:\CloudDriveLab\E1Native`。P1—P4 的业务代码和二进制来自既有 E1 冻结镜像，测量时六个服务以普通进程运行。

```powershell
python scripts/native/prepare.py
```

准备命令要求目标目录全新，不覆盖现有发行版。它从未启动的临时容器导出原镜像文件系统，再用 WSL 导入到 D 盘；
原数据库/MinIO 卷不参与导出。临时容器及其本轮新建匿名卷在导出后移除，原有容器、卷和凭证保留。
参照 [Microsoft 自定义 WSL 导入流程](https://learn.microsoft.com/en-us/windows/wsl/use-custom-distro)。

本轮不运行 P5。最终报告与对照解释放在 docs/exp，原始请求和资源记录放在 experiments/E1。
