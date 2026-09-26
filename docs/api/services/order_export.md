# services.order_export

> 源文件 `services/order_export.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

EVE 挂单导出解析 —— 纯函数（无 DB、无 Qt）。

数据来源：游戏内「钱包 → 订单 → 导出」写出的**本地文件**（CSV）。

解析策略（按优先级）：
1. **表头驱动**：首行若是逗号/制表符分隔且含已知列名，则按列名建「列序→字段」映射，
   逐行按位置取值。列名映射大小写与下划线不敏感，并接受同义名
   （``typeID``/``type_id``、``volRemaining``/``vol_remaining`` 等）。
   列序可任意打乱，缺失列取默认值。
2. **启发式兜底**：无表头（或表头认不出）时，退化为逐行「找最大整数当订单 ID /
   小数当价格 / 两个整数当挂单量·剩余 / 买·卖词当方向 / X 天·X 小时当有效期」的启发式；
   认不出的行计入未识别计数。

两种路径都不抛异常；输出 dict 的键与 ``open_orders`` 表列一致。

## 函数

### `_empty_order`

```python
def _empty_order() -> dict
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`26`

### `_norm_col`

```python
def _norm_col(name: str) -> str
```

归一化列名：小写 + 去空格/下划线（大小写与下划线不敏感）。

定义行：`91`

### `_clean_value`

```python
def _clean_value(raw: str) -> str
```

拆掉 ``<localized>`` 包装并去掉值尾部那个占位 ``*``。

定义行：`107`

### `read_export_text`

```python
def read_export_text(path: str | Path) -> str
```

读导出文件 → 文本。**按 BOM/编码逐档尝试**。

定义行：`133`

### `_normalize_number`

```python
def _normalize_number(token: str) -> str | None
```

把带千分位/货币后缀的数值串归一为可 ``float()`` 的纯数字串；失败返回 None。

定义行：`156`

### `_to_float`

```python
def _to_float(token: str) -> float | None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`184`

### `_to_int`

```python
def _to_int(token: str) -> int | None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`194`

### `_to_bool`

```python
def _to_bool(token: str) -> int | None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`204`

### `_to_duration`

```python
def _to_duration(token: str) -> int | None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`213`

### `_split_csv_line`

```python
def _split_csv_line(line: str, delim: str) -> list[str]
```

按分隔符拆一行 CSV（正确处理引号包裹的字段）。

定义行：`225`

### `_header_mapping`

```python
def _header_mapping(cols: list[str]) -> dict[int, str]
```

列序 → 字段。至少命中 2 个已知列名才认定为表头（否则返回空 dict）。

定义行：`230`

### `_assign`

```python
def _assign(row: dict, field: str, val: str) -> None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`242`

### `_parse_with_header`

```python
def _parse_with_header(lines: list[str], delim: str, mapping: dict[int, str]) -> tuple[list[dict], int]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`275`

### `_split_heuristic`

```python
def _split_heuristic(line: str) -> list[str]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`298`

### `_is_header_row`

```python
def _is_header_row(parts: list[str]) -> bool
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`304`

### `_parse_heuristic_row`

```python
def _parse_heuristic_row(parts: list[str]) -> dict | None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`310`

### `_parse_heuristic`

```python
def _parse_heuristic(lines: list[str]) -> tuple[list[dict], int]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`361`

### `parse_order_export`

```python
def parse_order_export(raw: str) -> tuple[list[dict], int]
```

解析 EVE 挂单导出文本 → ``(订单列表, 未识别行数)``。

定义行：`386`

### `_default_export_dir`

```python
def _default_export_dir() -> str
```

EVE 订单导出默认目录。

定义行：`408`

### `_safe_mtime`

```python
def _safe_mtime(path: Path) -> float
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`419`

### `find_latest_export`

```python
def find_latest_export(directory: str | None=None) -> str | None
```

返回目录下最新的订单导出文件路径（按 mtime）；没有则 None。

定义行：`426`
