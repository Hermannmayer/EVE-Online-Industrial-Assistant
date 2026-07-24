# 制造公式审计报告

对照 EVE University Wiki（Manufacturing 页，末次修订 2026-07-24，Viridian 税改后公式）+ fuzzwork industry.py（生产环境参考实现）+ Reddit（2023 年公式讨论）。

> **版本确认**：材料浪费公式未随 Viridian（2023）改动，仍为经典 `wasteFactor/100 / (1+ME)` 曲线。安装费结构在 Viridian 改为加法（SCI×SB + FT + SCC + AT），SCC 4% 是那次引入的。以下对比均面向当前游戏版本。

---

## 目录

- [A] 材料浪费公式线性化
- [B] 未区分 T1/T2/T3 wasteFactor
- [C] 缺 ceil() 取整
- [D] EIV 基数错误（产品售价 → 材料成本）
- [E] 费用结构乘法 vs 加法
- [F] 缺 SCC surcharge 4%
- [G] 缺工程站时间减免 15-30%
- [H] 缺工程站材料减免 1%
- [I] INSTALL_FEE_RATE=0.05 是虚构常量

---

## [A] 材料浪费公式线性化 — 严重

### 项目代码

`core/eve_formulas.py:31`
```python
ME_WASTE_BASE = 0.1  # ME 0 = 10% 浪费，每级 -1%
```

三处使用点：
- `services/scoring_service.py:458` — 制造评分
- `services/bom_expander.py:191` — BOM 展开
- `services/production_scheduler.py:141` — 生产排程

```python
waste_factor = 1 + ME_WASTE_BASE * (1 - bp_me / 10)
# = 1 + 0.1 * (1 - bp_me / 10)
```

| ME | 项目公式 | 实际公式 | 偏差 |
|----|---------|---------|------|
| 0 | 1.10 (10%) | 1.1000 (10%) | 0.0pp |
| 5 | 1.05 (5%) | 1.0167 (1.67%) | +3.33pp |
| 10 | 1.00 (0%) | 1.0091 (0.91%) | -0.91pp |
| 50 | 0.50 (-50%!) | 1.0020 (0.20%) | 荒谬 |

### 实际公式

**T1 蓝图**（wasteFactor = 10）：
```
material = base_qty × (1 + 10/100 / (1 + ME))
         = base_qty × (1 + 0.1 / (1 + ME))
```

**推导**：
- wasteFactor 取自 SDE 的 `industryActivityMaterials.wasteFactor` 列
- T1 = 10，T2 = 2，T3/rigs = 5，旗舰 = 12，部分势力 = 15
- base_waste_ratio = wasteFactor / 100
- effective_waste = base_waste_ratio / (1 + ME_level)
- material_per_run = base_qty × (1 + effective_waste)
- 浪费**永远不为零**。ME100 时：`0.1 / 101 ≈ 0.099%`

**修正**：将项目线性公式替换为 `1 + wasteFactor/100 / (1 + ME)`，其中 wasteFactor 查 SDE。

---

## [B] 未区分 T1/T2/T3 wasteFactor — 严重

### 项目代码

所有物品硬编码 `ME_WASTE_BASE = 0.1`，无兜底查表逻辑。

### 实际情况

| 蓝图类型 | SDE wasteFactor | 基浪费 | 对应 0.1 倍率 |
|---------|----------------|--------|--------------|
| T1 物品 | 10 | 10% | 当前硬编码正确 |
| T2 物品 | 2 | 2% | 高估 5 倍 |
| T3/rigs | 5 | 5% | 高估 2 倍 |
| 旗舰/超旗 | 12 | 12% | 低估 |
| 部分势力 | 15 | 15% | 低估 |

### 根因

项目 DB `blueprint_materials` 表所有 manufacturing 记录的 `wastefactor` 列全是 **NULL**（23549 行）。导入 SDE 时丢弃了 wasteFactor 信息。

### 修正

1. 从 SDE 重新导入 `industryActivityMaterials.wasteFactor` 到 DB
2. 代码中读取 `wastefactor` 列：有值则用它，NULL 时默认 10（T1 兜底）
3. 删除硬编码 `ME_WASTE_BASE = 0.1`

---

## [C] 缺 ceil() 取整 — 中

### 项目代码

```python
# scoring_service.py:463
waste_qty = mat_qty * waste_factor
# bom_expander.py:218
child_qty = mat_base_qty * waste_factor * runs
# procurement_tab.py:246
need = round(qty * waste * runs, 2)
```

全部用 float。EVE 对每种材料**每轮次**向上取整。

### 实际公式

```
per_run_units = ceil(base_qty × waste_factor)
total_units = per_run_units × runs
```

### 影响

base_qty=1、wasteFactor=2(T2)、ME=0：
- 项目：`1 × 1.02 = 1.02`
- EVE：`ceil(1 × 1.02) = 2`

单个跑就差 1 倍。多轮次时差别略小但仍存在。EVE Uni Wiki 专门讨论了这种"rounding error"（`"100 runs with 10% material reduction still needs 100 items"`）。

### 修正

在 BOM expander 和 scoring 里对 `mat_qty * waste_factor` 做 `math.ceil()`，再乘以 runs。

---

## [D] EIV 基数错误 — 严重

### 项目代码

