"""物品种类判定（services/item_kind.py）与材料剪贴板蓝图过滤。

蓝图判定唯一依据是 reference.db `item` 表的 group 名后缀，故本文件自建含
`zh_group_name` / `en_group_name` 列的 item 表，并一律断言 `filtered` 计数——
即使判定查询失败（失败开放 = 不过滤）也不会被误判为通过。
"""

import sqlite3

import pytest

from services.inventory_clipboard_service import parse_clipboard_rows
from services.item_kind import blueprint_type_ids, is_material_name, looks_like_blueprint_name

_ITEM_DDL = """
CREATE TABLE item (
    type_id INTEGER PRIMARY KEY,
    zh_name TEXT,
    en_name TEXT,
    zh_group_name TEXT,
    en_group_name TEXT
)
"""

# 覆盖：基础材料、T1 蓝图、T2 反应配方（zh 组名以「配方」结尾）、
#       名字含「蓝图」但并非蓝图的改装件、名字不含「蓝图」但实为蓝图的物品、无组名物品
_ITEMS = [
    (1001, "三钛合金", "Tritanium", "矿物", "Mineral"),
    (3001, "渡鸦级蓝图", "Raven Blueprint", "战列舰蓝图", "Battleship Blueprint"),
    (
        57495,
        "神经链接增强器反应配方",
        "Neuro-Link Formula",
        "分子熔铸反应配方",
        "Molecular-Forged Reaction Formulas",
    ),
    (
        43729,
        "屹立大型蓝图拷贝优化 I",
        "Standup L-Set Blueprint Copy Optimization I",
        "建筑工程大型改装件 - 蓝图拷贝优化",
        "Structure Engineering Rig L - Blueprint Copy Optimization",
    ),
    (28734, "莫德团雷达ECM", "Mordus Radar ECM", "ECM发生器蓝图", "ECM Blueprint"),
    (9001, "无组名物品", "No Group Item", None, None),
]


@pytest.fixture
def ref_conn():
    """内存 ref 连接（含 item 表与种类样本数据）。"""
    conn = sqlite3.connect(":memory:")
    conn.execute(_ITEM_DDL)
    conn.executemany("INSERT INTO item VALUES (?, ?, ?, ?, ?)", _ITEMS)
    conn.commit()
    yield conn
    conn.close()


class TestLooksLikeBlueprintName:
    def test_markers(self):
        """带蓝图/公式标记的名字（中英、忽略大小写）"""
        assert looks_like_blueprint_name("渡鸦级蓝图")
        assert looks_like_blueprint_name("Raven Blueprint")
        assert looks_like_blueprint_name("BLUEPRINT II")
        assert looks_like_blueprint_name("神经链接增强器反应配方")

    def test_non_blueprint(self):
        """材料名 / 空值不带标记"""
        assert not looks_like_blueprint_name("碳纤维")
        assert not looks_like_blueprint_name("")
        assert not looks_like_blueprint_name(None)


class TestBlueprintTypeIds:
    def test_group_suffix_predicate(self, ref_conn):
        """en 后缀 Blueprint(s)/Formula(s) 与 zh 后缀 蓝图/公式/配方 命中蓝图"""
        ids = blueprint_type_ids(ref_conn, [1001, 3001, 57495, 43729, 28734, 9001])
        assert ids == {3001, 57495, 28734}

    def test_empty_input(self, ref_conn):
        """空/None 输入不查库，返回空集合"""
        assert blueprint_type_ids(ref_conn, []) == set()
        assert blueprint_type_ids(ref_conn, [None, 0]) == set()

    def test_fail_open_on_missing_column(self):
        """旧库缺 group 列 → 返回空集合（失败开放：本次不过滤，不抛异常）"""
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE item (type_id INTEGER PRIMARY KEY, zh_name TEXT, en_name TEXT)")
        conn.execute("INSERT INTO item VALUES (1001, '三钛合金', 'Tritanium')")
        assert blueprint_type_ids(conn, [1001]) == set()
        conn.close()


class TestIsMaterialName:
    def test_material(self, ref_conn):
        assert is_material_name(ref_conn, "三钛合金") is True

    def test_blueprint_marker_short_circuits(self, ref_conn):
        """名字带标记 → 一律不按材料处理（含名字带「蓝图」的改装件）"""
        assert is_material_name(ref_conn, "渡鸦级蓝图") is False
        assert is_material_name(ref_conn, "屹立大型蓝图拷贝优化 I") is False

    def test_markerless_blueprint(self, ref_conn):
        """名字不含「蓝图」但 group 属蓝图 → 不是材料"""
        assert is_material_name(ref_conn, "莫德团雷达ECM") is False

    def test_unknown_name(self, ref_conn):
        """查不到的名字不是材料（由调用方沿用静默跳过）"""
        assert is_material_name(ref_conn, "完全不存在的东西") is False
        assert is_material_name(ref_conn, "") is False


class TestParseClipboardRowsFiltersBlueprints:
    def test_mixed_clipboard(self, ref_conn):
        """混合剪贴板：材料保留、蓝图行（ME 被当数量）被过滤并计数"""
        raw = "三钛合金\t1,000\n渡鸦级蓝图\t10\t20\t3\t原图\n"
        rows, filtered = parse_clipboard_rows(ref_conn, raw)
        assert filtered == 1
        assert [r["type_id"] for r in rows] == [1001]
        assert rows[0]["qty"] == 1000

    def test_pure_material_clipboard(self, ref_conn):
        """纯材料剪贴板不受影响"""
        rows, filtered = parse_clipboard_rows(ref_conn, "三钛合金\t100\n")
        assert filtered == 0
        assert len(rows) == 1
        assert rows[0]["status"] == "matched"

    def test_unmatched_blueprint_name_filtered(self, ref_conn):
        """未匹配但名字带蓝图标记的行也被过滤并计数"""
        rows, filtered = parse_clipboard_rows(ref_conn, "未知蓝图甲\t5\n")
        assert rows == []
        assert filtered == 1

    def test_unmatched_unknown_name_kept(self, ref_conn):
        """未匹配且无标记的行保持原行为（显示为未匹配，可手动搜索匹配）"""
        rows, filtered = parse_clipboard_rows(ref_conn, "完全不存在的东西\t5\n")
        assert filtered == 0
        assert len(rows) == 1
        assert rows[0]["type_id"] is None

    def test_rig_name_kept_as_material(self, ref_conn):
        """名字含「蓝图」但实为改装件（已匹配非蓝图）→ 仍作为材料保留"""
        rows, filtered = parse_clipboard_rows(ref_conn, "屹立大型蓝图拷贝优化 I\t2\n")
        assert filtered == 0
        assert [r["type_id"] for r in rows] == [43729]
