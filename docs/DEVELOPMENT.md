# 开发指南

面向修改网页、搜索服务和本地 Skill 的贡献者。在线使用见[网页指南](../web/README.md)，正式部署见[部署指南](../backend/README.md)。

待开发的页面与功能见[开发规划](ROADMAP.md)。

## 项目结构

| 目录或文件 | 用途 |
| --- | --- |
| `web/app.py` | 网页路由、会话与同源 JSON API |
| `web/static/` | HTML、CSS、JavaScript 与 favicon |
| `backend/mcp/server.py` | MCP 搜索、结果、额度及夸克工具 |
| `backend/mcp/oauth.py` | OAuth 注册、授权、令牌交换和元数据 |
| `backend/` | 账号、存储、上游适配、搜索及额度逻辑 |
| `skills/resource-hub/` | 仅 MCP 流程说明，无本地运行脚本 |
| `install.py` | 本地 Skill 安装和更新 |
| `update.sh` | Linux 服务器拉取、构建与更新 |

网页、MCP 和 OAuth 共用服务入口 `backend.app:create_app`。前端不需要单独构建，静态资源由服务的 `/assets/` 路由提供。

## 本地启动

在线服务使用 Python 3.12（与 Docker 一致）。在仓库根目录创建虚拟环境并安装依赖：

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r backend/requirements.lock
```

通过当前终端或开发环境注入配置。下面是仅绑定本机的开发地址：

```bash
export PUBLIC_BASE_URL=http://127.0.0.1:8000
export DATABASE_PATH=.cache/dev/service.sqlite3
```

另外配置实际可用的 `PANSOU_BASE_URL` 及认证变量，名称见 [部署配置](../backend/README.md#1-下载与配置)。本地地址允许 HTTP；面向外部使用应配置 HTTPS。开发数据库与正式部署数据库应分开。

创建开发账号并启动：

```bash
umask 077
python -m backend.manage add-user admin --admin
uvicorn backend.app:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

