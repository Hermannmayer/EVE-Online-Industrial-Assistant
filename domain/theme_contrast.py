"""配色对比度 —— WCAG 计算与校正，**纯 hex、不碰 Qt**。

原先住在 `ui_pyside6/views/industry/production_launcher.py` 里，用的是 `QColor`。
搬到 `domain/` 就不能再构造 Qt 对象（铁律：domain 无 DB/Qt/缓存），
所以这里一律走 `#rrggbb` 字符串与整数元组；要画的时候由调用方自己包 `QColor`。

顺带解决另一件事：对比度契约（`CONTRAST_CONTRACT`）是一份**纯数据的领域不变量**，
与「谁来画」无关。原先它挂在 1900 行的窗口模块上，测试为了断言配色要 import
整个启动器；现在测试只依赖这个模块。
"""

from __future__ import annotations

__all__ = [
    "CONTRAST_CONTRACT",
    "MIN_NON_TEXT_RATIO",
    "MIN_TEXT_RATIO",
    "SURFACE_ORDER_DARK",
    "SURFACE_ORDER_LIGHT",
    "contrast_ratio",
    "ensure_contrast",
    "relative_luminance",
]

#: WCAG 1.4.11 非文字对比度（图形/图标）
MIN_NON_TEXT_RATIO = 3.0
#: WCAG 1.4.3 正文对比度
MIN_TEXT_RATIO = 4.5

# ── 对比度契约 ───────────────────────────────────────────
#
# 角色 → (前景 token, 背景 token, 阈值)。
# `tests/test_theme_registry.py` 遍历 THEME_REGISTRY 的全部主题断言达标，
# 因此新增主题会被自动检查。**改样式必须同步改这张表**。
CONTRAST_CONTRACT: dict[str, tuple[str, str, float]] = {
    "工具条说明文字": ("TEXT_PRIMARY", "BG_DARK", MIN_TEXT_RATIO),
    "占用区标签": ("TEXT_PRIMARY", "BG_DARK", MIN_TEXT_RATIO),
    "状态徽章文字": ("TEXT_PRIMARY", "BG_SURFACE_LIGHT", MIN_TEXT_RATIO),
    "行标题": ("TEXT_BRIGHT", "BG_DARK", MIN_TEXT_RATIO),
    "行副标题": ("TEXT_PRIMARY", "BG_DARK", MIN_TEXT_RATIO),
    "行标题(悬浮)": ("TEXT_BRIGHT", "BG_SURFACE_LIGHT", MIN_TEXT_RATIO),
    "行副标题(悬浮)": ("TEXT_PRIMARY", "BG_SURFACE_LIGHT", MIN_TEXT_RATIO),
    "行标题(选中)": ("TEXT_BRIGHT", "BG_SURFACE_LIGHT", MIN_TEXT_RATIO),
    "行副标题(选中)": ("TEXT_PRIMARY", "BG_SURFACE_LIGHT", MIN_TEXT_RATIO),
    "主启动按钮文字": ("BG_DARK", "TEXT_BRIGHT", MIN_TEXT_RATIO),
    "主启动按钮文字(悬浮)": ("BG_DARK", "TEXT_PRIMARY", MIN_TEXT_RATIO),
    "次要按钮文字": ("TEXT_PRIMARY", "BG_HOVER", MIN_TEXT_RATIO),
    "输入框文字": ("TEXT_PRIMARY", "BG_HOVER", MIN_TEXT_RATIO),
    "底部面板文字": ("TEXT_PRIMARY", "BG_SURFACE", MIN_TEXT_RATIO),
}

#: 面的层次 —— **两套主题的次序不一样**，不是同一串（由暗到亮）：
#:
#: - 深色：窗口底 < 卡片 < 控件 < 悬浮（越抬升越亮，Fluent 深色惯例）
#: - 浅色：悬浮 < 控件 < 窗口底 < 卡片（越抬升越亮的只有卡片；控件/悬浮靠变暗区分）
#:
#: ⚠️ `docs/dev/ui-blueprint.md` 原先写「两个模式都是 `BG_SURFACE` < `BG_DARK` <
#: `BG_SURFACE_LIGHT` < `BG_HOVER`」，实测**两套都不满足** —— 那是主题收敛到 Fluent
#: 双主题之前的约定，文档已同步修正。跨主题成立的只有「卡片面与窗口底必须可区分」。
#:
#: 测试逐主题按 `BG_DARK` 的亮度选对应次序，断言**严格递增**。只测「前景/背景对各自
#: 达标」抓不到层次**翻转**：一对一对拆开都合格，整体却可能出现控件比它所在的底更暗
#: ——那就是文档里说的「黑洞」。
SURFACE_ORDER_DARK = ("BG_DARK", "BG_SURFACE", "BG_SURFACE_LIGHT", "BG_HOVER")
SURFACE_ORDER_LIGHT = ("BG_HOVER", "BG_SURFACE_LIGHT", "BG_DARK", "BG_SURFACE")


def _rgb(color: str) -> tuple[int, int, int]:
    """`#rrggbb`（或缩写 `#rgb`）→ (r, g, b)。"""
    text = str(color).strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        raise ValueError(f"不是 #rrggbb 颜色: {color!r}")
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def _hex(rgb: tuple[int, int, int]) -> str:
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


def relative_luminance(color: str) -> float:
    """WCAG 2.x 相对亮度（sRGB），入参 `#rrggbb`。"""

    def lin(channel: int) -> float:
        c = channel / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = _rgb(color)
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast_ratio(a: str, b: str) -> float:
    """WCAG 对比度（1.0–21.0）。"""
    high, low = sorted((relative_luminance(a), relative_luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def ensure_contrast(color: str, background: str, min_ratio: float = MIN_NON_TEXT_RATIO) -> str:
    """把颜色朝黑/白方向线性混合，直到与背景达到 `min_ratio`；返回 `#rrggbb`。

    用于**自绘图形**（占用方块、状态字形）：强调色是给填充用的中间调，
    在部分浅色主题下直接用会低于 WCAG 非文字 3:1（实测 one-light 的绿仅 2.87、
    eve-polar 的青仅 2.85）。亮底往黑调、暗底往白调，固定步数，必然终止且必然达标。
    """
    steps = 20
    original = _rgb(color)
    target = (0, 0, 0) if relative_luminance(background) > 0.5 else (255, 255, 255)
    current = original
    for step in range(1, steps + 1):
        if contrast_ratio(_hex(current), background) >= min_ratio:
            return _hex(current)
        t = step / steps
        current = (
            round(original[0] + (target[0] - original[0]) * t),
            round(original[1] + (target[1] - original[1]) * t),
            round(original[2] + (target[2] - original[2]) * t),
        )
    return _hex(target)
