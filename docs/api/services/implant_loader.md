# services.implant_loader

> 源文件 `services/implant_loader.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

工业植入体数据加载 — 从 reference.db 读取并解析加成描述。

## 函数

### `_parse_implant_bonus`

```python
def _parse_implant_bonus(attrs: list) -> str
```

从 dogma 属性解析人类可读的加成描述。

定义行：`14`

### `load_implants`

```python
def load_implants() -> list[dict]
```

从 item_dogma 表加载所有工业植入体。

定义行：`44`
