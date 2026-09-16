"""移库对话框（QML）的业务契约测试。

只锁业务：行装配（clamp / 未匹配行）、统计行、勾选与数量状态、确认落库的汇总，
外加「QML 宿主签名与原类一致」这条契约。**不放**「加载无告警」那条 —— 由主流程在
`tests/test_qml_dialogs.py` 统一加。

与 Widgets 版 `ui_pyside6/views/inventory/transfer_dialog.py` 逐条对齐。
"""

from __future__ import annotations

import inspect

import ui_qml.theme.registry as theme
from ui_qml.bridge import transfer_bridge as tb
from ui_qml.bridge.transfer_bridge import HangarTransferBridge, HangarTransferQmlDialog

_TARGET = 2


def _install(
    monkeypatch,
    *,
    hangars: list[dict] | None = None,
    stocks: dict[int, dict[int, int]] | None = None,
    items: dict[int, list[dict]] | None = None,
) -> list[tuple[int, int, int, int]]:
    """打桩机库 / 库存 / 物品表与落库，返回落库调用记录。"""
    hangars = hangars if hangars is not None else [{"id": 1, "name": "源仓"}, {"id": 2, "name": "目标仓"}]
    stocks = stocks or {}
    items = items or {}
    moves: list[tuple[int, int, int, int]] = []

    def _move(src: int, type_id: int, qty: int, dst: int) -> int:
        # 与真实 move_quantity 同口径：源库不足时只搬现有量
        moves.append((src, type_id, qty, dst))
        return min(qty, stocks.get(src, {}).get(type_id, 0))

    monkeypatch.setattr(tb, "get_hangars", lambda: [dict(h) for h in hangars])
    monkeypatch.setattr(tb, "get_items", lambda hid: [dict(it) for it in items.get(hid, [])])
    monkeypatch.setattr(tb, "get_hangar_stock", lambda hid: dict(stocks.get(hid, {})))
    monkeypatch.setattr(tb, "move_quantity", _move)
    return moves


def _parsed_matched(qty: int = 150) -> list[dict]:
    return [
        {
            "type_id": 34,
            "raw_name": "三钛合金",
            "zh_name": "三钛合金",
            "en_name": "",
            "qty": qty,
            "status": "matched",
        }
    ]


def _parsed_unmatched() -> list[dict]:
    return [{"type_id": None, "raw_name": "???", "zh_name": "", "en_name": "", "qty": 5, "status": "unmatched"}]


def _bridge(monkeypatch, parsed: list[dict], **kw) -> HangarTransferBridge:
    _install(
        monkeypatch,
        stocks={1: {34: 100}, 2: {34: 5}},
        items={1: [{"type_id": 34, "cost_price": 5.5}]},
        **kw,
    )
    return HangarTransferBridge(parsed, _TARGET, "目标仓")


# ════════════════════════════════════════════════════════════════
#  行装配
# ════════════════════════════════════════════════════════════════


def test_matched_row_clamps_and_marks_source_short(qapp, monkeypatch):
    """剪贴板 150 > 源库 100 → 移动量 clamp 到 100，行标「源库不足」并染橙。"""
    bridge = _bridge(monkeypatch, _parsed_matched(150))
    assert len(bridge.rows) == 1
    row = bridge.rows[0]
    assert row["matched"] is True and row["capped"] is True
    assert row["moveQty"] == 100 and row["maxQty"] == 100
    assert row["nameText"] == "三钛合金（源库不足）"
    assert row["nameColor"] == theme.ACCENT_ORANGE
    assert row["clipText"] == "150" and row["srcText"] == "100" and row["targetText"] == "5"
    assert row["costText"] == "5.50"
    assert row["checked"] is True


def test_matched_row_within_stock_is_not_capped(qapp, monkeypatch):
    bridge = _bridge(monkeypatch, _parsed_matched(40))
    row = bridge.rows[0]
    assert row["capped"] is False
    assert row["moveQty"] == 40
    assert row["nameText"] == "三钛合金"
    assert row["nameColor"] == ""


def test_unmatched_row_is_greyed_and_has_no_numbers(qapp, monkeypatch):
    bridge = _bridge(monkeypatch, _parsed_unmatched())
    assert len(bridge.rows) == 1
    row = bridge.rows[0]
    assert row["matched"] is False and row["type_id"] is None
    assert row["nameText"] == "???（未匹配）"
    assert row["nameColor"] == theme.TEXT_SECONDARY
    assert [row["clipText"], row["srcText"], row["costText"], row["targetText"]] == ["-", "-", "-", "-"]


