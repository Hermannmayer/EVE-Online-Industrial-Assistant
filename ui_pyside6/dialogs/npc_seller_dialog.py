"""蓝图 NPC 卖家查询对话框 — 从 ESI 拉该蓝图卖单，筛出 NPC 公司的直售单"""

import asyncio
from typing import cast

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

import ui_pyside6.theme as theme
from core.constants import TRADE_HUB_IDS
from core.logger import log
from services.npc_seller import (
    filter_npc_sell_orders,
    load_npc_corp_context,
    resolve_stations_by_ids,
)

ESI_BASE_URL = "https://esi.evetech.net/latest"


class NpcOrderWorker(QThread):
    """后台拉取指定蓝图的 ESI 卖单并按 NPC 公司过滤"""

    result = Signal(list, str)  # rows: [(公司, 地点, 价格, 剩余量)], error

    def __init__(self, region_id: int, blueprint_type_id: int, parent=None):
        super().__init__(parent)
        self._region_id = region_id
        self._type_id = blueprint_type_id

    def run(self):
        try:
            async def _fetch():
                from services.client import APIClient

                async with APIClient(timeout=20) as client:
                    url = (
                        f"{ESI_BASE_URL}/markets/{self._region_id}/orders/"
                        f"?order_type=sell&type_id={self._type_id}"
                    )
                    return await client.fetch_raw(url) or []

            orders = asyncio.run(_fetch())

            npc_ids, corp_names = load_npc_corp_context()
            sellers = filter_npc_sell_orders(orders, npc_ids)
            stations = resolve_stations_by_ids({o.get("location_id") for o in sellers})

            rows = []
            for o in sorted(sellers, key=lambda x: x.get("price", 0)):
                corp_id = o.get("corporation_id")
                station, system = stations.get(o.get("location_id"), ("", ""))
                loc = f"{station}（{system}）" if station else str(o.get("location_id") or "未知")
                rows.append(
                    (
                        corp_names.get(corp_id, str(corp_id)),
                        loc,
                        float(o.get("price") or 0),
                        int(o.get("volume_remain") or 0),
                    )
                )
            self.result.emit(rows, "")
        except Exception as ex:
            log.exception("拉取蓝图NPC卖家失败 type_id=%s", self._type_id)
            self.result.emit([], f"拉取失败：{ex}")


class NpcSellerDialog(QDialog):
    """蓝图 NPC 卖家 — 该蓝图在当前贸易中心的 NPC 公司直售单（BPO）"""

    _HUBS = [("吉他", "Jita"), ("艾玛", "Amarr"), ("多迪", "Dodixie"), ("伦斯", "Rens")]

    def __init__(self, blueprint_type_id: int, blueprint_name: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"蓝图 NPC 卖家 — {blueprint_name}")
        self.setMinimumSize(660, 420)
        self.resize(720, 480)
        self.setObjectName("npc_seller_dialog")
        self._type_id = blueprint_type_id
        self._worker: NpcOrderWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        header = QLabel(f"<b>{blueprint_name}</b>  (type_id: {blueprint_type_id})")
        header.setStyleSheet(f"color: {theme.PRIMARY}; font-size: 14px;")
        layout.addWidget(header)

        note = QLabel(
            "T1 蓝图原版(BPO) 由 NPC 公司在其空间站直售；此处列出该蓝图在当前贸易中心的 NPC 直售单。\n"
            "若列表为空：该蓝图可能非 NPC 直售（如 T2 蓝图），请到市场找玩家订单。"
        )
        note.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
        note.setWordWrap(True)
        layout.addWidget(note)

        # ── 区域选择 + 刷新 ──
        top = QHBoxLayout()
        top.addWidget(QLabel("贸易中心:"))
        self._hub_combo = QComboBox()
        for zh, en in self._HUBS:
            self._hub_combo.addItem(f"{zh} ({en})", TRADE_HUB_IDS[en])
        self._hub_combo.currentIndexChanged.connect(lambda *_: self._start_fetch())
        top.addWidget(self._hub_combo)
        self._refresh_btn = QPushButton("刷新")
        self._refresh_btn.clicked.connect(self._start_fetch)
        top.addWidget(self._refresh_btn)
        top.addStretch()
        layout.addLayout(top)

        # ── 状态/加载提示 ──
        self._status_label = QLabel("")
        self._status_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")
        layout.addWidget(self._status_label)

        # ── 卖单表 ──
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["NPC 公司", "空间站", "价格", "剩余量"])
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._table.setColumnWidth(0, 180)
        layout.addWidget(self._table, 1)

        # ── 关闭按钮 ──
        btn_bar = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btn_bar.rejected.connect(self.close)
        layout.addWidget(btn_bar)

        self._start_fetch()
        theme.add_theme_listener(self._on_theme_changed)

    # ── 抓取 ──

    def _start_fetch(self):
        if self._worker and self._worker.isRunning():
            return
        region_id = cast(int, self._hub_combo.currentData())
        self._refresh_btn.setEnabled(False)
        self._status_label.setText("正在从 ESI 获取卖单…")
        self._worker = NpcOrderWorker(region_id, self._type_id, self)
        self._worker.result.connect(self._on_result)
        self._worker.start()

    def _on_result(self, rows: list, error: str):
        self._refresh_btn.setEnabled(True)
        self._table.setRowCount(0)
        self._table.setRowCount(len(rows))
        for i, (corp, loc, price, vol) in enumerate(rows):
            for col, text in [
                (0, corp),
                (1, loc),
                (2, f"{price:,.2f}"),
                (3, f"{vol:,}"),
            ]:
                it = QTableWidgetItem(text)
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if col >= 2:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self._table.setItem(i, col, it)
        if error:
            self._status_label.setText(error)
        elif not rows:
            self._status_label.setText("该蓝图在当前贸易中心没有 NPC 直售单（可能为 T2/高级蓝图，请到市场找玩家订单）")
        else:
            self._status_label.setText(f"共 {len(rows)} 条 NPC 直售单")

    def _on_theme_changed(self):
        self._status_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 11px;")

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.requestInterruption()
        super().closeEvent(event)
