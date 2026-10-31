# 开发指南

[项目首页](../README.md) · [网页与账号](../web/README.md) · [MCP 接入与工具](../mcp/README.md) · [部署与维护](../backend/README.md)

本文集中维护代码结构、接口、开发验证、界面规则和后续规划。部署变量、SMTP、PanSou 网络、生产更新与备份统一在部署指南；工具的用户参数和执行流程统一在 MCP 指南，避免多处维护同一规则。

## 代码与运行链路

| 位置 | 职责 |
| --- | --- |
| `backend/app.py` | 创建服务、请求体与 MCP 认证保护、生命周期和定时清理 |
| `backend/config.py` | 站点地址、数据库路径、搜索运行参数 |
| `backend/store.py` | SQLite、账号、编号计数器、邮箱验证码、Token、额度、记录与加密绑定 |
| `backend/email_verification.py` | 邮箱规范化、会话绑定的验证码证明、受限并发 SMTP/TLS 发信 |
| `backend/service.py` | 共享搜索、限额预占、幂等、仅夸克过滤和结果核验 |
| `backend/upstream.py` | PanSou 认证、搜索、公开来源与链接检测 |
| `backend/mcp/server.py`、`oauth.py` | MCP 工具及 OAuth；根目录 `mcp/` 只放使用文档 |
| `backend/quark.py` | 按用户读取凭据、独立 Node 进程、后台归零及操作记录 |
| `backend/quark_client/` | 部署需要的 Node 接口与工作流；不放研究抓取、中间脚本或凭据 |
| `web/app.py` | 同源网页/API、会话、注册、邮箱和普通用户管理 |
| `web/static/` | HTML、CSS、原生 JavaScript，服务直接读取，无前端构建步骤 |
| `backend/tests/`、`web/tests/` | Python 集成测试和模拟浏览器回归 |
| `skills/resource-hub/SKILL.md` | MCP 流程说明，无本地业务脚本 |
| `install.py`、`update.sh` | 流程说明安装与 Linux 部署更新 |

浏览器通过本站 API 使用搜索和账号功能；MCP 入口校验站点授权后进入同一搜索/存储层。只有服务器访问 PanSou 和用户绑定的夸克。`mcp` 也是第三方 Python SDK 的包名，服务代码放在 `backend/mcp`，不要在根目录文档文件夹创建同名 Python 包遮蔽 SDK。

## 本地运行

Python 3.12、Node.js 18+，安装与 Docker 相同的锁定依赖。在仓库根目录的 Bash 中：

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r backend/requirements.lock
export PUBLIC_BASE_URL=http://127.0.0.1:8000
export DATABASE_PATH=.cache/dev/service.sqlite3
export PANSOU_BASE_URL=https://你的实际上游
export PANSOU_API_TOKEN=你的上游Token
python -m backend.manage add-user admin --admin
uvicorn backend.app:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

PowerShell 可用 `python -m venv .venv`、`.venv/Scripts/Activate.ps1` 创建并激活环境，以 `$env:变量名='值'` 设置相同变量。配置通过进程环境注入；直接运行 uvicorn 不会自动读取 `backend/.env`。仅本机地址允许 HTTP，真实搜索需要可用上游，注册需另外注入 SMTP 变量；配置含义见部署指南。

打开 `http://127.0.0.1:8000`，不直接双击 HTML。前端文件保存后刷新页面，HTML 对资源按内容加版本；后端修改需要重启。开发数据库与生产数据库隔离，不将已知预览账号和测试 Cookie 搬到生产。

## 网页与认证接口

| 路径 | 方法 | 功能 |
| --- | --- | --- |
| `/`、`/profile`、`/assets/*` | GET | 页面与静态资源 |
| `/api/session` | GET | 会话、CSRF、注册开关或当前账号资料、偏好与额度 |
| `/api/login`、`/api/logout` | POST | 用户名密码登录、退出 |
| `/api/register/code`、`/api/register` | POST | 发注册验证码、验证邮箱并创建普通账号 |
| `/api/email/code`、`/api/email` | POST | 已登录账号发验证码、绑定邮箱 |
| `/api/password` | POST | 校验当前密码后更新并撤销授权 |
| `/api/users` | GET / POST / PATCH | 主管理员搜索分页、创建或修改普通成员 |
| `/api/users/{user_id}` | DELETE | 主管理员按目标编号和确认账号名删除普通成员 |
| `/api/search` | POST | 新搜索，接受 `query`、`request_id`、`options`、`refresh` |
| `/api/results/{id}` | GET | 当前账号读取原结果 |
| `/api/history`、`/api/history/{id}` | GET / DELETE；后者 DELETE | 历史列表、清空、删除同关键词记录，不返还额度 |
| `/api/preferences`、`/api/catalog` | PUT；GET | 保存偏好、读取公开插件和频道 |
| `/api/mcp-token` | GET / POST / DELETE | 读取、生成或撤销个人 Token |
| `/api/connections/revoke` | POST | 撤销当前账号 MCP/OAuth 授权 |
| `/api/quark-account` | GET / POST / DELETE | 夸克状态、验证保存 Cookie、解绑 |
| `/api/quark-account/reveal` | POST | 本人页面读取已保存 Cookie |
| `/oauth/register`、`/oauth/authorize`、`/oauth/token` | 依 OAuth 路由 | 客户端注册、授权与交换令牌 |
| `/mcp` | Streamable HTTP | MCP 工具入口 |
| `/healthz` | GET | 应用存活检查，不证明上游可用 |

