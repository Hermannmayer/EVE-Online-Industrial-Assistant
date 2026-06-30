"""BOM 展开逻辑单元测试 — services/bom_expander.py

测试覆盖:
  - BomNode 数据类构造
  - _resolve_name: 物品名称解析
  - _find_blueprint_for_product: 蓝图查找
  - _get_materials: 材料列表获取
  - _expand: 叶子节点 / 中间产品 / 循环检测
  - expand_bom: 完整入口
  - 便捷函数: get_material_tree, get_flat_materials, print_tree
"""

from unittest.mock import MagicMock, patch

from services.bom_expander import (
    BomNode,
    _find_blueprint_for_product,
    _get_materials,
    _resolve_name,
    expand_bom,
    get_flat_materials,
    get_material_tree,
    print_tree,
)


class TestBomNode:
    """BomNode 数据类"""

    def test_default_construction(self):
        node = BomNode(
            type_id=34, name="Tritanium", quantity=100.0,
            base_quantity=100, is_intermediate=False,
        )
        assert node.type_id == 34
        assert node.name == "Tritanium"
        assert node.quantity == 100.0
        assert node.base_quantity == 100
        assert node.is_intermediate is False
        assert node.children == []
        assert node.depth == 0
        assert node.unit_price == 0.0
        assert node.subtotal == 0.0
        assert node.blueprint_type_id is None

    def test_with_children(self):
        child = BomNode(
            type_id=34, name="Tritanium", quantity=500.0,
            base_quantity=500, is_intermediate=False,
        )
        parent = BomNode(
            type_id=587, name="Raven", quantity=1.0,
            base_quantity=1, is_intermediate=True,
            children=[child], depth=1, unit_price=50_000_000,
            subtotal=2500.0, blueprint_type_id=3001,
        )
        assert len(parent.children) == 1
        assert parent.children[0].type_id == 34
        assert parent.is_intermediate is True

    def test_empty_children_default(self):
        node = BomNode(type_id=1, name="x", quantity=1.0, base_quantity=1, is_intermediate=False)
        assert node.children == []


class TestResolveName:
    """物品名称解析"""

    def test_mineral_name(self):
        """矿物 type_id 使用硬编码名称"""
        c = MagicMock()
        name = _resolve_name(c, 34)
        assert name == "三钛合金"
        c.execute.assert_not_called()

    def test_item_table_name(self):
        """从 item 表查询名称"""
        c = MagicMock()
        c.execute.return_value.fetchone.return_value = ("渡鸦级", "Raven")
        name = _resolve_name(c, 2001)
        assert name == "渡鸦级"

    def test_fallback_to_en_name(self):
        c = MagicMock()
        c.execute.return_value.fetchone.return_value = (None, "Raven")
        name = _resolve_name(c, 2001)
        assert name == "Raven"

    def test_fallback_to_type_id(self):
        c = MagicMock()
        c.execute.return_value.fetchone.return_value = (None, None)
        name = _resolve_name(c, 99999)
        assert name == "99999"


class TestFindBlueprintForProduct:
    """查找产出指定物品的蓝图"""

    def test_finds_blueprint(self):
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = (3001, 1, 3600)
        result = _find_blueprint_for_product(conn, 2001, "manufacturing")
        assert result == (3001, 1, 3600)

    def test_returns_none_when_not_found(self):
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = None
        result = _find_blueprint_for_product(conn, 99999, "manufacturing")
        assert result is None


class TestGetMaterials:
    """获取蓝图材料列表"""

    def test_returns_materials(self):
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [(34, 100), (35, 50)]
        result = _get_materials(conn, 3001, "manufacturing")
        assert len(result) == 2
        assert result[0] == (34, 100)

    def test_returns_empty(self):
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = []
        result = _get_materials(conn, 99999, "manufacturing")
        assert result == []


