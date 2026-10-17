"""机库桥「批量填充 T2 蓝图成本」的 mock 契约。

只断言**落库参数**（repo 收到哪些 id、cost_per_run 值）与提示，不碰 Qt/QML：
`auto_fill_cost_per_run` 是纯编排函数（依赖在函数内 import，便于 patch）。
"""

from __future__ import annotations

from ui_qml.bridge.blueprint_actions import auto_fill_cost_per_run


class _FakeBridge:
    def __init__(self) -> None:
        self.hints: list[str] = []
        self.reloaded = 0

    def _set_bp_hint(self, text: str) -> None:
        self.hints.append(text)

    def loadBlueprints(self) -> None:
        self.reloaded += 1


def _patch_deps(monkeypatch, costs: dict[int, dict], calls: list[tuple[list[int], dict]]):
    class _Container:
        db = object()

    monkeypatch.setattr("core.container.get_container", lambda: _Container())
    monkeypatch.setattr("services.research_plans.research_cost_per_run", lambda db, bid: costs.get(bid))

    def _update(ids, **kwargs):
        calls.append((list(ids), dict(kwargs)))
        return len(ids)

    monkeypatch.setattr("services.inventory_manager.update_blueprints_batch", _update)


def _invention(bid: int, cost: float, outcomes: list[tuple[int, float]] | None = None) -> dict:
    return {
        "kind": "invention",
        "cost_per_run": cost,
        "outcomes": [{"blueprint_type_id": obid, "cost_per_run": ocost} for obid, ocost in (outcomes or [(bid, cost)])],
    }


def test_fills_every_selected_t2_bpc(monkeypatch):
    """多选 2 张 T2 BPC + 1 张 T1 + 1 张原图 → 只写 2 张 T2 BPC，各按自己的成本。"""
    calls: list[tuple[list[int], dict]] = []
    _patch_deps(
        monkeypatch,
        {5001: _invention(5001, 100.0), 5002: _invention(5002, 200.0)},
        calls,
    )
    bridge = _FakeBridge()
    rows = [
        {"id": 1, "blueprint_type_id": 5001, "tech_level": 2, "is_bpo": False},
        {"id": 2, "blueprint_type_id": 5002, "tech_level": 2, "is_bpo": False},
        {"id": 3, "blueprint_type_id": 5003, "tech_level": 1, "is_bpo": False},  # T1 跳过
        {"id": 4, "blueprint_type_id": 5004, "tech_level": 2, "is_bpo": True},  # 原图跳过
    ]
    auto_fill_cost_per_run(bridge, rows)

    assert calls == [([1], {"cost_per_run": 100.0}), ([2], {"cost_per_run": 200.0})]
    assert bridge.reloaded == 1
    assert "2 张" in bridge.hints[-1]


def test_same_cost_grouped_into_one_update(monkeypatch):
    """同成本值的多张合并成一次 update（repo 契约：批量写入）。"""
    calls: list[tuple[list[int], dict]] = []
    _patch_deps(
        monkeypatch,
        {5001: _invention(5001, 100.0), 5002: _invention(5002, 100.004)},
        calls,
    )
    bridge = _FakeBridge()
    auto_fill_cost_per_run(
        bridge,
        [
            {"id": 7, "blueprint_type_id": 5001, "tech_level": 2, "is_bpo": False},
            {"id": 8, "blueprint_type_id": 5002, "tech_level": 2, "is_bpo": False},
        ],
    )
    assert calls == [([7, 8], {"cost_per_run": 100.0})]


def test_multi_outcome_picks_the_selected_blueprint(monkeypatch):
    """同一 T1 有多个 T2 产物时，只取命中**本行蓝图**的那个产物成本（不取最优/第一个）。"""
    calls: list[tuple[list[int], dict]] = []
    _patch_deps(
        monkeypatch,
        {5001: _invention(5001, 999.0, outcomes=[(5001, 111.0), (5002, 222.0)])},
        calls,
    )
    bridge = _FakeBridge()
    auto_fill_cost_per_run(bridge, [{"id": 1, "blueprint_type_id": 5001, "tech_level": 2, "is_bpo": False}])
    assert calls == [([1], {"cost_per_run": 111.0})]


def test_single_t1_keeps_legacy_copy_cost_path(monkeypatch):
    """单选一张 T1 → 保留旧行为：按拷贝活动成本填写（不是 T2 批量路径）。"""
    calls: list[tuple[list[int], dict]] = []
    _patch_deps(monkeypatch, {5001: {"kind": "copying", "cost_per_run": 777.0}}, calls)
    bridge = _FakeBridge()
    auto_fill_cost_per_run(bridge, [{"id": 3, "blueprint_type_id": 5001, "tech_level": 1, "is_bpo": False}])
    assert calls == [([3], {"cost_per_run": 777.0})]
    assert bridge.reloaded == 1


def test_no_blueprint_info_only_hints(monkeypatch):
    """选中行没有蓝图信息（无 blueprint_type_id）→ 不写库，给提示。"""
    calls: list[tuple[list[int], dict]] = []
    _patch_deps(monkeypatch, {}, calls)
    bridge = _FakeBridge()
    auto_fill_cost_per_run(bridge, [{"id": 1, "blueprint_type_id": None, "tech_level": 1, "is_bpo": False}])
    assert calls == []
    assert bridge.reloaded == 0
    assert bridge.hints


def test_no_invention_path_skips_write(monkeypatch):
    """T2 蓝图查不到发明路径（research_cost_per_run 返回 None）→ 不写、给提示。"""
    calls: list[tuple[list[int], dict]] = []
    _patch_deps(monkeypatch, {}, calls)
    bridge = _FakeBridge()
    auto_fill_cost_per_run(bridge, [{"id": 1, "blueprint_type_id": 5001, "tech_level": 2, "is_bpo": False}])
    assert calls == []
    assert bridge.reloaded == 0
    assert "发明" in bridge.hints[-1]
