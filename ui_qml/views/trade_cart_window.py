"""贸易购物车 —— **控制器**（渲染交给 `TradeCartWindow.qml`）。

非模态独立工具窗，可置顶悬浮在游戏之上。数据来源只有一个：贸易页排行表每行的
「加入购物车」。按**方向**（起点中心/起点价、终点中心/终点价）分组 ——
同一件物品在两个方向上各成一行，互不干扰。

持久化在 `data/trade_cart.json`（`core.paths.trade_cart_file`），与
`search_history.json` / `window_geometry.json` 同一类「轻量本地状态」，
**不落 user.db**：它是候选清单，不是用户资产。写盘只在主线程做，先写临时文件
再 `os.replace` 原子替换，中途崩不会留下半截 JSON。

窗口属主是 `ShellWindow`（`shell.trade_cart()` 懒建单例）—— 贸易页与购物车窗口
必须拿到**同一个**实例，否则两边各记一份、状态栏数字对不上。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickWindow

from core.logger import log
from core.paths import trade_cart_file
from ui_qml.icon_cache import icon_url
from ui_qml.pin_utils import apply_window_pin, reassert_pin

__all__ = ["MODE_LABELS", "TradeCartController", "group_key_of", "group_label_of"]

_QML_FILE = "pages/TradeCartWindow.qml"
_CART_VERSION = 1
_PIN_KEY = "trade_cart_pin"

#: 价格类型 → 界面文案（与贸易页的两个下拉一致）
MODE_LABELS = {"buy": "买单", "sell": "卖单"}


def _read_text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _read_float(value: Any) -> float:
    return float(value) if isinstance(value, int | float) else 0.0


def group_key_of(item: dict) -> str:
    """方向键 —— 同键的行归到一个分组。"""
    return "|".join(_read_text(item.get(k)) for k in ("from_hub", "from_mode", "to_hub", "to_mode"))


def group_label_of(item: dict) -> str:
    """分组标题，如 `Jita(卖单) → Amarr(买单)`。"""
    return (
        f"{_read_text(item.get('from_hub'))}({MODE_LABELS.get(_read_text(item.get('from_mode')), '')})"
        f" → {_read_text(item.get('to_hub'))}({MODE_LABELS.get(_read_text(item.get('to_mode')), '')})"
    )


class TradeCartController(QObject):
    """购物车数据 + 窗口宿主。"""

    changed = Signal()  # 条目/数量/购买态变了（页面状态栏与窗口都听它）

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._window: QQuickWindow | None = None
        self._engine: QQmlEngine | None = None
        self._component: QQmlComponent | None = None
        self._bridge: Any = None
        self._items: list[dict] = []
        self._groups: list[dict] = []
        self._pinned = False
        self._hint = ""
        self._load()
        self._rebuild()
        self._restore_pin()

    # ── 读 ──────────────────────────────────────────────────

    def groups(self) -> list[dict]:
        """分组后的行（桥直接下发给 QML）。"""
        return [dict(g) for g in self._groups]

    def totals(self) -> dict:
        """整车汇总：条目数 / 金额 / 体积 / 预计利润（页面状态栏读它）。"""
        return self._summary(self._items)

    def count(self) -> int:
        return len(self._items)

    @staticmethod
    def _summary(items: list[dict]) -> dict:
        amount = sum(_read_float(i.get("price_a")) * int(i.get("qty") or 0) for i in items)
        volume = sum(_read_float(i.get("volume")) * int(i.get("qty") or 0) for i in items)
        profit = sum(_read_float(i.get("spread")) * int(i.get("qty") or 0) for i in items)
        return {
            "count": len(items),
            "amount": amount,
            "volume": volume,
            "profit": profit,
        }

    # ── 写 ──────────────────────────────────────────────────

    def add(self, row: dict) -> str:
        """从排行表加一件。

        同一个方向上的同一件物品**累加数量**，不重复建行 —— 排行表是「扫一遍点几个」
        的用法，重复点同一行应当理解为「多买一点」，而不是悄悄多出一行。
        """
        from_hub = _read_text(row.get("from_hub"))
        to_hub = _read_text(row.get("to_hub"))
        from_mode = _read_text(row.get("from_mode")) or "sell"
        to_mode = _read_text(row.get("to_mode")) or "buy"
        type_id = int(row.get("id") or 0)
        if not type_id or not from_hub or not to_hub:
            return "这一行没有可用的价格数据，未加入"

        for it in self._items:
            if (
                int(it.get("type_id") or 0) == type_id
                and it.get("from_hub") == from_hub
                and it.get("to_hub") == to_hub
                and it.get("from_mode") == from_mode
                and it.get("to_mode") == to_mode
            ):
                it["qty"] = int(it.get("qty") or 0) + 1
                it["price_a"] = _read_float(row.get("pa"))
                it["price_b"] = _read_float(row.get("pb"))
                it["spread"] = _read_float(row.get("spread"))
                self._commit()
                return f"已加量到 {it['qty']}：{it.get('zh') or it.get('en') or type_id}"

        name = _read_text(row.get("z")) or _read_text(row.get("e")) or str(type_id)
        self._items.append(
            {
                "type_id": type_id,
                "zh": _read_text(row.get("z")),
                "en": _read_text(row.get("e")),
                "from_hub": from_hub,
                "from_mode": from_mode,
                "to_hub": to_hub,
                "to_mode": to_mode,
                "price_a": _read_float(row.get("pa")),
                "price_b": _read_float(row.get("pb")),
                "spread": _read_float(row.get("spread")),
                "volume": _read_float(row.get("v")),
                "qty": 1,
                "purchased": False,
                "added_at": datetime.now().isoformat(timespec="seconds"),
            }
        )
        self._commit()
        return f"已加入购物车：{name}"

    def set_qty(self, group_index: int, row_index: int, qty: int) -> None:
        item = self._locate(group_index, row_index)
        if item is None:
            return
        item["qty"] = max(1, int(qty))
        self._commit()

    def toggle_purchased(self, group_index: int, row_index: int) -> None:
        item = self._locate(group_index, row_index)
        if item is None:
            return
        item["purchased"] = not bool(item.get("purchased"))
        self._commit()

    def remove(self, group_index: int, row_index: int) -> None:
        item = self._locate(group_index, row_index)
        if item is None:
            return
        name = item.get("zh") or item.get("en") or item.get("type_id")
        self._items.remove(item)
        self._commit()
        self._hint = f"已移除 {name}"

    def clear_purchased(self) -> None:
        before = len(self._items)
        self._items = [i for i in self._items if not i.get("purchased")]
        if before == len(self._items):
            return
        self._hint = f"已清理 {before - len(self._items)} 项已购买"
        self._commit()

    def copy_name(self, group_index: int, row_index: int) -> None:
        item = self._locate(group_index, row_index)
        if item is None:
            return
        text = item.get("zh") or item.get("en") or str(item.get("type_id"))
        QGuiApplication.clipboard().setText(str(text))
        self._hint = f"已复制: {text}"
        self.changed.emit()

    # ── 内部 ────────────────────────────────────────────────

    def _locate(self, group_index: int, row_index: int) -> dict | None:
        """按「分组下标 + 组内行下标」取条目 —— 下标由 QML 传回，越界一律当没点到。"""
        if not 0 <= group_index < len(self._groups):
            return None
        rows = self._groups[group_index].get("rows") or []
        if not 0 <= row_index < len(rows):
            return None
        item = rows[row_index].get("item")
        return item if isinstance(item, dict) else None

    def _commit(self, force: bool = True) -> None:
        self._rebuild()
        self._save()
        if force:
            self.changed.emit()

    def _rebuild(self) -> None:
        """按方向分组重建 QML 要的行。组顺序 = 首次出现的顺序（稳定的）。"""
        buckets: dict[str, list[dict]] = {}
        for it in self._items:
            buckets.setdefault(group_key_of(it), []).append(it)

        groups: list[dict] = []
        for key, items in buckets.items():
            rows = []
            for it in items:
                qty = int(it.get("qty") or 0)
                price_a = _read_float(it.get("price_a"))
                rows.append(
                    {
                        "item": it,
                        "typeId": int(it.get("type_id") or 0),
                        "name": it.get("zh") or it.get("en") or str(it.get("type_id") or ""),
                        "en": it.get("en") or "",
                        "iconUrl": icon_url(it.get("type_id")),
                        "spreadText": f"{_read_float(it.get('spread')):,.2f}",
                        "qty": qty,
                        "amountText": f"{price_a * qty:,.2f}",
                        "purchased": bool(it.get("purchased")),
                    }
                )
            s = self._summary(items)
            groups.append(
                {
                    "key": key,
                    "label": group_label_of(items[0]),
                    "rows": rows,
                    "summary": (
                        f"{s['count']} 项 · 金额 {s['amount']:,.0f} · "
                        f"体积 {s['volume']:,.2f} m³ · 预计利润 {s['profit']:,.0f}"
                    ),
                }
            )
        self._groups = groups

    # ── 持久化 ──────────────────────────────────────────────

    def _load(self) -> None:
        path = trade_cart_file()
        try:
            import json
            import os

            if not os.path.exists(path):
                return
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or data.get("version") != _CART_VERSION:
                log.warning(
                    "购物车文件版本不符（%r），按空车启动", data.get("version") if isinstance(data, dict) else data
                )
                return
            items = data.get("items")
            if isinstance(items, list):
                self._items = [i for i in items if isinstance(i, dict) and i.get("type_id")]
        except Exception:
            # 文件损坏 / 权限 / 半截 JSON：当作空车，别让开窗失败
            log.exception("读取购物车失败: %s", path)

    def _save(self) -> None:
        import json
        import os

        path = trade_cart_file()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = f"{path}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(
                    {"version": _CART_VERSION, "items": self._items},
                    f,
                    ensure_ascii=False,
                    indent=1,
                )
            os.replace(tmp, path)
        except Exception:
            log.exception("写入购物车失败: %s", path)

    # ── 窗口 ────────────────────────────────────────────────

    def show(self) -> None:
        if self._window is None:
            self._build_window()
        if self._window is not None:
            self._window.show()
            self._window.raise_()
            self._window.requestActivate()
            reassert_pin(self._window, self._pinned)

    def _build_window(self) -> None:
        """实例化 `TradeCartWindow.qml`（根元素是 `Window`）。

        根是 `Window` 时 `QQuickView` / `QQuickWidget` 都用不了（两者根必须是 `Item`），
        只能走 `QQmlEngine` + `QQmlComponent`，与 `procurement_tab` / `splash_window` 同法。
        """
        from ui_qml.bridge import CONTEXT_NAME, theme_singleton
        from ui_qml.bridge.trade_cart_bridge import TradeCartBridge
        from ui_qml.host import QML_ROOT

        bridge = TradeCartBridge(self, self)
        engine = QQmlEngine()
        self._engine = engine
        ctx = engine.rootContext()
        ctx.setContextProperty(CONTEXT_NAME, theme_singleton())
        ctx.setContextProperty("bridge", bridge)
        path = QML_ROOT / _QML_FILE
        component = QQmlComponent(engine)
        component.setData(path.read_bytes(), QUrl.fromLocalFile(str(path)))
        if component.isError():
            raise RuntimeError("; ".join(e.toString() for e in component.errors()))
        self._component = component
        window = component.create(ctx)
        if not isinstance(window, QQuickWindow):
            raise RuntimeError(f"{_QML_FILE} 的根元素不是 Window：{window!r}")
        # 所有权：引擎挂到窗口名下（与 `procurement_tab._build_window` 同一条父子链）
        component.setParent(engine)
        engine.setParent(window)
        self._window = window
        self._bridge = bridge

    def is_visible(self) -> bool:
        return self._window is not None and bool(self._window.isVisible())

    def hint(self) -> str:
        return self._hint

    def dispose(self) -> None:
        """退出时拆掉 QML 场景（不是关窗）。

        只 `close()` 不够：关窗只是隐藏，QML 树与 `QQmlEngine` 都还活着；等解释器
        收尾把 `Theme` 单例回收后，场景里那些 `Theme.xxx` 绑定会对着 null 求值刷告警。
        顺序与 `_teardown_qml` 同一条：先删根对象（连同场景），再让引擎/组件沿父子链走。
        """
        window = self._window
        if window is None:
            return
        self._window = None
        self._component = None
        self._engine = None
        self._bridge = None
        window.close()
        # 不能靠丢引用析构：window 是 engine 的 QObject 父、engine 又持有根对象（就是
        # window）—— 跨 Python/C++ 的引用环，丢引用后两边都活着。
        window.deleteLater()

    # ── 置顶 ────────────────────────────────────────────────

    def pinned(self) -> bool:
        return bool(self._pinned)

    def set_pinned(self, checked: bool) -> None:
        self._pinned = bool(checked)
        if self._window is not None:
            apply_window_pin(self._window, self._pinned)
        try:
            from services.user_settings import save_settings

            save_settings({_PIN_KEY: self._pinned})
        except Exception:
            log.warning("保存购物车置顶偏好失败", exc_info=True)

    def _restore_pin(self) -> None:
        try:
            from services.user_settings import load_settings

            if load_settings().get(_PIN_KEY):
                self._pinned = True
                if self._window is not None:
                    apply_window_pin(self._window, True)
        except Exception:
            log.warning("读取购物车置顶偏好失败", exc_info=True)

    def window_visibility_changed(self, visible: bool) -> None:
        """QML 的 `onVisibleChanged` 转发过来（窗口显示后重申一次置顶）。"""
        if visible:
            reassert_pin(self._window, self._pinned)
