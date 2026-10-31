# 服务器部署与维护

将 Resource Hub 部署为一个同时提供网页、网页 API 和 MCP 的服务。适用于拥有 Linux 服务器、域名及 PanSou 上游访问权限的维护者。

[返回项目首页](../README.md) · [网页使用](../web/README.md) · [MCP 接入](../mcp/README.md) · [连接已有 PanSou](EXISTING_PANSOU.md)

## 部署前准备

- Linux、Git、Docker Engine 和 Docker Compose 插件。
- 解析到服务器的域名，公网 TCP 80/443 可访问。
- 可用的 PanSou 兼容 API 地址，以及 API Token 或账号密码。
- 80/443 可交给项目的 Caddy 使用；已有共用代理时需调整入口，避免端口冲突。

本项目不附带 PanSou 搜索服务。服务器已有 PanSou 容器时，请使用[已有 PanSou 接入指南](EXISTING_PANSOU.md)，其中包含 Docker 网络和旧站迁移步骤。

网页用户在 Resource Hub 中创建，上游 PanSou 凭据仅由服务器使用。公共测试站的网页地址和账号不能直接作为其他部署的 PanSou 上游配置。

## 1. 下载与配置

```bash
git clone https://github.com/zhufeng2/resource-hub.git
cd resource-hub
cp backend/.env.example backend/.env
chmod 600 backend/.env
```

已有配置时直接编辑，不要覆盖 `.env`。至少修改站点域名、上游地址和上游认证：

| 变量 | 说明 |
| --- | --- |
| `PUBLIC_BASE_URL` | 自己的网站根地址，例如 `https://search.example.com`，不带路径 |
| `PANSOU_BASE_URL` | 必须配置实际的 PanSou API 根地址；不能使用 Resource Hub 测试网站地址 |
| `PANSOU_API_TOKEN` | 上游固定 Token；使用它时无需设置上游账号密码 |
| `PANSOU_USERNAME` / `PANSOU_PASSWORD` | 上游账号密码，必须成对配置；Token 优先 |
| `OAUTH_REDIRECT_URIS` | 客户端提供的准确 OAuth 回调地址，多个以逗号分隔 |
| `DEFAULT_DAILY_LIMIT` | 新普通账号的每日额度，默认 5 |
| `SEARCH_TIMEOUT` | 上游搜索超时，默认 25 秒 |
| `SEARCH_CONCURRENCY` | 同时进行的搜索数量，默认 4 |
| `PANSOU_ALLOW_HTTP` | 仅访问受信任的内部 HTTP 上游时设为 `true` |
| `SOURCE_SITE_HOSTS` | 管理员可配置的搜索源镜像主机名，多个以逗号分隔 |

浏览器不需要上游凭据，不要将这些值写入前端代码。站点外部访问地址应与 `PUBLIC_BASE_URL` 一致，OAuth 回调地址需与客户端提供的值精确匹配。

## 2. 启动服务

以下命令均在仓库根目录执行：

```bash
docker compose --project-directory backend --env-file backend/.env -f backend/compose.yaml config --quiet
docker compose --project-directory backend --env-file backend/.env -f backend/compose.yaml up -d --build
docker compose --project-directory backend --env-file backend/.env -f backend/compose.yaml ps
```

Caddy 根据配置自动申请 HTTPS 证书。将下面地址替换为自己的域名：

```bash
curl --fail https://search.example.com/healthz
```

健康检查成功只说明应用响应正常，还需用实际账号验证搜索和上游连接。

使用 `compose.pansou.yaml` 的部署，手动执行 Compose 命令时应同时传入两个文件：`-f backend/compose.yaml -f backend/compose.pansou.yaml`。完整步骤见[已有 PanSou 接入](EXISTING_PANSOU.md)。

## 3. 创建账号

```bash
docker compose --project-directory backend --env-file backend/.env -f backend/compose.yaml exec app python -m backend.manage add-user admin --admin
docker compose --project-directory backend --env-file backend/.env -f backend/compose.yaml exec app python -m backend.manage add-user alice --limit 5
```

密码按提示输入，至少 12 个字符。先创建名为 `admin` 的管理员，之后可在网页“个人主页 → 用户管理”中管理用户；该入口只对名为 `admin` 的管理员开放。其他管理员享有不限搜索额度，但不显示网页用户管理入口。

登录网页，打开搜索设置读取来源，再执行一次搜索，检查结果与账户额度。需要 MCP 的用户继续阅读 [MCP 接入指南](../mcp/README.md)。

## 账号维护

在以下命令前加上本部署对应的 `docker compose ... exec app` 前缀：