def test_matched_rows_come_before_unmatched(qapp, monkeypatch):
    """行序：已匹配在前、未匹配在后（原 `_populate_rows` 的布局）。"""
    parsed = [*_parsed_matched(10), *_parsed_unmatched()]
    bridge = _bridge(monkeypatch, parsed)
    assert [r["matched"] for r in bridge.rows] == [True, False]
    assert [r["index"] for r in bridge.rows] == [0, 1]


# ════════════════════════════════════════════════════════════════
#  统计行
# ════════════════════════════════════════════════════════════════


def test_summary_reports_counts_and_move(qapp, monkeypatch):
    parsed = [*_parsed_matched(150), *_parsed_unmatched()]
    bridge = _bridge(
        monkeypatch,
        parsed,
    )
    assert bridge.summaryText == "共 2 项 / 勾选 1 项 / 将移动 100 件 / 源库不足 1 项 / 未匹配 1 项"


def test_filtered_note_is_shown(qapp, monkeypatch):
    _install(monkeypatch, stocks={1: {34: 100}, 2: {}}, items={1: [{"type_id": 34, "cost_price": 1.0}]})
    bridge = HangarTransferBridge(_parsed_matched(10), _TARGET, "目标仓", filtered_note=3)
    assert "已过滤 3 行蓝图" in bridge.summaryText


def test_unchecking_updates_summary_only(qapp, monkeypatch):
    """取消勾选：统计行变，行集不重建（重建会抢走微调框焦点）。"""
    bridge = _bridge(monkeypatch, _parsed_matched(10))
    rebuilt: list[int] = []
    bridge.contentChanged.connect(lambda: rebuilt.append(1))

    bridge.setRowChecked(0, False)
    assert bridge.summaryText == "共 1 项"
    assert rebuilt == [], "只改勾选不该重建整张表"

    bridge.setRowChecked(0, True)
    assert "将移动 10 件" in bridge.summaryText


def test_setting_qty_updates_summary(qapp, monkeypatch):
    bridge = _bridge(monkeypatch, _parsed_matched(150))
    bridge.setRowQty(0, 25)
    assert "将移动 25 件" in bridge.summaryText


def test_rebuild_notifies_summary(qapp, monkeypatch):
    """重填后统计行必须发通知 —— 它的 notify 是 `summaryChanged` 而不是 `contentChanged`，
    漏发的话换来源 / 删行之后 QML 上那句统计还是旧的。"""
    parsed = [*_parsed_matched(150), *_parsed_unmatched()]
    bridge = _bridge(monkeypatch, parsed)
    fired: list[int] = []
    bridge.summaryChanged.connect(lambda: fired.append(1))

    bridge.deleteRows([1])
    assert fired == [1]
    assert bridge.summaryText == "共 1 项 / 勾选 1 项 / 将移动 100 件 / 源库不足 1 项"


# ════════════════════════════════════════════════════════════════
#  确认落库
# ════════════════════════════════════════════════════════════════


def test_accept_moves_and_reports_result(qapp, monkeypatch):
    moves = _install(monkeypatch, stocks={1: {34: 100}, 2: {34: 5}}, items={1: [{"type_id": 34, "cost_price": 5.5}]})
    bridge = HangarTransferBridge(_parsed_matched(150), _TARGET, "目标仓")
    accepted: list[int] = []
    bridge.accepted.connect(lambda: accepted.append(1))

    bridge.accept()
    assert moves == [(1, 34, 100, 2)]
    assert accepted == [1]
    assert bridge.result_summary() == {"moved": 100, "capped": 1}


def test_accept_without_movable_items_reports_error(qapp, monkeypatch):
    """勾选清零（数量 0）时不动库、不关闭，只给一句提示（原 QMessageBox 的等价物）。"""
    _install(monkeypatch, stocks={1: {34: 100}, 2: {}}, items={1: [{"type_id": 34, "cost_price": 1.0}]})
    bridge = HangarTransferBridge(_parsed_matched(10), _TARGET, "目标仓")
    accepted: list[int] = []
    bridge.accepted.connect(lambda: accepted.append(1))

    bridge.setRowQty(0, 0)
    bridge.accept()
    assert accepted == []
    assert bridge.error == "没有可移动的物品"
    assert bridge.result_summary() == {"moved": 0, "capped": 0}


