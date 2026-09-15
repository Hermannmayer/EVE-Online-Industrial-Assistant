"""
EVE 商人助手 — PySide6 入口点
运行: python Main.py
"""

import os
import sys
import threading
import traceback

from core.null_streams import ensure_console_streams

# --windowed 打包无控制台时 sys.stdout/stderr 为 None，必须先兜底再创建日志 handler，
# 否则 tqdm/logging 第一行输出就抛 "NoneType' object has no attribute 'write'"。
ensure_console_streams()
# PyInstaller 冻结 + 多进程 spawn 需 freeze_support，防止子进程重入主模块挂起
if sys.platform == "win32":
    import multiprocessing

    multiprocessing.freeze_support()

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from core.diagnostics import install_background_hooks, write_crash_dump  # noqa: E402
from core.logger import log, prune_logs  # noqa: E402
from core.paths import (  # noqa: E402
    BP_DB_PATH,
    DB_PATH,
    REF_DB_PATH,
    USR_DB_PATH,
    crashes_dir,
    ensure_dirs_exist,
    log_dir,
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
    """全局未捕获异常处理器 — 记录日志、写崩溃转储并弹窗提示"""
    # Ctrl+C 不是崩溃。照常写崩溃转储只会在 crashes/ 里堆垃圾，弹窗更会挡着退出。
    # 必须主动退出：Qt 事件循环不处理 SIGINT，这个异常只会在某个槽函数里冒出来，
    # 吞掉它就表现为「Ctrl+C 按了没反应」。
    if issubclass(exc_type, KeyboardInterrupt):
        log.info("收到 Ctrl+C，退出")
        app = QApplication.instance()
        if app is not None:
            app.quit()
        else:
            sys.exit(130)
        return

    log.error("未捕获异常", exc_info=(exc_type, exc_value, exc_traceback))
    write_crash_dump((exc_type, exc_value, exc_traceback))

    # 弹窗只在主线程且 QApplication 已创建时进行：后台线程建窗是 Qt 跨线程违规，
    # QApplication 未就绪时 exec() 会挂死。后台线程崩溃只落盘不弹窗。
    if threading.current_thread() is threading.main_thread() and QApplication.instance() is not None:
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


def _make_shell(hot_reload: bool):
    """造主窗口。

    默认是 **QML 外壳**（阶段 5 / 批次 6.1，`ui_qml.shell_window.ShellWindow`）；
    设 `EVE_WIDGETS_SHELL=1` 回退到 Widgets 外壳（`ui_pyside6.main_window.MainWindow`）。

    回退开关是**过渡期的安全带**：QML 外壳一旦在真机上出问题，不用改代码就能切回去
    （改文件 + 重新打包的代价太高）。两套外壳共用同一份页面桥与业务，
    切换只影响外框与页面宿主。
    """
    if os.environ.get("EVE_WIDGETS_SHELL") == "1":
        from ui_pyside6.main_window import MainWindow

        return MainWindow(hot_reload=hot_reload)

    from ui_qml.shell_window import ShellWindow

    return ShellWindow(hot_reload=hot_reload)


def main():
    ensure_dirs_exist()

    # 尽早安装崩溃钩子：threading.excepthook 兜底后台线程、faulthandler 捕获原生段错误、
    # sys.excepthook 在主线程未捕获异常时写崩溃转储（弹窗守卫保证 QApplication 未创建时跳过）
    install_background_hooks()
    prune_logs(log_dir(), crashes_dir())
    sys.excepthook = _global_exception_handler

    HOT_RELOAD = "--hot-reload" in sys.argv

    # -- Single instance lock（前置：失败不闪 splash） --
    from core.single_instance import show_message, try_lock, unlock

    if not try_lock(force="--force" in sys.argv):
        show_message()
        sys.exit(1)

    app = QApplication(sys.argv)
    app.setApplicationName("EVE 商人助手")
    app.setOrganizationName("EVEAssistant")

    # QML 控件样式：微软 Fluent WinUI3（由 Qt 官方维护，源自微软 Fluent Figma）。
    # 必须在加载任何 QML 之前设置。失败不致命——ui_qml 的页面会回退到 Widgets 版。
    try:
        from PySide6.QtQuickControls2 import QQuickStyle

        QQuickStyle.setStyle("FluentWinUI3")
    except Exception:
        log.warning("QQuickStyle 不可用，QML 页面将回退 Widgets 版", exc_info=True)

    # splash 配色与主窗一致（启动早期主题未初始化时先应用偏好）
    import ui_pyside6.theme as theme

    # 默认字体随「全局字号」设置；apply_theme 内部会同步 QApplication 字体，
    # 早于此处设置可避免系统字体配置中的无效值导致警告
    theme.set_font_scale(theme.load_font_scale())
    theme.apply_theme(theme.load_theme_preference())

    # -- 启动界面：立即显示 splash，后台完成迁移 + 数据检查 --
    from ui_pyside6.splash_screen import SplashScreen

    splash = SplashScreen()
    splash.show()

    # 其余启动初始化在 splash 显示后进行（不阻塞首帧）

    # 自定义 Qt 消息处理器，过滤字体大小警告
    from PySide6.QtCore import QtMsgType, qInstallMessageHandler

    from core import qt_noise

    def _qt_message_handler(msg_type, context, message):
        if "QFont::setPointSize" in message and "Point size <= 0" in message:
            return  # 过滤字体大小警告
        # 退出期 Qt 自带 QML 的拆除噪音（点关闭后成片刷屏，见 core.qt_noise）：
        # 只丢「退出已开始 + 出自 qrc:/qt-project.org/」这一种，运行期照旧记录
        if qt_noise.shutting_down() and qt_noise.is_qt_internal_qml(message):
            return
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

    from PySide6.QtCore import QObject, Slot

    class _StartupHandler(QObject):
        """启动检查完成后的处理者。

        **必须是 QObject 的绑定方法，不能把普通函数直接当槽连过去**：
        `worker` 是 QThread，PySide 对普通 Python 可调用对象用 DirectConnection，
        回调会在**工作线程**上执行，于是 MainWindow 在非 GUI 线程里被构造。
        以前这里只创建 QWidget 侥幸能跑；加入 QML 页面后
        `QQuickWidget.setSource()` 会同步等待 QML 线程，跨线程调用直接死锁
        （现象：启动卡在 0%，无任何报错）。用绑定方法后 Qt 按接收者所在线程
        （GUI 线程）排队投递，这才是安全的。
        """

        @Slot(bool, list)
        def handle(self, ready: bool, missing_keys: list) -> None:
            if ready:
                win = _make_shell(HOT_RELOAD)  # splash 仍在屏，构建期无空白

                def _show_main():
                    win.show()
                    splash.close()

                splash.complete(_show_main)
            else:
                # 有缺失 → 转交 InitWizard 自动下载（splash 已查过，免二次扫描）
                from ui_qml.bridge.init_wizard_bridge import InitWizardQmlDialog as InitWizard

                def _show_wizard_then_main():
                    InitWizard(auto_mode=True, prechecked_missing=missing_keys).exec()
                    _make_shell(HOT_RELOAD).show()

                splash.complete(_show_wizard_then_main)

    # 持有强引用：handler 若被回收，连接会失效
    _startup_handler = _StartupHandler()
    worker.finished_all.connect(_startup_handler.handle)
    worker.start()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
