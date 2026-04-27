"""
查询物品页面 — Flet 实现

功能：
  - 模糊搜索 + 实时候选下拉列表
  - 搜索类别名自动显示该类物品
  - 图片图标、价格后括号标注数量
  - 双击行 → 展开底部订单面板（买单 Top5 / 卖单 Top5）
  - 清空按钮、单击复制价格
  - 搜索/加载时显示进度条
  - 订单缓存（5分钟过期）
  - 右键菜单占位
"""
import flet as ft
import sqlite3
import aiohttp
import asyncio
import json
import os
import pyperclip
import time as _time
from pathlib import Path
from typing import Optional, Callable
from ui.config import DB_PATH, ICON_DIR, ICON_SIZE, CJK_FONT, MONO_FONT, ESI_BASE_URL, REGION_ID
from core.paths import search_history_file

HISTORY_FILE = Path(search_history_file())
MAX_HISTORY = 20

_station_name_cache: dict[int, str] = {}

async def _resolve_names(location_ids: list[int]):
    need = [lid for lid in location_ids if lid not in _station_name_cache]
    if not need: return
    url = f"{ESI_BASE_URL}/universe/names/"
    chunks = [need[i:i+1000] for i in range(0, len(need), 1000)]
    async with aiohttp.ClientSession(
        headers={"Accept": "application/json", "User-Agent": "EveDataCrawler/1.0"},
        timeout=aiohttp.ClientTimeout(total=30)
    ) as session:
        for chunk in chunks:
            try:
                async with session.post(url, json=chunk) as resp:
                    if resp.status == 200:
                        for item in await resp.json():
                            _station_name_cache[item["id"]] = item.get("name", str(item["id"]))
                    else:
                        for lid in chunk: _station_name_cache.setdefault(lid, str(lid))
            except Exception:
                for lid in chunk: _station_name_cache.setdefault(lid, str(lid))


