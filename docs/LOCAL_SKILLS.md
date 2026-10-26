# 本地 Skill 安装与使用

本地 Skill 让支持技能目录的助手完成资源搜索、链接与文件核验，以及夸克转存和文件管理。仅使用网页搜索无需安装。

[返回项目首页](../README.md) · [网页使用](../web/README.md) · [MCP 接入](../gpt/README.md)

## 环境要求

- Python 3.10 或更新版本。
- 使用夸克官方工具时需要 Node.js 16 或更新版本，安装脚本会检查环境。
- 可以加载本地 Skill 的助手。
- 可用的 PanSou 兼容搜索 API 地址和凭据；涉及转存时还需夸克网盘账号。

## 安装

```bash
git clone https://github.com/zhufeng2/resource-hub.git
cd resource-hub
python3 install.py
```

默认安装 `resource-hub` 和 `quarkclouddrive` 两个 Skill 到 `$CODEX_HOME/skills`，未设置 `CODEX_HOME` 时使用 `~/.codex/skills`。

指定其他助手的技能目录：

```bash
python3 install.py --skills-dir /path/to/skills
```

安装后，在助手中新建对话以加载技能。Windows 可根据环境将 `python3` 替换为 `python` 或 `py -3`，路径含空格时加引号。

## 配置搜索服务

向搜索服务提供方获取 PanSou API 地址和凭据，在终端交互配置。以下命令适用于默认安装路径：

```bash
python3 ~/.codex/skills/resource-hub/scripts/resource.py setup
python3 ~/.codex/skills/resource-hub/scripts/resource.py auth-test
```

使用自定义安装目录时替换路径。`setup` 保存配置，`auth-test` 验证登录和搜索权限；保存配置本身不代表已连接成功。

也可由运行环境注入：

| 变量 | 用途 |
| --- | --- |
| `PANSOU_BASE_URL` | 提供方给出的 PanSou 兼容 API 地址 |
| `PANSOU_USERNAME` / `PANSOU_PASSWORD` | 配套账号密码，必须成对配置 |
| `PANSOU_API_TOKEN` | 固定 API Token，配置后优先于账号密码 |

Resource Hub 测试站的网页账号和 MCP Token 不能直接作为 PanSou 凭据使用。安装后请检查并配置实际可用的上游地址，不依赖脚本内置地址。完整参数见 [resource-hub 技能规范](../skills/resource-hub/SKILL.md)。

## 授权夸克网盘

在助手中提出网盘操作请求，按官方工具提示完成授权。首次使用需要下载运行工具；安装定义文件不会自动登录网盘。

也可以在 macOS/Linux 终端手动安装运行工具：

```bash
cd ~/.codex/skills/quarkclouddrive
bash scripts/install.sh
```

使用自定义路径时替换目录。官方工具的安装、授权和使用要求见 [夸克网盘 Skill](../skills/quarkclouddrive/SKILL.md)。授权信息只保存在执行工具的设备上。

## 示例请求

- “搜索某部电影，列出合适的夸克链接。”
- “核验这个分享是否包含完整剧集。”
- “搜索这个系列的电影并转存到夸克。”
- “只补齐缺少的几部，保存到 AI转存/系列名。”
- “查找我网盘里已保存的文件。”

默认搜索夸克资源。只要求搜索时不会写入网盘；明确要求转存后，才调用官方工具保存。默认保存到 `AI转存/<作品名>`；系列使用 `AI转存/<系列>/<作品或季>`。请求中可指定其他目录和范围。

链接有效、读取到目录、内容匹配和转存成功是不同状态。助手应根据实际核验和官方返回结果说明完成情况，不仅依据分享标题判断。

## 更新

在仓库目录执行：

```bash
git pull --ff-only
python3 install.py --update
```

首次安装使用了自定义目录时，更新时也要带上相同的 `--skills-dir` 参数。更新会先备份已安装目录到技能目录旁的 `skill-backups/`，再合并文件，保留本机运行工具及账号配置。备份可能含凭据，应限制访问。更新后新建对话加载新版本。

## 常见问题

**已经登录网页，为什么本地还要求配置？**

网页和 MCP 使用 Resource Hub 账号，本地搜索使用 PanSou 凭据，夸克操作使用网盘授权，三者分别配置。

**搜索成功但不能转存？**

检查夸克运行工具是否安装、账号是否授权，以及分享是否仍可访问。

**找不到 Skill 或脚本？**

检查安装输出中的实际路径，以及助手配置的技能目录。默认路径仅是示例，不适用于所有客户端。
