# 界面结构规范图

沟通界面时统一使用本页的区域名，避免「上面那个栏」「右边那块」这类歧义。
命名沿用代码既有约定（见 `ui_qml/views/industry_view.py` 的「5 区布局」），不另造一套。

![界面结构规范图](/assets/ui-blueprint.png)

> 图示为「工业制造」页（区域最完整的页面）。
> **虚线框 = 窗口级区域**（所有页面共有）；**实线框 = 页面级区域**（按页存在）。

## 窗口级区域

所有页面共有的窗口骨架。原 Widgets 外壳（`ui_pyside6/main_window.py` + `main_window_nav.py`）已随 QML 迁移删除，现由 `ui_qml/shell_window.py`（QQuickView 主窗口）+ `ui_qml/qml/shell/` 实现；下表的区域名沿用，`代码定位` 列记录的是 Widgets 时代的标识。

| # | 中文名 | 代码定位 | 说明 |
|---|---|---|---|
| 1 | 标题栏 | `MainWindow._title_bar` | 无边框自绘标题栏：标题文字 + 置顶/最小化/最大化/关闭。文字左内边距由 `Main.qml` 的 `chromeInset` 传入，与下面几行对齐成一条竖线 |
| 2 | 主工具栏 | `#main_toolbar` | **左侧一组「状态与上下文」**：区域勾选 → 价格时效 → 自动更新开关（后两者说的是同一件事，必须相邻）；**右侧唯一动作**：更新价格 |
| 3 | 左侧导航栏 | `#nav_panel` | 固定宽 160px，自顶向下：logo → 导航树 → 底部按钮组 |
| 4 | 导航树 | `#nav_tree` | 页面入口列表（物品查询/估价/工业制造/…，顺序即 `NAV_TREE`；**无分组标题**）。图标**各有配色**，见下 |
| 5 | 导航底部按钮组 | `_hangar_settings_btn` 等三个按钮 | 机库 / 人物 / 系统，**图标在上文字在下、整组水平居中** |
| 6 | 内容区 | `#content_stack` | `QStackedWidget`，承载所有页面 |
| 7 | 状态栏 | `MainWindow.status_bar` | 左侧状态文本 + 右侧进度条 |

**导航图标的配色**：颜色写在 `NAV_TREE` 的第 4 列，但存的是**主题 token 名**（`"ACCENT_YELLOW"` 这种），
不是色值 —— 那样这份常量表就不必依赖 Qt/主题。外壳桥的 `navIconColor()` 把它解析成当前主题的实际颜色，
并且**必过 `domain.theme_contrast.ensure_contrast`**：浅色主题的琥珀 `#ffb300` 对白底只有 1.79:1，
低于 WCAG 1.4.11 对图形要求的 3:1，不压暗会糊成一片。选中态**不再改图标颜色** ——
选中由行底色与文字色表达，图标保持各自的彩色。

**导航栏顶部的 logo**，不是文字：标题栏已经写着「EVE 商人助手」，侧栏再写一遍是重复。
两张资产 `ui_qml/assets/logo_dark.png` / `logo_light.png`（透明底，深/浅主题各一张，红点沿用设计稿自己的红）
由 `scripts/make_app_icon.py` 生成；路径由外壳桥的 `logoSource` 以 `file://` 发出 ——
**QML 不拼文件路径**，`ui_qml/qml/shell/` 下写 `Qt.resolvedUrl("../assets/…")` 会解析到不存在的
`ui_qml/qml/assets/`，表现为静默空白。logo **水平居中**（160px 的独立面板，贴左会往内容区挤）。

