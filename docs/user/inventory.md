# 库存管理

库存管理提供机库定义、物品 CRUD、蓝图管理和加权平均成本计算。

## 数据模型

库存数据存储在 `user.db` 中（`services/inventory_manager.py`）：

### 机库（hangars）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK | 自增主键 |
| `name` | TEXT UNIQUE | 机库名称 |
| `notes` | TEXT | 备注 |

**默认机库**：矿仓、组件仓、产品仓、通用仓库

### 库存物品（inventory_items）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK | 自增主键 |
| `hangar_id` | INTEGER FK | 所属机库 |
| `type_id` | INTEGER | 物品 ID |
| `quantity` | INTEGER | 数量 |
| `cost_price` | REAL | 加权平均成本价 |
| `created_at` | TEXT | 入库时间 |

唯一索引：`(hangar_id, type_id)` — 同一机库同物品只有一条记录。

### 蓝图（user_blueprints）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK | 自增主键 |
| `hangar_id` | INTEGER FK | 所属机库 |
| `blueprint_type_id` | INTEGER | 蓝图物品 ID |
| `is_bpo` | INTEGER | 1=BPO（原件），0=BPC（拷贝件） |
| `me_level` | INTEGER | 材料效率等级（0-10） |
| `te_level` | INTEGER | 技术效率等级（0-20） |
| `runs` | INTEGER | 剩余可运行次数（BPC） |
| `quantity` | INTEGER | 数量 |
| `notes` | TEXT | 备注 |

## 加权平均成本

当多次入库同一物品时，成本按加权平均计算：

```
新均价 = (旧数量 × 旧均价 + 新数量 × 新单价) / (旧数量 + 新数量)
```

这个成本用于制造计划的「个人利润率」计算，确保利润评估反映你的实际持有成本。

## 库存界面

`ui_pyside6/views/inventory/` 包含：

| 文件 | 功能 |
|------|------|
| `inventory_page.py` | 主页面 Tab 容器 |
| `hangar_tab.py` | 单个机库的物品表格 Tab |
| `blueprint_tab.py` | 蓝图管理 Tab（BPO/BPC、ME/TE） |
| `blueprint_import_worker.py` | 蓝图批量导入 Worker |
| `inventory_helpers.py` | 辅助函数 |
| `review_dialog.py` | 入库审核对话框 |

## API 参考

详见 [`services/inventory_manager.py`](/api/services/inventory_manager)。