网页写入要求同源 Origin 与当前 CSRF，匿名注册使用受保护的匿名登录 Cookie，登录后的用户 ID 只从会话取。账号管理只允许名为 `admin` 的启用管理员，列表和搜索排除管理员，API 也禁止修改/删除管理员或通过网页提升权限。普通账号和邮箱均受数据库唯一约束，账号编号在删除后仍不复用。

注册验证码只保存会话/用途绑定的证明，错误尝试落盘，校验成功和账号创建/绑定原子提交。密码哈希计算不长期持有写锁；删除后的迟到会话、偏好写入和旧账号密码变更不能写入新账号。SMTP 不回显授权码、密码或内部错误。

网页和普通 MCP 写请求体上限 16KiB；只有已认证的 `quark_create_text_file` MCP 调用允许最多 256KiB JSON 传输体，以容纳转义和参数，解码后的文本仍限 32KiB。不能扩大其他工具或绑定接口的请求体上限。

所有新搜索、旧记录读取、旧偏好和导入配置都固定夸克，不能通过 URL 或直接传其他类型重新启用多网盘。搜索源账号页面、路由及上游绑定流程已移除。保持 SQLite 短写事务和单机运行模型；数据库迁移需覆盖旧数据、重启与唯一约束测试。

## 自动验证

在仓库根目录运行已存在的测试和脚本：

```bash
python -m unittest discover -s backend/tests -t .
python -m compileall -q install.py backend web
node --test backend/quark_client/runner.test.cjs backend/quark_client/workflows/manage.test.cjs backend/quark_client/workflows/reset-progress.test.cjs
node --check web/static/startup.js
node --check web/static/app.js
node --check web/static/accounts.js
node --check web/static/registration.js
node --check web/static/quark.js
node --check web/static/controls.js
bash -n update.sh
```

Python 测试使用临时 SQLite、模拟上游，覆盖 OAuth、邮箱注册/绑定、SMTP 传输、验证码过期与重放、并发邮箱唯一、普通用户分页、管理员保护、删号清理、编号不复用、额度与夸克隔离。Node 测试覆盖调用边界、目录管理、幂等记录和归零工作流，不依赖真实 Cookie。

浏览器测试需要开发依赖 Playwright 和浏览器，可单独安装到忽略的缓存：

```bash
npm install --prefix .cache/browser-tools --no-audit --no-fund playwright
export NODE_PATH="$PWD/.cache/browser-tools/node_modules"
CHROME_CHANNEL=chrome node web/tests/mobile-login.cjs
CHROME_CHANNEL=chrome node web/tests/quark-account.cjs
```

以上使用本机 Chrome；手机登录测试也支持先准备 Playwright Chromium 或 `BROWSER=webkit` 的 WebKit。浏览器测试通过请求模拟使用临时数据，不登录真实网盘。视口缩放不能完全替代实际手机软键盘测试。

如安装 Bandit、依赖审计工具，分别扫描运行时代码与锁定依赖。更新依赖时同步维护顶层声明 `backend/requirements.txt` 和 `backend/requirements.lock`，再回归；不把历史扫描结果当作新版本持续安全的证明。

## 界面回归清单

1. 桌面与手机：搜索、Enter、清除、失败重试、空结果、长标题与横向溢出。
2. 刷新、前进、后退、已有记录恢复不重复搜索，旧网盘参数仍固定为夸克。
3. 设置打开、独立滚动、恢复、保存和导入导出；没有网盘类型与搜索源账号入口。
4. 注册/登录模式切换、邮箱验证码、过期与限流、绑定邮箱、退出和授权失效。
5. 搜索记录标题、单条垃圾桶、全部清空确认、首页同步与额度不返还。
6. 主管理员只看到普通成员，搜索/分页/创建/编辑/停用/删除；确认输入错误不删除，删除最后一页后回到有效页。
7. 账号操作容器用 flex 居中，编辑与垃圾桶按钮均为 44px 高，按同一中心线对齐；不要依靠行内 baseline 或额外外边距拼齐。
8. MCP Token 与 Cookie 的输入框不嵌套重复边框；默认遮罩，显示、复制、保存、解绑及失败保留原值。
9. 弹窗 Escape、焦点、键盘下拉、减少动态效果，手机输入不被视口变化打断。

## 夸克工作流与验证边界

业务通过 `backend/quark.py` 向独立 Node 子进程的标准输入传递凭据，工具参数不含凭据。操作日志先记录意图再提交写入，按用户、绑定和请求编号隔离。凭据、任务锁和生产备份要求见部署指南；完整工具参数、预览与 `verified` 的含义见 MCP 指南。

