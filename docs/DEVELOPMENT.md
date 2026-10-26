# 开发指南

面向修改网页、搜索服务和本地 Skill 的贡献者。在线使用见[网页指南](../web/README.md)，正式部署见[部署指南](../backend/README.md)。

## 项目结构

| 目录或文件 | 用途 |
| --- | --- |
| `web/app.py` | 网页路由、会话与同源 JSON API |
| `web/static/` | HTML、CSS、JavaScript 与 favicon |
| `gpt/server.py` | MCP 搜索、结果与额度工具 |
| `gpt/oauth.py` | OAuth 注册、授权、令牌交换和元数据 |
| `backend/` | 账号、存储、上游适配、搜索及额度逻辑 |
| `skills/resource-hub/` | 本地资源搜索、核验与任务流程 |
| `skills/quarkclouddrive/` | 夸克官方技能定义、参考文档及安装脚本 |
| `install.py` | 本地 Skill 安装和更新 |
| `update.sh` | Linux 服务器拉取、构建与更新 |

网页、MCP 和 OAuth 共用服务入口 `backend.app:create_app`。前端不需要单独构建，静态资源由服务的 `/assets/` 路由提供。

## 本地启动

需要 Python 3.10+。在仓库根目录创建虚拟环境并安装依赖：

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r backend/requirements.txt
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
| `/api/history` | GET | 当前账号的搜索记录 |
| `/api/preferences` | PUT | 更新设置 |
| `/api/catalog` | GET | 上游启用的来源 |
| `/api/bindings` | GET / POST | 搜索源账号列表与创建 |
| `/mcp` | MCP Streamable HTTP | 助手工具入口 |
| `/healthz` | GET | 应用健康状态 |

写请求需携带当前会话的 `X-CSRF-Token`，浏览器 `Origin` 与 `PUBLIC_BASE_URL` 一致。前端只调用同源 API，不直接向上游提交登录凭据。完整路由以 `web/app.py` 为准。

## 自动检查

在仓库根目录运行：

```bash
python -m unittest backend.tests.test_service backend.tests.test_web -v
python3 skills/resource-hub/tests/test_workflow.py
python3 -m compileall -q install.py backend gpt web skills/resource-hub/scripts
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

## 网页回归检查

在桌面和手机尺寸检查：

1. 搜索框 Enter、清除、关键词修改、搜索失败重试与空结果。
2. 刷新、前进、后退及已有搜索结果恢复，确认恢复不会重复搜索。
3. 搜索设置的打开、独立滚动、恢复默认、保存、配置导入导出。
4. 弹窗 Escape 关闭、焦点返回和键盘操作，下拉菜单选项与原生值同步。
5. 登录、退出、登录过期、额度不足、账户信息与个人主页各栏目。
6. 手机菜单不透出背景文字，键盘打开后输入和保存按钮仍可访问。
7. 页面中心线、横向溢出、长标题、长账号名及“减少动态效果”设置。
8. 首页和授权页的 favicon、静态资源及控制台错误。

使用临时数据库和模拟上游进行反复验证，真实部署完成后再检查实际搜索源和登录回调。不要把开发账号、模拟结果或设备绝对路径写入公开使用文档。

## 界面维护

结构样式位于 `style.css` 与 `interface.css`，最终视觉样式位于 `glass.css`。修改前查看[界面设计规范](../web/design/glassmorphism.md)，避免单个组件覆盖后造成颜色、透明度或对齐方式不一致。

本地 Skill 的执行协议位于各自 `SKILL.md`，不是普通网页帮助文档。修改其行为时应核对对应脚本和工作流测试。第三方文件的来源与范围见 [THIRD_PARTY.md](../THIRD_PARTY.md)。