**左对齐竖线**：`chromeInset`（= `Theme.spacingMd`，12px）是标题栏文字、主工具栏左侧控件组、
导航行图标列共用的左内边距。改动其中一处要一并改，否则会出现「上面的字和下面的字错开一格」。
**logo 不在这条线上**（它居中）。

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
| 物品查询 `query` | — | ✅ `#query_toolbar` | ✅ 两态：仪表盘 / 结果表 + 详情面板 | ✅ `#query_status` | — |
| 市场贸易 `trade` | — | ✅ `#tradeToolbar` | ✅ 排行表 + `#rankEmpty` 空态 | ✅ `#statusText` + `#cartSummary` | ✅ `#cartButton` |
| 价格监控 `watchlist` | — | — | ✅ `QTableView` | — | — |
| 合同市场 `contract` | — | ✅ 页面工具栏 | ✅ `FTabBar` + 三个页签 | ✅ 状态条 | — |
| 仓库管理 `storage` | — | — | ✅ `QTabWidget` | — | — |

> **合同市场页有三个子页签**（拍卖 / 物品交换 / 运输），由 `ContractPage.qml` 的
> `FTabBar` + `StackLayout` 承载，三个页签主体共用 `ContractTabPane.qml`。
> 三类合同的判定口径不同，所以拆开而不是一张表加类型筛选：拍卖比一口价、物品交换比
> 内容物市价（含蓝图时还要算制造利润）、运输比每方每跳 ISK。
> **页面工具栏**是「星域（下拉 + 按名字自动补全）+ 拉取合同 + 补齐物品 + 停止」，
> 状态条显示拉取/补齐的进度与结果（不再有静默失败）。
>
> ⚠️ 本页是唯一**在 `Component.onCompleted` 里查库**的页面（旧版没有任何初次加载入口，
> 第一次打开永远是空表且不报错）。查库是**同步**的（实测最重一档 3000 行 49 ms）——
> 异步结果回来时视图可能正在销毁，实测会让 ui 档后续用例 `access violation`。
> 需要开线程的只有打 ESI 的「拉取列表」与「补齐物品」。

> 启动时的默认着陆页 = **导航首项**（界面改版第 1 步后是「物品查询」，此前是「估价」）。
> 取法见 `ui_qml/shell_window.py` 装配尾部，**不硬编码任何页面 key** —— 换序即换默认页。

### 物品查询页的两态（界面改版第 2/3 步）

主工作区有**两个互斥的态**，判据是**有没有选中物品**（`detail.typeId > 0`）：

| 态 | 区域名 | 代码定位 | 内容 |
|---|---|---|---|
| 空闲态 | 仪表盘 | `#queryDashboard` | 三栏：产线详情（`OccupancyPanel`，**每人物一块、块内制造/科研/反应三行**，行尾给「待下线 N」，**该列恒定预留宽度**，条子分母取该线型各人物上限的最大值）/ 资产折线图（`AssetChartPanel`，5 条线 + 右上角「刷新」`#assetRefreshButton`；涨跌基准取档位起点**之前**最近一条快照）/ 挂单列表（`OpenOrdersPanel`，**卖单 `#sellOrdersTable` 在上、买单 `#buyOrdersTable` 在下两张表** + `#readOrdersButton`；钱包余额 `#walletField`） |
| 详情态 | 详情面板 | `#queryDetailPane` | 四块 2×2，**铺满整个工作区**（原先上半屏是结果表，已删） |

> **这一页没有结果表格**（用户明确要求）：候选弹窗 `#suggestPopup` **就是**匹配清单 ——
> 输入即列全部前缀匹配（条数不限、自带滚动），点一条直接进详情态。
> 随之删除的还有：工具栏的「搜索」按钮、右键菜单（`#rowMenu`）与那套复制动作，
> 以及 `ui_qml/models/query_model(s).py`。唯一保住的功能是「查看制造配方」，
> 改挂工具栏按钮 `#recipeButton`（没选中物品时不可点）。
>
> 仪表盘上原先那块「快捷操作（可启动 / 可下线）」列表**已删除**（用户要求：既占地方又没用）——
> 启动 / 下线在**生产计划表**与**产线启动小助手**里都有。
> 挂单面板原有的「导出目录」输入框也一并删除：目录**固定**为游戏默认目录。

详情面板是 2×2：左上「5 个默认贸易中心的价格」、右上「订单列表」、
左下「精炼产物、价格」（顶部有**人物 / 数量 / 站点**三个输入，产率按该人物的提炼技能算）、
右下「制造所需的材料」。

