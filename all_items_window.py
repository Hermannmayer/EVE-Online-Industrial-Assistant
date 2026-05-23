"""
全物品查询 — 独立窗口
用法: python all_items_window.py
"""
import flet as ft
import sqlite3
import asyncio
import concurrent.futures
from typing import Optional
from ui.config import DB_PATH, MONO_FONT


class AllItemsUI:
    """全物品查询 UI — 左侧市场分类树 + 右侧物品表格"""

    _COL_LABELS = ["ID", "中文名称", "英文名称", "最高价", "最低价", "平均价", "体积 m³"]
    _SORT_KEYS = ["type_id", "zh_name", "en_name", "sell_price", "buy_price", "avg_price", "volume"]
    _COL_WIDTHS = [60, 140, 180, 100, 100, 90, 80]

    def __init__(self, page: ft.Page):
        self._page = page

        # Tree state
        self._tree_data: list = []
        self._children_map: dict = {}
        self._expanded_nodes: set = set()
        self._selected_mg_id: Optional[int] = None

        # Item state
        self._item_results: list = []
        self._sort_column: Optional[str] = None
        self._sort_asc: bool = True

        # Concurrency
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        self._latest_request_id: int = 0
        self._last_queried_mg_id: Optional[int] = None

        # Price auto-refresh
        self._last_price_time: Optional[str] = None

        self._build_ui()
        self._page.run_task(self._load_tree)
        self._page.run_task(self._auto_refresh_prices)

    # ═══════════════════════════════════════════
    #  UI construction
    # ═══════════════════════════════════════════

    def _build_ui(self):
        # Left panel — tree
        self._tree_progress = ft.ProgressBar(height=3, color="#e94560", bgcolor="#2a2a4a", visible=False)
        self._tree_list = ft.ListView(expand=True, spacing=0,
                                      padding=ft.padding.Padding(left=0, top=0, right=0, bottom=0))
        self._tree_empty = ft.Text("", size=12, color="#888888")

        left_panel = ft.Container(
            content=ft.Column([
                ft.Container(
                    content=ft.Text("市场分类", size=13, weight=ft.FontWeight.BOLD, color="#e0e0e0"),
                    padding=ft.padding.Padding(left=12, top=10, right=0, bottom=6),
                ),
                self._tree_progress,
                self._tree_list,
                self._tree_empty,
            ], spacing=0, expand=True),
            width=280,
            bgcolor="#16213e",
            border=ft.Border(right=ft.BorderSide(1, "#2a2a4a")),
            padding=ft.padding.Padding(left=0, top=0, right=0, bottom=0),
        )

        # Right panel — item table
        self._item_count_text = ft.Text("", size=11, color="#888888")
        self._item_status_text = ft.Text("点击左侧分类筛选物品", size=11, color="#888888")
        self._item_progress = ft.ProgressBar(height=3, color="#e94560", bgcolor="#2a2a4a", visible=False)
        self._header_row = ft.Container(
            content=ft.Row(controls=self._build_header_cells(), spacing=12),
            bgcolor="#0f3460",
            padding=ft.padding.Padding(left=12, top=8, right=12, bottom=8),
            border=ft.Border(bottom=ft.BorderSide(1, "#2a2a4a")),
        )
        self._item_list = ft.ListView(controls=[], expand=True, spacing=1,
                                      padding=ft.padding.Padding(left=8, top=4, right=8, bottom=4))

        right_panel = ft.Container(
            content=ft.Column([
                ft.Row([self._item_count_text, self._item_status_text],
                       alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                self._item_progress,
                self._header_row,
                self._item_list,
            ], spacing=2, expand=True),
            expand=True,
            padding=ft.padding.Padding(left=10, top=6, right=10, bottom=6),
        )

        # Pin button in title bar area
        self._pin_btn = ft.IconButton(
            icon=ft.icons.Icons.PUSH_PIN,
            icon_color="#888888",
            icon_size=18,
            tooltip="置顶",
            on_click=self._toggle_pin,
        )

        # Build page content
        self._page.add(
            ft.Column([
                # Title bar
                ft.Container(
                    content=ft.Row([
                        ft.Icon(ft.icons.Icons.CATEGORY, color="#e94560", size=18),
                        ft.Text("全物品查询", size=14, weight=ft.FontWeight.BOLD, color="#e0e0e0"),
                        ft.Container(expand=True),
                        self._pin_btn,
                    ], spacing=8),
                    bgcolor="#16213e",
                    padding=ft.padding.Padding(left=16, top=8, right=8, bottom=8),
                    border=ft.Border(bottom=ft.BorderSide(1, "#2a2a4a")),
                ),
                # Content
                ft.Row([
                    left_panel,
                    ft.VerticalDivider(width=1, color="#2a2a4a"),
                    right_panel,
                ], spacing=0, expand=True),
            ], spacing=0, expand=True)
        )

    def _build_header_cells(self):
        sort_key = self._sort_column
        sort_asc = self._sort_asc
        cells = []
        for i, label in enumerate(self._COL_LABELS):
            sk = self._SORT_KEYS[i]
            if sk and sk == sort_key:
                label = f"{label} {'▲' if sort_asc else '▼'}"
            cell = ft.Container(
                content=ft.Text(label, size=12, weight=ft.FontWeight.BOLD,
                                color="#e0e0e0", no_wrap=True),
                width=self._COL_WIDTHS[i],
                bgcolor="#e9456040" if sk and sk == sort_key else "transparent",
            )
            if sk:
                cell.on_click = lambda e, col=sk: self._toggle_sort(col)
            cells.append(cell)
        return cells

    # ═══════════════════════════════════════════
    #  Pin toggle
    # ═══════════════════════════════════════════

    def _toggle_pin(self, e):
        try:
            current = self._page.window.always_on_top
            self._page.window.always_on_top = not current
            self._pin_btn.icon_color = "#e94560" if not current else "#888888"
            self._pin_btn.update()
        except Exception:
            pass

    # ═══════════════════════════════════════════
    #  Tree: load
    # ═══════════════════════════════════════════

    async def _load_tree(self):
        self._tree_progress.visible = True
        self._tree_progress.update()

        loop = asyncio.get_event_loop()
        try:
            self._tree_data = await loop.run_in_executor(None, self._db_load_tree)
            self._build_children_map()
            if self._tree_data:
                self._render_tree()
                self._page.run_task(self._load_items_async, None)
            else:
                self._tree_empty.value = "市场分类数据未加载，请先完成数据初始化"
                self._tree_empty.update()
        except Exception as ex:
            self._tree_empty.value = f"加载失败: {ex}"
            self._tree_empty.update()
        finally:
            self._tree_progress.visible = False
            self._tree_progress.update()

    def _db_load_tree(self):
        conn = sqlite3.connect(DB_PATH)
        try:
            c = conn.cursor()
            c.execute("SELECT market_group_id, parent_group_id, en_name, zh_name "
                      "FROM market_tree ORDER BY parent_group_id, zh_name, en_name")
            return c.fetchall()
        finally:
            conn.close()

    def _build_children_map(self):
        self._children_map.clear()
        for row in self._tree_data:
            mg_id, parent_id = row[0], row[1]
            self._children_map.setdefault(parent_id, []).append(row)

    # ═══════════════════════════════════════════
    #  Tree: render
    # ═══════════════════════════════════════════

    def _render_tree(self):
        def dfs(parent_id, depth):
            nodes = []
            for row in self._children_map.get(parent_id, []):
                mg_id = row[0]
                has_children = mg_id in self._children_map
                is_expanded = mg_id in self._expanded_nodes
                nodes.append((depth, is_expanded, has_children, row))
                if is_expanded and has_children:
                    nodes.extend(dfs(mg_id, depth + 1))
            return nodes

        flat = dfs(None, 0)
        controls = []
        for depth, is_expanded, has_children, row in flat:
            mg_id, _, en_name, zh_name = row
            label = zh_name or en_name or str(mg_id)
            is_sel = mg_id == self._selected_mg_id

            if has_children:
                icon = ft.icons.Icons.FOLDER_OPEN if is_expanded else ft.icons.Icons.FOLDER
                icon_color = "#e94560" if is_expanded else "#aaaaaa"
            else:
                icon = ft.icons.Icons.ARTICLE
                icon_color = "#888888"

            row_ctrl = ft.Container(
                content=ft.Row([
                    ft.Container(width=depth * 20),
                    ft.Icon(icon, color=icon_color, size=16),
                    ft.Text(label, size=12, color="#e94560" if is_sel else "#e0e0e0",
                            weight=ft.FontWeight.BOLD if is_sel else ft.FontWeight.NORMAL,
                            expand=True, no_wrap=True),
                ], spacing=4),
                padding=ft.padding.Padding(left=8, top=4, right=8, bottom=4),
                bgcolor="#e9456040" if is_sel else "transparent",
                border_radius=4,
                on_click=lambda e, gid=mg_id: self._on_tree_node_click(gid),
            )
            controls.append(row_ctrl)

        self._tree_list.controls = controls
        self._tree_list.update()

    # ═══════════════════════════════════════════
    #  Tree: interaction
    # ═══════════════════════════════════════════

    def _on_tree_node_click(self, mg_id: int):
        has_children = mg_id in self._children_map
        if has_children:
            if mg_id in self._expanded_nodes:
                self._expanded_nodes.discard(mg_id)
            else:
                self._expanded_nodes.add(mg_id)

        if self._selected_mg_id == mg_id:
            self._selected_mg_id = None
        else:
            self._selected_mg_id = mg_id

        self._render_tree()
        self._page.run_task(self._load_items_async, self._selected_mg_id)

    # ═══════════════════════════════════════════
    #  Items: load
    # ═══════════════════════════════════════════

    async def _load_items_async(self, mg_id: Optional[int]):
        self._latest_request_id += 1
        request_id = self._latest_request_id

        self._item_progress.visible = True
        self._item_count_text.value = ""
        self._item_status_text.value = "加载中..."
        self._item_progress.update()
        self._item_count_text.update()
        self._item_status_text.update()

        if mg_id == self._last_queried_mg_id and self._item_results:
            self._item_progress.visible = False
            self._item_count_text.value = f"共 {len(self._item_results)} 个物品"
            self._item_status_text.value = "已加载（缓存）"
            self._page.update()
            return

        loop = asyncio.get_event_loop()
        try:
            if mg_id is not None:
                mg_ids = await loop.run_in_executor(None, self._get_descendant_ids, mg_id)
            else:
                mg_ids = None

            if mg_ids is not None and not mg_ids:
                self._item_results = []
                self._render_items()
                self._item_count_text.value = "共 0 个物品"
                self._item_status_text.value = "该分类下无物品"
                self._item_progress.visible = False
                self._page.update()
                return

            rows = await loop.run_in_executor(
                None, self._fetch_items_sync, mg_ids,
                self._sort_column, self._sort_asc,
            )
            if request_id != self._latest_request_id:
                return

            self._item_results = self._build_row_data(rows)
            self._last_queried_mg_id = mg_id
            self._render_items()

            truncated = mg_ids is not None and len(self._item_results) >= 300
            self._item_status_text.value = "结果已截断（最多300条）" if truncated else ""
            self._item_count_text.value = f"共 {len(self._item_results)} 个物品"

        except Exception as ex:
            self._item_status_text.value = f"查询失败: {ex}"
            self._item_count_text.value = ""
            self._item_list.controls.clear()
        finally:
            self._item_progress.visible = False
            self._page.update()

    def _get_descendant_ids(self, mg_id: int):
        ids = [mg_id]
        stack = [mg_id]
        while stack:
            parent = stack.pop()
            for child in self._children_map.get(parent, []):
                child_id = child[0]
                ids.append(child_id)
                if child_id in self._children_map:
                    stack.append(child_id)
        return ids

    def _fetch_items_sync(self, mg_ids, sort_col, sort_asc):
        conn = sqlite3.connect(DB_PATH)
        try:
            c = conn.cursor()
            col_map = {
                "type_id": "i.type_id",
                "zh_name": "i.zh_name",
                "en_name": "i.en_name",
                "sell_price": "mp.sell_price",
                "buy_price": "mp.buy_price",
                "avg_price": "(mp.buy_price + mp.sell_price) / 2.0",
                "volume": "i.volume",
            }
            order_expr = col_map.get(sort_col, "i.type_id")
            direction = "ASC" if sort_asc else "DESC"

            sql = (
                "SELECT i.type_id, i.zh_name, i.en_name, i.volume, "
                "       mp.buy_price, mp.sell_price "
                "FROM item i "
                "LEFT JOIN market_prices mp ON i.type_id = mp.type_id "
                "  AND mp.fetch_time = ("
                "    SELECT MAX(mp2.fetch_time) FROM market_prices mp2 "
                "    WHERE mp2.type_id = i.type_id"
                "  ) "
            )
            params = []
            if mg_ids is not None:
                placeholders = ",".join("?" * len(mg_ids))
                sql += f"WHERE i.market_group_id IN ({placeholders}) "
                params.extend(mg_ids)
            sql += f"ORDER BY {order_expr} {direction} LIMIT 300"

            c.execute(sql, params)
            return c.fetchall()
        finally:
            conn.close()

    def _build_row_data(self, rows):
        results = []
        for tid, zh, en, vol, buy_p, sell_p in rows:
            vol = vol or 0.0
            sell_str = f"{sell_p:,.2f}" if sell_p is not None else "—"
            sell_val = sell_p or 0.0
            buy_str = f"{buy_p:,.2f}" if buy_p is not None else "—"
            buy_val = buy_p or 0.0
            avg_val = 0.0
            avg_str = "—"
            if buy_p is not None and sell_p is not None:
                avg_val = (buy_p + sell_p) / 2
                avg_str = f"{avg_val:,.2f}"
            elif buy_p is not None:
                avg_val = buy_p
                avg_str = f"{buy_p:,.2f}"
            elif sell_p is not None:
                avg_val = sell_p
                avg_str = f"{sell_p:,.2f}"
            vol_str = f"{vol:,.2f}" if vol > 0 else "—"
            results.append({
                "type_id": tid,
                "zh_name": zh or "",
                "en_name": en or "",
                "sell_str": sell_str, "sell_val": sell_val,
                "buy_str": buy_str, "buy_val": buy_val,
                "avg_str": avg_str, "avg_val": avg_val,
                "vol_str": vol_str, "vol_val": vol,
            })
        return results

    # ═══════════════════════════════════════════
    #  Items: render (flat Row, no nested Containers)
    # ═══════════════════════════════════════════

    def _render_items(self):
        controls = []
        for i, row in enumerate(self._item_results):
            bg = "#1e1e3a" if i % 2 == 0 else "transparent"
            tid = row["type_id"]
            row_ctrl = ft.Container(
                content=ft.Row([
                    ft.Text(str(tid), width=self._COL_WIDTHS[0], size=11,
                            color="#888888", font_family=MONO_FONT),
                    ft.Text(row["zh_name"], width=self._COL_WIDTHS[1], size=12,
                            color="#e0e0e0", no_wrap=True),
                    ft.Text(row["en_name"], width=self._COL_WIDTHS[2], size=11,
                            color="#aaaaaa", no_wrap=True),
                    ft.Text(row["sell_str"], width=self._COL_WIDTHS[3], size=12,
                            color="#ff6b6b", font_family=MONO_FONT),
                    ft.Text(row["buy_str"], width=self._COL_WIDTHS[4], size=12,
                            color="#00ff88", font_family=MONO_FONT),
                    ft.Text(row["avg_str"], width=self._COL_WIDTHS[5], size=12,
                            color="#ffcc00", font_family=MONO_FONT),
                    ft.Text(row["vol_str"], width=self._COL_WIDTHS[6], size=12,
                            color="#e0e0e0", font_family=MONO_FONT),
                ], spacing=12),
                padding=ft.padding.Padding(left=12, top=4, right=12, bottom=4),
                bgcolor=bg,
                border_radius=4,
                on_click=lambda e, t=tid: self._copy_id(t),
            )
            controls.append(row_ctrl)

        self._item_list.controls = controls
        self._item_list.update()

    # ═══════════════════════════════════════════
    #  Copy to clipboard
    # ═══════════════════════════════════════════

    def _copy_id(self, type_id: int):
        try:
            import pyperclip
            pyperclip.copy(str(type_id))
        except Exception:
            try:
                self._page.set_clipboard(str(type_id))
            except Exception:
                pass
        self._item_status_text.value = f"已复制: {type_id}"
        self._item_status_text.update()

    # ═══════════════════════════════════════════
    #  Sorting
    # ═══════════════════════════════════════════

    def _toggle_sort(self, column_key: str):
        if self._sort_column != column_key:
            self._sort_column = column_key
            self._sort_asc = True
        elif self._sort_asc:
            self._sort_asc = False
        else:
            self._sort_column = None
            self._sort_asc = True
        self._apply_sort()

    def _apply_sort(self):
        if not self._item_results or not self._item_list.controls:
            return

        self._header_row.content = ft.Row(controls=self._build_header_cells(), spacing=12)
        self._header_row.update()

        col = self._sort_column
        asc = self._sort_asc

        if not col:
            self._render_items()
            self._page.update()
            return

        key_map = {
            "type_id": ("type_id", True),
            "zh_name": ("zh_name", False),
            "en_name": ("en_name", False),
            "sell_price": ("sell_val", True),
            "buy_price": ("buy_val", True),
            "avg_price": ("avg_val", True),
            "volume": ("vol_val", True),
        }
        field, is_numeric = key_map.get(col, (col, False))
        reverse = not asc

        if is_numeric:
            results_sorted = sorted(
                enumerate(self._item_results),
                key=lambda x: x[1].get(field, 0) or 0,
                reverse=reverse,
            )
        else:
            results_sorted = sorted(
                enumerate(self._item_results),
                key=lambda x: (x[1].get(field) or "").lower(),
                reverse=reverse,
            )

        self._item_list.controls[:] = [self._item_list.controls[idx] for idx, _ in results_sorted]
        self._item_list.update()
        self._page.update()

    # ═══════════════════════════════════════════
    #  Price auto-refresh
    # ═══════════════════════════════════════════

    async def _auto_refresh_prices(self):
        while True:
            await asyncio.sleep(30)
            try:
                loop = asyncio.get_event_loop()
                latest = await loop.run_in_executor(None, self._db_get_latest_price_time)
                if latest is None:
                    continue
                if self._last_price_time is None:
                    self._last_price_time = latest
                    continue
                if latest != self._last_price_time:
                    self._last_price_time = latest
                    if self._item_results:
                        self._last_queried_mg_id = None
                        self._page.run_task(self._load_items_async, self._selected_mg_id)
            except Exception:
                pass

    def _db_get_latest_price_time(self):
        conn = sqlite3.connect(DB_PATH)
        try:
            c = conn.cursor()
            c.execute("SELECT MAX(fetch_time) FROM market_prices")
            row = c.fetchone()
            return row[0] if row else None
        finally:
            conn.close()


def main(page: ft.Page):
    page.title = "全物品查询"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = "#1a1a2e"
    page.padding = 0
    page.spacing = 0
    page.window.min_width = 1100
    page.window.min_height = 650
    page.window.always_on_top = False

    AllItemsUI(page)


if __name__ == "__main__":
    ft.run(main)
