"""scripts/test_audit.py 的分类规则 —— 判定表体检工具自身。"""

from __future__ import annotations

import pytest

from scripts.test_audit import scan_source


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        # 外观 / 几何 —— 判定表禁止
        ('def test_a():\n    assert font.family() == "Consolas"\n', {"外观/几何断言"}),
        ("def test_b():\n    assert btn.width() < 100\n", {"外观/几何断言"}),
        ("def test_c():\n    assert align == Qt.AlignRight\n", {"外观/几何断言"}),
        # 标准库 / 内建类型 —— 判定表禁止
        ("def test_d():\n    assert isinstance(conn, sqlite3.Connection)\n", {"标准库或内建类型断言"}),
        ("def test_e():\n    assert isinstance(flat, list)\n", {"标准库或内建类型断言"}),
        # mock 调用序列 —— 判定表禁止（含 pytest-mock 的裸表达式写法）
        ("def test_f():\n    assert client.fetch.call_count == 3\n", {"mock 调用序列"}),
        ("def test_g():\n    client.fetch.assert_called_once_with(1)\n", {"mock 调用序列"}),
        # 零信息 —— 整个用例只有非 None 断言
        ("def test_h():\n    assert row is not None\n", {"零信息（仅非 None）"}),
        # 判定表允许的 —— 不应命中
        ("def test_i():\n    assert compute(2, 3) == 5\n", set()),
        ("def test_j():\n    assert row is not None\n    assert row.name == 'x'\n", set()),
        ("def test_k():\n    assert isinstance(item, MyModel)\n", set()),
        # 非测试函数不参与
        ("def helper():\n    assert font.family() == 'x'\n", set()),
        # 回归：断言写在 with/try 嵌套块里也要扫到（原先只看函数体顶层，整批漏掉）
        (
            "def test_l():\n    with ctx() as c:\n        assert isinstance(c, sqlite3.Connection)\n",
            {"标准库或内建类型断言"},
        ),
        (
            "def test_m():\n    try:\n        assert c.family() == 'x'\n    except KeyError:\n        pass\n",
            {"外观/几何断言"},
        ),
        # 嵌套函数里的断言不算在测试函数头上
        ("def test_n():\n    def inner():\n        assert font.family() == 'x'\n", set()),
        # 回归：身份断言（X is not Y）有信息量，不能算「零信息」
        ("def test_o():\n    assert conn_ref is not conn_mkt\n", set()),
    ],
)
def test_scan_source_classifies(source: str, expected: set[str]) -> None:
    assert {finding.category for finding in scan_source(source)} == expected
