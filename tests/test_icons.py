"""Phosphor 语义键 → SVG 资源的映射护栏。

原先这里还测 Widgets 专有的 `QIconEngine` 染色（`themed_icon` / `status_icon` /
`_pixmap_cache`）。批次 7.5 把 `ui_pyside6/icons.py` 那半删掉后，那些全没了 —— QML 侧的
染色走 `icon_provider`（拿 SVG 原文自己注入 `fill`），不经过 `QIconEngine`。

留下的是**跨两端都成立**的那条：`ICON_MAP` 里每个语义键都必须映射到**真实存在**的 SVG。
它挡的是「拼了 URL 但取不到图」——那种失败不报错，只是图标消失（本仓在 QML 外壳上
实测踩过一次，见 `tests/test_qml_shell.py` 的图标组）。

这些是纯文件 IO，**不碰 Qt**，所以不再打 `ui` 标记（归 validate 档）。
"""

from __future__ import annotations

import os

from ui_qml.icons import ICON_MAP, load_svg, svg_path


def test_every_icon_key_maps_to_an_existing_svg():
    missing = sorted(key for key in ICON_MAP if not os.path.isfile(svg_path(ICON_MAP[key])))
    assert not missing, f"这些语义键映射不到 SVG：{missing}（会静默显示成空白）"


def test_icon_map_is_not_empty():
    """护栏自身别失效：映射表空了的话上面那条会恒真。"""
    assert len(ICON_MAP) > 20, f"ICON_MAP 只有 {len(ICON_MAP)} 项，是不是被清空了？"


def test_load_svg_returns_real_markup():
    """`load_svg` 交出的是 SVG 原文（QML 侧靠它自己注入 `fill` 染色）。"""
    text = load_svg(ICON_MAP["settings"])
    assert "<svg" in text, "load_svg 没返回 SVG 内容"


def test_unknown_key_falls_back_to_itself():
    """未知键原样返回（沿用 `ICON_MAP.get(k, k)` 的约定），不至于拼出空 URL。"""
    assert ICON_MAP.get("no-such-key", "no-such-key") == "no-such-key"