`scoring_service.py:486-489`
```python
revenue = prod_price × prod_qty          # ← 产品市场售价
install_base = INSTALL_FEE_RATE × revenue  # ← 5% × 售价
```

### 实际公式

```
Estimated Item Value (EIV) = Σ(material_qty × adjusted_price)
                             对所有材料，按 ME0、无加成
Total job cost = EIV × ((SCI × SB) + FT + SCC + AT)
```

**EIV ≠ 产品售价**。EIV 是所有材料的**adjusted price**之和（ME0 无浪费状态下）。可从 ESI `/markets/prices/` 获取 adjusted price。

### 影响

产品售价通常远高于材料成本，项目算出的安装费系统性偏高。且安装费随产品市场波动而非材料市场波动，定价逻辑偏离游戏机制。

### 修正

1. 删除 `INSTALL_FEE_RATE = 0.05` 和 `revenue` 作为安装费基数的逻辑
2. 改为：遍历材料，查 adjusted price（或 buy price），求和得 EIV
3. 用真实 EIV 计算 job cost

---

## [E] 费用结构乘法 vs 加法 — 高

### 项目代码

`scoring_service.py:490`
```python
facility_fee = install_base × sci × (1 - structure_bonus) × (1 + facility_tax_pct / 100)
```

连乘链：`base × SCI × (1-SB) × (1+FT%)`

### 实际公式

```
job_cost = EIV × (SCI × SB + FT + SCC + AT)
```

**加法结构**：
- `SCI × SB`：系统成本指数乘以设施加成系数（NPC 站 ~1.1，玩家站 SB<1）
- `FT`：设施税（NPC 0.25%，玩家站自设 0-10%）
- `SCC`：固定 4%
- `AT`：Alpha 克隆 0.25%（仅 Alpha 账号）

### 影响

项目把 SB 当作 SCI 的折扣率（1-SB），实际 SB 是 SCI 的乘数（>1 表示加价，<1 表示折扣）。加法 vs 乘法在 tax 较高时差异明显。

### 修正

重写为 `EIV * (sci * sb + fac_tax + scc + alpha_tax)`，每项是十进制小数（如 0.0025 表示 0.25%）。

---

## [F] 缺 SCC surcharge 4% — 高

### 项目代码

`scoring_service.py:490` 没有 SCC 项。

### 实际

- **SCC surcharge** = 4%（所有制造/反应/发明/拷贝作业固定收取）
- 来源：Viridian 扩展笔记，EVE Uni Wiki Manufacturing > Tax reforms

### 修正

在 `core/eve_formulas.py` 新增常量 `SCC_SURCHARGE = 0.04`，加到 job cost 公式的加法项中（见 [E]）。

---

## [G] 缺工程站时间减免 15-30% — 中

### 项目代码

`scoring_service.py:502-504`
```python
skill_mod = (1 - 0.04 × ind_lvl) × (1 - 0.03 × adv_lvl)
actual_time = base_time × skill_mod × (1 - 0.01 × TE)
```

### 实际

```
time = base_time × skill_mod × TE_mod × structure_time_mod
```

工程站（Engineering Complex）提供时间减免：
- **Raitaru**（小）：15%
- **Athanor**（中）：20%
- **Tatara**（大）：25%
- **Sotiyo**（超大）：30%
- 可安装 rig 进一步降低

NPC 站无时间减免（mod = 1.0）。

### 修正

在 scoring 函数的 `structure_bonus` 参数基础上，增加 `production_time_modifier` 参数（0.70~1.0），作为额外乘数加入时间公式。

---

## [H] 缺工程站材料减免 1% — 低

### 实际

所有工程站自带 1% 材料扣除（reduce material requirement by 1%），rig 可增加。

### 项目

未实现。`waste_factor` 公式中无材料减免因子。

### 修正

在 waste_factor 公式中追加一个 `material_efficiency_modifier` 乘数（0.99 或 1.0 默认）。

---

## [I] INSTALL_FEE_RATE = 0.05 是虚构常量 — 与 [D][E][F] 连带

`core/eve_formulas.py:27`
```python
INSTALL_FEE_RATE = 0.05  # 安装费 = 5% × 成品收入
```

EVE 没有"安装费 = 固定比例 × 售价"这个机制。安装费就是 `Total job cost`，由 [D][E][F] 构成。这个 0.05 是完全虚构的参数，应删除。

---

## 文件级修改清单

| 文件 | 修改内容 |
|------|---------|
| `core/eve_formulas.py` | 删除 `INSTALL_FEE_RATE`, `ME_WASTE_BASE`。新增 `SCC_SURCHARGE`, `FACILITY_TAX_NPC`, `ALPHA_TAX`, `STRUCTURE_TIME_BONUS_{RAITARU/ATHANOR/TATARA/SOTIYO}`, `STRUCTURE_MAT_SAVING` |
| `services/scoring_service.py` | 重写 `calc_manufacturing_score` 的材料浪费、安装费部分。改为查 wasteFactor；加 ceil；加 SCC；加结构时间折扣 |
| `services/bom_expander.py` | `_expand` 中 waste_factor 公式改用查表 + ceil |
| `services/production_scheduler.py` | 同上 |
| `ui_pyside6/views/procurement_tab.py` | `ceil` 替代 `round` |
| 数据层 | 重新导入 `industryActivityMaterials.wasteFactor` 到 DB |
