"""名称→type_id 测试 — services/name_resolver.py

覆盖 search_item_type_id 的四级回退优先级：
精确 → terminology 反向 → LIKE 模糊 → 引号归一化 LIKE。
重点防回归：基础矿物（type_id 34-40）不在 item 表，必须优先走 terminology，
不能被含子串的无关物品（如「三钛合金条」）用 LIKE 抢占。

以及 search_item_type_ids_batch（整仓剪贴板导入用）——它必须与逐行调用逐项等价。
"""

from services.name_resolver import search_item_type_id, search_item_type_ids_batch


def _build_item_db(db_manager):
    """在空 reference.db 建 item 表，模拟「三钛合金条」等真实场景"""
    with db_manager.connect("ref") as conn:
        conn.execute("CREATE TABLE item (type_id INTEGER PRIMARY KEY, zh_name TEXT, en_name TEXT)")
        conn.execute(
            "INSERT INTO item (type_id, zh_name, en_name) VALUES (?, ?, ?)",
            (25595, "三钛合金条", "Alloyed Tritanium Bar"),
        )
        conn.execute(
            "INSERT INTO item (type_id, zh_name, en_name) VALUES (?, ?, ?)",
            (2001, "渡鸦级", "Raven"),
        )
    return db_manager


def test_exact_match_zh(db_manager):
    """中文名精确匹配"""
    db = _build_item_db(db_manager)
    with db.connect("ref") as conn:
        assert search_item_type_id(conn, "渡鸦级") == 2001


def test_exact_match_en(db_manager):
    """英文名精确匹配"""
    db = _build_item_db(db_manager)
    with db.connect("ref") as conn:
        assert search_item_type_id(conn, "Raven") == 2001


def test_terminology_override_priority_over_like(db_manager):
    """「三钛合金」(基础矿物 34) 不在 item 表，优先 terminology，不能被 LIKE 误命中"""
    db = _build_item_db(db_manager)
    with db.connect("ref") as conn:
        # 若无优先排序，LIKE '%三钛合金%' 会命中「三钛合金条」(25595)
        assert search_item_type_id(conn, "三钛合金") == 34


def test_like_fallback_substring(db_manager):
    """子串名仍可精确命中 item 表"""
    db = _build_item_db(db_manager)
    with db.connect("ref") as conn:
        assert search_item_type_id(conn, "三钛合金条") == 25595


def test_unknown_returns_none(db_manager):
    """未知名称返回 None"""
    db = _build_item_db(db_manager)
    with db.connect("ref") as conn:
        assert search_item_type_id(conn, "不存在物品XYZ") is None


def test_blank_name_returns_none(db_manager):
    """空名/纯空白返回 None"""
    db = _build_item_db(db_manager)
    with db.connect("ref") as conn:
        assert search_item_type_id(conn, "") is None
        assert search_item_type_id(conn, "   ") is None


# ════════════════════════════════════════════════════════════════
#  批量匹配（整仓剪贴板导入）—— 必须与逐行调用逐项等价
# ════════════════════════════════════════════════════════════════


class TestBatchSearch:
    def test_batch_matches_row_by_row(self, db_manager):
        """命中/术语反向/模糊/未命中的四类名字，批量结果与逐行 search_item_type_id 完全一致"""
        db = _build_item_db(db_manager)
        with db.connect("ref") as conn:
            conn.execute(
                "INSERT INTO item (type_id, zh_name, en_name) VALUES (?, ?, ?)",
                (34, None, None),  # 基础矿物只在 terminology 注册
            )
            conn.commit()
            names = ["渡鸦级", "Raven", "三钛合金", "三钛合金条", "不存在物品XYZ", ""]
            batch = search_item_type_ids_batch(conn, names)
            assert batch == {n: search_item_type_id(conn, n) for n in names}
            assert batch["渡鸦级"] == 2001
            assert batch["三钛合金"] == 34
            assert batch["不存在物品XYZ"] is None

    def test_batch_dedups_and_keeps_original_keys(self, db_manager):
        """同名重复行只查一次，且原样键（含空串）都在返回里"""
        db = _build_item_db(db_manager)
        with db.connect("ref") as conn:
            batch = search_item_type_ids_batch(conn, ["渡鸦级", "渡鸦级", "", "渡鸦级"])
            assert batch == {"渡鸦级": 2001, "": None}