class TestExpand:
    """内部 _expand 递归展开"""

    @patch("services.bom_expander.get_price")
    def test_leaf_node_no_blueprint(self, mock_get_price):
        """无蓝图的物品 → 叶子节点"""
        mock_get_price.return_value = 5.0

        conn = MagicMock()
        # 第一次 execute: _resolve_name (type_id=34 → mineral, 不走 execute)
        # 但 _resolve_name 会查表，除非是矿物
        # 使用非矿物 type_id 确保走查询路径
        conn.execute.return_value.fetchone.side_effect = [
            ("Widget", None),       # _resolve_name
            None,                    # _find_blueprint_for_product → no bp
        ]

        from services.bom_expander import _expand

        node = _expand(
            conn=conn, type_id=9999, needed_qty=100.0,
            bp_me=10, price_hub="Jita", price_type="sell",
            depth=0, max_depth=5, seen=set(), cache={},
        )

        assert node.type_id == 9999
        assert node.name == "Widget"
        assert node.quantity == 100.0
        assert node.is_intermediate is False
        assert node.unit_price == 5.0
        assert node.subtotal == 500.0

    @patch("services.bom_expander.get_price")
    def test_intermediate_node_with_materials(self, mock_get_price):
        """有蓝图的物品 → 中间产品 + 子节点"""
        mock_get_price.return_value = 50_000_000.0

        conn = MagicMock()

        def execute_side_effect(sql, params=()):
            mock_c = MagicMock()
            if "FROM item" in sql:
                mock_c.fetchone.return_value = ("Raven", "Raven")
            elif "FROM blueprint_products" in sql:
                if params == (2001, "manufacturing"):
                    mock_c.fetchone.return_value = (3001, 1, 3600)
                else:
                    mock_c.fetchone.return_value = None
            elif "FROM blueprint_materials" in sql:
                mock_c.fetchall.return_value = [(34, 100)]
            else:
                mock_c.fetchone.return_value = None
                mock_c.fetchall.return_value = []
            return mock_c

        conn.execute.side_effect = execute_side_effect

        from services.bom_expander import _expand

        node = _expand(
            conn=conn, type_id=2001, needed_qty=1.0,
            bp_me=10, price_hub="Jita", price_type="sell",
            depth=0, max_depth=5, seen=set(), cache={},
        )

        assert node.type_id == 2001
        assert node.is_intermediate is True
        # Type_id 34 is a mineral → _resolve_name returns from _MINERAL_NAMES
        assert len(node.children) == 1
        assert node.children[0].is_intermediate is False

    @patch("services.bom_expander.get_price")
    def test_depth_limit(self, mock_get_price):
        mock_get_price.return_value = 10.0
        conn = MagicMock()
        conn.execute.return_value.fetchone.side_effect = [("Deep", None), None]

        from services.bom_expander import _expand

        node = _expand(
            conn=conn, type_id=999, needed_qty=5.0,
            bp_me=0, price_hub="Jita", price_type="buy",
            depth=6, max_depth=5, seen=set(), cache={},
        )
        assert node.is_intermediate is False
        assert node.quantity == 5.0

    @patch("services.bom_expander.get_price")
    def test_cycle_detection(self, mock_get_price):
        mock_get_price.return_value = 99.0
        conn = MagicMock()
        conn.execute.return_value.fetchone.side_effect = [("Loop", None), None]

        from services.bom_expander import _expand

        node = _expand(
            conn=conn, type_id=2001, needed_qty=1.0,
            bp_me=5, price_hub="Jita", price_type="sell",
            depth=2, max_depth=5, seen={2001}, cache={},
        )
        assert node.is_intermediate is False
        assert node.type_id == 2001

    @patch("services.bom_expander.get_price")
    def test_empty_materials_list(self, mock_get_price):
        """蓝图无材料记录时降级为叶子"""
        mock_get_price.return_value = 5000.0

        conn = MagicMock()

        def execute_side_effect(sql, params=()):
            mock_c = MagicMock()
            if "FROM item" in sql:
                mock_c.fetchone.return_value = ("EmptyBP", None)
            elif "FROM blueprint_products" in sql:
                mock_c.fetchone.return_value = (4001, 1, 1200)
            elif "FROM blueprint_materials" in sql:
                mock_c.fetchall.return_value = []
            else:
                mock_c.fetchone.return_value = None
            return mock_c

        conn.execute.side_effect = execute_side_effect

        from services.bom_expander import _expand

        node = _expand(
            conn=conn, type_id=2002, needed_qty=10.0,
            bp_me=0, price_hub="Jita", price_type="sell",
            depth=0, max_depth=5, seen=set(), cache={},
        )
        assert node.is_intermediate is False
        assert node.blueprint_type_id == 4001


