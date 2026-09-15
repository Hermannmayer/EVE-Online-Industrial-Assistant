"""可制造物品浏览器（QML 版）的业务契约。

对照 Widgets 版的 `ManufacturableItemsDialog`：这里断的是桥的属性、分类树防抖、
筛选后的表数据、评分列（恒定 基础列 + 制造列）、「刷新计算」的价格前置检查、
Ctrl+C / Ctrl+A 复制与右键菜单的接线。

`qapp` fixture 是**必须**的：这些用例都要构造 QWidget（`QmlDialog` 是 QDialog），
漏了会挂死而不是报错（本仓踩过）。
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QGuiApplication

from ui_qml.bridge import manufacturable_items_bridge as mi
from ui_qml.models.all_items_models import BCOLS, MCOLS
from ui_qml.workers.all_items_workers import JITA_RID

pytestmark = pytest.mark.ui

_ROWS = [
    {"id": 2001, "z": "渡鸦级", "e": "Raven", "bp": 100.0, "sp": 120.0, "ap": 110.0, "v": 10000.0},
    {"id": 34, "z": "三钛合金", "e": "Tritanium", "bp": 5.0, "sp": 6.0, "ap": 5.5, "v": 0.01},
]

_TREE = [
    {"id": 10, "p": None, "n": "舰船"},
    {"id": 11, "p": 10, "n": "护卫舰"},
    {"id": 20, "p": None, "n": "矿物"},
]


# ════════════════════════════════════════════════════════════
#  替身
# ════════════════════════════════════════════════════════════


class _FakeWorker(QObject):
    """`MfgTreeW` / `ItemsW` / `SearchItemsW` / `ScoreW` 的同步替身（见全物品那份的说明）。"""

    done = Signal(list)
    progress = Signal(int, int)

    def __init__(self, *args, **kwargs):
        parent = kwargs.pop("parent", None)
        if args and isinstance(args[-1], QObject):
            parent = args[-1]
            args = args[:-1]
        super().__init__(parent)
        self.parent_obj = parent
        self.args = list(args)
        self.started = False
        self.interrupted = False
        self.waited: list[int] = []

    def isRunning(self) -> bool:
        return False

    def requestInterruption(self) -> None:
        self.interrupted = True

    def wait(self, ms: int = 0) -> bool:
        self.waited.append(ms)
        return True

    def start(self) -> None:
        self.started = True


class _SlowWorker(_FakeWorker):
    def isRunning(self) -> bool:
        return True


class _Repo:
    def get_all_product_ids(self, activity: str) -> list[int]:
        return [2001, 34] if activity == "manufacturing" else [3001]

    def get_t1_manufacturable_product_ids(self) -> list[int]:
        return [2001]

    def get_t2_manufacturable_product_ids(self) -> list[int]:
        return [3002]

    def get_faction_manufacturable_product_ids(self) -> list[int]:
        return [3003]


class _MarketRepo:
    def __init__(self, has_prices: bool = True) -> None:
        self.has_prices = has_prices

    def has_any_prices(self) -> bool:
        return self.has_prices


class _Container:
    blueprint_repo = _Repo()
    market_repo = _MarketRepo()


class _RecordingDialog:
    calls: list[dict] = []
    accept = False

    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs
        _RecordingDialog.calls.append({"args": args, "kwargs": kwargs})

    def exec(self) -> int:
        return 1 if _RecordingDialog.accept else 0

    def show(self) -> None:
        pass

    def result_data(self) -> dict:
        return {}

    def get(self) -> dict:
        return {}


class _MsgBox:
    texts: list[str] = []

    @staticmethod
    def information(_parent, _title, text) -> None:
        _MsgBox.texts.append(str(text))

    @staticmethod
    def warning(_parent, _title, text) -> None:
        _MsgBox.texts.append(str(text))


@pytest.fixture(autouse=True)
def stub_env(monkeypatch, tmp_path):
    monkeypatch.setattr(mi, "MfgTreeW", _FakeWorker)
    monkeypatch.setattr(mi, "ItemsW", _FakeWorker)
    monkeypatch.setattr(mi, "SearchItemsW", _FakeWorker)
    monkeypatch.setattr(mi, "ScoreW", _FakeWorker)
    monkeypatch.setattr(mi, "get_container", lambda: _Container())
    monkeypatch.setattr(mi, "data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(mi, "QMessageBox", _MsgBox)
    _RecordingDialog.calls = []
    _RecordingDialog.accept = False
    _MsgBox.texts = []
    yield


def _dialog() -> mi.ManufacturableItemsQmlDialog:
    return mi.ManufacturableItemsQmlDialog()


def _rows(dlg: mi.ManufacturableItemsQmlDialog) -> list[dict]:
    return list(dlg.bridge._model._rows)  # type: ignore[attr-defined]


def _titles(dlg: mi.ManufacturableItemsQmlDialog) -> list[str]:
    return [c["title"] for c in dlg.bridge.columns]  # type: ignore[attr-defined]


def _full_titles(hub: str) -> list[str]:
    """`_upd` 之后那一整套列（基础列 + 制造列，买卖价两列标题带区域名）。"""
    base = [c[0] for c in BCOLS]
    return base[:3] + [f"买价（{hub}）", f"卖价（{hub}）"] + base[5:] + [c[0] for c in MCOLS]


def _export_headers(hub: str) -> list[str]:
    """导出表头 —— 就是上面的那一套，去掉图标列（原版跳过 key=i）。"""
    return [t for t in _full_titles(hub) if t != "图标"]


# ════════════════════════════════════════════════════════════
#  初始态
# ════════════════════════════════════════════════════════════


def test_defaults(qapp):
    dlg = _dialog()
    try:
        assert dlg.ok(), "QML 没加载起来"
        assert dlg.windowTitle() == "可制造物品"

        bridge = dlg.bridge
        assert bridge.statusText == "请选择分类或搜索物品"
        assert len(bridge.categories) == 5
        # 还没加载过数据 → 列还是基础列（原版 `_build_ui` 之后才由 `_upd` 换成整套）
        assert [c["title"] for c in bridge.columns] == [c[0] for c in BCOLS]
        assert bridge.rowCount == 0
        assert bridge.progressVisible is False
        assert bridge.pinned is False
        assert bridge.pinLabel == "钉"
        assert bridge.treeRows == []
    finally:
        dlg.deleteLater()


def test_start_kicks_off_the_tree_worker(qapp):
    dlg = _dialog()
    try:
        assert dlg.bridge._tw.started is True  # type: ignore[attr-defined]
        assert dlg.bridge._tw.parent_obj is dlg.bridge  # type: ignore[attr-defined]
    finally:
        dlg.deleteLater()


def test_settings_file_is_read_when_present(qapp, tmp_path):
    (tmp_path / "mfg_browser_settings.json").write_text('{"mfg": {"hub": "Amarr"}}', encoding="utf-8")
    dlg = _dialog()
    try:
        assert dlg.bridge._mfg["hub"] == "Amarr"  # type: ignore[attr-defined]
        assert dlg.bridge._mfg["char"] == "main"  # type: ignore[attr-defined]
    finally:
        dlg.deleteLater()


def test_broken_settings_file_falls_back_to_defaults(qapp, tmp_path):
    """坏 JSON 不该把窗口带崩（原版是一段裸 `except: pass`）。"""
    (tmp_path / "mfg_browser_settings.json").write_text("{ 不是 JSON", encoding="utf-8")
    dlg = _dialog()
    try:
        assert dlg.bridge._mfg["hub"] == "Jita"  # type: ignore[attr-defined]
    finally:
        dlg.deleteLater()


# ════════════════════════════════════════════════════════════
#  分类树（带 200ms 防抖的那个）
# ════════════════════════════════════════════════════════════


def test_select_tree_node_is_debounced(qapp):
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_tree_data(_TREE)  # type: ignore[attr-defined]
        assert [r["id"] for r in bridge.treeRows] == [10, 20], "默认全折叠"

        bridge.selectTreeNode(0)
        assert bridge._iw is None, "防抖没到点之前不加载"  # type: ignore[attr-defined]

        bridge._on_tree_delayed()  # type: ignore[attr-defined]
        worker = bridge._iw  # type: ignore[attr-defined]
        assert worker.args == [[10, 11]], "要加载整棵子树（含子分类）"
        assert bridge.selectedTreeId == 10
        assert worker.started is True
    finally:
        dlg.deleteLater()


def test_toggle_tree_node_is_immediate(qapp):
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_tree_data(_TREE)  # type: ignore[attr-defined]
        bridge.toggleTreeNode(0)
        assert [r["id"] for r in bridge.treeRows] == [10, 11, 20]
        assert bridge._pending_tree_index == -1, "展开箭头不该顺手触发加载"  # type: ignore[attr-defined]
    finally:
        dlg.deleteLater()


def test_reload_disconnects_the_previous_item_worker(qapp):
    """换 ItemsW 前必须断开旧的 `done`：否则先发出的结果会覆盖后一次的数据。"""
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._reload_items([10])  # type: ignore[attr-defined]
        first = bridge._iw  # type: ignore[attr-defined]

        bridge._reload_items([7])  # type: ignore[attr-defined]
        assert bridge._iw is not first  # type: ignore[attr-defined]

        first.done.emit([{"id": 999, "z": "陈旧"}])
        assert bridge._data == [], "旧 worker 的结果不该再进来"  # type: ignore[attr-defined]
    finally:
        dlg.deleteLater()


# ════════════════════════════════════════════════════════════
#  筛选与列
# ════════════════════════════════════════════════════════════


def test_items_land_in_the_table_then_score(qapp):
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ROWS)  # type: ignore[attr-defined]

        assert [r["id"] for r in _rows(dlg)] == [2001, 34], "先落表再异步算分"
        assert bridge.statusText == "计算评分中...", "`_upd` 那句「共 N 条 |」随即被 `_calc` 覆盖（与原版一致）"
        scorer = bridge._wp  # type: ignore[attr-defined]
        assert scorer.args[1] is True, "这个窗口恒为制造评分"
        assert scorer.args[2] == bridge._mfg  # type: ignore[attr-defined]

        bridge._on_scored([{"id": 2001, "z": "渡鸦级", "_tag": "S"}])  # type: ignore[attr-defined]
        assert bridge.progressVisible is False
        assert bridge.statusText == "共 1 条 | 评分已计算"
    finally:
        dlg.deleteLater()


def test_category_filter_uses_blueprint_repo(qapp):
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ROWS + [{"id": 3002, "z": "T2产物"}])  # type: ignore[attr-defined]

        bridge.setCategoryIndex(1)  # 蓝图制造 T1
        assert [r["id"] for r in _rows(dlg)] == [2001]

        bridge.setCategoryIndex(2)  # 发明制造 T2
        assert [r["id"] for r in _rows(dlg)] == [3002]

        bridge.setCategoryIndex(4)  # 反应
        assert [r["id"] for r in _rows(dlg)] == [], "反应产物不在样例数据里"

        bridge.setCategoryIndex(0)  # 全部可制造 —— 这一档也是**过滤**，不是不过滤
        assert [r["id"] for r in _rows(dlg)] == [2001, 34]
        assert bridge.statusText == "计算评分中..."
    finally:
        dlg.deleteLater()


def test_empty_filter_says_no_data(qapp):
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items([])  # type: ignore[attr-defined]
        assert bridge.statusText == "无数据"
        assert bridge.progressVisible is False
    finally:
        dlg.deleteLater()


# ════════════════════════════════════════════════════════════
#  刷新计算
# ════════════════════════════════════════════════════════════


def test_refresh_without_data_does_nothing(qapp):
    dlg = _dialog()
    try:
        dlg.bridge.refreshScores()
        assert dlg.bridge.statusText == "请选择分类或搜索物品"
    finally:
        dlg.deleteLater()


def test_refresh_without_prices_keeps_the_status(qapp, monkeypatch):
    monkeypatch.setattr(mi, "get_container", lambda: _ContainerWithPrices(False))
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ROWS)  # type: ignore[attr-defined]
        bridge.refreshScores()
        assert bridge.statusText == "暂无价格数据，请先在主界面更新价格"
    finally:
        dlg.deleteLater()


def test_refresh_with_prices_recomputes(qapp):
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ROWS)  # type: ignore[attr-defined]
        bridge._on_scored(list(_ROWS))  # type: ignore[attr-defined]
        assert bridge.statusText == "共 2 条 | 评分已计算"

        bridge.refreshScores()
        assert bridge.statusText == "计算评分中...", "刷新会立刻回到算分态"
        assert bridge.progressVisible is True
    finally:
        dlg.deleteLater()


class _ContainerWithPrices(_Container):
    def __init__(self, has_prices: bool) -> None:
        self.market_repo = _MarketRepo(has_prices)


# ════════════════════════════════════════════════════════════
#  搜索 / 排序 / 行操作
# ════════════════════════════════════════════════════════════


def test_search_is_debounced_then_runs(qapp):
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge.setSearchText("渡鸦")
        assert bridge._sw is None  # type: ignore[attr-defined]
        bridge._do_search()  # type: ignore[attr-defined]
        assert bridge.statusText == "搜索中..."
        assert bridge._sw.args == ["渡鸦", JITA_RID]  # type: ignore[attr-defined]
    finally:
        dlg.deleteLater()


def test_sort_toggles_direction_on_the_same_column(qapp):
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ROWS)  # type: ignore[attr-defined]
        bridge.sortByColumn(1)
        assert (bridge.sortColumn, bridge.sortAscending) == (1, True)
        bridge.sortByColumn(1)
        assert (bridge.sortColumn, bridge.sortAscending) == (1, False)
        bridge.sortByColumn(0)
        assert (bridge.sortColumn, bridge.sortAscending) == (0, True)
    finally:
        dlg.deleteLater()


def test_click_cell_selects_and_copies(qapp):
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ROWS)  # type: ignore[attr-defined]

        bridge.clickCell(0, 1)  # 中文名列
        assert bridge.selectedRow == 0
        assert QGuiApplication.clipboard().text() == "渡鸦级"

        QGuiApplication.clipboard().setText("未改动")
        bridge.clickCell(0, 0)  # 图标列没有值
        assert QGuiApplication.clipboard().text() == "未改动"
    finally:
        dlg.deleteLater()


def test_copy_selection_and_copy_all(qapp):
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ROWS)  # type: ignore[attr-defined]

        bridge.copySelection()
        assert bridge.statusText == "没有选中行", "还没点过任何行"

        bridge.clickCell(0, 1)
        bridge.copySelection()
        line = QGuiApplication.clipboard().text()
        assert line.startswith("2001\t渡鸦级\tRaven\t"), "图标列换成 type_id（原版 `_copy_selection`）"
        assert bridge.statusText == "已复制 1 行"

        bridge.copyAll()
        lines = QGuiApplication.clipboard().text().splitlines()
        assert len(lines) == 2
        assert lines[1].startswith("34\t三钛合金\t")
        assert bridge.statusText == "已复制 2 行"
    finally:
        dlg.deleteLater()


def test_open_materials_uses_the_qml_material_dialog(qapp, monkeypatch):
    from ui_qml.bridge import all_items_bridge

    monkeypatch.setattr(all_items_bridge, "MatQmlDialog", _RecordingDialog)
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ROWS)  # type: ignore[attr-defined]
        bridge.openMaterials(0)
        assert _RecordingDialog.calls[0]["args"][0] == 2001

        bridge.openMaterials(9)  # 越界：不弹
        assert len(_RecordingDialog.calls) == 1
    finally:
        dlg.deleteLater()


def test_add_to_plan_wiring(qapp, monkeypatch):
    from ui_qml.bridge import industry_dialogs_bridge

    class _PlanDialog(_RecordingDialog):
        def result_data(self) -> dict:
            return {"fac": "空间站", "runs": 1}

    landed: list = []
    monkeypatch.setattr(industry_dialogs_bridge, "AddPlanDialogQmlDialog", _PlanDialog)
    monkeypatch.setattr(mi, "insert_plan_from_score", lambda *a: landed.append(a))

    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ROWS)  # type: ignore[attr-defined]

        _RecordingDialog.accept = False
        bridge.addToPlan(0)
        assert landed == []

        _RecordingDialog.accept = True
        bridge.addToPlan(0)
        assert len(landed) == 1
        type_id, name, _score, _data, cfg = landed[0]
        assert (type_id, name) == (2001, "渡鸦级")
        assert cfg == bridge._mfg  # type: ignore[attr-defined]
        assert _MsgBox.texts[-1] == "已加入制造列表: 渡鸦级"
    finally:
        dlg.deleteLater()


def test_open_compare_carries_the_selected_row(qapp, monkeypatch):
    from ui_qml.bridge import compare_bridge

    monkeypatch.setattr(compare_bridge, "CompareQmlDialog", _RecordingDialog)
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ROWS)  # type: ignore[attr-defined]
        bridge.clickCell(1, 1)
        bridge.openCompare()
        assert _RecordingDialog.calls[-1]["kwargs"]["initial_items"] == [{"type_id": 34, "name": "三钛合金"}]
    finally:
        dlg.deleteLater()


def test_settings_round_trip_only_reloads_when_hub_changes(qapp, monkeypatch):
    from ui_qml.bridge import score_dialogs_bridge

    class _SameHubDialog(_RecordingDialog):
        def get(self) -> dict:
            return {"hub": "Jita", "char": "alt", "tax": 1}

    monkeypatch.setattr(score_dialogs_bridge, "MfgQmlDialog", _SameHubDialog)
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ROWS)  # type: ignore[attr-defined]
        bridge._on_scored(list(_ROWS))  # type: ignore[attr-defined]
        assert bridge.statusText == "共 2 条 | 评分已计算"

        _RecordingDialog.accept = True
        bridge.openMfgSettings()
        assert bridge._mfg["char"] == "alt"  # type: ignore[attr-defined]
        assert bridge.statusText == "共 2 条 | 评分已计算", "区域没变就不重算（原版 `before_hub` 判断）"
    finally:
        dlg.deleteLater()


def test_settings_hub_change_reloads_the_columns(qapp, monkeypatch):
    from ui_qml.bridge import score_dialogs_bridge

    class _NewHubDialog(_RecordingDialog):
        def get(self) -> dict:
            return {"hub": "Amarr", "char": "main", "tax": 0}

    monkeypatch.setattr(score_dialogs_bridge, "MfgQmlDialog", _NewHubDialog)
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ROWS)  # type: ignore[attr-defined]
        _RecordingDialog.accept = True
        bridge.openMfgSettings()
        assert "买价（Amarr）" in _titles(dlg)
    finally:
        dlg.deleteLater()


# ════════════════════════════════════════════════════════════
#  置顶
# ════════════════════════════════════════════════════════════


def test_pin_toggles_flag_and_label(qapp):
    from PySide6.QtCore import Qt

    dlg = _dialog()
    try:
        assert not (dlg.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        dlg.bridge.setPinned(True)
        assert dlg.bridge.pinned is True
        assert dlg.bridge.pinLabel == "已钉"
        assert dlg.windowFlags() & Qt.WindowType.WindowStaysOnTopHint

        dlg.bridge.setPinned(False)
        assert dlg.bridge.pinLabel == "钉"
    finally:
        dlg.deleteLater()


# ════════════════════════════════════════════════════════════
#  导出 / 关闭收尾
# ════════════════════════════════════════════════════════════


def test_export_without_data_only_hints(qapp):
    dlg = _dialog()
    try:
        dlg.bridge.exportData()
        assert dlg.bridge.statusText == "没有数据可导出"
    finally:
        dlg.deleteLater()


def test_export_writes_csv(qapp, monkeypatch, tmp_path):
    target = tmp_path / "out.csv"
    monkeypatch.setattr("ui_qml.file_dialogs.get_save_filename", lambda *a, **k: str(target))
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ROWS)  # type: ignore[attr-defined]
        bridge.exportData()

        lines = target.read_text(encoding="utf-8-sig").splitlines()
        assert lines[0] == ",".join(_export_headers("Jita")), "列就是表格当前那一套，去掉图标列"
        assert lines[1].startswith("渡鸦级,Raven,100.00,"), "浮点两位小数（与原版口径一致）"
        assert bridge.statusText == "已导出 2 行"
    finally:
        dlg.deleteLater()


def test_stop_finishes_every_running_worker(qapp, monkeypatch):
    monkeypatch.setattr(mi, "MfgTreeW", _SlowWorker)
    monkeypatch.setattr(mi, "ItemsW", _SlowWorker)
    monkeypatch.setattr(mi, "SearchItemsW", _SlowWorker)
    monkeypatch.setattr(mi, "ScoreW", _SlowWorker)

    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ROWS)  # type: ignore[attr-defined]
        bridge._reload_items([10])  # type: ignore[attr-defined]
        bridge.setSearchText("渡鸦")
        bridge._do_search()  # type: ignore[attr-defined]

        workers = [bridge._tw, bridge._iw, bridge._wp, bridge._sw]  # type: ignore[attr-defined]
        dlg.done(0)
        for worker in workers:
            assert worker.interrupted is True
            assert worker.waited, "每个在跑的线程都要被 wait 收尾"
    finally:
        dlg.deleteLater()


# ════════════════════════════════════════════════════════════
#  纯函数：制造核算明细文案
# ════════════════════════════════════════════════════════════


def test_breakdown_text_status_uses_this_dialogs_own_wording():
    """这个窗口的状态码文案与全物品窗口不同（少了 `no_depth`，`no_materials` 写成 `no_mats`）。"""
    assert mi.breakdown_text({"status": "no_mats"}) == "状态: 蓝图无材料数据"
    assert mi.breakdown_text({"status": "no_depth"}) == "状态: no_depth", "没登记的状态码原样回显"
    assert mi.breakdown_text({"status": "no_price"}) == "状态: 查不到价格数据"


def test_breakdown_text_lines_and_optional_fees():
    text = mi.breakdown_text(
        {
            "score": 88.2,
            "profit_per_run": 1234.0,
            "margin_pct": 5.5,
            "isk_per_hour": 999.0,
            "breakdown": {"material_cost": 100.0, "run_cost": 1.0, "install_fee": 2.0},
        }
    )
    lines = text.splitlines()
    assert lines[0] == "评分: 88"
    assert lines[1] == "单批利润: 1,234 ISK"
    assert lines[3] == "每小时利润: 999 ISK"
    assert lines[4] == "材料成本: 100 ISK"
    assert lines[5] == "运行成本: 1 ISK"
    assert lines[6] == "安装费: 2 ISK"
    assert len(lines) == 7, "没有的费用项不占行"
