"""合同市场 — 后台 Worker 线程"""

from PySide6.QtCore import QThread, Signal

from services.contract_service import load_contract_items, load_contracts


class ContractFetchWorker(QThread):
    """后台拉取公开合同数据"""

    finished_signal = Signal(bool, str)  # success, message

    def __init__(self, regions: list[str] | None = None, parent=None):
        super().__init__(parent)
        self._regions = regions

    def run(self):
        try:
            from services.importers.getcontracts import run_contract_update

            run_contract_update(self._regions)
            self.finished_signal.emit(True, "合同数据更新完成")
        except Exception as ex:
            self.finished_signal.emit(False, str(ex))


class ContractLoadWorker(QThread):
    """后台从数据库加载合同列表"""

    finished_signal = Signal(list)  # list of contract dicts

    def __init__(self, region_id: int, contract_type: str, parent=None):
        super().__init__(parent)
        self._region_id = region_id
        self._contract_type = contract_type

    def run(self):
        try:
            self.finished_signal.emit(load_contracts(self._region_id, self._contract_type))
        except Exception:
            self.finished_signal.emit([])


class ContractItemsLoadWorker(QThread):
    """后台从数据库加载合同物品"""

    finished_signal = Signal(list)  # list of item dicts

    def __init__(self, contract_id: int, parent=None):
        super().__init__(parent)
        self._contract_id = contract_id

    def run(self):
        try:
            self.finished_signal.emit(load_contract_items(self._contract_id))
        except Exception:
            self.finished_signal.emit([])
