"""制造 / 贸易评分设置对话框（QML 版）的业务契约。

对照 Widgets 版的 `tests/test_score_dialogs.py`：那边断言的是控件（`dlg.h.currentText()`），
这边断言的是桥的属性与 `get()` 的返回结构 —— 调用方只靠 `get()`，
所以那三处「找不到就退回第 0 项 / 现查现判人物」的兜底行为必须锁住。

`qapp` fixture 是**必须**的：这些用例都要构造 QWidget（`QmlDialog` 是 QDialog），
漏了会挂死而不是报错（本仓踩过）。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ui_qml.bridge.score_dialogs_bridge import MfgQmlDialog, TradeQmlDialog

pytestmark = pytest.mark.ui


@pytest.fixture(autouse=True)
def two_characters(monkeypatch):
    """人物列表打桩（`char_settings_view` 的同名入口最终读这里）。"""
    monkeypatch.setattr(
        "services.char_config_resolver.get_character_list",
        lambda: ["main", "alt"],
    )


def _mfg(**kwargs):
    return MfgQmlDialog(**kwargs)


def _trade(**kwargs):
    return TradeQmlDialog(**kwargs)


# ── 制造评分设置 ─────────────────────────────────────────────


def test_mfg_defaults(qapp):
    """不给 current：区域=Jita、人物=main、税=0（与原版控件的初始态一致）。"""
    dlg = _mfg()
    try:
        assert dlg.ok(), "QML 没加载起来"
        assert dlg.windowTitle() == "制造评分设置"
        assert dlg.get() == {"hub": "Jita", "char": "main", "tax": 0.0}
    finally:
        dlg.deleteLater()


def test_mfg_honours_current_config(qapp):
    dlg = _mfg(current={"hub": "Amarr", "char": "alt", "tax": 2.5})
    try:
        assert dlg.get() == {"hub": "Amarr", "char": "alt", "tax": 2.5}
    finally:
        dlg.deleteLater()


def test_mfg_unknown_hub_keeps_the_first_item(qapp):
    """配置里的区域不在下拉里时停在第一项 —— 复刻 `QComboBox.setCurrentText` 的语义。

    原版依赖它兜底（区域被改名/删掉的旧配置不该让对话框空掉或崩掉）。
    """
    dlg = _mfg(current={"hub": "Nowhere"})
    try:
        assert dlg.get()["hub"] == "Jita"
    finally:
        dlg.deleteLater()


def test_mfg_unknown_char_falls_back_to_main(qapp):
    dlg = _mfg(current={"char": "ghost"})
    try:
        assert dlg.get()["char"] == "main"
    finally:
        dlg.deleteLater()


def test_mfg_tax_is_clamped_to_range(qapp):
    """税率范围 0..100（原版 `setRange(0, 100)`）；越界值由桥钳住。"""
    dlg = _mfg()
    try:
        bridge = dlg.bridge
        bridge.setTax(150.0)
        assert bridge.tax == 100.0
        bridge.setTax(-3.0)
        assert bridge.tax == 0.0
        bridge.setTax(1.25)
        assert dlg.get()["tax"] == 1.25
    finally:
        dlg.deleteLater()


def test_mfg_title_carries_the_item_name(qapp, monkeypatch):
    """带 type_id 时标题换成「制造评分 — 物品名」（原版 `setWindowTitle` 分支）。"""
    repo = MagicMock()
    repo.get_name.return_value = "渡鸦级"
    monkeypatch.setattr("ui_qml.bridge.score_dialogs_bridge.get_container", lambda: MagicMock(item_repo=repo))

    dlg = _mfg(type_id=2001)
    try:
        assert dlg.windowTitle() == "制造评分 — 渡鸦级"
    finally:
        dlg.deleteLater()


def test_mfg_title_survives_a_missing_item(qapp, monkeypatch):
    """取不到名字就保持默认标题（原版那段 `except: pass` —— 找不到物品不是错误）。"""
    monkeypatch.setattr(
        "ui_qml.bridge.score_dialogs_bridge.get_container",
        lambda: MagicMock(item_repo=MagicMock(get_name=MagicMock(side_effect=RuntimeError("no db")))),
    )

    dlg = _mfg(type_id=2001)
    try:
        assert dlg.windowTitle() == "制造评分设置"
    finally:
        dlg.deleteLater()


# ── 贸易评分设置 ─────────────────────────────────────────────


def test_trade_defaults(qapp):
    dlg = _trade()
    try:
        assert dlg.ok(), "QML 没加载起来"
        assert dlg.windowTitle() == "贸易评分设置"
        assert dlg.get() == {"bh": "Jita", "sh": "Jita", "bs": "sell", "ss": "sell", "char": "main"}
    finally:
        dlg.deleteLater()


def test_trade_honours_current_config(qapp):
    dlg = _trade(current={"bh": "Amarr", "sh": "Dodixie", "bs": "buy", "ss": "sell", "char": "alt"})
    try:
        assert dlg.get() == {"bh": "Amarr", "sh": "Dodixie", "bs": "buy", "ss": "sell", "char": "alt"}
    finally:
        dlg.deleteLater()


def test_trade_sides_are_stored_as_sell_buy(qapp):
    """下拉显示「卖单/买单」，存进配置的必须是 sell/buy（原版的 `currentIndex() == 0` 判断）。"""
    dlg = _trade()
    try:
        bridge = dlg.bridge
        assert bridge.sides == ["卖单", "买单"]

        bridge.setBuySideIndex(1)
        bridge.setSellSideIndex(0)
        assert dlg.get()["bs"] == "buy"
        assert dlg.get()["ss"] == "sell"

        bridge.setBuySideIndex(0)
        bridge.setSellSideIndex(1)
        assert dlg.get()["bs"] == "sell"
        assert dlg.get()["ss"] == "buy"
    finally:
        dlg.deleteLater()


def test_trade_side_index_out_of_range_is_ignored(qapp):
    dlg = _trade()
    try:
        dlg.bridge.setBuySideIndex(7)
        assert dlg.get()["bs"] == "sell", "越界下标该被忽略，而不是把 bs 弄成非法值"
    finally:
        dlg.deleteLater()


def test_get_rechecks_the_character_list(qapp, monkeypatch):
    """人物被删掉后 `get()` 必须退回 main —— 原版在 `get()` 里现查现判。"""
    dlg = _trade(current={"char": "alt"})
    try:
        assert dlg.get()["char"] == "alt"

        monkeypatch.setattr(
            "services.char_config_resolver.get_character_list",
            lambda: ["main"],
        )
        assert dlg.get()["char"] == "main"
    finally:
        dlg.deleteLater()


def test_hub_change_writes_through(qapp):
    dlg = _trade()
    try:
        dlg.bridge.setHubIndex(3)  # TRADE_HUBS 第 4 项
        dlg.bridge.setSellHubIndex(2)
        assert dlg.get()["bh"] == "Rens"
        assert dlg.get()["sh"] == "Dodixie"
    finally:
        dlg.deleteLater()
