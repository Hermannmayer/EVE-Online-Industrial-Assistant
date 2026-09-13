"""
仓库页面 — 蓝图导入后台线程
"""

from PySide6.QtCore import QThread, Signal

from core.container import get_container
from domain.blueprint_sync import group_key


def parse_blueprint_clipboard(raw: str, conn) -> tuple[list[dict], int, int]:
    """解析 EVE 蓝图剪贴板 → (蓝图行, 被过滤材料行数, 未识别蓝图行数)

    纯函数（依赖传入的 ref/bp 连接做名称→蓝图 ID 解析）。
    行格式（Tab 分隔，与游戏全选复制一致）:
        <蓝图名或产物名>\t<ME>\t<TE>\t<流程数>\t<原图/拷贝>
    """
    from services.ui_data_service import parse_blueprint_clipboard as _parse

    return _parse(raw, conn)


def build_blueprint_changes(
    before: dict[tuple, tuple[int, tuple[int, ...]]],
    after: dict[tuple, tuple[int, tuple[int, ...]]],
    names: dict[int, str],
) -> list[dict]:
    """对比导入前后蓝图库，返回变化行列表（对齐材料 compute_import_diff）。

    Args:
        before/after: {(bpid, is_bpo, me, te): (张数, 各张流程数排序元组)}
        names: 蓝图名映射 {bpid: 显示名}

    Returns:
        [{name, attr, qty_before, qty_after, qty_delta}]，仅含张数或流程数有变化的行。
    """
    result: list[dict] = []
    for key in sorted(set(before) | set(after)):
        b = before.get(key)
        a = after.get(key)
        if b == a:
            continue
        b_cnt, b_runs = b or (0, ())
        a_cnt, a_runs = a or (0, ())
        kind = "原图" if key[1] else "拷贝"
        attr = f"{kind}  ME{key[2]}  TE{key[3]}"
        values = sorted(set(a_runs or b_runs))
        if not key[1] and values:
            attr += f"  流程{values[0]}" if len(values) == 1 else f"  流程{values[0]}~{values[-1]}"
        result.append(
            {
                "name": names.get(key[0], f"ID:{key[0]}"),
                "attr": attr,
                "qty_before": b_cnt,
                "qty_after": a_cnt,
                "qty_delta": a_cnt - b_cnt,
            }
        )
    return result


def snapshot_blueprints(hangar_id: int) -> dict[tuple, tuple[int, tuple[int, ...]]]:
    """机库蓝图快照：组键 → (张数合计, 各张流程数排序元组)。

    张数用 `SUM(quantity)` 而非行数——下线产出会把同规格 BPC 合并进同一行
    （`quantity>1`），按行数计数会把「1 行 3 张」当成 1 张，全量同步随即
    误判为「库里少」而多插行。
    """
    from services import inventory_manager

    acc: dict[tuple, list[int]] = {}
    for bp in inventory_manager.get_blueprints(hangar_id):
        key = group_key(bp["blueprint_type_id"], bp["is_bpo"], bp["me_level"], bp["te_level"])
        qty = max(int(bp.get("quantity") or 1), 0)
        acc.setdefault(key, []).extend([int(bp.get("runs") or 0)] * qty)
    return {k: (len(v), tuple(sorted(v))) for k, v in acc.items()}


class _BlueprintImportWorker(QThread):
    """后台线程：解析剪贴板 → 比对库 → 产出 diff（增/删/更新）供预览确认"""

    progress = Signal(int, int, str)  # type: ignore[assignment]  # QThread 基类 Signal 无参数，子类覆盖 arity 属存根误报
    finished_signal = Signal(
        list
    )  # diff rows: [{blueprint_type_id, is_bpo, me, te, clip_runs, existing_rows, qty, existing_qty, name}]

    def __init__(self, raw: str, hangar_id: int, parent=None):
        super().__init__(parent)
        self._raw = raw
        self._hangar_id = hangar_id
        self.filtered_count = 0  # 剪贴板里被过滤的材料行数（供预览提示）
        self.unresolved_count = 0  # 剪贴板里结构完整但认不出蓝图的行数（供预览提示）

    def run(self):
        from services import inventory_manager
        from services.ui_data_service import parse_blueprint_clipboard_text

        # 1. 解析剪贴板（材料行按仓库类型过滤并计数）
        parsed, self.filtered_count, self.unresolved_count = parse_blueprint_clipboard_text(
            self._raw, db=get_container().db
        )

        # 2. 读取库中现有蓝图，按规格组聚合（保留行 id/备注，供原地更新而非删旧插新）
        existing: dict[tuple, list[dict]] = {}
        names: dict[int, str] = {}
        for bp in inventory_manager.get_blueprints(self._hangar_id):
            key = group_key(bp["blueprint_type_id"], bp["is_bpo"], bp["me_level"], bp["te_level"])
            existing.setdefault(key, []).append(
                {
                    "id": bp["id"],
                    "runs": bp["runs"],
                    "quantity": bp["quantity"],
                    "notes": bp["notes"],
                }
            )
            if bp["zh_name"]:
                names.setdefault(bp["blueprint_type_id"], bp["zh_name"])

        # 3. 剪贴板同样按规格组聚合，流程数展开成一张一项（张数是「每张一次」）
        clip: dict[tuple, list[int]] = {}
        for r in parsed:
            key = group_key(r["blueprint_type_id"], r["is_bpo"], r["me"], r["te"])
            clip.setdefault(key, []).extend([int(r["runs"])] * int(r["qty"]))
            names.setdefault(r["blueprint_type_id"], r["name"])

        diff: list[dict] = []
        for key in sorted(set(clip) | set(existing)):
            rows = existing.get(key, [])
            units = clip.get(key, [])
            diff.append(
                {
                    "blueprint_type_id": key[0],
                    "is_bpo": key[1],
                    "me": key[2],
                    "te": key[3],
                    "clip_runs": units,
                    "existing_rows": rows,
                    "qty": len(units),  # 剪贴板张数
                    "existing_qty": sum(max(int(r.get("quantity") or 1), 0) for r in rows),  # 库中张数
                    "name": names.get(key[0], ""),
                }
            )
        self.finished_signal.emit(diff)


def apply_blueprint_diff(diff_rows: list[dict], hangar_id: int, mode: str = "full") -> tuple[int, int, int]:
    """按勾选组应用增删，返回 (added, removed, blocked)。

    Args:
        diff_rows: [{blueprint_type_id, is_bpo, me, te, clip_runs, existing_rows, target_qty}]
        mode: "full" 全量同步（target_qty 为最终目标，增删按差额）
              "incremental" 增量累加（目标 = 现有张数 + 剪贴板张数，只增不减）
    """
    from services.ui_data_service import apply_blueprint_diff as _apply

    return _apply(diff_rows, hangar_id, mode, db=get_container().db)
