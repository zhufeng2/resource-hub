# 连接服务器上已有的 PanSou API

适用情况：服务器已有 `pansou-api-1`，镜像为 `ghcr.io/fish2018/pansou`，端口为 `127.0.0.1:8888->8888/tcp`。

推荐直接使用本项目自带的 Caddy 作为网站入口，自动管理 HTTPS。若当前域名通过宿主机 Nginx 提供旧网页，可按文末步骤切换；无需单独部署前端。

此容器提供搜索 API，应继续运行。当前容器列表没有独立的 `pansou-web` 服务，不能通过删除 `pansou-api-1` 来替换旧网页。

## 接口关系

```text
浏览器 → 网站域名 → Caddy → 本项目 app:8000
                              ├─ /、/profile、/assets/*：网页
                              ├─ /api/*：登录、搜索、额度、设置
                              ├─ /mcp：ChatGPT 接口
                              └─ 内部网络 → pansou-upstream:8888
```

`web/static/app.js` 已使用同域地址调用 API，无需配置浏览器端的 API Token 或另设前端域名。网页会先获取 `/api/session` 的 CSRF Token，再登录；登录后使用新的 Token 和会话 Cookie 调用搜索接口。

| 网页接口 | 方法 | 用途 |
| --- | --- | --- |
| `/api/session` | GET | 登录状态、CSRF Token；已登录时也返回额度与个人配置 |
| `/api/login` | POST | 本项目的用户登录 |
| `/api/search` | POST | 请求字段为 `query`、`request_id`，可选 `options`、`refresh` |
| `/api/results/{id}` | GET | 恢复已保存的搜索结果 |
| `/api/history` | GET | 当前用户搜索历史 |
| `/api/preferences` | PUT | 保存搜索设置 |
| `/api/catalog` | GET | 获取上游启用的插件和频道 |
| `/api/bindings` | GET / POST | 列出或添加搜索源账号 |

搜索返回 `search_id`、`results`、`quota` 等字段。写请求需要 `X-CSRF-Token`，浏览器 `Origin` 必须与 `PUBLIC_BASE_URL` 一致。网页用户在本项目数据库中创建，与 PanSou 上游认证账号分开。

以下命令在 Linux 服务器的本仓库根目录执行。

## 1. 连接现有 API

创建一个两个项目共用的网络，再为已有 API 设置内部别名：

```bash
docker network create resource-hub-upstream
docker network connect --alias pansou-upstream resource-hub-upstream pansou-api-1
```

如果网络已存在，不必重复创建；如果容器已加入网络，不必重复连接。保留已有 API 的端口映射。

手动连接会在旧容器重建后丢失。找到 PanSou 原有的 Compose 文件，在原有 API 服务中加入以下网络配置，合并现有配置而不是覆盖整份文件：

```yaml
services:
  api: # 使用原文件中的实际服务名
    networks:
      default: {}
      resource_hub:
        aliases:
          - pansou-upstream

networks:
  resource_hub:
    external: true
    name: resource-hub-upstream
```

如果 API 原来使用其他网络，继续保留那些网络。也可查看容器标签中的原始部署文件路径：

```bash
docker inspect pansou-api-1 --format '{{ index .Config.Labels "com.docker.compose.project.config_files" }}'
```

## 2. 配置新网站

首次部署时复制配置；已有 `.env` 时直接编辑，避免覆盖：

```bash
cp backend/.env.example backend/.env
chmod 600 backend/.env
```

编辑 `backend/.env`：

```dotenv
PUBLIC_BASE_URL=https://你的实际域名
PANSOU_BASE_URL=http://pansou-upstream:8888
PANSOU_ALLOW_HTTP=true
PANSOU_API_TOKEN=你的上游Token
PANSOU_USERNAME=
PANSOU_PASSWORD=
DEFAULT_DAILY_LIMIT=5
SEARCH_TIMEOUT=25
SEARCH_CONCURRENCY=4
```

本项目适配器要求上游认证。若使用账号密码，将 `PANSOU_API_TOKEN` 留空，并填写 PanSou 的用户名和密码。若现有 PanSou 没有启用认证，先按它当前版本的配置启用；不要填写随机 Token 来绕过配置。凭据只保存在服务器，不能填入网页 JavaScript。

PanSou 官方当前支持在原有 API 服务的 `environment` 中设置以下变量；实际密码和签名密钥应自行生成并仅保存在服务器：

```yaml
environment:
  AUTH_ENABLED: "true"
  AUTH_USERS: "resourcehub:替换为实际强密码"
  AUTH_JWT_SECRET: "替换为实际随机签名密钥"
```

