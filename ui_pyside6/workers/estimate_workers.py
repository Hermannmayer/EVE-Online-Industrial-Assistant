"""估价页面 — 剪贴板解析 Worker + 物品搜索"""

from PySide6.QtCore import QThread, Signal

from core.container import get_container


def _parse_clipboard(text: str) -> list[tuple[str, int, float]]:
    """解析 EVE 剪贴板格式，返回 [(物品名, 数量), ...]

    支持两种格式：
      Tab 分隔：物品名* \\t 数量 \\t 分组* \\t 体积 \\t 估价
      空格分隔：物品名*  数量  分组*  体积  估价
    物品名末尾的 * 会被自动去除。
    """
    results: list[tuple[str, int, float]] = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue

        # 判断分隔符：优先 Tab，其次多空格
        if "\t" in line:
            parts = [p.strip() for p in line.split("\t") if p.strip()]
        else:
            # 空格分隔 — 按 2 个以上空格拆分（避免拆开物品名内部的单空格）
            import re

            parts = [p.strip() for p in re.split(r" {2,}", line) if p.strip()]

        if not parts:
            continue

        # 物品名：去掉末尾的 *（EVE 游戏中表示特殊品质/状态）
        name = parts[0].rstrip("*")

        # 数量：取第一个能解析为整数的字段
        qty = 1
        for p in parts[1:]:
            # 去掉末尾 * 和单位后缀
            token = p.rstrip("*").replace(",", "").replace(" ", "")
            # 跳过明显是体积或价格的字段（含 m3、星币、ISK）
            if any(kw in p.lower() for kw in ("m3", "m³", "星币", "isk", "m³")):
                continue
            try:
                qty = int(token)
                break
            except ValueError:
                continue
        # 体积：从含 m3/m³ 的字段中提取数字
        clip_vol = 0.0
        for p in parts[1:]:
            if "m3" in p.lower() or "m³" in p:
                vol_token = p.rstrip("*").replace("m3", "").replace("m³", "").replace(",", "").strip()
                try:
                    clip_vol = float(vol_token)
                except ValueError:
                    pass
                break

        results.append((name, qty, clip_vol))
    return results


def _search_item_by_name(name: str) -> dict | None:
    """按中文/英文名搜索物品，返回 {type_id, zh_name, en_name, iconID, volume} 或 None"""
    from services.ui_data_service import search_item_by_name

    return search_item_by_name(name, db=get_container().db)


class ClipboardParseWorker(QThread):
    """后台解析剪贴板并查找物品/价格"""

    result_signal = Signal(list)  # list[dict] rows ready for table
    status_signal = Signal(str)  # status message

    def __init__(self, text: str, price_type: str, hub: str, parent=None):
        super().__init__(parent)
        self._text = text
        self._price_type = price_type  # "sell" / "buy" / "avg"
        self._hub = hub

    def run(self):
        parsed = _parse_clipboard(self._text)
        if not parsed:
            self.status_signal.emit("剪贴板没有识别到有效物品")
            return

        total = len(parsed)
        rows = []
        for i, (name, qty, clip_vol) in enumerate(parsed):
            self.status_signal.emit(f"正在查找... ({i + 1}/{total})")
            item = _search_item_by_name(name)
            if item is None:
                rows.append(
                    {
                        "type_id": None,
                        "name": name,
                        "qty": qty,
                        "sell_price": 0,
                        "buy_price": 0,
                        "unit_price": 0,
                        "sell_total": 0,
                        "buy_total": 0,
                        "volume": 0,
                        "_volume": clip_vol,
                        "bp_me": 0,
                        "bp_te": 0,
                    }
                )
                continue

            display_name = item["zh_name"] or item["en_name"] or name
            sell_p = get_container().pricing_service.get_price(item["type_id"], "sell", self._hub) or 0
            buy_p = get_container().pricing_service.get_price(item["type_id"], "buy", self._hub) or 0
            item_vol = item["volume"]

            rows.append(
                {
                    "type_id": item["type_id"],
                    "name": display_name,
                    "qty": qty,
                    "sell_price": sell_p,
                    "buy_price": buy_p,
                    "unit_price": 0,
                    "sell_total": 0,
                    "buy_total": 0,
                    "volume": 0,
                    "_volume": item_vol,
                    "bp_me": 0,
                    "bp_te": 0,
                }
            )

        self.result_signal.emit(rows)
        self.status_signal.emit(f"完成 — 共 {len(rows)} 项")
