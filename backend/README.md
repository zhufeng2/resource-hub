# 网页与 ChatGPT 搜索服务

在网页或 ChatGPT 中搜索网盘资源，两个入口共用账号和每日额度。默认每账号每天可搜索 5 次，北京时间零点重置。

## 网页使用

打开服务域名即可输入搜索；执行搜索时按提示登录。

- **搜索主页**：当前页面内展示结果，支持筛选、链接检测、翻页和 TXT/CSV/JSON 导出。搜索词与条件保存在 URL 中。
- **搜索设置**：在搜索框下方展开，修改网盘类型、来源、匹配方式和展示选项；支持保存、恢复默认和导入导出。
- **账户信息**：点击头像查看已用次数、剩余额度和重置时间。
- **个人主页**：查看搜索记录、连接搜索源、管理密码和 ChatGPT 授权；管理员可管理用户。

搜索源账号支持 QQ 频道、观影、盘链、微博和蜗牛。可用项目以 PanSou 后端启用的插件为准。绑定流程支持二维码、账号密码及盘链验证码/邮箱确认；各搜索源需要后端提供对应版本的接口。

## 连接使用

1. 向管理员获取服务地址和账号。
2. 在 ChatGPT 的插件或连接设置中添加自定义 MCP 服务，填写服务地址，例如 `https://search.example.com/mcp`。
3. 选择 OAuth 认证，跳转到登录页后输入账号密码并授权。
4. 回到 ChatGPT，在聊天中选择该服务，即可搜索。

示例：

- “搜索某部电影。”
- “查看下一页结果。”
- “我今天还可以搜索几次？”

成功搜索计 1 次，零结果也计次；失败不扣次数，结果翻页和额度查询免费。结果可在 24 小时内查看。链接有效性和文件内容需另行核实。

## 目录

网页位于 `web/`，MCP 与 OAuth 位于 `gpt/`；`backend/` 提供共用逻辑及统一部署入口。

## Linux 部署

准备 Docker Engine、Compose 插件，以及解析到服务器的专用域名。服务器需可访问 PanSou，入站 TCP 80/443 端口需可用。Caddy 自动配置 HTTPS 证书。

以下命令均在仓库根目录执行。

### 1. 配置服务

```bash
cp backend/.env.example backend/.env
chmod 600 backend/.env
```

编辑 `backend/.env`：

| 变量 | 配置说明 |
| --- | --- |
| `PUBLIC_BASE_URL` | 服务域名，例如 `https://search.example.com`，不带路径 |
| `PANSOU_BASE_URL` | PanSou 服务的 HTTPS 地址 |
| `PANSOU_API_TOKEN` | 搜索服务的 API Token |
| `PANSOU_USERNAME` / `PANSOU_PASSWORD` | 也可使用账号密码，需同时设置；Token 优先 |
| `OAUTH_REDIRECT_URIS` | ChatGPT 连接管理页面显示的完整回调地址；多个地址用逗号分隔 |
| `DEFAULT_DAILY_LIMIT` | 新账号默认每日额度，默认 5 次 |
| `SEARCH_CONCURRENCY` | 同时执行的搜索数量，默认 4 |
| `SEARCH_TIMEOUT` | 上游单次请求超时秒数，默认 25 |
| `PANSOU_ALLOW_HTTP` | 使用内部 HTTP 地址连接 PanSou 时设为 `true` |
| `SOURCE_SITE_HOSTS` | 管理员可配置的观影/蜗牛镜像域名，逗号分隔 |

PanSou 的访问凭据保存在服务器配置中，网页和 MCP 用户由本服务数据库管理。PanSou 应仅允许此服务通过内部网络或访问白名单连接。回调地址需严格匹配，示例使用 `https://chatgpt.com/connector_platform_oauth_redirect`，以实际连接页面为准。

### 2. 启动

```bash
docker compose --project-directory backend --env-file backend/.env -f backend/compose.yaml up -d --build
```

服务启动后，访问 `https://你的域名/healthz` 检查状态。如果 HTTPS 证书申请失败，检查域名解析、80/443 端口和 Caddy 日志。

如需同时部署 PanSou 后端，在 `.env` 中配置 `PANSOU_USERNAME`、`PANSOU_PASSWORD` 和强随机的 `PANSOU_JWT_SECRET`，使用附加配置启动：

```bash
docker compose --project-directory backend --env-file backend/.env -f backend/compose.yaml -f backend/compose.pansou.yaml up -d --build
```

