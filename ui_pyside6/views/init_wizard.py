"""
数据初始化向导 — subprocess 调用 tools/init.py

每个步骤通过 subprocess 在独立进程中执行，
不阻塞主程序 UI，也不再直接 import 初始化模块。
"""

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

import ui_pyside6.theme as theme
from services.init_check import check_all

# 项目根目录（用于定位 tools/init.py）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TOOLS_INIT = str(_PROJECT_ROOT / "tools" / "init.py")

# 步骤定义：名称, key, 是否需要网络
STEPS = [
    ("物品数据", "items", True),
    ("市场价格", "prices", True),
    ("蓝图数据", "blueprints", True),
    ("植入体数据", "implants", True),
    ("工业数据", "industry", True),
    ("物品图标", "icons", True),
    ("SDE扩展数据", "sde_data", False),
]


class InitStepWorker(QThread):
    """在后台线程运行一个初始化步骤"""

    result = Signal(str, bool, str)  # step_key, success, message

    def __init__(self, step_key: str, parent=None):
        super().__init__(parent)
        self._key = step_key

    def run(self):
        try:
            proc = subprocess.run(
                [sys.executable, TOOLS_INIT, "--step", self._key],
                capture_output=True,
                text=True,
                timeout=1800,  # 30 min per step
            )
            ok = proc.returncode == 0
            msg = proc.stdout.strip().split("\n")[-1] if proc.stdout else ""
            if not ok and proc.stderr:
                msg = proc.stderr.strip().split("\n")[-1]
            self.result.emit(self._key, ok, msg or ("完成" if ok else "失败"))
        except subprocess.TimeoutExpired:
            self.result.emit(self._key, False, "超时")
        except Exception as e:
            self.result.emit(self._key, False, str(e))


