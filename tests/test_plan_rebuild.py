"""服务层 plan_rebuild 测试 — 引用式需求 + 全量重放。

BOM（在 conftest bp 库之上扩展中间件 2003「聚变反应堆」）：
- bp3001 产渡鸦级 2001：材料 1001×1000、1002×500、2003×5
- bp3003 产聚变反应堆 2003：材料 1001×100、1002×50（每轮产 1 个）
- bp3002 产无人机 2002：材料 1001×100、1002×50、2003×10

两母项 2001/2002 共用中间件 2003 → 全局合并为一行、需求为两者之和。
"""

from types import SimpleNamespace

from services import inventory_manager, plan_execution, plan_rebuild
from services.repositories.plan_repository import PlanRepository

_BP_BOM_EXTRA = [
    # 3003 制造蓝图产出中间件 2003
    (3003, "manufacturing", 3600, 2003, 1, ((1001, 100, 10), (1002, 50, 10))),
    # 3001 渡鸦级增加中间件材料 2003
    (3001, "manufacturing", 3600, 2001, 1, ((1001, 1000, 10), (1002, 500, 10), (2003, 5, 10))),
    # 3002 无人机增加中间件材料 2003
    (3002, "manufacturing", 3600, 2002, 1, ((1001, 100, 10), (1002, 50, 10), (2003, 10, 10))),
]


def _seed_bom(db):
    """在 bp 库注入中间件 2003 的 BOM（幂等删除重建）。"""
    with db.connect("bp") as conn:
        conn.execute("DELETE FROM blueprint_activities WHERE blueprint_type_id IN (3001,3002,3003)")
        conn.execute("DELETE FROM blueprint_products WHERE blueprint_type_id IN (3001,3002,3003)")
        conn.execute("DELETE FROM blueprint_materials WHERE blueprint_type_id IN (3001,3002,3003)")
        for bp_id, activity, time, prod_id, qty, mats in _BP_BOM_EXTRA:
            conn.execute("INSERT INTO blueprint_activities VALUES (?,?,?)", (bp_id, activity, time))
            conn.execute("INSERT INTO blueprint_products VALUES (?,?,?,?)", (bp_id, activity, prod_id, qty))
            for mat_id, mat_qty, waste in mats:
                conn.execute(
                    "INSERT INTO blueprint_materials VALUES (?,?,?,?,?)",
                    (bp_id, activity, mat_id, mat_qty, waste),
                )


def _container(db):
    return SimpleNamespace(db=db, plan_repo=PlanRepository(db))


def _insert_mother(repo, product_type_id: int, *, runs=2, parallels=1, group=1) -> int:
    pid = repo.save(
        {
            "product_type_id": product_type_id,
            "product_name": str(product_type_id),
            "blueprint_type_id": None,
            "runs": runs,
            "parallels": parallels,
            "me_level": 0,
            "status": "pending",
        }
    )
    repo.update(pid, group_number=group, sub_level=0)
    return int(pid)


def _child_rows(db):
    with db.connect("user") as conn:
        rows = conn.execute(
            "SELECT id, product_type_id, runs, parallels, demand, source_mother_ids, "
            "component_parent_type_id, sub_level, status FROM production_plans WHERE sub_level > 0"
        ).fetchall()
    return [dict(r) for r in rows]


def _test_setup(temp_db, monkeypatch):
    _seed_bom(temp_db)
    # temp_db 的 user 库是空库（PRAGMA=v12）但无表：手动建 user_blueprints 等与 production_plans
    monkeypatch.setattr(inventory_manager, "_default_db", lambda: temp_db)
    inventory_manager.init_db()  # user_blueprints / hangars / inventory_items
    with temp_db.connect("user") as conn:
        # plan_blueprint_bindings 由 schema v7 迁移创建，测试库也补齐，供自动绑定/释放断言
        conn.executescript(
            "CREATE TABLE IF NOT EXISTS plan_blueprint_bindings ("
            "plan_id INTEGER NOT NULL, blueprint_id INTEGER NOT NULL, runs_used INTEGER DEFAULT 0, "
            "PRIMARY KEY (plan_id, blueprint_id))"
        )
    PlanRepository(temp_db).ensure_table()  # production_plans (v12 结构)
    monkeypatch.setattr(plan_rebuild, "get_container", lambda: _container(temp_db))
    # 自动绑定/释放走 plan_execution._container，也指向临时库，防污染真实 user.db
    monkeypatch.setattr(plan_execution, "_container", lambda: _container(temp_db))
    return _container(temp_db)