```bash
python -m backend.manage list-users
python -m backend.manage set-limit alice 10
python -m backend.manage disable-user alice
python -m backend.manage enable-user alice
python -m backend.manage reset-password alice
python -m backend.manage make-admin alice
python -m backend.manage cleanup
```

停用账号或重置密码会撤销已有授权。重新启用后需再次登录。将普通账号额度设为 0 可暂停新搜索；`DEFAULT_DAILY_LIMIT` 只影响之后创建的账号。管理员账号不受每日额度限制。

长期 MCP Token 的签发、列出及吊销命令见 [MCP 接入指南](../mcp/README.md)。

## 更新服务

首次部署完成后，在仓库根目录运行：

```bash
bash update.sh
```

脚本拉取 `origin/main`、执行快进合并、构建并更新 app，等待健康检查。它保留 `.env` 和数据卷，不重启 PanSou 或入口代理。检测到 `backend/compose.pansou.yaml` 时，会自动加载覆盖配置。

- 相同的已成功部署提交自动跳过；需要重新构建时使用 `bash update.sh --force`。
- 本地改动冲突或分支分歧会停止，脚本不会强制覆盖。
- 构建失败时旧应用继续运行；替换后健康检查失败需人工排查，脚本不自动回滚。
- 修改 Caddy 配置或部署结构后，还需按变更更新代理等相关服务。

脚本要求当前分支是 `main`，依赖 Bash、Git、Docker Compose、`flock`、`mktemp`、`sed` 和 `cmp`。更新前确保服务器账号能免交互拉取仓库。可用 `git remote -v` 检查远程地址；仓库地址为 `https://github.com/zhufeng2/resource-hub.git`。

默认基础镜像为 `public.ecr.aws/docker/library/python:3.12-slim`。需要更换来源时设置 `RESOURCE_HUB_PYTHON_IMAGE`；脚本生成临时构建文件，不修改仓库 Dockerfile。临时文件和部署记录位于 `.cache/update/`。手工上传且即将纳入版本管理的同名文件，只有内容匹配时才会备份后迁移；不匹配则停止。

### 定时检查更新

可通过服务器的 `crontab -e` 配置。下例假设项目安装在 `/opt/apps/resource-hub`，请替换为实际路径：

```cron
*/5 * * * * /bin/bash /opt/apps/resource-hub/update.sh >> /var/log/resource-hub-update.log 2>&1
```

每 5 分钟检查一次，仅有新提交或上次部署未成功时重建。使用具有项目、Docker 和日志文件写入权限的账号，并配置日志轮转。

## 备份与数据

账号、授权和用量保存在 `app_data` 卷中的 SQLite 数据库。重建容器会保留数据，`docker compose down -v` 会删除数据卷。

备份时停止 app 后复制数据卷，或使用 SQLite 在线备份接口。数据库使用 WAL 模式，直接复制正在写入的单个数据库文件可能遗漏数据。备份含搜索记录和认证信息，应限制访问。另行备份 `.env` 和入口代理配置，以便恢复部署。