class InitWizard(QDialog):
    """数据初始化向导"""

    def __init__(self, parent=None, on_done=None):
        super().__init__(parent)
        self.setWindowTitle("数据初始化")
        self.setMinimumSize(480, 400)
        self.setStyleSheet(f"background-color: {theme.BG_DARK};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        # 标题
        title = QLabel("数据初始化")
        title.setStyleSheet(f"color: {theme.PRIMARY}; font-size: 16px; font-weight: bold;")
        layout.addWidget(title)

        desc = QLabel("需要下载游戏数据才能使用全部功能。已就绪的组件会自动跳过。")
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12px;")
        layout.addWidget(desc)

        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"background-color: {theme.BORDER}; border: none;")
        line.setFixedHeight(1)
        layout.addWidget(line)

        # 步骤状态列表
        self._step_rows = {}
        status = self._build_display("init")
        layout.addLayout(status)

        # 进度条
        self._progress = QProgressBar()
        self._progress.setRange(0, len(STEPS))
        self._progress.setValue(0)
        self._progress.setTextVisible(True)
        self._progress.setStyleSheet(f"""
            QProgressBar {{
                background-color: {theme.BG_SURFACE};
                border: 1px solid {theme.BORDER};
                border-radius: 4px;
                height: 20px;
                text-align: center;
                color: {theme.TEXT_PRIMARY};
                font-size: 12px;
            }}
            QProgressBar::chunk {{
                background-color: {theme.PRIMARY};
                border-radius: 3px;
            }}
        """)
        layout.addWidget(self._progress)

        # 当前状态
        self._status_label = QLabel("就绪")
        self._status_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12px;")
        layout.addWidget(self._status_label)

        # 按钮
        btn_bar = QHBoxLayout()
        btn_bar.addStretch()

        self._run_btn = QPushButton("开始初始化")
        self._run_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme.PRIMARY};
                color: {theme.TEXT_ON_PRIMARY};
                border: none;
                border-radius: 6px;
                padding: 8px 24px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {theme.BG_HOVER}; }}
            QPushButton:disabled {{ background-color: {theme.TEXT_SECONDARY}; }}
        """)
        self._run_btn.clicked.connect(self._run_all)
        btn_bar.addWidget(self._run_btn)

        close_btn = QPushButton("关闭")
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme.BG_SURFACE};
                color: {theme.TEXT_PRIMARY};
                border: 1px solid {theme.BORDER};
                border-radius: 6px;
                padding: 8px 20px;
            }}
            QPushButton:hover {{ background-color: {theme.BORDER}; }}
        """)
        close_btn.clicked.connect(self._hide_wizard)
        btn_bar.addWidget(close_btn)

        layout.addLayout(btn_bar)

        self._on_done_callback = on_done
        self._current_idx = 0
        self._worker: InitStepWorker | None = None
        self._workers: list[InitStepWorker] = []
        self._step_names = {key: name for name, key, _ in STEPS}

        # 启动时刷新状态
        self._refresh_status()

    def showEvent(self, ev):
        """showEvent 时重新应用当前主题样式表"""
        super().showEvent(ev)
        self.setStyleSheet(f"background-color: {theme.BG_DARK};")

    def _build_display(self, prefix: str):
        """构建步骤状态显示"""
        layout = QVBoxLayout()
        layout.setSpacing(6)

        for name, key, _ in STEPS:
            row = QHBoxLayout()
            self._step_rows[key] = QLabel("⏸️")
            self._step_rows[key].setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 14px;")
            row.addWidget(self._step_rows[key])

            name_label = QLabel(name)
            name_label.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; font-size: 13px;")
            row.addWidget(name_label)

            row.addStretch()
            layout.addLayout(row)

        return layout

    def _refresh_status(self):
        """刷新所有步骤状态（从 DB 检查）"""
        status = check_all()
        done = 0
        for name, key, _ in STEPS:
            if status.get(key, False):
                self._step_rows[key].setText(" ✅")
                self._step_rows[key].setStyleSheet(f"color: {theme.ACCENT_GREEN}; font-size: 14px;")
                done += 1
            else:
                self._step_rows[key].setText(" ⏸️")
                self._step_rows[key].setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 14px;")
        self._progress.setValue(done)

    def _run_all(self):
        """开始按顺序执行所有步骤"""
        self._current_idx = 0
        self._run_btn.setEnabled(False)
        self._progress.setValue(0)
        self._status_label.setText("开始初始化...")
        self._status_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12px;")
        # 重置所有状态
        for key in self._step_rows:
            self._step_rows[key].setText(" ⏸️")
            self._step_rows[key].setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 14px;")

        self._run_next()

    def _run_next(self):
        """运行下一个未完成的步骤"""
        # 跳过已完成的
        status = check_all()
        while self._current_idx < len(STEPS):
            _, key, _ = STEPS[self._current_idx]
            if not status.get(key, False):
                break
            self._progress.setValue(self._current_idx + 1)
            self._current_idx += 1

        if self._current_idx >= len(STEPS):
            self._on_all_done()
            return

        name, key, _ = STEPS[self._current_idx]
        self._step_rows[key].setText(" ⏳")
        self._step_rows[key].setStyleSheet(f"color: {theme.PRIMARY}; font-size: 14px;")
        self._status_label.setText(f"正在下载：{name}...")
        self._status_label.setStyleSheet(f"color: {theme.PRIMARY}; font-size: 12px;")

        self._worker = InitStepWorker(key, None)
        self._workers.append(self._worker)
        self._worker.result.connect(self._on_step_done)
        self._worker.start()

    def _on_step_done(self, step_key: str, success: bool, message: str):
        name = self._step_names.get(step_key, step_key)
        if success:
            self._step_rows[step_key].setText(" ✅")
            self._step_rows[step_key].setStyleSheet(f"color: {theme.ACCENT_GREEN}; font-size: 14px;")
            self._status_label.setText(f"✓ {name} 完成")
            self._status_label.setStyleSheet(f"color: {theme.ACCENT_GREEN}; font-size: 12px;")
        else:
            self._step_rows[step_key].setText(" ❌")
            self._step_rows[step_key].setStyleSheet(f"color: {theme.ACCENT_RED}; font-size: 14px;")
            self._status_label.setText(f"✗ {name} 失败：{message}")
            self._status_label.setStyleSheet(f"color: {theme.ACCENT_RED}; font-size: 12px;")
            if self.isVisible():
                QMessageBox.warning(self, "初始化错误", f"{step_key}: {message}")

        self._current_idx += 1
        self._progress.setValue(self._current_idx)
        self._run_next()

    def _on_all_done(self):
        self._run_btn.setEnabled(True)
        self._progress.setValue(len(STEPS))
        self._status_label.setText("初始化完成！")
        self._status_label.setStyleSheet(f"color: {theme.ACCENT_GREEN}; font-size: 12px;")
        if self.isVisible():
            QMessageBox.information(
                self,
                "完成",
                "数据初始化完成！\n\n现在可以将 database/ 目录随程序一起打包分发，其他用户无需再次下载。",
            )
        if self._on_done_callback:
            self._on_done_callback()

    def _hide_wizard(self):
        """关闭窗口但不停止后台初始化"""
        self.hide()
        self._status_label.setText("后台运行中...")
        self._status_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12px;")

    def closeEvent(self, event: QCloseEvent):
        """窗口 X 按钮：隐藏而非关闭，保持后台运行"""
        event.ignore()
        self._hide_wizard()

    def reject(self):
        """ESC 键：隐藏而非关闭"""
        self._hide_wizard()
