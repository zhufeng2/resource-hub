# 第三方组件与来源

## 夸克接口库

`backend/quark_client/` 由用户提供的夸克网盘研究接口整理而来，保留部署需要的查询、目录、转存、改名移动、文本创建和播放进度模块，并提供 Resource Hub 的隔离调用适配。协议采集和中间研究产物在独立研究项目维护。未复制 Cookie、账号配置、研究抓取产物或官方打包 CLI。该接口不是官方开放平台授权方案，本项目不代表夸克官方背书。

项目不再分发或安装官方 `quarkclouddrive` Skill；已独立安装的官方工具不由本项目自动卸载。

## PanSou 搜索服务

Resource Hub 服务端通过兼容 API 使用外部 PanSou 服务，本地 Skill 仅编排 MCP。上游由部署者或使用者配置，本仓库不附带搜索服务的运行实例或访问凭据。

项目测试网站 [pan.sysscitech.com](https://pan.sysscitech.com/) 提供 Resource Hub 使用入口，不应仅依据域名将其视作可直接调用的 PanSou 上游 API。

## PanSou Web 接口兼容

公开搜索配置接口参考 [fish2018/pansou-web](https://github.com/fish2018/pansou-web) 的接口定义。页面布局、样式与交互在本项目中独立实现。

## 设计参考

浅色毛玻璃界面参考 [StyleKit Glassmorphism](https://www.stylekit.top/zh/styles/glassmorphism) 的材质思路。本项目的配色、布局和可读性规范见[开发指南中的界面规范](docs/DEVELOPMENT.md#界面规范)。
