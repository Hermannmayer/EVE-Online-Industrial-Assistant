# services.importers.getrigdata

> 源文件 `services/importers/getrigdata.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

拉取结构改装件（Standup Engineering Rigs）的制造加成（从 ESI /universe/types/ 并发拉取）

只处理制造相关的工程站改装件组（reference.db item 表 group 1816-1870，剔除
1818 Strong Boxes 与 1817 空组，共 53 组 111 个改件）：
  - 材料效率钻机（attributeEngRigMatBonus=2594）
  - 时间效率钻机（attributeEngRigTimeBonus=2593）
  - 成本优化钻机（attributeEngRigCostBonus=2595；发明/ME/TE 研究/拷贝成本）

说明：SDE 的 typeIDs.yaml 导出不含 dogmaAttributes，改件加成直接走 ESI 拉取，
写入 reference.db 的 structure_rigs 表（机库设置 UI 展示与成本解析使用）。

`cost_bonus` 是 2026-10-17 审计 01-13 补的列：旧缓存库没有该列，`init_db()` 会
「列不存在则 ALTER TABLE 补列」（reference.db 是可重建缓存，不走 user.db 迁移）；
旧库补列后该列为 NULL = 从未拉取过，`main()` 会把这些行重新拉一遍（不能把
「未拉取」的 0 当成真实加成）。

## 函数

### `init_db`

```python
def init_db(db_path: str)
```

建表 / 给旧缓存库补 `cost_bonus` 列（列不存在则 ALTER，幂等）。

定义行：`96`

### `get_rig_type_ids`

```python
def get_rig_type_ids(db_path: str) -> list[int]
```

从 item 表按改装件组查询 type_id 列表

定义行：`125`

### `fetch_rig_bonuses`

```python
async def fetch_rig_bonuses(client, type_id: int) -> dict | None
```

从 ESI 获取 type 的材料/时间/成本加成

定义行：`139`

### `main`

```python
async def main(progress_cb=None)
```

初始化表 → 查已缓存 → 增量并发拉取缺失 → 写入 structure_rigs

定义行：`160`