此配置通过内部网络连接 PanSou，其 8888 端口不映射到宿主机。可用 `PANSOU_PLUGINS` 指定启用的插件。管理命令也需使用相同的两个 `-f` 参数。

### 3. 创建账号

```bash
docker compose --project-directory backend --env-file backend/.env -f backend/compose.yaml exec app python -m backend.manage add-user admin --admin
docker compose --project-directory backend --env-file backend/.env -f backend/compose.yaml exec app python -m backend.manage add-user bob --limit 5
```

按提示输入至少 12 个字符的密码。使用 `admin` 账号管理用户。首次通过命令创建，之后可在网页“账号 → 用户管理”中创建其他用户。已有账号可用 `python -m backend.manage make-admin alice` 设置为管理员。

验证 PanSou 配置：

```bash
docker compose --project-directory backend --env-file backend/.env -f backend/compose.yaml exec app python skills/resource-hub/scripts/search.py --auth-test
```

### 4. 配置 ChatGPT 连接

服务地址填写 `https://你的域名/mcp`。认证选择 OAuth；如需选择客户端注册方式，使用 **DCR 动态注册**，Token 端点认证方式为 **`none`**，使用 **PKCE S256**。

确认 ChatGPT 页面显示的回调地址已加入 `OAUTH_REDIRECT_URIS`。修改环境配置后重新创建容器使其生效，再验证登录、搜索和额度查询。

参考：[MCP 认证文档](https://developers.openai.com/plugins/build/auth)、[连接与测试](https://developers.openai.com/plugins/deploy/connect-chatgpt)。

## 管理账号

在下面命令前加上 `docker compose --project-directory backend --env-file backend/.env -f backend/compose.yaml exec app`，即可在容器内操作：

```bash
python -m backend.manage list-users
python -m backend.manage set-limit alice 10
python -m backend.manage disable-user alice
python -m backend.manage enable-user alice
python -m backend.manage reset-password alice
python -m backend.manage cleanup
```

停用账号或重置密码会撤销已有授权。重新启用后需再次登录。每日额度设为 0 可暂停新搜索；修改 `DEFAULT_DAILY_LIMIT` 只影响之后创建的账号。

## 工具与额度

| 工具 | 功能 | 计次 |
| --- | --- | --- |
| `search_resources` | 按关键词搜索，每次最多保存前 200 条结果 | 成功计 1 次 |
| `get_search_results` | 根据 `search_id` 翻页，每页最多 50 条 | 免费 |
| `get_quota` | 查看已用、剩余和进行中的次数，以及下次重置时间 | 免费 |

- 按搜索开始时的北京时间日期计次。
- 并发搜索先预占额度，失败或取消后归还；进程意外退出的预占在 180 秒后失效。
- 重试时复用相同的 `request_id` 和搜索词，可避免重复计次；省略 ID 的调用视为新搜索。
- 每账号每分钟最多调用搜索工具 30 次。
- 结果按账号隔离，24 小时后不可读取；搜索记录和计数最多保留 31 天。

## 运维与备份

账号、授权和用量保存在 `app_data` 卷中的 SQLite 数据库。重建容器会保留数据；`docker compose down -v` 会删除数据卷。

备份时停止应用后复制数据卷，或使用 SQLite 在线备份接口。数据库使用 WAL 模式，直接复制正在写入的单个数据库文件可能遗漏数据。备份包含搜索记录和认证信息，请限制访问权限。

生产服务通过 HTTPS 网关访问，应用 8000 端口仅供内部网络使用。Compose 中的转发头信任设置适用于此网络布局；自定义部署时应指定实际代理 IP。HTTP 访问日志默认关闭，额外配置日志时需对授权码和令牌脱敏。

## 开发

需要 Python 3.10+。在仓库根目录安装依赖：

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r backend/requirements.txt
```

通过运行环境注入配置变量，然后创建账号并启动服务。直接运行时需自行加载环境变量：

```bash
umask 077
python -m backend.manage add-user alice
uvicorn backend.app:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

离线测试：

```bash
python -m unittest backend.tests.test_service -v
```

测试命令加入网页集成验证：

```bash
python -m unittest backend.tests.test_service backend.tests.test_web -v
```

测试覆盖网页与 OAuth 登录、MCP 调用、并发额度、账号隔离、管理权限和授权撤销。部署后需在实际域名下验证登录、搜索和搜索源绑定。
