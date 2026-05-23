"""
数据初始化向导 — 逐步运行各初始化脚本
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QFrame, QMessageBox,
)
from PySide6.QtCore import Qt, QThread, Signal

from ui_pyside6.theme import (
    BG_DARK, BG_SURFACE, PRIMARY, TEXT_PRIMARY, TEXT_SECONDARY,
    ACCENT_GREEN, ACCENT_RED, BORDER,
)
from services.init_check import check_all, missing_count


# 初始化步骤：名称, 检查函数, 是否需要网络
STEPS = [
    ("物品数据", "items", "getitems", True),
    ("市场价格", "prices", "getprices", True),
    ("蓝图数据", "blueprints", "getblueprints", False),
    ("植入体数据", "implants", "getimplantdata", True),
    ("物品图标", "icons", "geticon", True),
]


class InitStepWorker(QThread):
    """在后台线程运行一个初始化步骤"""
    result = Signal(str, bool, str)  # step_key, success, message

    def __init__(self, module_name: str, step_key: str, parent=None):
        super().__init__(parent)
        self._module = module_name
        self._key = step_key

    def run(self):
        try:
            import importlib
            import asyncio

            if self._module == "getitems":
                from services.workers.getitems import main
                asyncio.run(main())
            elif self._module == "getprices":
                from services.workers.getprices import run_price_update
                run_price_update()
            elif self._module == "getblueprints":
                from services.workers.getblueprints import run_blueprint_update
                asyncio.run(run_blueprint_update())
            elif self._module == "getimplantdata":
                from services.workers.getimplantdata import main
                asyncio.run(main())
            elif self._module == "geticon":
                from services.workers.geticon import main
                asyncio.run(main())
            else:
                self.result.emit(self._key, False, f"未知步骤: {self._module}")
                return

            self.result.emit(self._key, True, "完成")
        except Exception as e:
            self.result.emit(self._key, False, str(e))


class InitWizard(QDialog):
    """数据初始化向导"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("数据初始化")
        self.setMinimumSize(480, 400)
        self.setStyleSheet(f"background-color: {BG_DARK};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        # 标题
        title = QLabel("首次启动 — 数据初始化")
        title.setStyleSheet(f"color: {PRIMARY}; font-size: 16px; font-weight: bold;")
        layout.addWidget(title)

        desc = QLabel("需要下载游戏数据才能使用全部功能。已就绪的组件会自动跳过。")
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        layout.addWidget(desc)

        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"background-color: {BORDER}; border: none;")
        line.setFixedHeight(1)
        layout.addWidget(line)

        # 步骤状态列表
        self._step_rows = {}
        status = self._build_display("init")
        layout.addLayout(status)

        # 进度条
        self._progress = QProgressBar()
        self._progress.setRange(0, 5)
        self._progress.setValue(0)
        self._progress.setTextVisible(True)
        self._progress.setStyleSheet(f"""
            QProgressBar {{
                background-color: {BG_SURFACE};
                border: 1px solid {BORDER};
                border-radius: 4px;
                height: 20px;
                text-align: center;
                color: {TEXT_PRIMARY};
                font-size: 12px;
            }}
            QProgressBar::chunk {{
                background-color: {PRIMARY};
                border-radius: 3px;
            }}
        """)
        layout.addWidget(self._progress)

        # 按钮
        btn_bar = QHBoxLayout()
        btn_bar.addStretch()

        self._run_btn = QPushButton("开始初始化")
        self._run_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {PRIMARY};
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 24px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background-color: #5199e0; }}
            QPushButton:disabled {{ background-color: {TEXT_SECONDARY}; }}
        """)
        self._run_btn.clicked.connect(self._run_all)
        btn_bar.addWidget(self._run_btn)

        close_btn = QPushButton("关闭")
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {BG_SURFACE};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER};
                border-radius: 6px;
                padding: 8px 20px;
            }}
            QPushButton:hover {{ background-color: {BORDER}; }}
        """)
        close_btn.clicked.connect(self.accept)
        btn_bar.addWidget(close_btn)

        layout.addLayout(btn_bar)

        self._current_idx = 0
        self._worker: InitStepWorker | None = None

        # 启动时刷新状态
        self._refresh_status()

    def _build_display(self, prefix: str):
        """构建步骤状态显示"""
        layout = QVBoxLayout()
        layout.setSpacing(6)

        for name, key, _, _ in STEPS:
            row = QHBoxLayout()
            # 状态图标
            self._step_rows[key] = QLabel("⏸️")
            self._step_rows[key].setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 14px;")
            row.addWidget(self._step_rows[key])

            # 步骤名称
            name_label = QLabel(name)
            name_label.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px;")
            row.addWidget(name_label)

            row.addStretch()
            layout.addLayout(row)

        return layout

    def _refresh_status(self):
        """刷新所有步骤状态（从 DB 检查）"""
        status = check_all()
        done = 0
        for name, key, _, _ in STEPS:
            if status.get(key, False):
                self._step_rows[key].setText(" ✅")
                self._step_rows[key].setStyleSheet(f"color: {ACCENT_GREEN}; font-size: 14px;")
                done += 1
            else:
                self._step_rows[key].setText(" ⏸️")
                self._step_rows[key].setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 14px;")
        self._progress.setValue(done)

    def _run_all(self):
        """开始按顺序执行所有步骤"""
        self._current_idx = 0
        self._run_btn.setEnabled(False)
        self._progress.setValue(0)
        # 重置所有状态
        for key in self._step_rows:
            self._step_rows[key].setText(" ⏸️")
            self._step_rows[key].setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 14px;")

        self._run_next()

    def _run_next(self):
        """运行下一个未完成的步骤"""
        # 跳过已完成的
        status = check_all()
        while self._current_idx < len(STEPS):
            _, key, module, _ = STEPS[self._current_idx]
            if not status.get(key, False):
                break
            self._progress.setValue(self._current_idx + 1)
            self._current_idx += 1

        if self._current_idx >= len(STEPS):
            self._on_all_done()
            return

        name, key, module, _ = STEPS[self._current_idx]
        self._step_rows[key].setText(" ⏳")
        self._step_rows[key].setStyleSheet(f"color: {PRIMARY}; font-size: 14px;")

        self._worker = InitStepWorker(module, key, self)
        self._worker.result.connect(self._on_step_done)
        self._worker.start()

    def _on_step_done(self, step_key: str, success: bool, message: str):
        if success:
            self._step_rows[step_key].setText(" ✅")
            self._step_rows[step_key].setStyleSheet(f"color: {ACCENT_GREEN}; font-size: 14px;")
        else:
            self._step_rows[step_key].setText(" ❌")
            self._step_rows[step_key].setStyleSheet(f"color: {ACCENT_RED}; font-size: 14px;")
            # 显示错误但继续
            QMessageBox.warning(self, "初始化错误", f"{step_key}: {message}")

        self._current_idx += 1
        self._progress.setValue(self._current_idx)
        self._run_next()

    def _on_all_done(self):
        self._run_btn.setEnabled(True)
        self._progress.setValue(5)
        QMessageBox.information(
            self, "完成",
            "数据初始化完成！\n\n"
            "现在可以将 items.db 和 data/ 目录随程序一起打包分发，"
            "其他用户无需再次下载。"
        )
