# 母项拆解 / 子项并行 / 大规模并行 / 产线启动小助手 — 需求细化与实施状态

> 状态：**已实施**（2026-08-02），full 档 974 测试通过，ruff/mypy 全绿
> 关联：`docs/benchmark/t2-dealer-benchmark.md`（T2 对照）、`services/bom_expander.py`（递归 BOM）
> 图例：✅ 已实施 ｜ 📋 二期/待办

---

## 一、起点（改造前的真实状态）

| 功能 | 改造前 | 说明 |
|------|--------|------|
| 母项智能调整 `_smart_adjust_parent` | 只反推自身 runs，不拆解 | 已废弃 |
| 子项智能调整 `_smart_adjust_children` | **死代码**：`plan.get("group_id")` 恒为 None | 已废弃 |
| 大规模产线并行 `_smart_parallel_children` | **死代码**：同上 | 已废弃 |

**根因**：`production_plans` 真实列是 `group_number`/`sub_level`，但 UI/模型读 `group_id`/`child_level`，且**无代码写入这两列**；`bom_expander` 只算材料树不生成子项产线行。

---

## 二、已确认的决策（用户拍板）

1. **分解反应产物**：只拆组件（`activity='manufacturing'`）；反应物按外购叶子。
2. **拆解深度**：不设上限（完整递归到叶子）。
3. **库存扣减**：拆解时自动按材料机库库存减流程。
4. **大规模并行**：两种模式都做。
5. **产线上限**：软提示（超员警告，确认后放行）。
6. **子项 ME**：读库存蓝图最优等级；无蓝图 → 0-0 且标「无蓝图」。
7. **材料传播**：母项改为子项抵扣（组级材料用净需求到叶子）。
8. **未分配人物**：默认归当前人物。

---

## 三、实施状态清单

### 前置：人物技能 → 产线容量 ✅
- `services/char_capacity.py`：`max_production_lines`（1+高级量产技术）、`active_production_lines`（SUM parallels）、`active_lines_per_character`、`character_line_usage`。
- `tests/test_char_capacity.py`（8 用例）。

### 前置：group/sub_level key 映射 ✅
- `ui_pyside6/views/industry_view.py` `load_plans` 补 `group_id=group_number`、`child_level=sub_level`。
- 组号/子级列恢复显示，子项/大规模并行入口恢复可用。

### 产线启动小助手重设计 ✅
- `ui_pyside6/dialogs/production_wizard.py`（全重写）：
  - 顶部：按人物产线占用卡片（进度条 X/N，超员红「⚠超员」）。
  - 两列：左=全部产线（产品/子级/runs×parallels/状态），**点击蓝图名复制到剪贴板**；右=启动/状态区（备料足→绿色「▶ 启动」；缺料→灰字；运行中→剩余；待下线/已完成→文本）。
  - 软提示：超产线上限确认后放行；未分配人物默认当前人物；「应用到所选」「刷新备料」。
- `ui_pyside6/views/industry/action_buttons.py` 一级入口（与采购小助手并列）；`industry_view._on_launch_wizard` 传全部活跃计划。

### 母项调整 = 递归拆解 ✅
- `services/plan_decompose.py`：
  - `decompose_plan(plan, *, mat_hangar_id=None)`：只拆 manufacturing、无深度上限、按库存减流程、子项 ME/TE 读库存蓝图最优（无蓝图→0-0+has_blueprint=False）。
  - `best_inventory_blueprint`（BPO→ME 高者优先）、`parent_needs`（组内母项对直接组件总需求）。
- `ui_pyside6/views/industry/parent_decompose_dialog.py`：预览（组件/层/流程/ME-TE/无蓝图红字）→ 确认落库（母项 sub_level=0 同组，子项带 group_number/sub_level，同组同产品判重更新 runs）。
- `tests/test_plan_decompose.py`（8 用例）。

### 子项调整 = 并行配置弹窗 ✅
- `ui_pyside6/views/industry/child_parallel_dialog.py`：列出组内子项，每行母项需求/当前产出 + 可编辑并行数（QSpinBox）+ 每条流程（QSpinBox）；校验 `runs×parallels×单流程产出 ≥ 母项需求`，不足红字并禁用保存。
- `tests/test_industry_parallel.py`（校验拦截/放行）。

### 大规模产线并行 = 两模式 ✅
- `ui_pyside6/views/industry/mass_parallel_dialog.py`：
  - 模式1 按可用产线数：`compute_parallel_by_lines`（最大余数法按需求权重分线）。
  - 模式2 按目标工期：`compute_parallel_by_duration`（ceil(单线总时长/M天)）。
  - 预览表（调整后产出 vs 需求）+ 确认批量 UPDATE parallels。
- `tests/test_industry_parallel.py`（两模式纯函数）。

### 右键菜单接线 ✅
- `ui_pyside6/views/industry/plan_table.py` 智能调整子菜单改为三个新弹窗；删除旧 `_smart_adjust_*` 死代码。

---

## 四、二期 / 待办（📋）

1. **母项 material_cost 改为子项制造价合计**：当前母项成本仍按直接材料市场价算（组级填料/覆盖已用 `plan_aggregator` 净需求到叶子，但母项成本列未改为子项制造价）。
2. **子项完成后自动转移产品到母项材料机库**：当前靠子项 `deposit_hangar_id` + 逐级制造人工衔接；可做成自动（子项完成即写入母项材料机库）。
3. **备料校验懒加载**：产线启动小助手打开时对全部 pending 批量算备料（`check_materials` 会重算 scoring）；计划多时可改懒加载（选中行才算）。
4. **共享组件合并**：同一组件在 BOM 树多处出现时当前按最深 depth 建线；可进一步合并需求。

---

## 五、验证

- 新增测试：char_capacity（8）、plan_decompose（8）、并行/子项（8）、向导更新等，共 +26。
- `scripts/run_tests.sh quick` 870 passed / `full` **974 passed**；ruff + mypy 全绿。
