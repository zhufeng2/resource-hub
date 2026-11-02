# Resource Hub 与 StreamBox 共用夸克 Cookie

本次直接复用现有 MCP 的 quark_accounts 记录，按已登录用户绑定。服务器继续使用现有 Fernet 密钥加密，密文中的 user_id/binding_id 与数据库行交叉核对。没有新增凭据表、密钥或独立服务。

## 接口

- GET /api/quark-account：现有绑定状态及版本，不含 Cookie。
- POST /api/quark-account：用户手动设置 Cookie，沿用校验成功再替换的规则；校验失败保留原绑定。
- DELETE /api/quark-account：解除当前用户绑定，App 与 MCP 都不再使用该绑定。
- POST /api/quark-account/session：新增，返回当前用户同一快照的 bound/id/updated_at/cookie，未绑定返回 bound=false。
- POST /api/quark-account/reveal：原网页显式查看入口保持兼容。

凭据读取必须经过当前登录用户、Origin 和 CSRF 校验；不接受 user_id 等客户端选定归属字段。响应 no-store；新入口每用户每分钟最多 60 次。日志不输出 Cookie，请勿为此入口启用请求/响应正文日志。

## App 策略

登录后、回到前台、打开设置及应用运行中周期性读取云端版本。自动同步只读，不会用旧本机 Cookie 覆盖服务器。只有用户手动保存时才上传，新绑定仍供 MCP 使用。App Cookie 仅在进程内存中使用，不保存到本机磁盘；Cookie 的账号归属与绑定版本也只保留在内存中。

手动保存先在 App 只读验证，再调用服务器原有绑定校验，成功后重新读取云端当前版本导入本机。云端更新成功而本机导入失败时显示已更新、待重新同步；不会声称服务端已经回滚。网络错误、断网或登录失效时清除 App 内存凭据并显示未连接，不使用离线回退。恢复网络后重新确认云端。升级时清除旧版本本机 Cookie，不自动上传。

## 升级

将本仓库 main 更新到本次提交，在服务器项目根目录按现有方式重建 app：

```sh
git pull --ff-only
docker compose -f backend/compose.yaml up -d --build app
```

保留原数据卷和 Cookie 加密密钥；无需手工迁移数据库。然后安装配套 StreamBox 版本，登录同一 Resource Hub 用户，联网后自动读取云端 Cookie。设置页仅显示连接状态与更改入口。

新接口不等于生产已经部署。本轮未读取真实 Cookie，也未执行真实账号同步、目录转存或播放测试。
