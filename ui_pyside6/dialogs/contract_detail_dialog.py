"""合同详情弹窗 — 显示合同信息 + 物品列表"""

from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QLabel,
    QTableView,
    QVBoxLayout,
)

import ui_pyside6.theme as theme
from ui_pyside6.models.contract_models import (
    _ITEM_COLUMNS,
    CONTRACT_STATUS_CN,
    CONTRACT_TYPE_CN,
    ContractItemTableModel,
)
from ui_pyside6.workers.contract_workers import ContractItemsLoadWorker


class ContractDetailDialog(QDialog):
    """合同详情弹窗 — 显示合同信息 + 物品列表"""

    def __init__(self, contract: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"合同详情 — #{contract.get('contract_id', '')}")
        self.setMinimumSize(750, 500)
        self.setObjectName("contract_detail_dialog")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # 合同基本信息
        info = contract
        title = info.get("title", "") or "无标题"
        type_cn = CONTRACT_TYPE_CN.get(info.get("type", ""), info.get("type", ""))
        status_cn = CONTRACT_STATUS_CN.get(info.get("status", ""), info.get("status", ""))

        header_text = f"#{info.get('contract_id', '')}  {title}"
        self._header = QLabel(header_text)
        self._header.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {theme.PRIMARY};")
        layout.addWidget(self._header)

        detail_text = (
            f"类型: {type_cn}  |  状态: {status_cn}  |  "
            f"价格: {info.get('price', 0):,.2f} ISK  |  "
            f"抵押: {info.get('collateral', 0):,.2f} ISK  |  "
            f"体积: {info.get('volume', 0):,.1f} m³  |  "
            f"运输天数: {info.get('days_completed', 0)}"
        )
        self._detail = QLabel(detail_text)
        self._detail.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12px;")
        layout.addWidget(self._detail)

        dates_text = (
            f"签发: {info.get('date_issued', '—')}  |  "
            f"过期: {info.get('date_expired', '—')}  |  "
            f"起始站: {info.get('start_location_id', '—')}  |  "
            f"终点站: {info.get('end_location_id', '—')}  |  "
            f"企业合同: {'是' if info.get('for_corporation') else '否'}"
        )
        self._dates = QLabel(dates_text)
        self._dates.setStyleSheet(f"color: {theme.TEXT_SECONDARY}; font-size: 12px;")
        layout.addWidget(self._dates)

        # 物品列表
        items_label = QLabel("合同物品:")
        items_label.setStyleSheet(f"font-weight: bold; color: {theme.TEXT_PRIMARY};")
        layout.addWidget(items_label)

        self._item_model = ContractItemTableModel()
        self._items_table = QTableView()
        self._items_table.setModel(self._item_model)
        self._items_table.setAlternatingRowColors(False)
        self._items_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._items_table.setSortingEnabled(True)
        self._items_table.verticalHeader().setVisible(False)
        header = self._items_table.horizontalHeader()
        header.setStretchLastSection(True)
        for i, (_, w) in enumerate(_ITEM_COLUMNS):
            header.resizeSection(i, w)
        layout.addWidget(self._items_table)

        self._items_worker: ContractItemsLoadWorker | None = None
        self._load_items(info.get("contract_id", 0))

    def _load_items(self, contract_id: int):
        self._items_worker = ContractItemsLoadWorker(contract_id, self)
        self._items_worker.finished_signal.connect(self._on_items_loaded)
        self._items_worker.start()

    def _on_items_loaded(self, items: list[dict]):
        self._item_model.set_rows(items)
