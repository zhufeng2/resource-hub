# 网页与 ChatGPT 搜索服务

在网页或 ChatGPT 中搜索网盘资源，两个入口共用账号和每日额度。默认每账号每天可搜索 5 次，北京时间零点重置。

## 网页使用

打开服务域名即可输入搜索；执行搜索时按提示登录。

- **搜索主页**：当前页面内展示结果，支持筛选、链接检测、翻页和 TXT/CSV/JSON 导出。搜索词与条件保存在 URL 中。
- **搜索设置**：点击搜索框下方的齿轮打开独立面板，修改网盘类型、来源、匹配方式和展示选项；手机使用全屏子面板，支持保存并返回、恢复默认和导入导出。
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

服务器已有 `pansou-api-1`、需要将本项目接到其 API 并替换旧网页时，按 [连接现有 PanSou 与迁移网页](EXISTING_PANSOU.md) 操作；配套配置为 `compose.pansou.yaml`。

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

### 5. 配置 DeepSeek Harness（静态 Token）

DeepSeek Harness 的 MCP 客户端使用 Streamable HTTP + `Authorization` 请求头，不走 ChatGPT 的 OAuth 回调。为账号生成一个长期 Token：

```bash
docker compose --project-directory backend --env-file backend/.env -f backend/compose.yaml exec app \
  python -m backend.manage issue-mcp-token bob --days 365
```

Token 只显示一次；重新生成会立即使旧 Token 失效。吊销：

```bash
docker compose --project-directory backend --env-file backend/.env -f backend/compose.yaml exec app \
  python -m backend.manage revoke-mcp-token bob
```

在 DSH 的 Profile patch（`$DSH_HOME/profiles/<profile>/cordis.patch.yml`）中合并：

```yaml
- insert:
    - id: resource-hub-mcp
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: resource-hub
        transport: streamable-http
        url: https://你的域名/mcp
        headers:
          Authorization: Bearer rh_mcp_xxx
```

保存后等待 DSH 热加载或重启 Host，新建会话即可看到 `mcp__resource-hub__*` 工具。Token 与网页账号共用每日额度；管理员账号不限次数。不要把 Token 提交到 Git 或公开聊天。

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
- 管理员账号不受每日搜索额度限制，今日已用次数仍会记录。
- 并发搜索先预占额度，失败或取消后归还；进程意外退出的预占在 180 秒后失效。
- 重试时复用相同的 `request_id` 和搜索词，可避免重复计次；省略 ID 的调用视为新搜索。
- 每账号每分钟最多调用搜索工具 30 次。
- 结果按账号隔离，24 小时后不可读取；搜索记录和计数最多保留 31 天。

## 运维与备份

### 一键更新

首次部署成功后，在服务器项目根目录运行 `bash update.sh`，自动拉取 `origin/main`、构建并更新 app，等待健康检查。脚本可从其他目录通过绝对路径运行；`bash update.sh --force` 可强制重新构建当前版本。

脚本保留服务器 `.env` 和数据卷，更新网页、API 与 MCP，不重启 PanSou 或入口代理。Git 冲突会停止，不会强制覆盖本地修改。镜像构建失败时旧应用继续运行；替换应用后健康检查失败会报错，需要人工排查，脚本不自动回滚数据库或容器。Caddy 配置或部署结构变更仍需另行处理。

仓库 Dockerfile 与更新脚本均默认使用 `public.ecr.aws/docker/library/python:3.12-slim`，与此次服务器已验证可用的镜像来源保持一致。脚本通过临时 Dockerfile 支持使用 `RESOURCE_HUB_PYTHON_IMAGE` 环境变量指定其他来源，不修改仓库文件。首次运行会构建一次，之后相同的已成功部署提交自动跳过。手工上传的 `update.sh`、`compose.pansou.yaml` 若与远程内容一致，会先备份再纳入 Git 管理；内容不一致则停止。若仓库 Dockerfile 后续有改动，与服务器手工修改冲突时仍需人工合并。

临时构建文件放在项目内的 `.cache/update/build.*`，退出时清理，避免新版 Bake 读取项目外 `/tmp` 文件时要求额外的 `fs.read` 权限。

如需自动检查，执行 `crontab -e`，加入下面一行（路径按实际部署位置修改）：

```cron
*/5 * * * * /bin/bash /opt/apps/resource-hub/update.sh >> /var/log/resource-hub-update.log 2>&1
```

这会每 5 分钟检查一次，只有新提交或上次未成功部署时才重建。使用具有项目和 Docker 权限的账号配置定时任务，并确保该账号能免交互拉取仓库。脚本依赖 Linux 的 Bash、Git、Docker Compose 与 `flock`。首次运行前应将脚本提交到 GitHub 并同步至服务器；不要提交 `.env`。定时任务日志应按服务器策略轮转。

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
