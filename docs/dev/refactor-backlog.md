# 架构重构遗留项清单（Backlog）

> 状态：**#1 已完成**（#2–#4 未开始） · 关联：架构审计报告（`docs/dev/audit-report.md`）与已合入的 `refactor: 架构审计修复与分层收敛`
>
> 说明：本清单收录 4 项在上一轮重构中**刻意未做**的工作——其中 2 项属「纯风格、零功能收益」，2 项属「高风险大重构」。每项标注性质、现状位置、目标方案、风险、门禁与预计改动量，供后续分轮推进时按序领取。

---

## 总览

| # | 项目 | 性质 | 风险 | 预计量 |
|---|------|------|------|--------|
| 1 | `bom_expander` / `logistics` 的 DI 收敛 | 纯风格 | 低（测试 churn） | 小 |
| 2 | 评分算法纯度化 | 高风险 | **高**（缓存键/线程/金标准） | 中 |
| 3 | BOM 展开逻辑合并 | 复杂 | 中高（语义对齐） | 中 |
| 4 | 巨型 View 拆分 + 下载器统一 + 模型/delegate 分层 | 最大 | 中高 | 大 |

**建议顺序**：#1 已完成，下一步 2（价值最高、需独立一轮专注回归防护），最后 3 → 4。

---

## 1. `bom_expander` / `logistics` 的 DI 收敛（纯风格）✅ 已完成

**性质**：纯风格。`db = get_db()` 与 `get_container().db` 返回**同一单例**，功能零变化；唯一成本是测试 mock 语义迁移。

> **实际落地补充**：实施时发现 `core/container.py` 的 `bom_expander` / `logistics_service` 属性 import 了不存在的 `BomExpander` / `LogisticsService` 类，且 `TransportWorker._compute()` 经 `get_container().logistics_service.calc_transport_profit(...)` 调用——运行时会 `ImportError` 被 `BaseScoreWorker.run()` 吞成 `status: "error: ..."`（跨区域运输功能静默失效）。本次一并：删除两个坏属性 + `TransportWorker` 改为直接调模块级 `calc_transport_profit`。

### 现状位置

| 文件 | 位置 | 现状 |
|------|------|------|
| `services/bom_expander.py` | `:25-26` | `db = get_db()` + `_pricing = _PricingService(get_db())` |
| `services/logistics.py` | `:22-23` | `db = get_db()` + `_pricing = _PricingService(get_db())` |

### 测试耦合（转换的障碍所在）

| 测试文件 | 耦合点 |
|----------|--------|
| `tests/test_bom_expander.py` | `@patch("services.bom_expander.db")` ×4 + `@patch("services.bom_expander._pricing.get_price")` ×5 |
| `tests/test_logistics_cost.py` | `with patch("services.logistics.db")` ×9 + `@patch("services.logistics._pricing.get_price")` ×8 |

### 目标方案

```python
# bom_expander.py / logistics.py
from core.container import get_container

def _default_db():
    """惰性获取 DatabaseManager（经容器）。"""
    return get_container().db

def _default_pricing():
    """惰性获取 PricingService（经容器）。"""
    return get_container().pricing_service
```

调用点：
- `with db.connect(...)` → `with _default_db().connect(...)`
- `_pricing.get_price(...)` → `_default_pricing().get_price(...)`

### 测试迁移（关键，占全部工作量）

`db` 的 mock 语义变化：
```python
# before
@patch("services.bom_expander.db")
def test_x(self, mock_get_price, mock_db):
    mock_db.connect.return_value = mock_cm   # mock_db 是 DatabaseManager

# after（_default_db 是函数，mock 的是函数）
@patch("services.bom_expander._default_db")
def test_x(self, mock_get_price, mock_fn):
    mock_fn.return_value.connect.return_value = mock_cm
```

`_pricing` 的方法级 patch 更麻烦——需改为 patch 容器的 `pricing_service` 返回值：
```python
# before
@patch("services.bom_expander._pricing.get_price")

# after（pricing_service 由容器惰性返回）
@patch("core.container.get_container")
def test_x(self, mock_cont, ...):
    mock_cont.return_value.pricing_service.get_price = ...
```

### 风险 / 门禁 / 回滚

- **风险**：低（纯测试 churn，功能零变化）
- **门禁**：`ruff` + `mypy` + `test_bom_expander.py` + `test_logistics_cost.py` 全绿
- **回滚**：单文件独立 commit，出错 `git revert` 单文件
- **预计量**：2 源文件 + 2 测试文件，~26 处 mock 调整

---

