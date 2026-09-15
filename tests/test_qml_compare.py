"""批量对比对话框（QML 版）的业务契约。

对照 Widgets 版的 `tests/test_compare_dialog.py`（那边断的是 `_selected_items`
与控件状态），这里断的是桥的属性、表格模型的展示结果与状态文案。

`qapp` fixture 是**必须**的：这些用例都要构造 QWidget（`QmlDialog` 是 QDialog），
漏了会挂死而不是报错（本仓踩过）。
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QGuiApplication

from ui_qml.bridge.compare_bridge import CompareQmlDialog
from ui_qml.models.compare_qml_model import CompareQmlModel

pytestmark = pytest.mark.ui


# ════════════════════════════════════════════════════════════
#  替身
# ════════════════════════════════════════════════════════════

_MFG_COLS = 9
_TRADE_COLS = 8


def _mfg_row(name: str, profit: float, status: str = "") -> dict:
    return {
        "type_id": 2001,
        "name": name,
        "cost": 100.0,
        "revenue": 100.0 + profit,
        "profit": profit,
        "margin": 10.0,
        "score": 9.0,
        "isk_per_hour": 1000.0,
        "runs_per_day": 24.0,
        "status": status,
    }


_TRADE_ROW = {
    "type_id": 34,
    "name": "三钛合金",
    "buy_cost": 5.0,
    "sell_revenue": 6.0,
    "gross_profit": 1.0,
    "margin": 20.0,
    "score": 5.0,
    "profit_per_m3": 100.0,
    "status": "",
}


class _FakeWorker(QObject):
    """`CompareWorker` 的同步替身：start() 里立刻回一批结果（不碰 DB、不起线程）。"""

    progress = Signal(int, int)
    done = Signal(list)

    def __init__(self, items, mode, cfg, parent=None):
        super().__init__(parent)
        self.items = list(items)
        self.mode = mode
        self.cfg = dict(cfg)
        self.started = False
        self.cancelled = False
        self.interrupted = False
        self.waited = 0

    def isRunning(self) -> bool:
        return False

    def cancel(self) -> None:
        self.cancelled = True

    def requestInterruption(self) -> None:
        self.interrupted = True

    def wait(self, ms: int = 0) -> bool:
        self.waited = ms
        return True

    def start(self) -> None:
        self.started = True
        results = (
            [_TRADE_ROW]
            if self.mode == "trade"
            else [_mfg_row("渡鸦级", 500.0), _mfg_row("幼龙级", -200.0, status="no_price")]
        )
        self.progress.emit(len(results), len(results))
        self.done.emit(results)


class _SlowWorker(_FakeWorker):
    """一直说自己在跑 —— 用来验证关窗时确实做了收尾（QThread 运行中被析构会 abort）。"""

    def isRunning(self) -> bool:
        return True

    def start(self) -> None:
        self.started = True


class _EmptyWorker(_FakeWorker):
    """一个结果也不回（全部算不出来）—— 用来验证「无有效结果」那条文案。"""

    def start(self) -> None:
        self.started = True
        self.done.emit([])


@pytest.fixture(autouse=True)
def stub_lookups(monkeypatch):
    """物品搜索 / 名称查询 / 后台 worker 全部打桩（用例都不该碰 DB）。"""
    monkeypatch.setattr(
        "ui_qml.bridge.compare_bridge.search_items",
        lambda query: [{"type_id": 2001, "zh_name": "渡鸦级", "en_name": "Raven"}],
    )
    monkeypatch.setattr("ui_qml.bridge.compare_bridge.item_name", lambda type_id: f"物品{type_id}")
    monkeypatch.setattr("ui_qml.bridge.compare_bridge.CompareWorker", _FakeWorker)


def _dialog(**kwargs) -> CompareQmlDialog:
    return CompareQmlDialog(**kwargs)


def _rows(dialog: CompareQmlDialog) -> list[dict]:
    return list(dialog.bridge._model._rows)  # type: ignore[attr-defined]


# ════════════════════════════════════════════════════════════
#  初始态
# ════════════════════════════════════════════════════════════


def test_defaults(qapp):
    dlg = _dialog()
    try:
        assert dlg.ok(), "QML 没加载起来"
        assert dlg.windowTitle() == "批量对比"

        bridge = dlg.bridge
        assert bridge.modeNames == ["制造评分", "贸易评分", "反应评分"]
        assert bridge.modeIndex == 0
        assert bridge.showMeTe is True
        assert bridge.me == 0
        assert bridge.te == 0
        assert bridge.tax == 0.0
        assert bridge.items == []
        assert bridge.hasItems is False
        assert bridge.statusText == "就绪"
        assert bridge.canCompare is True
        assert bridge.exportEnabled is False
        assert len(bridge.columns) == _MFG_COLS
    finally:
        dlg.deleteLater()


def test_initial_items_are_named_and_deduped(qapp):
    """预选列表：重名同 id 只留一条，缺名字的按 `item_name` 补齐（原版 `__init__` 的行为）。"""
    dlg = _dialog(
        initial_items=[
            {"type_id": 2001, "name": "渡鸦级"},
            {"type_id": 2001, "name": "渡鸦级"},
            {"type_id": 34},
        ]
    )
    try:
        assert dlg.bridge.items == [{"name": "渡鸦级"}, {"name": "物品34"}]
        assert dlg.bridge.hasItems is True
    finally:
        dlg.deleteLater()


# ════════════════════════════════════════════════════════════
#  添加 / 移除 / 清空
# ════════════════════════════════════════════════════════════


def test_add_first_match_uses_the_current_query(qapp, monkeypatch):
    """「添加」按当下的输入重查一次，并清空搜索框（对齐原版 `_on_add_first_match`）。"""
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge.setSearchText("渡鸦")
        bridge.addFirstMatch()

        assert bridge.items == [{"name": "渡鸦级"}]
        assert bridge.searchText == "", "添加成功后搜索框该被清空"
        assert "已添加: 渡鸦级" in bridge.statusText
    finally:
        dlg.deleteLater()


def test_add_duplicate_only_hints(qapp):
    dlg = _dialog(initial_items=[{"type_id": 2001, "name": "渡鸦级"}])
    try:
        bridge = dlg.bridge
        bridge.setSearchText("渡鸦")
        bridge.addFirstMatch()
        assert len(bridge.items) == 1
        assert bridge.statusText == "已添加: 渡鸦级"
    finally:
        dlg.deleteLater()


def test_add_without_match_hints(qapp, monkeypatch):
    monkeypatch.setattr("ui_qml.bridge.compare_bridge.search_items", lambda query: [])
    dlg = _dialog()
    try:
        dlg.bridge.setSearchText("不存在")
        dlg.bridge.addFirstMatch()
        assert dlg.bridge.statusText == "未找到匹配物品"
        assert dlg.bridge.items == []
    finally:
        dlg.deleteLater()


def test_remove_item(qapp):
    dlg = _dialog(initial_items=[{"type_id": 2001, "name": "渡鸦级"}, {"type_id": 34, "name": "三钛合金"}])
    try:
        dlg.bridge.removeItem(0)
        assert dlg.bridge.items == [{"name": "三钛合金"}]
        assert "已移除: 渡鸦级" in dlg.bridge.statusText

        dlg.bridge.removeItem(9)  # 越界：什么也不做
        assert len(dlg.bridge.items) == 1
    finally:
        dlg.deleteLater()


def test_clear_items_also_drops_the_results(qapp):
    dlg = _dialog(initial_items=[{"type_id": 2001, "name": "渡鸦级"}])
    try:
        bridge = dlg.bridge
        bridge.compare()
        assert bridge.exportEnabled is True, "算过就该能导出"

        bridge.clearItems()
        assert bridge.items == []
        assert bridge.canCompare is True
        assert bridge.exportEnabled is False, "清空后不该还能导出旧结果"
        assert len(_rows(dlg)) == 0
        assert bridge.statusText == "已清空"
    finally:
        dlg.deleteLater()


# ════════════════════════════════════════════════════════════
#  模式与参数
# ════════════════════════════════════════════════════════════


def test_mode_switch_changes_columns_and_me_te(qapp):
    """换模式换一套列；ME/TE 只对制造与反应有意义（对齐原版 `_on_mode_changed`）。"""
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge.setModeIndex(1)  # 贸易
        assert len(bridge.columns) == _TRADE_COLS
        assert bridge.showMeTe is False

        bridge.setModeIndex(2)  # 反应：列与制造同构
        assert len(bridge.columns) == _MFG_COLS
        assert bridge.showMeTe is True
    finally:
        dlg.deleteLater()


def test_mode_index_out_of_range_is_ignored(qapp):
    dlg = _dialog()
    try:
        dlg.bridge.setModeIndex(9)
        assert dlg.bridge.modeIndex == 0
    finally:
        dlg.deleteLater()


def test_mode_switch_recomputes_existing_results(qapp):
    """已经有结果时换模式会按新模式重算（原版 `if self._results: self._on_compare()`）。"""
    dlg = _dialog(initial_items=[{"type_id": 2001, "name": "渡鸦级"}])
    try:
        bridge = dlg.bridge
        bridge.compare()
        assert len(_rows(dlg)) == 2

        bridge.setModeIndex(1)
        assert len(_rows(dlg)) == 1, "贸易模式该重算出贸易的那一行"
        assert _rows(dlg)[0]["name"] == "三钛合金"
    finally:
        dlg.deleteLater()


def test_parameters_are_clamped(qapp):
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge.setMe(99)
        bridge.setTe(-5)
        bridge.setTax(999.0)
        assert (bridge.me, bridge.te, bridge.tax) == (10, 0, 100.0)
    finally:
        dlg.deleteLater()


def test_hub_and_character_choose_the_config(qapp, monkeypatch):
    """区域/角色下拉统一喂给 worker 的 cfg（原版把买入卖出都指向同一个下拉）。"""
    monkeypatch.setattr(
        "ui_pyside6.views.char_settings_view.services_get_character_list",
        lambda: ["main", "alt"],
    )
    dlg = _dialog(initial_items=[{"type_id": 2001, "name": "渡鸦级"}])
    try:
        bridge = dlg.bridge
        bridge.setHubIndex(1)  # Amarr
        bridge.setCharIndex(1)  # alt
        bridge.setMe(5)
        bridge.setTe(7)
        bridge.setTax(1.5)
        bridge.compare()

        cfg = bridge._worker.cfg  # type: ignore[attr-defined]
        assert cfg["hub"] == "Amarr"
        assert cfg["bh"] == cfg["sh"] == "Amarr"
        assert cfg["char"] == "alt"
        assert (cfg["me"], cfg["te"], cfg["tax"]) == (5, 7, 1.5)
    finally:
        dlg.deleteLater()


# ════════════════════════════════════════════════════════════
#  对比计算
# ════════════════════════════════════════════════════════════


def test_compare_without_items_only_hints(qapp):
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge.compare()
        assert bridge.statusText == "请先添加物品"
        assert bridge.progressVisible is False
    finally:
        dlg.deleteLater()


def test_compare_fills_the_table_and_reports_the_best(qapp):
    dlg = _dialog(initial_items=[{"type_id": 2001, "name": "渡鸦级"}, {"type_id": 2002, "name": "幼龙级"}])
    try:
        bridge = dlg.bridge
        bridge.compare()

        assert len(_rows(dlg)) == 2
        assert bridge.progressVisible is False, "算完要把进度条收起来"
        assert bridge.canCompare is True, "算完要恢复「开始对比」"
        assert bridge.exportEnabled is True
        # 有效项只有第一行（第二行带 status），最佳利润取自它
        assert "完成 2 项" in bridge.statusText
        assert "有效 1 项" in bridge.statusText
        assert "最佳: 渡鸦级" in bridge.statusText
        assert "500" in bridge.statusText
    finally:
        dlg.deleteLater()


def test_compare_without_valid_rows_says_so(qapp, monkeypatch):
    monkeypatch.setattr("ui_qml.bridge.compare_bridge.CompareWorker", _EmptyWorker)
    dlg = _dialog(initial_items=[{"type_id": 2001, "name": "渡鸦级"}])
    try:
        dlg.bridge.compare()
        assert dlg.bridge.statusText == "完成 0 项 | 无有效结果"
    finally:
        dlg.deleteLater()


def test_trade_mode_best_uses_gross_profit(qapp):
    dlg = _dialog(initial_items=[{"type_id": 34, "name": "三钛合金"}])
    try:
        bridge = dlg.bridge
        bridge.setModeIndex(1)
        bridge.compare()
        assert "最佳: 三钛合金" in bridge.statusText
        assert "1" in bridge.statusText
    finally:
        dlg.deleteLater()


def test_stop_finishes_the_running_worker(qapp, monkeypatch):
    """关窗必须让在跑的线程收尾。

    不收尾的话线程是桥的子对象、桥随对话框一起销毁 —— `QThread` 在运行时被析构，
    Qt 直接 abort()（实测退出码 127、一行日志都没有）。
    """
    monkeypatch.setattr("ui_qml.bridge.compare_bridge.CompareWorker", _SlowWorker)
    dlg = _dialog(initial_items=[{"type_id": 2001, "name": "渡鸦级"}])
    try:
        bridge = dlg.bridge
        bridge.compare()
        worker = bridge._worker  # type: ignore[attr-defined]
        assert worker.isRunning(), "替身应当一直说自己在跑"

        dlg.done(0)  # 确定 / 取消 / Esc 都走这里
        assert worker.cancelled and worker.interrupted and worker.waited > 0
    finally:
        dlg.deleteLater()


# ════════════════════════════════════════════════════════════
#  表格单元格（展示规则只该有一份）
# ════════════════════════════════════════════════════════════


def test_cells_reuse_the_widgets_model(qapp):
    """QML 模型是 `CompareTableModel` 的子类：文本/颜色/对齐仍由父类算。

    这样「改了 Widgets 版忘了改 QML 版」不可能发生。
    """
    from ui_pyside6.views.compare.compare_models import CompareTableModel

    model = CompareQmlModel("mfg")
    assert isinstance(model, CompareTableModel)

    model.set_rows([_mfg_row("渡鸦级", 500.0), _mfg_row("幼龙级", -200.0, status="no_price")])
    index0 = model.index(0, 0)
    profit_idx0 = model.index(0, 3)
    status_idx1 = model.index(1, 8)

    assert model.data(index0, Qt.ItemDataRole.UserRole + 1) == "渡鸦级"
    assert model.data(index0, Qt.ItemDataRole.UserRole + 4) is False  # 物品列左对齐
    assert model.data(profit_idx0, Qt.ItemDataRole.UserRole + 4) is True  # 数值列右对齐
    assert model.data(profit_idx0, Qt.ItemDataRole.UserRole + 2) != ""  # 正利润染色
    assert model.data(status_idx1, Qt.ItemDataRole.UserRole + 2) != ""  # 有状态染色
    # 与父类逐字一致（同一条展示规则）
    assert model.data(profit_idx0, Qt.ItemDataRole.UserRole + 1) == model.data(profit_idx0, Qt.ItemDataRole.DisplayRole)


def test_row_info_and_copy(qapp):
    dlg = _dialog(initial_items=[{"type_id": 2001, "name": "渡鸦级"}])
    try:
        bridge = dlg.bridge
        bridge.compare()

        assert bridge.rowInfo(0) == {"valid": True, "typeId": 2001, "name": "渡鸦级"}
        assert bridge.rowInfo(9)["valid"] is False

        bridge.copyRow(0)
        clipboard = QGuiApplication.clipboard().text()
        assert clipboard.startswith("渡鸦级\t"), "行复制该是制表符分隔、首列是物品名"
        assert "已复制行数据到剪贴板" in bridge.statusText

        bridge.copyAllCsv()
        clipboard = QGuiApplication.clipboard().text()
        assert clipboard.startswith("物品,"), "整表复制该带表头且是 CSV"
        assert "已复制 2 行数据到剪贴板" in bridge.statusText
    finally:
        dlg.deleteLater()


def test_export_without_results_only_hints(qapp):
    dlg = _dialog()
    try:
        dlg.bridge.exportCsv()
        assert dlg.bridge.statusText == "无数据可导出"
    finally:
        dlg.deleteLater()


# ════════════════════════════════════════════════════════════
#  二级弹出：按模式弹制造 / 贸易评分设置
# ════════════════════════════════════════════════════════════


class _RecordingDialog:
    """评分弹窗的替身：记下构造参数，`exec()` 立刻返回（不真开窗、不阻塞）。"""

    calls: list[dict] = []

    def __init__(self, current=None, parent=None, type_id=None) -> None:
        self.current = current
        self.parent = parent
        self.window_title = ""
        _RecordingDialog.calls.append({"current": current, "parent": parent})

    def setWindowTitle(self, title: str) -> None:
        self.window_title = title

    def exec(self) -> int:
        return 1


@pytest.mark.parametrize(
    ("mode_index", "stub_name", "prefix"),
    [(0, "MfgQmlDialog", "制造评分"), (1, "TradeQmlDialog", "贸易评分"), (2, "MfgQmlDialog", "制造评分")],
)
def test_open_item_detail_picks_the_dialog_by_mode(qapp, monkeypatch, mode_index, stub_name, prefix):
    """「查看物品」按当前模式弹对应的评分弹窗，并把窗口标题换成物品名。

    这条跨模块调用正是本批次两个文件必须一起迁的原因：留着 Widgets 版的
    `MfgDlg` 就还得从 QML 页面里弹出一个 Widgets 窗口。
    """
    monkeypatch.setattr(f"ui_qml.bridge.score_dialogs_bridge.{stub_name}", _RecordingDialog)
    _RecordingDialog.calls = []

    dlg = _dialog(initial_items=[{"type_id": 2001, "name": "渡鸦级"}])
    try:
        bridge = dlg.bridge
        bridge.setModeIndex(mode_index)
        bridge.compare()
        bridge.openItemDetail(0)

        assert len(_RecordingDialog.calls) == 1
        assert _RecordingDialog.calls[0]["current"]["hub"] == "Jita"
        assert "char" in _RecordingDialog.calls[0]["current"]
        assert _RecordingDialog.calls[0]["parent"] is dlg, "二级弹窗该以宿主对话框当 parent"
    finally:
        dlg.deleteLater()


def test_open_item_detail_ignores_a_row_without_type_id(qapp, monkeypatch):
    monkeypatch.setattr("ui_qml.bridge.score_dialogs_bridge.MfgQmlDialog", _RecordingDialog)
    _RecordingDialog.calls = []

    dlg = _dialog(initial_items=[{"type_id": 2001, "name": "渡鸦级"}])
    try:
        bridge = dlg.bridge
        bridge.compare()
        bridge._results[0]["type_id"] = None  # 没有 type_id 的行不该弹窗
        bridge.openItemDetail(0)
        assert _RecordingDialog.calls == []
    finally:
        dlg.deleteLater()