打开 [http://127.0.0.1:8000](http://127.0.0.1:8000)。不要直接打开 `web/static/index.html`：`file://` 无法提供 `/assets/` 和 `/api/` 路由。

开发时前端文件由服务直接读取；后端代码修改后重启进程。真实搜索需要可用上游，下面的离线测试则使用模拟上游。

## 网页接口

| 路径 | 方法 | 功能 |
| --- | --- | --- |
| `/`、`/profile` | GET | 搜索页与个人主页 |
| `/assets/*` | GET | 静态资源 |
| `/api/session` | GET | 会话、CSRF Token、用户配置与额度 |
| `/api/login`、`/api/logout` | POST | 网页登录与退出 |
| `/api/search` | POST | 创建搜索，接受 `query`、`request_id` 等字段 |
| `/api/results/{id}` | GET | 读取已有结果 |
| `/api/history` | GET / DELETE | 读取或清空当前账号的搜索记录 |
| `/api/history/{id}` | DELETE | 删除该账号同一关键词的记录与已保存结果，不返还额度 |
| `/api/preferences` | PUT | 更新设置 |
| `/api/catalog` | GET | 上游启用的来源 |
| `/api/mcp-token` | GET / POST / DELETE | 当前登录用户查看、生成或撤销个人 MCP Token；写操作要求 CSRF |
| `/mcp` | MCP Streamable HTTP | 助手工具入口 |
| `/healthz` | GET | 应用健康状态 |

写请求需携带当前会话的 `X-CSRF-Token`，浏览器 `Origin` 与 `PUBLIC_BASE_URL` 一致。前端只调用同源 API，不直接向上游提交登录凭据。完整路由以 `web/app.py` 为准。

## 自动检查

在仓库根目录运行：

```bash
python -m unittest discover -s backend/tests -t . -v
python3 skills/resource-hub/tests/test_workflow.py
python3 -m compileall -q install.py backend web skills/resource-hub/scripts
bash -n update.sh
bash -n skills/quarkclouddrive/scripts/install.sh
bash -n skills/quarkclouddrive/scripts/uninstall.sh
```

服务测试覆盖 OAuth、网页、MCP、并发额度、账号隔离、权限与授权撤销，不使用真实 PanSou 账号进行搜索。前端脚本也可使用 Node.js 做语法检查：

```bash
node --check web/static/startup.js
node --check web/static/app.js
node --check web/static/accounts.js
node --check web/static/controls.js
```

安装 Playwright 及其 Chromium 后，运行 `node web/tests/mobile-login.cjs`：手机宽度下登录页必须位于普通文档流（没有 fixed 祖先），视口高度变化时输入框不丢焦点，关闭后重新打开会清空密码；桌面宽度下仍打开原生对话框。可用 `CHROME_CHANNEL=chrome` 使用本机 Chrome，或用 `BROWSER=webkit` 检查 WebKit。此测试模拟视口变化，真实软键盘的弹出与收起仍需在手机浏览器复测。

## 网页回归检查

在桌面和手机尺寸检查：

1. 搜索框 Enter、清除、关键词修改、搜索失败重试与空结果。
2. 刷新、前进、后退及已有搜索结果恢复，确认恢复不会重复搜索。
3. 搜索设置的打开、独立滚动、恢复默认、保存、配置导入导出。
4. 弹窗 Escape 关闭、焦点返回和键盘操作，下拉菜单选项与原生值同步。
5. 登录、退出、登录过期、额度不足、账户信息与个人主页各栏目。
6. 搜索记录标题打开结果、垃圾桶直接删除、清空确认与取消、首页同步和刷新后不再出现，确认其他账号及已用额度不受影响。
7. 手机菜单不透出背景文字，键盘打开后输入和保存按钮仍可访问。
8. 页面中心线、横向溢出、长标题、长账号名及“减少动态效果”设置。
9. 首页和授权页的 favicon、静态资源及控制台错误。

使用临时数据库和模拟上游进行反复验证，真实部署完成后再检查实际搜索源和登录回调。不要把开发账号、模拟结果或设备绝对路径写入公开使用文档。

## 界面维护

结构样式位于 `style.css` 与 `interface.css`，最终视觉样式位于 `glass.css`。修改前查看[界面设计规范](../web/design/glassmorphism.md)，避免单个组件覆盖后造成颜色、透明度或对齐方式不一致。

MCP 流程说明位于 `skills/resource-hub/SKILL.md`，旧 Skill 的脚本和测试已经移除；业务实现只维护在服务端。第三方文件的来源与范围见 [THIRD_PARTY.md](../THIRD_PARTY.md)。

## 审计与缓存

安全边界和部署限制见[部署指南](../backend/README.md)。本地 `.cache/*-qa/`、`.cache/npm/`、`.cache/ms-playwright/` 和 `__pycache__/` 可在测试结束后删除。`node_modules/` 是可重新安装的开发依赖。不要整目录删除 `.cache/`：其中可能有开发数据库，`.cache/update/` 还存放部署锁、版本记录与迁移备份。不要把 `docker compose down -v` 或 `docker volume prune` 当作清理缓存使用。


## 夸克 MCP 开发验证

`backend/quark.py` 按已验证的用户身份取出加密凭据，以标准输入调用 `backend/quark_client/runner.cjs`。Node.js 18+ 由服务端提供；本地流程说明不执行脚本。网页 `/api/quark-account` 的 POST/DELETE 要求登录、同源和 CSRF，GET 只返回绑定状态。

```bash
python -m unittest discover -s backend/tests -t .
node --test backend/quark_client/runner.test.cjs backend/quark_client/workflows/manage.test.cjs backend/quark_client/workflows/reset-progress.test.cjs
node web/tests/quark-account.cjs
```

浏览器测试需要 Playwright 和已安装 Chrome，只使用模拟页面与临时凭据，不访问真实网盘。手机登录回归仍用 `web/tests/mobile-login.cjs`。测试通过不代表真实搜索、建目录或转存完成；实际接口验证应另有明确范围和证据。
