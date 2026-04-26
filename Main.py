"""
EVE 制造助手 — 入口点
"""
import tkinter as tk
import sqlite3
import subprocess
import threading
import os
from datetime import datetime, timezone, timedelta
from ui.views import QueryPage, IndustryPage, TradePage, WarehousePage
from ui.config import DB_PATH, CJK_FONT, load_window_geometry, bind_geometry_persistence, save_window_geometry


class MainApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("EVE 制造助手")
        default_geo = load_window_geometry("MainApp", "1280x720")
        self.geometry(default_geo)
        self.minsize(1024, 600)

        # 窗口关闭时保存几何位置
        self.bind("<Destroy>", lambda e: save_window_geometry("MainApp", self.geometry()), add="+")
        bind_geometry_persistence(self, "MainApp")

        # 页面容器（导航栏下方，状态栏上方的主区域）
        self.container = tk.Frame(self)
        self.container.pack(fill="both", expand=True)
        self.container.grid_rowconfigure(0, weight=1)
        self.container.grid_columnconfigure(0, weight=1)

        # 初始化所有页面
        self.frames = {}
        for F in (QueryPage, IndustryPage, TradePage, WarehousePage):
            page_name = F.__name__
            frame = F(parent=self.container, controller=self)
            self.frames[page_name] = frame
            frame.grid(row=0, column=0, sticky="nsew")

        # 注意：show_frame 必须在底部状态栏创建之后调用，
        # 因为 refresh_price_time 需要访问 price_time_var

        # ── 顶部导航栏 ──
        nav = tk.Frame(self, bg="#e0e0e0")
        nav.pack(side="top", fill="x")
        for text, page in [
            ("查询物品", "QueryPage"),
            ("工业", "IndustryPage"),
            ("贸易", "TradePage"),
            ("仓库", "WarehousePage"),
        ]:
            btn = tk.Button(
                nav, text=text, font=CJK_FONT,
                relief=tk.FLAT, padx=20, pady=6,
                command=lambda p=page: self.show_frame(p)
            )
            btn.pack(side="left", expand=True, fill="x")

        # ── 底部状态栏 ──
        bottom_bar = tk.Frame(self, bg="#f0f0f0", relief=tk.SUNKEN, bd=1)
        bottom_bar.pack(side="bottom", fill="x")

        self.price_time_var = tk.StringVar()
        self.price_time_var.set("价格更新时间: —")
        time_label = tk.Label(
            bottom_bar, textvariable=self.price_time_var,
            font=('Microsoft YaHei UI', 9), fg="#555555",
            bg="#f0f0f0", padx=10
        )
        time_label.pack(side="left")

        self.update_btn = tk.Button(
            bottom_bar, text="🔄 更新价格", font=('Microsoft YaHei UI', 9),
            command=self.trigger_price_update, padx=10
        )
        self.update_btn.pack(side="right", padx=10, pady=2)

        self.update_status_var = tk.StringVar()
        self.update_status_var.set("")
        status_label = tk.Label(
            bottom_bar, textvariable=self.update_status_var,
            font=('Microsoft YaHei UI', 9), fg="#888888",
            bg="#f0f0f0", padx=10
        )
        status_label.pack(side="right")

        # 最后显示默认页面（此时所有 UI 组件已创建）
        self.show_frame("QueryPage")

    def show_frame(self, page_name):
        self.frames[page_name].tkraise()
        if page_name == "QueryPage":
            self.refresh_price_time()

    def refresh_price_time(self):
        """查询数据库中最新的价格更新时间"""
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
                    self.price_time_var.set(f"价格更新时间: {bj_str} (北京)")
                except:
                    self.price_time_var.set(f"价格更新时间: {utc_str} UTC")
            else:
                self.price_time_var.set("价格更新时间: 暂无数据")
        except Exception:
            self.price_time_var.set("价格更新时间: 数据库未就绪")

    def trigger_price_update(self):
        """在新线程中运行 getprices.py，避免阻塞UI"""
        if hasattr(self, '_updating') and self._updating:
            return
        self._updating = True
        self.update_btn.config(state=tk.DISABLED, text="⏳ 更新中...")
        self.update_status_var.set("正在抓取市场价格...")

        def run_update():
            try:
                result = subprocess.run(
                    ["python", "getprices.py"],
                    capture_output=True, text=True, timeout=600,
                )

                def on_done():
                    self._updating = False
                    self.update_btn.config(state=tk.NORMAL, text="🔄 更新价格")
                    if result.returncode == 0:
                        self.update_status_var.set("✅ 价格更新完成")
                        self.refresh_price_time()
                        qp = self.frames.get("QueryPage")
                        if qp and hasattr(qp, 'refresh_display'):
                            qp.refresh_display()
                    else:
                        self.update_status_var.set("❌ 更新失败，请查看控制台")
                    self.after(4000, lambda: self.update_status_var.set(""))

                self.after(0, on_done)
            except Exception as e:

                def on_error():
                    self._updating = False
                    self.update_btn.config(state=tk.NORMAL, text="🔄 更新价格")
                    self.update_status_var.set(f"❌ {str(e)}")

                self.after(0, on_error)

        thread = threading.Thread(target=run_update, daemon=True)
        thread.start()


if __name__ == "__main__":
    app = MainApp()
    app.mainloop()