> **两态判据要用桥上的 Property**（`detail.typeId`，`notify=changed`），QML 绑定才追得到；
> 写成 Slot 调用（如原先的 `model.rowCount()`）绑定不会刷新，界面会一直停在仪表盘 ——
> 不报错，只是不动。判据里**不能带 `busy`**：那是「按候选查明细」的中间态，
> 掺进来会让界面来回翻两次。

> **面板容器用 `FPanel` 而不是 `FSection`。** `FSection` 把子项收进内层 `ColumnLayout`，
> 在里面写 `anchors.fill: parent` 会被布局**静默忽略**，整块内容塌成自己的
> `implicitHeight`（实测：整张表只剩表头一条线，看着像「没数据」）。
> `FPanel` 与 `FSection` 外观相同，但子项收进普通 `Item`，可以锚点。
> 判断标准：面板里放**一整块自己管布局的内容**（表格 / 图表 / 占用条）用 `FPanel`；
> 放若干行依次排列的控件用 `FSection`。

> **资产折线图的颜色由 Python 侧算好、随 `assetPlot.series[].color` 下发**，
> 且过 `ensure_contrast`。QML 不直接读 `Theme` 取折线色 —— `PriceChartDialog.qml`
> 那样直接读 `Theme.primary/accentOrange` 是**没做对比度保障**的，不要照抄那个缺陷。

## 产线启动小助手（独立工具窗）

`ui_qml/views/industry/production_launcher.py`（控制器）+ `ui_qml/qml/pages/LauncherWindow.qml`（**整窗 QML**，批次 7.4 起）。
区域编号用 **L1–L4**，与上面的窗口级 1–7、页面级 8–12 区分开，避免歧义。
下面「代码定位」给的是**当前 QML 的 `objectName`**（老文档里的 `#launcher_toolbar` 那套是 Widgets 版遗留，已随该版本删除）。

| # | 中文名 | 代码定位（QML `objectName`） | 说明 |
|---|---|---|---|
| L1 | 工具条 | `toolbar` | 蓝图类别筛选 + 人物筛选两个下拉 + 过滤摘要 + 置顶；固定单行 |
| L2 | 占用面板 | `occPanel`（标题行是 QML id `occHeader`，无 objectName） | 标题行（折叠钮 + 标题 + 摘要）+ 每角色一行 `FCapacityRow`；≤4 行不滚动，超出内部滚动 |
| L3 | 产线列表 | `listArea` | 主工作区；行卡片内容行是 `rowCardRow`（图标 / 名称+徽章+副标题 / 时长+动作槽），点击区 `launcherClickArea`，右键菜单 `rowMenu` |
| L4 | 详情/执行面板 | `bottomPanel` | 未选中为紧凑提示；选中后展开参数摘要 + 执行人下拉 + 主按钮 + 反馈 |

**窗口宽度**：`width` 默认 520、`minimumWidth` 430（两个都 × `Theme.fontScale`）。取的是**实测的内容最小宽**，
不是「好看」的宽 —— 这窗常与游戏同屏（L1 有「置顶」），宽了就挡游戏。下限由 L2 的容量方块行定（≈420），
L1 只需 ≈350；默认 520 是「行卡片的名称 / 副标题还读得全」的折中。改尺寸相关值（方块、下拉宽、字号）后跑
`tests/test_production_launcher.py::test_narrowest_window_clips_nothing`（按渲染几何兜「控件被裁」）。

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
| 行高 | 列表行 58px、占用行 26px | 列表行的真正下限是右侧「时长 + 26px 动作按钮」那一列（13+4+26=43），加 4×2 内边距 = 51；占用行只需容下 32px 图标与两行文字 |
| 图标 | 32px | 多行列表项 32epx + Body/Caption 两级文字 |
| 披露层级 | 最多 2 层（列表 → 详情面板） | NN/g 渐进披露 |
| 对比度 | 文字 4.5:1、图形 3:1 | WCAG 1.4.3 / 1.4.11 |

