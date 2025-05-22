import tkinter as tk
import sqlite3
import ctldata
class MainApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("eve 制造助手")
        self.geometry("1280x720")

        # 创建容器
        self.container = tk.Frame(self)
        self.container.pack(fill="both", expand=True)

        # 存储页面
        self.frames = {}

        for F in (QueryPage, IndustryPage, TradePage, WarehousePage):
            page_name = F.__name__
            frame = F(parent=self.container, controller=self)
            self.frames[page_name] = frame
            frame.grid(row=0, column=0, sticky="nsew")

        self.show_frame("QueryPage")

        # 顶部导航栏
        nav = tk.Frame(self)
        nav.pack(side="top", fill="x")
        for text, page in [("查询物品", "QueryPage"), ("工业", "IndustryPage"), ("贸易", "TradePage"), ("仓库", "WarehousePage")]:
            tk.Button(nav, text=text, command=lambda p=page: self.show_frame(p)).pack(side="left", expand=True, fill="x")

        # 让container中的frame扩展填充
        self.container.grid_rowconfigure(0, weight=1)
        self.container.grid_columnconfigure(0, weight=1)

    def show_frame(self, page_name):
        frame = self.frames[page_name]
        frame.tkraise()

class QueryPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # 居中Label
        label = tk.Label(self, text="查询物品", font=("Arial", 16))
        label.grid(row=0, column=0, pady=10, sticky="n")

        # 搜索框和按钮（居中）
        search_frame = tk.Frame(self)
        search_frame.grid(row=1, column=0, pady=5, sticky="n")
        self.search_var = tk.StringVar()
        entry = tk.Entry(search_frame, textvariable=self.search_var, width=30, justify="center")
        entry.pack(side="left", padx=5)
        search_btn = tk.Button(search_frame, text="搜索", command=self.search_item)
        search_btn.pack(side="left")

        # 查询结果显示（居中）
        self.result_text = tk.Text(self, height=10, width=40)
        self.result_text.grid(row=2, column=0, pady=10, sticky="n")
        self.result_text.tag_configure("center", justify='center')

    def search_item(self):
        query = self.search_var.get()
        self.result_text.delete(1.0, tk.END)
        if not query:
            self.result_text.insert(tk.END, "请输入搜索内容。", "center")
            return

        try:
            conn = sqlite3.connect("items.db")
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM items WHERE name LIKE ?", ('%' + query + '%',))
            results = cursor.fetchall()
            if results:
                for row in results:
                    self.result_text.insert(tk.END, f"{row}\n", "center")
            else:
                self.result_text.insert(tk.END, "未找到相关物品。", "center")
            conn.close()
        except Exception as e:
            self.result_text.insert(tk.END, f"查询出错: {e}", "center")

class IndustryPage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        label = tk.Label(self, text="工业页面", font=("Arial", 16))
        label.grid(row=0, column=0, pady=20, sticky="n")

class TradePage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        label = tk.Label(self, text="贸易页面", font=("Arial", 16))
        label.grid(row=0, column=0, pady=20, sticky="n")

class WarehousePage(tk.Frame):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # 顶部二级导航栏
        nav = tk.Frame(self)
        nav.grid(row=0, column=0, sticky="ew")
        btn_item = tk.Button(nav, text="物品仓库", command=lambda: self.show_subpage("item"))
        btn_blueprint = tk.Button(nav, text="蓝图仓库", command=lambda: self.show_subpage("blueprint"))
        btn_item.pack(side="left", expand=True, fill="x")
        btn_blueprint.pack(side="left", expand=True, fill="x")

        # 二级页面容器
        self.subpages = {}
        self.subpage_container = tk.Frame(self)
        self.subpage_container.grid(row=1, column=0, sticky="nsew")
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        self.subpages["item"] = ItemWarehousePage(self.subpage_container)
        self.subpages["blueprint"] = BlueprintWarehousePage(self.subpage_container)
        self.subpages["item"].grid(row=0, column=0, sticky="nsew")
        self.subpages["blueprint"].grid(row=0, column=0, sticky="nsew")

        self.show_subpage("item")

    def show_subpage(self, name):
        self.subpages[name].tkraise()

class ItemWarehousePage(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # 导入按钮
        import_btn = tk.Button(self, text="从剪贴板读取数据并导入物品", command=self.import_from_clipboard)
        import_btn.grid(row=0, column=0, pady=10, sticky="ew")

        # 显示区
        self.text = tk.Text(self, height=20)
        self.text.grid(row=1, column=0, sticky="nsew")

    def import_from_clipboard(self):
        try:
            data = self.clipboard_get()
            self.text.delete(1.0, tk.END)
            self.text.insert(tk.END, f"导入物品数据：\n{data}")
            # 这里可以添加解析和入库逻辑
        except Exception as e:
            self.text.delete(1.0, tk.END)
            self.text.insert(tk.END, f"读取剪贴板失败: {e}")

class BlueprintWarehousePage(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # 导入按钮
        import_btn = tk.Button(self, text="从剪贴板读取数据并导入蓝图", command=self.import_from_clipboard)
        import_btn.grid(row=0, column=0, pady=10, sticky="ew")

        # 显示区
        self.text = tk.Text(self, height=20)
        self.text.grid(row=1, column=0, sticky="nsew")

    def import_from_clipboard(self):
        try:
            data = self.clipboard_get()
            self.text.delete(1.0, tk.END)
            self.text.insert(tk.END, f"导入蓝图数据：\n{data}")
            # 这里可以添加解析和入库逻辑
        except Exception as e:
            self.text.delete(1.0, tk.END)
            self.text.insert(tk.END, f"读取剪贴板失败: {e}")

if __name__ == "__main__":
    app = MainApp()
    app.mainloop()
    


