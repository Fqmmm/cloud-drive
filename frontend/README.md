# 课程版前端

复用原 Vue 3 / Element Plus / UnoCSS 项目，`src/main.ts` 只加载 `src/course/` 的课程入口。
原完整网盘源码通过 Git 与旧目录保留，不在课程路由和类型检查范围加载。
当前支持个人注册、登录、基础资料、刷新登录状态、退出和课程导航；文件/分享将在后续提交接入。
不加载旧插件、动态权限菜单、团队、会员、私密空间、回收站或 SSE。

## 开发

已验证 Node 24.11.0 / pnpm 10.32.1，要求 Node ^20.19.0 或 >=22.12.0。
依赖按 `pnpm-lock.yaml` 固定；首次安装使用 `pnpm install --frozen-lockfile --ignore-scripts`。
此次未启用 Husky，也未将现有钩子配置视为已运行；格式与检查显式执行。

```powershell
pnpm dev
pnpm exec vue-tsc --noEmit
pnpm exec vite build
pnpm exec eslint src/main.ts src/course vite.config.ts
pnpm exec prettier --check src/main.ts src/course vite.config.ts tsconfig.json package.json
pnpm exec stylelint src/course/course.css
python script/code_check.py -d src
pnpm exec playwright test --config playwright.course.config.ts
```

开发入口 `http://127.0.0.1:5173`，hash 路由。开发代理配置 `AUTH_PROXY_URL`、`FILE_PROXY_URL`、
`SHARE_PROXY_URL`，默认分别为本机 8081/8082/8083；完整保留 `/api/v1`，页面代码不带内部服务地址。
部署由 Nginx 同源转发，镜像与路由在 A 运行交付阶段补齐。
`tsconfig.json` 明确检查课程入口、课程组件、自动导入声明和 Vite 配置；不宣称旧完整网盘类型已通过。

## 验证记录

2026-11-15 类型与构建通过，课程改动 ESLint/Prettier/Stylelint、课程目录自定义检查通过。
生产包包含整个 Element Plus，Vite 提示大于 500 kB 的 chunk，为体积提示，不影响运行。
全量自定义检查有 11 项原有问题，位于 BpmnViewer、旧 share、config、invitation、team 页面；
新增课程目录没有这些问题，未为通过检查改动旧页面或添加忽略规则。
2 项 Chromium 开发测试通过：以明确的 API 替身验证表单/导航、刷新退出、过期凭证和网关错误。
这些浏览器测试不代替真实 API 与最终 AB 联调。既有 tests/e2e 含移出课程范围的旧用例，保留但本轮不作为课程验收。