### ⚠️ 层次陷阱：控件面不能和它所在的底同层

**两套主题的层次次序不一样**（由暗到亮）：

| 主题 | 次序 |
|---|---|
| `fluent-dark` | `BG_DARK` < `BG_SURFACE` < `BG_SURFACE_LIGHT` < `BG_HOVER` |
| `fluent-light` | `BG_HOVER` < `BG_SURFACE_LIGHT` < `BG_DARK` < `BG_SURFACE` |

深色是「越抬升越亮」（Fluent 深色惯例）；浅色里只有卡片比窗口底亮，控件与悬浮靠**变暗**区分。

> 本节原先写「两个模式都是 `BG_SURFACE` < `BG_DARK` < `BG_SURFACE_LIGHT` < `BG_HOVER`，
> 且 `BG_SURFACE` 是下沉面」——主题收敛到 Fluent 双主题后已不成立：实测 `BG_SURFACE`
> 在两套里都是**抬升的卡片面**（深色 `#1e293b` 比窗口底 `#0f172a` 亮，浅色 `#ffffff` 比
> `#f2f4fb` 亮）。说明与实现脱节了一段时间，2026-09 修正。

不变量由 `tests/test_theme_registry.py::test_surface_luminance_order_is_strictly_increasing`
逐主题守着（按 `BG_DARK` 的亮度选上表对应的那一串，断言严格递增），另加一条
「`BG_SURFACE` 与 `BG_DARK` 必须可区分」——两者几乎同色时卡片与窗口底会糊成一块。

实践含义：

- **控件（下拉/按钮）不要直接用 `BG_SURFACE` 做底**。深色下它紧贴窗口底，会渲染成
  「黑洞 + 亮边」的黑色内框；浅色下它又最亮，控件看起来像浮出来的白块。控件底用
  `BG_HOVER` 或 `BG_SURFACE_LIGHT`。
- 悬浮/选中态用 `BG_SURFACE_LIGHT`；卡片与下沉页脚用 `BG_SURFACE`。

### 字形可用性（踩过的坑）

段首是符号、后面紧跟中文时，Qt 会把整段解析到中文字体（`theme.FONT_FAMILY`）。
`Microsoft YaHei UI` **有** `◆ ○ ● ▲ ▼ ■ → · ×`，**没有** `▸ ▾ ▶ ✓ ⓘ 📌` —— 后者渲染成豆腐块（□）。

**即使用了存在的字形，符号来自不同字体、字号与中文也不匹配**（`▼ 折叠(1)` 里的 ▼ 明显比中文大一圈），
所以本窗的结论是：**正文里不用几何符号**——
状态徽章只放文字（语义由文字承担，左侧 3px 色条仅作辅助），折叠/展开用 `+` / `−`，
行首只用 `◆` 标父项，动作槽位也不放占位符号。新增符号前先实机确认字号协调。

**动作槽位显示真实状态，不用 `?` 占位**（历史：兜底分支把「待下线 / 生产中 / 硬阻塞」
统统渲染成 `?`，真实原因只躺在 tooltip 里，界面上什么也读不到）。五态互斥：

| 状态 | 动作槽 |
|---|---|
| 母项有未完成子项（`child_level==0`） | `折叠(N)` / `展开(N)` |
| 待下线（`ready`） | **`可下线`** —— 点击走单行下线（选产出机库） |
| 可启动 | `启动` |
| 缺料 / 蓝图流程不足（**唯一**阻塞） | 按钮文字即短标签（`材料不够` / `缺蓝图`），**仍可点**，点击后二次确认 |
| 其它阻塞、生产中 | 短标签（`材料不够` / `缺蓝图` / `等子项` / `子项运行中` / `生产中`），完整原因进 tooltip |

短标签由 `plan_start_block` 的类别码映射（`_BLOCK_SHORT_LABELS`），**UI 不解析中文文案**；
`plan_start_block_reason` 仍是同一次判定的文案投影（返回值被测试冻结）。
槽宽按**按钮自身字体**下的最长文案取值并固定（QSS 给 `#btn_row` 与 `#btn_row_ghost` 设了
不同字号，用控件字体量会偏小、最长标签会被截断），避免行动作区左右跳动。
合成根行（共享组件，`id=None`）不属于任何可操作状态，动作槽留空。

