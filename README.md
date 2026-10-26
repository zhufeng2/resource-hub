# Resource Hub

搜索公开的网盘分享，整理搜索结果，并通过本地 Skill 将选中的资源保存到夸克网盘。

**[访问测试网站](https://pan.sysscitech.com/)** · [网页使用](web/README.md) · [MCP 接入](gpt/README.md) · [本地 Skill 安装](docs/LOCAL_SKILLS.md) · [自行部署](backend/README.md)

## 选择使用方式

| 方式 | 适合的需求 | 是否需要自己部署 |
| --- | --- | --- |
| 网页 | 搜索、筛选、检查链接、导出结果和管理个人账号 | 使用已有站点时不需要 |
| MCP | 在支持 MCP 的助手中搜索、翻页和查询额度 | 使用已有服务时不需要 |
| 本地 Skill | 由助手核验资源、整理系列、转存和管理夸克文件 | 需要安装 Skill、连接 MCP，并完成夸克授权 |

网页和 MCP 共用 Resource Hub 账号及每日额度。本地 Skill 复用助手连接的 MCP 搜索服务，目录核验和转存使用夸克官方授权；网页登录不会自动授权助手。网页和 MCP 搜索接口不提供夸克转存功能。

## 在线体验

打开 [pan.sysscitech.com](https://pan.sysscitech.com/)，输入关键词后按提示登录。账号由站点管理员提供，网站目前不提供自助注册。额度以登录后的“账户信息”为准。

测试站用于体验功能，不提供可用性或资源完整性承诺。请自行保留需要长期使用的搜索结果。分享链接可访问不等于文件内容已确认，保存前仍需检查是否符合需要。

## 功能

- 网页搜索支持网盘类型、来源、关键词条件和排序设置。
- 搜索结果支持链接检测、分页，以及 TXT、CSV、JSON 导出。
- 个人主页可查看最近搜索、连接搜索源账号、修改密码和撤销助手授权。
- MCP 提供搜索、读取已有结果、查询额度三个工具。
- 本地 Skill 支持资源核验、系列补齐、夸克转存和文件管理；转存需明确提出保存请求。

只搜索或保存有权访问和使用的内容。搜索结果来自外部来源，标题、画质及完整性需自行核实。

## 文档导航

| 文档 | 内容 |
| --- | --- |
| [网页使用指南](web/README.md) | 登录、搜索设置、结果、个人主页、常见问题 |
| [MCP 接入指南](gpt/README.md) | OAuth、Bearer Token、工具参数和额度规则 |
| [本地 Skill 安装与使用](docs/LOCAL_SKILLS.md) | 环境要求、安装、搜索配置、夸克授权、更新 |
| [服务器部署与维护](backend/README.md) | Docker 部署、账号管理、更新、备份和故障排查 |
| [连接已有 PanSou](backend/EXISTING_PANSOU.md) | Docker 网络、上游认证及旧站入口迁移 |
| [开发指南](docs/DEVELOPMENT.md) | 项目结构、本地启动、测试及网页回归检查 |
| [界面设计规范](web/design/glassmorphism.md) | 浅色毛玻璃、组件、响应式与可访问性 |
| [第三方组件说明](THIRD_PARTY.md) | 来源、组件范围和分发说明 |

## 下载

```bash
git clone https://github.com/zhufeng2/resource-hub.git
cd resource-hub
```

使用在线站点无需下载代码。安装 Skill 请继续阅读[安装指南](docs/LOCAL_SKILLS.md)；搭建自己的站点请阅读[部署指南](backend/README.md)。
