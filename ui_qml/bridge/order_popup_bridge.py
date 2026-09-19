"""订单列表 → 表格行的纯函数（原「订单弹窗」的模块，弹窗本身已移除）。

**为什么这个模块还在**：物品查询页详情面板的「订单列表」直接吃 `order_rows()` 的输出，
它是订单行格式的**唯一**实现（`QueryDetailBridge._render_orders` 在用）。
原先它是「双击结果行弹出的订单弹窗」（右上角再带一张价格走势图）的配套函数 ——
弹窗删除后，这一份纯函数留下来继续服务下方面板。

弹窗为什么删：详情面板已经实时展示同一份买单/卖单各 5 条（同一个 `order_cache`、
同一个格式化函数），再弹一个窗口只是重复一遍。连带影响是 `PriceChartQmlDialog`
（原三级链的第三层「走势图」）**失去了入口** —— 桥与 QML 文件都原样留在仓库里，
只是暂时点不到。

`cell()` 取自 `summary_dialog`，因此本模块并非「零 Qt」（那一个函数要读主题色 token）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ui_qml.bridge.summary_dialog import cell

__all__ = ["order_rows"]


def order_rows(
    orders: Sequence[Mapping[str, Any]],
    token: str,
    station_names: Mapping[int, str] | None = None,
) -> list[dict]:
    """订单列表 → 单元格行（纯函数，便于单测）。

    买入染绿、卖出染红（对齐原 `QListWidgetItem.setForeground`）；
    空间站列显示**站名**（如 `Jita IV - Moon 4 - Caldari Navy Assembly Plant`）。
    解析不到时退回 `location_id` —— 站名解析器只会缓存成功的条目，所以「缓存里有值」
    就等于「解析成功」，不必再区分。原先站名后面总跟一个 ` [id]`，与站名重复且挤占列宽，
    已去掉。
    """
    names = station_names or {}
    rows: list[dict] = []
    for i, order in enumerate(orders):
        loc_id = int(order["location_id"])
        station = str(names.get(loc_id) or "")
        rows.append(
            {
                "cells": [
                    cell(f"#{i + 1}", token),
                    cell(f"{order['price']:,.2f}", token),
                    cell(f"{order['volume_remain']:,}", token),
                    cell(station or str(loc_id), token),
                ]
            }
        )
    return rows
