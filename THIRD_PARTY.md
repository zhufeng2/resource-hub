# 第三方组件

## 夸克网盘官方 Skill

- 组件目录：`skills/quarkclouddrive/`
- 技能版本：1.0.25（以目录内 `SKILL.md` 为准）
- 提供方：夸克网盘
- 官方网站：https://pan.quark.cn
- 官方安装配置接口：https://open-api-drive.quark.cn/agent/v1/skill_config
- 本仓库收录范围：技能说明、参考文档、官方安装与卸载脚本。
- 不收录：官方打包运行工具、账号授权信息、用户配置、目录记录和缓存。

该组件保留原有内容。运行工具由官方安装脚本从官方服务获取，可能独立更新。组件权利归相应权利方所有，本仓库不为其授予额外许可证，也不代表官方背书。

## PanSou API

`resource-hub` 调用外部搜索服务，默认地址为 `https://pan.sysscitech.com`，可配置其他兼容服务。

## PanSou Web 接口兼容

网页的搜索配置与搜索源账号流程参考 [fish2018/pansou-web](https://github.com/fish2018/pansou-web) 的接口定义。页面布局、样式与交互在本项目中独立实现。
