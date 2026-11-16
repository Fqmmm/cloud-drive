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

## 功能核验结果

部署提交 1ab83d6；业务代码沿用 e2c2f04。测试脚本与本记录的最终结果单独提交。
测试依赖使用本机已有的 Python 3、requests、Playwright，Chromium 143.0.7499.4；未使用 computer-use。
API 和浏览器均通过实际根 Compose 的 http://localhost:8080 访问，不使用旧 AB 临时栈或替身业务服务。

| 编号 | 已验证场景 | 结果 |
|---|---|---|
| FR-01 | 个人注册、中文昵称、字段错误、重复账户/邮箱、小写归一、密码散列；页面隐藏密码、重复时保留非敏感字段 | 通过 |
| FR-02 | 登录及基础资料、错密码、缺失/篡改/过期 JWT；页面刷新、退出清除凭证与资料、过期跳转 | 通过 |
| FR-03 | 根目录/子目录、空状态、面包屑、第二用户空间与私有资源操作隔离 | 通过 |
| FR-04 | 去首尾空白、中文空格、非法名称、255/256 边界、重命名、非空拒删、空目录删除、文件/目录同名冲突 | 通过 |
| FR-05 | 上传显示、阻止重复点击、失败重试、100 MiB+1 拒绝、失败不增容量；MinIO 停止时上传 503 | 通过 |
| FR-06 | 本人下载文件名及 SHA-256、重命名保持归属/容量/内容、旧分享使用新名称、截断下载提示与重试 | 通过 |
| FR-07 | 页面永久删除确认、下载失效、重复删除不重复扣额、同名重新上传不复活旧分享 | 通过 |
| FR-08 | 10 GiB 默认容量、目录不计费、上传删除刷新、三个并发上传不超额、待清理对象不计额 | 通过 |
| FR-09 | 公开/保护、多分享、1/7/30 天及永久、实际生成前导零码、非法配置、页面复制及失败不留成功地址 | 通过 |
| FR-10 | 匿名保护页隐藏详情、错码停留、verify 后下载再验、错码限流/正确码绕过、替换 fileId 无效、依赖恢复后原链接可用 | 通过 |
| FR-11 | 本人分享历史、名称快照、状态/到期/取消、跨用户列表和取消隔离、重复取消、一个取消不影响另一个 | 通过 |
| FR-12 | 不存在/过期/取消/源文件删除分别提示；真实 file-service/MinIO 中断返回 503，恢复可再次访问 | 通过 |

文件名比较为 utf8mb4_0900_as_cs，大小写敏感：Case 与 case 可并存。
65536 字节二进制样本 SHA-256：4b640d85ab3ba30fd02c9fc9db4a8928f416322ad27022ea58a65aaee68a4df2。
本人、公开分享和保护分享的浏览器下载均核对文件名与内容。

实际运行及保留证据（目录由 Git 忽略，不含实际凭证）：

- `python -u scripts/smoke/functional.py --with-outages`：20261116T033200Z 批次，先完成 92 项 API 显式检查，全部通过；
  后续浏览器因测试使用了过严的 select 标签定位而中止。该批次整体有 fatal，不能称作完整脚本通过。
- `python -u scripts/smoke/functional.py --browser-only`：20261116T033426Z 批次，27 项通过；
  测试在 hash 导航后直接改 localStorage，没有重建内存会话，过期用例失败。修正为刷新页面后验证。
- 相同浏览器命令：20261116T033658Z 批次，29/29 项显式检查通过，fatal=null。
  最终按“API 92 项 + 浏览器 29 项”交接；API 没有因浏览器测试修正而重复注入故障。
- 原始脱敏 JSON 位于 artifacts/functional/<上述批次>/results.json；联合通过记录为 artifacts/functional/accepted.json。
- 验收后六服务全部 running/healthy，nginx -t 通过，.env 和 artifacts 的 Git 忽略检查通过。

浏览器断网上传和截断下载使用定向故障注入；真实服务的停止/恢复单独由容器用例验证。
临时账号和分享历史保留；失败的早期浏览器轮次可能留下该临时账号自己的样本，不涉及用户已有资料。
未修改 A/B 的业务源码、SQL、JWT 或内部接口契约。本轮未运行旧 Java/前端全量规范检查，
原检查器解析跳过和前端遗留问题见 [AB 记录](ab-validation.md)，不声称全部旧规范通过。
本轮未采集正式 E1—E4 数据，未将停止/启动当作保留卷重建的持久化实验。
