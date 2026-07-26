"""估价页面 — 精炼相关后台 Worker"""

from PySide6.QtCore import QThread, Signal

from core.container import get_container


class RefineWorker(QThread):
    """后台精炼计算 Worker — 继承 QThread 模式，参考 ClipboardParseWorker"""

    result_signal = Signal(dict)  # 精炼计算结果
    status_signal = Signal(str)  # 状态消息

    def __init__(
        self,
        items: list[dict],
        *,
        skills: dict | None = None,
        is_player_facility: bool = False,
        price_hub: str = "Jita",
        gas_rate: float = 0.0,
        residual: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._items = items
        self._skills = skills
        self._is_player_facility = is_player_facility
        self._price_hub = price_hub
        self._gas_rate = gas_rate
        self._residual = residual

    def run(self):
        total_input_value = 0.0
        total_output_value = 0.0
        all_output: list[dict] = []
        errors: list[str] = []

        total = len(self._items)
        for i, item in enumerate(self._items):
            type_id = item.get("type_id")
            qty = item.get("qty", 1) or 1
            name = item.get("name", f"ID:{type_id}")

            self.status_signal.emit(f"正在精炼 {name}... ({i + 1}/{total})")

            if not type_id:
                errors.append(f"第 {i + 1} 项缺少 type_id")
                continue

            try:
                result = get_container().refining_service.calc_value(
                    type_id,
                    quantity=qty,
                    skills=self._skills,
                    is_player_facility=self._is_player_facility,
                    price_hub=self._price_hub,
                )
            except Exception as e:
                errors.append(f"{name}: {e}")
                continue

            if not result["output"]:
                self.status_signal.emit(f"{name} 不可精炼，已跳过")
                continue

            total_input_value += result["input_value"]
            total_output_value += result["total_value"]
            all_output.append(
                {
                    "input_name": name,
                    "input_qty": qty,
                    "yield_rate": result["yield_rate"],
                    "output": result["output"],
                    "input_value": result["input_value"],
                    "output_value": result["total_value"],
                    "profit": result["profit"],
                    "margin_pct": result["margin_pct"],
                }
            )

        self.result_signal.emit(
            {
                "items": all_output,
                "total_input_value": round(total_input_value, 2),
                "total_output_value": round(total_output_value, 2),
                "total_profit": round(total_output_value - total_input_value, 2),
                "item_count": len(all_output),
                "errors": errors,
            }
        )
