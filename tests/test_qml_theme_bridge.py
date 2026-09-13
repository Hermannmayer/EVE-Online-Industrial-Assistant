"""ThemeBridge（QML 主题桥）契约测试。

不依赖 QApplication：`ThemeBridge` 的 `_apply_accent` 在无应用实例时静默跳过，
其余 token 读取纯走 `ui_pyside6.theme`，因此归入 validate 档。
"""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtGui import QColor

import ui_pyside6.theme as theme
from tests.test_theme_registry import _COLOR_KEYS
from ui_qml.bridge import CONTEXT_NAME, ThemeBridge, theme_singleton
from ui_qml.bridge.theme_bridge import COLOR_TOKENS


def test_color_tokens_match_registry_schema():
    """桥暴露的颜色 token 必须与主题注册表的 schema 完全一致（单一来源）。"""
    assert set(COLOR_TOKENS) == _COLOR_KEYS


def test_context_name_is_theme():
    """QML 侧写死的名字，改名即破坏所有页面。"""
    assert CONTEXT_NAME == "Theme"


def test_every_token_resolves_to_theme_value():
    bridge = ThemeBridge()
    for token in COLOR_TOKENS:
        # snake → camel：BG_SURFACE_LIGHT → bgSurfaceLight
        head, *tail = token.lower().split("_")
        attr = head + "".join(part.capitalize() for part in tail)
        actual = getattr(bridge, attr)
        assert isinstance(actual, QColor)
        assert actual.isValid(), f"{token} 未解析为有效颜色"
        assert actual.name() == QColor(getattr(theme, token)).name(), f"{token} 与 theme 不一致"
    bridge.detach()


def test_qml_property_names_are_camel_case():
    """回归护栏：PySide6 以 Python 属性名作为 QML 名。

    若写成 snake_case，QML 里的 `Theme.bgDark` 会**静默**解析为 undefined
    （不报错、拿到空值），极难排查——故在此锁死命名风格。
    """
    bridge = ThemeBridge()
    meta = bridge.metaObject()
    names = [meta.property(i).name() for i in range(meta.propertyCount())]
    exposed = [n for n in names if not n.startswith("_") and n != "objectName"]
    snake = [n for n in exposed if "_" in n]
    assert not snake, f"以下属性名含下划线，QML 侧会静默取不到值: {snake}"
    bridge.detach()


def test_theme_switch_emits_changed_and_updates_values():
    bridge = ThemeBridge()
    fired: list[int] = []
    bridge.changed.connect(lambda: fired.append(1))

    theme.apply_theme("one-dark")
    dark_primary = bridge.primary.name()
    dark_is_dark = bridge.isDark

    theme.apply_theme("one-light")
    assert fired, "切换主题未触发 changed 信号"
    assert bridge.themeId == "one-light"
    assert bridge.isDark is False
    assert dark_is_dark is True
    assert bridge.primary.name() != dark_primary, "主色未随主题变化"

    theme.apply_theme("one-dark")  # 还原，避免污染其他测试
    bridge.detach()


def test_design_tokens_exposed():
    """Fluent 设计 token（高度/动效/间距/焦点环）必须可读且与 theme 一致。"""
    bridge = ThemeBridge()
    assert bridge.durationFast == theme.DURATION_FAST
    assert bridge.durationCard == theme.DURATION_CARD
    assert bridge.spacingSm == theme.SPACING_SM
    assert bridge.focusRingWidth == theme.FOCUS_RING_WIDTH
    assert bridge.radius == theme.RADIUS
    assert bridge.fs(13) == theme.fs(13)

    for level in (1, 2, 3, 4):
        blur, offset, alpha = theme.ELEVATION[level]
        assert bridge.elevationBlur(level) == blur
        assert bridge.elevationOffset(level) == offset
        assert bridge.elevationAlpha(level) == alpha
    bridge.detach()


def test_singleton_is_stable():
    assert theme_singleton() is theme_singleton()


def _meta_name(value: object) -> str:
    """QMetaObject 的名字统一成 str。

    PySide6 这里给的是 `QByteArray`：它没有 `.decode()`，
    而 `str()` 会带上 `b'...'` 前缀（得到 `"b'fs'"` 而不是 `"fs"`），
    必须走 buffer 协议转 bytes 再解码。
    """
    if isinstance(value, str):
        return value
    try:
        return str(bytes(value).decode("utf-8"))  # type: ignore[call-overload]
    except (TypeError, ValueError, AttributeError):
        return str(value)


def test_qml_only_references_existing_theme_tokens():
    """回归护栏：QML 里写错的 `Theme.xxx` 会**静默**变成 undefined。

    与 Python 侧那个 snake_case 陷阱同源——QML 引用不存在的 token 不报错，
    只在运行时表现为尺寸/颜色异常。实测踩过一次：`Theme.spacing_lg`（正确是
    `spacingLg`）让 `implicitWidth` 变成 NaN，Row 里的按钮宽度全为 0。
    这里静态扫描全部 QML 文件，逐个核对 token 是否真的存在于桥上。
    """
    bridge = ThemeBridge()
    meta = bridge.metaObject()
    known = {meta.property(i).name() for i in range(meta.propertyCount())}
    for i in range(meta.methodCount()):
        # PySide6 这里返回 QByteArray，不是 bytes/str
        known.add(_meta_name(meta.method(i).name()))

    qml_root = Path(__file__).resolve().parent.parent / "ui_qml" / "qml"
    files = sorted(qml_root.rglob("*.qml"))
    assert files, f"未找到任何 QML 文件，路径可能已变更: {qml_root}"

    unknown: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        for name in sorted(set(re.findall(r"\bTheme\.([A-Za-z_]\w*)", text))):
            if name not in known:
                unknown.append(f"{path.name}: Theme.{name}")

    bridge.detach()
    assert not unknown, "QML 引用了不存在的 Theme token（运行时静默为 undefined）: " + ", ".join(unknown)
