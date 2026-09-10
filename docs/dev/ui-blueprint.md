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

## 产线启动小助手（独立工具窗）

`ui_pyside6/views/industry/production_launcher.py`。区域编号用 **L1–L4**，与上面的窗口级 1–7、页面级 8–12 区分开，避免歧义。

| # | 中文名 | 代码定位 | 说明 |
|---|---|---|---|
| L1 | 工具条 | `#launcher_toolbar`（`QFrame`） | 线型筛选 `#line_filter` + 人物筛选 `#char_filter` + 过滤指示 `#filter_summary` + 置顶 `#pin_btn`；固定单行 |
| L2 | 占用面板 | `#occ_header` + `#occ_scroll` | 标题行（折叠钮 `#occ_disc` + `#occ_title` + `#occ_summary`）+ 每角色一行 `CapacitySlotBar`；≤4 行不滚动，超出内部滚动 |
| L3 | 产线列表 | `#launcher_list` | 主工作区（`stretch=1`）；行卡片 `#plan_row` 内含 `#row_indent` / `#row_title` / `#status_badge` / `#row_meta` / `#row_duration` |
| L4 | 详情/执行面板 | `#launcher_bottom` | 未选中为紧凑态 `#bottom_hint`；选中后展开 `#detail_summary` + `#executor_combo` + `#btn_launch` + `#feedback`（无内容时不占位） |

L1 的 `#launcher_toolbar` **必须是 `QFrame`**（不能是裸布局），否则 QSS 的 id 选择器命中不到。

**`#line_filter` 按蓝图类别过滤，不是按产线容量线型**：选项为 全部 / 制造 / 复制 / 发明 / 反应，
名称取自 `services.terminology.term.activity()`（CCP 官方中文），data 存 `frozenset[str] | None`。
判据是 `services.plan_category.load_category_map` 推出的 `plan["category"]`，
**不能用 `char_capacity.capacity_line_for_category`** —— 那个映射把 copying/invention 合并成「科研」，
是为「技能决定的产线容量」（L2 占用面板）服务的，拿来当筛选项就会漏筛（历史缺陷：能制造+能复制的
普通蓝图全被判成 copying，制造计划漏进科研筛选）。
「发明」一项同时收纳 `invention` / `research_material` / `research_time`：后两类在本应用建不出计划
（`production_plans` 无 activity 字段，取数链路全写死 `manufacturing`），独立成项会恒空。

### 设计依据（改本窗前先读）

| 维度 | 取值 | 依据 |
|---|---|---|
| 间距 | `_GAP_XS/SM/MD/LG = 4/8/12/16` | Windows/Fluent：控件间距 8、控件↔标签 12、表面↔边缘 16 |
| 字号 | Caption 13 / Body 14，全部走 `theme.fs()` | Windows 11 类型梯度最小 12px regular；本窗为悬浮工具窗、常在放大窗口里用，取更舒适的一档 |
| 行高 | 列表行 68px、占用行 32px | 容得下 32px 图标 + Body/Caption 两行文字 + 8px 上下内边距 |
| 图标 | 32px | 多行列表项 32epx + Body/Caption 两级文字 |
| 披露层级 | 最多 2 层（列表 → 详情面板） | NN/g 渐进披露 |
| 对比度 | 文字 4.5:1、图形 3:1 | WCAG 1.4.3 / 1.4.11 |

### ⚠️ 层次陷阱：`BG_SURFACE` 比 `BG_DARK` **更暗**

两个模式的 token 关系都是 `BG_SURFACE` < `BG_DARK` < `BG_SURFACE_LIGHT` < `BG_HOVER`（亮度递增）。
`BG_SURFACE` 是**下沉面**，不是抬升面。全局 `QComboBox` 用 `BG_SURFACE` 做底，所以：

- **控件（下拉/按钮）必须用比背景更亮的面**（本窗用 `BG_HOVER`），否则在 `BG_DARK` 上渲染成
  「黑洞 + 亮边」，看起来像黑色内框。本窗在 `_launcher_qss()` 里显式覆盖了 `#line_filter` /
  `#char_filter` / `#executor_combo` / `#btn_row_ghost` 的背景。
- 悬浮/选中态用 `BG_SURFACE_LIGHT`；`#launcher_bottom` 作为下沉页脚用 `BG_SURFACE` 是对的。

### 字形可用性（踩过的坑）

段首是符号、后面紧跟中文时，Qt 会把整段解析到中文字体（`theme.FONT_FAMILY`）。
`Microsoft YaHei UI` **有** `◆ ○ ● ▲ ▼ ■ → · ×`，**没有** `▸ ▾ ▶ ✓ ⓘ 📌` —— 后者渲染成豆腐块（□）。

