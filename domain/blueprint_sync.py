"""蓝图库存同步的纯逻辑 —— 剪贴板属性归一 与 同规格组内的行级配对。

剪贴板导入原以 `(类型, is_bpo, ME, TE, 流程数)` 为匹配键，于是流程数一变
（BPC 被消耗后 runs 变小、或原图的 -1 被归一）就被判成「另一张图」，
走成「删旧行 + 插新行」：蓝图行 `id`、`notes`，以及 `delete_blueprint`
连带清理的计划绑定全部丢失。

这里把匹配收敛到 `(类型, is_bpo, ME, TE)`，流程数降级为行内属性：同一
规格组内先按「流程数相同」配对（保证重复粘贴是不动点），再补足容量，
最后把用不上的行删除、放不下的张数新增。id / notes / 计划绑定因此得以保留。

无 DB / Qt 依赖，供 services 层编排与 UI 层预览共用。
"""

from __future__ import annotations

from collections import Counter

# 剪贴板第 5 列的「原图」判词。只认中文「原图/原本」会在英文客户端下把原图
# 误判成拷贝（进而被全量同步当作多余行删除），故一并接受英文 Original。
_BPO_TEXTS = ("原图", "原本", "original")


def group_key(blueprint_type_id: int, is_bpo: bool, me_level: int, te_level: int) -> tuple:
    """同规格组键：类型 + 原图/拷贝 + ME + TE。

    **不含流程数**——流程数是行内属性（会被消耗、会被归一），把它并进键就会
    让「同一张蓝图改了流程数」变成「另一张蓝图」，进而删旧插新。
    """
    return (int(blueprint_type_id), bool(is_bpo), int(me_level or 0), int(te_level or 0))


def normalize_clipboard_attr(is_bpo_text: str, runs: int) -> tuple[bool, int]:
    """剪贴板原始属性 → `(is_bpo, runs)`。

    游戏里原图的「流程数」列就是 -1，所以 `runs < 0` 同样判为原图——这是
    英文客户端判词失配时的兜底，也是把 `-1` 哨兵彻底退役的归一入口。

    原图一律归 `runs = 0`（游戏给 -1，人工也可能填别的值）：让
    「`is_bpo=1` ⇒ `runs=0`」成为迁移与解析两侧共用的全局不变量，
    「粘贴 → 落库」才是不动点。
    """
    text = (is_bpo_text or "").strip().lower()
    is_bpo = any(t in text for t in _BPO_TEXTS) or int(runs) < 0
    return is_bpo, 0 if is_bpo else max(int(runs), 0)


def plan_group_sync(existing_rows: list[dict], clip_units: list[int]) -> list[dict]:
    """同一 `(类型, is_bpo, ME, TE)` 组内的行级同步操作。

    existing_rows: 该组现有行 `[{id, runs, quantity, notes}]`（quantity = 该行代表的张数）
    clip_units:    同步后该组应有的「每张的流程数」列表，长度即目标张数。
                   全量同步 = 剪贴板张数（可被用户改写）；增量 = 现有张数 + 剪贴板张数。

    返回确定性操作集：
      {"op": "update", "id", "runs", "quantity"}  — 原地改（保留 id/notes/绑定）
      {"op": "delete", "id"}                       — 该行容量不再需要
      {"op": "insert", "runs"}                     — 多出的张数

    配对顺序：有备注的行优先保留，其次 id 小者优先（删则从无备注、id 大者删起）；
    容量分配先取「流程数与现有行相同」的份额，使流程数未变时为**零操作**；
    同一行被分到多个不同流程数时（`quantity > 1` 撞上异构剪贴板），保 id 给
    张数最多的那个流程数，其余份额转为新增。
    """
    rows = sorted(
        existing_rows,
        key=lambda r: (not str(r.get("notes") or "").strip(), int(r.get("id") or 0)),
    )
    pool = sorted(int(u) for u in clip_units)
    caps = [max(int(r.get("quantity") or 1), 0) for r in rows]

    assigned: list[list[int]] = [[] for _ in rows]
    # 第一轮：流程数相同的份额优先（幂等路径 —— 重复粘贴不产生任何写操作）
    for i, row in enumerate(rows):
        want = int(row.get("runs") or 0)
        while len(assigned[i]) < caps[i] and want in pool:
            pool.remove(want)
            assigned[i].append(want)
    # 第二轮：仍有余量的行按顺序领走剩余份额（行容量用尽的行拿不到）
    for i in range(len(rows)):
        while len(assigned[i]) < caps[i] and pool:
            assigned[i].append(pool.pop(0))

    ops: list[dict] = []
    for i, row in enumerate(rows):
        got = assigned[i]
        row_id = int(row["id"])
        if not got:
            ops.append({"op": "delete", "id": row_id})
            continue
        counts = Counter(got)
        if len(counts) == 1:
            new_runs, new_qty = got[0], len(got)
        else:
            # 并列时取流程数小者，保证结果与输入顺序无关
            new_runs, new_qty = min(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        old_runs, old_qty = int(row.get("runs") or 0), caps[i]
        if new_runs != old_runs or new_qty != old_qty:
            ops.append({"op": "update", "id": row_id, "runs": new_runs, "quantity": new_qty})
        # 该行容不下的异构份额转为新增
        overflow = list(got)
        for _ in range(new_qty):
            overflow.remove(new_runs)
        ops.extend({"op": "insert", "runs": u} for u in overflow)

    ops.extend({"op": "insert", "runs": u} for u in pool)
    return ops


def target_units(clip_units: list[int], target_qty: int) -> list[int]:
    """把剪贴板张数调整为用户指定的目标张数（全量同步的「最终」列）。

    多则截断（保留靠前的），少则用组内出现最多的流程数补齐；剪贴板为空时
    以 0（原图/无流程）补齐——空组补张数属异常输入，取 0 比编造流程数安全。
    """
    units = [int(u) for u in clip_units]
    target = max(int(target_qty), 0)
    if target <= len(units):
        return units[:target]
    fill = Counter(units).most_common(1)[0][0] if units else 0
    return units + [fill] * (target - len(units))
