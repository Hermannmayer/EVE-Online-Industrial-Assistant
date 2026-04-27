"""
贸易页面 — Flet 实现

功能：
  - 二层子页面：价格监控 & 蓝运输分析（均为占位符，待后续实现）
"""
import flet as ft
from ui.config import CJK_FONT


class TradePage(ft.Container):
    """贸易页容器 — 带二级导航标签"""

    def __init__(self, page: ft.Page):
        super().__init__()
        self._page = page
        self.expand = True
        self.bgcolor = "#1a1a2e"

        sub_tabs = [
            ("价格监控", ft.icons.Icons.MONITOR_HEART_OUTLINED),
            ("蓝运输分析", ft.icons.Icons.LOCAL_SHIPPING_OUTLINED),
        ]

        self._tab_buttons = []
        self._tab_contents = []

        for name, icon in sub_tabs:
            btn = ft.Container(
                content=ft.Row(
                    controls=[
                        ft.Icon(icon, size=18, color="#888888"),
                        ft.Text(name, size=14, color="#888888"),
                    ],
                    spacing=6,
                    alignment=ft.MainAxisAlignment.CENTER,
                ),
                padding=ft.padding.symmetric(horizontal=20, vertical=10),
                border_radius=8,
                bgcolor="transparent",
                on_click=lambda e, n=name: self._switch_tab(n),
                ink=True,
            )
            self._tab_buttons.append(btn)
            self._tab_contents.append(
                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Icon(icon, size=64, color="#555555"),
                            ft.Text(f"{name} — 开发中", size=18, color="#555555"),
                        ],
                        alignment=ft.MainAxisAlignment.CENTER,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    expand=True,
                    alignment=ft.alignment.Alignment(0, 0),
                )
            )

        self._nav_row = ft.Row(
            controls=self._tab_buttons,
            spacing=8,
            alignment=ft.MainAxisAlignment.CENTER,
        )

        self._content_stack = ft.Stack(
            controls=self._tab_contents,
            expand=True,
        )

        self.content = ft.Column(
            controls=[
                ft.Container(
                    content=self._nav_row,
                    bgcolor="#16213e",
                    padding=ft.padding.symmetric(vertical=8, horizontal=20),
                    border=ft.border.only(bottom=ft.BorderSide(1, "#2a2a4a")),
                ),
                self._content_stack,
            ],
            spacing=0,
            expand=True,
        )

        self._switch_tab("价格监控")

    def _switch_tab(self, name: str):
        tab_names = ["价格监控", "运输分析"]
        idx = tab_names.index(name)
        for i, btn in enumerate(self._tab_buttons):
            is_active = (i == idx)
            btn.bgcolor = "#e94560" if is_active else "transparent"
            for c in btn.content.controls:
                c.color = "#ffffff" if is_active else "#888888"
        for i, content in enumerate(self._tab_contents):
            content.visible = (i == idx)
        self._page.update()