class TestExpandBom:
    """公开 API expand_bom"""

    @patch("services.bom_expander.db")
    @patch("services.bom_expander.get_price")
    def test_expand_simple_item(self, mock_get_price, mock_db):
        """展开一个无蓝图的简单物品"""
        mock_get_price.return_value = 5.0

        mock_conn = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__enter__.return_value = mock_conn
        mock_cm.__exit__.return_value = False
        mock_db.connect.return_value = mock_cm

        # Using type_id = 9999 (non-mineral, no blueprint)
        mock_conn.execute.return_value.fetchone.side_effect = [
            ("Simple", None),  # _resolve_name
            None,               # _find_blueprint_for_product
        ]

        result = expand_bom(type_id=9999, quantity=100, bp_me=10)

        assert result["tree"] is not None
        assert result["tree"].type_id == 9999
        assert result["full_cost"] == 500.0
        assert result["leaf_only_cost"] == 500.0
        assert len(result["raw_materials"]) == 1
        assert result["raw_materials"][0]["name"] == "Simple"

    @patch("services.bom_expander.db")
    @patch("services.bom_expander.get_price")
    def test_expand_with_blueprint(self, mock_get_price, mock_db):
        """展开一个含蓝图的物品"""
        mock_get_price.return_value = 1000.0

        mock_conn = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__enter__.return_value = mock_conn
        mock_cm.__exit__.return_value = False
        mock_db.connect.return_value = mock_cm

        def execute_side_effect(sql, params=()):
            mock_c = MagicMock()
            if "FROM item" in sql:
                mock_c.fetchone.return_value = ("TestItem", "TestItem")
            elif "FROM blueprint_products" in sql:
                if params == (2001, "manufacturing"):
                    mock_c.fetchone.return_value = (3001, 1, 3600)
                else:
                    mock_c.fetchone.return_value = None
            elif "FROM blueprint_materials" in sql:
                if params == (3001, "manufacturing"):
                    mock_c.fetchall.return_value = [(34, 100)]
                else:
                    mock_c.fetchall.return_value = []
            else:
                mock_c.fetchone.return_value = None
                mock_c.fetchall.return_value = []
            return mock_c

        mock_conn.execute.side_effect = execute_side_effect

        result = expand_bom(type_id=2001, quantity=1, bp_me=10)

        tree = result["tree"]
        assert tree.is_intermediate is True
        assert len(tree.children) >= 1
        # Type 34 is a mineral so name comes from _MINERAL_NAMES
        assert "raw_materials" in result
        assert "intermediates" in result

    @patch("services.bom_expander.db")
    @patch("services.bom_expander.get_price")
    def test_get_material_tree_convenience(self, mock_get_price, mock_db):
        """get_material_tree 返回树根节点"""
        mock_get_price.return_value = 5.0
        mock_conn = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__enter__.return_value = mock_conn
        mock_cm.__exit__.return_value = False
        mock_db.connect.return_value = mock_cm
        mock_conn.execute.return_value.fetchone.side_effect = [("Mineral", None), None]

        tree = get_material_tree(type_id=9999, quantity=10)
        assert isinstance(tree, BomNode)
        assert tree.type_id == 9999

    @patch("services.bom_expander.db")
    @patch("services.bom_expander.get_price")
    def test_get_flat_materials_convenience(self, mock_get_price, mock_db):
        """get_flat_materials 返回扁平材料列表"""
        mock_get_price.return_value = 5.0
        mock_conn = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__enter__.return_value = mock_conn
        mock_cm.__exit__.return_value = False
        mock_db.connect.return_value = mock_cm
        mock_conn.execute.return_value.fetchone.side_effect = [("Mineral", None), None]

        flat = get_flat_materials(type_id=9999, quantity=10)
        assert isinstance(flat, list)
        assert len(flat) >= 1
        assert flat[0]["type_id"] == 9999

    def test_print_tree(self):
        """print_tree 生成可读树结构"""
        child = BomNode(
            type_id=34, name="Tritanium", quantity=500.0,
            base_quantity=500, is_intermediate=False, subtotal=2500.0,
        )
        parent = BomNode(
            type_id=587, name="Raven", quantity=1.0,
            base_quantity=1, is_intermediate=True,
            children=[child], subtotal=2500.0,
        )
        output = print_tree(parent)
        assert "[造]" in output or "[买]" in output
        assert "Raven" in output
        assert "Tritanium" in output
        assert "ISK" in output
