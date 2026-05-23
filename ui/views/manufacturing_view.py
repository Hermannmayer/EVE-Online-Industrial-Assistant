"""
制造 / 工业页面 — Flet 实现

子页面：估价与精炼、制造业（成本计算器）、行星工业、忠诚点价值
"""
import flet as ft
import sqlite3
import asyncio
import concurrent.futures
from typing import Optional
from ui.config import DB_PATH, CJK_FONT, MONO_FONT


class IndustryPage(ft.Container):
    """制造/工业页面容器 — 带二级导航标签"""

    def __init__(self, page: ft.Page):
        super().__init__()
        self._page = page
        self.expand = True
        self.bgcolor = "#1a1a2e"
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

        # Calculator state
        self._blueprint_results: list[dict] = []
        self._selected_bp: Optional[dict] = None
        self._materials: list[dict] = []
        self._products: list[dict] = []
        self._bp_skills: list[dict] = []
        self._user_skills: dict[int, int] = {}
        self._bp_time: int = 0
        self._price_source: str = "buy"
        self._activity: str = "manufacturing"
        self._selected_system_cost: float = 0.0

        # Build UI
        self._build_ui()

        # Load user skills
        self._page.run_task(self._load_user_skills)

    # ─────────────────────────────
    #  UI
    # ─────────────────────────────

    def _build_ui(self):
        sub_tabs = [
            ("估价与精炼", ft.icons.Icons.CALCULATE),
            ("制 造 业", ft.icons.Icons.FACTORY),
            ("行星工业", ft.icons.Icons.PUBLIC),
            ("忠诚点价值", ft.icons.Icons.STARS),
        ]

        self._tab_buttons = []
        self._tab_contents = []

        for i, (name, icon) in enumerate(sub_tabs):
            btn = ft.Container(
                content=ft.Row(
                    controls=[
                        ft.Icon(icon, size=18, color="#888888"),
                        ft.Text(name, size=14, color="#888888"),
                    ],
                    spacing=6,
                    alignment=ft.MainAxisAlignment.CENTER,
                ),
                padding=ft.padding.Padding(left=20, top=10, right=20, bottom=10),
                border_radius=8,
                bgcolor="transparent",
                on_click=lambda e, n=name: self._switch_tab(n),
                ink=True,
            )
            self._tab_buttons.append(btn)

            if name == "制 造 业":
                content = self._build_calculator_tab()
            else:
                content = ft.Container(
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
            self._tab_contents.append(content)

        # Navigation row
        self._nav_row = ft.Row(
            controls=self._tab_buttons,
            spacing=8,
            alignment=ft.MainAxisAlignment.CENTER,
        )

        # Content stack
        self._content_stack = ft.Stack(
            controls=self._tab_contents,
            expand=True,
        )

        self.content = ft.Column(
            controls=[
                ft.Container(
                    content=self._nav_row,
                    bgcolor="#16213e",
                    padding=ft.padding.Padding(left=20, top=8, right=20, bottom=8),
                    border=ft.Border(bottom=ft.BorderSide(1, "#2a2a4a")),
                ),
                self._content_stack,
            ],
            spacing=0,
            expand=True,
        )

        self._switch_tab("估价与精炼")

    def _build_calculator_tab(self) -> ft.Container:
        """Build the manufacturing cost calculator tab content."""
        # Search bar
        self._bp_search_input = ft.TextField(
            hint_text="输入蓝图名称搜索...",
            prefix_icon=ft.icons.Icons.SEARCH,
            suffix=ft.IconButton(
                icon=ft.icons.Icons.CLOSE,
                icon_size=16,
                on_click=lambda e: self._clear_search(),
            ),
            on_change=lambda e: self._page.run_task(self._search_blueprints, self._bp_search_input.value),
            on_submit=lambda e: self._page.run_task(self._search_blueprints, self._bp_search_input.value),
            bgcolor="#0f3460",
            color="#e0e0e0",
            hint_style=ft.TextStyle(color="#666666"),
            border_color="#2a2a4a",
            border_radius=6,
            text_size=14,
            expand=True,
        )

        # Price source
        self._price_dropdown = ft.Dropdown(
            options=[
                ft.DropdownOption("buy", "买单价"),
                ft.DropdownOption("sell", "卖单价"),
            ],
            value="buy",
            width=100,
            bgcolor="#0f3460",
            color="#e0e0e0",
            border_color="#2a2a4a",
            text_size=13,
            on_select=lambda e: self._recalc(),
        )

        # Activity type
        self._activity_dropdown = ft.Dropdown(
            options=[
                ft.DropdownOption("manufacturing", "制造"),
                ft.DropdownOption("invention", "发明"),
                ft.DropdownOption("copying", "复制"),
                ft.DropdownOption("reaction", "反应"),
            ],
            value="manufacturing",
            width=80,
            bgcolor="#0f3460",
            color="#e0e0e0",
            border_color="#2a2a4a",
            text_size=13,
            on_select=lambda e: self._recalc(),
        )

        # Batch quantity
        self._batch_qty = ft.TextField(
            value="1",
            width=60,
            height=36,
            bgcolor="#0f3460",
            color="#e0e0e0",
            border_color="#2a2a4a",
            text_size=13,
            text_align=RIGHT,
            keyboard_type=ft.KeyboardType.NUMBER,
            on_submit=lambda e: self._recalc(),
        )

        # System cost index
        self._system_dropdown = ft.Dropdown(
            options=[ft.DropdownOption("none", "无（不计安装费）")],
            value="none",
            width=140,
            bgcolor="#0f3460",
            color="#e0e0e0",
            border_color="#2a2a4a",
            text_size=12,
            on_select=lambda e: self._recalc(),
        )
        self._page.run_task(self._load_systems)

        # Manual tax rate (%)
        self._tax_input = ft.TextField(
            value="0",
            width=50,
            height=36,
            bgcolor="#0f3460",
            color="#e0e0e0",
            border_color="#2a2a4a",
            text_size=13,
            text_align=RIGHT,
            keyboard_type=ft.KeyboardType.NUMBER,
            on_submit=lambda e: self._recalc(),
        )

        # Blueprint suggestion dropdown
        self._suggestion_list = ft.ListView(spacing=1, height=0, visible=False)

        self._suggestion_panel = ft.Container(
            content=self._suggestion_list,
            bgcolor="#16213e",
            border=ft.Border(
                left=ft.BorderSide(1, "#2a2a4a"),
                right=ft.BorderSide(1, "#2a2a4a"),
                bottom=ft.BorderSide(1, "#2a2a4a"),
            ),
            border_radius=ft.BorderRadius(top_left=0, top_right=0, bottom_left=6, bottom_right=6),
            visible=False,
            padding=4,
        )

        # Product info
        self._product_text = ft.Text("", size=13, color="#e0e0e0")
        self._time_text = ft.Text("", size=12, color="#888888")

        # Material table header
        self._mat_header = ft.Container(
            content=ft.Row([
                ft.Text("材料", size=12, weight=ft.FontWeight.BOLD, color="#e0e0e0", expand=True),
                ft.Text("数量", size=12, weight=ft.FontWeight.BOLD, color="#e0e0e0", width=80, text_align=RIGHT),
                ft.Text("单价", size=12, weight=ft.FontWeight.BOLD, color="#e0e0e0", width=100, text_align=RIGHT),
                ft.Text("小计", size=12, weight=ft.FontWeight.BOLD, color="#e0e0e0", width=100, text_align=RIGHT),
            ], spacing=8),
            bgcolor="#0f3460",
            padding=ft.padding.Padding(left=12, top=6, right=12, bottom=6),
            visible=False,
        )

        self._material_list = ft.ListView(controls=[], expand=True, spacing=1)

        # Skills panel
        self._skill_controls: dict[int, ft.Dropdown] = {}
        self._skill_list = ft.ListView(controls=[], spacing=2)

        # Summary
        self._summary_text = ft.Text("", size=13, color="#e0e0e0")

        # Right panel: skills
        right_panel = ft.Container(
            content=ft.Column([
                ft.Text("技能等级", size=14, weight=ft.FontWeight.BOLD, color="#e0e0e0"),
                ft.Divider(color="#2a2a4a", height=1),
                self._skill_list,
                ft.Container(height=8),
                ft.Button(
                    content=ft.Row([
                        ft.Icon(ft.icons.Icons.SAVE, color="#e0e0e0", size=16),
                        ft.Text("保存技能等级", color="#e0e0e0", size=13),
                    ], spacing=4),
                    style=ft.ButtonStyle(
                        bgcolor="#0f3460",
                        padding=ft.padding.Padding(left=16, top=6, right=16, bottom=6),
                    ),
                    on_click=self._save_skills,
                ),
            ], spacing=4, expand=True),
            width=280,
            bgcolor="#16213e",
            border=ft.Border(left=ft.BorderSide(1, "#2a2a4a")),
            padding=ft.padding.Padding(left=12, top=10, right=12, bottom=10),
            visible=False,
        )

        # Left panel: materials
        left_panel = ft.Container(
            content=ft.Column([
                self._mat_header,
                self._material_list,
            ], expand=True),
            expand=True,
            padding=ft.padding.Padding(left=8, top=4, right=8, bottom=4),
        )

        # Content area
        self._content_area = ft.Container(
            content=ft.Row([
                left_panel,
                right_panel,
            ], spacing=0, expand=True, visible=False),
            expand=True,
        )

        # Full layout
        return ft.Container(
            content=ft.Column([
                # Search row
                ft.Container(
                    content=ft.Row([
                        self._bp_search_input,
                        ft.Text("类型:", size=13, color="#888888"),
                        self._activity_dropdown,
                        ft.Text("数量:", size=13, color="#888888"),
                        self._batch_qty,
                        ft.Text("价格:", size=13, color="#888888"),
                        self._price_dropdown,
                        ft.Text("税率:", size=13, color="#888888"),
                        self._tax_input,
                        ft.Text("%", size=13, color="#888888"),
                    ], spacing=6, scroll=ft.ScrollMode.AUTO),
                    padding=ft.padding.Padding(left=16, top=12, right=16, bottom=4),
                ),
                # Suggestions
                ft.Container(
                    content=ft.Stack([
                        self._suggestion_panel,
                    ]),
                    padding=ft.padding.Padding(left=16, top=0, right=16, bottom=0),
                ),
                # Product info
                ft.Container(
                    content=ft.Row([
                        self._product_text,
                        ft.Container(expand=True),
                        self._time_text,
                    ]),
                    padding=ft.padding.Padding(left=16, top=4, right=16, bottom=4),
                ),
                # Summary
                ft.Container(
                    content=self._summary_text,
                    padding=ft.padding.Padding(left=16, top=4, right=16, bottom=4),
                ),
                # Content
                self._content_area,
            ], spacing=0, expand=True),
            expand=True,
        )

    # ─────────────────────────────
    #  Tab switching
    # ─────────────────────────────

    def _switch_tab(self, name: str):
        tab_names = ["估价与精炼", "制 造 业", "行星工业", "忠诚点价值"]
        try:
            idx = tab_names.index(name)
        except ValueError:
            return
        for i, btn in enumerate(self._tab_buttons):
            is_active = (i == idx)
            btn.bgcolor = "#e94560" if is_active else "transparent"
            for c in btn.content.controls:
                c.color = "#ffffff" if is_active else "#888888"
        for i, content in enumerate(self._tab_contents):
            content.visible = (i == idx)
        self._page.update()

    # ─────────────────────────────
    #  Blueprint search
    # ─────────────────────────────

    async def _search_blueprints(self, query: str):
        if not query or len(query.strip()) < 1:
            self._suggestion_panel.visible = False
            self._page.update()
            return

        loop = asyncio.get_event_loop()
        try:
            rows = await loop.run_in_executor(
                self._executor, self._db_search_blueprints, query.strip()
            )
        except Exception as ex:
            print(f"[ERROR] 蓝图搜索失败: {ex}")
            return

        if not rows:
            self._suggestion_list.controls = [
                ft.Text("未找到匹配的蓝图", size=12, color="#888888", no_wrap=True)
            ]
            self._suggestion_list.height = 40
            self._suggestion_panel.visible = True
            self._page.update()
            return

        self._blueprint_results = rows
        suggestions = []
        for r in rows:
            tid = r["type_id"]
            label = r["zh_name"] or r["en_name"] or str(tid)
            en = r["en_name"]
            sr = en if en and en != label else ""
            suggestions.append(
                ft.Container(
                    content=ft.Column([
                        ft.Text(label, size=12, color="#e0e0e0"),
                        ft.Text(sr, size=10, color="#888888") if sr else ft.Container(),
                    ], spacing=0),
                    padding=ft.padding.Padding(left=8, top=4, right=8, bottom=4),
                    on_click=lambda e, r=r: self._select_blueprint(r),
                    on_hover=lambda e: setattr(e.control, 'bgcolor', '#0f3460' if e.data == 'true' else 'transparent') or self._page.update(),
                )
            )

        max_show = min(len(suggestions), 8)
        self._suggestion_list.controls = suggestions
        self._suggestion_list.height = max_show * 48
        self._suggestion_panel.visible = True
        self._page.update()

    def _db_search_blueprints(self, query: str) -> list[dict]:
        conn = sqlite3.connect(DB_PATH)
        try:
            c = conn.cursor()
            like = f"%{query}%"
            c.execute("""
                SELECT i.type_id, i.zh_name, i.en_name
                FROM item i
                WHERE i.type_id IN (
                    SELECT DISTINCT blueprint_type_id FROM blueprint_activities
                )
                AND (i.en_name LIKE ? OR i.zh_name LIKE ?)
                ORDER BY i.zh_name, i.en_name
                LIMIT 20
            """, (like, like))
            return [
                {"type_id": tid, "zh_name": zh or "", "en_name": en or ""}
                for tid, zh, en in c.fetchall()
            ]
        finally:
            conn.close()

    # ─────────────────────────────
    #  Blueprint select
    # ─────────────────────────────

    async def _select_blueprint(self, bp: dict):
        self._selected_bp = bp
        self._suggestion_panel.visible = False
        self._bp_search_input.value = bp["zh_name"] or bp["en_name"] or str(bp["type_id"])
        activity = self._activity

        loop = asyncio.get_event_loop()

        try:
            materials, products, bp_skills, activity_data = await asyncio.gather(
                loop.run_in_executor(self._executor, self._db_get_materials, bp["type_id"], activity),
                loop.run_in_executor(self._executor, self._db_get_products, bp["type_id"], activity),
                loop.run_in_executor(self._executor, self._db_get_bp_skills, bp["type_id"], activity),
                loop.run_in_executor(self._executor, self._db_get_activity, bp["type_id"], activity),
            )
        except Exception as ex:
            self._product_text.value = f"查询失败: {ex}"
            self._page.update()
            return

        self._materials = materials
        self._products = products
        self._bp_skills = bp_skills
        self._bp_time = activity_data["time"] if activity_data else 0

        self._render_results()

    def _db_get_materials(self, bp_id: int, activity: str) -> list[dict]:
        conn = sqlite3.connect(DB_PATH)
        try:
            c = conn.cursor()
            c.execute("""
                SELECT bm.material_type_id, bm.quantity, i.zh_name, i.en_name,
                       mp.buy_price, mp.sell_price
                FROM blueprint_materials bm
                JOIN item i ON bm.material_type_id = i.type_id
                LEFT JOIN market_prices mp ON mp.type_id = i.type_id
                  AND mp.fetch_time = (
                    SELECT MAX(fetch_time) FROM market_prices WHERE type_id = i.type_id
                  )
                WHERE bm.blueprint_type_id = ? AND bm.activity = ?
                ORDER BY i.zh_name, i.en_name
            """, (bp_id, activity))
            return [
                {
                    "type_id": tid, "quantity": qty,
                    "zh_name": zh or "", "en_name": en or "",
                    "buy_price": buy, "sell_price": sell,
                }
                for tid, qty, zh, en, buy, sell in c.fetchall()
            ]
        finally:
            conn.close()

    def _db_get_products(self, bp_id: int, activity: str) -> list[dict]:
        conn = sqlite3.connect(DB_PATH)
        try:
            c = conn.cursor()
            c.execute("""
                SELECT bp.product_type_id, bp.quantity, i.zh_name, i.en_name,
                       mp.buy_price, mp.sell_price
                FROM blueprint_products bp
                JOIN item i ON bp.product_type_id = i.type_id
                LEFT JOIN market_prices mp ON mp.type_id = i.type_id
                  AND mp.fetch_time = (
                    SELECT MAX(fetch_time) FROM market_prices WHERE type_id = i.type_id
                  )
                WHERE bp.blueprint_type_id = ? AND bp.activity = ?
            """, (bp_id, activity))
            return [
                {
                    "type_id": tid, "quantity": qty,
                    "zh_name": zh or "", "en_name": en or "",
                    "buy_price": buy, "sell_price": sell,
                }
                for tid, qty, zh, en, buy, sell in c.fetchall()
            ]
        finally:
            conn.close()

    def _db_get_bp_skills(self, bp_id: int, activity: str) -> list[dict]:
        conn = sqlite3.connect(DB_PATH)
        try:
            c = conn.cursor()
            c.execute("""
                SELECT bs.skill_type_id, bs.level, i.zh_name, i.en_name,
                       COALESCE(u.level, 0) as user_level
                FROM blueprint_skills bs
                JOIN item i ON bs.skill_type_id = i.type_id
                LEFT JOIN user_skills u ON u.skill_type_id = bs.skill_type_id
                WHERE bs.blueprint_type_id = ? AND bs.activity = ?
                ORDER BY i.zh_name, i.en_name
            """, (bp_id, activity))
            return [
                {
                    "type_id": tid, "required_level": req_lvl,
                    "zh_name": zh or "", "en_name": en or "",
                    "user_level": user_lvl,
                }
                for tid, req_lvl, zh, en, user_lvl in c.fetchall()
            ]
        finally:
            conn.close()

    def _db_get_activity(self, bp_id: int, activity: str) -> Optional[dict]:
        conn = sqlite3.connect(DB_PATH)
        try:
            c = conn.cursor()
            c.execute("""
                SELECT time, max_production_limit
                FROM blueprint_activities
                WHERE blueprint_type_id = ? AND activity = ?
            """, (bp_id, activity))
            row = c.fetchone()
            if row:
                return {"time": row[0], "max_limit": row[1]}
            return None
        finally:
            conn.close()

    # ─────────────────────────────
    #  Render results
    # ─────────────────────────────

    def _render_results(self):
        if not self._products:
            self._product_text.value = "无产出物数据"
            self._page.update()
            return

        price_col = "buy_price" if self._price_source == "buy" else "sell_price"
        price_label = "买单价" if self._price_source == "buy" else "卖单价"

        # Batch quantity
        try:
            batch = int(self._batch_qty.value or "1")
            if batch < 1:
                batch = 1
        except ValueError:
            batch = 1

        # Facility tax
        facility_tax = 0.0

        # Product info
        prod = self._products[0]
        prod_name = prod["zh_name"] or prod["en_name"] or str(prod["type_id"])
        run_qty = prod["quantity"]
        total_output_qty = run_qty * batch
        prod_price = prod.get(price_col)
        prod_price_str = f"{prod_price:,.2f} ISK" if prod_price else "—"

        # Time
        time_str = ""
        if self._bp_time:
            mins = self._bp_time // 60
            secs = self._bp_time % 60
            ind_lvl = self._user_skills.get(3380, 5)
            adv_lvl = self._user_skills.get(3388, 5)
            sup_lvl = self._user_skills.get(24268, 5)
            adj_time = self._bp_time * (1 - 0.04 * ind_lvl) * (1 - 0.03 * adv_lvl) * (1 - 0.03 * sup_lvl)
            adj_mins = int(adj_time // 60)
            adj_secs = int(adj_time % 60)
            total_adj = adj_time * batch
            th = int(total_adj // 3600)
            tm = int((total_adj % 3600) // 60)
            ts = int(total_adj % 60)
            time_str = f"单次 {mins}分{secs}秒 → 技能调整 {adj_mins}分{adj_secs}秒 → ×{batch} = {th}h{tm}m{ts}s"

        self._product_text.value = f"产出: {prod_name} × {total_output_qty}  ({batch} runs × {run_qty})"
        self._time_text.value = time_str

        # Materials table
        total_cost = 0.0
        mat_controls = []
        for i, mat in enumerate(self._materials):
            qty = mat["quantity"] * batch
            unit_price = mat.get(price_col) or 0.0
            subtotal = qty * unit_price
            total_cost += subtotal

            bg = "#1e1e3a" if i % 2 == 0 else "transparent"
            mat_controls.append(
                ft.Container(
                    content=ft.Row([
                        ft.Text(mat["zh_name"] or mat["en_name"], size=12, color="#e0e0e0", expand=True, no_wrap=True),
                        ft.Text(f"{qty:,}", size=12, color="#e0e0e0", width=80, text_align=RIGHT, font_family=MONO_FONT),
                        ft.Text(f"{unit_price:,.2f}" if unit_price else "—", size=12,
                                color="#00ff88" if self._price_source == "buy" else "#ff6b6b",
                                width=100, text_align=RIGHT, font_family=MONO_FONT),
                        ft.Text(f"{subtotal:,.2f}" if subtotal else "—", size=12, color="#ffcc00",
                                width=100, text_align=RIGHT, font_family=MONO_FONT),
                    ], spacing=8),
                    padding=ft.padding.Padding(left=12, top=4, right=12, bottom=4),
                    bgcolor=bg,
                )
            )

        self._material_list.controls = mat_controls
        self._mat_header.visible = bool(mat_controls)

        # Skills panel - blueprint skills + global skills
        skill_controls = []
        self._skill_controls.clear()

        # Global skills section
        global_skills = [
            ("Industry", 3380),
            ("Advanced Industry", 3388),
            ("Supply Chain Mgmt", 24268),
        ]
        skill_controls.append(
            ft.Text("全局制造技能", size=13, weight=ft.FontWeight.BOLD, color="#e94560")
        )
        for name, sk_id in global_skills:
            cur = self._user_skills.get(sk_id, 5)
            dd = ft.Dropdown(
                options=[ft.DropdownOption(str(lv), str(lv)) for lv in range(1, 6)],
                value=str(cur),
                width=60,
                bgcolor="#0f3460",
                color="#e0e0e0",
                border_color="#2a2a4a",
                text_size=12,
            )
            self._skill_controls[sk_id] = dd
            skill_controls.append(
                ft.Container(
                    content=ft.Row([
                        ft.Text(name, size=12, color="#e0e0e0", expand=True),
                        dd,
                    ], spacing=4),
                    padding=ft.padding.Padding(top=2, bottom=2),
                )
            )

        # Blueprint-specific skills (only if different from global)
        bp_skill_ids = {s["type_id"] for s in self._bp_skills}
        global_ids = {k for _, k in global_skills}
        if bp_skill_ids - global_ids:
            skill_controls.append(
                ft.Container(height=8),
            )
            skill_controls.append(
                ft.Text("蓝图专属技能", size=13, weight=ft.FontWeight.BOLD, color="#ff6b6b")
            )
            for sk in self._bp_skills:
                if sk["type_id"] in global_ids:
                    continue  # already shown in global
                cur_lvl = sk["user_level"]
                req_lvl = sk["required_level"]
                dd = ft.Dropdown(
                    options=[ft.DropdownOption(str(lv), str(lv)) for lv in range(1, 6)],
                    value=str(cur_lvl),
                    width=60,
                    bgcolor="#0f3460",
                    color="#e0e0e0",
                    border_color="#2a2a4a",
                    text_size=12,
                )
                self._skill_controls[sk["type_id"]] = dd
                skill_controls.append(
                    ft.Container(
                        content=ft.Row([
                            ft.Text(sk["zh_name"] or sk["en_name"], size=12, color="#e0e0e0", expand=True),
                            ft.Text(f"需 Lv{req_lvl}", size=10, color="#888888", width=45),
                            dd,
                        ], spacing=4),
                        padding=ft.padding.Padding(top=2, bottom=2),
                    )
                )

        self._skill_list.controls = skill_controls

        # Summary - cost breakdown section
        cost_label = price_label

        # Install fee
        system_val = self._system_dropdown.value
        system_cost_idx = 0.0
        system_name = "无"
        if system_val and system_val != "none":
            try:
                parts = system_val.split("|")
                system_cost_idx = float(parts[1])
                system_name = parts[0]
            except (ValueError, IndexError):
                pass

        install_fee = 0.0
        if system_cost_idx > 0 and prod_price and prod_price > 0:
            install_fee = prod_price * 0.04 * system_cost_idx * batch

        # Tax
        try:
            tax_pct = float(self._tax_input.value or "0")
            if tax_pct < 0:
                tax_pct = 0
        except ValueError:
            tax_pct = 0
        tax_fee = total_cost * (tax_pct / 100)

        # Totals
        total_without_tax = total_cost + install_fee
        grand_total = total_without_tax + tax_fee

        output_price_val = prod_price if prod_price else 0.0
        total_output = output_price_val * total_output_qty
        profit = total_output - grand_total
        margin = (profit / grand_total * 100) if grand_total > 0 else 0.0

        # Build multi-line summary
        summary_lines = []
        summary_lines.append(f"材料成本: {total_cost:,.2f} ISK  ({cost_label})")
        if install_fee > 0:
            summary_lines.append(f"安装费:   {install_fee:,.2f} ISK  (系统: {system_name}, 指数: {system_cost_idx})")
        if tax_pct > 0:
            summary_lines.append(f"设施税:   {tax_fee:,.2f} ISK  ({tax_pct:.1f}%)")
        summary_lines.append(f"──────")
        summary_lines.append(f"总成本:   {grand_total:,.2f} ISK")
        summary_lines.append(f"产出:     {total_output:,.2f} ISK  (单价 {prod_price_str} × {total_output_qty})")
        if profit >= 0:
            summary_lines.append(f"利润:     +{profit:,.2f} ISK  ({margin:.1f}%)")
        else:
            summary_lines.append(f"亏损:     {profit:,.2f} ISK  ({margin:.1f}%)")

        self._summary_text.value = "\n".join(summary_lines)

        # Show content
        self._content_area.visible = True
        content_row = self._content_area.content
        if isinstance(content_row, ft.Row):
            content_row.controls[1].visible = True

        self._page.update()

    # ─────────────────────────────
    #  Recalc (when price source changes)
    # ─────────────────────────────

    def _recalc(self):
        new_activity = self._activity_dropdown.value or "manufacturing"
        price_changed = self._price_dropdown.value != self._price_source
        activity_changed = new_activity != self._activity
        self._price_source = self._price_dropdown.value or "buy"

        if self._selected_bp:
            if activity_changed:
                self._activity = new_activity
                self._page.run_task(self._select_blueprint, self._selected_bp)
            else:
                self._render_results()

    # ─────────────────────────────
    #  Skills
    # ─────────────────────────────

    async def _load_user_skills(self):
        loop = asyncio.get_event_loop()
        try:
            self._user_skills = await loop.run_in_executor(self._executor, self._db_get_all_user_skills)
        except Exception as ex:
            print(f"[ERROR] 加载技能等级失败: {ex}")

    def _db_get_all_user_skills(self) -> dict[int, int]:
        conn = sqlite3.connect(DB_PATH)
        try:
            c = conn.cursor()
            c.execute("SELECT skill_type_id, level FROM user_skills")
            return {row[0]: row[1] for row in c.fetchall()}
        finally:
            conn.close()

    def _save_skills(self, e):
        """Save skill levels from dropdowns to DB."""
        updates = []
        for sk_id, dd in self._skill_controls.items():
            try:
                lvl = int(dd.value)
                updates.append((lvl, sk_id))
            except (ValueError, TypeError):
                pass

        conn = sqlite3.connect(DB_PATH)
        try:
            c = conn.cursor()
            c.executemany(
                "INSERT OR REPLACE INTO user_skills (skill_type_id, level) VALUES (?, ?)",
                [(sk_id, lvl) for lvl, sk_id in updates],
            )
            conn.commit()
        finally:
            conn.close()

        # Update local cache
        for lvl, sk_id in updates:
            self._user_skills[sk_id] = lvl

        # Recalc
        if self._selected_bp:
            self._render_results()

        # Show feedback via status update
        self._product_text.value = (self._product_text.value or "").split(" | ")[0]
        self._product_text.value = (self._product_text.value or "") + " | ✅ 技能等级已保存"
        self._page.update()

    # ─────────────────────────────
    #  Clear
    # ─────────────────────────────

    def _clear_search(self):
        self._bp_search_input.value = ""
        self._selected_bp = None
        self._suggestion_panel.visible = False
        self._content_area.visible = False
        self._product_text.value = ""
        self._time_text.value = ""
        self._summary_text.value = ""
        self._mat_header.visible = False
        self._material_list.controls.clear()
        self._skill_list.controls.clear()
        self._page.update()

    # ─────────────────────────────
    #  Facilities
    # ─────────────────────────────

        # ------------------------
    #  Systems
    # ------------------------

    async def _load_systems(self):
        loop = asyncio.get_event_loop()
        try:
            systems = await loop.run_in_executor(self._executor, self._db_get_systems)
        except Exception:
            systems = []

        options = [ft.DropdownOption("none", "无（不计安装费）")]
        for sys_ in systems:
            label = f"{sys_['name']} (指数 {sys_['cost_index']})"
            val = f"{sys_['name']}|{sys_['cost_index']}"
            options.append(ft.DropdownOption(val, label))
        self._system_dropdown.options = options
        self._system_dropdown.value = "none"
        self._page.update()

    def _db_get_systems(self) -> list[dict]:
        conn = sqlite3.connect(DB_PATH)
        try:
            c = conn.cursor()
            c.execute("""
                SELECT solar_system_id, cost_index
                FROM industry_system_costs
                WHERE activity = 'manufacturing'
                ORDER BY cost_index ASC
                LIMIT 30
            """)
            rows = c.fetchall()
            result = []
            for sid, cost in rows:
                c2 = conn.cursor()
                c2.execute("SELECT zh_name, en_name FROM item WHERE type_id = ?", (sid,))
                name_row = c2.fetchone()
                name = "?"
                if name_row:
                    name = name_row[0] or name_row[1] or str(sid)
                result.append({"system_id": sid, "cost_index": cost, "name": name})
            return result
        finally:
            conn.close()
def _clear_search(self):
        self._bp_search_input.value = ""
        self._selected_bp = None
        self._suggestion_panel.visible = False
        self._content_area.visible = False
        self._product_text.value = ""
        self._time_text.value = ""
        self._summary_text.value = ""
        self._mat_header.visible = False
        self._material_list.controls.clear()
        self._skill_list.controls.clear()
        self._page.update()

RIGHT = ft.TextAlign.RIGHT