搜索关键词和结果在 24 小时后由定时清理任务擦除（最多延迟 5 分钟）；计数和请求标识最多保留 31 天。用户可删除记录并擦除关键词与结果，计次和请求标识仍按保留策略保存，防止删除记录后返还额度。详细计次规则见 [MCP 额度说明](../mcp/README.md#额度规则)。

## 故障排查

查看状态和最近日志：

```bash
docker compose --project-directory backend --env-file backend/.env -f backend/compose.yaml ps
docker compose --project-directory backend --env-file backend/.env -f backend/compose.yaml logs --tail=80 app proxy
```

| 现象 | 检查项 |
| --- | --- |
| 证书申请或网页访问失败 | DNS、80/443、防火墙、其他代理占用及 Caddy 日志 |
| 登录或保存设置提示请求失效 | 外部访问域名是否与 `PUBLIC_BASE_URL` 一致，会话是否过期 |
| 健康检查正常但搜索失败 | PanSou 地址、认证、内部网络、上游实际接口 |
| 普通搜索正常但账号绑定不可用 | PanSou 是否提供对应来源的绑定接口 |
| 更新停止 | Git 分支、本地改动、上游网络、构建及健康检查日志 |

默认 Compose 将 8000 端口仅暴露给内部网络。自定义反向代理布局时，应配置实际的转发头信任范围。HTTP 访问日志默认关闭，额外启用时对授权码和令牌脱敏。

开发环境、接口结构及离线测试见[开发指南](../docs/DEVELOPMENT.md)。

## MCP Token 的展示与备份

用户可在“个人主页 → 安全与连接 → MCP 服务”生成、查看、复制和撤销自己的 Token。网页读取接口要求登录，写操作沿用同源与 CSRF 校验；Token 认证仍绑定用户和站点资源，共享网页额度。

服务器保留 Token 哈希用于认证，并用 Fernet 加密保存可恢复副本。首次签发时在数据库旁自动生成 `<数据库文件名>.mcp.key`（仅服务用户可读写）；Docker 默认与数据库一起保存在 `/data` 持久卷中。备份及恢复必须同时保留数据库和此密钥，不要提交密钥到版本库。旧版 Token 或缺少密钥时不会自动失效，但无法恢复显示，用户可主动重新生成；重新生成只轮换该用户的个人 Token，不影响 OAuth 授权。改密码、停用账号或撤销全部 MCP 授权会同时清除相关可恢复副本。

## 安全维护

Compose 为应用和代理配置日志轮转，每个容器最多保留 3 个 10 MB 日志文件。首次应用此 Compose 变更需运行当前部署使用的完整 `docker compose ... up -d` 命令，`update.sh` 只更新应用容器，不会重建代理。

## 夸克凭据与运行环境

服务复用 `backend/quark_client/` 中的用户接口库，每次调用启动独立 Node.js 进程；凭据通过标准输入传递，不放入命令行、工具参数或日志。Docker 构建已包含 Node.js；本地运行需 Node.js 18+，可用 `QUARK_NODE_BINARY` 指定管理员控制的可执行文件路径。

夸克 Cookie 使用 Fernet 加密保存在 `quark_accounts` 表，用户 ID 来自已验证的网页登录会话或 MCP Token。优先通过环境变量 `QUARK_SECRET_KEY` 注入独立 Fernet 密钥（可运行 `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` 生成并保存至服务器秘密配置，勿提交版本库）。未配置时首次绑定会生成数据库旁的 `<数据库名>.quark.key`，权限 0600；生产环境建议独立秘密管理。密钥丢失或更换后旧绑定无法解密，需要重新绑定；不回退共享 Cookie。备份加密数据库与密钥时应分开保管。

操作记录位于数据库旁 `quark-operations/<user_id>/<binding_id>/<request_id>.json`，不含 Cookie、分享访问令牌或文件转存令牌。每次重新绑定产生新的绑定 ID，不能将旧任务带到新账号。请求编号只接受受限字符，不能指定任意记录路径或上游任务 ID。

`.lock` 文件负责跨进程互斥。正常结束自动释放；进程被杀或执行超时可能留下锁，此时返回 operation_busy，管理员先核对该记录、进程与实际网盘结果，再决定如何恢复；不得自动清锁、删除记录或换编号重新转存。记录提交意图但没有任务 ID 时同样停止，不假设提交失败。锁和任务记录需要随数据卷持久化，不应按搜索记录的 24 小时策略清理。

解绑只删除当前加密凭据，不撤销夸克登录 Cookie、不取消已经提交的上游任务。操作记录保留用于核对，管理员可在确认所有关联任务已结束后按自己的保留策略清理。站点/代理/APM 禁止记录绑定接口请求体和认证请求头。已有 OAuth scope 名称 `search` 为兼容而保留，夸克读写访问由用户主动绑定授予；不能把该 scope 名称解释为整个 MCP 永远只读。

Cookie 显示/复制使用 POST `/api/quark-account/reveal`，要求网页登录、同源、CSRF，始终从会话取得用户 ID；响应 no-store，不允许指定其他用户。GET 状态和 MCP 工具仍不返回 Cookie。


## 本轮上线前确认

镜像从 `backend/requirements.lock` 安装本轮验证过的固定依赖；`requirements.txt` 保留顶层依赖声明，更新依赖后应重建锁文件、扫描并回归，不能只改声明文件。非 Docker 运行使用 Python 3.12、Node.js 18+，同样安装锁文件。

按上文配置 backend/.env 后，先运行 `docker compose --project-directory backend --env-file backend/.env -f backend/compose.yaml config --quiet`，再按当前部署所需的覆盖文件启动构建。随后核对健康检查、HTTPS、OAuth/MCP、一次实际搜索及独立测试目录的网盘操作。使用 PanSou 覆盖文件时，这些命令都要带上 `-f backend/compose.pansou.yaml`。

不要复制本地 `.cache/dev-preview` 数据库到生产环境，其中是已知密码的预览管理员和测试授权。已有生产数据必须备份再迁移，沿用对应加密密钥；新生产账号独立创建并重新绑定夸克。应用8000端口不要映射公网，保持单进程运行，代理/APM不记录凭据请求体。

本轮没有代为部署服务器，Docker构建、证书与真实生产上游验证须在服务器完成。
