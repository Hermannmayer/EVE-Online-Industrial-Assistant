"""
导出工具 — CSV / Excel 批量导出
"""

import csv

from openpyxl import Workbook


def export_to_csv(headers: list[str], rows: list[list], filepath: str) -> None:
    """导出为 CSV（UTF-8 BOM，兼容 Excel 中文）"""
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)


def export_to_excel(headers: list[str], rows: list[list], filepath: str) -> None:
    """导出为 Excel（.xlsx），自动调整列宽"""
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(headers)
    for row in rows:
        ws.append(row)

    # 自动列宽
    for col_cells in ws.columns:
        max_len = 0
        col_letter = col_cells[0].column_letter
        for cell in col_cells:
            val = str(cell.value) if cell.value is not None else ""
            # CJK 字符按 2 倍宽度估算
            width = sum(2 if ord(c) > 127 else 1 for c in val)
            if width > max_len:
                max_len = width
        ws.column_dimensions[col_letter].width = min(max_len + 3, 60)

    wb.save(filepath)


def get_save_filename(parent, default_name: str, file_filter: str) -> str:
    """弹出保存文件对话框，返回路径（空字符串表示取消）"""
    from PySide6.QtWidgets import QFileDialog

    path, _ = QFileDialog.getSaveFileName(parent, "导出", default_name, file_filter)
    return path
