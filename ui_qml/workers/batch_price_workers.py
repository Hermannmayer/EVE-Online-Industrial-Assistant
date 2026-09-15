"""批量查价的线程与搜索助手（原先在 `ui_pyside6/views/batch_price_dialog.py`）。"""

from PySide6.QtCore import QThread, Signal

from core.container import get_container


class BatchPriceWorker(QThread):
    """批量查价工作线程"""

    finished_signal = Signal(list)  # list[dict]
    progress_signal = Signal(int, int)  # current, total
    error_signal = Signal(str)

    def __init__(self, items: list[dict], parent=None):
        super().__init__(parent)
        self._items = items
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        results = []
        total = len(self._items)
        for i, item in enumerate(self._items):
            if self._cancelled:
                return
            try:
                result = self._query_one(item)
                results.append(result)
            except Exception as e:
                results.append(
                    {
                        "name": item.get("name", str(item.get("type_id", "?"))),
                        "not_found": True,
                        "error": str(e),
                    }
                )
            self.progress_signal.emit(i + 1, total)
        self.finished_signal.emit(results)

    def _query_one(self, item: dict) -> dict:
        """查询单个物品价格"""
        type_id = item["type_id"]
        name = item.get("name", str(type_id))

        row = get_container().market_repo.get_latest_price(type_id)

        if not row:
            return {"type_id": type_id, "name": name, "not_found": True}

        buy_p, sell_p, buy_v, sell_v = row

        # 格式价格
        buy_str = "—"
        buy_val = 0.0
        if buy_p is not None and buy_v > 0:
            buy_str = f"{buy_p:,.2f} ({buy_v:,})"
            buy_val = buy_p
        elif buy_p is not None:
            buy_str = f"{buy_p:,.2f}"
            buy_val = buy_p

        sell_str = "—"
        sell_val = 0.0
        if sell_p is not None and sell_v > 0:
            sell_str = f"{sell_p:,.2f} ({sell_v:,})"
            sell_val = sell_p
        elif sell_p is not None:
            sell_str = f"{sell_p:,.2f}"
            sell_val = sell_p

        # 均价
        avg_val = 0.0
        avg_str = "—"
        if buy_val > 0 and sell_val > 0:
            avg_val = (buy_val + sell_val) / 2
            avg_str = f"{avg_val:,.2f}"
        elif buy_val > 0:
            avg_val = buy_val
            avg_str = f"{buy_val:,.2f}"
        elif sell_val > 0:
            avg_val = sell_val
            avg_str = f"{sell_val:,.2f}"

        # 价差
        spread_val = sell_val - buy_val if buy_val > 0 and sell_val > 0 else 0.0
        spread_str = f"{spread_val:+,.2f}" if buy_val > 0 and sell_val > 0 else "—"

        # 成交量
        vol_val = buy_v + sell_v
        vol_str = f"{vol_val:,}" if vol_val > 0 else "—"

        return {
            "type_id": type_id,
            "name": name,
            "buy_str": buy_str,
            "sell_str": sell_str,
            "avg_str": avg_str,
            "spread_str": spread_str,
            "vol_str": vol_str,
            "buy_val": buy_val,
            "sell_val": sell_val,
            "avg_val": avg_val,
            "spread_val": spread_val,
            "vol_val": vol_val,
            "not_found": False,
        }


# ── 数据库搜索 ──


def _search_items(queries: list[str]) -> list[dict]:
    """批量搜索物品，返回 [{type_id, name, raw_query}]"""
    results = []
    seen_type_ids = set()
    repo = get_container().item_repo
    for q in queries:
        q = q.strip()
        if not q:
            continue
        if q.isdigit():
            item = repo.get_by_id(int(q))
        else:
            matches = repo.search_by_name(q, limit=1)
            item = matches[0] if matches else None
        if item:
            tid = item["type_id"]
            if tid not in seen_type_ids:
                seen_type_ids.add(tid)
                name = item["zh_name"] or item["en_name"] or str(tid)
                results.append({"type_id": tid, "name": name, "raw_query": q})
        else:
            # 未找到 — 保留占位
            results.append({"type_id": 0, "name": q, "raw_query": q, "not_found": True})
    return results
