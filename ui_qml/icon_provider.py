"""Phosphor SVG 图片供应器 —— 让 QML 也能用上主题染色的图标。

**为什么不用 `MultiEffect.colorization`**：它是 `layer.enabled` + 离屏特效，
`scripts/ui_snapshot.py` 的 offscreen 路径渲染不出来（阶段 1 已实测：带 layer 的
item 在 offscreen 下整个消失）。图标一旦依赖它，截图核对就永远是空的。
这里改为在**取图时染色**并返回 `QImage`——与 Widgets 侧 `icons._render_pixmap`
的注入 `fill` 手法完全一致，offscreen 与真实窗口渲染结果相同。

URL 形式：`image://phosphor/<svg 文件名>?c=<#rrggbb>&s=<像素>`

- 用 `QImage` 而不是 `QPixmap`：`requestImage` 可能在工作线程被调用，
  `QPixmap` 只能在 GUI 线程构造。
- 供应商自身带缓存：同一 (文件名, 颜色, 尺寸) 只渲染一次；主题切换会换颜色，
  自然换 URL，旧条目随 LRU 上限淘汰。
"""

from __future__ import annotations

from collections import OrderedDict
from urllib.parse import parse_qs

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage
from PySide6.QtQuick import QQuickImageProvider

import ui_pyside6.theme as theme
from ui_pyside6.icons import load_svg

__all__ = ["PhosphorIconProvider", "PROVIDER_ID"]

PROVIDER_ID = "phosphor"

_CACHE_LIMIT = 512
#: QML 里 Icon 的默认尺寸（`Image.sourceSize` 会覆盖它）
_DEFAULT_SIZE = 16


class PhosphorIconProvider(QQuickImageProvider):
    """`image://phosphor/<name>?c=<color>&s=<size>` → 染色后的 SVG 位图。"""

    def __init__(self) -> None:
        super().__init__(QQuickImageProvider.ImageType.Image)
        self._cache: OrderedDict[tuple[str, str, int], QImage] = OrderedDict()

    # ── QQuickImageProvider ───────────────────────────────────

    def requestImage(self, image_id: str, size: QSize, requested_size: QSize) -> QImage:
        name, _, query = image_id.partition("?")
        params = parse_qs(query)
        color = params.get("c", [theme.TEXT_SECONDARY])[0] or theme.TEXT_SECONDARY
        try:
            px = int(params.get("s", [_DEFAULT_SIZE])[0])
        except ValueError:
            px = _DEFAULT_SIZE
        px = max(1, min(px, 256))

        # 回填 size：Qt 据此决定是否缓存这张图（尺寸为 0 会被反复请求）
        size.setWidth(px)
        size.setHeight(px)
        return self._render(name, color, px)

    # ── 渲染与缓存 ────────────────────────────────────────────

    def _render(self, name: str, color: str, px: int) -> QImage:
        key = (name, color, px)
        hit = self._cache.get(key)
        if hit is not None:
            self._cache.move_to_end(key)
            return hit

        image = self._render_uncached(name, color, px)
        self._cache[key] = image
        while len(self._cache) > _CACHE_LIMIT:
            self._cache.popitem(last=False)
        return image

    @staticmethod
    def _render_uncached(name: str, color: str, px: int) -> QImage:
        svg = load_svg(name)
        if not svg:
            return _blank(px)
        # Phosphor 把 fill 写在 <svg> 根上，而 QSvgRenderer 不把根级 fill 继承给
        # <path>；直接给第一个 <path> 注入颜色（与 icons._render_pixmap 同法）。
        tinted = svg.replace("<path ", f'<path fill="{color}" ', 1)
        image = QImage()
        if not image.loadFromData(tinted.encode("utf-8")):
            return _blank(px)
        return image.scaled(
            px,
            px,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )


def _blank(px: int) -> QImage:
    """取不到图标时给一张全透明图：QML 的 Image 拿到空图不会刷警告。"""
    image = QImage(px, px, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    return image
