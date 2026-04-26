"""
查询物品页面

功能：
  - 模糊搜索 + 候选下拉框（跟随主窗口移动）
  - 搜索类别名自动显示该类物品
  - 图标自适应行高、价格后括号标注数量
  - 双击行 → 查看前5笔买/卖单（含空间站名称+ID）
  - 清空按钮、单击复制（不含数量）
"""
import tkinter as tk
from tkinter import ttk, messagebox
import sqlite3
import aiohttp
import asyncio
import threading
from pathlib import Path
from typing import Optional
from PIL import Image, ImageTk, ImageDraw
from ui.config import CJK_FONT, DB_PATH, load_window_geometry, save_window_geometry, bind_geometry_persistence

ESI_BASE_URL = "https://esi.evetech.net/latest"
REGION_ID = 10000002               # 伏尔戈（The Forge）
ICON_DIR = Path("data/caches/icons")
ICON_SIZE = 48                     # 图标显示尺寸

# ── 默认占位图标 ──
_PLACEHOLDER_IMG = None

def _get_place_holder(size=ICON_SIZE) -> ImageTk.PhotoImage:
    global _PLACEHOLDER_IMG
    if _PLACEHOLDER_IMG is None:
        img = Image.new("RGBA", (size, size), (200, 200, 200, 255))
        draw = ImageDraw.Draw(img)
        draw.text((size//3, size//3), "?", fill=(120, 120, 120))
        _PLACEHOLDER_IMG = ImageTk.PhotoImage(img)
    return _PLACEHOLDER_IMG


def _load_icon_photo(type_id: int) -> Optional[ImageTk.PhotoImage]:
    """尝试加载本地缓存的图标；返回PhotoImage或None"""
    png_path = ICON_DIR / f"{type_id}.png"
    if png_path.exists():
        try:
            img = Image.open(png_path).resize((ICON_SIZE, ICON_SIZE), Image.LANCZOS)
            return ImageTk.PhotoImage(img)
        except Exception:
            pass
    return None


# ── 空间站名称缓存 ──
_station_name_cache = {}  # type: dict[int, str]
_station_cache_lock = asyncio.Lock()


async def _resolve_names(location_ids):
    """从ESI /universe/names/ 批量解析名称，补充缓存"""
    need = [lid for lid in location_ids if lid not in _station_name_cache]
    if not need:
        return
    async with _station_cache_lock:
        need = [lid for lid in location_ids if lid not in _station_name_cache]
        if not need:
            return
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
                            data = await resp.json()
                            for item in data:
                                _station_name_cache[item["id"]] = item.get("name", str(item["id"]))
                        else:
                            for lid in chunk:
                                _station_name_cache.setdefault(lid, str(lid))
                except Exception:
                    for lid in chunk:
                        _station_name_cache.setdefault(lid, str(lid))


class QueryPage(tk.Frame):
    """物品查询页面"""

    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # ── 图标缓存 ──
        self._icon_photos = {}  # type: dict[int, ImageTk.PhotoImage]
        self._icon_placeholder = _get_place_holder()

        # ═══════════════════════════════════════
        # ① 搜索区域
        # ═══════════════════════════════════════
        search_frame = tk.Frame(self)
        search_frame.grid(row=0, column=0, pady=(15, 5), sticky="ew")

        inner = tk.Frame(search_frame)
        inner.pack(anchor="center")

        tk.Label(inner, text="🔍 查询物品", font=("Microsoft YaHei UI", 14, "bold"),
                 foreground="#2a6496").pack(side="top", pady=(0, 8))

        row1 = tk.Frame(inner)
        row1.pack()

        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self._on_entry_changed)
        self.entry = tk.Entry(row1, textvariable=self.search_var, width=32,
                              font=CJK_FONT, justify="center",
                              relief=tk.SUNKEN, borderwidth=2)
        self.entry.pack(side="left", padx=3)
        self.entry.bind("<Return>", lambda e: self.search_item())
        self.entry.bind("<Down>", lambda e: self._focus_suggestion())
        self.entry.bind("<Escape>", lambda e: self._hide_suggestions())

        search_btn = tk.Button(row1, text="搜索", font=CJK_FONT,
                               command=self.search_item, width=6,
                               bg="#4a90d9", fg="white", relief=tk.RAISED)
        search_btn.pack(side="left", padx=2)

        # ── 清空按钮 ──
        clear_btn = tk.Button(row1, text="✕", font=("Microsoft YaHei UI", 10),
                              command=self._clear_search, width=3,
                              relief=tk.FLAT, fg="#888888")
        clear_btn.pack(side="left", padx=1)

        # 异步加载类别列表
        self._all_groups = []  # type: list[tuple[int, str, str]]
        self.after(100, self._load_group_list)

        # ── 候选下拉框（无边框Toplevel） ──
        self._suggestion_toplevel = None
        self._suggestion_data = []  # type: list[tuple[int, str]]
        self._suggestion_visible = False
        self._debounce_timer = None

        # ── 统计行 ──
        info_frame = tk.Frame(self)
        info_frame.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 5))

        self.count_var = tk.StringVar()
        self.count_var.set("")
        tk.Label(info_frame, textvariable=self.count_var,
                 font=("Microsoft YaHei UI", 9), fg="#666666").pack(side="left")

        self.status_var = tk.StringVar()
        self.status_var.set("输入物品名称/ID/类别 后搜索，双击行查看实时订单")
        tk.Label(info_frame, textvariable=self.status_var,
                 font=("Microsoft YaHei UI", 9), fg="#888888",
                 anchor="e").pack(side="right")

        # ═══════════════════════════════════════
        # ② 主表格
        # ═══════════════════════════════════════
        table_frame = tk.Frame(self)
        table_frame.grid(row=2, column=0, sticky="nsew", padx=20, pady=(0, 10))
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        # 列：不再有独立的买/卖量列，价格后括号标注
        columns = ("type_id", "zh_name", "en_name", "group_name",
                   "buy_price", "sell_price", "volume")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="tree headings",
                                 height=20, selectmode="browse")

        # 首列 #0 用于显示图标
        self.tree.column("#0", width=ICON_SIZE+12, minwidth=50, anchor="center")
        self.tree.heading("#0", text="图标",
                          command=lambda: self._sort_column("type_id", False))

        col_cfg = [
            ("type_id",    "ID",        60,  "center"),
            ("zh_name",    "中文名",    130, "center"),
            ("en_name",    "英文名",    170, "w"),
            ("group_name", "类别",      130, "center"),
            # "买单价格(量)" 与 "卖单价格(量)" 合并显示
            ("buy_price",  "买单 ↓",    140, "e"),
            ("sell_price", "卖单 ↑",    140, "e"),
            ("volume",     "体积(m³)",  90,  "e"),
        ]
        for col, heading, width, anchor in col_cfg:
            self.tree.column(col, width=width, minwidth=50, anchor=anchor)
            self.tree.heading(col, text=heading,
                              command=lambda c=col: self._sort_column(c, False))

        self.tree.grid(row=0, column=0, sticky="nsew")

        v_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        v_scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=v_scroll.set)

        h_scroll = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        h_scroll.grid(row=1, column=0, sticky="ew")
        self.tree.configure(xscrollcommand=h_scroll.set)

        # 事件绑定
        self.tree.bind("<Button-1>", self._on_single_click)
        self.tree.bind("<Double-1>", self._on_double_click)

        # 样式
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", font=("Microsoft YaHei UI", 10),
                        rowheight=ICON_SIZE + 8)
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 10, "bold"),
                        background="#e8e8e8")

        self.tree.tag_configure("even", background="#f8f8f8")
        self.tree.tag_configure("odd", background="#ffffff")
        self.tree.tag_configure("buy_gt_sell", background="#fff0f0")

        # ═══════════════════════════════════════
        # ③ 订单弹窗
        # ═══════════════════════════════════════
        self._order_popup = None

        # ── 全局点击关闭候选框 ──
        self._suggestion_click_bind = self.controller.bind(
            "<Button-1>", self._on_any_click, add="+"
        )

        # ── 主窗口移动时更新候选框位置 ──
        self._suggestion_move_bind = self.controller.bind(
            "<Configure>", self._on_window_configure, add="+"
        )

    # ══════════════════════════════════════════════
    # 类别列表
    # ══════════════════════════════════════════════

    def _load_group_list(self):
        """从数据库加载物品类别"""
        def do_load():
            try:
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT DISTINCT e.group_id, e.en_group_name, e.zh_group_name "
                    "FROM item e WHERE e.group_id IS NOT NULL "
                    "ORDER BY e.zh_group_name, e.en_group_name"
                )
                rows = cursor.fetchall()
                conn.close()
                self._all_groups = rows
                self.after(0, lambda: self.status_var.set(
                    f"已加载 {len(rows)} 个物品类别"
                ))
            except Exception as e:
                print(f"加载类别列表失败: {e}")

        threading.Thread(target=do_load, daemon=True).start()

    # ══════════════════════════════════════════════
    # 清空
    # ══════════════════════════════════════════════

    def _clear_search(self):
        self.search_var.set("")
        self.entry.focus_set()
        # 清空表格
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._icon_photos.clear()
        self.count_var.set("")
        self.status_var.set("已清空")

    # ══════════════════════════════════════════════
    # 候选下拉框
    # ══════════════════════════════════════════════

    def _ensure_suggestion_window(self):
        if self._suggestion_toplevel is not None:
            return
        win = tk.Toplevel(self)
        win.withdraw()
        win.overrideredirect(True)
        win.attributes("-topmost", False)  # 不置顶，跟随主窗口层级
        win.configure(bg="#ffffff")

        listbox = tk.Listbox(
            win, font=CJK_FONT, height=10,
            bg="#ffffff", fg="#333333",
            selectbackground="#4a90d9", selectforeground="white",
            relief=tk.SUNKEN, borderwidth=1,
            activestyle="none"
        )
        listbox.pack(fill="both", expand=True)
        listbox.bind("<<ListboxSelect>>", self._on_suggestion_select)
        listbox.bind("<Double-1>", lambda e: self._on_suggestion_click(None))
        listbox.bind("<Button-1>", self._on_suggestion_inner_click)
        listbox.bind("<Escape>", lambda e: self._hide_suggestions())
        win.bind("<Escape>", lambda e: self._hide_suggestions())

        self._suggestion_toplevel = win
        self._suggestion_listbox = listbox

    def _on_entry_changed(self, *args):
        query = self.search_var.get().strip()
        if self._debounce_timer:
            self.after_cancel(self._debounce_timer)
        if len(query) >= 1:
            self._debounce_timer = self.after(200, lambda: self._fetch_suggestions(query))
        else:
            self._hide_suggestions()

    def _fetch_suggestions(self, query):
        if not query:
            self._hide_suggestions()
            return

        def do_fetch():
            try:
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                if query.isdigit():
                    cursor.execute(
                        "SELECT type_id, en_name, zh_name FROM item WHERE type_id = ? LIMIT 10",
                        (int(query),)
                    )
                else:
                    cursor.execute(
                        "SELECT type_id, en_name, zh_name FROM item "
                        "WHERE en_name LIKE ? OR zh_name LIKE ? "
                        "ORDER BY CASE WHEN en_name LIKE ? THEN 0 WHEN zh_name LIKE ? THEN 1 ELSE 2 END,"
                        " LENGTH(en_name), type_id LIMIT 10",
                        (f"{query}%", f"{query}%", f"{query}%", f"{query}%")
                    )
                rows = cursor.fetchall()
                conn.close()
                suggestions = []
                for tid, en, zh in rows:
                    display = f"[{tid}] {zh or ''} ({en or ''})" if zh and en else f"[{tid}] {zh or en or 'Unknown'}"
                    suggestions.append((tid, display))
                self.after(0, lambda: self._show_suggestions(suggestions))
            except Exception:
                self.after(0, self._hide_suggestions)

        threading.Thread(target=do_fetch, daemon=True).start()

    def _show_suggestions(self, suggestions):
        self._hide_suggestions()
        if not suggestions:
            return
        self._ensure_suggestion_window()
        self._suggestion_data = suggestions
        self._suggestion_visible = True

        lb = self._suggestion_listbox
        lb.delete(0, tk.END)
        for _, display in suggestions:
            lb.insert(tk.END, display)

        self.entry.update_idletasks()
        x = self.entry.winfo_rootx()
        y = self.entry.winfo_rooty() + self.entry.winfo_height() + 2
        w = max(450, self.entry.winfo_width())

        win = self._suggestion_toplevel
        win.geometry(f"{w}x{min(350, len(suggestions) * 28 + 10)}+{x}+{y}")
        win.deiconify()
        win.lift()

    def _hide_suggestions(self):
        self._suggestion_visible = False
        if self._suggestion_toplevel is not None:
            self._suggestion_toplevel.withdraw()

    def _on_any_click(self, event):
        """全局点击：点击候选框外部则关闭"""
        if not self._suggestion_visible:
            return
        win = self._suggestion_toplevel
        if win is None:
            return
        try:
            x, y = event.x_root, event.y_root
            wx = win.winfo_rootx()
            wy = win.winfo_rooty()
            ww = win.winfo_width()
            wh = win.winfo_height()
            if not (wx <= x <= wx + ww and wy <= y <= wy + wh):
                self._hide_suggestions()
        except tk.TclError:
            self._hide_suggestions()

    def _on_window_configure(self, event):
        """主窗口移动/调整时同步更新候选框位置"""
        if not self._suggestion_visible:
            return
        win = self._suggestion_toplevel
        if win is None:
            return
        try:
            self.entry.update_idletasks()
            x = self.entry.winfo_rootx()
            y = self.entry.winfo_rooty() + self.entry.winfo_height() + 2
            w = max(450, self.entry.winfo_width())
            h = win.winfo_height()
            win.geometry(f"{w}x{h}+{x}+{y}")
        except tk.TclError:
            pass

    def _on_suggestion_select(self, event):
        if not self._suggestion_visible:
            return
        sel = self._suggestion_listbox.curselection()
        if sel:
            idx = sel[0]
            tid, _ = self._suggestion_data[idx]
            self.search_var.set(str(tid))

    def _on_suggestion_click(self, event=None):
        if not self._suggestion_visible:
            return
        sel = self._suggestion_listbox.curselection()
        if sel:
            idx = sel[0]
            tid, _ = self._suggestion_data[idx]
            self.search_var.set(str(tid))
            self._hide_suggestions()
            self.after(50, self.search_item)

    def _on_suggestion_inner_click(self, event):
        """候选框内部点击：选中并搜索"""
        if not self._suggestion_visible:
            return
        idx = self._suggestion_listbox.nearest(event.y)
        if 0 <= idx < len(self._suggestion_data):
            tid, _ = self._suggestion_data[idx]
            self.search_var.set(str(tid))
            self._hide_suggestions()
            self.after(50, self.search_item)

    def _focus_suggestion(self):
        if self._suggestion_visible and self._suggestion_listbox and self._suggestion_listbox.size() > 0:
            self._suggestion_listbox.focus_set()
            self._suggestion_listbox.selection_set(0)

    # ══════════════════════════════════════════════
    # 搜索 & 排序
    # ══════════════════════════════════════════════

    def search_item(self):
        """执行搜索（名称 / ID / 类别名）"""
        query = self.search_var.get().strip()
        self._hide_suggestions()

        if not query:
            self.status_var.set("请输入物品名称或 ID")
            return

        # 清空表格
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._icon_photos.clear()

        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # 判断搜索条件
            if query.isdigit():
                conditions = "i.type_id = ?"
                params = (int(query),)
            else:
                # 先尝试匹配类别名
                group_match = None
                for gid, en, zh in self._all_groups:
                    if (zh and query in zh) or (en and query in en):
                        group_match = gid
                        break
                if group_match is not None:
                    conditions = "i.group_id = ?"
                    params = (group_match,)
                else:
                    conditions = "i.en_name LIKE ? OR i.zh_name LIKE ?"
                    params = (f"%{query}%", f"%{query}%")

            sql = f"""
                SELECT
                    i.type_id, i.zh_name, i.en_name,
                    i.en_group_name, i.zh_group_name, i.volume,
                    mp.buy_price, mp.sell_price, mp.buy_volume, mp.sell_volume
                FROM item i
                LEFT JOIN market_prices mp ON i.type_id = mp.type_id
                    AND mp.fetch_time = (
                        SELECT MAX(mp2.fetch_time) FROM market_prices mp2
                        WHERE mp2.type_id = i.type_id
                    )
                WHERE {conditions}
                ORDER BY i.type_id
                LIMIT 100
            """
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            conn.close()

            if not rows:
                self.status_var.set(f"未找到包含「{query}」的物品")
                self.count_var.set("")
                return

            for idx, row in enumerate(rows):
                tid = row["type_id"]
                zh = row["zh_name"] or ""
                en = row["en_name"] or ""
                group = row["zh_group_name"] or row["en_group_name"] or "—"
                buy_p = row["buy_price"]
                sell_p = row["sell_price"]
                buy_v = row["buy_volume"] or 0
                sell_v = row["sell_volume"] or 0
                vol = row["volume"] or 0.0

                # 价格 + 括号标注数量
                if buy_p is not None and buy_v > 0:
                    buy_str = f"{buy_p:,.2f} ({buy_v:,})"
                elif buy_p is not None:
                    buy_str = f"{buy_p:,.2f}"
                else:
                    buy_str = "—"

                if sell_p is not None and sell_v > 0:
                    sell_str = f"{sell_p:,.2f} ({sell_v:,})"
                elif sell_p is not None:
                    sell_str = f"{sell_p:,.2f}"
                else:
                    sell_str = "—"

                vol_str = f"{vol:,.2f}" if vol > 0 else "—"

                # 加载图标
                photo = _load_icon_photo(tid)
                if photo is None:
                    photo = self._icon_placeholder
                self._icon_photos[tid] = photo  # 保持引用

                values = (tid, zh, en, group, buy_str, sell_str, vol_str)
                tag = "even" if idx % 2 == 0 else "odd"
                if buy_p is not None and sell_p is not None and buy_p > sell_p:
                    tag = "buy_gt_sell"
                self.tree.insert("", "end", image=photo, values=values, tags=(tag,))

            self.count_var.set(f"共 {len(rows)} 条结果")
            self.status_var.set("双击行查看深度买/卖单")

        except sqlite3.OperationalError as e:
            if "no such table: market_prices" in str(e):
                self.status_var.set("⚠ market_prices 不存在，请先运行 getprices.py")
                self._fallback_search(query)
            else:
                self.status_var.set(f"❌ 数据库错误: {e}")
        except Exception as e:
            self.status_var.set(f"❌ 查询出错: {e}")

    def _fallback_search(self, query):
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            if query.isdigit():
                cursor.execute(
                    "SELECT type_id, en_name, zh_name, en_group_name, zh_group_name, volume "
                    "FROM item WHERE type_id = ?", (int(query),)
                )
            else:
                cursor.execute(
                    "SELECT type_id, en_name, zh_name, en_group_name, zh_group_name, volume "
                    "FROM item WHERE en_name LIKE ? OR zh_name LIKE ? LIMIT 100",
                    (f"%{query}%", f"%{query}%")
                )
            rows = cursor.fetchall()
            conn.close()
            if not rows:
                self.status_var.set(f"未找到「{query}」")
                return
            for idx, row in enumerate(rows):
                tid, en, zh, eng, zhg, vol = row
                photo = _load_icon_photo(tid) or self._icon_placeholder
                self._icon_photos[tid] = photo
                group = zhg or eng or "—"
                vol_str = f"{vol:,.2f}" if vol else "—"
                tag = "even" if idx % 2 == 0 else "odd"
                self.tree.insert("", "end", image=photo,
                                 values=(tid, zh or "", en or "", group,
                                         "—", "—", vol_str),
                                 tags=(tag,))
            self.count_var.set(f"共 {len(rows)} 条结果 (仅基本信息)")
            self.status_var.set("⚠ 无价格数据")
        except Exception as e:
            self.status_var.set(f"❌ 降级查询失败: {e}")

    def refresh_display(self):
        if self.search_var.get().strip():
            self.search_item()
        else:
            self.status_var.set("就绪 — 价格数据已更新")

    def _sort_column(self, col, reverse):
        rows = []
        for child in self.tree.get_children(""):
            val = self.tree.set(child, col)
            # 提取价格部分（去掉括号及内容）
            if val and val != "—":
                clean = val.split(" (")[0].replace(",", "")
            else:
                clean = val
            rows.append((clean, child))
        try:
            rows = [(float(v) if v and v != "—" else -1e9, child)
                    for v, child in rows]
            rows.sort(reverse=reverse)
        except ValueError:
            rows.sort(reverse=reverse, key=lambda x: x[0].lower())
        for idx, (_, child) in enumerate(rows):
            self.tree.move(child, "", idx)
        self.tree.heading(col, command=lambda: self._sort_column(col, not reverse))

    # ══════════════════════════════════════════════
    # 单击复制（不复制数量部分）
    # ══════════════════════════════════════════════

    def _on_single_click(self, event):
        region = self.tree.identify_region(event.x, event.y)
        if region == "cell":
            col = self.tree.identify_column(event.x)
            item = self.tree.identify_row(event.y)
            if item:
                col_idx = int(col.replace("#", "")) - 1
                keys = self.tree["columns"]
                if col_idx < len(keys):
                    col_key = keys[col_idx]
                    cell_text = self.tree.set(item, col_key)
                    if cell_text and cell_text != "—":
                        # 提取价格部分：去掉 " (数字)" 后缀
                        copy_text = cell_text.split(" (")[0]
                        self.clipboard_clear()
                        self.clipboard_append(copy_text)
                        self.status_var.set(f"已复制: {col_key} = {copy_text}")

    # ══════════════════════════════════════════════
    # 双击 → 订单详情弹窗（自适应）
    # ══════════════════════════════════════════════

    def _on_double_click(self, event):
        region = self.tree.identify_region(event.x, event.y)
        if region not in ("cell", "tree"):
            return
        item = self.tree.identify_row(event.y)
        if not item:
            return
        type_id = self.tree.set(item, "type_id")
        zh_name = self.tree.set(item, "zh_name")
        en_name = self.tree.set(item, "en_name")
        name = f"{zh_name} ({en_name})" if zh_name and en_name else (zh_name or en_name or str(type_id))
        self._show_order_popup(int(type_id), name)

    def _show_order_popup(self, type_id, item_name):
        self._close_order_popup()

        popup = tk.Toplevel(self)
        popup.title(f"订单详情 — {item_name}")
        popup.resizable(True, True)
        popup.attributes("-topmost", True)
        popup.configure(bg="#f5f5f5")
        popup.grab_set()

        # 恢复上次保存的窗口位置/大小；默认 820x520
        default_geo = load_window_geometry(f"OrderPopup_{type_id}", "820x520")
        popup.geometry(default_geo)
        # 绑定窗口几何位置持久化（每次移动/调整大小时保存）
        bind_geometry_persistence(popup, f"OrderPopup_{type_id}")

        # 点击窗口外任意位置 → 关闭
        self._popup_close_bind = self.controller.bind(
            "<Button-1>", self._on_any_click_outside, add="+"
        )

        popup.protocol("WM_DELETE_WINDOW", lambda: self._close_order_popup())
        popup.bind("<Escape>", lambda e: self._close_order_popup())

        # 内容框架（使用grid/pack自适应）
        content = tk.Frame(popup, bg="#f5f5f5", padx=15, pady=10)
        content.pack(fill="both", expand=True)
        content.bind("<Button-1>", lambda e: None)

        # 标题
        title = tk.Label(content, text=f"📋 {item_name}  (Type ID: {type_id})",
                         font=("Microsoft YaHei UI", 13, "bold"),
                         foreground="#2a6496", bg="#f5f5f5")
        title.pack(pady=(0, 10))

        loading = tk.Label(content, text="正在从 ESI 获取实时订单数据...",
                           font=("Microsoft YaHei UI", 10),
                           foreground="#888888", bg="#f5f5f5")
        loading.pack(expand=True)

        self._order_popup = {"popup": popup, "content": content, "type_id": type_id}

        # 异步获取
        threading.Thread(
            target=self._fetch_order_details,
            args=(type_id, content, loading),
            daemon=True
        ).start()

    def _on_any_click_outside(self, event):
        """监测全局点击，如果点击不在弹窗内则关闭弹窗"""
        if self._order_popup is None:
            return
        popup = self._order_popup["popup"]
        try:
            x, y = event.x_root, event.y_root
            px = popup.winfo_rootx()
            py = popup.winfo_rooty()
            pw = popup.winfo_width()
            ph = popup.winfo_height()
            if not (px <= x <= px + pw and py <= y <= py + ph):
                self._close_order_popup()
        except tk.TclError:
            self._close_order_popup()

    def _fetch_order_details(self, type_id, content, loading_label):
        """后台获取订单数据"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            buy_orders, sell_orders = loop.run_until_complete(
                self._fetch_orders_from_esi(type_id)
            )
            loop.close()

            def update_ui():
                loading_label.destroy()
                self._render_order_details(content, buy_orders, sell_orders)

            self.after(0, update_ui)
        except Exception as e:
            def show_error():
                loading_label.config(text=f"❌ 获取订单失败: {e}", fg="#cc0000")
            self.after(0, show_error)

    async def _fetch_orders_from_esi(self, type_id):
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(
            headers={"Accept": "application/json", "User-Agent": "EveDataCrawler/1.0"},
            timeout=timeout
        ) as session:
            url = f"{ESI_BASE_URL}/markets/{REGION_ID}/orders/"
            params = {"type_id": type_id, "order_type": "buy"}
            async with session.get(url, params=params) as resp:
                resp.raise_for_status()
                buy_data = await resp.json()
            params["order_type"] = "sell"
            async with session.get(url, params=params) as resp:
                resp.raise_for_status()
                sell_data = await resp.json()

        buy_orders = sorted(buy_data, key=lambda o: o["price"], reverse=True)[:5]
        sell_orders = sorted(sell_data, key=lambda o: o["price"])[:5]

        # 解析空间站名称
        all_loc_ids = set()
        for o in buy_orders + sell_orders:
            all_loc_ids.add(o["location_id"])
        await _resolve_names(list(all_loc_ids))

        return buy_orders, sell_orders

    def _render_order_details(self, content, buy_orders, sell_orders):
        for w in content.winfo_children():
            w.destroy()

        # 使用 panedwindow 让左右可拖动调整
        pw = tk.PanedWindow(content, orient="horizontal", bg="#f5f5f5",
                            sashrelief=tk.RAISED, sashwidth=3)
        pw.pack(fill="both", expand=True)

        # ── 买单 ──
        buy_frame = tk.Frame(pw, bg="#f0fff0", relief=tk.GROOVE, bd=1)
        pw.add(buy_frame, stretch="always")

        tk.Label(buy_frame, text="💰 买单 (Buy Orders)",
                 font=("Microsoft YaHei UI", 12, "bold"),
                 foreground="#006600", bg="#f0fff0").pack(anchor="w", pady=(5, 3), padx=8)

        if buy_orders:
            self._make_order_table(buy_frame, buy_orders, is_buy=True)
        else:
            tk.Label(buy_frame, text="   无买单数据", font=CJK_FONT,
                     fg="#888888", bg="#f0fff0").pack(anchor="w", padx=8, pady=5)

        # ── 卖单 ──
        sell_frame = tk.Frame(pw, bg="#fff0f0", relief=tk.GROOVE, bd=1)
        pw.add(sell_frame, stretch="always")

        tk.Label(sell_frame, text="📈 卖单 (Sell Orders)",
                 font=("Microsoft YaHei UI", 12, "bold"),
                 foreground="#cc0000", bg="#fff0f0").pack(anchor="w", pady=(5, 3), padx=8)

        if sell_orders:
            self._make_order_table(sell_frame, sell_orders, is_buy=False)
        else:
            tk.Label(sell_frame, text="   无卖单数据", font=CJK_FONT,
                     fg="#888888", bg="#fff0f0").pack(anchor="w", padx=8, pady=5)

        # 提示
        tk.Label(content, text="单击窗口外任意位置关闭  |  Esc 关闭  |  可拖动调整左右宽度",
                 font=("Microsoft YaHei UI", 9), fg="#aaaaaa", bg="#f5f5f5"
                 ).pack(side="bottom", pady=5)

    def _make_order_table(self, parent, orders, is_buy=True):
        """创建订单小表格（含空间站名称）"""
        cols = ("#", "价格", "数量", "空间站")
        tree = ttk.Treeview(parent, columns=cols, show="headings", height=5,
                            selectmode="none")
        tree.column("#", width=30, anchor="center")
        tree.column("价格", width=120, anchor="e")
        tree.column("数量", width=100, anchor="e")
        tree.column("空间站", width=150, anchor="w")
        tree.heading("#", text="#")
        tree.heading("价格", text="价格 (ISK)")
        tree.heading("数量", text="剩余数量")
        tree.heading("空间站", text="空间站")

        tag = "buy" if is_buy else "sell"
        tree.tag_configure("buy", foreground="#006600")
        tree.tag_configure("sell", foreground="#cc0000")

        for i, order in enumerate(orders):
            price = f"{order['price']:,.2f}"
            vol = f"{order['volume_remain']:,}"
            loc_id = order["location_id"]
            station_name = _station_name_cache.get(loc_id, str(loc_id))
            loc_str = f"{station_name} [{loc_id}]"
            tree.insert("", "end", values=(i + 1, price, vol, loc_str), tags=(tag,))

        tree.pack(fill="both", expand=True, padx=5, pady=5)

    def _close_order_popup(self):
        if self._order_popup:
            try:
                if hasattr(self, "_popup_close_bind"):
                    try:
                        self.controller.unbind("<Button-1>", self._popup_close_bind)
                    except:
                        pass
                self._order_popup["popup"].grab_release()
                self._order_popup["popup"].destroy()
            except:
                pass
            self._order_popup = None
