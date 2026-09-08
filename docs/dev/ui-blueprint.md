# 界面结构规范图

沟通界面时统一使用本页的区域名，避免「上面那个栏」「右边那块」这类歧义。
命名沿用代码既有约定（见 `ui_pyside6/views/industry_view.py` 的「5 区布局」），不另造一套。

![界面结构规范图](/assets/ui-blueprint.png)

> 图示为「工业制造」页（区域最完整的页面）。
> **虚线框 = 窗口级区域**（所有页面共有）；**实线框 = 页面级区域**（按页存在）。

## 窗口级区域

所有页面共有的窗口骨架，定义在 `ui_pyside6/main_window.py` + `main_window_nav.py`。

| # | 中文名 | 代码定位 | 说明 |
|---|---|---|---|
| 1 | 标题栏 | `MainWindow._title_bar` | 无边框自绘标题栏：标题文字 + 置顶/最小化/最大化/关闭 |
| 2 | 主工具栏 | `#main_toolbar` | 区域勾选、更新价格、价格时效、自动更新开关 |
| 3 | 左侧导航栏 | `#nav_panel` | 固定宽 160px，含导航树与底部按钮组 |
| 4 | 导航树 | `#nav_tree` | 页面入口列表（估价/物品查询/工业制造/…） |
| 5 | 导航底部按钮组 | `_hangar_settings_btn` 等三个按钮 | 机库设置 / 人物设置 / 系统设置 |
| 6 | 内容区 | `#content_stack` | `QStackedWidget`，承载所有页面 |
| 7 | 状态栏 | `MainWindow.status_bar` | 左侧状态文本 + 右侧进度条 |

## 页面级区域

页面**内部**的五个分区，是推荐结构；页面按需实现，不必五个都有。

| # | 中文名 | 代码定位（以 industry 页为例） | 说明 |
|---|---|---|---|
| 8 | 页面标题栏 | `_title_label` / `_plan_count` 所在行 | 页面名 + 计数等概要信息 |
| 9 | 页面工具栏 | `TopToolbar`（`_toolbar`） | 页面级操作与筛选，按「蓝图导入 / 价格来源 / 视图·筛选·刷新」三组换行 |
| 10 | 主工作区 | `_view_stack` | 页面主体内容，占据剩余空间 |
| 11 | 页面状态栏 | `StatusBar`（`_status_bar`） | 页面级汇总信息 |
| 12 | 页面功能按钮 | `ActionButtons`（`_action_buttons`） | 页面底部的批量操作入口 |

> 工业制造页五区高度（13px 字号下）：标题栏 28 + 工具栏 68 + 主工作区 725 + 状态栏 31 + 功能按钮 35 = 887，正好铺满页面。
> 字号变化时各区高度会随 `theme.fs()` 缩放。

## 各页面区域现状

| 页面 | 页面标题栏 | 页面工具栏 | 主工作区 | 页面状态栏 | 页面功能按钮 |
|---|:---:|:---:|:---:|:---:|:---:|
| 工业制造 `industry` | ✅ | ✅ `TopToolbar` | ✅ `_view_stack` | ✅ `StatusBar` | ✅ `ActionButtons` |
| 估价 `estimate` | — | 顶部输入区 | ✅ `QTableView` | 底部汇总栏 | — |
| 物品查询 `query` | — | ✅ `#query_toolbar` | ✅ `QTableView` | ✅ `#query_status` | — |
| 市场贸易 `trade` | — | — | ✅ `QTabWidget` | — | — |
| 价格监控 `watchlist` | — | — | ✅ `QTableView` | — | — |
| 合同市场 `contract` | — | — | ✅ `QTableView` | — | — |
| 仓库管理 `storage` | — | — | ✅ `QTabWidget` | — | — |

## 沟通约定

- **指位置**：用「区域名 + 相对位置」，例：`导航栏底部按钮组`、`页面工具栏右侧的视图切换`、`主工作区第三行`。
- **指控件**：优先给 `objectName`，例：`#batch_price_btn`、`#query_toolbar`。没有 `objectName` 的用「区域名 + 中文标签」，例：`页面功能按钮里的「采购小助手」`。
- **别再用**：「上面那个栏」「左边那块」「底栏」——这三句在本项目至少各指两个不同区域。

## 重新生成

```bash
python scripts/ui_blueprint.py                  # 默认工业制造页 → docs/public/assets/
python scripts/ui_blueprint.py --page query     # 换页面
python scripts/ui_blueprint.py --theme eve-deep # 换主题
```

新增或调整页面分区后，重跑本脚本并更新本文档的「各页面区域现状」表。
