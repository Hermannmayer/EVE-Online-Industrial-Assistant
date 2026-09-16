"""全物品浏览器（QML 版）的业务契约。

对照 Widgets 版的 `AllItemsDialog` / `MatDlg`：这里断的是桥的属性、分类树的扁平化、
筛选后的表数据、评分模式换列、导出与右键菜单的接线。

`qapp` fixture 是**必须**的：这些用例都要构造 QWidget（`QmlDialog` 是 QDialog），
漏了会挂死而不是报错（本仓踩过）。
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QGuiApplication

from ui_qml.bridge import all_items_bridge as ai
from ui_qml.models.all_items_models import BCOLS, MCOLS, TCOLS
from ui_qml.workers.all_items_workers import JITA_RID

pytestmark = pytest.mark.ui

_ALL_ROWS = [
    {"id": 2001, "z": "渡鸦级", "e": "Raven", "bp": 100.0, "sp": 120.0, "ap": 110.0, "v": 10000.0},
    {"id": 34, "z": "三钛合金", "e": "Tritanium", "bp": 5.0, "sp": 6.0, "ap": 5.5, "v": 0.01},
]

_TREE = [
    {"id": 10, "p": None, "n": "舰船"},
    {"id": 11, "p": 10, "n": "护卫舰"},
    {"id": 12, "p": 10, "n": "巡洋舰"},
    {"id": 13, "p": 11, "n": "突击护卫舰"},
    {"id": 20, "p": None, "n": "矿物"},
]


# ════════════════════════════════════════════════════════════
#  替身
# ════════════════════════════════════════════════════════════


class _FakeWorker(QObject):
    """`TreeW` / `ItemsW` / `SearchItemsW` / `ScoreW` 的同步替身。

    桥用四种不同的构造签名构造它们：`(parent)`、`(ids, rid=, parent=)`、
    `(query, rid, parent)`、`(items, is_mfg, cfg, parent)` —— 一律照收，
    顺便记下实参供断言。`start()` 只打标记，**不**回调，免得用例拿到
    「构造途中就派发结果」的时序。
    """

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
    """一直说自己在跑 —— 验证关窗时确实做了收尾（QThread 运行中被析构会中止进程）。"""

    def isRunning(self) -> bool:
        return True


class _Repo:
    """`blueprint_repo` / `item_repo` 的替身（筛选只读这几个 id 集合）。"""

    def get_all_product_ids(self, activity: str) -> list[int]:
        return [2001] if activity == "manufacturing" else [3001]

    def get_t1_manufacturable_product_ids(self) -> list[int]:
        return [2001]

    def get_t2_manufacturable_product_ids(self) -> list[int]:
        return [3002]

    def get_faction_manufacturable_product_ids(self) -> list[int]:
        return [3003]

    def get_all_blueprint_product_ids(self) -> list[int]:
        return [2001]

    def get_planetary_product_ids(self) -> list[int]:
        return [4001]


class _Container:
    blueprint_repo = _Repo()
    item_repo = _Repo()


class _RecordingDialog:
    """二级弹窗替身：记下构造参数，`exec()` 按 `accept` 立刻返回（不真开窗、不阻塞）。"""

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
    """`FMessageDialog` 替身：只记下调用（用例不该弹模态窗）。"""

    texts: list[str] = []

    @staticmethod
    def information(_parent, _title, text) -> None:
        _MsgBox.texts.append(str(text))

    @staticmethod
    def warning(_parent, _title, text) -> None:
        _MsgBox.texts.append(str(text))


@pytest.fixture(autouse=True)
def stub_env(monkeypatch, tmp_path):
    """后台 worker / 容器 / 设置目录全部打桩（用例都不该碰 DB 与用户数据）。"""
    monkeypatch.setattr(ai, "TreeW", _FakeWorker)
    monkeypatch.setattr(ai, "ItemsW", _FakeWorker)
    monkeypatch.setattr(ai, "SearchItemsW", _FakeWorker)
    monkeypatch.setattr(ai, "ScoreW", _FakeWorker)
    monkeypatch.setattr(ai, "get_container", lambda: _Container())
    monkeypatch.setattr(ai, "data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(ai, "FMessageDialog", _MsgBox)
    _RecordingDialog.calls = []
    _RecordingDialog.accept = False
    _MsgBox.texts = []
    yield


def _dialog(manufacturable_only: bool = False) -> ai.AllItemsQmlDialog:
    return ai.AllItemsQmlDialog(None, manufacturable_only)


def _rows(dlg: ai.AllItemsQmlDialog) -> list[dict]:
    return list(dlg.bridge._model._rows)  # type: ignore[attr-defined]


def _titles(dlg: ai.AllItemsQmlDialog) -> list[str]:
    return [c["title"] for c in dlg.bridge.columns]  # type: ignore[attr-defined]


# ════════════════════════════════════════════════════════════
#  初始态
# ════════════════════════════════════════════════════════════


def test_defaults(qapp):
    dlg = _dialog()
    try:
        assert dlg.ok(), "QML 没加载起来"
        assert dlg.windowTitle() == "全物品查询"

        bridge = dlg.bridge
        assert bridge.statusText == "就绪"
        assert bridge.manufacturableOnly is False
        assert len(bridge.categories) == 7, "全物品有 7 个类别（含行星开发）"
        assert [c["title"] for c in bridge.columns] == [c[0] for c in BCOLS]
        assert bridge.treeRows == []
        assert bridge.rowCount == 0
        assert bridge.progressVisible is False
        assert bridge.pinned is False
        assert bridge.sortColumn == -1
    finally:
        dlg.deleteLater()


def test_manufacturable_only_switches_title_and_categories(qapp):
    dlg = _dialog(manufacturable_only=True)
    try:
        assert dlg.windowTitle() == "可制造物品 - 添加至生产计划"
        assert dlg.bridge.manufacturableOnly is True
        assert len(dlg.bridge.categories) == 5, "可制造模式只有 5 个类别"
    finally:
        dlg.deleteLater()


def test_start_kicks_off_the_tree_and_item_workers(qapp):
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        assert bridge._tw.started is True  # type: ignore[attr-defined]
        assert bridge._iw.started is True  # type: ignore[attr-defined]
        assert bridge._iw.args == [None], "首次是全量加载（ids=None）"  # type: ignore[attr-defined]
        assert bridge._iw.parent_obj is bridge  # type: ignore[attr-defined]
    finally:
        dlg.deleteLater()


def test_settings_file_is_read_when_present(qapp, tmp_path):
    """`score_settings.json` 里的区域/角色要生效（原 `_load_settings`）。"""
    (tmp_path / "score_settings.json").write_text(
        '{"mfg": {"hub": "Amarr"}, "trade": {"bh": "Dodixie"}}', encoding="utf-8"
    )
    dlg = _dialog()
    try:
        assert dlg.bridge._mfg["hub"] == "Amarr"  # type: ignore[attr-defined]
        assert dlg.bridge._trade["bh"] == "Dodixie"  # type: ignore[attr-defined]
        assert dlg.bridge._mfg["char"] == "main", "没给的键保持默认"  # type: ignore[attr-defined]
    finally:
        dlg.deleteLater()


# ════════════════════════════════════════════════════════════
#  分类树（原 QTreeWidget → 扁平行）
# ════════════════════════════════════════════════════════════


def test_market_tree_rows_is_depth_first():
    rows = ai.market_tree_rows(_TREE)
    assert [(r["id"], r["depth"]) for r in rows] == [(10, 0), (11, 1), (13, 2), (12, 1), (20, 0)]
    assert rows[0]["hasChildren"] is True
    assert rows[0]["parent"] is None
    assert rows[2]["parent"] == 11


def test_market_tree_rows_treats_orphans_as_roots():
    """父节点不在集合里的行按顶层处理（原版 `p in nm` 的判据）。"""
    rows = ai.market_tree_rows([{"id": 1, "p": 999, "n": "孤儿"}])
    assert [(r["id"], r["depth"]) for r in rows] == [(1, 0)]


def test_visible_rows_hide_collapsed_subtrees():
    rows = ai.market_tree_rows(_TREE)
    assert [r["id"] for r in ai.visible_tree_rows(rows, set())] == [10, 20], "默认全折叠"
    assert [r["id"] for r in ai.visible_tree_rows(rows, {10})] == [10, 11, 12, 20]
    assert [r["id"] for r in ai.visible_tree_rows(rows, {10, 11})] == [10, 11, 13, 12, 20]
    assert ai.visible_tree_rows(rows, {10})[0]["expanded"] is True


def test_subtree_ids_covers_self_and_descendants():
    rows = ai.market_tree_rows(_TREE)
    assert ai.subtree_ids(rows, 10) == {10, 11, 12, 13}
    assert ai.subtree_ids(rows, 11) == {11, 13}
    assert ai.subtree_ids(rows, 20) == {20}
    assert ai.subtree_ids(rows, 999) == set()


def test_toggle_and_select_tree_node(qapp):
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_tree_data(_TREE)  # type: ignore[attr-defined]

        assert [r["id"] for r in bridge.treeRows] == [10, 20]
        bridge.toggleTreeNode(0)  # 展开「舰船」
        assert [r["id"] for r in bridge.treeRows] == [10, 11, 12, 20]
        bridge.toggleTreeNode(0)  # 再点一次收回
        assert [r["id"] for r in bridge.treeRows] == [10, 20]

        bridge.setSearchText("渡鸦")
        bridge.selectTreeNode(0)
        worker = bridge._iw  # type: ignore[attr-defined]
        assert worker.args == [sorted({10, 11, 12, 13})], "点分类要加载整棵子树"
        assert bridge.selectedTreeId == 10
        assert bridge.searchText == "", "点分类要清空搜索框（原版 `_search_input.clear()`）"
        assert worker.started is True
    finally:
        dlg.deleteLater()


def test_toggle_leaf_node_does_nothing(qapp):
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_tree_data([{"id": 20, "p": None, "n": "矿物"}])  # type: ignore[attr-defined]
        bridge.toggleTreeNode(0)
        assert bridge.treeRows[0]["expanded"] is False

        bridge.toggleTreeNode(9)  # 越界：忽略
        assert len(bridge.treeRows) == 1
    finally:
        dlg.deleteLater()


# ════════════════════════════════════════════════════════════
#  筛选与显示模式
# ════════════════════════════════════════════════════════════


def test_items_land_in_the_table(qapp):
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ALL_ROWS)  # type: ignore[attr-defined]
        assert len(_rows(dlg)) == 2
        assert bridge.rowCount == 2
        assert bridge.statusText == "共 2 条"
    finally:
        dlg.deleteLater()


def test_category_filter_uses_blueprint_repo(qapp):
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ALL_ROWS + [{"id": 4001, "z": "行星产物"}])  # type: ignore[attr-defined]

        bridge.setCategoryIndex(1)  # 无法制造获得 —— 去掉所有有蓝图的
        assert [r["id"] for r in _rows(dlg)] == [34, 4001]

        bridge.setCategoryIndex(2)  # 蓝图制造 T1
        assert [r["id"] for r in _rows(dlg)] == [2001]

        bridge.setCategoryIndex(6)  # 行星开发
        assert [r["id"] for r in _rows(dlg)] == [4001]

        bridge.setCategoryIndex(0)  # 全部
        assert len(_rows(dlg)) == 3
    finally:
        dlg.deleteLater()


def test_manufacturing_mode_appends_mfg_columns_and_scores(qapp):
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ALL_ROWS)  # type: ignore[attr-defined]
        bridge.showMfgMode()

        base = [c[0] for c in BCOLS]
        expected = base[:3] + ["买价（Jita）", "卖价（Jita）"] + base[5:] + [c[0] for c in MCOLS]
        assert _titles(dlg) == expected
        assert bridge.showManufacturing is True
        assert bridge.progressVisible is True
        assert bridge.statusText == "计算评分中..."

        scorer = bridge._wp  # type: ignore[attr-defined]
        assert scorer.args[1] is True, "制造模式要 is_mfg=True"
        assert scorer.args[2] == bridge._mfg  # type: ignore[attr-defined]
        assert scorer.parent_obj is bridge

        bridge._on_scored([{"id": 2001, "z": "渡鸦级", "_tag": "S"}])  # type: ignore[attr-defined]
        assert bridge.progressVisible is False
        assert bridge.statusText == "共 1 条 | 评分已计算"
    finally:
        dlg.deleteLater()


def test_trade_mode_appends_trade_columns(qapp):
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ALL_ROWS)  # type: ignore[attr-defined]
        bridge.showTradeMode()

        titles = _titles(dlg)
        assert "买价（Amarr卖单）" in titles, "贸易模式的列标题带区域 + 买卖单"
        assert "卖价（Jita卖单）" in titles
        assert titles[-len(TCOLS) :] == [c[0] for c in TCOLS]
        assert bridge.showTrade is True

        scorer = bridge._wp  # type: ignore[attr-defined]
        assert scorer.args[1] is False, "贸易模式要 is_mfg=False"
        assert scorer.args[2] == bridge._trade  # type: ignore[attr-defined]
    finally:
        dlg.deleteLater()


def test_switching_modes_replaces_the_other(qapp):
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ALL_ROWS)  # type: ignore[attr-defined]
        bridge.showMfgMode()
        bridge.showTradeMode()
        assert bridge.showManufacturing is False
        assert bridge.showTrade is True
    finally:
        dlg.deleteLater()


def test_empty_mode_switch_only_says_no_data(qapp):
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge.showMfgMode()
        assert bridge.statusText == "无数据"
        assert bridge.progressVisible is False, "没数据不该起评分线程"
    finally:
        dlg.deleteLater()


def test_calc_stops_the_previous_scorer(qapp, monkeypatch):
    """连点两次评分不该留下两条线程（原版直接覆盖 `self._wp`，旧线程仍在跑）。"""
    monkeypatch.setattr(ai, "ScoreW", _SlowWorker)
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ALL_ROWS)  # type: ignore[attr-defined]
        bridge.showMfgMode()
        first = bridge._wp  # type: ignore[attr-defined]
        bridge.showMfgMode()
        assert first.interrupted is True
        assert first.waited, "旧线程要被 wait 收尾"
        assert bridge._wp is not first  # type: ignore[attr-defined]
    finally:
        dlg.deleteLater()


# ════════════════════════════════════════════════════════════
#  搜索
# ════════════════════════════════════════════════════════════


def test_search_is_debounced_then_runs(qapp):
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge.setSearchText("渡鸦")
        assert bridge.searchText == "渡鸦"
        assert bridge._sw is None, "防抖没到点之前不查库"  # type: ignore[attr-defined]

        bridge._do_search()  # type: ignore[attr-defined]
        assert bridge.statusText == "搜索中..."
        assert bridge._sw.args == ["渡鸦", JITA_RID]  # type: ignore[attr-defined]
    finally:
        dlg.deleteLater()


def test_search_with_blank_query_does_nothing(qapp):
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge.setSearchText("   ")
        bridge._do_search()  # type: ignore[attr-defined]
        assert bridge._sw is None  # type: ignore[attr-defined]
    finally:
        dlg.deleteLater()


# ════════════════════════════════════════════════════════════
#  排序 / 行操作
# ════════════════════════════════════════════════════════════


def test_sort_toggles_direction_on_the_same_column(qapp):
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ALL_ROWS)  # type: ignore[attr-defined]

        bridge.sortByColumn(1)
        assert (bridge.sortColumn, bridge.sortAscending) == (1, True)
        bridge.sortByColumn(1)
        assert (bridge.sortColumn, bridge.sortAscending) == (1, False)
        bridge.sortByColumn(2)
        assert (bridge.sortColumn, bridge.sortAscending) == (2, True), "换列要回到升序"

        bridge.sortByColumn(99)  # 越界：忽略
        assert bridge.sortColumn == 2
    finally:
        dlg.deleteLater()


def test_row_info_and_clipboard(qapp):
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ALL_ROWS)  # type: ignore[attr-defined]

        assert bridge.rowInfo(0) == {
            "valid": True,
            "typeId": 2001,
            "name": "渡鸦级",
            "hasMfgDetail": False,
            "hasTradeDetail": False,
        }
        assert bridge.rowInfo(9)["valid"] is False, "越界行要报无效"

        bridge.copyName(0)
        assert QGuiApplication.clipboard().text() == "渡鸦级"
        bridge.copyId(0)
        assert QGuiApplication.clipboard().text() == "2001"
    finally:
        dlg.deleteLater()


def test_click_cell_selects_and_copies(qapp):
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ALL_ROWS)  # type: ignore[attr-defined]

        bridge.clickCell(0, 3)  # 买价列
        assert bridge.selectedRow == 0
        assert QGuiApplication.clipboard().text() == "100.0", "复制的是原始值，不是千分位显示串"

        QGuiApplication.clipboard().setText("未改动")
        bridge.clickCell(0, 0)  # 图标列没有值
        assert QGuiApplication.clipboard().text() == "未改动", "空值不覆盖剪贴板"
    finally:
        dlg.deleteLater()


def test_open_materials_uses_the_qml_material_dialog(qapp, monkeypatch):
    monkeypatch.setattr(ai, "MatQmlDialog", _RecordingDialog)
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ALL_ROWS)  # type: ignore[attr-defined]
        bridge.openMaterials(0)
        assert _RecordingDialog.calls[0]["args"][0] == 2001

        bridge.openMaterials(9)  # 越界：不弹
        assert len(_RecordingDialog.calls) == 1
    finally:
        dlg.deleteLater()


# ════════════════════════════════════════════════════════════
#  导出 / 批量对比 / 加入计划（跨模块接线）
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
        bridge._on_items(_ALL_ROWS)  # type: ignore[attr-defined]
        bridge.exportData()

        lines = target.read_text(encoding="utf-8-sig").splitlines()
        assert lines[0] == "中文名,English,买价,卖价,均价,体积", "图标列不进导出（原版跳过 key=i）"
        assert lines[1].startswith("渡鸦级,Raven,100.00,")
        assert bridge.statusText == "已导出 2 行"
    finally:
        dlg.deleteLater()


def test_open_compare_carries_the_selected_row(qapp, monkeypatch):
    from ui_qml.bridge import compare_bridge

    monkeypatch.setattr(compare_bridge, "CompareQmlDialog", _RecordingDialog)
    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ALL_ROWS)  # type: ignore[attr-defined]

        bridge.openCompare()
        assert _RecordingDialog.calls[-1]["kwargs"]["initial_items"] == [], "没选中行就是空列表"

        bridge.clickCell(1, 1)
        bridge.openCompare()
        assert _RecordingDialog.calls[-1]["kwargs"]["initial_items"] == [{"type_id": 34, "name": "三钛合金"}]
    finally:
        dlg.deleteLater()


def test_add_to_plan_wiring(qapp, monkeypatch):
    from ui_qml.bridge import industry_dialogs_bridge

    class _PlanDialog(_RecordingDialog):
        def result_data(self) -> dict:
            return {"fac": "空间站", "runs": 1}

    landed: list = []
    monkeypatch.setattr(industry_dialogs_bridge, "AddPlanDialogQmlDialog", _PlanDialog)
    monkeypatch.setattr(ai, "insert_plan_from_score", lambda *a: landed.append(a))

    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ALL_ROWS)  # type: ignore[attr-defined]

        _RecordingDialog.accept = False
        bridge.addToPlan(0)
        assert landed == [], "取消对话框就不该落库"

        _RecordingDialog.accept = True
        bridge.addToPlan(0)
        assert len(landed) == 1, "确定后要落一条计划"
        type_id, name, _score, data, cfg = landed[0]
        assert (type_id, name) == (2001, "渡鸦级")
        assert data == {"fac": "空间站", "runs": 1}
        assert cfg == bridge._mfg  # type: ignore[attr-defined]
        assert _MsgBox.texts[-1] == "已加入制造列表: 渡鸦级"
    finally:
        dlg.deleteLater()


def test_add_to_plan_ignores_an_invalid_row(qapp):
    dlg = _dialog()
    try:
        dlg.bridge.addToPlan(9)
        assert _MsgBox.texts == []
    finally:
        dlg.deleteLater()


def test_settings_dialogs_round_trip(qapp, monkeypatch):
    from ui_qml.bridge import score_dialogs_bridge

    class _SettingsDialog(_RecordingDialog):
        def get(self) -> dict:
            return {"hub": "Amarr", "char": "alt", "tax": 3}

    monkeypatch.setattr(score_dialogs_bridge, "MfgQmlDialog", _SettingsDialog)
    monkeypatch.setattr(score_dialogs_bridge, "TradeQmlDialog", _SettingsDialog)

    dlg = _dialog()
    try:
        bridge = dlg.bridge
        _RecordingDialog.accept = False
        bridge.openMfgSettings()
        assert bridge._mfg["hub"] == "Jita", "取消就不改设置"  # type: ignore[attr-defined]

        _RecordingDialog.accept = True
        bridge.openMfgSettings()
        assert bridge._mfg["hub"] == "Amarr"  # type: ignore[attr-defined]
        assert _RecordingDialog.calls[0]["args"][0] == {"hub": "Jita", "char": "main", "tax": 0}
    finally:
        dlg.deleteLater()


# ════════════════════════════════════════════════════════════
#  置顶
# ════════════════════════════════════════════════════════════


def test_pin_toggles_the_stay_on_top_flag(qapp):
    from PySide6.QtCore import Qt

    dlg = _dialog()
    try:
        assert not (dlg.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        dlg.bridge.setPinned(True)
        assert dlg.bridge.pinned is True
        assert dlg.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
        dlg.bridge.setPinned(False)
        assert not (dlg.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
    finally:
        dlg.deleteLater()


# ════════════════════════════════════════════════════════════
#  关闭收尾
# ════════════════════════════════════════════════════════════


def test_stop_finishes_every_running_worker(qapp, monkeypatch):
    """关窗必须让在跑的线程收尾。

    不收尾的话线程是桥的子对象、桥随对话框一起销毁 —— `QThread` 在运行时被析构，
    Qt 直接 `qFatal` 中止进程（实测退出码 127、一行日志都没有）。
    """
    monkeypatch.setattr(ai, "TreeW", _SlowWorker)
    monkeypatch.setattr(ai, "ItemsW", _SlowWorker)
    monkeypatch.setattr(ai, "SearchItemsW", _SlowWorker)
    monkeypatch.setattr(ai, "ScoreW", _SlowWorker)

    dlg = _dialog()
    try:
        bridge = dlg.bridge
        bridge._on_items(_ALL_ROWS)  # type: ignore[attr-defined]
        bridge.showMfgMode()
        bridge.setSearchText("渡鸦")
        bridge._do_search()  # type: ignore[attr-defined]

        workers = [bridge._tw, bridge._iw, bridge._wp, bridge._sw]  # type: ignore[attr-defined]
        dlg.done(0)  # 确定 / 取消 / Esc 都走这里
        for worker in workers:
            assert worker.interrupted is True
            assert worker.waited, "每个在跑的线程都要被 wait 收尾"
    finally:
        dlg.deleteLater()


# ════════════════════════════════════════════════════════════
#  制造材料明细（原 `MatDlg`）
# ════════════════════════════════════════════════════════════


class _ItemRepo:
    def get_name(self, type_id: int) -> str:
        return f"物品{type_id}"


class _BpRepo:
    def __init__(self, materials):
        self._materials = materials

    def get_manufacturing_materials(self, type_id: int):
        return self._materials


def _stub_material_container(monkeypatch, materials):
    class _C:
        item_repo = _ItemRepo()
        blueprint_repo = _BpRepo(materials)

    monkeypatch.setattr(ai, "get_container", lambda: _C())


def test_material_dialog_lists_materials(monkeypatch, qapp):
    _stub_material_container(
        monkeypatch,
        (1001, [(34, 1000, "三钛合金", "Tritanium", 5.0), (35, 2, "", "Pyerite", None)]),
    )
    dlg = ai.MatQmlDialog(2001, None)
    try:
        assert dlg.ok(), "QML 没加载起来"
        bridge = dlg.bridge
        assert bridge.itemTitle == "制造材料: 物品2001"
        assert bridge.found is True
        assert bridge.totalText == "总成本: 5,000.00 ISK", "单价为空按 0 计（原版 `sp or 0`）"
        assert [r["text"] for r in bridge.rows] == [
            "  三钛合金 x1,000 @ 5.00 = 5,000.00",
            "  Pyerite x2 @ 0.00 = 0.00",
        ]
    finally:
        dlg.deleteLater()


def test_material_dialog_without_blueprint(monkeypatch, qapp):
    _stub_material_container(monkeypatch, None)
    dlg = ai.MatQmlDialog(2001, None)
    try:
        assert dlg.bridge.found is False
        assert dlg.bridge.rows == []
        assert dlg.bridge.totalText == ""
    finally:
        dlg.deleteLater()


# ════════════════════════════════════════════════════════════
#  纯函数：明细文案
# ════════════════════════════════════════════════════════════


def test_breakdown_text_mfg_status_short_circuits():
    assert ai.breakdown_text({"status": "no_price"}, True) == "查不到价格数据，请在主界面更新价格"
    assert ai.breakdown_text({"status": "no_depth"}, True) == "市场没有买单"
    assert ai.breakdown_text({"status": "no_blueprint"}, True) == "此物品没有制造蓝图"


def test_breakdown_text_falls_back_to_the_raw_status():
    assert ai.breakdown_text({"status": "weird"}, True) == "weird"
    assert ai.breakdown_text({"status": "no_price"}, False) == "状态: no_price"
