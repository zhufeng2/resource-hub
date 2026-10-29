# MCP 接入指南

Resource Hub 通过 MCP 向助手提供资源搜索、读取结果、额度查询和用户绑定的夸克网盘操作。网页与 MCP 使用同一账号，搜索记录和额度共享。

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

授权页过期、已使用或 Cookie 无效时，从客户端重新发起连接，不要重复提交旧页面。OAuth 连接仍处于开发阶段；当前网页主要提供通用 MCP Token 管理。

## Bearer Token 连接

适用于支持 Streamable HTTP 与自定义请求头的客户端，不限于 ChatGPT。登录网页，进入“个人主页 → 安全与连接 → MCP 服务”，生成当前账号的 Token，并复制 HTTP 地址与 Token。在客户端配置：

```text
URL: https://你的域名/mcp
Authorization: Bearer 你的MCP令牌
```

该 Token 由 Resource Hub 签发，不能填入 `PANSOU_API_TOKEN`，也不能使用 PanSou 的 Token 替代。Token 按用户隔离并共享账号额度，默认有效期 7 天。登录后可随时显示和复制自己的 Token；服务器加密保存可恢复副本，不在网页本地存储中持久化。旧版仅有哈希的 Token 仍能认证，但无法显示，需主动重新生成一次。重新生成会使原 Token 立即失效，客户端需更新配置；单独撤销 Token 不影响 OAuth。

有效期自签发时起计算为 7 × 24 小时；重新生成后开始新的 7 天，旧 Token 立即失效。过期后登录网页重新生成，并更新客户端中的 `Authorization: Bearer <Token>` 请求头。已有 Token 保留签发时的到期时间；改为一星期需主动重新生成。网页不展示请求头示例或到期时间，配置说明以本文为准。网页登录会话仍为 7 天，OAuth 访问令牌另行管理。

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
docker compose --project-directory backend --env-file backend/.env -f backend/compose.yaml exec app python -m backend.manage issue-mcp-token alice --days 7
docker compose --project-directory backend --env-file backend/.env -f backend/compose.yaml exec app python -m backend.manage list-mcp-tokens
docker compose --project-directory backend --env-file backend/.env -f backend/compose.yaml exec app python -m backend.manage revoke-mcp-token alice
```

签发前账号必须已存在。命令行签发的 Token 也可由对应用户登录网页后查看和复制；吊销后客户端需重新配置。OAuth 授权与长期 MCP Token 使用不同管理入口，停用账号或重置密码会撤销已有授权。

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

翻页应复用已有 `search_id`，不应通过重新搜索实现。MCP 可直接读取已绑定夸克账号、建目录、改名、移动以及批量转存文件和目录；[本地 Skill](../docs/LOCAL_SKILLS.md) 提供系列筛选和归档流程。

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
| 查询已有结果失败 | 确认是同一账号、结果未超过 24 小时且未在网页中删除 |

服务端实现位于 `server.py` 和 `oauth.py`，开发与测试见[开发指南](../docs/DEVELOPMENT.md)。

## 夸克网盘绑定与操作

用户在网站“个人主页 → 安全与连接 → 夸克网盘”填写一整行 Cookie，验证并保存。Cookie 仅通过登录会话及 CSRF 保护的 HTTPS POST 提交，默认隐藏，显示和复制仅在本人主动点击时读取，不作为工具参数。绑定后，该用户已授权的 MCP 客户端即可读取网盘、转存和创建目录。

| 工具 | 用途 |
| --- | --- |
| `quark_status` | 查看绑定状态，不返回凭据 |
| `quark_list_files` | 按 parent_fid、page、size 读取个人目录 |
| `quark_search_files` | 个人网盘搜索，已通过小范围真实验证 |
| `quark_file_info` | 读取个人文件允许的元数据 |
| `quark_share_files` | 按真实目录 fid 分页读取分享，不返回令牌 |
| `quark_create_folder` | 指定父目录及名称创建目录，默认预览 |
| `quark_save_file` | 选定单文件转存到指定目录，默认预览 |
| `quark_operation_status` | 以 request_id 查询当前绑定的操作记录 |

写工具需要 request_id（1–80 位字母、数字、短横线或下划线），execute 默认 false；明确执行时设为 true。同一操作的重试或续查必须复用原参数和原编号，不改变编号重新提交。不同用户、绑定及操作记录独立；更新绑定后旧记录不会在新账号继续运行。任务结束不等于目标核验完成，只有 phase=verified 才表示操作通过核验。

夸克操作不扣公开资源搜索额度，仍受 MCP 限流约束。分享目录为有界分页，未读完不能判完整。当前尚无上传和删除工具；不能用它上传观看指南。建目录与个人搜索已通过小范围真实验证。Cookie 更新只在单次调用中保留，不构成长期自动刷新登录。

解绑后后续请求不能再使用该凭据；已发送至夸克的操作可能继续完成。更新绑定前应先处理未完成任务。


### 批量转存与系列整理

- `quark_save_entries(share_url, fids, source_parent_fid, to_parent_fid, request_id, execute=false)`：一次提交同一分享目录中明确选中的 1–100 个文件或文件夹。整系列文件夹可直接原生转存，无需逐集调用；内部获取令牌，不自动全选无关条目。不同分享或不同父目录分别建立操作。
- `quark_rename(fid, name, request_id, execute=false)`：修改个人文件或文件夹名称，适用于系列目录重命名。
- `quark_move(fids, to_parent_fid, request_id, execute=false)`：一次移动 1–100 个个人文件或文件夹。移动系列文件夹会整体调整其位置，不逐集移动。

这些工具同样默认预览；execute=true 才执行，重试复用原参数及编号。遇到同名条目不覆盖、不合并，暂停并返回 name_conflict。移动会读取实际目标祖先，拒绝将目录移入自身或后代。任务记录在提交前建立，响应不明时不自动重提。

批量转存不依赖返回 ID 的顺序，按目标 ID、名称、类型、文件大小和目标目录核对选中顶层条目。目录成功返回 verification_scope=selected_top_level_entries、descendants_verified=false，明确没有对目录内部做完整递归审计；不能据此保证全系列完整。目录转存、改名和移动已完成小范围真实写入及回读验证，详见 [实测记录](../docs/MCP_LIVE_TEST_20261030.md)。上传和删除仍需补充实际接口实现。


### 指定文件夹观看进度归零

`quark_reset_folder_progress(folder_fid, folder_name, request_id, include_subfolders=true, explicitly_requested=false, execute=false)` 只处理明确指定文件夹内的视频，拒绝根目录 0，并核对实际文件夹名称。只有用户明确要求该范围观看进度全部归零时，才能设置 explicitly_requested=true、execute=true；不会因搜索或转存而触发。

复用研究项目 `examples/set-progress.cjs` 和 `src/playback.cjs` 的已封装接口：每个视频只上报一次 `source=PLAY / extra.play_progress=0`，之后延迟回读个人详情的 `last_play_info.time`；不把业务成功直接当作进度持久化成功。提交状态不明时，仅继续回读，不重复上报。

大系列每次最多处理5个视频，原请求编号接续；目录枚举最多200个目录、10000个条目、2000个视频，完整枚举失败不开始写入。已移动到范围外的文件停止处理。缺少有效时长的条目计入 skipped，返回 partial；只有全部确认是0才返回 verified。新批量流程通过模拟测试，未执行真实进度重置。
