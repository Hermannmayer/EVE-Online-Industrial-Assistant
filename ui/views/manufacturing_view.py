"""
制造 / 工业页面 — Flet 实现

功能：
  - 三级子页面：估价与精炼、制造业、行星工业、忠诚点价值
  - 均以占位符形式显示
"""
import flet as ft
from typing import Optional
from ui.config import CJK_FONT


class IndustryPage(ft.Container):
    """制造/工业页面容器 — 带二级导航标签"""

    def __init__(self, page: ft.Page):
        super().__init__()
        self._page = page
        self.expand = True
        self.bgcolor = "#1a1a2e"

        # ── 二级导航标签 ──
        sub_tabs = [
            ("估价与精炼", ft.icons.Icons.CALCULATE),
            ("制 造 业", ft.icons.Icons.FACTORY),
            ("行星工业", ft.icons.Icons.PUBLIC),
            ("忠诚点价值", ft.icons.Icons.STARS),
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
            # 占位页面
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

        # 导航行
        self._nav_row = ft.Row(
            controls=self._tab_buttons,
            spacing=8,
            alignment=ft.MainAxisAlignment.CENTER,
        )

        # 内容堆栈
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

        # 默认选中第一项
        self._switch_tab("估价与精炼")

    def _switch_tab(self, name: str):
        """切换二级标签"""
        tab_names = ["估价与精炼", "制 造 业", "行星工业", "忠诚点价值"]
        idx = tab_names.index(name)
        # 更新按钮样式
        for i, btn in enumerate(self._tab_buttons):
            is_active = (i == idx)
            btn.bgcolor = "#e94560" if is_active else "transparent"
            for c in btn.content.controls:
                c.color = "#ffffff" if is_active else "#888888"
        # 切换内容
        for i, content in enumerate(self._tab_contents):
            content.visible = (i == idx)
        self._page.update()