**「缺料」是软阻塞**：材料不足但**没有**别的阻塞（无蓝图 / 等子项 / 机库未设置）时，
行上仍给可点的按钮（文字就是「材料不够」）、详情面板给「强制启动」，点击后弹确认
（与计划表格同口径，见 `services.plan_start_check.can_force_start`）。
把缺料直接显示成不可点的状态，会让用户以为彻底不能启动，而实际上
「扣现有库存、缺口记待补」是允许的。判定用到的材料缺口**每轮轮询都要重算**
（库存不进计划字段，只缓存计划字段会让补齐材料后永远显示旧值）。

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
- ⚠️ 可用宽度预算必须扣掉三项线型**标签宽度**（`labelW`）与组间留白，否则格子会画到右侧状态徽章底下。
- ⚠️ 第 i 组的起点 x 必须**累加前面各组**的「标签 + 那组全部方块」（`FCapacityRow.groupX`）。
  写成 `index × lines[index].cap × effStride` 是拿**本组**的 cap 当累计量 —— 三类容量不同
  （制造 / 科研 / 反应），每组都被摆到偏左的 x 上：方块压到标签、整体与右侧徽章脱节。
  运行期只有「看着错位」，不报任何错，所以补了一条静态护栏
  （`tests/test_production_launcher.py::test_capacity_group_x_accumulates_previous_groups`）。

### 配色不变量（有测试兜底，勿绕过）

- `domain/theme_contrast.py::CONTRAST_CONTRACT` 声明本窗所有「文字/背景」对，`tests/test_theme_registry.py` 遍历全部主题断言 —— 新增主题会被自动检查。（契约原在 `production_launcher.py`，随该模块失去渲染职责一并上移到 `domain/`，不再依赖 Qt。）
- 自绘图形（占用方块、状态色条）一律经 `ensure_contrast()` 调到 ≥3:1 再使用：强调色是中间调，浅色主题下直接用不达标（实测 one-light 的绿仅 2.87）。
- **禁止用 accent 作文字色**；小字（≤13px）禁用 `TEXT_SECONDARY`（在 `BG_HOVER` 上 0/10 主题达标）。

## 沟通约定

- **指位置**：用「区域名 + 相对位置」，例：`导航栏底部按钮组`、`页面工具栏右侧的视图切换`、`主工作区第三行`。
- **指控件**：优先给 `objectName`，例：`#batch_price_btn`、`#query_toolbar`。没有 `objectName` 的用「区域名 + 中文标签」，例：`页面功能按钮里的「采购小助手」`。
- **别再用**：「上面那个栏」「左边那块」「底栏」——这三句在本项目至少各指两个不同区域。

## 重新生成

> 生成器 `scripts/ui_blueprint.py` 与 Widgets 截图脚本 `scripts/ui_snapshot.py` 已随 QML 迁移删除
> （两者都写在已移除的 Widgets 外壳上）。本页的标注图 `/assets/ui-blueprint.png` 现为**静态参考图**，
> 不再由脚本生成。
>
> ⚠️ 该图绘于 Widgets 时代，**没有反映界面改版第 1 步**（导航去分组标题并换序、侧栏顶部换成 logo
> 且居中、导航图标各有配色、主工具栏重新分组、导航底部按钮组加文字并居中）。窗口级区域
> **编号与名字**仍然有效，观感请看下面的快照脚本。

当前界面截图请用 QML 外壳快照脚本：

```bash
python scripts/shell_snapshot.py                 # QML 外壳（离屏，验结构/配色）
python scripts/shell_snapshot.py --real          # QML 外壳（真窗口，验字形/毛玻璃）
python scripts/shell_snapshot.py --page industry # 切到某页再拍
```

新增或调整页面分区后，更新本文档的「各页面区域现状」表。