def test_shared_child_merged_across_mothers(temp_db, monkeypatch):
    """两母项共用 2003 → 仅一行，demand 为两者之和，source 含两母项。"""
    c = _test_setup(temp_db, monkeypatch)
    m1 = _insert_mother(c.plan_repo, 2001, runs=2, group=1)
    m2 = _insert_mother(c.plan_repo, 2002, runs=2, group=2)

    res = plan_rebuild.rebuild_children(create=True, prune=True)
    assert res["created"] == 1, res

    kids = _child_rows(temp_db)
    assert len(kids) == 1
    k = kids[0]
    assert k["product_type_id"] == 2003
    # 2001 需 5×2=10；2002 需 10×2=20 → demand=30
    assert k["demand"] == 30
    assert k["runs"] == 30  # 每轮产 1
    assert sorted(int(x) for x in k["source_mother_ids"].split(",") if x) == sorted([m1, m2])
    assert k["sub_level"] == 1


def test_rebuild_idempotent(temp_db, monkeypatch):
    """幂等：二次重放零新增/零删除、runs 不变。"""
    c = _test_setup(temp_db, monkeypatch)
    _insert_mother(c.plan_repo, 2001, runs=2, group=1)
    _insert_mother(c.plan_repo, 2002, runs=2, group=2)
    plan_rebuild.rebuild_children(create=True, prune=True)
    before = _child_rows(temp_db)
    res = plan_rebuild.rebuild_children(create=True, prune=True)
    assert res == {"created": 0, "updated": 0, "deleted": 0}
    after = _child_rows(temp_db)
    assert [(r["runs"], r["demand"]) for r in after] == [(r["runs"], r["demand"]) for r in before]


def test_mother_runs_change_recalc_children(temp_db, monkeypatch):
    """编辑母项 runs → 重放后子项 runs/demand 联动。"""
    c = _test_setup(temp_db, monkeypatch)
    m1 = _insert_mother(c.plan_repo, 2001, runs=1, group=1)
    c.plan_repo.update(m1, runs=5)
    plan_rebuild.rebuild_children(create=True, prune=True)
    k = _child_rows(temp_db)[0]
    assert k["demand"] == 5 * 5  # 仅 2001 引用，2002 未插入
    assert k["runs"] == 25


def test_add_mother_doubles_shared_demand(temp_db, monkeypatch):
    """新增共用组件母项 → 需求翻倍。"""
    c = _test_setup(temp_db, monkeypatch)
    _insert_mother(c.plan_repo, 2001, runs=2, group=1)
    plan_rebuild.rebuild_children(create=True, prune=True)
    k1 = _child_rows(temp_db)[0]
    assert k1["demand"] == 10

    _insert_mother(c.plan_repo, 2002, runs=2, group=2)
    plan_rebuild.rebuild_children(create=True, prune=True)
    k2 = _child_rows(temp_db)[0]
    assert k2["demand"] == 30
    assert len(_child_rows(temp_db)) == 1  # 仍是单行（合并）


def test_remove_mother_shrinks_demand(temp_db, monkeypatch):
    """删除一个母项 → 重放后需求收缩、source 只剩剩母项。"""
    c = _test_setup(temp_db, monkeypatch)
    m1 = _insert_mother(c.plan_repo, 2001, runs=2, group=1)
    m2 = _insert_mother(c.plan_repo, 2002, runs=2, group=2)
    plan_rebuild.rebuild_children(create=True, prune=True)
    assert _child_rows(temp_db)[0]["demand"] == 30

    c.plan_repo.delete(m1)
    plan_rebuild.rebuild_children(create=True, prune=True)
    kids = _child_rows(temp_db)
    assert len(kids) == 1
    k = kids[0]
    assert k["demand"] == 20  # 只剩 2002 的 10×2
    assert [int(x) for x in k["source_mother_ids"].split(",") if x] == [m2]


