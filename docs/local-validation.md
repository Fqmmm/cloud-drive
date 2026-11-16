# 根 Compose 本地验收记录

日期：2026-11-16。分支：feat/compose-local-deployment，起点 e2c2f04。
本轮由组长/C 接入根编排，目标是先运行系统并按 FR-01—FR-12 检查功能。

## 部署结果

- Windows 11，Docker Desktop Linux Engine 29.9.2，Compose v5.6.1，desktop-linux context。
- 根目录 `pwsh -NoProfile -File scripts/deployment/start.ps1` 成功；四应用源码镜像构建，六服务均 healthy。
- 前端仅发布 127.0.0.1:8080，访问地址 http://localhost:8080；未发布数据库和对象存储端口。
- 三个独立 Maven 工程构建成功，A 的镜像执行 verify；前端类型检查和生产构建成功，保留大 chunk 提示。
- 新建 cloud-drive-course_mysql_data、cloud-drive-course_minio_data；自动建库建表及私有桶，无手工导入。
- 在 MinIO 容器内匿名读取 cloud-drive 返回 403。
- 本机 .env 自动生成独立随机凭证，Git 忽略检查通过；示例和日志未输出实际凭证。
- 用户另行授权删除旧 mysql-dev 容器及其专属匿名卷；test_mysql_data 和本项目两卷保留。

原 MinIO Quay 标签返回 401，Docker Hub minio/minio 拒绝拉取。用户允许使用其他可运行版本，
本轮选 dappros/minio 的固定归档 digest。运行核验为 RELEASE.2025-09-07T16-13-09Z，
commit 07c3a429bfed433e49018cb0f78a52145d4bedeb，Go 1.24.6。
与旧开发机镜像身份不同，按本次实际运行及互操作结果交接。
Docker Hub 曾出现暂时 EOF，重试恢复；一次相同 digest 的 Node 镜像加速拉取成功，未改 Docker 全局配置。

当前运行镜像身份（重新 build 产生的 provenance 可使镜像 ID 改变，复验时重新记录）：

| 服务 | 镜像 ID / digest |
|---|---|
| auth-service | 5f63f257f2f17cc44355fc7024d4281ae4f057247ddee30c9d00b65fa718be18 |
| file-service | af5503ce1bd46fe1f0b9c03604fe416ecc7b484d24f57854d07364868ce4d373 |
| share-service | e086e671d0460d51a8e81304c22ed0b47d4d56b16b96bccaafdd5f6f91a6eb3d |
| frontend | b4de03eb9dcc04f056e6ebc213a0171b281b81384adbf4b60b3b521966196097 |
| mysql | 152cf187a3efc56afb0b3877b4d21e231d1d6eb828ca9221056590b0ac834c75 |
| minio | 624bad2fe79a8613aa3c5c9b765ebcab365080b8445cf1b05c357cc7753725f0 |

## 功能核验进度

已在本次根 Compose 上通过 API 正反向流程，包括双用户隔离、并发配额、100 MiB 超限拒绝、
公开/保护分享、前导零提取码、过期/取消/删除源文件，以及实际停止/恢复 file-service 与 MinIO。
浏览器核验正在收尾，最终按 FR 编号的结果随功能测试交付更新。
本轮未采集正式 E1—E4 数据，未将已有卷停止/启动当作保留卷重建的持久化实验。
