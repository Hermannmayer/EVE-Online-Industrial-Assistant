"""
仓库页面 — 蓝图导入后台线程
"""

from PySide6.QtCore import QThread, Signal

from core.container import get_container


def parse_blueprint_clipboard(raw: str, conn) -> list[dict]:
    """解析 EVE 蓝图剪贴板 → [{blueprint_type_id, name, is_bpo, me, te, runs}]

    纯函数（依赖传入的 ref/bp 连接做名称→蓝图 ID 解析）。
    行格式（Tab 分隔，与游戏全选复制一致）:
        <蓝图名或产物名>\t<ME>\t<TE>\t<流程数>\t<原图/拷贝>
    """
    from services.ui_data_service import parse_blueprint_clipboard as _parse

    return _parse(raw, conn)


def build_blueprint_changes(
    before: dict[tuple, int],
    after: dict[tuple, int],
    names: dict[int, str],
) -> list[dict]:
    """对比导入前后蓝图库，返回变化行列表（对齐材料 compute_import_diff）。

    Args:
        before: 导入前 {(bpid, is_bpo, me, te, runs): 数量}
        after: 导入后 {(bpid, is_bpo, me, te, runs): 数量}
        names: 蓝图名映射 {bpid: 显示名}

    Returns:
        [{name, attr, qty_before, qty_after, qty_delta}]，仅含数量变化的行。
    """
    result: list[dict] = []
    all_keys = set(before) | set(after)
    for key in sorted(all_keys):
        b_qty = before.get(key, 0)
        a_qty = after.get(key, 0)
        if b_qty == a_qty:
            continue
        kind = "原图" if key[1] else "拷贝"
        result.append(
            {
                "name": names.get(key[0], f"ID:{key[0]}"),
                "attr": f"{kind}  ME{key[2]}  TE{key[3]}  流程{key[4]}",
                "qty_before": b_qty,
                "qty_after": a_qty,
                "qty_delta": a_qty - b_qty,
            }
        )
    return result


class _BlueprintImportWorker(QThread):
    """后台线程：解析剪贴板 → 比对库 → 产出 diff（增/删/不变）供预览确认"""

    progress = Signal(int, int, str)  # type: ignore[assignment]  # QThread 基类 Signal 无参数，子类覆盖 arity 属存根误报
    finished = Signal(  # type: ignore[assignment]  # QThread 基类 Signal 无参数，子类覆盖 arity 属存根误报
        list
    )  # diff rows: [{name, blueprint_type_id, is_bpo, me, te, runs, qty, existing_qty, row_id, delta, final}]

    def __init__(self, raw: str, hangar_id: int, parent=None):
        super().__init__(parent)
        self._raw = raw
        self._hangar_id = hangar_id

    def run(self):
        from services import inventory_manager
        from services.ui_data_service import parse_blueprint_clipboard_text

        # 1. 解析剪贴板
        parsed = parse_blueprint_clipboard_text(self._raw, db=get_container().db)

        # 2. 读取库中现有蓝图（保留 id 用于精确删除）
        existing: dict[tuple, list[int]] = {}  # (bpid, is_bpo, me, te, runs) → [row_ids]（同属性多张）
        for bp in inventory_manager.get_blueprints(self._hangar_id):
            key = (bp["blueprint_type_id"], bp["is_bpo"], bp["me_level"], bp["te_level"], bp["runs"])
            existing.setdefault(key, []).append(bp["id"])

        # 3. 比对变化（保留重复数量）
        from collections import Counter

        pasted = Counter(
            {(r["blueprint_type_id"], bool(r["is_bpo"]), r["me"], r["te"], r["runs"]): r["qty"] for r in parsed}
        )
        existing_cnt = Counter({k: len(v) for k, v in existing.items()})
        all_keys = set(pasted) | set(existing_cnt)
        names = {r["blueprint_type_id"]: r["name"] for r in parsed}

        diff: list[dict] = []
        for key in sorted(all_keys):
            p_cnt = pasted.get(key, 0)
            e_cnt = existing_cnt.get(key, 0)
            diff.append(
                {
                    "blueprint_type_id": key[0],
                    "is_bpo": key[1],
                    "me": key[2],
                    "te": key[3],
                    "runs": key[4],
                    "qty": p_cnt,  # 剪贴板数量
                    "existing_qty": e_cnt,  # 库中数量
                    "row_ids": existing.get(key, []),
                    "name": names.get(key[0], ""),
                }
            )
        self.finished.emit(diff)


def apply_blueprint_diff(diff_rows: list[dict], hangar_id: int, mode: str = "full") -> tuple[int, int]:
    """按勾选行应用增删，返回 (added, removed)。

    Args:
        diff_rows: [{blueprint_type_id, is_bpo, me, te, runs, target_qty, row_ids}]
        mode: "full" 全量同步（target_qty 为最终目标，增删按差额）
              "incremental" 增量累加（target_qty = 现有+剪贴板，只增不减）
    """
    from services.ui_data_service import apply_blueprint_diff as _apply

    return _apply(diff_rows, hangar_id, mode, db=get_container().db)
