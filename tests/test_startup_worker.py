"""测试启动检查 Worker — 迁移顺序与数据就绪上报。"""

from unittest.mock import patch

import pytest

import Main
from services.init_check import check_all as _real_check_all

pytestmark = pytest.mark.ui


def _ready_status() -> dict:
    """构造全就绪的 check_all 结果（key 与真实 check_all 一致）。"""
    return dict.fromkeys(_real_check_all(), True)


def _run_worker():
    from ui_pyside6.workers.startup_worker import StartupCheckWorker

    worker = StartupCheckWorker()
    events: dict = {"stages": [], "components": [], "finished": []}
    worker.stage.connect(lambda m: events["stages"].append(m))
    worker.component_checked.connect(lambda k, n, r: events["components"].append((k, n, r)))
    worker.finished_all.connect(lambda ok, miss: events["finished"].append((ok, miss)))
    worker.run()  # 同线程直接执行（信号直连）
    return events


def test_worker_ready_all(qapp):
    """全部就绪 → finished_all(True, [])，且逐步上报检查结果。"""
    with (
        patch.object(Main, "_migrate_split_db"),
        patch.object(Main, "_migrate_blueprint_db"),
        patch("services.schema_migrations.ensure_all_schemas"),
        patch("services.inventory_manager.init_db"),
        patch("services.init_check.check_all", return_value=_ready_status()),
    ):
        events = _run_worker()

    assert events["finished"] == [(True, [])]
    assert "迁移数据库" in events["stages"]
    assert "检查数据" in events["stages"]
    assert len(events["components"]) == len(_ready_status())


def test_worker_reports_missing(qapp):
    """部分未就绪 → finished_all(False, [缺失 key 列表])。"""
    status = _ready_status()
    status["icons"] = False
    status["rigs"] = False
    with (
        patch.object(Main, "_migrate_split_db"),
        patch.object(Main, "_migrate_blueprint_db"),
        patch("services.schema_migrations.ensure_all_schemas"),
        patch("services.inventory_manager.init_db"),
        patch("services.init_check.check_all", return_value=status),
    ):
        events = _run_worker()

    assert events["finished"] == [(False, ["icons", "rigs"])]


def test_worker_migration_failure_does_not_block(qapp):
    """迁移步骤抛异常不阻断，仍进入数据检查并上报。"""
    status = _ready_status()
    with (
        patch.object(Main, "_migrate_split_db", side_effect=RuntimeError("boom")),
        patch.object(Main, "_migrate_blueprint_db"),
        patch("services.schema_migrations.ensure_all_schemas"),
        patch("services.inventory_manager.init_db"),
        patch("services.init_check.check_all", return_value=status),
    ):
        events = _run_worker()

    assert events["finished"] == [(True, [])], "迁移失败应降级继续，不影响就绪上报"
