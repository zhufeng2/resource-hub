# 第三方组件与来源

## 夸克接口库

`backend/quark_client/` 从用户提供的夸克网盘研究项目 `src/` 接入，保留业务模块和单文件转存流程，新增 Resource Hub 的隔离调用适配。未复制 Cookie、账号配置、研究抓取产物或官方打包 CLI。该接口不是官方开放平台授权方案，本项目不代表夸克官方背书。

项目不再分发或安装官方 `quarkclouddrive` Skill；已独立安装的官方工具不由本项目自动卸载。

## PanSou 搜索服务

Resource Hub 和本地搜索 Skill 通过兼容 API 使用外部 PanSou 服务。上游由部署者或使用者配置，本仓库不附带搜索服务的运行实例或访问凭据。

项目测试网站 [pan.sysscitech.com](https://pan.sysscitech.com/) 提供 Resource Hub 使用入口，不应仅依据域名将其视作可直接调用的 PanSou 上游 API。

## PanSou Web 接口兼容

网页搜索配置和搜索源账号流程参考 [fish2018/pansou-web](https://github.com/fish2018/pansou-web) 的接口定义。页面布局、样式与交互在本项目中独立实现。

## 设计参考

浅色毛玻璃界面参考 [StyleKit Glassmorphism](https://www.stylekit.top/zh/styles/glassmorphism) 的材质思路。本项目的配色、布局和可读性规范见[界面设计规范](web/design/glassmorphism.md)。
