"""
EVE 商人助手 — PySide6 入口点
运行: python Main.py
"""
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from core.logger import log
from core.paths import DB_PATH, REF_DB_PATH, MKT_DB_PATH, USR_DB_PATH, ensure_dirs_exist


def _migrate_split_db():
    """数据库拆分迁移：将旧 items.db 拆分为 reference.db / market.db / user.db

    只在旧 DB 存在且新 DB 尚未创建时执行。
    迁移完成后 items.db 保留不动（作为备份），所有新代码读写三个新库。
    """
    old_db = DB_PATH
    if not os.path.exists(old_db):
        return
    # 如果新库已存在，跳过迁移
    if os.path.exists(REF_DB_PATH) and os.path.exists(MKT_DB_PATH) and os.path.exists(USR_DB_PATH):
        return

    log.info("检测到旧版 items.db，正在迁移到拆分数据库...")
    try:
        # 动态导入以避免启动时 import 循环
        from scripts.migrate_split_db import run_migration
        run_migration()
    except Exception:
        log.exception("数据库拆分迁移失败")
        # 不阻止启动，后续仍可手动运行迁移脚本


def _global_exception_handler(exc_type, exc_value, exc_traceback):
    """全局未捕获异常处理器 — 记录日志并弹窗提示"""
    log.error("未捕获异常",
              exc_info=(exc_type, exc_value, exc_traceback))

    # 写入崩溃转储文件
    try:
        crash_dir = Path.home() / ".eve-assistant" / "crashes"
        crash_dir.mkdir(parents=True, exist_ok=True)
        crash_file = crash_dir / f"crash_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        with open(crash_file, "w", encoding="utf-8") as f:
            traceback.print_exception(exc_type, exc_value, exc_traceback, file=f)
    except Exception:
        pass

    # 仅在非 KeyboardInterrupt 时弹窗
    if not issubclass(exc_type, KeyboardInterrupt):
        try:
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Icon.Critical)
            msg.setWindowTitle("EVE 商人助手 — 发生错误")
            msg.setText("程序遇到了意外错误，请重启应用。")
            msg.setDetailedText(
                "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
            )
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg.exec()
        except Exception:
            pass


def main():
    ensure_dirs_exist()

    # 数据库拆分迁移（items.db → reference.db + market.db + user.db）
    _migrate_split_db()

    # 调试模式: python Main.py --debug
    if "--debug" in sys.argv:
        from core.logger import set_debug
        set_debug(True)
        log.debug("调试模式已启用")

    # 注册全局异常处理器
    sys.excepthook = _global_exception_handler

    app = QApplication(sys.argv)
    app.setApplicationName("EVE 商人助手")
    app.setOrganizationName("EVEAssistant")

    from ui_pyside6.main_window import MainWindow
    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
