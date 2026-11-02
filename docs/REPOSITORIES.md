# 仓库分工

| 项目 | 本地路径 | GitHub | 维护范围 |
| --- | --- | --- | --- |
| Resource Hub | `D:\学习资料\resource-hub` | https://github.com/zhufeng2/resource-hub | 服务器网页、账号、搜索、MCP、网盘后端与云同步 API |
| StreamBox | `D:\学习资料\streambox` | https://github.com/zhufeng2/streambox（私有） | Android App、播放器、缓存和同步客户端 |

App 不属于此仓库，也不是 Git 子模块。服务器 Docker 构建继续只发送 backend/ 和 web/。账号同步仍由当前后端提供，不增加独立服务器进程；API 约定见 [云同步](STREAMBOX_CLOUD_SYNC.md)。

Android 项目、真实本机开发配置、IDE/Gradle 缓存和历史截图已保留在新的本地目录。App 安装包移至 `streambox/dist/`；服务端历史更新 ZIP 位于本地 `resource-hub/releases/`。这些产物均不提交 Git。

App 的旧 `resource-hub/android` 路径仅是历史文档中的路径。今后在 Android Studio 打开 `D:\学习资料\streambox`，服务器开发继续使用此仓库。