合并后在 PanSou 原有部署目录重建其 API 服务，保留原有数据挂载、插件配置和网络。新网站配置 `PANSOU_USERNAME=resourcehub`、对应的 `PANSOU_PASSWORD`，并将 `PANSOU_API_TOKEN` 留空，适配器会自动登录和更新 Token。参见 [PanSou 官方认证说明](https://github.com/fish2018/pansou#认证配置可选)。

`compose.pansou.yaml` 会为 app 明确设置上述内部地址和 HTTP 开关。`127.0.0.1:8888` 仅供宿主机访问，不能作为新 app 容器的上游地址。

域名应解析到服务器。基础 Compose 的 Caddy 会占用 80/443；启动前先检查是否已有 Nginx、Caddy 或其他网站服务占用：

```bash
sudo ss -lntp '( sport = :80 or sport = :443 )'
```

若已有代理提供其他网站，应复用现有代理并调整本项目暴露方式；不要直接停掉共用代理。以下完整启动命令适用于 80/443 可供本项目使用的情况。若 Nginx 目前仅提供旧网页，先按文末步骤启动 app，再停旧入口并启动 Caddy。

## 3. 启动与创建账号

```bash
docker compose --project-directory backend --env-file backend/.env -f backend/compose.yaml -f backend/compose.pansou.yaml config --quiet
docker compose --project-directory backend --env-file backend/.env -f backend/compose.yaml -f backend/compose.pansou.yaml up -d --build
docker compose --project-directory backend --env-file backend/.env -f backend/compose.yaml -f backend/compose.pansou.yaml exec app python -m backend.manage add-user admin --admin
```

管理员密码按提示输入。已有 `admin` 时跳过创建。后续可在个人主页中创建普通用户。

后续更新、查看状态和执行管理命令时，均保留两个 `-f` 参数，以加载外部网络配置。

## 4. 验证实际接口

```bash
docker compose --project-directory backend --env-file backend/.env -f backend/compose.yaml -f backend/compose.pansou.yaml ps
curl --fail https://你的实际域名/healthz
```

`/healthz` 只证明应用可响应，不代表 PanSou 搜索可用。再登录网页、展开搜索设置读取搜索源、执行一次搜索，检查结果和账户信息中的额度。

基础搜索使用上游 `/api/auth/login`、`/api/search`、`/api/health`；账号绑定另外依赖上游 `/{provider}/{hash}` 接口，链接检测依赖 `/api/check/links`。这些扩展功能需要现有 PanSou 版本确实实现对应接口。普通搜索成功不代表绑定和检测也已支持。

## 5. 替换旧网页

先确认旧入口由谁提供：

```bash
docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}'
sudo ss -lntp '( sport = :80 or sport = :443 )'
```

如果仅有 `pansou-api-1`，继续检查宿主机代理或静态站点配置。将域名入口切换到新项目，由新项目同时处理网页与 `/api/*`；不要把新网页的 `/api/*` 直接转发到 PanSou，否则会绕开本项目的登录、CSRF 和额度逻辑，且两个服务的接口格式不同。

如果确认存在独立旧网页容器，在新站验证成功后，先从旧 Compose 文件移除该网页服务，再停止并移除对应的旧网页容器。保留搜索 API、挂载目录及数据卷。当前提供的容器列表没有可确认删除的旧网页容器，因此本说明不猜测容器名或执行删除。

如旧页面由代理的静态目录提供，切换对应域名的站点配置即可；先保留旧文件用于回退，无需删除整个代理服务。

### 推荐：宿主机 Nginx 仅提供旧网页时，切换到自带 Caddy

此流程仅适用于 Nginx 由宿主机 systemd 管理、且不承载其他网站的情况。若 Nginx 运行在容器、面板或其他进程管理器中，应使用对应的服务管理方式停止旧入口，不能直接套用 `systemctl`。域名 DNS 应指向此服务器，公网 TCP 80/443 应可访问。

先完成前文的网络与 `.env` 配置。让新 app 在内部启动，此时旧网页仍可访问：

```bash
docker compose --project-directory backend --env-file backend/.env -f backend/compose.yaml -f backend/compose.pansou.yaml config --quiet
docker compose --project-directory backend --env-file backend/.env -f backend/compose.yaml -f backend/compose.pansou.yaml up -d --build app
docker compose --project-directory backend --env-file backend/.env -f backend/compose.yaml -f backend/compose.pansou.yaml ps
```

确认 app 状态为 healthy，再验证 app 能通过内部网络认证并读取 PanSou 搜索源。此命令仅打印成功提示，不输出 Token：

```bash
docker compose --project-directory backend --env-file backend/.env -f backend/compose.yaml -f backend/compose.pansou.yaml exec app python -c 'import asyncio; from backend.upstream import Upstream; asyncio.run(Upstream().catalog()); print("PanSou API connection OK")'
```

如果失败，先修复网络、认证或上游接口。成功后创建管理员；已有账号时跳过：

```bash
docker compose --project-directory backend --env-file backend/.env -f backend/compose.yaml -f backend/compose.pansou.yaml exec app python -m backend.manage add-user admin --admin
```

确认 Nginx 仅服务旧站后，备份配置。以下备份命令适用于标准 `/etc/nginx` 安装，其他安装使用实际路径：

```bash
sudo tar -czf /root/nginx-before-resource-hub-$(date +%Y%m%d-%H%M%S).tar.gz /etc/nginx
sudo systemctl stop nginx
docker compose --project-directory backend --env-file backend/.env -f backend/compose.yaml -f backend/compose.pansou.yaml up -d proxy
```

随后访问域名，检查 `/healthz`、网页登录、真实搜索、搜索设置和账户额度。证书申请需要域名与端口正确；失败时查看入口日志：

```bash
docker compose --project-directory backend --env-file backend/.env -f backend/compose.yaml -f backend/compose.pansou.yaml logs --tail=80 proxy
```

若需要回退，先释放新入口的端口，再恢复旧 Nginx：

```bash
docker compose --project-directory backend --env-file backend/.env -f backend/compose.yaml -f backend/compose.pansou.yaml stop proxy
sudo systemctl start nginx
```

新站确认正常且决定保留后，再关闭旧 Nginx 的开机启动，避免服务器重启时争抢 80/443：

```bash
sudo systemctl disable nginx
```

回退后若决定继续使用旧 Nginx，应执行 `sudo systemctl enable nginx` 恢复开机启动。旧静态文件可在稳定运行后按实际站点目录单独归档或删除；无需卸载 Nginx，也无需移除 `pansou-api-1`。
