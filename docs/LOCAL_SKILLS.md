# 本地 Skill 安装与使用

本地 Skill 负责资源筛选、系列完整性和归档流程；搜索与网盘操作统一通过 Resource Hub MCP。

## 安装与更新

```bash
git clone https://github.com/zhufeng2/resource-hub.git
cd resource-hub
python3 install.py
```

默认仅安装 resource-hub 到 `$CODEX_HOME/skills`，未设置时使用 `~/.codex/skills`。可用 `--skills-dir /path/to/skills` 指定目录；已有安装使用 `--update`，先备份再替换，移除旧运行脚本。更新后新建聊天加载。安装不再分发或更新官方 quarkclouddrive Skill，也不会擅自卸载设备上已有的独立官方工具或撤销其授权。

## 连接与绑定

在助手中连接站点 `/mcp` 地址，通过 OAuth 或 Authorization Bearer Token 认证。使用 get_quota 免费检查连接。用户在网站“个人主页 → 安全与连接”绑定夸克 Cookie，即可读取网盘、转存和创建目录。不要在聊天、工具参数或本地 Skill 配置中填写 Cookie。

本地无需 Node.js 或夸克运行工具；Node.js 由服务端维护。安装器需要 Python 3.10+；流程说明没有本地运行脚本、缓存或账号配置。MCP 不可用时提示重新连接，不回退到共享账号或官方 CLI。

## 使用

- “搜索某部电影，列出合适的夸克链接。”
- “检查这个分享是否包含完整剧集。”
- “把这些选中的文件转存到 AI转存/作品名。”
- “查看我网盘里保存的文件。”

Skill 使用 quark_share_files 核验分享，quark_list_files 定位目录，quark_create_folder 创建缺失目录，quark_save_entries 批量转存明确文件及目录，quark_rename 调整名称，quark_move 移动文件及目录。写工具默认预览，用户已明确授权时 execute=true；每个操作记录唯一 request_id，超时先查 quark_operation_status，再用原参数、原 ID 续查。

只有 phase=verified 才报告完成。当前不支持上传或删除；观看指南交付本地文件并注明未上传。个人搜索与建目录尚未真实接口验证，不能将离线测试通过说成实测完成。

搜索及翻页规则见 [MCP 接入指南](../gpt/README.md)，流程见 [resource-hub 技能](../skills/resource-hub/SKILL.md)。

旧 Skill 的搜索/检链/缓存/进度脚本及兼容测试已移除，业务实现只维护在 MCP 服务端。此目录仅保留 MCP 调用流程说明。
