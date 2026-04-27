"""
EVE 制造助手 — Flet 入口点
"""
import flet as ft
import sqlite3
import subprocess
import asyncio
import os
import json
from datetime import datetime, timezone, timedelta
from ui.config import DB_PATH, CJK_FONT


from core.paths import ensure_dirs_exist, progress_file

def main(page: ft.Page):
    # 确保数据目录存在（打包后首次运行）
    ensure_dirs_exist()

    page.title = "EVE 商人助手"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = "#1a1a2e"
    page.padding = 0
    page.spacing = 0
    page.window.min_width = 1200
    page.window.min_height = 700

    # ── 自定义主题 ──
    page.theme = ft.Theme(
        color_scheme=ft.ColorScheme(
            primary="#e94560",
            on_primary="#ffffff",
            secondary="#0f3460",
            on_secondary="#e0e0e0",
            surface="#16213e",
            on_surface="#e0e0e0",
        ),
        font_family=CJK_FONT,
    )

    # ── 价格更新时间 ──
    price_time_text = ft.Text("价格更新时间: —", size=11, color="#888888")

    def refresh_price_time():
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(fetch_time) FROM market_prices")
            row = cursor.fetchone()
            conn.close()
            if row and row[0]:
                utc_str = row[0]
                try:
                    dt = datetime.strptime(utc_str, "%Y-%m-%d %H:%M:%S")
                    bj_dt = dt.replace(tzinfo=timezone.utc) + timedelta(hours=8)
                    bj_str = bj_dt.strftime("%Y-%m-%d %H:%M:%S")
                    price_time_text.value = f"价格更新时间: {bj_str} (北京)"
                except Exception:
                    price_time_text.value = f"价格更新时间: {utc_str} UTC"
            else:
                price_time_text.value = "价格更新时间: 暂无数据"
        except Exception:
            price_time_text.value = "价格更新时间: 数据库未就绪"
        page.update()

    # ── 内容容器 ──
    content_container = ft.Container(
        expand=True,
        bgcolor="#1a1a2e",
        padding=0,
    )

    # ── 页面实例 ──
    from ui.views.query_view import QueryPage
    from ui.views.manufacturing_view import IndustryPage
    from ui.views.market_view import TradePage
    from ui.views.inventory_view import StoragePage

    pages = {}
    pages["query"] = QueryPage(page, refresh_price_time)
    pages["industry"] = IndustryPage(page)
    pages["trade"] = TradePage(page)
    pages["storage"] = StoragePage(page)

    # ── 紧凑侧边栏 ──
    _nav_selected_index = [0]  # 可变容器，闭包可写

    # 导航定义：图标 + 标签 + 页码键
    nav_entries = [
        (ft.icons.Icons.SEARCH, "查询", "query"),
        (ft.icons.Icons.CALCULATE, "估价/精炼", "industry"),
        (ft.icons.Icons.FACTORY, "制造业", "industry"),
        (ft.icons.Icons.PUBLIC, "行星工业", "industry"),
        (ft.icons.Icons.TRENDING_UP, "贸易业", "trade"),
        (ft.icons.Icons.WAREHOUSE, "仓库", "storage"),
        (ft.icons.Icons.STARS, "忠诚点", "industry"),
    ]

    nav_items_container = ft.Column(spacing=2, scroll=ft.ScrollMode.AUTO)

    def build_nav_buttons(selected_idx):
        btns = []
        for i, (icon_name, label, key) in enumerate(nav_entries):
            is_sel = i == selected_idx
            btns.append(
                ft.Container(
                    content=ft.Row([
                        ft.Icon(icon_name, color="#e94560" if is_sel else "#888888", size=18),
                        ft.Text(label, size=12, color="#e0e0e0" if is_sel else "#aaaaaa", weight=ft.FontWeight.BOLD if is_sel else ft.FontWeight.NORMAL),
                    ], spacing=6, alignment=ft.MainAxisAlignment.START),
                    padding=ft.padding.symmetric(horizontal=10, vertical=7),
                    bgcolor="#0f3460" if is_sel else "transparent",
                    border_radius=6,
                    on_click=lambda e, idx=i, k=key: _on_nav_click(idx, k),
                    on_hover=lambda e, c=i: setattr(e.control, 'bgcolor', '#0f3460' if e.data == 'true' else ('#0f3460' if c == _nav_selected_index[0] else 'transparent')) or page.update(),
                )
            )
        return btns

    def _on_nav_click(idx, key):
        _nav_selected_index[0] = idx
        nav_items_container.controls = build_nav_buttons(idx)
        content_container.content = pages.get(key, pages["query"])
        page.update()

    nav_items_container.controls = build_nav_buttons(0)

    sidebar = ft.Container(
        content=ft.Column([
            ft.Container(height=8),
            nav_items_container,
        ], spacing=0, expand=True),
        width=120,
        bgcolor="#16213e",
        padding=ft.padding.symmetric(horizontal=4, vertical=0),
        border=ft.border.only(right=ft.BorderSide(1, "#2a2a4a")),
    )

    # ── 顶部标题栏 ──
    header = ft.Container(
        content=ft.Row(
            controls=[
                ft.Icon(ft.icons.Icons.ROCKET_LAUNCH, color="#e94560", size=28),
                ft.Text("EVE 商人助手", size=20, weight=ft.FontWeight.BOLD, color="#e0e0e0"),
            ],
            alignment=ft.MainAxisAlignment.CENTER,
        ),
        bgcolor="#16213e",
        padding=ft.padding.symmetric(vertical=12, horizontal=20),
        border=ft.border.only(bottom=ft.BorderSide(1, "#2a2a4a")),
    )

    # ── 底部状态栏 ──
    update_status_text = ft.Text("", size=11, color="#888888")
    update_btn_ref = ft.Ref[ft.Button]()
    update_progress_bar = ft.ProgressBar(width=200, height=4, color="#e94560", bgcolor="#2a2a4a", visible=False)

    def poll_progress():
        """轮询进度文件并更新 UI"""
        try:
            if os.path.exists(progress_file):
                with open(progress_file, "r") as f:
                    data = json.load(f)
                current = data.get("current", 0)
                total = data.get("total", 1)
                phase = data.get("phase", "")
                # 格式: "3/5 拉取卖单数据..."
                update_status_text.value = f"{current}/{total} {phase}"
                page.update()
                return current < total
            else:
                return True
        except Exception:
            return True

    _update_running = [False]  # 防止重复启动

    def trigger_price_update(e):
        if _update_running[0]:
            return
        _update_running[0] = True
        btn = update_btn_ref.current
        if btn is not None:
            btn.disabled = True
            btn.content = ft.Text("⏳ 更新中...", color="#e0e0e0", size=13)
        update_status_text.value = "正在抓取市场价格..."
        update_progress_bar.visible = True
        page.update()

        async def run_update_async():
            try:
                # 直接调用，无需 subprocess（兼容 exe 打包）
                from services.workers.getprices import run_price_update
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, run_price_update)

                btn.disabled = False
                btn.content = ft.Row(
                    controls=[
                        ft.Icon(ft.icons.Icons.REFRESH, color="#e0e0e0", size=16),
                        ft.Text("🔄 更新价格", color="#e0e0e0", size=13),
                    ],
                    spacing=4,
                )
                update_progress_bar.visible = False
                update_status_text.value = "✅ 价格更新完成"
                refresh_price_time()
                if hasattr(pages.get("query"), "refresh_display"):
                    pages["query"].refresh_display()
                page.update()
                await asyncio.sleep(4)
                update_status_text.value = ""
                page.update()
            except Exception as ex:
                btn.disabled = False
                btn.content = ft.Row(
                    controls=[
                        ft.Icon(ft.icons.Icons.REFRESH, color="#e0e0e0", size=16),
                        ft.Text("🔄 更新价格", color="#e0e0e0", size=13),
                    ],
                    spacing=4,
                )
                update_progress_bar.visible = False
                update_status_text.value = f"❌ {str(ex)}"
                page.update()

        page.run_task(run_update_async)

    update_btn = ft.Button(
        ref=update_btn_ref,
        content=ft.Row(
            controls=[
                ft.Icon(ft.icons.Icons.REFRESH, color="#e0e0e0", size=16),
                ft.Text("🔄 更新价格", color="#e0e0e0", size=13),
            ],
            spacing=4,
        ),
        on_click=trigger_price_update,
        style=ft.ButtonStyle(
            color="#e0e0e0",
            bgcolor="#0f3460",
            padding=ft.padding.symmetric(horizontal=16, vertical=6),
        ),
    )

    bottom_bar = ft.Container(
        content=ft.Row(
            controls=[
                price_time_text,
                ft.Column(
                    controls=[
                        update_progress_bar,
                        ft.Row(
                            controls=[update_status_text, update_btn],
                            spacing=10,
                        ),
                    ],
                    spacing=2,
                    horizontal_alignment=ft.CrossAxisAlignment.END,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        ),
        bgcolor="#16213e",
        padding=ft.padding.symmetric(horizontal=16, vertical=6),
        border=ft.border.only(top=ft.BorderSide(1, "#2a2a4a")),
    )

    # ── 默认显示查询页 ──
    content_container.content = pages["query"]

    # ── 整体布局 ──
    page.add(
        ft.Column(
            controls=[
                header,
                ft.Row(
                    controls=[
                        sidebar,
                        content_container,
                    ],
                    expand=True,
                    spacing=0,
                ),
                bottom_bar,
            ],
            spacing=0,
            expand=True,
        )
    )

    # ── 启动时自动核验价格时间，超过半小时自动更新 ──
    def check_price_and_update():
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(fetch_time) FROM market_prices")
            row = cursor.fetchone()
            conn.close()
            if row and row[0]:
                utc_str = row[0]
                dt = datetime.strptime(utc_str, "%Y-%m-%d %H:%M:%S")
                now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
                diff = (now_utc - dt).total_seconds()
                if diff > 1800:  # 超过半小时
                    update_status_text.value = "价格数据已超过半小时，自动更新中..."
                    page.update()
                    trigger_price_update(None)
                else:
                    update_status_text.value = f"✓ 价格数据{(diff/60):.0f}分钟前更新，无需更新"
                    page.update()
            else:
                # 无数据，直接更新
                update_status_text.value = "无价格数据，自动更新中..."
                page.update()
                trigger_price_update(None)
        except Exception as ex:
            update_status_text.value = f"价格检查失败: {ex}"
            page.update()

    refresh_price_time()
    # 延迟2秒再检查，确保页面渲染完成
    async def delayed_check():
        await asyncio.sleep(2)
        check_price_and_update()
    page.run_task(delayed_check)


if __name__ == "__main__":
    ft.app(target=main)
