# MCP 接入指南

Resource Hub 通过 MCP 向助手提供资源搜索、读取结果和额度查询。网页与 MCP 使用同一账号，搜索记录和额度共享。

[返回项目首页](../README.md) · [网页使用](../web/README.md) · [服务器部署](../backend/README.md)

## 服务地址与账号

MCP 地址是在 Resource Hub 网站根地址后加 `/mcp`。测试站地址为：

```text
https://pan.sysscitech.com/mcp
```

账号由站点管理员提供。自建服务请使用自己的域名。这个地址是 MCP 入口，不是 PanSou 上游 API，也不是夸克授权入口。

## OAuth 连接

适用于支持 OAuth 的 MCP 客户端：

1. 添加自定义 MCP 服务，填写站点的 `/mcp` 地址。
2. 选择 OAuth 认证，打开 Resource Hub 授权页。
3. 输入站点账号和密码，确认授权。
4. 返回助手，调用搜索或额度工具验证连接。

ChatGPT 可按以上流程连接。管理员需要将客户端显示的准确回调地址配置到 `OAUTH_REDIRECT_URIS`。本服务支持动态客户端注册、Authorization Code + PKCE S256，Token 端点认证方式为 `none`，授权范围为 `search`。

授权页过期、已使用或 Cookie 无效时，从客户端重新发起连接，不要重复提交旧页面。网页“个人主页 → 安全与连接”可撤销 ChatGPT 授权。

## Bearer Token 连接

适用于支持 Streamable HTTP 与自定义请求头的客户端。向管理员申请 MCP Token，在客户端配置：

```text
URL: https://你的域名/mcp
Authorization: Bearer 你的MCP令牌
```

该 Token 由 Resource Hub 签发，不能填入 `PANSOU_API_TOKEN`，也不能使用 PanSou 的 Token 替代。Token 按用户隔离并共享账号额度，重新签发会使旧 Token 失效。

### DeepSeek Harness 配置示例

在 Profile patch（`$DSH_HOME/profiles/<profile>/cordis.patch.yml`）中合并：

```yaml
- insert:
    - id: resource-hub-mcp
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: resource-hub
        transport: streamable-http
        url: https://你的域名/mcp
        headers:
          Authorization: Bearer 你的MCP令牌
```

将地址和令牌替换为管理员提供的实际值，再按客户端方式加载配置。不要把含真实 Token 的配置提交到仓库。

### 管理员签发与吊销

以下命令在已部署服务的仓库根目录执行。连接已有 PanSou、使用了 Compose 覆盖文件时，在 `exec` 前增加 `-f backend/compose.pansou.yaml`。

```bash
docker compose --project-directory backend --env-file backend/.env -f backend/compose.yaml exec app python -m backend.manage issue-mcp-token alice --days 365
docker compose --project-directory backend --env-file backend/.env -f backend/compose.yaml exec app python -m backend.manage list-mcp-tokens
docker compose --project-directory backend --env-file backend/.env -f backend/compose.yaml exec app python -m backend.manage revoke-mcp-token alice
```

签发前账号必须已存在。Token 只显示一次，妥善交付给对应用户；吊销后客户端需重新配置。OAuth 授权与长期 MCP Token 使用不同管理入口，停用账号或重置密码会撤销已有授权。

## 工具

| 工具 | 参数 | 用途与计次 |
| --- | --- | --- |
| `search_resources` | `query`，可选 `request_id` | 搜索夸克分享；成功计 1 次，零结果也计次 |
| `get_search_results` | `search_id`，可选 `offset`、`limit` | 读取本账号已有结果；不重新搜索、不扣新额度 |
| `get_quota` | 无 | 查询今日用量、剩余及重置时间；免费 |

`query` 为 1–120 字符，`request_id` 最多 80 字符，允许字母、数字、短横线和下划线。同一账号重试同一搜索时复用 `request_id`，可避免重复计次。

每次搜索最多保存前 200 条结果；翻页每页 1–50 条，默认 20 条。结果在 24 小时内可读取。返回前会检测链接并剔除确认失效的结果，但不会核验文件内容、清晰度或完整性。

## 使用示例

- “搜索某部电影的夸克分享。”
- “查看上一轮搜索的下一页。”
- “我今天还剩多少次搜索？”

翻页应复用已有 `search_id`，不应通过重新搜索实现。MCP 接口仅用于搜索和读取结果，需要转存到夸克时使用[本地 Skill](../docs/LOCAL_SKILLS.md)。

## 额度规则

- 普通账号默认每天 5 次，以管理员设置和查询结果为准；管理员不受每日额度限制。
- 按搜索开始时的北京时间日期计次，零点重置。
- 成功搜索计 1 次，失败或取消后归还预占额度。
- 查询额度、读取有效期内已有结果和翻页免费。
- 每账号每分钟最多调用搜索工具 30 次；频繁重试应稍后再试。

## 排查连接问题

| 现象 | 检查方式 |
| --- | --- |
| 401 或要求重新登录 | 检查 Token 是否过期或被吊销，OAuth 客户端重新授权 |
| 授权页提示过期 | 从客户端重新添加或发起连接，使用新授权页面 |
| 回调失败 | 管理员检查准确回调地址、站点域名及反向代理 |
| 额度不足 | 调用 `get_quota`，等待重置或联系管理员 |
| 查询已有结果失败 | 确认是同一账号、结果未超过 24 小时 |

服务端实现位于 `server.py` 和 `oauth.py`，开发与测试见[开发指南](../docs/DEVELOPMENT.md)。