class QueryPage(ft.Container):
    """物品查询页面"""

    def __init__(self, page: ft.Page, refresh_callback: Optional[Callable] = None):
        super().__init__()
        self._page = page
        self.expand = True
        self.bgcolor = "#1a1a2e"
        self._refresh_callback = refresh_callback
        self._all_groups: list[tuple[int, str, str]] = []
        self._search_results: list[dict] = []
        self._order_panel_visible = False
        self._current_order_type_id: Optional[int] = None
        self._current_query: str = ""
        # 订单缓存: {type_id: (buy_orders, sell_orders, fetch_time)}
        self._order_cache: dict[int, tuple] = {}
        # 排序状态
        self._sort_column: str = None
        self._sort_asc: bool = True

        self._build_ui()
        self._page.run_task(self._load_group_list)

    # ─── 表头文本列 ───
    _COLUMN_KEYS = ["图标", "ID", "中文名", "英文名", "类别", "买单 ↓", "卖单 ↑", "均价", "体积 m³"]
    # 各列对应的数据 key（用于排序）；None 表示不可排序
    _SORT_KEYS = [None, "type_id", "zh", "en", "group", "buy_price", "sell_price", "avg_price", "vol_val"]

    def _build_ui(self):

        # 搜索栏
        self.search_input = ft.TextField(
            hint_text="请输入物品名称/ID/类别搜索",
            text_size=14, color="#e0e0e0",
            hint_style=ft.TextStyle(color="#888888"),
            border_color="#2a2a4a", focused_border_color="#e94560",
            bgcolor="#0f3460", border_radius=8, expand=True, height=40,
            content_padding=ft.padding.symmetric(horizontal=12, vertical=8),
            on_change=self._on_search_input_change,
            on_focus=lambda e: self._show_search_history(),
            on_submit=lambda e: self._do_search(),
            prefix_icon=ft.icons.Icons.SEARCH,
            suffix=ft.IconButton(
                icon=ft.icons.Icons.CLOSE, icon_color="#888888", icon_size=18,
                tooltip="清空", on_click=lambda e: self._clear_search(),
            ),
        )
        self.search_bar = ft.Container(
            content=ft.Row([self.search_input], spacing=8, alignment=ft.MainAxisAlignment.CENTER),
            padding=ft.padding.symmetric(horizontal=20, vertical=6),
            bgcolor="#16213e",
            border=ft.border.only(bottom=ft.BorderSide(1, "#2a2a4a")),
        )

        # 进度条
        self._progress_bar = ft.ProgressBar(width=0, height=3, color="#e94560", bgcolor="#2a2a4a", visible=False)

        # 状态信息
        self._count_text = ft.Text("", size=11, color="#888888")
        self._status_text = ft.Text("输入物品名称/ID/类别后搜索，双击行查看实时订单", size=11, color="#888888")
        self.status_row = ft.Row(
            controls=[self._count_text, self._status_text],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN, visible=False,
        )

        # 表头行
        self._header_row = ft.Container(
            content=ft.Row(
                controls=self._build_header_cells(),
                spacing=12,
            ),
            bgcolor="#0f3460",
            padding=ft.padding.symmetric(horizontal=12, vertical=8),
            border=ft.Border(bottom=ft.BorderSide(1, "#2a2a4a")),
        )

        # 结果列表（使用 ListView 代替 DataTable）
        self._result_list = ft.ListView(
            controls=[],
            expand=True,
            spacing=2,
            padding=8,
        )

        # 结果区域容器
        self._result_area = ft.Container(
            content=ft.Column(
                controls=[
                    self.status_row,
                    self._header_row,
                    self._result_list,
                ],
                spacing=2,
                expand=True,
            ),
            padding=ft.padding.symmetric(horizontal=16, vertical=8),
            expand=True,
        )

        # 订单面板
        self._order_title = ft.Text("", size=14, weight=ft.FontWeight.BOLD, color="#e0e0e0")
        self._order_buy_list = ft.ListView(controls=[], expand=True, spacing=2)
        self._order_sell_list = ft.ListView(controls=[], expand=True, spacing=2)

        self._order_panel = ft.Container(
            content=ft.Column([
                self._order_title,
                ft.Row([
                    ft.Container(
                        content=ft.Column([
                            ft.Text("💰 买单 (Buy)", size=13, weight=ft.FontWeight.BOLD, color="#00ff88"),
                            self._order_buy_list,
                        ], spacing=4, expand=True),
                        expand=True, padding=8,
                    ),
                    ft.VerticalDivider(width=1, color="#2a2a4a"),
                    ft.Container(
                        content=ft.Column([
                            ft.Text("📈 卖单 (Sell)", size=13, weight=ft.FontWeight.BOLD, color="#ff6b6b"),
                            self._order_sell_list,
                        ], spacing=4, expand=True),
                        expand=True, padding=8,
                    ),
                ], expand=True, spacing=0),
            ], spacing=4),
            bgcolor="#16213e",
            border=ft.border.all(1, "#2a2a4a"), border_radius=8,
            padding=8, visible=False,
        )

        # 实时候选列表
        self._suggestion_list = ft.Column(controls=[], spacing=0, scroll=ft.ScrollMode.AUTO)
        self._suggestion_container = ft.Container(
            content=self._suggestion_list,
            bgcolor="#16213e", border=ft.border.all(1, "#2a2a4a"), border_radius=8,
            padding=2, visible=False, left=20, right=20, top=62, height=0,
        )

        # 整体布局
        self.content = ft.Stack([
            ft.Column([
                self.search_bar,
                self._progress_bar,
                ft.Column([self._result_area, self._order_panel], expand=True, spacing=0),
            ], spacing=0, expand=True),
            self._suggestion_container,
        ], expand=True)

    def _build_header_cells(self):
        widths = [56, 60, 120, 160, 100, 130, 130, 80, 80]
        sort_key = getattr(self, '_sort_column', None)
        sort_asc = getattr(self, '_sort_asc', True)
        cells = []
        for i, key in enumerate(self._COLUMN_KEYS):
            sk = self._SORT_KEYS[i]
            label = key
            if sk and sk == sort_key:
                if sk == "avg_price":
                    label = "均价"
                label = f"{label} {'▲' if sort_asc else '▼'}"
            cell = ft.Container(
                content=ft.Text(label, size=12, weight=ft.FontWeight.BOLD, color="#e0e0e0", no_wrap=True),
                width=widths[i],
                bgcolor="#e9456040" if sk and sk == sort_key else "transparent",
            )
            if sk:
                cell.on_click = lambda e, col=sk: self._toggle_sort(col)
                cell.on_hover = lambda e, c=sk: (
                    setattr(e.control, 'bgcolor', '#e9456080' if e.data == 'true' else ('#e9456040' if c == getattr(self, '_sort_column', None) else 'transparent'))
                    or self._page.update()
                ) if c else None
            cells.append(cell)
        return cells

    def _show_progress(self):
        self._progress_bar.visible = True
        self._page.update()

    def _hide_progress(self):
        self._progress_bar.visible = False
        self._page.update()

    # ─── 单击复制，双击打开订单 ───
    _last_click_time = 0.0
    _last_click_type_id = None

    def _copy_price(self, text: str, type_id: int = None):
        now = _time.time()
        # 检测双击（同一物品 300ms 内第二次点击）
        if type_id and type_id == self._last_click_type_id and (now - self._last_click_time) < 0.3:
            self._last_click_time = 0.0
            self._on_row_click(type_id)
            return
        self._last_click_time = now
        self._last_click_type_id = type_id

        copy_text = text.split(" (")[0] if " (" in text else text
        try:
            pyperclip.copy(copy_text)
            self._status_text.value = f"已复制: {copy_text}"
        except Exception:
            try:
                self._page.set_clipboard(copy_text)
                self._status_text.value = f"已复制: {copy_text}"
            except Exception:
                self._status_text.value = f"点击复制: {copy_text}"
        self._page.update()

    # ─── 类别列表加载 ───
    async def _load_group_list(self):
        try:
            self._all_groups = await asyncio.get_event_loop().run_in_executor(None, self._db_load_groups)
        except Exception as e:
            print(f"加载类别列表失败: {e}")

    def _db_load_groups(self):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT DISTINCT e.group_id, e.en_group_name, e.zh_group_name "
            "FROM item e WHERE e.group_id IS NOT NULL "
            "ORDER BY e.zh_group_name, e.en_group_name"
        )
        rows = cursor.fetchall()
        conn.close()
        return rows

    # ─── 候选列表 ───
    def _on_search_input_change(self, e):
        query = e.control.value.strip()
        if len(query) >= 1:
            self._page.run_task(self._fetch_suggestions_async, query)
        else:
            self._hide_suggestions()

    async def _fetch_suggestions_async(self, query: str):
        try:
            rows = await asyncio.get_event_loop().run_in_executor(None, self._db_fetch_suggestions, query)
            suggestions = []
            for tid, en, zh in rows:
                zh_name = zh or en or str(tid)
                display = f"[{tid}] {zh or ''} ({en or ''})" if zh and en else f"[{tid}] {zh or en or 'Unknown'}"
                suggestions.append((tid, display, zh_name))
            if suggestions: self._show_suggestions(suggestions)
            else: self._hide_suggestions()
        except Exception:
            self._hide_suggestions()

    def _db_fetch_suggestions(self, query: str):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        if query.isdigit():
            # 数字搜索：先精确 ID 匹配，再按名称模糊搜索
            cursor.execute(
                "SELECT type_id, en_name, zh_name FROM item "
                "WHERE type_id = ? OR en_name LIKE ? OR zh_name LIKE ? "
                "ORDER BY "
                "  CASE WHEN type_id = ? THEN 0 ELSE 1 END, "
                "  CASE WHEN en_name LIKE ? THEN 0 WHEN zh_name LIKE ? THEN 1 ELSE 2 END, "
                "  LENGTH(en_name), type_id LIMIT 10",
                (int(query), f"%{query}%", f"%{query}%",
                 int(query), f"%{query}%", f"%{query}%")
            )
        else:
            cursor.execute(
                "SELECT type_id, en_name, zh_name FROM item "
                "WHERE en_name LIKE ? OR zh_name LIKE ? "
                "ORDER BY CASE WHEN en_name LIKE ? THEN 0 WHEN zh_name LIKE ? THEN 1 ELSE 2 END, LENGTH(en_name), type_id LIMIT 10",
                (f"%{query}%", f"%{query}%", f"%{query}%", f"%{query}%")
            )
        rows = cursor.fetchall()
        conn.close()
        return rows

    def _show_suggestions(self, suggestions: list):
        self._suggestion_list.controls.clear()
        for tid, display, zh_name in suggestions[:10]:
            btn = ft.Container(
                content=ft.Text(display, size=12, color="#e0e0e0", no_wrap=True),
                padding=ft.padding.symmetric(horizontal=10, vertical=4),
                bgcolor="transparent", border_radius=4,
                data={"type": "suggestion", "type_id": tid, "name": zh_name},
                on_click=lambda e, t=tid, n=zh_name: self._on_suggestion_click(t, n),
                on_hover=lambda e: setattr(e.control, 'bgcolor', '#0f3460' if e.data == 'true' else 'transparent') or self._page.update(),
            )
            self._suggestion_list.controls.append(btn)
        self._suggestion_container.height = min(len(suggestions), 10) * 28 + 8
        self._suggestion_container.visible = True
        self._page.update()

    def _hide_suggestions(self):
        self._suggestion_container.visible = False
        self._suggestion_list.controls.clear()
        self._page.update()

    def _on_suggestion_click(self, type_id: int, name: str = ""):
        self.search_input.value = name
        self._hide_suggestions()
        self._do_search()

    # ═══════════════════════════════
    # 搜索
    # ═══════════════════════════════
    # ─── 搜索历史 ───
    def _add_search_history(self, query: str):
        try:
            history = []
            if HISTORY_FILE.exists():
                history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
            history = [h for h in history if h.get("query") != query]
            history.insert(0, {"query": query, "time": _time.time()})
            if len(history) > MAX_HISTORY:
                history = history[:MAX_HISTORY]
            HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def _load_search_history(self) -> list:
        try:
            if HISTORY_FILE.exists():
                return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
        return []

    def _show_search_history(self):
        if self.search_input.value.strip():
            return
        self._suggestion_list.controls.clear()

        history = self._load_search_history()
        if not history:
            self._hide_suggestions()
            return

        title = ft.Container(
            content=ft.Text("🕐 最近搜索", size=11, color="#888888", weight=ft.FontWeight.BOLD),
            padding=ft.padding.symmetric(horizontal=10, vertical=6),
            bgcolor="#0f3460",
            border_radius=ft.border_radius.only(top_left=6, top_right=6),
        )
        self._suggestion_list.controls.append(title)

        for item in history[:8]:
            q = item["query"]
            btn = ft.Container(
                content=ft.Text(f"🔍  {q}", size=12, color="#e0e0e0", no_wrap=True),
                padding=ft.padding.symmetric(horizontal=10, vertical=4),
                bgcolor="transparent", border_radius=4,
                on_click=lambda e, t=q: self._on_history_click(t),
                on_hover=lambda e: setattr(e.control, 'bgcolor', '#0f3460' if e.data == 'true' else 'transparent') or self._page.update(),
            )
            self._suggestion_list.controls.append(btn)

        self._suggestion_container.height = min(len(history) + 1, 9) * 28 + 8
        self._suggestion_container.visible = True
        self._page.update()

    def _on_history_click(self, query: str):
        self.search_input.value = query
        self._hide_suggestions()
        self._do_search()

    def _do_search(self):
        query = self.search_input.value.strip()
        self._hide_suggestions()
        if not query:
            self._status_text.value = "请输入物品名称或 ID"
            self._page.update()
            return

        self._current_query = query
        self._hide_order_panel()
        self._show_progress()

        self._add_search_history(query)

        self._search_results = []
        self._result_list.controls.clear()
        self._result_list.update()
        self._page.update()

        self._page.run_task(self._do_search_async, query)

    async def _do_search_async(self, query: str):
        loop = asyncio.get_event_loop()
        try:
            rows = await loop.run_in_executor(None, self._db_execute_search, query)
            is_fallback = False
        except Exception as e:
            print(f"[ERROR] 完整搜索失败: {e}")
            try:
                rows = await loop.run_in_executor(None, self._db_search_basic, query)
                is_fallback = True
            except Exception as e2:
                print(f"[ERROR] 降级搜索也失败: {e2}")
                self._status_text.value = f"❌ 查询出错: {e2}"
                self._hide_progress()
                self._page.update()
                return

        if not rows:
            self._count_text.value = ""
            self._status_text.value = f"未找到包含「{query}」的物品"
            self.status_row.visible = True
            self._result_list.controls.clear()
            self._hide_progress()
            self._page.update()
            return

        # ── 构建可见行 ──
        widths = [56, 60, 120, 160, 100, 130, 130, 80, 80]
        self._search_results = []

        for idx, row in enumerate(rows):
            if is_fallback:
                tid, zh, en, zhg, eng, vol = row[:6]
                buy_p = None; sell_p = None; buy_v = 0; sell_v = 0
            else:
                tid, zh, en, en_group, zh_group, volume, buy_p, sell_p, buy_v, sell_v = row
                buy_v = buy_v or 0; sell_v = sell_v or 0
                vol = volume or 0.0

            group = (zh_group or en_group or "—") if not is_fallback else (zhg or eng or "—")

            buy_str = "—"
            if buy_p is not None and buy_v > 0:
                buy_str = f"{buy_p:,.2f} ({buy_v:,})"
            elif buy_p is not None:
                buy_str = f"{buy_p:,.2f}"

            sell_str = "—"
            if sell_p is not None and sell_v > 0:
                sell_str = f"{sell_p:,.2f} ({sell_v:,})"
            elif sell_p is not None:
                sell_str = f"{sell_p:,.2f}"

            vol_str = f"{vol:,.2f}" if vol > 0 else "—"

            avg_price_str = "—"
            avg_price_val = 0.0
            if buy_p is not None and sell_p is not None:
                avg_price_val = (buy_p + sell_p) / 2
                avg_price_str = f"{avg_price_val:,.2f}"
            elif buy_p is not None:
                avg_price_val = buy_p
                avg_price_str = f"{buy_p:,.2f}"
            elif sell_p is not None:
                avg_price_val = sell_p
                avg_price_str = f"{sell_p:,.2f}"

            is_inverted = buy_p is not None and sell_p is not None and buy_p > sell_p

            buy_val = buy_p if buy_p is not None else 0.0
            sell_val = sell_p if sell_p is not None else 0.0

            row_data = {
                "type_id": tid, "zh": zh or "", "en": en or "", "group": group,
                "buy_str": buy_str, "sell_str": sell_str,
                "buy_val": buy_val, "sell_val": sell_val,
                "avg_price_str": avg_price_str, "avg_price_val": avg_price_val,
                "vol_str": vol_str, "vol_val": vol,
                "is_inverted": is_inverted,
            }
            self._search_results.append(row_data)

            raw_values = [
                str(tid), zh or "", en or "", group,
                buy_str.split(" (")[0] if " (" in buy_str else buy_str,
                sell_str.split(" (")[0] if " (" in sell_str else sell_str,
                avg_price_str, vol_str,
            ]

            avg_color = "#00ff88" if avg_price_str != "—" else "#888888"

            cell_widgets = [
                # 图标
                ft.Container(
                    content=ft.Image(src=str(Path(ICON_DIR) / f"{tid}.png"), width=ICON_SIZE, height=ICON_SIZE, fit="contain") if (Path(ICON_DIR) / f"{tid}.png").exists() else ft.Text("?", size=20, color="#888888"),
                    width=widths[0], height=ICON_SIZE+4,
                    alignment=ft.alignment.Alignment(0, 0),
                ),
                # ID
                ft.Container(ft.Text(str(tid), size=11, color="#888888", font_family=MONO_FONT), width=widths[1],
                    on_click=lambda e, t=raw_values[0], tid=tid: self._copy_price(t, tid)),
                # 中文名
                ft.Container(ft.Text(zh or "", size=12, color="#e0e0e0"), width=widths[2],
                    on_click=lambda e, t=raw_values[1], tid=tid: self._copy_price(t, tid)),
                # 英文名
                ft.Container(ft.Text(en or "", size=11, color="#aaaaaa"), width=widths[3],
                    on_click=lambda e, t=raw_values[2], tid=tid: self._copy_price(t, tid)),
                # 类别
                ft.Container(ft.Text(group, size=11, color="#888888"), width=widths[4],
                    on_click=lambda e, t=raw_values[3], tid=tid: self._copy_price(t, tid)),
                # 买单
                ft.Container(
                    content=ft.Text(buy_str, size=12, color="#00ff88" if buy_str != "—" else "#888888", font_family=MONO_FONT),
                    width=widths[5], on_click=lambda e, t=raw_values[4], tid=tid: self._copy_price(t, tid),
                ),
                # 卖单
                ft.Container(
                    content=ft.Text(sell_str, size=12, color="#ff6b6b" if sell_str != "—" else "#888888", font_family=MONO_FONT),
                    width=widths[6], on_click=lambda e, t=raw_values[5], tid=tid: self._copy_price(t, tid),
                ),
                # 均价
                ft.Container(
                    content=ft.Text(avg_price_str, size=12, color=avg_color, font_family=MONO_FONT),
                    width=widths[7], on_click=lambda e, t=raw_values[6], tid=tid: self._copy_price(t, tid),
                ),
                # 体积
                ft.Container(ft.Text(vol_str, size=11, color="#888888", font_family=MONO_FONT), width=widths[8],
                    on_click=lambda e, t=raw_values[7], tid=tid: self._copy_price(t, tid)),
            ]

            row_bg = "#1f1f3f" if is_inverted else ("#16213e" if idx % 2 == 0 else "#1a1a2e")

            # 右键菜单
            row_menu = ft.PopupMenuButton(
                items=[
                    ft.PopupMenuItem(content=ft.Text("🛒 添加到购物车（待实现）"), disabled=True),
                    ft.PopupMenuItem(content=ft.Text("🔧 查看制造所需物品（待实现）"), disabled=True),
                    ft.PopupMenuItem(content=ft.Text("🔄 更新价格（待实现）"), disabled=True),
                ],
            )

            row_ctrl = ft.Container(
                content=ft.Row([
                    *cell_widgets,
                    row_menu,
                ], spacing=12),
                bgcolor=row_bg,
                padding=ft.padding.symmetric(horizontal=12, vertical=6),
                border_radius=4,
                on_long_press=lambda e: setattr(row_menu, 'open', True) or self._page.update(),
                data={"type_id": tid},
            )

            self._result_list.controls.append(row_ctrl)

        self._count_text.value = f"共 {len(rows)} 条结果" + (" (仅基本信息)" if is_fallback else "")
        self._status_text.value = "⚠ 无价格数据" if is_fallback else "单击行查看深度买/卖单"
        self.status_row.visible = True

        self._hide_progress()
        self._result_list.update()
        self._page.update()

    def _db_execute_search(self, query: str):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        like_pattern = f"%{query}%"

        # 检查是否有匹配的类别名
        group_match = None
        for gid, en, zh in self._all_groups:
            if (zh and str(query) in zh) or (en and str(query) in en):
                group_match = gid
                break

        # 搜索逻辑：数字 → 先精确 ID 匹配，再按名称包含匹配
        if query.isdigit():
            # 先尝试精确 ID 匹配，同时用名称搜索匹配 ID 的数字
            cursor.execute(f"""
                SELECT i.type_id, i.zh_name, i.en_name, i.en_group_name, i.zh_group_name, i.volume,
                       mp.buy_price, mp.sell_price, mp.buy_volume, mp.sell_volume
                FROM item i
                LEFT JOIN market_prices mp ON i.type_id = mp.type_id
                    AND mp.fetch_time = (SELECT MAX(mp2.fetch_time) FROM market_prices mp2 WHERE mp2.type_id = i.type_id)
                WHERE i.type_id = ? OR i.en_name LIKE ? OR i.zh_name LIKE ?
                ORDER BY i.type_id LIMIT 300
            """, (int(query), like_pattern, like_pattern))
        else:
            if group_match is not None:
                cursor.execute(f"""
                    SELECT sub.type_id, sub.zh_name, sub.en_name, sub.en_group_name, sub.zh_group_name, sub.volume,
                           mp.buy_price, mp.sell_price, mp.buy_volume, mp.sell_volume
                    FROM (
                        SELECT i.type_id, i.zh_name, i.en_name, i.en_group_name, i.zh_group_name, i.volume
                        FROM item i
                        WHERE i.group_id = ?
                        UNION
                        SELECT i.type_id, i.zh_name, i.en_name, i.en_group_name, i.zh_group_name, i.volume
                        FROM item i
                        WHERE (i.en_name LIKE ? OR i.zh_name LIKE ?)
                    ) sub
                    LEFT JOIN market_prices mp ON sub.type_id = mp.type_id
                        AND mp.fetch_time = (SELECT MAX(mp2.fetch_time) FROM market_prices mp2 WHERE mp2.type_id = sub.type_id)
                    ORDER BY sub.type_id LIMIT 300
                """, (group_match, like_pattern, like_pattern))
            else:
                cursor.execute(f"""
                    SELECT i.type_id, i.zh_name, i.en_name, i.en_group_name, i.zh_group_name, i.volume,
                           mp.buy_price, mp.sell_price, mp.buy_volume, mp.sell_volume
                    FROM item i
                    LEFT JOIN market_prices mp ON i.type_id = mp.type_id
                        AND mp.fetch_time = (SELECT MAX(mp2.fetch_time) FROM market_prices mp2 WHERE mp2.type_id = i.type_id)
                    WHERE i.en_name LIKE ? OR i.zh_name LIKE ?
                    ORDER BY i.type_id LIMIT 300
                """, (like_pattern, like_pattern))
        rows = cursor.fetchall()
        conn.close()
        return rows

    def _db_search_basic(self, query: str):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        if query.isdigit():
            cursor.execute("SELECT type_id, zh_name, en_name, zh_group_name, en_group_name, volume FROM item WHERE type_id = ?", (int(query),))
        else:
            cursor.execute("SELECT type_id, zh_name, en_name, zh_group_name, en_group_name, volume FROM item WHERE en_name LIKE ? OR zh_name LIKE ? LIMIT 100", (f"%{query}%", f"%{query}%"))
        rows = cursor.fetchall()
        conn.close()
        return rows

    # ─── 排序（快速重排控件，不重建） ───
    def _toggle_sort(self, column_key: str):
        if column_key is None:
            return
        current = getattr(self, '_sort_column', None)
        if current != column_key:
            self._sort_column = column_key
            self._sort_asc = True
        elif self._sort_asc:
            self._sort_asc = False
        else:
            self._sort_column = None
            self._sort_asc = True
        self._apply_sort()

    def _apply_sort(self):
        if not self._search_results or not self._result_list.controls:
            return
        col = getattr(self, '_sort_column', None)
        asc = getattr(self, '_sort_asc', True)

        # 更新表头
        self._header_row.content = ft.Row(
            controls=self._build_header_cells(),
            spacing=12,
        )
        self._header_row.update()

        if not col:
            # 取消排序 → 恢复原始顺序（按 _search_results 原序重排）
            # 直接显示原顺序
            self._result_list.update()
            self._page.update()
            return

        # 构建 (index, sort_key) 列表，对 indices 排序
        key_map = {
            "type_id": ("type_id", True),
            "zh": ("zh", False),
            "en": ("en", False),
            "group": ("group", False),
            "buy_price": ("buy_val", True),
            "sell_price": ("sell_val", True),
            "avg_price": ("avg_price_val", True),
            "vol_val": ("vol_val", True),
        }
        field, is_numeric = key_map.get(col, (col, False))
        reverse = not asc

        if is_numeric:
            results_sorted = sorted(
                enumerate(self._search_results),
                key=lambda x: x[1].get(field, 0) if x[1].get(field) else 0,
                reverse=reverse
            )
        else:
            results_sorted = sorted(
                enumerate(self._search_results),
                key=lambda x: (x[1].get(field) or "").lower(),
                reverse=reverse
            )

        # 重排控件（不移除/重建，只改变顺序）
        self._result_list.controls[:] = [self._result_list.controls[idx] for idx, _ in results_sorted]
        self._result_list.update()
        self._page.update()

    def _clear_search(self):
        self.search_input.value = ""
        self._current_query = ""
        self._result_list.controls.clear()
        self._search_results = []
        self._count_text.value = ""
        self._status_text.value = "已清空"
        self.status_row.visible = True
        self._hide_order_panel()
        self._hide_suggestions()
        self._result_list.update()
        self._page.update()

    # ─── 行交互 ───
    def _on_row_click(self, type_id: int):
        if self._order_panel_visible and self._current_order_type_id == type_id:
            self._hide_order_panel()
            return

        name = str(type_id)
        for row in self._search_results:
            if row["type_id"] == type_id:
                name = f"{row['zh']} ({row['en']})" if row['zh'] and row['en'] else (row['zh'] or row['en'] or str(type_id))
                break

        self._current_order_type_id = type_id
        self._order_title.value = f"📋 {name}  (Type ID: {type_id})"
        self._order_panel.visible = True
        self._order_buy_list.controls.clear()
        self._order_sell_list.controls.clear()

        # 检查缓存
        cached = self._order_cache.get(type_id)
        if cached:
            buy_orders, sell_orders, fetch_time = cached
            if _time.time() - fetch_time < 300:  # 5 分钟 = 300 秒
                self._display_orders(buy_orders, sell_orders)
                self._status_text.value = "订单数据已加载（缓存） ✓"
                self._page.update()
                return

        self._status_text.value = "正在从 ESI 获取实时订单数据..."
        self._page.update()
        self._page.run_task(self._fetch_and_show_orders, type_id)

    def _hide_order_panel(self):
        self._order_panel.visible = False
        self._current_order_type_id = None
        self._order_panel_visible = False
        self._status_text.value = "单击行查看深度买/卖单"
        self._page.update()

    def _display_orders(self, buy_orders: list, sell_orders: list):
        self._order_panel_visible = True

        buy_items = []
        if buy_orders:
            for i, order in enumerate(buy_orders):
                price = f"{order['price']:,.2f}"
                vol = f"{order['volume_remain']:,}"
                loc_id = order["location_id"]
                station_name = _station_name_cache.get(loc_id, str(loc_id))
                buy_items.append(ft.Container(
                    content=ft.Row([
                        ft.Text(str(i+1), size=11, color="#00ff88", width=30),
                        ft.Text(price, size=11, color="#00ff88", font_family=MONO_FONT, width=120),
                        ft.Text(vol, size=11, color="#00ff88", font_family=MONO_FONT, width=80),
                        ft.Text(f"{station_name} [{loc_id}]", size=10, color="#aaaaaa", width=180),
                    ]),
                    bgcolor="#0f3460" if i%2==0 else "#16213e",
                    padding=ft.padding.symmetric(horizontal=8, vertical=4),
                ))
        else:
            buy_items.append(ft.Container(ft.Text("无买单数据", size=11, color="#888888"), padding=10))
        self._order_buy_list.controls = buy_items

        sell_items = []
        if sell_orders:
            for i, order in enumerate(sell_orders):
                price = f"{order['price']:,.2f}"
                vol = f"{order['volume_remain']:,}"
                loc_id = order["location_id"]
                station_name = _station_name_cache.get(loc_id, str(loc_id))
                sell_items.append(ft.Container(
                    content=ft.Row([
                        ft.Text(str(i+1), size=11, color="#ff6b6b", width=30),
                        ft.Text(price, size=11, color="#ff6b6b", font_family=MONO_FONT, width=120),
                        ft.Text(vol, size=11, color="#ff6b6b", font_family=MONO_FONT, width=80),
                        ft.Text(f"{station_name} [{loc_id}]", size=10, color="#aaaaaa", width=180),
                    ]),
                    bgcolor="#0f3460" if i%2==0 else "#16213e",
                    padding=ft.padding.symmetric(horizontal=8, vertical=4),
                ))
        else:
            sell_items.append(ft.Container(ft.Text("无卖单数据", size=11, color="#888888"), padding=10))
        self._order_sell_list.controls = sell_items

        self._order_buy_list.update()
        self._order_sell_list.update()

    async def _fetch_and_show_orders(self, type_id: int):
        try:
            buy_orders, sell_orders = await self._fetch_orders_from_esi(type_id)
            # 写入缓存
            self._order_cache[type_id] = (buy_orders, sell_orders, _time.time())
            self._display_orders(buy_orders, sell_orders)
            self._status_text.value = "实时订单数据已加载 ✓  单击行再次展开/收起"
            self._page.update()
        except Exception as e:
            self._status_text.value = f"❌ 获取订单失败: {e}"
            self._page.update()

    async def _fetch_orders_from_esi(self, type_id: int):
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(
            headers={"Accept": "application/json", "User-Agent": "EveDataCrawler/1.0"}, timeout=timeout
        ) as session:
            url = f"{ESI_BASE_URL}/markets/{REGION_ID}/orders/"
            async with session.get(url, params={"type_id": type_id, "order_type": "buy"}) as resp:
                resp.raise_for_status(); buy_data = await resp.json()
            async with session.get(url, params={"type_id": type_id, "order_type": "sell"}) as resp:
                resp.raise_for_status(); sell_data = await resp.json()

        buy_orders = sorted(buy_data, key=lambda o: o["price"], reverse=True)[:5]
        sell_orders = sorted(sell_data, key=lambda o: o["price"])[:5]

        all_loc_ids = set()
        for o in buy_orders + sell_orders: all_loc_ids.add(o["location_id"])
        await _resolve_names(list(all_loc_ids))
        return buy_orders, sell_orders

    def refresh_display(self):
        if self._current_query:
            self._do_search()
        else:
            self._status_text.value = "就绪 — 价格数据已更新"
            self._page.update()
