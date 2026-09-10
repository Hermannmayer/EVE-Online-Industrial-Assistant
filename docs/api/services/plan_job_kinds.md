# services.plan_job_kinds

> 源文件 `services/plan_job_kinds.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

工业计划的活动契约 — 每种作业「需要什么输入蓝图 / 产出什么」的唯一真源。

生产计划（production_plans）从「制造计划」泛化为「工业计划」后，
`product_type_id` / `blueprint_type_id` 的语义随 `activity` 变化，
所有消费方（启动校验、蓝图绑定、采购聚合、类别推导、产能占用）
必须经本模块判定，不得各自硬编码 `activity='manufacturing'`。

语义契约:
    activity                      product_type_id 是        blueprint_type_id 是
    ----------------------------  -----------------------  ---------------------
    manufacturing                 造出来的物品              制造蓝图
    copying                       产出的 BPC 代表的蓝图      被拷贝的 BPO
    invention                     产出的 T2/T3 蓝图         被发明的 T2 蓝图（T1 由它反查）
    researching_*_efficiency      被研究的那个蓝图          被研究的 BPO

推论：科研行的产物**不在** `blueprint_products.activity='manufacturing'` 里
（蓝图不是制造品），任何「按产物反查制造蓝图」的逻辑对科研行都会得到错误结果。

## 函数

### `normalize`

```python
def normalize(activity: str | None) -> str
```

未知/空 activity 一律归 manufacturing（旧行兼容）。

定义行：`75`

### `is_science`

```python
def is_science(activity: str | None) -> bool
```

是否科研作业（拷贝/发明/ME-TE 研究）。

定义行：`81`

### `input_blueprint_rule`

```python
def input_blueprint_rule(activity: str | None) -> str
```

该活动需要的输入蓝图规则 → RULE_* 常量。

定义行：`86`

### `needs_input_blueprint`

```python
def needs_input_blueprint(activity: str | None) -> bool
```

该活动是否必须绑定一张输入蓝图才能开工。

定义行：`91`

### `output_kind`

```python
def output_kind(activity: str | None) -> str
```

该活动的产出口径 → OUTPUT_* 常量。

定义行：`96`

### `product_is_blueprint`

```python
def product_is_blueprint(activity: str | None) -> bool
```

产物是否是一张蓝图（科研=True）→ 消费方禁止按「制造产物」反查关键数据。

定义行：`101`

### `accepts_bpo`

```python
def accepts_bpo(activity: str | None) -> bool
```

该活动是否接受蓝图原本（BPO）。

定义行：`106`

### `accepts_bpc`

```python
def accepts_bpc(activity: str | None) -> bool
```

该活动是否接受蓝图拷贝（BPC）。

定义行：`111`

### `input_blueprint_hint`

```python
def input_blueprint_hint(activity: str | None) -> str
```

输入蓝图不足时的用户提示（启动校验用）。

定义行：`116`

### `material_activity`

```python
def material_activity(activity: str | None) -> str
```

该活动在 blueprint_materials / blueprint_activities 表里的活动名。

定义行：`129`
