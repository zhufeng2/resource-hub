# Resource Hub + 夸克网盘 Skills

供 Codex 等支持 `SKILL.md` 的助手使用：搜索资源、核对候选，并通过夸克官方工具转存。两个技能放在同一个仓库，方便安装和跨设备同步。

这是个人维护的组合仓库，不是夸克官方发布仓库。

## 两个技能分别做什么

| 技能 | 用途 |
| --- | --- |
| `resource-hub` | 通过 API/CLI 搜索资源，整理系列清单，筛选候选，协调转存 |
| `quarkclouddrive` | 通过官方工具授权账号、查找文件、读取分享、转存及管理网盘文件 |

仅搜索不会写入网盘。明确要求“转存/保存”后才执行保存。默认只搜索夸克资源。

核对限于两类：

1. **资源有无问题**：链接可访问、实际内容对应目标作品、部数或集数没有明显缺项，排除广告。
2. **转存是否成功**：以官方成功结果为准；只有报错、数量不符或结果不明确时才补查。

默认保存到网盘根目录下的 `AI转存/<系列>/<独立作品或季>`，例如 `AI转存/蜘蛛侠系列/蜘蛛侠（2002）`。单部作品使用 `AI转存/<作品名>`。不额外增加“电影”“来自：Codex”等父目录；用户明确指定其他位置时按其要求执行。

## 安装

需要 Python 3.10+。夸克官方工具使用 Node.js 16+，首次使用时由其安装脚本检查环境。

克隆本仓库后，在仓库目录运行：

```bash
python3 install.py
```

默认安装到 `$CODEX_HOME/skills`；未设置 `CODEX_HOME` 时使用 `~/.codex/skills`。两个技能必须保留同级目录关系。

如果已经安装过，使用：

```bash
python3 install.py --update
```

更新前会将已有技能完整备份到技能目录旁的 `skill-backups/`，并保留设备本地的官方运行工具和账号配置。备份可能包含本地账号信息，请勿上传或分享备份。更新后新开一个对话加载技能。

其他支持本地技能的助手可以指定技能目录：

```bash
python3 install.py --skills-dir /你的/全局技能目录
```

## 首次配置

### 搜索服务

`resource-hub` 需要可用的 PanSou API 服务和你自己的访问凭据。默认服务地址为 `https://my-pansou-api.onrender.com`；本仓库不提供共享账号，也不保证第三方服务持续可用。

以默认安装位置为例，在自己的终端配置并验证：

```bash
python3 ~/.codex/skills/resource-hub/scripts/resource.py setup
python3 ~/.codex/skills/resource-hub/scripts/resource.py auth-test
```

使用自建服务时，可设置 `PANSOU_BASE_URL`。账号密码模式使用配对的 `PANSOU_USERNAME` / `PANSOU_PASSWORD`；固定 API token 模式使用 `PANSOU_API_TOKEN`。不要把实际凭据写进仓库或聊天。服务配置详情见 [resource-hub 技能说明](skills/resource-hub/SKILL.md)。

### 夸克授权

在助手中提出网盘操作请求，按官方技能提示完成账号授权。官方安装脚本会从夸克服务下载运行工具，本仓库不包含已安装的运行文件或任何人的登录状态。每台设备单独授权。

如需手动准备官方运行工具，以默认安装位置为例：

```bash
cd ~/.codex/skills/quarkclouddrive
bash scripts/install.sh
```

该脚本由夸克官方组件提供，可能更新技能说明和运行工具；请先阅读 [官方技能说明](skills/quarkclouddrive/SKILL.md)。

## 使用示例

- “使用 resource-hub 搜索某部电影。”
- “搜索这个系列的全部电影并转存到夸克。”
- “只补齐缺少的几部，存到 AI转存/系列名。”
- “使用夸克网盘技能查找我已保存的文件。”

请仅保存你有权访问、使用和保存的内容。

## 跨设备同步

在另一台设备克隆本仓库，运行 `python3 install.py`，再单独配置搜索服务并授权夸克。

已有安装需要同步仓库中的技能文件时：

```bash
git pull --ff-only
python3 install.py --update
```

仓库只同步技能代码与说明。网盘文件、账号凭据、缓存、搜索结果和任务进度不通过 GitHub 同步。官方工具可通过其安装脚本独立更新。

GitHub 登录授权仅用于维护者本机的仓库操作，不随本仓库分发。使用者克隆公开仓库不需要共享维护者的 GitHub 授权。建议在仓库内修改技能，再运行安装命令同步到本机；不要将含账号配置的已安装目录整包复制回仓库。

## 开发检查

以下检查使用离线模拟数据，不登录账号、不转存文件：

```bash
python3 skills/resource-hub/tests/test_workflow.py
python3 -m compileall -q install.py skills/resource-hub/scripts
bash -n skills/quarkclouddrive/scripts/install.sh
bash -n skills/quarkclouddrive/scripts/uninstall.sh
```

## 来源与分发说明

`resource-hub` 为本仓库维护的搜索协调技能。`quarkclouddrive` 为夸克官方技能组件，来源和版本说明见 [THIRD_PARTY.md](THIRD_PARTY.md)。本仓库没有为官方组件另行授予开源许可证；使用、修改和再分发时应遵循其适用条款。