**即使用了存在的字形，符号来自不同字体、字号与中文也不匹配**（`▼ 折叠(1)` 里的 ▼ 明显比中文大一圈），
所以本窗的结论是：**正文里不用几何符号**——
状态徽章只放文字（语义由文字承担，左侧 3px 色条仅作辅助），折叠/展开用 `+` / `−`，
行首只用 `◆` 标父项，被阻塞用 `?`。新增符号前先实机确认字号协调。

**「缺料」是软阻塞**：材料不足但**没有**别的阻塞（无蓝图 / 等子项 / 机库未设置）时，
行上仍给「启动」按钮、详情面板给「强制启动」，点击后弹确认
（与计划表格同口径，见 `services.plan_start_check.can_force_start`）。
只有缺料时用 `?` 会让用户以为彻底不能启动，而实际上「扣现有库存、缺口记待补」是允许的。
判定用到的材料缺口**每轮轮询都要重算**（库存不进计划字段，只缓存计划字段会让补齐材料后永远显示旧值）。

同类问题还有**行图标回退**：`services.plan_category.category_symbol()` 返回 emoji（`⚙ 📋 ⚗ 💡`），
在无图标行会渲染成空白/豆腐块。本窗改用**类别首字**（制/科/反）作占位（`#row_icon`）。

**补充实测（计划表格 ME/TE 列的 `≠` 标记）**：用 `QRawFont.supportsCharacter` 核过
`Microsoft YaHei UI`（`theme.FONT_FAMILY`）——`≠ U+2260` / `× U+00D7` / `✔ U+2714` / `✓ U+2713`
**均有字形**，`≠` 可直接用在计划表格里，无需退回 ASCII。上方「没有 ▸ ▾ ▶ ✓ ⓘ 📌」的结论
是**本窗字体环境**下的观察，与计划表格（默认字体、非本窗 QSS）不是同一场景，勿直接外推。

### 占用条几何

- 每类产线的格子区宽度**按该类容量占全部容量的比例**分配；`line_caps`（各线型的最大容量）
  由 `ProductionLauncher` 按全部人物算一次后传给每个 `CapacitySlotBar` —— 各行格子区仍纵向对齐，
  且「制造 11 格 / 科研 1 格」不会在一行里留下十几个空档。
- 只画该人物**容量内**的格子（格子数即容量）；占用格 accent 渐变，空容量格 `BG_HOVER`，
  超出技能容量的不绘制。
- ⚠️ 可用宽度预算必须扣掉三项线型**标签宽度**（`label_w`）与组间留白，否则格子会画到右侧状态徽章底下。
  旧实现漏了 `label_w`，只是被 `_MAX_BLOCK_W = 12` 的上限掩盖住了。

### 配色不变量（有测试兜底，勿绕过）

- `production_launcher._CONTRAST_CONTRACT` 声明本窗所有「文字/背景」对，`tests/test_theme_registry.py` 遍历全部主题断言 —— 新增主题会被自动检查。
- 自绘图形（占用方块、状态色条）一律经 `ensure_contrast()` 调到 ≥3:1 再使用：强调色是中间调，浅色主题下直接用不达标（实测 one-light 的绿仅 2.87）。
- **禁止用 accent 作文字色**；小字（≤13px）禁用 `TEXT_SECONDARY`（在 `BG_HOVER` 上 0/10 主题达标）。

## 沟通约定

- **指位置**：用「区域名 + 相对位置」，例：`导航栏底部按钮组`、`页面工具栏右侧的视图切换`、`主工作区第三行`。
- **指控件**：优先给 `objectName`，例：`#batch_price_btn`、`#query_toolbar`。没有 `objectName` 的用「区域名 + 中文标签」，例：`页面功能按钮里的「采购小助手」`。
- **别再用**：「上面那个栏」「左边那块」「底栏」——这三句在本项目至少各指两个不同区域。

## 重新生成

```bash
python scripts/ui_blueprint.py                  # 默认工业制造页 → docs/public/assets/
python scripts/ui_blueprint.py --page query     # 换页面
python scripts/ui_blueprint.py --theme eve-deep # 换主题
python scripts/ui_snapshot.py --dialog launcher # 产线启动小助手（PNG + 控件树）
```

新增或调整页面分区后，重跑本脚本并更新本文档的「各页面区域现状」表。
改动产线启动小助手时，用 `ui_snapshot.py --dialog launcher` 出前后对比截图（明暗主题各跑一次）。
