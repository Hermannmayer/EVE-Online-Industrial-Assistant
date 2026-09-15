"""蓝图导入对话框（QML 版）的业务契约测试。

只管**迁移后仍必须成立的行为**：行装配、变更分类（默认勾选策略）、状态文案、
桥的属性与槽、worker 产出回填。宿主的「加载无告警」那条由主流程在
`tests/test_qml_dialogs.py` 里统一加，这里不重复。

业务判定的真源是原文件 `ui_pyside6/views/inventory/blueprint_import_dialog.py`
（桥只是整形），所以这里断言的是「桥有没有把它如实搬出来」。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ui_qml.bridge.blueprint_import_bridge import (
    BlueprintImportChangeBridge,
    BlueprintImportReviewBridge,
    change_rows,
)

pytestmark = pytest.mark.ui


# ── 造 diff 行（形状与 `_BlueprintImportWorker.finished_signal` 一致）──


def _row(row_id: int, runs: int = 0, quantity: int = 1) -> dict:
    return {"id": row_id, "runs": runs, "quantity": quantity, "notes": ""}


def _diff_row(
    bpid: int,
    *,
    is_bpo: bool,
    me: int = 0,
    te: int = 0,
    clip_runs: list[int] | None = None,
    existing_rows: list[dict] | None = None,
    name: str = "",
) -> dict:
    clip = list(clip_runs or [])
    rows = list(existing_rows or [])
    return {
        "blueprint_type_id": bpid,
        "is_bpo": is_bpo,
        "me": me,
        "te": te,
        "clip_runs": clip,
        "existing_rows": rows,
        "qty": len(clip),
        "existing_qty": sum(max(int(r.get("quantity") or 1), 0) for r in rows),
        "name": name,
    }


@pytest.fixture
def diff_rows() -> list[dict]:
    """三行覆盖三种行态：纯新增 / 纯删除 / 张数不变但流程数变了。"""
    return [
        _diff_row(3001, is_bpo=True, clip_runs=[0, 0], name="渡鸦级蓝图"),
        _diff_row(3002, is_bpo=False, me=10, te=20, existing_rows=[_row(1, runs=2996, quantity=3)], name="无人机蓝图"),
        _diff_row(
            3003, is_bpo=False, me=5, te=5, clip_runs=[100], existing_rows=[_row(2, runs=200)], name="护卫舰蓝图"
        ),
    ]


# ══════════════════════════════════════════════════════════════
#  导入预览桥
# ══════════════════════════════════════════════════════════════


def test_rows_assembly_follows_the_original(diff_rows, qapp):
    """行装配：名字/属性/现有/剪贴板/增减文本 + 颜色 token + 可编辑位。"""
    bridge = BlueprintImportReviewBridge(diff_rows, "矿仓")
    rows = bridge.rows
    assert len(rows) == 3

    # 纯新增：原图无流程数概念，增减为 +2 染绿
    assert rows[0]["name"] == "渡鸦级蓝图"
    assert rows[0]["attr"] == "原图  ME0  TE0"
    assert rows[0]["current"] == "0"
    assert rows[0]["clip"] == "2"
    assert rows[0]["delta"] == "+2"
    assert rows[0]["deltaToken"] == "ACCENT_GREEN"
    assert rows[0]["finalText"] == "2"
    assert rows[0]["editable"] is True

    # 纯删除：-3 染红
    assert rows[1]["delta"] == "-3"
    assert rows[1]["deltaToken"] == "ACCENT_RED"

    # 张数不变、流程数变：增减 0 用次要色，属性里两侧流程数都列出来
    assert rows[2]["delta"] == "0"
    assert rows[2]["deltaToken"] == "TEXT_SECONDARY"
    assert rows[2]["attr"] == "拷贝  ME5  TE5  流程100~200"


def test_change_classification_defaults(diff_rows, qapp):
    """变更分类（复用原 `_default_checked`）：增/更新默认勾选，**纯删除默认不勾选**。"""
    bridge = BlueprintImportReviewBridge(diff_rows, "矿仓")
    checked = [r["checked"] for r in bridge.rows]
    assert checked == [True, False, True], "纯删除是唯一不可逆动作，默认必须不勾"


def test_delta_equal_zero_without_runs_change_is_unchecked(qapp):
    """张数没变、流程数也没变 → 不算更新，默认不勾。"""
    rows = [_diff_row(3003, is_bpo=False, me=5, te=5, clip_runs=[200], existing_rows=[_row(2, runs=200)])]
    bridge = BlueprintImportReviewBridge(rows, "矿仓")
    assert bridge.rows[0]["delta"] == "0"
    assert bridge.rows[0]["checked"] is False


def test_summary_text_prefixes_and_full_suffix(diff_rows, qapp):
    """状态文案：勾选/总数/增减 + 全量提示 + 前置的「已过滤/未识别」提示（顺序与原版一致）。"""
    bridge = BlueprintImportReviewBridge(diff_rows, "矿仓", filtered_note=2, unresolved_note=1)
    text = bridge.summaryText
    assert "已勾选 2 项 / 总计 3 项 / 蓝图增减 +2" in text
    assert "全量同步以剪贴板为准" in text
    # 原版先拼「已过滤」再拼「未识别」，所以未识别落在最外层
    assert text.index("未识别 1 行蓝图") < text.index("已过滤 2 行材料")


def test_summary_text_incremental_has_no_full_suffix(diff_rows, qapp):
    bridge = BlueprintImportReviewBridge(diff_rows, "矿仓", default_mode="incremental")
    assert bridge.modeIndex == 0
    assert bridge.isFullMode is False
    assert "全量同步以剪贴板为准" not in bridge.summaryText
    # 增量：最终 = 现有 + 剪贴板，且不可编辑
    assert bridge.rows[0]["finalText"] == "2"
    assert bridge.rows[0]["editable"] is False


def test_select_all_and_deselect_all(diff_rows, qapp):
    bridge = BlueprintImportReviewBridge(diff_rows, "矿仓")
    bridge.deselectAll()
    assert all(r["checked"] is False for r in bridge.rows)
    bridge.selectAll()
    assert all(r["checked"] is True for r in bridge.rows)


def test_mode_switch_keeps_user_choices(diff_rows, qapp):
    """切模式重建表，但用户手改的勾选不得被默认策略复活（对齐原 `_snapshot_state`）。"""
    bridge = BlueprintImportReviewBridge(diff_rows, "矿仓")
    bridge.toggleCheck(1, True)  # 第 1 行是纯删除，默认不勾，用户手动勾上
    assert bridge.rows[1]["checked"] is True

    bridge.setModeIndex(0)  # 切到增量
    assert bridge.mode() == "incremental"
    assert bridge.rows[1]["checked"] is True, "切模式不能把用户的取舍清零"


def test_set_final_recomputes_delta(diff_rows, qapp):
    """全量模式手改「最终」→ 增减跟着变；非法值标红并拦下。"""
    bridge = BlueprintImportReviewBridge(diff_rows, "矿仓")
    bridge.setFinal(0, "5")  # 现有 0，改成 5
    assert bridge.rows[0]["finalText"] == "5"
    assert bridge.rows[0]["delta"] == "+5"

    bridge.setFinal(0, "不是数字")
    assert bridge.rows[0]["finalToken"] == "ACCENT_RED"
    assert bridge.rows[0]["finalText"] == "不是数字"


def test_accept_blocks_when_nothing_checked(diff_rows, qapp):
    bridge = BlueprintImportReviewBridge(diff_rows, "矿仓")
    accepted: list[bool] = []
    bridge.accepted.connect(lambda: accepted.append(True))
    bridge.deselectAll()
    bridge.accept()
    assert accepted == []
    assert bridge.error == "没有勾选的蓝图，无法导入"


def test_accept_blocks_invalid_final(diff_rows, qapp):
    bridge = BlueprintImportReviewBridge(diff_rows, "矿仓")
    accepted: list[bool] = []
    bridge.accepted.connect(lambda: accepted.append(True))
    bridge.setFinal(0, "-1")  # 负数 → 非法
    bridge.accept()
    assert accepted == []
    assert "不是合法的非负整数" in bridge.error


def test_accept_deletions_needs_a_second_click(diff_rows, qapp):
    """全量删除：第一次「确定导入」只给警告，第二次才关（替代原版 QMessageBox Yes/No）。"""
    bridge = BlueprintImportReviewBridge(diff_rows, "矿仓")
    accepted: list[bool] = []
    bridge.accepted.connect(lambda: accepted.append(True))
    bridge.toggleCheck(1, True)  # 勾上纯删除行
    bridge.accept()
    assert accepted == [], "删除要先二次确认"
    assert "删除不可撤销" in bridge.error

    bridge.accept()
    assert accepted == [True]


def test_accept_two_step_resets_after_any_change(diff_rows, qapp):
    """二次确认后只要动了任何东西，警告作废、必须重新确认。"""
    bridge = BlueprintImportReviewBridge(diff_rows, "矿仓")
    accepted: list[bool] = []
    bridge.accepted.connect(lambda: accepted.append(True))
    bridge.toggleCheck(1, True)
    bridge.accept()  # 第一次 → 警告
    bridge.toggleCheck(0, False)  # 改动
    bridge.accept()  # 应再次拦截
    assert accepted == []
    assert "删除不可撤销" in bridge.error


def test_applied_rows_full_vs_incremental(diff_rows, qapp):
    """target_qty：全量 = 手改后的最终值；增量 = 现有 + 剪贴板（只增不减）。"""
    full = BlueprintImportReviewBridge(diff_rows, "矿仓")
    full.setFinal(0, "4")
    applied = full.get_applied_rows()
    assert [r["target_qty"] for r in applied] == [4, 1]  # 勾选的是第 0、2 行
    assert all("blueprint_type_id" in r for r in applied)

    inc = BlueprintImportReviewBridge(diff_rows, "矿仓", default_mode="incremental")
    applied_inc = inc.get_applied_rows()
    # 增量模式三行都默认勾选（第 1 行张数为 0 但流程数变了，`_runs_differ` 判为更新）；
    # target 一律是「现有 + 剪贴板」，只增不减。
    assert [r["target_qty"] for r in applied_inc] == [0 + 2, 3 + 0, 1 + 1]
    assert len(applied_inc) == 3


def test_applied_rows_skips_invalid_final(diff_rows, qapp):
    """非法「最终」值兜底为「不动」——不把它当成 0 写库。"""
    bridge = BlueprintImportReviewBridge(diff_rows, "矿仓")
    bridge.setFinal(0, "x")
    rows = bridge.get_applied_rows()
    assert [r["blueprint_type_id"] for r in rows] == [3003]


# ══════════════════════════════════════════════════════════════
#  变动汇总桥
# ══════════════════════════════════════════════════════════════


def _changes() -> list[dict]:
    return [
        {"name": "渡鸦级蓝图", "attr": "原图  ME0  TE0", "qty_before": 1, "qty_after": 3, "qty_delta": 2},
        {"name": "无人机蓝图", "attr": "拷贝  ME10  TE20", "qty_before": 4, "qty_after": 1, "qty_delta": -3},
        {"name": "护卫舰蓝图", "attr": "拷贝  ME5  TE5  流程100", "qty_before": 2, "qty_after": 2, "qty_delta": 0},
    ]


def test_change_rows_color_by_delta():
    """增减染色：正绿、负红、零沿用默认（token 空串）。"""
    rows = change_rows(_changes())
    assert rows[0]["cells"][2]["text"] == "1 → 3"
    assert rows[0]["cells"][2]["color"] != ""  # 增 → 绿
    assert rows[1]["cells"][2]["color"] != ""  # 减 → 红
    assert rows[2]["cells"][2]["color"] == ""  # 零 → 默认色
    assert rows[0]["cells"][1]["color"] != ""  # 属性列用次要色


def test_change_bridge_summary_and_rows(qapp):
    """汇总文案复用原类 `_build_summary`；表格吃 `FSummaryTable` 的单元格形状。"""
    bridge = BlueprintImportChangeBridge(_changes(), added=3, removed=1, hangar_name="矿仓")
    assert bridge.rowCount == 3
    assert "3 项变化" in bridge.headerText
    assert "增加 1" in bridge.headerText and "减少 1" in bridge.headerText
    assert "新增 3 张" in bridge.headerText and "删除 1 张" in bridge.headerText
    assert bridge.rows[0]["cells"][0]["text"] == "渡鸦级蓝图"
    assert bridge.rows[1]["cells"][2]["text"] == "4 → 1"


def test_change_bridge_empty_summary(qapp):
    bridge = BlueprintImportChangeBridge([], added=2, removed=0, hangar_name="矿仓")
    assert bridge.rowCount == 0
    assert bridge.headerText == "新增 2 条，删除 0 条，无属性变化"


# ══════════════════════════════════════════════════════════════
#  worker 产出回填：解析线程吐出的 diff 要能直接喂给预览桥
# ══════════════════════════════════════════════════════════════


def test_worker_output_feeds_the_review_bridge(qapp, monkeypatch):
    """跑一遍既有的 `_BlueprintImportWorker`（打桩数据源），确认它吐出的 diff 形状
    正是预览桥消费的形状 —— 两条链路对得上，迁移没有把契约改掉。"""
    import services.inventory_manager as inventory_manager
    import services.ui_data_service as ui_data_service
    from ui_pyside6.views.inventory import blueprint_import_worker

    monkeypatch.setattr(blueprint_import_worker, "get_container", lambda: SimpleNamespace(db=object()))
    monkeypatch.setattr(
        inventory_manager,
        "get_blueprints",
        lambda hangar_id: [
            {
                "id": 1,
                "blueprint_type_id": 3001,
                "is_bpo": True,
                "me_level": 0,
                "te_level": 0,
                "runs": 0,
                "quantity": 1,
                "notes": "",
                "zh_name": "渡鸦级蓝图",
            }
        ],
    )
    monkeypatch.setattr(
        ui_data_service,
        "parse_blueprint_clipboard_text",
        lambda raw, db=None: (
            [{"blueprint_type_id": 3001, "is_bpo": True, "me": 0, "te": 0, "runs": 0, "qty": 3, "name": "渡鸦级蓝图"}],
            1,
            0,
        ),
    )

    worker = blueprint_import_worker._BlueprintImportWorker("raw", 1)
    captured: dict = {}
    worker.finished_signal.connect(lambda diff: captured.update(diff=diff))
    worker.run()  # 同步跑，不真起线程

    diff = captured["diff"]
    assert len(diff) == 1
    assert diff[0]["existing_qty"] == 1 and diff[0]["qty"] == 3
    assert (worker.filtered_count, worker.unresolved_count) == (1, 0)

    bridge = BlueprintImportReviewBridge(
        diff,
        "矿仓",
        filtered_note=worker.filtered_count,
        unresolved_note=worker.unresolved_count,
    )
    rows = bridge.rows
    assert rows[0]["current"] == "1"
    assert rows[0]["clip"] == "3"
    assert rows[0]["delta"] == "+2"
    assert rows[0]["checked"] is True
    assert bridge.summaryText.startswith("[已过滤 1 行材料]")
