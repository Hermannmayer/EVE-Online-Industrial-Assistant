"""
EVE 商人助手 — PySide6 入口点
运行: python Main.py
"""

import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

from core.null_streams import ensure_console_streams

# --windowed 打包无控制台时 sys.stdout/stderr 为 None，必须先兜底再创建日志 handler，
# 否则 tqdm/logging 第一行输出就抛 "NoneType' object has no attribute 'write'"。
ensure_console_streams()
# PyInstaller 冻结 + 多进程 spawn 需 freeze_support，防止子进程重入主模块挂起
if sys.platform == "win32":
    import multiprocessing

    multiprocessing.freeze_support()

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from core.logger import log  # noqa: E402
from core.paths import (  # noqa: E402
    BP_DB_PATH,
    DB_PATH,
    REF_DB_PATH,
    USR_DB_PATH,
    ensure_dirs_exist,
)


def _migrate_split_db():
    """数据库拆分迁移：将旧 items.db 拆分为 reference.db / market.db / user.db

    只在旧 DB 存在且拆分未完成（无 _split_migration_complete 标记）时执行。
    半途中断后重跑：CREATE IF NOT EXISTS + INSERT OR IGNORE 幂等，可续传。
    迁移完成后 items.db 保留不动（作为备份），所有新代码读写三个新库。
    """
    import sqlite3

    old_db = DB_PATH
    if not os.path.exists(old_db):
        return
    # 以完成标记为准，而非「三个库文件都存在」（半迁移的库文件已存在但数据不完整）
    if os.path.exists(USR_DB_PATH):
        try:
            conn = sqlite3.connect(USR_DB_PATH)
            row = conn.execute("SELECT 1 FROM _split_migration_complete WHERE id = 1").fetchone()
            conn.close()
            if row:
                return
        except sqlite3.Error:
            pass  # 标记表不存在（旧库/半迁移）→ 继续迁移

    log.info("检测到旧版 items.db，正在迁移到拆分数据库...")
    try:
        # 动态导入以避免启动时 import 循环
        from scripts.migrate_split_db import run_migration

        run_migration()
    except Exception:
        log.exception("数据库拆分迁移失败")
        # 不阻止启动，后续仍可手动运行迁移脚本


def _migrate_blueprint_db():
    """将蓝图表从 reference.db 分离到 blueprint.db

    原子性：先写入 blueprint.db.tmp，全部表 COPY + DROP 完成后
    用 os.replace 原子替换正式文件；中途崩溃 → tmp 残留，下次启动
    删除 tmp 重新迁移（reference.db 的蓝图表仍在，可重入）。
    """
    import sqlite3

    if not os.path.exists(REF_DB_PATH):
        return
    if os.path.exists(BP_DB_PATH):
        return

    bp_tables = ["blueprint_activities", "blueprint_materials", "blueprint_products", "blueprint_skills"]

    conn = sqlite3.connect(REF_DB_PATH)
    try:
        c = conn.cursor()
        placeholders = ",".join("?" * len(bp_tables))
        c.execute(
            f"SELECT name FROM sqlite_master WHERE type='table' AND name IN ({placeholders})",
            bp_tables,
        )
        existing = {r[0] for r in c.fetchall()}

        if not existing:
            return

        # 半途中断残留的临时库：删除后重来（所有 COPY/DROP 在同一事务内，
        # 崩溃时 conn.close() 自动回滚，reference.db 的蓝图表必然完好）
        tmp_path = f"{BP_DB_PATH}.tmp"
        if os.path.exists(tmp_path):
            log.info("检测到未完成的蓝图迁移（.tmp 残留），重新迁移")
            os.remove(tmp_path)

        log.info("正在将蓝图表迁移到 blueprint.db...")
        safe_tmp = tmp_path.replace("\\", "/").replace("'", "''")
        conn.execute(f"ATTACH DATABASE '{safe_tmp}' AS bp_db")
        conn.execute("PRAGMA bp_db.journal_mode=WAL")

        for table in bp_tables:
            if table in existing:
                conn.execute(f"CREATE TABLE bp_db.{table} AS SELECT * FROM main.{table}")
                conn.execute(f"DROP TABLE main.{table}")
                log.info("  已迁移: %s", table)

        conn.commit()
        conn.execute("VACUUM")
        conn.close()
        conn = None
        os.replace(tmp_path, BP_DB_PATH)
        log.info("蓝图数据库迁移完成")
    finally:
        if conn is not None:
            conn.close()


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

    HOT_RELOAD = "--hot-reload" in sys.argv

    # -- Single instance lock（前置：失败不闪 splash） --
    from core.single_instance import show_message, try_lock, unlock

    if not try_lock(force="--force" in sys.argv):
        show_message()
        sys.exit(1)

    from PySide6.QtGui import QFont

    app = QApplication(sys.argv)
    app.setApplicationName("EVE 商人助手")
    app.setOrganizationName("EVEAssistant")

    # 设置默认字体（避免系统字体配置中的无效值导致警告）
    app.setFont(QFont("Microsoft YaHei UI", 10))

    # splash 配色与主窗一致（启动早期主题未初始化时先应用偏好）
    import ui_pyside6.theme as theme

    theme.apply_theme(theme.load_theme_preference())

    # -- 启动界面：立即显示 splash，后台完成迁移 + 数据检查 --
    from ui_pyside6.splash_screen import SplashScreen

    splash = SplashScreen()
    splash.show()

    # 其余启动初始化在 splash 显示后进行（不阻塞首帧）
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

    if "--debug" in sys.argv:
        from core.logger import set_debug

        set_debug(True)
        log.debug("调试模式已启用")

    from services.database_manager import get_db

    app.aboutToQuit.connect(unlock)
    app.aboutToQuit.connect(get_db().close_all)

    from ui_pyside6.workers.startup_worker import StartupCheckWorker

    worker = StartupCheckWorker(parent=splash)
    worker.stage.connect(splash.set_stage)
    worker.component_checked.connect(splash.set_component)

    def _on_startup_done(ready: bool, missing_keys: list):
        from ui_pyside6.main_window import MainWindow

        if ready:
            win = MainWindow(hot_reload=HOT_RELOAD)  # splash 仍在屏，构建期无空白

            def _show_main():
                win.show()
                splash.close()

            splash.complete(_show_main)
        else:
            # 有缺失 → 转交 InitWizard 自动下载（splash 已查过，免二次扫描）
            from ui_pyside6.views.init_wizard import InitWizard

            def _show_wizard_then_main():
                InitWizard(auto_mode=True, prechecked_missing=missing_keys).exec()
                MainWindow(hot_reload=HOT_RELOAD).show()

            splash.complete(_show_wizard_then_main)

    worker.finished_all.connect(_on_startup_done)
    worker.start()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
