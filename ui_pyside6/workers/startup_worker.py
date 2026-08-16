"""启动后台检查 Worker — 迁移 + schema + 数据就绪，信号上报 SplashScreen。

将原 Main.py 启动时的耗时操作（旧库拆分迁移、蓝图表迁移、schema 版本迁移、
user 表初始化、数据就绪扫描）移入子线程，避免主线程阻塞 splash 动画。
"""

from PySide6.QtCore import QThread, Signal

from core.logger import log


class StartupCheckWorker(QThread):
    """后台顺序执行迁移与数据检查，逐步上报进度。"""

    stage = Signal(str)  # 阶段提示："迁移数据库" / "检查数据"
    component_checked = Signal(str, str, bool)  # key, 中文名, ready
    finished_all = Signal(bool, list)  # 全部就绪?, 缺失 key 列表

    def run(self):
        try:
            self.stage.emit("迁移数据库")
            self._run_migrations()
            self.stage.emit("检查数据")
            status = self._check_data()
            missing = [k for k, v in status.items() if not v]
            self.finished_all.emit(all(status.values()), missing)
        except Exception:
            log.exception("启动检查失败")
            self.finished_all.emit(False, [])

    # ── 内部步骤（延迟 import，避免 import 循环） ──

    def _run_migrations(self):
        from Main import _migrate_blueprint_db, _migrate_split_db
        from services.inventory_manager import init_db
        from services.schema_migrations import ensure_all_schemas

        for fn in (_migrate_split_db, _migrate_blueprint_db, ensure_all_schemas, init_db):
            try:
                fn()
            except Exception:
                log.exception("启动迁移步骤失败（不阻断启动）")

    def _check_data(self):
        from services.init_check import check_all
        from services.init_service import STEP_MAP

        status = check_all()
        for key, ready in status.items():
            name = STEP_MAP[key].name if key in STEP_MAP else key
            self.component_checked.emit(key, name, ready)
        return status