def test_no_other_hangar_disables_accept(qapp, monkeypatch):
    _install(monkeypatch, hangars=[{"id": 2, "name": "目标仓"}])
    bridge = HangarTransferBridge(_parsed_matched(10), _TARGET, "目标仓")
    assert bridge.canAccept is False
    assert bridge.rows == []
    assert bridge.summaryText == "没有其他机库可移动"

    accepted: list[int] = []
    bridge.accepted.connect(lambda: accepted.append(1))
    bridge.accept()
    assert accepted == []
    assert bridge.error == "没有可用的来源机库"


def test_source_switch_reloads_stock(qapp, monkeypatch):
    """换来源机库重取库存 —— 同一个 type_id 在两个源库的可用量不同。"""
    moves = _install(
        monkeypatch,
        hangars=[{"id": 1, "name": "源仓"}, {"id": 3, "name": "备仓"}, {"id": 2, "name": "目标仓"}],
        stocks={1: {34: 100}, 3: {34: 7}, 2: {}},
        items={1: [{"type_id": 34, "cost_price": 5.5}], 3: [{"type_id": 34, "cost_price": 9.0}]},
    )
    bridge = HangarTransferBridge(_parsed_matched(150), _TARGET, "目标仓")
    assert bridge.rows[0]["moveQty"] == 100

    bridge.setSourceIndex(1)  # 备仓
    assert bridge.rows[0]["moveQty"] == 7
    assert bridge.rows[0]["srcText"] == "7"
    assert bridge.rows[0]["costText"] == "9.00"

    bridge.accept()
    assert moves == [(3, 34, 7, 2)]


# ════════════════════════════════════════════════════════════════
#  删除行 / 未匹配行接物品
# ════════════════════════════════════════════════════════════════


def test_delete_rows_removes_parsed_entries(qapp, monkeypatch):
    parsed = [*_parsed_matched(10), *_parsed_unmatched()]
    bridge = _bridge(monkeypatch, parsed)
    bridge.deleteRows([1, 0])
    assert parsed == []
    assert bridge.rows == []
    assert bridge.summaryText == "共 0 项"


def test_apply_match_folds_unmatched_row_into_plan(qapp, monkeypatch):
    """未匹配行接上物品后纳入移库计划（原 `_search_match` 的落地部分）。"""
    parsed = _parsed_unmatched()
    _install(
        monkeypatch,
        stocks={1: {35: 20}, 2: {}},
        items={1: [{"type_id": 35, "cost_price": 2.0}]},
    )
    bridge = HangarTransferBridge(parsed, _TARGET, "目标仓")
    assert bridge.rows[0]["matched"] is False

    bridge.apply_match(0, {"type_id": 35, "zh_name": "类晶体胶矿", "en_name": "Pyerite"})
    row = bridge.rows[0]
    assert row["matched"] is True and row["type_id"] == 35
    assert row["nameText"] == "类晶体胶矿"
    assert row["moveQty"] == 5  # 剪贴板 5 < 源库 20
    assert row["capped"] is False
    assert "未匹配" not in bridge.summaryText


def test_apply_match_ignores_already_matched_row(qapp, monkeypatch):
    parsed = _parsed_matched(10)
    bridge = _bridge(monkeypatch, parsed)
    bridge.apply_match(0, {"type_id": 99, "zh_name": "别的", "en_name": "Other"})
    assert parsed[0]["type_id"] == 34, "已匹配行不该被顶掉"
    assert parsed[0]["zh_name"] == "三钛合金"


# ════════════════════════════════════════════════════════════════
#  宿主契约
# ════════════════════════════════════════════════════════════════


def test_qml_dialog_keeps_original_signature():
    """构造签名与原 `HangarTransferDialog(rows, target_hangar_id, hangar_name, parent, *, filtered_note)` 一致。"""
    params = inspect.signature(HangarTransferQmlDialog.__init__).parameters
    assert list(params) == ["self", "rows", "target_hangar_id", "hangar_name", "parent", "filtered_note"]
    assert params["filtered_note"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["parent"].default is None
    assert callable(HangarTransferQmlDialog.result_summary)
