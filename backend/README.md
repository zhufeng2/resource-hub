# 部署与维护

[项目首页](../README.md) · [网页与账号](../web/README.md) · [MCP 接入与工具](../mcp/README.md) · [开发指南](../docs/DEVELOPMENT.md)

本服务在同一个应用中提供网页、同源 API、OAuth 和 MCP，搜索固定为夸克。需要 Linux、Git、Docker Engine、Docker Compose 插件、域名及可用的 PanSou 兼容上游；本仓库不附带 PanSou 服务或上游凭据。

以下命令在仓库根目录执行。已有站点先备份配置和数据，再更新，不要用示例文件覆盖现有 `.env`。

## 1. 下载与基础配置

```bash
git clone https://github.com/zhufeng2/resource-hub.git
cd resource-hub
cp backend/.env.example backend/.env
chmod 600 backend/.env
```

编辑 `backend/.env`，填写实际域名和上游认证。Resource Hub 用户账号与 PanSou 上游账号相互独立，测试站网址不能直接充当 PanSou API。

| 变量 | 用途 |
| --- | --- |
| `PUBLIC_BASE_URL` | HTTPS 站点根地址，不带路径，例如 `https://search.example.com` |
| `PANSOU_BASE_URL` | 实际 PanSou API 根地址 |
| `PANSOU_API_TOKEN` | 固定上游 Token；与下面的账号密码方式择一 |
| `PANSOU_USERNAME`、`PANSOU_PASSWORD` | 上游账号密码，Token 留空时服务端自动登录 |
| `PANSOU_ALLOW_HTTP` | 仅受信任内部 HTTP 上游设为 `true` |
| `OAUTH_REDIRECT_URIS` | MCP 客户端提供的准确 HTTPS 回调地址，多个以逗号分隔 |
| `DEFAULT_DAILY_LIMIT` | 新普通账号每日搜索额度，默认 5，不修改已有账号额度 |
| `SEARCH_TIMEOUT`、`SEARCH_CONCURRENCY` | 搜索超时默认 25 秒，并发默认 4 |
| `REGISTRATION_ENABLED` | 默认 `true`，SMTP 可用时开放注册；`false` 关闭新注册 |
| `SMTP_*` | 验证邮件配置，见下文 |
| `QUARK_SECRET_KEY` | 可选独立 Fernet 密钥；为空时首次绑定在数据卷生成密钥文件 |
| `QUARK_NODE_BINARY` | 非 Docker 部署可选 Node.js 可执行文件；镜像已包含 Node.js |

站点写请求校验 Origin 与 CSRF。浏览器只访问本站 API，不持有 PanSou 认证信息；代理或 APM 不应记录认证头和凭据请求体。

## 2. 选择上游连接方式

### 已有本机 PanSou 容器

以下用容器 `pansou-api-1`、内部端口 `8888` 为例，替换为实际值。先让两个项目共用内部网络和稳定别名：

```bash
docker network create resource-hub-upstream
docker network connect --alias pansou-upstream resource-hub-upstream pansou-api-1
```

网络已存在或容器已连接时跳过对应命令。为避免 PanSou 重建后丢失连接，将以下配置合并到它原来的 Compose 文件，保留原有服务、挂载与网络：

```yaml
services:
  api: # 替换为原文件中的实际服务名
    networks:
      default: {}
      resource_hub:
        aliases: [pansou-upstream]
networks:
  resource_hub:
    external: true
    name: resource-hub-upstream
```

可用容器标签定位原有 Compose 文件：

```bash
docker inspect pansou-api-1 --format '{{ index .Config.Labels "com.docker.compose.project.config_files" }}'
```

本站 `.env` 配置 `PANSOU_BASE_URL=http://pansou-upstream:8888`、`PANSOU_ALLOW_HTTP=true`，并填写真实上游 Token 或账号密码。`127.0.0.1:8888` 指向 app 容器自身，不能用来连接宿主机的 PanSou。上游必须支持所需认证、搜索和检测接口，不能用随机 Token 绕过认证。

此部署加载仓库自带的覆盖文件。为避免后续命令漏掉网络配置，当前终端定义统一前缀：

```bash
dc() {
  docker compose --project-directory backend --env-file backend/.env \
    -f backend/compose.yaml -f backend/compose.pansou.yaml "$@"
}
```

### 独立 HTTPS 上游

如果 PanSou 已有可访问的 HTTPS API，在 `.env` 填写该地址和认证信息，并仅使用基础 Compose：

