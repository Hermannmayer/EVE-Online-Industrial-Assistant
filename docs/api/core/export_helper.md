# core.export_helper

> 源文件 `core/export_helper.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

导出工具 — CSV / Excel 批量导出（纯 Python，零 Qt）。

原先在 `ui_pyside6/views/export_helper.py`，随批次 6.0 搬来 `core/`：
两个函数只依赖标准库与 openpyxl，两套 UI 都要用。
弹保存框的 `get_save_filename` 依赖 QFileDialog，落在 `ui_qml/file_dialogs.py`。

## 函数

### `export_to_csv`

```python
def export_to_csv(headers: list[str], rows: list[list], filepath: str) -> None
```

导出为 CSV（UTF-8 BOM，兼容 Excel 中文）

定义行：`15`

### `export_to_excel`

```python
def export_to_excel(headers: list[str], rows: list[list], filepath: str) -> None
```

导出为 Excel（.xlsx），自动调整列宽

定义行：`23`
