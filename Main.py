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
from core.paths import BP_DB_PATH, DB_PATH, MKT_DB_PATH, REF_DB_PATH, USR_DB_PATH, ensure_dirs_exist


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


def _migrate_blueprint_db():
    """将蓝图表从 reference.db 分离到 blueprint.db"""
    import sqlite3

    if not os.path.exists(REF_DB_PATH):
        return
    if os.path.exists(BP_DB_PATH):
        return

    bp_tables = ["blueprint_activities", "blueprint_materials", "blueprint_products", "blueprint_skills"]

    conn = sqlite3.connect(REF_DB_PATH)
    c = conn.cursor()
    placeholders = ",".join("?" * len(bp_tables))
    c.execute(
        f"SELECT name FROM sqlite_master WHERE type='table' AND name IN ({placeholders})",
        bp_tables,
    )
    existing = {r[0] for r in c.fetchall()}

    if not existing:
        conn.close()
        return

    log.info("正在将蓝图表迁移到 blueprint.db...")
    bp_path = BP_DB_PATH.replace("\\", "/")
    safe_path = bp_path.replace("'", "''")
    conn.execute(f"ATTACH DATABASE '{safe_path}' AS bp_db")
    conn.execute("PRAGMA bp_db.journal_mode=WAL")

    for table in bp_tables:
        if table in existing:
            conn.execute(f"CREATE TABLE bp_db.{table} AS SELECT * FROM main.{table}")
            conn.execute(f"DROP TABLE main.{table}")
            log.info(f"  已迁移: {table}")

    conn.commit()
    conn.execute("VACUUM")
    conn.close()
    log.info("蓝图数据库迁移完成")


def _global_exception_handler(exc_type, exc_value, exc_traceback):
    """全局未捕获异常处理器 — 记录日志并弹窗提示"""
    log.error("未捕获异常", exc_info=(exc_type, exc_value, exc_traceback))

    # 写入崩溃转储文件
    try:
        crash_dir = Path.home() / ".eve-assistant" / "crashes"
        crash_dir.mkdir(parents=True, exist_ok=True)
        crash_file = crash_dir / f"crash_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        with open(crash_file, "w", encoding="utf-8") as f:
            traceback.print_exception(exc_type, exc_value, exc_traceback, file=f)
    except Exception:
        log.exception("写入崩溃转储失败")

    # 仅在非 KeyboardInterrupt 时弹窗
    if not issubclass(exc_type, KeyboardInterrupt):
        try:
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Icon.Critical)
            msg.setWindowTitle("EVE 商人助手 — 发生错误")
            msg.setText("程序遇到了意外错误，请重启应用。")
            msg.setDetailedText("".join(traceback.format_exception(exc_type, exc_value, exc_traceback)))
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg.exec()
        except Exception:
            pass


def main():
    ensure_dirs_exist()

    _migrate_split_db()
    _migrate_blueprint_db()

    # 执行 Schema 迁移（wastefactor 列等）
    from services.schema_migrations import ensure_all_schemas

    ensure_all_schemas()

    from services.inventory_manager import init_db

    init_db()

    if "--debug" in sys.argv:
        from core.logger import set_debug

        set_debug(True)
        log.debug("调试模式已启用")

    sys.excepthook = _global_exception_handler

    # 自定义 Qt 消息处理器，过滤字体大小警告
    from PySide6.QtCore import QtMsgType, qInstallMessageHandler

    def _qt_message_handler(msg_type, context, message):
        if "QFont::setPointSize" in message and "Point size <= 0" in message:
            return  # 过滤字体大小警告
        # 其他消息正常处理
        if msg_type == QtMsgType.QtDebugMsg:
            log.debug(message)
        elif msg_type == QtMsgType.QtWarningMsg:
            log.warning(message)
        elif msg_type == QtMsgType.QtCriticalMsg:
            log.error(message)
        elif msg_type == QtMsgType.QtFatalMsg:
            log.critical(message)

    qInstallMessageHandler(_qt_message_handler)

    app = QApplication(sys.argv)
    app.setApplicationName("EVE 商人助手")
    app.setOrganizationName("EVEAssistant")

    # 设置默认字体（避免系统字体配置中的无效值导致警告）
    from PySide6.QtGui import QFont

    default_font = QFont("Microsoft YaHei UI", 10)
    app.setFont(default_font)

    # -- Single instance lock --
    from PySide6.QtCore import QTimer

    from core.single_instance import show_message, try_lock, unlock

    if not try_lock(force="--force" in sys.argv):
        show_message()
        QTimer.singleShot(2000, app.quit)
        sys.exit(app.exec())
        return

    app.aboutToQuit.connect(unlock)

    # -- Hot reload --
    HOT_RELOAD = "--hot-reload" in sys.argv

    from ui_pyside6.main_window import MainWindow

    window = MainWindow(hot_reload=HOT_RELOAD)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
