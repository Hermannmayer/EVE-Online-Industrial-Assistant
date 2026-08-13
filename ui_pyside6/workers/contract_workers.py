"""合同市场 — 后台 Worker 线程"""

from PySide6.QtCore import QThread, Signal

from core.container import get_container


class ContractFetchWorker(QThread):
    """后台拉取公开合同数据"""

    finished_signal = Signal(bool, str)  # success, message

    def __init__(self, regions: list[str] | None = None, parent=None):
        super().__init__(parent)
        self._regions = regions

    def run(self):
        try:
            from services.workers.getcontracts import run_contract_update

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
            with get_container().db.connect("mkt") as conn:
                c = conn.cursor()
                query = "SELECT * FROM public_contracts WHERE region_id = ?"
                params: list = [self._region_id]
                if self._contract_type != "all":
                    query += " AND type = ?"
                    params.append(self._contract_type)
                query += " ORDER BY date_issued DESC LIMIT 2000"
                c.execute(query, params)
                rows = c.fetchall()
                result = [dict(r) for r in rows]
                self.finished_signal.emit(result)
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
            with get_container().db.connect("mkt", "ref") as conn:
                c = conn.cursor()
                c.execute(
                    """
                    SELECT ci.*, r.zh_name, r.en_name
                    FROM contract_items ci
                    LEFT JOIN ref.item r ON ci.type_id = r.type_id
                    WHERE ci.contract_id = ?
                    ORDER BY ci.record_id
                """,
                    (self._contract_id,),
                )
                rows = c.fetchall()
                result = [dict(r) for r in rows]
                self.finished_signal.emit(result)
        except Exception:
            self.finished_signal.emit([])