## 2. 评分算法纯度化（高风险）

**性质**：高风险。这是「ScoringService 拆 3」的核心——把评分算法从 SQL/Qt/缓存中剥离成可脱离 SQLite 单测的纯函数。

### 现状位置

| 函数 | 位置 | 现状 |
|------|------|------|
| `ScoringService.calc_manufacturing_score` | `services/scoring_service.py`（~300 行） | 内嵌 `self._db.connect("ref","mkt","bp")` 查蓝图/材料/价格 |
| `ScoringService.calc_trade_score` | 同上 | 内嵌 `get_price`/`get_volume` + `ref` 库体积查询 |
| `ScoringService.calc_reaction_score` | 同上 | 内嵌蓝图/材料/价格查询 |

### 目标方案

抽 `domain/scoring.py` 纯函数，DB 访问经两个协议注入：

```python
# domain/ports.py
class PriceProvider(Protocol):
    def get_price(self, type_id, price_type, hub=None) -> float | None: ...
    def get_volume(self, type_id, vol_type="total", hub=None) -> int: ...
    def get_system_cost_index(self, system_id, activity, hub) -> float: ...
    def get_adjusted_price(self, type_id) -> float | None: ...

class BlueprintReader(Protocol):
    def materials(self, blueprint_type_id, activity="manufacturing") -> list[tuple[int,int,int]]: ...
    def product(self, product_type_id, activity="manufacturing") -> tuple[int,int,int] | None: ...
```

```python
# domain/scoring.py —— 纯函数，无 self/无 DB/无 Qt
def calc_manufacturing_score(
    *,
    blueprint: BlueprintRecipe,        # application 层已取好
    prices: PriceProvider,             # 协议注入
    char_config: dict,
    bp_me: int, bp_te: int,
    facility_tax_pct: float, is_alpha: bool,
    structure: StructureModifiers,
    system_id: int | None,
    cache_key: str | None,             # 缓存键由 application 传
) -> ScoreResult: ...
```

`application/scoring_facade.py` 负责：开连接 → 取 blueprint/materials/prices → 组装 `BlueprintRecipe` → 调纯函数 → 写缓存。

### 风险点（必须逐一防护）

1. **缓存键**：当前键含 `char_name` 但不含 `facility_tax_pct`/`is_alpha`/standing——上一轮已补 `facility_tax/is_alpha`，但 standing 仍缺失；纯度化后要确保键完整。
2. **线程**：评分在 `QThread` worker 里跑，`DatabaseManager` 线程隔离靠 `threading.local`；纯函数化后数据取用必须在同一线程完成，不能跨线程传连接。
3. **金标准数值**：制造公式由 `test_manufacturing_calculator_golden.py` 锁定；评分结果由 `test_scoring_service.py` 逐条断言。纯度化必须**先抓 baseline、再改、再逐字节对照**。
4. **状态码**：`no_blueprint`/`no_price`/`no_materials` 等早退语义要原样保留，避免 UI 依赖的状态判定失效。

### 门禁 / 回滚 / 预计量

- **门禁**：`test_manufacturing_calculator_golden.py` + `test_scoring_service.py` + `test_scoring_cache.py` 全绿，输出数值逐字节一致
- **回滚**：分两 commit（先抽 `calc_manufacturing_score`，再抽 trade/reaction），任一步可独立 revert
- **预计量**：1 新增 `domain/scoring.py` + 1 `application/scoring_facade.py` + `scoring_service.py` 瘦身

---

## 3. BOM 展开逻辑合并（复杂）

**性质**：复杂。两套递归 BOM 展开语义不同、输出形状不同，合并需先统一语义。

### 现状位置

| 实现 | 位置 | 输出 | 环处理 |
|------|------|------|--------|
| `bom_expander._expand` | `services/bom_expander.py:97-246` | `BomNode` 树（成本/层级，供「材料树」展示） | `seen` 命中当市场价叶子计价 |
| `plan_aggregator._expand` | `services/plan_aggregator.py:159-229` | 扁平 `materials` dict（总需求量，供「材料总表」） | `seen` 全局 + `depth` 封顶 |

### 目标方案

抽单一 `domain/bom.py` 遍历器，产出两种「投影」：

```python
# domain/bom.py
def walk_bom(
    blueprint_reader,          # 协议：按 product_type_id 取 blueprint/materials
    root_type_id, quantity,
    me_level, max_depth,
    on_leaf,                   # 叶子回调（两种视图共用）
    on_intermediate,           # 中间产品回调
) -> BomTraversalResult: ...
```

