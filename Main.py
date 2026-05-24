"""
EVE 商人助手 — PySide6 入口点
运行: python Main.py
"""
import sqlite3
import sys
import traceback
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from core.logger import log
from core.paths import DB_PATH, database_path


def _migrate_db():
    """数据库迁移：旧版 market_prices 无 region_id，重建为新表结构"""
    db_path = database_path()
    if not db_path or not Path(db_path).exists():
        return

    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        # 检查是否为空表
        c.execute("SELECT COUNT(*) FROM market_prices")
        if c.fetchone()[0] == 0:
            log.warning("market_prices 表为空，需要更新价格")
        # 检查 market_prices 是否有 region_id 列
        c.execute("PRAGMA table_info(market_prices)")
        cols = {row[1] for row in c.fetchall()}
        if "region_id" not in cols:
            log.info("迁移 market_prices 表 → 增加 region_id 列")
            c.execute("DROP TABLE IF EXISTS market_prices_new")
            c.execute("""
                CREATE TABLE market_prices_new (
                    type_id INTEGER NOT NULL,
                    region_id INTEGER NOT NULL,
                    buy_price REAL,
                    sell_price REAL,
                    buy_volume BIGINT DEFAULT 0,
                    sell_volume BIGINT DEFAULT 0,
                    fetch_time TIMESTAMP NOT NULL DEFAULT (datetime('now')),
                    PRIMARY KEY (type_id, region_id)
                )
            """)
            c.execute("INSERT INTO market_prices_new (type_id, region_id, buy_price, sell_price, buy_volume, sell_volume, fetch_time) SELECT type_id, 10000002, buy_price, sell_price, buy_volume, sell_volume, fetch_time FROM market_prices")
            c.execute("DROP TABLE market_prices")
            c.execute("ALTER TABLE market_prices_new RENAME TO market_prices")
            conn.commit()
            log.info("market_prices 迁移完成（旧数据归入 Jita/10000002）")
        # 检查 market_volume_snapshots
        c.execute("PRAGMA table_info(market_volume_snapshots)")
        cols = {row[1] for row in c.fetchall()}
        if "region_id" not in cols:
            log.info("迁移 market_volume_snapshots 表 → 增加 region_id 列")
            c.execute("DROP TABLE IF EXISTS mvs_new")
            c.execute("""
                CREATE TABLE mvs_new (
                    type_id INTEGER NOT NULL,
                    region_id INTEGER NOT NULL,
                    date TEXT NOT NULL,
                    buy_price REAL DEFAULT 0,
                    sell_price REAL DEFAULT 0,
                    buy_volume BIGINT DEFAULT 0,
                    sell_volume BIGINT DEFAULT 0,
                    PRIMARY KEY (type_id, region_id, date)
                )
            """)
            c.execute("INSERT INTO mvs_new (type_id, region_id, date, buy_price, sell_price, buy_volume, sell_volume) SELECT type_id, 10000002, date, buy_price, sell_price, buy_volume, sell_volume FROM market_volume_snapshots")
            c.execute("DROP TABLE market_volume_snapshots")
            c.execute("ALTER TABLE mvs_new RENAME TO market_volume_snapshots")
            conn.commit()
            log.info("market_volume_snapshots 迁移完成")
        conn.close()
    except Exception:
        log.exception("数据库迁移失败（非致命，等下次价格更新自动重建）")


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
    # 数据库迁移（region_id 列）
    _migrate_db()

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