模拟成功、HTTP 成功、上游任务结束、元数据回读及实际内容回读必须区分。目录转存只核验顶层选中条目；创建文本要求独立下载回读；归零要求视频进度读回为 0。已有小范围真实验证不能推断全部大目录、格式和容量边界已实测；后台批量等改动以相应模拟/集成测试覆盖，生产验收仍需明确授权范围。

协议采集、官方脚本与中间研究代码维护在独立的 `reverse-engineering-research/夸克网盘` 项目。本仓库只保留部署业务代码、必要测试和流程说明，不复制研究缓存、Cookie 或本地账号配置。

## 界面规范

统一的浅色毛玻璃、蓝色主按钮、系统字体与可访问性规则集中在下面。`style.css`、`interface.css` 负责结构，最后加载的 `glass.css` 决定材质；先核对层叠与公共组件，不为每个局部追加冲突覆盖。删除图标由 `trashButton` 共用，搜索记录和用户列表各自绑定行为，不能混用业务专属禁用选择器。

### 视觉参数

| 元素 | 规范 |
| --- | --- |
| 页面背景 | #F5F5F7，低对比度蓝、米色及灰绿光晕，不使用大幅光带 |
| 普通玻璃面板 | 28% 白色背景、渐变内高光、细灰边框、24px 圆角 |
| 阴影 | 柔和外阴影与受光顶边，避免明显白色描边或厚重黑影 |
| 导航与吸顶区 | 32% 白色背景，无贯穿导航栏的白色分隔线 |
| 模糊 | 桌面基础 24px，弹层 32px；手机基础 30px |
| 饱和度 | 150% |
| 文字 | 标题 #1D1D1F，正文 #515158，说明 #65656D |
| 强调 | 蓝色 #0066CC；主按钮 #0071E3，悬停 #006EDB，文字白色 |
| 字体 | 优先系统字体，依次回退到 Segoe UI、苹方、微软雅黑 |
| 动效 | 500ms 平滑过渡、轻微上浮；不使用装饰扫光 |

手机端账户菜单、账户信息弹窗和登录卡片使用不透明浅色背景 `#FBFCFE`，避免后方文字透入。材质感由圆角、细腻高光与阴影体现。

### 布局与对齐

- 首页标志、标题、说明、搜索框和设置入口共用中心线。
- 限制文字最大宽度时，居中区域同时使用自动水平外边距。
- 页面双侧对称预留滚动条空间，搜索框左右内边距一致。
- 登录介绍、弹窗标题、提示和空状态居中；表单标签、输入内容、结果正文保持左对齐。
- 手机端登录使用普通文档流页面，不要改回 `showModal()` 弹窗：顶层固定元素在软键盘弹出或视口变化时容易丢失输入焦点。
- 登录输入框不要包在 `<label>` 内：使用 `label for` + 同级 `input`。部分安卓 WebView 会对 label 内嵌 input 二次激活，表现为键盘弹出后立即收起。
- 个人主页以分区面板组织内容，内部列表不重复嵌套玻璃卡片。
- 标题与操作文案不添加装饰点号、箭头或省略号；必要的关闭、展开和功能图标保留。

### 手机与可访问性

- 首页顶部间距为 `clamp(32px, 8svh, 64px)`，副标题下方间距 28px；不影响结果页吸顶区。
- 搜索设置使用独立全屏面板，保留安全区、固定操作区和内部滚动。
- 输入控件文字至少 16px，避免移动浏览器聚焦时自动缩放。
- 所有交互有可见焦点和可访问名称，不能仅用颜色传达状态。
- `prefers-reduced-motion` 下关闭动画、过渡和位移。
- 使用长账号、长标题和窄屏检查溢出；降低透明度不能以牺牲文字清晰度为代价。

### 实现入口

`web/static/glass.css` 在结构样式后加载，主要视觉变量位于文件顶部。`startup.js` 在首屏统一应用浅色主题；旧主题字段保留配置兼容性，不提供单独深色切换。首页和 OAuth 授权页共用样式及 favicon。

设计参考：[StyleKit Glassmorphism](https://www.stylekit.top/zh/styles/glassmorphism)。本项目采用其玻璃材质思路，并使用独立的浅色配色、透明度与可读性规则，不要求复现参考页的夜景方案。

## 后续规划

- 已实现搜索主页、个人主页、邮箱注册、普通用户管理和夸克 MCP 操作。
- 待实现站内使用说明页面，在主页提供统一入口；本次只整理仓库文档，不新增页面。
- 自助密码找回、邮箱换绑、任意二进制上传与网盘删除尚未实现，不能在使用文档中描述为可用。

## 本地缓存与第三方来源

测试缓存、Playwright 依赖和 `__pycache__` 可在确认无任务运行后按目录清理。不要整目录删除 `.cache`：其中可能含开发数据库、密钥及 `.cache/update` 的部署记录、锁和迁移备份。生产数据卷不属于缓存。

第三方组件与独立接口库的来源集中在 [THIRD_PARTY.md](../THIRD_PARTY.md)。可选 Skill 仅维护 MCP 使用流程，没有旧 Skill 脚本和测试目录；不要恢复已删除的测试命令或调用官方夸克工具。
