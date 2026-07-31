---
layout: home
hero:
  name: EVE 工业助手
  text: EVE Online 工业制造桌面应用
  tagline: 多区域价格查询 · 制造利润计算 · 物流规划 · 贸易评分，基于 PySide6 的开源工具
  actions:
    - theme: brand
      text: 快速开始
      link: /guide/quickstart
    - theme: alt
      text: 项目简介
      link: /guide/intro
    - theme: alt
      text: GitHub
      link: https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant
features:
  - icon: 🔍
    title: 物品查询
    details: 中英文模糊搜索、类别浏览、深层次订单、价格走势图、CSV/Excel 批量导出
  - icon: ⭐
    title: 工业制造
    details: 生产计划管理、蓝图搜索、材料/安装费/税费精确核算、甘特图、多汇总弹窗
  - icon: 📦
    title: 物流规划
    details: 需求 → 运输路线 → 利润评估，自动计算物流距离
  - icon: 📊
    title: 价格与评分
    details: 多区域价格对比、跨区贸易评分、关注列表价格变动检测
  - icon: 🎨
    title: 双主题
    details: One Dark Pro / One Light 主题，运行时一键切换并自动保存
  - icon: 🗄️
    title: 本地数据
    details: 4 库分离的 SQLite 架构，数据完全本地化，离线可用
---

::: tip 当前版本状态
项目处于 **0.x 开发阶段**：功能与 API 均可能随时变化。详见[版本管理说明](/dev/versioning)。
:::

## 快速链接

- [安装与启动](/guide/install) — 使用 uv 安装依赖、打包 EXE、首次启动初始化
- [界面总览](/user/overview) — 主窗口布局与各页面导航
- [工业制造](/user/industry) — 生产计划、利润计算、甘特图使用说明
- [API 参考](/dev/api-reference) — 函数级代码文档（自动生成）
- [更新日志](/guide/changelog) — 版本发布历史（自动同步 CHANGELOG）
