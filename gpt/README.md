# ChatGPT MCP

`server.py` 定义搜索、读取结果与查询额度工具，`oauth.py` 提供账号授权流程。账号、搜索与额度逻辑由 `online/` 共用。

统一启动入口为 `online.app:create_app`，MCP 地址为服务域名下的 `/mcp`。部署和连接方式见 [部署说明](../online/README.md)。
