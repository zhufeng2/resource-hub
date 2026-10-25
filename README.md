# Resource Hub

在网页或 ChatGPT 中搜索网盘资源，也可安装本地 Skill 完成核验、转存和文件管理。

| 使用方式 | 功能 | 入口 |
| --- | --- | --- |
| 本地 Skill | 资源搜索、核验、夸克转存和文件管理 | 按下方步骤安装 |
| 网页搜索 | 居中搜索、原地搜索设置、结果导出和个人主页 | [部署与使用说明](backend/README.md) |
| ChatGPT MCP | 资源搜索、结果翻页、每日额度查询 | 使用同一服务的 `/mcp` 地址 |

## 项目结构

- `web/`：网页路由、页面样式与交互。
- `gpt/`：ChatGPT MCP 工具和 OAuth 授权。
- `backend/`：共用的账号、搜索、额度及部署配置。
- `skills/`：本地 Skill。

网页与 GPT 服务使用同一数据库，部署入口为 `backend.app:create_app`。

## 本地安装

需要 Python 3.10+。夸克官方工具需要 Node.js 16+，安装时会检查环境。

下载或克隆本仓库后，在仓库目录运行：

```bash
python3 install.py
```

默认安装到 `$CODEX_HOME/skills`；未设置 `CODEX_HOME` 时使用 `~/.codex/skills`。也可以指定其他助手的技能目录：

```bash
python3 install.py --skills-dir /你的/技能目录
```

安装完成后，新开一个对话加载技能。

### 配置搜索服务

准备可用的 PanSou 服务地址及访问凭据。默认服务地址为 `https://pan.sysscitech.com`。

以默认安装位置为例，在终端配置并验证：

```bash
python3 ~/.codex/skills/resource-hub/scripts/resource.py setup
python3 ~/.codex/skills/resource-hub/scripts/resource.py auth-test
```

也可以使用环境变量配置：

| 变量 | 用途 |
| --- | --- |
| `PANSOU_BASE_URL` | PanSou 服务地址 |
| `PANSOU_USERNAME` / `PANSOU_PASSWORD` | 账号密码，需同时设置 |
| `PANSOU_API_TOKEN` | 固定 API Token，优先于账号密码 |

凭据请保存在本机配置或环境变量中。完整配置见 [resource-hub 技能说明](skills/resource-hub/SKILL.md)。

### 授权夸克网盘

在助手中提出网盘操作请求，按提示完成授权。首次使用会下载官方运行工具。

也可以手动安装：

```bash
cd ~/.codex/skills/quarkclouddrive
bash scripts/install.sh
```

授权和工具说明见 [夸克网盘 Skill](skills/quarkclouddrive/SKILL.md)。

## 使用

- “搜索某部电影。”
- “搜索这个系列的全部电影并转存到夸克。”
- “只补齐缺少的几部，存到 AI转存/系列名。”
- “查找我已保存的文件。”

默认搜索夸克资源；提出转存请求后保存文件。单部作品保存到 `AI转存/<作品名>`，系列保存到 `AI转存/<系列>/<作品或季>`，也可在请求中指定目录。

`resource-hub` 负责资源搜索、筛选与核验，`quarkclouddrive` 负责网盘授权、转存和文件管理。请仅保存你有权使用的内容。

## 更新

在仓库目录拉取更新后重新安装：

```bash
git pull --ff-only
python3 install.py --update
```

更新前会备份已安装的技能到技能目录旁的 `skill-backups/`，并保留本机运行工具和账号配置。备份可能包含账号信息，请妥善保管。更新后新开一个对话。

## 开发检查

```bash
python3 skills/resource-hub/tests/test_workflow.py
python3 -m compileall -q install.py skills/resource-hub/scripts
bash -n skills/quarkclouddrive/scripts/install.sh
bash -n skills/quarkclouddrive/scripts/uninstall.sh
```

在线服务的测试与部署步骤见 [backend/README.md](backend/README.md)。

## 来源

本仓库由个人维护。`quarkclouddrive` 采用夸克官方 Skill 组件，其来源与分发条款见 [THIRD_PARTY.md](THIRD_PARTY.md)。
