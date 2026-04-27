"""
仓库页面 — Flet 实现

功能：
  - 展示选中的物品清单
  - 顶部搜索/过滤栏
  - 表格形式展示物品
"""
import flet as ft
from typing import Optional
import sqlite3
import os
from ui.config import CJK_FONT


from core.paths import DB_PATH


class StoragePage(ft.Container):
    """仓库页 — 物品清单与搜索"""

    def __init__(self, page: ft.Page):
        super().__init__()
        self._page = page
        self.expand = True
        self.bgcolor = "#1a1a2e"

        # 搜索输入
        self.search_field = ft.TextField(
            hint_text="输入物品名称搜索…",
            border_color="#2a2a4a",
            color="#ffffff",
            hint_style=ft.TextStyle(color="#555555"),
            border_radius=8,
            expand=True,
            text_size=14,
            on_submit=lambda e: self._load_items(),
        )

        search_btn = ft.IconButton(
            icon=ft.icons.Icons.SEARCH,
            icon_color="#e94560",
            on_click=lambda e: self._load_items(),
        )

        # 表格列定义
        columns = [
            ft.DataColumn(ft.Text("物品ID", color="#888888", size=12)),
            ft.DataColumn(ft.Text("名称", color="#888888", size=12)),
            ft.DataColumn(ft.Text("类别", color="#888888", size=12)),
            ft.DataColumn(ft.Text("数量", color="#888888", size=12)),
        ]

        self.data_table = ft.DataTable(
            columns=columns,
            rows=[],
            border=ft.border.all(1, "#2a2a4a"),
            border_radius=8,
            heading_row_color="#16213e",
            data_row_color="#1a1a2e",
            column_spacing=40,
        )

        self._content_area = ft.Container(
            content=ft.Column(
                controls=[
                    self.data_table,
                ],
                scroll=ft.ScrollMode.AUTO,
                expand=True,
            ),
            expand=True,
            padding=20,
        )

        self.content = ft.Column(
            controls=[
                ft.Container(
                    content=ft.Row(
                        controls=[self.search_field, search_btn],
                        spacing=8,
                    ),
                    padding=ft.padding.symmetric(horizontal=20, vertical=10),
                    bgcolor="#16213e",
                    border=ft.border.only(bottom=ft.BorderSide(1, "#2a2a4a")),
                ),
                self._content_area,
            ],
            spacing=0,
            expand=True,
        )

    def _load_items(self):
        """从数据库加载物品数据"""
        keyword = self.search_field.value.strip()
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            if keyword:
                cursor.execute(
                    "SELECT type_id, name, group_name, portion_size FROM items WHERE name LIKE ? LIMIT 200",
                    (f"%{keyword}%",),
                )
            else:
                cursor.execute(
                    "SELECT type_id, name, group_name, portion_size FROM items LIMIT 200"
                )
            rows = cursor.fetchall()
            conn.close()

            self.data_table.rows.clear()
            for row in rows:
                self.data_table.rows.append(
                    ft.DataRow(
                        cells=[
                            ft.DataCell(ft.Text(str(row[0]), color="#cccccc", size=12)),
                            ft.DataCell(ft.Text(row[1], color="#ffffff", size=13)),
                            ft.DataCell(ft.Text(row[2] or "", color="#aaaaaa", size=12)),
                            ft.DataCell(ft.Text(str(row[3]), color="#cccccc", size=12)),
                        ]
                    )
                )
        except Exception as ex:
            print(f"[DB Error] {ex}")

        self._page.update()
