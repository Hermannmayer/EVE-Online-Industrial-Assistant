"""贸易购物车控制器的契约（`ui_qml/views/trade_cart_window.py`）。

购物车是**文件持久化**的（`data/trade_cart.json`），所以这里重点是导入边界：
坏 JSON、版本不符、缺字段 —— 三种都只能降级成空车，不能把开窗带崩。
分组/汇总/去重是纯逻辑，一并钉住。
"""

from __future__ import annotations

import json

import pytest

from ui_qml.views import trade_cart_window as tcw

JITA, AMARR = "Jita", "Amarr"


@pytest.fixture
def cart(tmp_path, monkeypatch):
    """把购物车文件指到 tmp_path，返回一个空车。"""
    path = tmp_path / "trade_cart.json"
    monkeypatch.setattr(tcw, "trade_cart_file", lambda: str(path))
    c = tcw.TradeCartController()
    c.path = path
    return c


def _row(tid: int = 34, zh: str = "三钛合金", pa: float = 4.0, pb: float = 9.0, vol: float = 0.01):
    return {
        "id": tid,
        "z": zh,
        "e": "Tritanium",
        "v": vol,
        "pa": pa,
        "pb": pb,
        "spread": pb - pa,
        "from_hub": JITA,
        "from_mode": "sell",
        "to_hub": AMARR,
        "to_mode": "buy",
    }


# ── 去重与分组 ──────────────────────────────────────────────


@pytest.mark.fast
def test_same_item_same_direction_stacks_quantity(cart):
    cart.add(_row())
    cart.add(_row())

    assert cart.count() == 1
    assert cart.groups()[0]["rows"][0]["qty"] == 2
    assert "2" in cart.groups()[0]["summary"]


@pytest.mark.fast
def test_same_item_opposite_direction_is_a_separate_group(cart):
    """A→B 与 B→A 是两笔生意，不能合并。"""
    cart.add(_row())
    flipped = _row()
    flipped.update(from_hub=AMARR, to_hub=JITA)
    cart.add(flipped)

    labels = [g["label"] for g in cart.groups()]

    assert cart.count() == 2
    assert labels == ["Jita(卖单) → Amarr(买单)", "Amarr(卖单) → Jita(买单)"]


@pytest.mark.fast
def test_price_type_difference_also_splits_groups(cart):
    """同一个中心对、但一边取买单价一边取卖单价 —— 也是不同的一笔。"""
    cart.add(_row())
    other = _row()
    other["from_mode"] = "buy"
    cart.add(other)

    assert len(cart.groups()) == 2


@pytest.mark.fast
def test_rows_without_prices_are_rejected(cart):
    cart.add({"id": 0, "z": "无价物品"})

    assert cart.count() == 0


@pytest.mark.fast
def test_group_summary_sums_amount_volume_and_profit(cart):
    cart.add(_row(pa=4.0, pb=9.0, vol=0.5))
    cart.set_qty(0, 0, 10)

    summary = cart.groups()[0]["summary"]

    assert "1 项" in summary
    assert "40" in summary  # 金额 = 4 × 10
    assert "5.00" in summary  # 体积 = 0.5 × 10
    assert "50" in summary  # 预计利润 = (9-4) × 10


# ── 编辑 ────────────────────────────────────────────────────


@pytest.mark.fast
def test_quantity_is_clamped_to_at_least_one(cart):
    cart.add(_row())
    cart.set_qty(0, 0, 0)

    assert cart.groups()[0]["rows"][0]["qty"] == 1


@pytest.mark.fast
def test_out_of_range_indexes_are_ignored(cart):
    """QML 传回来的下标可能已过期（列表刚重建）——越界一律当没点到。"""
    cart.add(_row())
    cart.set_qty(9, 9, 5)
    cart.toggle_purchased(-1, 0)
    cart.remove(0, 99)

    assert cart.count() == 1


@pytest.mark.fast
def test_clear_purchased_keeps_the_rest(cart):
    cart.add(_row(tid=34))
    cart.add(_row(tid=35, zh="类银"))
    cart.toggle_purchased(0, 0)

    cart.clear_purchased()

    assert cart.count() == 1
    assert cart.groups()[0]["rows"][0]["typeId"] == 35


@pytest.mark.fast
def test_changed_fires_on_every_mutation(cart):
    seen = []
    cart.changed.connect(lambda: seen.append(1))

    cart.add(_row())
    cart.set_qty(0, 0, 3)
    cart.toggle_purchased(0, 0)
    cart.remove(0, 0)

    assert len(seen) == 4


# ── 持久化 ──────────────────────────────────────────────────


@pytest.mark.fast
def test_cart_survives_a_restart(cart):
    cart.add(_row())
    cart.set_qty(0, 0, 7)

    reopened = tcw.TradeCartController()

    assert reopened.count() == 1
    assert reopened.groups()[0]["rows"][0]["qty"] == 7


@pytest.mark.fast
@pytest.mark.parametrize(
    "payload",
    [
        "{ this is not json",
        "",
        "[]",
        '{"version": 99, "items": []}',
        '{"version": 1, "items": "not a list"}',
        '{"version": 1, "items": [{"no_type_id": 1}]}',
    ],
)
def test_broken_cart_file_starts_empty_without_raising(cart, payload):
    cart.path.write_text(payload, encoding="utf-8")

    reopened = tcw.TradeCartController()

    assert reopened.count() == 0
    assert reopened.groups() == []


@pytest.mark.fast
def test_saving_is_atomic(cart):
    """写盘走「先写临时文件再替换」，中途失败不留半截 JSON。"""
    cart.add(_row())

    assert cart.path.exists()
    assert not cart.path.with_suffix(".json.tmp").exists()
    assert json.loads(cart.path.read_text(encoding="utf-8"))["version"] == tcw._CART_VERSION


@pytest.mark.fast
def test_unknown_fields_from_an_older_cart_are_tolerated(cart):
    cart.path.write_text(
        json.dumps(
            {
                "version": 1,
                "items": [
                    {
                        "type_id": 34,
                        "zh": "三钛合金",
                        "from_hub": JITA,
                        "to_hub": AMARR,
                        "qty": 5,
                        "something_new": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    reopened = tcw.TradeCartController()

    assert reopened.count() == 1
    assert reopened.groups()[0]["rows"][0]["qty"] == 5
    assert reopened.totals()["count"] == 1


# ── 窗口 ────────────────────────────────────────────────────


@pytest.mark.ui
def test_cart_window_loads_without_warnings(cart, qapp):
    """购物车窗口（QML 根是 `Window`）能建起来，且不给 Qt 刷告警。

    与 `tests/qml_page_load.py` 那条护栏同源：QML 里 `HorizontalHeaderView` 的
    `textRole` 指错角色、绑定引用已删属性这类问题**只看得到告警、看不到报错**，
    界面只是不动或者空着。这条用例就是为它们守门的。
    """
    from pathlib import Path

    from PySide6.QtCore import QtMsgType, qInstallMessageHandler

    from tests.qml_click import spin

    cart.add(_row())
    caught: list[str] = []
    previous = qInstallMessageHandler(
        lambda mode, ctx, msg: (
            caught.append(f"[{Path(ctx.file).name}:{ctx.line}] {msg}")
            if mode in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg)
            and "qt-project.org" not in str(ctx.file)
            else None
        )
    )
    try:
        cart.show()
        spin(250)
        assert cart.is_visible()
    finally:
        cart.dispose()
        spin(60)
        qInstallMessageHandler(previous)

    assert not caught, "购物车窗口产生了 QML 告警：\n" + "\n".join(dict.fromkeys(caught))
