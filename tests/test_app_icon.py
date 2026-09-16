"""程序图标产物校验 —— 保证提交进仓库的 `.ico` 是有效的多尺寸容器。

Qt 的 ico 写入器只输出单张，多尺寸容器是 `scripts/make_app_icon.py` 手写的，
所以这里按 ICO 规范逐字段核对（容器坏掉时 Windows 会静默回退成默认图标，
不会报错 —— 只能靠测试挡住）。生成整条管线要 10s 级（逐像素处理 2048² 源图），
不在测试里跑，只校验产物。
"""

import struct
from pathlib import Path

import pytest

ASSETS = Path(__file__).resolve().parent.parent / "ui_qml" / "assets"
APP_ICO = ASSETS / "app.ico"
ICON_SOURCE = ASSETS / "icon-source.png"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def test_icon_assets_exist():
    assert ICON_SOURCE.exists(), "设计稿缺失 → scripts/make_app_icon.py 无法重新生成图标"
    assert APP_ICO.exists(), "程序图标缺失 → PyInstaller 的 --icon 会让打包直接失败"


def test_app_ico_is_valid_multi_size():
    data = APP_ICO.read_bytes()
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind) == (0, 1), "ICO 头应为 reserved=0 / type=1"
    assert count == len(SIZES), f"应含 {len(SIZES)} 个尺寸，实际 {count}"

    declared: list[int] = []
    for i in range(count):
        w, h, _colors, _res, _planes, bpp, size, offset = struct.unpack("<BBBBHHII", data[6 + 16 * i : 22 + 16 * i])
        assert bpp == 32, "应声明 32bpp（含 alpha）"
        assert data[offset : offset + 8] == b"\x89PNG\r\n\x1a\n", "载荷应为 PNG（项目只跑 Windows 10/11）"
        png_w, png_h = struct.unpack(">II", data[offset + 16 : offset + 24])
        assert (png_w, png_h) == (w or 256, h or 256), "目录声明的尺寸必须与 PNG 实际尺寸一致"
        declared.append(png_w)

    assert tuple(sorted(declared)) == SIZES


@pytest.mark.ui
def test_qt_reads_every_size(qapp):
    """Qt 能读出全部尺寸 —— 反向确认容器结构没写歪。"""
    from ui_qml.app_icon import app_icon

    sizes = sorted((s.width(), s.height()) for s in app_icon().availableSizes())
    assert sizes == [(s, s) for s in SIZES]