```bash
dc() {
  docker compose --project-directory backend --env-file backend/.env \
    -f backend/compose.yaml "$@"
}
```

`compose.pansou.yaml` 会强制覆盖上游为内部别名，因此此布局不要加载它。下文的 `dc` 表示上面按实际布局选择的函数；开启新终端后需重新定义。

## 3. 邮箱验证注册

在同一份 `backend/.env` 中配置发件服务，例如 QQ 邮箱：

```dotenv
REGISTRATION_ENABLED=true
SMTP_HOST=smtp.qq.com
SMTP_PORT=465
SMTP_SECURITY=ssl
SMTP_USERNAME=你的QQ号@qq.com
SMTP_PASSWORD=你的SMTP授权码
SMTP_FROM=你的QQ号@qq.com
```

QQ 邮箱在“设置 → 账号与安全 → 安全设置”开启 SMTP 并生成授权码，参见[官方说明](https://help.mail.qq.com/detail/106/985)。授权码只放在服务器配置中。发件服务不限制注册邮箱服务商，QQ、163、Gmail、Outlook、企业邮箱等均可接收验证码。

其他发件服务按其参数修改；587 端口通常配 `SMTP_SECURITY=starttls`。仅支持校验证书的 SSL 或 STARTTLS，不支持明文 SMTP。SMTP 缺失或配置格式无效时注册入口关闭；`REGISTRATION_ENABLED=false` 只关闭新注册，不关闭已有账号的邮箱绑定。实际认证和投递仍需上线后验证。

验证码 10 分钟有效、最多尝试 5 次，绑定当前浏览器会话及注册/绑定用途，成功后立即失效。发送限制为同邮箱每分钟 1 次、每天 5 次；同 IP 每 10 分钟 3 次、每天 10 次；全站每小时 100 次。邮箱验证降低滥用，但不能阻止使用多个邮箱注册。

配置变更需要重新创建 app 容器，`restart` 不会更新容器环境。首次部署随下面的构建生效；已部署后的重新加载见“更新服务”。

## 4. 启动、创建主管理员和验证

域名需解析到服务器，TCP 80/443 可供自带 Caddy 使用；已有共用代理时先调整入口，避免端口冲突。基础 Compose 的 app 8000 端口只在容器网络开放。

```bash
dc config --quiet
dc up -d --build
dc ps
dc exec app python -m backend.manage add-user admin --admin
```

已有 `admin` 时跳过创建，密码按提示输入，至少 12 字符。Caddy 管理 HTTPS 证书，验证站点与上游：

```bash
curl --fail https://你的域名/healthz
dc exec app python -c 'import asyncio; from backend.upstream import Upstream; asyncio.run(Upstream().catalog()); print("PanSou API connection OK")'
```

健康检查不代表搜索已成功。再登录网站，读取公开来源并完成一次实际搜索，核对结果与额度；配置 SMTP 后以独立测试邮箱完成注册和投递验证；需要网盘时绑定自己的 Cookie，在明确授权的测试目录验证操作。Docker 构建、证书和生产上游的实际验证由部署环境完成，不把模拟测试当作上线验证。

### 替换旧网页或代理入口

先确认旧网页、API 和代理各自职责：

```bash
docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}'
sudo ss -lntp '( sport = :80 or sport = :443 )'
```

新域名入口应统一转发到本站 app，由 app 处理 `/`、`/assets/*`、`/api/*` 和 `/mcp`；不要把本站 `/api/*` 直接转发给 PanSou，否则会绕开账号、CSRF 和额度流程。

只有宿主机 Nginx 确认只提供旧网页、没有其他站点时，才按下面切换；共用代理应修改对应域名路由，不能停整个代理。先保留旧入口并启动 app：

```bash
dc up -d --build app
dc ps
```

确认 healthy 并通过上游连接验证后，按实际安装路径备份旧 Nginx 配置，再切入口：

```bash
sudo tar -czf /root/nginx-before-resource-hub.tar.gz /etc/nginx
sudo systemctl stop nginx
dc up -d proxy
```

该备份文件已存在时应换新文件名，保留旧备份。检查 HTTPS、登录、真实搜索与额度；需要回退时执行 `dc stop proxy`，再 `sudo systemctl start nginx`。稳定后才决定是否 `sudo systemctl disable nginx`；回退后需要旧入口自动启动时重新 enable。保留 PanSou API、挂载和数据卷，容器名字不能证明它可删除。

## 5. 账号与权限维护

网页仅名为 `admin` 的管理员能管理普通成员，支持用户名/邮箱搜索、20/50/100 条分页、创建、密码重置、额度调整、停用与垃圾桶删除。管理员账号不出现在该列表，接口也禁止编辑、删除或通过网页创建/提升管理员。

删除需输入账号名确认，清理用户、会话、OAuth 与个人 Token、加密 Cookie 绑定、偏好及搜索记录。账号编号持久递增不复用。操作日志为核对已提交任务而保留，删号不能撤销已经发往夸克的操作。

管理员角色通过服务器维护；提升后账号会从普通成员列表隐藏：

```bash
dc exec app python -m backend.manage list-users
dc exec app python -m backend.manage add-user alice --limit 5
dc exec app python -m backend.manage set-limit alice 10
dc exec app python -m backend.manage disable-user alice
dc exec app python -m backend.manage enable-user alice
dc exec app python -m backend.manage reset-password alice
dc exec app python -m backend.manage make-admin alice
```

停用或重置密码会撤销现有授权，重新启用需重新登录。管理员不限每日搜索额度，但仍限流；普通账号额度设为 0 可暂停新搜索。

个人 MCP Token 默认 7 天，用户可自行在网页管理；服务器也可签发或吊销：

```bash
dc exec app python -m backend.manage issue-mcp-token alice --days 7
dc exec app python -m backend.manage list-mcp-tokens
dc exec app python -m backend.manage revoke-mcp-token alice
```

Token 命令会输出敏感信息，应在可信终端执行，不写入公开日志。客户端连接和全部工具集中在 [MCP 指南](../mcp/README.md)。

## 6. 更新服务

### 本机 PanSou 覆盖文件布局

```bash
bash update.sh
# 仅改了环境配置，或相同代码版本也需重建
bash update.sh --force
```

脚本从 `origin/main` 拉取并快进合并，构建、更新 app 并等待健康检查。它保留 `.env` 和数据卷，不重启 PanSou 或代理。检测到 `backend/compose.pansou.yaml` 就加载该文件，因此仓库默认脚本适合上文的本机 PanSou 网络布局。

同一已成功部署提交自动跳过，`--force` 强制重建。分支分歧、冲突、网络或构建失败会停止，不覆盖本地改动。替换后健康失败需排查，不自动回滚。脚本要求 main 分支、非交互 Git 拉取及 Bash、Git、Docker Compose、flock、mktemp、sed、cmp。

默认 Python 基础镜像为 `public.ecr.aws/docker/library/python:3.12-slim`，可用 `RESOURCE_HUB_PYTHON_IMAGE` 指定替代来源。临时构建文件、版本记录、锁和迁移备份在 `.cache/update/`，不要随意删除。

### 独立 HTTPS 上游或自定义布局

使用已定义的基础/自定义 `dc` 前缀更新，不加载强制内部别名的覆盖文件：

```bash
git pull --ff-only origin main
dc config --quiet
dc build app
dc up -d --no-deps --wait --wait-timeout 120 app
```

只改环境配置也要重新创建 app。代理配置或部署结构变更时，按实际布局更新相关服务；只更新 app 不会应用代理变化。

如需定时更新，仅在已验证适配的布局中将实际项目路径的 `update.sh` 加入 cron，并配置日志轮转和合适的 Docker/Git 权限。

## 7. 数据库、密钥与备份

默认数据库是 SQLite，位于容器 `/data/service.sqlite3`，持久化在 Compose 的 `app_data` 数据卷里，不在代码目录，也不会随 Git 推送。首次启动自动建表，现有数据库自动补齐邮箱字段、验证码表及用户编号计数器。注册邮箱唯一，密码使用 scrypt 哈希。

```bash
dc exec app ls -lh /data
dc exec app python -m backend.manage cleanup
```

数据库启用 WAL 和短写事务，适合当前单机部署；高并发写入承载量需压测，不能按注册人数保证性能。不要将多台服务器通过网络文件系统共享此 SQLite 文件。

| 数据 | 持久位置与恢复要求 |
| --- | --- |
| 账号、邮箱、授权、配置、搜索与用量 | `/data/service.sqlite3`，备份数据库 |
| MCP Token 可恢复副本的密钥 | `/data/service.sqlite3.mcp.key`，与对应数据库一并保留 |
| 夸克 Cookie 密钥 | 优先 `QUARK_SECRET_KEY`；为空时为 `/data/service.sqlite3.quark.key` |
| 网盘操作记录与锁 | `/data/quark-operations/<用户ID>/<绑定ID>/<request_id>.json` 及相关锁 |
| 服务配置 | 服务器 `backend/.env`、代理配置和实际 Compose 布局 |

备份时停止 app 后备份完整数据卷，或用 SQLite 在线备份接口；不要只复制正在写入的单个 `.sqlite3` 文件，WAL 中可能还有未合并数据。恢复需匹配数据库与密钥，密钥和备份按敏感数据保管。`docker compose down -v` 会删除数据卷，不能当作日常更新或缓存清理命令。

搜索关键词和结果在 24 小时后擦除，自动清理间隔 5 分钟；计数和请求标识最多保留 31 天。手动删除记录同样不返还用量。验证码过期后由定时任务清理。网盘操作记录不适用搜索记录的 24 小时清理规则。

## 8. 凭据与网盘任务维护

Cookie 按当前登录用户和绑定标识加密，个人 Token 只认证本账号。独立 Node.js 子进程通过标准输入接收 Cookie，不放在工具参数、命令行或日志；Docker 已安装运行环境，非 Docker 需 Python 3.12、Node.js 18+ 和锁定依赖。

Cookie 保存成功后默认遮罩；本人页面的显示/复制请求受登录、同源和 CSRF 保护，响应不缓存。普通绑定状态与 MCP 工具不返回 Cookie。重新绑定会隔离旧任务，不自动刷新长期登录，也不会改用共享凭据。

任务提交前记录意图，`.lock` 跨进程互斥，正常结束释放。强制终止或结果不明可能留下锁；`operation_busy` 时先核对原记录、进程和真实网盘结果，不自动删锁、删记录或更换请求编号。没有任务 ID 也不能据此断言提交失败。已完成关联任务的旧操作日志可由维护者按自己的保留策略清理。

进度归零正常关机等待当前有界批次落盘，Compose 为 app 提供 60 秒退出宽限。重启后不自动恢复所有任务，用户按原参数和编号接续；解绑、停用和删号会阻止后续绑定校验通过，已经提交的操作可能继续完成。

## 9. 排查与上线验证

```bash
dc ps
dc logs --tail=80 app proxy
```

| 现象 | 核对项 |
| --- | --- |
| 无法访问或证书失败 | DNS、80/443、防火墙、入口占用、Caddy 日志 |
| 请求失效 | 实际域名、`PUBLIC_BASE_URL`、会话和代理转发 |
| 搜索失败 | 上游认证、Docker 网络、实际 API 是否兼容 |
| 无注册入口 | 注册开关、SMTP 地址/端口/加密、发件人和认证配置 |
| 邮件发送失败 | SMTP 授权码、出站端口、服务商限制和收件垃圾箱；不输出验证码和密码 |
| Cookie/Token 无法显示 | 对应密钥是否保留，必要时用户主动重新绑定或生成 |
| 更新后不生效 | 新提交是否拉取、容器是否重建、环境和覆盖文件是否匹配 |
| 网盘操作锁定或状态未知 | 复用原编号核对记录、进程及独立回读结果 |

应用使用锁定依赖 `backend/requirements.lock`，容器非 root、只读根文件系统，日志默认轮转为每容器 3 个 10MB 文件。保持当前单进程模型，8000 不直接映射公网，反向代理信任范围按实际布局维护。不把本地 `.cache/dev-preview` 数据库或已知预览账号搬到生产。

首次部署及重要更新后，实际验证 HTTPS、注册邮件、登录、普通用户管理、一次搜索、MCP 认证与独立测试目录中的网盘功能。离线测试和开发方法见[开发指南](../docs/DEVELOPMENT.md)。

### 邮箱找回密码

已验证邮箱的用户可在登录页选择“忘记密码”，使用邮箱验证码设置新密码。复用现有 SMTP 配置，关闭 `REGISTRATION_ENABLED` 不会关闭密码找回；未配置可用 SMTP 时提示联系管理员。找回成功撤销该用户所有网页登录、个人 MCP Token、OAuth 访问及刷新令牌，客户端需要重新连接。

验证码 10 分钟有效，每份证明最多 5 次错误尝试，成功后一次性消费，并绑定浏览器会话、账号编号及当前密码版本。发送限制与注册共用邮箱/IP/全局额度，不在响应或日志中输出验证码。未知或停用邮箱与 SMTP 失败统一返回发送提示；未收到邮件时按本指南检查 SMTP 和垃圾邮件。没有邮箱的测试账号由管理员使用 `reset-password` 命令或用户管理页重置。个人主页不再提供单独的绑定邮箱栏目。
