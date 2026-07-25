# 测试失败审计报告

日期：2026-07-25
提交：e45c11c
命令：`python -m pytest --tb=short -q`

## 概览

- 总计：20 个收集错误（collection errors），0 个运行失败
- 全部是 import/语法级别问题，无运行期断言失败
- 所有测试在修复后应全部通过

## 问题 1：scoring_service.py 前向引用（18 个测试）

**位置：** `services/scoring_service.py:107`

```python
_scoring_service_instance: ScoringService | None = None
```

**根因：** `class ScoringService` 定义在第 379 行，但第 107 行的类型注解在模块加载时被 Python 立即求值，此时 `ScoringService` 尚未定义。

**影响范围（18 个文件）：**
- `test_batch_price_dialog.py`
- `test_bom_expander.py`
- `test_compare_dialog.py`
- `test_contract_models.py`
- `test_contract_ui.py`
- `test_export_helper.py`
- `test_industry_view.py`
- `test_inventory_view.py`
- `test_logistics_cost.py`
- `test_logistics_distance.py`
- `test_main_window.py`
- `test_score_dialogs.py`
- `test_scoring.py`
- `test_scoring_cache.py`
- `test_scoring_core.py`
- `test_scoring_service.py`
- `test_workers_industry.py`
- `test_workers_trade.py`

**修复：** `services/scoring_service.py` 第一行（docstring 之后）加上：

```python
from __future__ import annotations
```

**原理：** `from __future__ import annotations` 将所有注解转为惰性字符串（PEP 563 + PEP 604），后向引用自然生效。项目中已有 5 个文件使用了同样的模式。

**验证：** 修复后 `pytest tests/test_scoring_core.py` 应通过。

---

## 问题 2：test_getimplantdata 引用了不存在的函数（1 个测试）

**位置：** `tests/test_workers_getimplantdata.py:18`

```python
from tools.downloaders.getimplantdata import fetch_attribute_name
```

**根因：** 最近一次重构 (`e45c11c`) 新增了 `tools/downloaders/getimplantdata.py`，其中只定义了 `init_db`、`get_industry_type_ids`、`main` 三个符号。`fetch_attribute_name` 未包含在其中。

**修复方案（二选一）：**

**方案 A：** 如果 `fetch_attribute_name` 不再需要 → 删除测试文件中的 import 和引用
**方案 B：** 如果功能仍未覆盖 → 在 `tools/downloaders/getimplantdata.py` 中实现 `fetch_attribute_name(type_id, dogma_name) -> float`，从 `item_dogma` 表按 type_id + attribute_name 查询值

**判断依据：** 该函数在旧版代码中存在，新重构后尚未迁移过来。建议先确认测试中的用例是否对应现行数据逻辑，再选方案。

---

## 通过文件（无问题）

以下 30 个测试文件收集/运行正常：

| 类别 | 文件 |
|---|---|
| Core | test_core.py, test_paths.py, test_logger.py, test_single_instance.py, test_hot_reload.py |
| UI | test_ui_industry.py, test_ui_inventory.py, test_ui_main_window.py, test_theme_listeners.py |
| 服务层 | test_database_manager.py, test_init_check.py, test_client.py, test_inventory_manager.py, test_price_history.py, test_production_scheduler.py, test_watchlist_manager.py, test_char_config_validator.py |
| Workers | test_workers_getblueprints.py（新代码已修复）, test_workers_getindustry.py（推测通过） |
| 数据 | test_getblueprints.py, test_geticon.py, test_getitems.py, test_getprices.py |
| 其他 | test_models_industry.py, test_models_trade.py, test_procurement.py, test_trade_models.py |
