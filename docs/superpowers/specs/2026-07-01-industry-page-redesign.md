 # 工业制造页面重设计 - 完整实施计划
 > 参考截图: EVE Online 工业规划工具风格 (Pyfa/蓝图计算器)
 > 审计后更新: 2026-07-01
 
 ---
 
 ## 一、整体布局结构
 
 页面从上到下分为 5 个区域:
 
 ```
 ================================================================
   页面标题栏
   "生产规划" + 计划数量统计
 ----------------------------------------------------------------
   顶部工具栏
   [蓝图粘贴板输入框][添加] |  [预默认] |  [+ 从蓝图列表]
   [材料Hub][卖出/买入倍率][人物选择] |
   [筛选: 全部|待排|运行中|完成] [刷新]
 ----------------------------------------------------------------
   主表格 (生产计划表)
   20列可滚动/可排序/可筛选
   表头右键菜单 -> 显示/隐藏列
   支持行内编辑
 ----------------------------------------------------------------
   新增行区域
   [+ 从蓝图列表添加] 按钮
 ----------------------------------------------------------------
   底部状态栏
   计划总数: N | 运行中: N | 待排: N |
   采购总额: XXX ISK | 体积: XXX m3 | [保存价格]
 ----------------------------------------------------------------
   底部功能按钮
   [刷新材料表/采购助手] [蓝图表] [填料总表] [产出总表] [人物占用]
 ================================================================
 ```
 
 ---
 
 ## 二、顶部工具栏详细设计
 
 ### 2.1 左侧: 蓝图导入区
 
 | 控件 | 类型 | 说明 |
 |------|------|------|
 | 蓝图粘贴板输入框 | QLineEdit | placeholder="蓝图 粘贴板切导入", 用于粘贴游戏内复制的蓝图信息 |
 | 添加按钮 | QPushButton | 解析输入框内容或打开蓝图选择创建新计划 |
 | "+ 从蓝图列表"按钮 | QPushButton | 打开蓝图批量选择对话框, 支持链式添加(成品+组件+反应) |
 | 预默认/小部节接 | QPushButton | 针对选中行单独配置 ME/TE/技能等级, 阶段三实现 |
 
 ### 2.2 中间: 材料/价格设置区
 
 | 控件 | 类型 | 说明 |
 |------|------|------|
 | 材料Hub下拉 | QComboBox | 材料购买中心: Jita/Amarr/Dodixie/Rens/Hek |
 | 卖出价格倍率 | QDoubleSpinBox | 卖出价格调整 (默认1.00) |
 | 买入价格倍率 | QDoubleSpinBox | 买入价格调整 (默认1.00) |
 
 ### 2.3 右侧: 人物 + 筛选 + 操作区
 
 | 控件 | 类型 | 说明 |
 |------|------|------|
 | 人物选择下拉 | QComboBox | 从char_config.json读取所有角色名, 选中后该角色的技能用于利润计算. 选项格式: "main(技能全5)", "alt(技能全4)" 等, 并包含 "自定义" 选项 |
 | 状态筛选 | QComboBox | 全部/待排/运行中/已完成 |
 | 数据/甘特切换 | QRadioButton组 | 数据视图/甘特图, 阶段三实现, 阶段一仅占位 |
 | 子项自动调流程 | QCheckBox | 阶段三实现 |
 | 刷新按钮 | QPushButton | 刷新全部数据 |
 
 ### 2.4 "预默认/小部节接" 按钮行为 (针对单行)
 
 - **不是全局配置, 而是针对选中的生产行单独设置**
 - 点击弹出对话框: 设置该行的 ME/TE等级、设施位置、输出位置、技能等级
 - 阶段一: 按钮存在但点击时弹出 "功能开发中" 提示
 
 ---
 
 ## 三、主表格详细设计
 
 ### 3.1 表格列定义
 
 | # | 列名 | 数据源 | 宽度 | 排序 | 行内编辑 | 说明 |
 |---|------|--------|------|------|----------|------|
 | 0 | 图标 | data/caches/icons/{type_id}.png -> QPixmapCache | 32px | 否 | 否 | 32x32物品图标, 缓存缺失则留空 |
 | 1 | 产品 | product_name | auto | 是 | 否 | 产品名称 |
 | 2 | 批次 | runs | 60px | 是 | 是 | 制造批次 |
 | 3 | 并行 | parallels | 50px | 是 | 是 | 并行队列数 |
 | 4 | 组号 | group_number | 50px | 是 | 否 | 分组编号, 同一制造链的项目共享组号 |
 | 5 | 子级 | sub_level | 50px | 是 | 否 | 制造顺序: 0=成品, 1=成品组件, 2=组件的组件... 必须先完成子级大的再完成子级小的 |
 | 6 | 状态 | status | 80px | 是 | 否 | 待排/运行中/完成/未确认 |
 | 7 | 备注 | notes | 120px | 否 | 是 | 用户备注 |
 | 8 | 人物 | char_name | 100px | 是 | 是 | 生产角色 |
 | 9 | 流程 | "runs x parallels" | 60px | 否 | 否 | 显示 "1 x1" 格式 |
 | 10 | 蓝图 | "me-te[有/没图]" | 100px | 否 | 否 | 如 "10-20[有图]" |
 | 11 | 时长 | calculated_time(sec) | 80px | 是 | 否 | 格式 "HH:MM:SS" |
 | 12 | 产能 | daily_output | 80px | 是 | 否 | 该行单条产线一天的产量 (24h/时长*单次产量) |
 | 13 | 设施 | facility_name | 80px | 是 | 是 | 生产设施 |
 | 14 | 输出 | output_location | 80px | 是 | 是 | 输出位置 |
 | 15 | 成本 | material_cost | 110px | 是 | 否 | 材料总成本 ISK (带千分位) |
 | 16 | 利润 | profit | 110px | 是 | 否 | 利润 ISK (正绿负红) |
 | 17 | 市场利润率 | market_margin_pct | 80px | 是 | 否 | 材料和成品均取市场价计算, 组件分解到原材料 |
 | 18 | 个人利润率 | personal_margin_pct | 80px | 是 | 否 | 材料按库存成本+子项逐级成本传递计算 |
 | 19 | 操作列 | - | 120px | 否 | 否 | 启动/完成/删除按钮 |
 
 ### 3.2 组号与子级逻辑 (用户澄清)
 
 - 单个项目加入: 组号=0, 子级=0
 - 批量链式加入 (成品-组件-反应): 所有项目分配统一的组号
 - 子级代表制造顺序:
   - 子级0 = 成品
   - 子级1 = 成品的组件
   - 子级2 = 组件的组件
   - 必须先完成子级N再完成子级N-1: 要制造子级0需要先完成子级1, 要制造子级1需要先完成子级2...
 
 ### 3.3 利润率计算澄清
 
 **市场利润率 (market_margin_pct)**:
 - 材料取市场卖价 (sell_price)
 - 成品取市场卖价 (sell_price)
 - 组件分解: 递归展开BOM, 叶子节点取市场价, 中间产物按子材料求和
 - 公式: (成品市场价 - 全部材料市场价) / 全部材料市场价 * 100%
 
 **个人利润率 (personal_margin_pct)**:
 - 材料按库存成本价 (inventory_items.cost_price) 计算
 - 子项逐级成本传递: 子级1的制造成本传递为子级0的材料成本
 - 库存中没有的材料按市场价计算
 - 公式: (成品市场价 - 逐级累计成本) / 逐级累计成本 * 100%
 
 ### 3.4 表格交互
 
 - **单击行**: 选中并高亮
 - **双击行**: 打开该计划的详细编辑对话框 (阶段三实现)
 - **列头点击**: 排序 (升/降/取消)
 - **列头右键菜单**: 显示/隐藏列 (阶段一实现)
   - QMenu + QCheckBox 列表, 调用 `tableView.setColumnHidden()`
 - **行内编辑**: 阶段一支持 editable 列双击编辑
   - `flags()` 返回 `Qt.ItemIsEditable` 的列: 批次, 并行, 备注, 人物, 设施, 输出
   - `setData()` 更新模型内存 + 写数据库
 
 ### 3.5 右键菜单 (用户提供完整清单)
 
 选中行后右键弹出以下菜单项:
 
 | 菜单项 | 行为 | 实现阶段 |
 |--------|------|----------|
 | 修改流程数 | 弹出输入框修改 runs | 阶段一 |
 | 修改并行数 | 弹出输入框修改 parallels | 阶段一 |
 | --- 分隔线 --- | | |
 | 母项智能调整 | 自动调整父级项目的流程/并行数 | 阶段三 |
 | 子项智能调整 | 自动调整子级项目的流程/并行数 | 阶段三 |
 | 子项大规模产线并行 | 为所有子项启用最大并行配置 | 阶段三 |
 | --- 分隔线 --- | | |
 | 复制制造所需蓝图名称到剪切板 | 复制该行的蓝图名称到剪切板 | 阶段一 |
 | 查看原本图的NPC卖家 | 查询蓝图NPC售卖信息弹窗 | 阶段三 |
 | 查看核算 | 打开该行的利润/成本核算详情弹窗 | 阶段二 |
 | --- 分隔线 --- | | |
 | 更多修改 > | 子菜单 | 阶段三 |
 | 为设施设置所在星系 | 为该行设置设施所在星系的 system_id | 阶段三 |
 | 为设施所在星系设置成本系数 | 设置SCI成本系数 | 阶段三 |
 | --- 分隔线 --- | | |
 | 勾选备料 | 标记该行已备料 | 阶段一 |
 | 取消勾选备料 | 取消备料标记 | 阶段一 |
 | 项目启动 | status -> running | 阶段一 |
 | 项目完成 | status -> completed | 阶段一 |
 | --- 分隔线 --- | | |
 | 查看物品详情 | 打开物品详情弹窗 | 阶段二 |
 | 产线启动小助手 | 打开产线启动向导 | 阶段三 |
 | 删除行 | 删除该行计划 | 阶段一 |
 
 ### 3.6 图标列渲染 (审计后修正)
 
 **重要**: 禁止在 DecorationRole 中做文件I/O, 使用 QPixmapCache:
 
 ```python
 from PySide6.QtGui import QPixmapCache, QPixmap
 
 # 在 PlanTableModel.data() 中处理 DecorationRole:
 pixmap = QPixmapCache.find(f"icon_{type_id}")
 if not pixmap:
     icon_path = f"data/caches/icons/{type_id}.png"
     if os.path.exists(icon_path):
         pixmap = QPixmap(icon_path).scaled(32, 32, ...)
         QPixmapCache.insert(f"icon_{type_id}", pixmap)
     else:
         return None  # 无图标, 留空
 return pixmap
 ```
 
 geticon.py 是预下载工具, 不在表格渲染时调用.
 
 ### 3.7 筛选功能
 
 | 筛选项 | SQL 条件 |
 |--------|----------|
 | 全部 | (无筛选) |
 | 待排 | WHERE status IN ('pending') |
 | 运行中 | WHERE status IN ('running', 'in_progress') |
 | 已完成 | WHERE status IN ('completed', 'done') |
 
 ### 3.8 计划创建入口
 
 - 表格下方: "+ 从蓝图列表添加" 按钮
 - 点击打开蓝图选择对话框
 - 输入: type_id + runs + parallels + ME + TE + 角色
 - INSERT 到 production_plans, 然后 load_plans() 刷新
 
 ### 3.9 产能列计算
 
 产能 = 一条产线一天的产量
 - 公式: 24小时 / 单次制造时长(小时) * 单次产量
 - 例: 某产品每run 2小时产出3个, 则产能 = 24 / 2 * 3 = 36个/条线/天 (产能是单线产量, 不与并行数相乘)
 
 ---
 
 ## 四、底部状态栏详细设计
 
 ```
 计划总数: N | 运行中: N | 待排: N |
 采购总额: XXX,XXX.XX ISK | 体积(m3): XXX | [保存价格]
 ```
 
 | 字段 | 计算方式 | 更新时机 |
 |------|----------|----------|
 | 计划总数/运行中/待排 | 从 PlanTableModel._plans 内存计算 | load_plans 后 |
 | 采购总额 | 所有活跃计划的材料总成本 | 刷新材料后 |
 | 体积(m3) | 所有待采购材料的体积总和 | 刷新材料后 |
 | 保存价格按钮 | 保存当前价格到 price_snapshots 表 | 点击时 |
 
 ---
 
 ## 五、底部功能按钮 & 子面板
 
 ### 5.1 刷新材料表 / 采购小助手
 - 已有: procurement_tab.py ProcurementDialog
 - 改造: 集成到底部按钮, 对话框标题显示汇总金额
 
 ### 5.2 所需蓝图表
 - 新建: BlueprintRequirementsDialog
 - 数据源:
   1. 获取所有活跃计划
   2. 对每个计划的 product_type_id 调用 bom_expander.expand_bom() 递归展开
   3. 收集所有中间产物的 blueprint_type_id
   4. 汇总去重后与 user_blueprints 表对比
   5. 列出蓝图名/BPO或BPC/ME/TE/需求量/拥有量/状态
 
 | 列名 | 说明 |
 |------|------|
 | 蓝图名称 | 蓝图物品名 |
 | 类型 | BPO/BPC |
 | ME | 当前ME等级 |
 | TE | 当前TE等级 |
 | 所需数量 | 需要多少个蓝图 |
 | 已拥有 | 用户蓝图库中已有数量 |
 | 状态 | 齐全/缺少 |
 
 ### 5.3 填料总表
 - 新建: MaterialsSummaryDialog
 - 数据源: bom_expander.expand_bom() 递归展开 + 库存对比
 
 | 列名 | 说明 |
 |------|------|
 | 材料名称 | 物品名 |
 | 层级 | 0=原材料, 1=一级子组件... |
 | 所需数量 | 总需求量(含ME浪费) |
 | 库存数量 | 用户库存中已有量 |
 | 缺口 | 需要补充的数量 |
 | 单价 | 当前市场价 |
 | 总价 | 缺口 x 单价 |
 | 体积 | 缺口 x 单体积 |
 
 ### 5.4 产出总表
 - 新建: OutputSummaryDialog
 - 数据源: production_plans + scoring.calc_manufacturing_score()
 
 | 列名 | 说明 |
 |------|------|
 | 产品名称 | 物品名 |
 | 数量 | 总产出量 |
 | 成本 | 总材料成本 |
 | 售价 | 当前市场售价 |
 | 利润 | 售价-成本 |
 | 利润率 | 利润/成本 % |
 | 状态 | 待排/运行中/完成 |
 
 ### 5.5 人物占用
 - 新建: CharacterUsageDialog
 - 数据源: production_plans GROUP BY char_name + char_config.json
 
 | 列名 | 说明 |
 |------|------|
 | 角色名称 | 生产角色名 |
 | 活跃计划数 | 正在执行的计划数 |
 | 队列时长 | 该角色所有计划总时长 |
 | 技能等级 | 工业/高级工业等技能 |
 | 占用详情 | 展开显示具体计划 |
 
 ### 5.6 保存价格按钮
 
 - 表: price_snapshots (见第六章)
 - 逻辑: 将当前所有活跃计划涉及商品的 sell_price/buy_price 快照
 - 提示: "已保存 {N} 个价格快照于 {时间}"
 
 ---
 
 ## 六、数据库变更
 
 ### 6.1 production_plans 新增字段
 
 ```sql
 ALTER TABLE production_plans ADD COLUMN notes TEXT DEFAULT '';
 ALTER TABLE production_plans ADD COLUMN group_number INTEGER DEFAULT 0;
 ALTER TABLE production_plans ADD COLUMN sub_level INTEGER DEFAULT 0;
 ALTER TABLE production_plans ADD COLUMN facility TEXT DEFAULT '';
 ALTER TABLE production_plans ADD COLUMN output_location TEXT DEFAULT '';
 ALTER TABLE production_plans ADD COLUMN sell_hub TEXT DEFAULT 'Jita';
 ALTER TABLE production_plans ADD COLUMN market_margin REAL DEFAULT 0;
 ALTER TABLE production_plans ADD COLUMN personal_margin REAL DEFAULT 0;
 ALTER TABLE production_plans ADD COLUMN daily_output REAL DEFAULT 0;
 ALTER TABLE production_plans ADD COLUMN materials_ready INTEGER DEFAULT 0;
 ```
 
 ### 6.2 新建表
 
 ```sql
 CREATE TABLE IF NOT EXISTS price_snapshots (
     id INTEGER PRIMARY KEY AUTOINCREMENT,
     type_id INTEGER NOT NULL,
     region_id INTEGER NOT NULL,
     sell_price REAL,
     buy_price REAL,
     snapshot_time TEXT NOT NULL DEFAULT (datetime('now','localtime')),
     UNIQUE(type_id, region_id, snapshot_time)
 );
 ```
 
 ---
 
 ## 七、文件变更清单
 
 ### 7.1 修改的文件
 
 | 文件 | 变更 | 说明 |
 |------|------|------|
 | ui_pyside6/views/industry_view.py | 重写 | 页面总体编排 |
 | ui_pyside6/models/industry_models.py | 扩展 | PlanTableModel 20列 + QPixmapCache + 行内编辑 |
 | services/production_scheduler.py | 扩展 | 时间/利润/产能计算, save_prices() |
 
 ### 7.2 新建的文件
 
 | 文件 | 说明 |
 |------|------|
 | ui_pyside6/views/industry/__init__.py | 导出所有组件 |
 | ui_pyside6/views/industry/top_toolbar.py | 工具栏: 蓝图导入+Hub+价格倍率+人物选择+筛选+刷新 |
 | ui_pyside6/views/industry/plan_table.py | 主表格: 列定义/渲染/图标/右键菜单/行内编辑 |
 | ui_pyside6/views/industry/status_bar.py | 状态栏: 统计+保存价格 |
 | ui_pyside6/views/industry/action_buttons.py | 底部按钮组 |
 | ui_pyside6/views/industry/blueprint_dialog.py | 所需蓝图表 |
 | ui_pyside6/views/industry/materials_dialog.py | 填料总表 (BOM展开) |
 | ui_pyside6/views/industry/output_dialog.py | 产出总表 |
 | ui_pyside6/views/industry/char_usage_dialog.py | 人物占用 |
 
 ---
 
 ## 八、实施顺序
 
 ### 阶段一: 主框架+表格 (1200-1500行)
 
 1. 重构 industry_view.py 页面布局
 2. 扩展 PlanTableModel 到20列 + QPixmapCache图标
 3. 行内编辑: runs/parallels/notes/char_name/facility/output_location
 4. 列可见性控制
 5. 右键菜单: 修改流程数/并行数/复制蓝图名/勾选备料/启动/完成/删除
 6. 状态栏实时计算
 7. 工具栏: Hub选择/人物选择/筛选/刷新
 8. "+ 从蓝图列表添加" 按钮
 
 ### 阶段二: 子面板 (800-1000行)
 
 1. 采购小助手 (复用)
 2. 蓝图表 (BlueprintRequirementsDialog)
 3. 填料总表 (MaterialsSummaryDialog)
 4. 产出总表 (OutputSummaryDialog)
 5. 人物占用 (CharacterUsageDialog)
 6. 右键菜单: 查看核算/查看物品详情
 
 ### 阶段三: 高级功能 (500-700行)
 
 1. 蓝图粘贴板导入解析
 2. 预默认(单行配置对话框)
 3. 计划详情编辑对话框
 4. 甘特图视图
 5. 右键菜单: 母项/子项智能调整/大规模产线并行/NPC卖家/星系设置/SCI系数/产线启动小助手
 
 ---
 
 ## 九、数据流
 
 ```
 用户操作 -> 工具栏变更
     |
 load_plans()
     |
 每条计划:
   +-- blueprint_products -> 蓝图信息
   +-- blueprint_materials -> 材料清单
   +-- market_prices -> 成本/售价
   +-- user_blueprints -> 蓝图库存
   +-- inventory_items -> 材料库存 + cost_price
   +-- char_config -> 技能等级
   +-- calc_manufacturing_score() -> 时长/利润/利润率
     |
 PlanTableModel -> 表格渲染
     |
 状态栏统计更新
 ```
 
 ---
 
 ## 十、风险与注意事项
 
 1. 图标: QPixmapCache 内存缓存, 无IO阻塞
 2. BOM递归: bom_expander 已处理循环引用
 3. 配色: 全部从 ui_pyside6.theme 导入
 4. 暗/亮模式: 每个子面板 add_theme_listener + _on_theme_changed
 5. 编码: UTF-8, 中文注释
 6. Ruff: 提交前 ruff check . 通过
 
 ---
 
 ## 十一、行数预估
 
 | 阶段 | 行数 |
 |------|------|
 | 阶段一 | 1200-1500 |
 | 阶段二 | 800-1000 |
 | 阶段三 | 500-700 |
 | 总计 | 2500-3200 |



