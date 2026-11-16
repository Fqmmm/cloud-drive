# Windows 本地六容器部署

从仓库根目录使用 PowerShell 7。先打开 Docker Desktop，等待 Linux 引擎显示 Engine running。
不需要宿主机安装 Java、Maven、Node 或 pnpm，四个应用镜像均从源码构建。

```powershell
pwsh -NoProfile -File scripts/deployment/start.ps1
```

脚本首次生成根目录 `.env`，为各数据库账号、MinIO、JWT 和内部调用生成独立随机凭证；
后续启动保留该文件。实际凭证不输出、不提交。`.env.example` 仅提供配置名及占位值。
初始化配置后，也可以直接从根目录执行计划中的启动命令：

```powershell
docker compose up -d --build
docker compose ps
```

默认地址为 <http://localhost:8080>。只有 frontend 发布到本机回环端口；其他五个服务仅在容器网络可达。
若端口已占用，同时修改 `.env` 的 HTTP_PORT 和 PUBLIC_BASE_URL，再重新启动。
文件和数据库使用当前项目的 mysql_data、minio_data 命名卷；不要改变项目名后误接入空卷。
MySQL 全新卷自动建库、授权及建表，文件服务自动创建私有桶，无需手动导入 SQL 或建桶。
健康依赖按 MySQL/MinIO、认证/文件、分享、前端的顺序等待。

```powershell
# 停止并保留数据
docker compose stop
# 使用已有镜像恢复
docker compose up -d --wait
# 查看最近日志（不要公开包含敏感内容的完整输出）
docker compose logs --tail 80 auth-service file-service share-service
```

`docker compose down` 保留命名卷。不要使用 `down -v`；已有卷的密码必须和首次初始化一致，
删除或重新生成 `.env` 不会修改数据库中的账号密码。

原 Quay/Docker Hub MinIO 来源在本机返回 401/拒绝拉取。用户已允许选择可运行的 MinIO 版本，
根编排使用 [dappros 的 MinIO 归档镜像](https://hub.docker.com/r/dappros/minio)，固定 manifest digest，
对应 RELEASE.2025-09-07T16-13-09Z。该镜像身份与旧开发机记录不同，不声称它们逐字节相同。
实际版本、健康命令与存储互操作由本地验收确认。MINIO_IMAGE 可覆盖为其他已验证来源，
镜像变更后重新验证自动建桶、匿名拒绝、上传下载和分享。

默认单文件 100 MiB、每用户 10 GiB。调大 MAX_FILE_BYTES 时须同时调整 MAX_REQUEST_SIZE、
frontend/nginx/default.conf 的 client_max_body_size 并重建前端；前端显示限制由构建参数自动同步。

## 功能验证

FR-01—FR-12 以 [功能需求](functional-requirements.md)为准。测试在当前根 Compose 上创建随机测试账号，
通过同源前端访问 API，并使用两个已登录浏览器和一个匿名浏览器。需要 Python、requests、Playwright 和 Chromium；
本机这些依赖已经具备。其他开发机如需准备测试依赖，可执行 `python -m pip install requests playwright` 和
`python -m playwright install chromium`。运行服务本身不需要这些测试依赖。

```powershell
# API 与真实页面流程；会短暂停止本项目的文件服务和 MinIO，并在 finally 中恢复
python -u scripts/smoke/functional.py --with-outages
# 仅 API 或仅浏览器复验
python -u scripts/smoke/functional.py --api-only --with-outages
python -u scripts/smoke/functional.py --browser-only
```

自定义入口时传 `--base-url http://localhost:<端口>`，与 PUBLIC_BASE_URL 保持一致。
超额和到期用例只调整本次临时账号的配额与临时分享到期时间，不修改表结构；配额测试后恢复。
临时账号与分享历史保留在本地库中，测试脚本清理其 API 样本文件；不输出密码、JWT、提取码或完整分享地址。
上传断网及截断下载由测试注入；依赖停止/恢复为真实容器操作。结果写入 Git 忽略的 artifacts/functional/<UTC批次>/。

本轮结果和环境记录在 [本地验收记录](local-validation.md)，正式 E1—E4 实验另行执行。
