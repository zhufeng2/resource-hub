# 第三方组件与来源

## 夸克网盘官方 Skill

- 组件目录：`skills/quarkclouddrive/`
- 技能版本：1.0.25，以目录内 `SKILL.md` 为准。
- 提供方：夸克网盘。
- 官方网站：[夸克网盘](https://pan.quark.cn)。
- 安装配置接口：[官方 Skill 配置](https://open-api-drive.quark.cn/agent/v1/skill_config)。
- 本仓库收录技能说明、参考文档、官方安装与卸载脚本。
- 官方打包运行工具、账号授权信息、用户配置、目录记录和缓存不随仓库分发。

该组件保留原有内容。运行工具由官方安装脚本从官方服务获取，可能独立更新。组件权利归相应权利方所有，本仓库不为其授予额外许可证，也不代表官方背书。

## PanSou 搜索服务

Resource Hub 和本地搜索 Skill 通过兼容 API 使用外部 PanSou 服务。上游由部署者或使用者配置，本仓库不附带搜索服务的运行实例或访问凭据。

项目测试网站 [pan.sysscitech.com](https://pan.sysscitech.com/) 提供 Resource Hub 使用入口，不应仅依据域名将其视作可直接调用的 PanSou 上游 API。

## PanSou Web 接口兼容

网页搜索配置和搜索源账号流程参考 [fish2018/pansou-web](https://github.com/fish2018/pansou-web) 的接口定义。页面布局、样式与交互在本项目中独立实现。

## 设计参考

浅色毛玻璃界面参考 [StyleKit Glassmorphism](https://www.stylekit.top/zh/styles/glassmorphism) 的材质思路。本项目的配色、布局和可读性规范见[界面设计规范](web/design/glassmorphism.md)。