- `bom_expander.expand_bom` → 用 `walk_bom` 组装树视图
- `plan_aggregator.expand_material_requirements` → 用 `walk_bom` 组装扁平聚合视图

### 关键难点（需先统一语义）

1. **环检测不一致**：`bom_expander` 把真环当「市场价叶子」计价（会静默错价）；`plan_aggregator` 用 `seen`+`depth` 终止。合并后应统一为「标记环-无法计算」而非静默计价。
2. **`seen` 语义**：`bom_expander` 是路径集（`add`+`discard`，允许同层复用）；`plan_aggregator` 是全局集（共享子 BOM 的需求累加）。两者对「共享中间产品」的计数方式不同，需明确。
3. **ME/waste 口径**：两处 `calc_material_for_runs` 的 `wastefactor` 兜底（`_DEFAULT_WASTE=10` vs `10` 硬编码）需统一。

### 门禁 / 回滚 / 预计量

- **门禁**：`test_bom_expander.py` + `test_plan_aggregator.py` + `test_material_coverage.py` 全绿，先抓 baseline 再改
- **回滚**：分两步（先抽 `walk_bom` 只供 plan_aggregator 用，再迁 bom_expander），逐步切换
- **预计量**：1 新增 `domain/bom.py` + 两个调用方重构

---

## 4. 巨型 View 拆分 + 下载器统一 + 模型/delegate 分层（最大）

**性质**：最大。三件事可分轮独立推进。

### 4a. 巨型 View 拆分

**现状位置**（方法数）：`estimate_view`（49）、`hangar_tab`（53）、`contract_view`（50）、`all_items_view`（47）、`plan_table`（47）。

**目标**：拆「容器组件 + 行组件 + 对话框」，业务逻辑下沉 application 层。

**风险**：中高。逐 View 拆，每个 View 拆完跑该 View 冒烟测试（`test_ui_*`）。

### 4b. 下载器统一

**现状位置**：`services/workers/`（getprices/getindustry/getcontracts）vs `tools/downloaders/`（getitems/getblueprints/geticon/getimplantdata/getrigdata/sde_loader/sde_cache），两套风格（APIClient vs 裸 aiosqlite）。`services/init_service.py:433-443` 的 `entry_map` 硬编码跨两个包。

**目标**：统一到 `services/importers/`，下载器只负责「网络→落库」，进度/限流/重试策略共用。

**风险**：中。`sde_loader.py`（684 行）/`sde_cache.py`（479 行）自身偏大，可一并拆。

### 4c. 模型/delegate 分层

**现状位置**：`ui_pyside6/models/industry_models.py`（5 个 model，`PlanTableModel` 占 ~337 行）在 `data()` 里内联数字格式化 + `QColor` 染色 + 图标 `QPixmap` 加载。

**目标**：模型只暴露原始/已算数据；格式化+染色交给 `QStyledItemDelegate`；图标异步加载。

**风险**：中。需先确认 QTableWidget（29 文件）与 QTableView+Model（33 文件）的取舍，哪些大表需虚拟化/排序、哪些小表用 item widget 更简单（**待验证**）。

### 门禁 / 回滚 / 预计量

- **门禁**：`test_ui_main_window.py` + `test_ui_industry.py` + `test_theme_listeners.py` 冒烟全绿
- **回滚**：按 View/下载器逐文件 commit
- **预计量**：大（数十文件）

---

## 附：已完成、无需再做的清单（避免重复）

以下已在 `fc1eaa5` 及之前的修复轮落地，本 backlog 不再涉及：

- 评分缓存键补 `facility_tax/is_alpha`
- 合同明细删除顺序、取消返还扣减快照（schema v9→v10）、BOM 环防护
- `price_history_service` 断线、watchlist `updated_at` 脏串、SCI 兜底统一、single_instance 原子锁、版本号统一、settings 路径收敛
- UI 写操作下沉仓储（plan_table 11 处 + industry_view/production_wizard/mass_parallel/blueprint_import）
- production_plans DDL 单一来源、`plan_metrics.py` 纯算法抽取
- DI 收敛（4 模块：watchlist_manager / hangar_industry_config / scoring_service / inventory_manager）、core→UI 反向依赖清零、死代码删除（scoring.py shim、calc_refining_value）
- `bom_expander` / `logistics` DI 收敛（backlog #1）：移除模块级 `db`/`_pricing` 改惰性 `_default_db()`/`_default_pricing()`，删除容器坏属性 `bom_expander`/`logistics_service`，`TransportWorker` 改直调模块级 `calc_transport_profit`
