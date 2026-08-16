# services.inventory_clipboard_service

> 源文件 `services/inventory_clipboard_service.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

库存剪贴板解析 — 将 EVE 复制文本匹配到物品 ID。

## 函数

### `parse_clipboard`

```python
def parse_clipboard(raw: str) -> list[dict]
```

解析 EVE 剪贴板 → list[&#123;type_id|None, raw_name, zh_name, en_name, qty, status&#125;]。

定义行：`10`