def test_remove_last_mother_deletes_child(temp_db, monkeypatch):
    """引用归零 → 子项被删除。"""
    c = _test_setup(temp_db, monkeypatch)
    m1 = _insert_mother(c.plan_repo, 2001, runs=2, group=1)
    plan_rebuild.rebuild_children(create=True, prune=True)
    assert len(_child_rows(temp_db)) == 1

    c.plan_repo.delete(m1)
    res = plan_rebuild.rebuild_children(create=True, prune=True)
    assert res["created"] == 0 and res["deleted"] == 1
    assert _child_rows(temp_db) == []


def test_rebuild_preserves_user_parallels(temp_db, monkeypatch):
    """已存在子项用户设的 parallels 保留，runs 按 parallels 重新摊。"""
    c = _test_setup(temp_db, monkeypatch)
    _insert_mother(c.plan_repo, 2001, runs=3, group=1)
    plan_rebuild.rebuild_children(create=True, prune=True)
    kid = _child_rows(temp_db)[0]
    assert kid["runs"] == 15  # demand 3×5=15，parallels=1

    c.plan_repo.update(kid["id"], parallels=3)
    plan_rebuild.rebuild_children(create=True, prune=True)
    k2 = _child_rows(temp_db)[0]
    assert k2["parallels"] == 3
    assert k2["runs"] == 5  # ceil(15 / (3×1))
    assert k2["demand"] == 15


def test_running_child_keeps_runs(temp_db, monkeypatch):
    """已投产子项（in_progress）重放时保留 runs、只更新需求/引用。"""
    c = _test_setup(temp_db, monkeypatch)
    m1 = _insert_mother(c.plan_repo, 2001, runs=2, group=1)
    plan_rebuild.rebuild_children(create=True, prune=True)
    kid = _child_rows(temp_db)[0]
    c.plan_repo.update(kid["id"], status="in_progress", runs=99)

    c.plan_repo.update(m1, runs=5)
    plan_rebuild.rebuild_children(create=True, prune=True)
    k2 = _child_rows(temp_db)[0]
    assert k2["runs"] == 99  # 已投产 runs 不砍
    assert k2["demand"] == 25  # 需求照常更新


def test_deleted_child_not_recreated_by_default(temp_db, monkeypatch):
    """删掉的子项产线不会因普通重放（create=False）被自动加回；
    但右键拆解（create=True）会重新生成。"""
    c = _test_setup(temp_db, monkeypatch)
    _insert_mother(c.plan_repo, 2001, runs=2, group=1)
    plan_rebuild.rebuild_children(create=True, prune=True)
    kid = _child_rows(temp_db)[0]
    c.plan_repo.delete(kid["id"])

    # 普通编辑母项 → 默认重放不重建已删子项
    plan_rebuild.rebuild_children()
    assert _child_rows(temp_db) == []

    # 显式拆解 → 重新生成
    plan_rebuild.rebuild_children(create=True, prune=True)
    assert len(_child_rows(temp_db)) == 1


def test_default_mode_updates_existing_but_no_create(temp_db, monkeypatch):
    """默认模式（create=False）只更新已存在子项，不创建新行。"""
    c = _test_setup(temp_db, monkeypatch)
    _insert_mother(c.plan_repo, 2001, runs=1, group=1)
    plan_rebuild.rebuild_children(create=True, prune=True)
    kid = _child_rows(temp_db)[0]
    c.plan_repo.update(kid["id"], demand=0)  # 抹掉旧需求
    c.plan_repo.update(_insert_mother(c.plan_repo, 2002, runs=2, group=2), runs=2)

    plan_rebuild.rebuild_children()  # 默认：不新建 2002 引出的缺口子项（此处仅 2003 已在）
    kids = _child_rows(temp_db)
    assert [k["product_type_id"] for k in kids] == [2003]  # 无新增


