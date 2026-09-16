"""从设计稿生成程序图标 —— 多尺寸 `.ico` + 预览 PNG。

用法::

    python scripts/make_app_icon.py            # 用默认设计稿
    python scripts/make_app_icon.py --source <path/to/design.png> --radius 0.18

设计稿约定：**白底 + 纯黑线条 + 可选浅灰水印**（AI 出图常见形态）。

管线与理由：

1. **二值化**：按亮度阈值取黑/白。设计稿的主体是纯黑线条，而水印与抗锯齿都是浅灰
   → 一次阈值就把它们一起清掉，不需要手工修图。
   **红色重点（设计稿的红点）单独摘出来**：它的亮度其实低于阈值、会被判成黑，而它是
   设计里唯一的彩色元素、也是小尺寸下最认得出的锚点 —— 按「红通道显著高于绿蓝」识别，
   从黑白图里挖掉，最后由 `render_icon` 按归一化坐标重画成红色。
2. **裁到落墨包围盒**：这类设计稿常是「宽而扁」的构图，直接塞进方形图标会在上下留大片
   白、把字母缩小一圈。先裁掉四周纯白再缩放。
3. **白底圆角方块**：主体是纯黑线条，抠成透明后放到 Windows **深色任务栏**上会变成
   「黑底黑图」只剩彩色点可见；保留白底 + 切圆角，四种主题下都读得出来。
   四角做透明（不是白色），这样圆角在深色背景上才真的是圆的。
4. **小尺寸简化**：16/24/32px 先做**形态学开运算**（先腐蚀后膨胀）去掉网格线、
   飞船同心椭圆这类细笔画，只留粗笔画与色点，再缩放 —— 直接缩原图在 32px 下
   只剩噪点、16px 下字母横笔画会粘连。
5. **组装 ICO**：Qt 的 ico 写入器**只输出单张图**（实测 `QImageWriter` 写 256 图
   得到的容器 `image count == 1`），所以这里自己拼多尺寸容器（PNG 载荷，
   Windows Vista+ 支持）。

产物：``ui_qml/assets/app.ico``（打包用）+ ``app.png``（256px 预览/运行时用）
      + ``logo_dark.png`` / ``logo_light.png``（外壳侧栏 logo，透明底，深/浅各一张）。
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QImageWriter, QPainter, QPainterPath

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = ROOT / "ui_qml" / "assets" / "icon-source.png"
OUT_DIR = ROOT / "ui_qml" / "assets"

# 打进 .ico 的尺寸。≥48 用原图，更小的走简化版（见模块 docstring 第 3 条）。
SIZES = (16, 24, 32, 48, 64, 128, 256)
SIMPLIFY_BELOW = 48

# 二值化阈值（0-255）：低于它算「图形」。水印/抗锯齿是浅灰，远高于此值。
THRESHOLD = 128
# 简化版的开运算半径，按工作分辨率的比例给（细笔画宽度因稿而异，需按实际调）
OPEN_RATIO = 0.012
# 圆角半径占边长的比例
CORNER_RATIO = 0.18
# 图形占图标边长（留边，避免线条顶到圆角）
ART_RATIO = 0.86
# 红点的最小半径占图标边长的比例：小尺寸下缩得比这更小就看不见了
MIN_ACCENT_RATIO = 0.055
# 开运算的工作分辨率：在此尺寸上简化后再缩放，比在 16px 上做精细得多
WORK_SIZE = 256

# ── 侧栏 logo（`ui_qml/assets/logo_*.png`）────────────────────────────
# 生成高度取显示高度的 2×：侧栏按约 32px 显示，留一倍余量供 `sourceSize` 下采样。
LOGO_HEIGHT = 96
# 墨色 **冻结在生成期**，不随主题 token 走：logo 是品牌资产（与 app.ico、物品图标同类），
# 不是界面配色，所以不参与「配色一律取自 registry」那条铁律。取值对齐两套调色板的
# 亮色文字（深色 #f8fafc = TEXT_BRIGHT，浅色 #1a1c2e = TEXT_PRIMARY），
# 这样贴到侧栏上与周边文字同色系。**改了要重跑本脚本**，旧图不会自己更新。
LOGO_INK_DARK = "#f8fafc"
LOGO_INK_LIGHT = "#1a1c2e"


def _luma(c: QColor) -> int:
    """感知亮度（ITU-R BT.601）。"""
    return (c.red() * 299 + c.green() * 587 + c.blue() * 114) // 1000


def _is_accent(c: QColor) -> bool:
    """红色重点（设计稿的红点）：红通道显著高于绿蓝。"""
    return c.red() > 110 and c.red() - max(c.green(), c.blue()) > 60


def binarize(img: QImage, threshold: int = THRESHOLD) -> tuple[QImage, tuple[int, int, int, QColor] | None]:
    """按亮度二值化 → `(黑白图, 红点的 (圆心x, 圆心y, 半径, 平均色) | None)`。

    红点的亮度低于阈值、会被判成黑，若不特判就会丢掉设计里唯一的彩色元素。
    这里把它从黑白图里挖白（留给 `render_icon` 最后重画），并返回其外接信息；
    颜色取红点像素的**平均值**，这样用的是设计稿自己的红，不用另编一个色值。
    """
    out = QImage(img.size(), QImage.Format.Format_ARGB32)
    out.fill(QColor("white"))
    sx = sy = n = 0
    sr = sg = sb = 0
    minx, maxx, miny, maxy = img.width(), 0, img.height(), 0
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if _is_accent(c):
                sx += x
                sy += y
                sr += c.red()
                sg += c.green()
                sb += c.blue()
                n += 1
                minx, maxx = min(minx, x), max(maxx, x)
                miny, maxy = min(miny, y), max(maxy, y)
                continue  # 挖白，稍后按归一化坐标重画
            if _luma(c) < threshold:
                out.setPixelColor(x, y, QColor("black"))
    if not n:
        return out, None
    accent = (sx // n, sy // n, max(maxx - minx, maxy - miny) // 2, QColor(sr // n, sg // n, sb // n))
    return out, accent


def crop_to_ink(img: QImage, margin_ratio: float = 0.02) -> tuple[QImage, int, int]:
    """裁到落墨包围盒（含少量留白）→ `(裁切图, x0, y0)`。

    设计稿常是「宽而扁」的构图，不裁的话在方形图标里上下会留大片白、字母被缩小一圈。
    隔点采样判断有没有墨，够用且快。
    """
    xs: list[int] = []
    ys: list[int] = []
    for y in range(0, img.height(), 2):
        for x in range(0, img.width(), 2):
            if _is_ink(img, x, y):
                xs.append(x)
                ys.append(y)
    if not xs:
        return img, 0, 0
    mx, my = int(img.width() * margin_ratio), int(img.height() * margin_ratio)
    x0, x1 = max(0, min(xs) - mx), min(img.width(), max(xs) + mx)
    y0, y1 = max(0, min(ys) - my), min(img.height(), max(ys) + my)
    return img.copy(x0, y0, x1 - x0, y1 - y0), x0, y0


def _is_ink(img: QImage, x: int, y: int) -> bool:
    return _luma(img.pixelColor(x, y)) < 128


def _morph(img: QImage, radius: int, *, erode: bool) -> QImage:
    """可分离的最小/最大滤波（腐蚀/膨胀），黑=前景。

    分横竖两趟做，复杂度 O(w·h·r) 而非 O(w·h·r²)；图标尺寸下够快。
    """
    w, h = img.width(), img.height()
    mid = QImage(img.size(), QImage.Format.Format_ARGB32)
    mid.fill(QColor("white"))

    def _pick(flags: list[bool]) -> bool:
        return all(flags) if erode else any(flags)

    for y in range(h):  # 横向
        for x in range(w):
            lo, hi = max(0, x - radius), min(w - 1, x + radius)
            if _pick([_is_ink(img, i, y) for i in range(lo, hi + 1)]):
                mid.setPixelColor(x, y, QColor("black"))
    out = QImage(img.size(), QImage.Format.Format_ARGB32)
    out.fill(QColor("white"))
    for y in range(h):  # 纵向
        for x in range(w):
            lo, hi = max(0, y - radius), min(h - 1, y + radius)
            if _pick([_is_ink(mid, x, i) for i in range(lo, hi + 1)]):
                out.setPixelColor(x, y, QColor("black"))
    return out


def simplify(img: QImage, radius: int) -> QImage:
    """形态学开运算：先腐蚀去掉细笔画、再膨胀把剩下的粗笔画恢复到原粗细。"""
    if radius <= 0:
        return img
    return _morph(_morph(img, radius, erode=True), radius, erode=False)


def render_icon(
    art: QImage,
    size: int,
    *,
    corner_ratio: float = CORNER_RATIO,
    art_ratio: float = ART_RATIO,
    accent: tuple[float, float, float, QColor] | None = None,
) -> QImage:
    """把二值化的图形画成「白底圆角方块 + 居中图形」，四角透明。

    accent 为**归一化**的 `(cx, cy, r, color)`（相对图形自身，0-1）：画在缩放后的
    对应位置上，并有最小半径保底 —— 否则 16px 下它会缩成看不见的一点，而它正是
    小尺寸最容易辨认的锚点。
    """
    out = QImage(size, size, QImage.Format.Format_ARGB32)
    out.fill(Qt.GlobalColor.transparent)
    inner = max(1, int(size * art_ratio))
    scaled = art.scaled(inner, inner, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    path = QPainterPath()
    r = size * corner_ratio
    path.addRoundedRect(QRectF(0, 0, size, size), r, r)
    ox, oy = (size - scaled.width()) // 2, (size - scaled.height()) // 2
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setClipPath(path)
    p.fillRect(QRectF(0, 0, size, size), QColor("white"))
    p.drawImage(ox, oy, scaled)
    if accent is not None:
        nx, ny, nr, color = accent
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawEllipse(
            QPointF(ox + nx * scaled.width(), oy + ny * scaled.height()),
            max(nr * scaled.width(), size * MIN_ACCENT_RATIO),
            max(nr * scaled.width(), size * MIN_ACCENT_RATIO),
        )
    p.end()
    return out


def render_logo(
    art: QImage,
    height: int,
    *,
    ink: QColor,
    accent: tuple[float, float, float, QColor] | None = None,
) -> QImage:
    """把二值图（白底黑墨）画成**透明底 + 指定墨色**的侧栏 logo。

    与 `render_icon` 的三点不同，都是刻意的：
      1. **不铺白底、不切圆角** —— 它是贴在界面 chrome 上的图形，不是任务栏图标块；
         深色主题下那块白底在侧栏里就是一块突兀的白砖。
      2. **按高度缩放，不塞进方形盒** —— 设计稿是宽扁构图，塞进方盒会白白缩小一圈。
      3. **墨色由调用方给** —— 深色主题要亮墨、浅色主题要暗墨，同一份设计稿出两张。

    墨色的 alpha 由**亮度反推**（越黑越不透明），缩放产生的灰边因此自带抗锯齿，
    不必自己写插值。
    """
    scaled = art.scaledToHeight(height, Qt.TransformationMode.SmoothTransformation)
    out = QImage(scaled.size(), QImage.Format.Format_ARGB32)
    out.fill(Qt.GlobalColor.transparent)
    for y in range(scaled.height()):
        for x in range(scaled.width()):
            alpha = 255 - _luma(scaled.pixelColor(x, y))
            if alpha <= 0:
                continue
            out.setPixelColor(x, y, QColor(ink.red(), ink.green(), ink.blue(), alpha))

    if accent is not None:
        nx, ny, nr, color = accent
        r = max(nr * scaled.width(), height * MIN_ACCENT_RATIO)
        p = QPainter(out)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawEllipse(QPointF(nx * scaled.width(), ny * scaled.height()), r, r)
        p.end()
    return out


def _png_bytes(img: QImage) -> bytes:
    buf = QByteArray()
    b = QBuffer(buf)
    b.open(QBuffer.OpenModeFlag.WriteOnly)
    QImageWriter(b, b"png").write(img)
    b.close()
    return bytes(buf.data())


def write_ico(path: Path, images: list[QImage]) -> None:
    """手写多尺寸 ICO 容器：ICONDIR(6B) + N×ICONDIRENTRY(16B) + N 段 PNG 载荷。

    宽/高字段在尺寸 ≥256 时写 0（ICO 规范如此）。png 载荷需 Windows Vista+，
    本应用只跑在 Windows 10/11 上。
    """
    blobs = [_png_bytes(im) for im in images]
    n = len(images)
    offset = 6 + 16 * n
    entries = bytearray()
    for im, blob in zip(images, blobs, strict=True):
        w = 0 if im.width() >= 256 else im.width()
        h = 0 if im.height() >= 256 else im.height()
        entries += struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    header = struct.pack("<HHH", 0, 1, n)
    path.write_bytes(header + bytes(entries) + b"".join(blobs))


def main(argv: list[str] | None = None) -> int:
    # 控制台默认是 GBK，收尾那几行里的 ✅ 会抛 UnicodeEncodeError ——
    # 那时产物**已经写完**，却是「成功干活 + 非零退出」的假故障。这里把输出钉成 UTF-8。
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(description="从设计稿生成程序图标（多尺寸 .ico）")
    ap.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="设计稿 PNG（白底 + 纯黑线条）")
    ap.add_argument("--out", type=Path, default=OUT_DIR / "app.ico", help="输出的 .ico 路径")
    ap.add_argument("--threshold", type=int, default=THRESHOLD, help="二值化阈值（默认 128）")
    ap.add_argument("--radius", type=float, default=CORNER_RATIO, help="圆角半径占边长比例（默认 0.18）")
    ap.add_argument("--open-ratio", type=float, default=OPEN_RATIO, help="小尺寸简化用的开运算半径比例")
    args = ap.parse_args(argv)

    if not args.source.exists():
        print(f"❌ 找不到设计稿：{args.source}")
        print("   请把原图存成 PNG（白底 + 纯黑线条）后重跑；浅灰水印会在二值化时自动清掉。")
        return 1

    src = QImage(str(args.source))
    if src.isNull():
        print(f"❌ 无法读取设计稿：{args.source}")
        return 1

    base, accent = binarize(src, args.threshold)
    base, x0, y0 = crop_to_ink(base)
    # 红点改成「相对裁切后图形」的归一化坐标，供 render_icon 在任意尺寸下重画
    norm_accent = None
    if accent:
        norm_accent = (
            (accent[0] - x0) / max(base.width(), 1),
            (accent[1] - y0) / max(base.height(), 1),
            accent[2] / max(base.width(), 1),
            accent[3],
        )
    # 开运算在固定工作分辨率上做，再缩放 —— 在 16px 上直接做会把字母一起吃掉
    work = base.scaled(
        WORK_SIZE, WORK_SIZE, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
    )
    simple = simplify(work, max(1, round(WORK_SIZE * args.open_ratio)))

    images = [
        render_icon(simple if size < SIMPLIFY_BELOW else base, size, corner_ratio=args.radius, accent=norm_accent)
        for size in SIZES
    ]
    write_ico(args.out, images)
    preview = OUT_DIR / "app.png"
    images[-1].save(str(preview))

    # 侧栏 logo：同一份设计稿出深/浅两张（透明底，墨色不同，红点沿用设计稿自己的红）
    for name, ink in (("logo_dark.png", LOGO_INK_DARK), ("logo_light.png", LOGO_INK_LIGHT)):
        logo = render_logo(base, LOGO_HEIGHT, ink=QColor(ink), accent=norm_accent)
        logo.save(str(OUT_DIR / name))

    print(f"✅ 已生成 {args.out.name}（{len(SIZES)} 个尺寸：{', '.join(str(s) for s in SIZES)}）")
    print(f"   裁到落墨范围：源 {src.width()}x{src.height()} → {base.width()}x{base.height()}（含留白）")
    if norm_accent:
        print(f"   红点已保留：{norm_accent[3].name()}，最小半径 {MIN_ACCENT_RATIO:.3f}×边长")
    print(f"   <{SIMPLIFY_BELOW}px 用简化版（开运算半径 {max(1, round(WORK_SIZE * args.open_ratio))}px @ {WORK_SIZE}）")
    print(f"✅ 预览图 {preview.name}")
    print(f"✅ 侧栏 logo：logo_dark.png（墨 {LOGO_INK_DARK}）/ logo_light.png（墨 {LOGO_INK_LIGHT}），高 {LOGO_HEIGHT}px")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
