"""蓝图批量加入规划时的派生指标计算线程。

原先在 `ui_pyside6/views/inventory/blueprint_tab.py`。
"""

from PySide6.QtCore import QThread, Signal


class _BulkPlanMetricsWorker(QThread):
    """后台批量计算各组合并后的派生指标（评分较重，避免卡死 UI）。"""

    done = Signal(list)

    def __init__(self, group_items: list[list[dict]], product_name: str, char_name: str, parent=None):
        super().__init__(parent)
        self._group_items = group_items
        self._product_name = product_name
        self._char_name = char_name

    def run(self):
        from services import inventory_manager, plan_service, user_settings

        # 价格来源设置（材料/成品 hub）替代硬编码 "Jita"，与单条添加流程口径一致
        settings = user_settings.load_settings()
        price_settings = settings.get("price_settings") or {}
        mat_hub = price_settings.get("mat_hub", "Jita")
        sell_hub = price_settings.get("prod_hub", "Jita")
        mat_mult = float(price_settings.get("mat_mult") or 1.0)
        prod_mult = float(price_settings.get("prod_mult") or 1.0)
        # 产出机库默认（机库设置里配置）→ 写入计划，下线时自动入库
        deposit_hangar_id = settings.get("default_deposit_hangar_id")
        # 从默认材料机库带出星系，写入计划（避免空星系 → 回退吉他 SCI）
        mat_hangar_id, solar_system_id = inventory_manager.get_default_mat_hangar_and_system()
        hangar_name = inventory_manager.get_hangar_name(mat_hangar_id)

        rows = []
        for bps in self._group_items:
            parallels = len(bps)
            d = {
                "parallels": parallels,
                "me": bps[0].get("me_level") or 0,
                "te": bps[0].get("te_level") or 0,
                "char": self._char_name,
                "fac": hangar_name,
                "runs": bps[0].get("runs") or 1,
            }
            metrics = plan_service.calculate_plan_metrics(
                {
                    "product_type_id": bps[0]["product_type_id"],
                    "product_name": self._product_name,
                    "runs": d["runs"],
                    "parallels": parallels,
                    "me_level": d["me"],
                    "te_level": d["te"],
                    "mat_hub": mat_hub,
                    "sell_hub": sell_hub,
                    "char_name": d["char"],
                    "facility": hangar_name,
                    "mat_hangar_id": mat_hangar_id,
                    "solar_system_id": solar_system_id,
                },
                char_name=self._char_name,
                mat_mult=mat_mult,
                prod_mult=prod_mult,
            )
            rows.append(
                {
                    "type_id": bps[0]["product_type_id"],
                    "product_name": self._product_name,
                    "data": d,
                    "metrics": metrics,
                    "bp_ids": [b["id"] for b in bps],
                    "mat_hangar_id": mat_hangar_id,
                    "solar_system_id": solar_system_id,
                    "deposit_hangar_id": deposit_hangar_id,
                    "mat_hub": mat_hub,
                    "sell_hub": sell_hub,
                }
            )
        self.done.emit(rows)