def test_prune_removes_orphan_child(temp_db, monkeypatch):
    """prune=True 时删除不再被任何母项引用的子项（删母项收缩）。"""
    c = _test_setup(temp_db, monkeypatch)
    m1 = _insert_mother(c.plan_repo, 2001, runs=2, group=1)
    plan_rebuild.rebuild_children(create=True, prune=True)
    assert len(_child_rows(temp_db)) == 1

    c.plan_repo.delete(m1)
    res = plan_rebuild.rebuild_children(create=False, prune=True)
    assert res["deleted"] == 1
    assert _child_rows(temp_db) == []


def test_delete_child_keeps_shared_child_for_other_mother(temp_db, monkeypatch):
    """共享子项删掉后，若仍被其他母项引用，prune 时不删除（仅更新引用）。"""
    c = _test_setup(temp_db, monkeypatch)
    m1 = _insert_mother(c.plan_repo, 2001, runs=2, group=1)
    m2 = _insert_mother(c.plan_repo, 2002, runs=2, group=2)
    plan_rebuild.rebuild_children(create=True, prune=True)
    kid = _child_rows(temp_db)[0]
    assert sorted(int(x) for x in kid["source_mother_ids"].split(",") if x) == sorted([m1, m2])

    # 删除一个母项 → 该母项退出引用；子项仍被 m2 引用 → 保留且 source 只剩 m2
    c.plan_repo.delete(m1)
    plan_rebuild.rebuild_children(create=False, prune=True)
    kids = _child_rows(temp_db)
    assert len(kids) == 1
    assert [int(x) for x in kids[0]["source_mother_ids"].split(",") if x] == [m2]


def test_prune_releases_child_binding(temp_db, monkeypatch):
    """prune 删除子项时其蓝图绑定被释放：关联表清空、蓝图归还不再占用（无孤儿行）。"""
    c = _test_setup(temp_db, monkeypatch)
    m1 = _insert_mother(c.plan_repo, 2001, runs=2, group=1)
    plan_rebuild.rebuild_children(create=True, prune=True)
    kid = _child_rows(temp_db)[0]
    # create 阶段库存为空未自动绑；这里手动绑给子项
    bp_id = inventory_manager.add_blueprint(1, 3003, is_bpo=False, me_level=0, te_level=0, runs=10, quantity=1)
    assert plan_execution.bind_blueprints(kid["id"], [bp_id])
    assert plan_execution.get_plan_blueprints(kid["id"]) == [bp_id]

    c.plan_repo.delete(m1)
    res = plan_rebuild.rebuild_children(create=False, prune=True)
    assert res["deleted"] == 1
    assert _child_rows(temp_db) == []
    with temp_db.connect("user") as conn:
        rows = conn.execute("SELECT * FROM plan_blueprint_bindings WHERE plan_id=?", (kid["id"],)).fetchall()
    assert rows == []  # 无孤儿绑定行
    assert bp_id not in plan_execution.get_occupied_blueprint_ids()  # 蓝图归还


def test_created_child_auto_binds_when_inventory_available(temp_db, monkeypatch):
    """新建子项时若库存有可用蓝图 → 自动绑定；无蓝图 → 保持未绑。"""
    c = _test_setup(temp_db, monkeypatch)
    inventory_manager.add_blueprint(1, 3003, is_bpo=False, me_level=5, te_level=0, runs=10, quantity=1)
    _insert_mother(c.plan_repo, 2001, runs=2, group=1)
    plan_rebuild.rebuild_children(create=True, prune=True)
    kid = _child_rows(temp_db)[0]
    assert kid["product_type_id"] == 2003
    assert plan_execution.get_plan_blueprints(kid["id"])  # 已自动绑定
