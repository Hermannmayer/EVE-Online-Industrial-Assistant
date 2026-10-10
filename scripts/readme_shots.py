"""README 宣传截图工具 —— 自包含，数据源**只接受合成演示根**。

为什么不直接用 `scripts/shell_snapshot.py`：
1. 它只拍「刚导航过去」的页面，拍不到页内状态（全物品、甘特图、购物车、蓝图页签…）；
2. 它的 `--real` 会把仓库里真实的 `database/` 与 `data/`（开发者账号数据）整目录复制到
   临时根再渲染 —— 那是本机开发手段，**绝不能用于公开仓库的宣传图**。

本工具的做法：把应用根整个改向 `--demo-root`（只含公共 SDE 派生库 + 合成的演示数据），
起真窗口，导航到目标页，按需调用页面桥的方法切到目标状态，再抓窗口帧缓冲。

用法：
    .venv/Scripts/python.exe scripts/readme_shots.py --demo-root %TEMP%\\eve-demo-root
    .venv/Scripts/python.exe scripts/readme_shots.py --demo-root ... --only query,industry
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

#: 一次截图任务：`(输出名, 页面 key, 进入页面后要做的动作)`。
#: 动作 `call:<方法>(<参数,...>)` 直接调**该页桥**（`QmlPage.hooks` 就是桥实例本身）；
#: `qml:<objectName>=<值>` 用来设 QML 节点属性（如页签 `currentIndex`）；空串 = 原样。
#: 详情面板要展示的物品（演示数据里行情最厚的一件）
DETAIL_ITEM = "重型脉冲激光器 I"

SHOTS: list[tuple[str, str, tuple[str, ...]]] = [
    # 首屏总览 = **不选物品**的空闲态（产线详情 / 资产折线 / 挂单列表三块仪表盘）
    ("shell", "query", ()),
    # 详情态：查询页 + 一件物品 + 合成订单簿（顺序不能反：先选中，再灌订单）
    ("query", "query", (f"call:pickSuggestion({DETAIL_ITEM})", f"call:detail.__orders__({DETAIL_ITEM})")),
    ("estimate", "estimate", ()),
    ("all-items", "query", ("call:openAllItems()",)),
    # 工业页的 hooks 是 IndustryPage 控制器，桥挂在 `.bridge` 上
    ("manufacturable", "industry", ("call:bridge.openManufacturableBrowser()",)),
    ("industry", "industry", ()),
    ("industry-gantt", "industry", ("call:bridge.setViewMode(gantt)",)),
    ("trade", "trade", ()),
    # 「贸易购物车」那张已移除：用户 2026-10-10 反馈「每次打开购物车软件就无响应」，
    # 出图不该去触发它（真要拍，等那个卡死修好再说）。见 README 的贸易一节只配 trade.png。
    ("watchlist", "watchlist", ()),
    # 关注页的 hooks 是 _MonitorHooks，__getattr__ 会把 selectRow 转给关注桥
    ("watchlist-follow", "watchlist", ("call:selectRow(0)",)),
    ("contract", "contract", ()),
    # 仓库页第 1 行是「类银超金属」——卖侧仅 3 件挂单的离群价，正好展示「⚠ 市价不可信」
    ("storage", "storage", ("call:setHangarIndex(0)",)),
    ("storage-blueprint", "storage", ("qml:storageTabBar=1",)),
]


def _synthetic_orders(demo_root: Path, item_name: str, hub: str = "Jita") -> tuple[list[dict], list[dict]]:
    """按**演示行情**合成本地订单簿（买降序 / 卖升序）。

    为什么不用 ESI 的公开实时订单：那会与合成价格打架（实测真实卖一 248,600 ISK、
    演示卖一 112,000 ISK），宣传图里「五个中心的价格」和「订单列表」自相矛盾。
    这里的价格围绕演示卖一价铺开，图内自洽；量级也按演示的挂单量量级给。
    """
    import sqlite3

    from core.constants import TRADE_HUB_IDS

    region = TRADE_HUB_IDS[hub]
    ref = sqlite3.connect(f"file:{demo_root / 'database' / 'reference.db'}?mode=ro", uri=True)
    hit = ref.execute("select type_id from item where zh_name = ?", (item_name,)).fetchone()
    ref.close()
    if not hit:
        return [], []
    type_id = int(hit[0])

    conn = sqlite3.connect(f"file:{demo_root / 'database' / 'market.db'}?mode=ro", uri=True)
    row = conn.execute(
        "select buy_price, sell_price, buy_volume, sell_volume from market_prices where type_id=? and region_id=?",
        (type_id, region),
    ).fetchone()
    conn.close()
    if not row:
        return [], []
    buy_p, sell_p, buy_v, sell_v = (float(row[0] or 0), float(row[1] or 0), int(row[2] or 0), int(row[3] or 0))
    station = 60003760  # Jita IV - Moon 4 - Caldari Navy Assembly Plant
    buy_orders = [
        {"price": round(buy_p * f, 2), "volume_remain": v, "location_id": station}
        for f, v in (
            (1.0, max(1, buy_v // 12)),
            (0.99, max(1, buy_v // 20)),
            (0.975, max(1, buy_v // 30)),
            (0.95, max(1, buy_v // 40)),
        )
    ]
    sell_orders = [
        {"price": round(sell_p * f, 2), "volume_remain": v, "location_id": station}
        for f, v in (
            (1.0, max(1, sell_v // 12)),
            (1.01, max(1, sell_v // 20)),
            (1.03, max(1, sell_v // 30)),
            (1.06, max(1, sell_v // 40)),
        )
    ]
    return buy_orders, sell_orders


def _spin(ms: int) -> None:
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _run_action(hooks: object, win: object, action: str) -> str:
    """执行页内动作；返回一句人话描述（失败不抛，只报告）。

    语法：
    - `call:<属性路径>.<方法>(<参数,...>)` —— 属性路径相对该页 hooks，支持点号下钻
      （实测 `industry` 页的 hooks 是 `IndustryPage` 控制器、桥挂在它 `.bridge` 上，
      而 `watchlist` 页的 hooks 只是个生命周期容器）。
    - `qml:<objectName>=<值>` —— 设 QML 节点属性（如页签 `currentIndex`）。
    """
    if not action:
        return "（原样）"
    kind, _, rest = action.partition(":")
    try:
        if kind == "call":
            path, _, call = rest.rpartition(".")
            method, _, raw_args = call.partition("(")
            args_txt = raw_args.rstrip(")")
            args: list[object] = []
            if args_txt.strip():
                for piece in args_txt.split(","):
                    piece = piece.strip()
                    args.append(int(piece) if piece.isdigit() else piece)
            # 路径可以为空（方法就在 hooks 上，如 `call:openAllItems()`）
            target = hooks
            for attr in [p for p in path.split(".") if p]:
                target = getattr(target, attr, None)
                if target is None:
                    return f"❌ hooks 上找不到 {path}"
            if method == "__orders__":
                # 特殊动作：给详情面板灌一份**与演示行情同源**的订单簿（解释见 _synthetic_orders）。
                # 物品名从动作参数给（比读 `detail.typeId` 稳 —— 那条依赖详情桥的异步时序）。
                item_name = args[0] if args else DETAIL_ITEM
                bridge: Any = target
                type_id = int(getattr(bridge, "typeId", 0) or 0)
                buy, sell = _synthetic_orders(Path(os.environ["EVE_ASSISTANT_APP_ROOT"]), str(item_name))
                bridge._on_orders_fetched(type_id, buy, sell)
                if not buy and not sell:
                    return f"❌ 合成订单簿为空（{item_name} 在演示库里没有 Jita 行情）"
                return f"合成订单簿({len(buy)} 买 / {len(sell)} 卖)"
            fn = getattr(target, method, None)
            if fn is None:
                return f"❌ {path or type(hooks).__name__} 没有 {method}"
            fn(*args)
            return f"{path + '.' if path else ''}{method}({args_txt})"
        if kind == "qml":
            name, _, value = rest.partition("=")
            node: Any = _find_qml(win, name)
            if node is None:
                return f"❌ QML 里找不到 objectName={name}"
            node.setProperty("currentIndex", int(value))
            return f"{name}.currentIndex={value}"
    except Exception as exc:
        return f"❌ {type(exc).__name__}: {exc}"
    return f"❌ 认不出的动作 {action}"


def _find_qml(root: object, object_name: str) -> object | None:
    """按 objectName 在 QML 对象树里找节点。

    注意要**同时**走两条树：`QObject.children()`（Python 侧挂的子对象）与
    `QQuickItem.childItems()`（QML 声明的视觉子项）—— 只走前者找不到 QML 里写的组件
    （实测 `storageTabBar` 只在视觉树里）。
    """
    from PySide6.QtCore import QObject
    from PySide6.QtQuick import QQuickItem

    if not isinstance(root, QObject):
        return None
    if root.objectName() == object_name:
        return root
    candidates = list(root.children())
    if isinstance(root, QQuickItem):
        candidates.extend(root.childItems())
    for child in candidates:
        found = _find_qml(child, object_name)
        if found is not None:
            return found
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo-root", required=True, help="合成演示根（build_demo_data.py 产出）")
    ap.add_argument("--out", default=str(REPO / "docs" / "public" / "screenshots"))
    ap.add_argument("--size", default="1600x1000")
    ap.add_argument("--only", default="", help="逗号分隔的输出名；留空=全部")
    ap.add_argument(
        "--batch", type=int, default=0, help="分批模式：每 N 张起一个新进程（实测单进程跑满 14 张偶发启动崩，分批稳）"
    )
    ap.add_argument("--dump-hooks", action="store_true", help="只打印各页 hooks 的真实形态后退出（诊断用）")
    args = ap.parse_args()

    root = Path(args.demo_root).expanduser().resolve()
    for required in ("database", "data"):
        if not (root / required).is_dir():
            raise SystemExit(f"演示根不完整：缺 {root / required}")
    os.environ["EVE_ASSISTANT_APP_ROOT"] = str(root)

    if args.batch:
        # 分批：每批一个子进程。实测单进程连续出 14 张时偶发在启动阶段 access violation，
        # 逐张跑则从不失败 —— 分批等价于逐张的成功率，又不用每张都付启动开销。
        names = [s[0] for s in SHOTS if not args.only or s[0] in {p.strip() for p in args.only.split(",")}]
        failed: list[str] = []
        for i in range(0, len(names), args.batch):
            chunk = names[i : i + args.batch]
            cmd = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--demo-root",
                str(root),
                "--out",
                args.out,
                "--size",
                args.size,
                "--only",
                ",".join(chunk),
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
            for line in (proc.stdout or "").splitlines():
                if line.startswith("[") or line.startswith("完成"):
                    print(line)
            if proc.returncode != 0:
                failed.extend(chunk)
                print(f"[批次 {i // args.batch + 1}] 失败 rc={proc.returncode}：{chunk}")
        print(f"\n分批完成：{len(names) - len(failed)}/{len(names)}；失败批次里的：{failed or '无'}")
        return 1 if failed else 0

    width, _, height = args.size.partition("x")
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    wanted = {s.strip() for s in args.only.split(",") if s.strip()}
    shots = [s for s in SHOTS if not wanted or s[0] in wanted]

    from PySide6.QtWidgets import QApplication

    QApplication([])  # 先有 QApplication 才能建窗口（引用不保留，Qt 自己持有）
    # 出图时抑制 QML 运行期噪声：真窗口样式下 Qt 会成片刷「当前样式不支持自定义该控件」
    # （本项目刻意自绘控件，这是预期行为），几千行会淹没脚本自己的进度输出。
    from PySide6.QtCore import QtMsgType, qInstallMessageHandler

    qInstallMessageHandler(lambda *_args: None if _args[0] in (QtMsgType.QtWarningMsg, QtMsgType.QtDebugMsg) else None)
    from ui_qml import shell_window

    # 掐掉真实价格检查/下载：出图不该联网，也不该让结果不确定（同 shell_snapshot.py 的做法）
    shell_window.ShellWindow._init_price_check = lambda self: None  # type: ignore[method-assign]
    # 演示根不复制全集图标缓存（67 MB），`check_all()` 的 icons 项必然 False，状态栏会显示
    # 「⚠ 1 项未初始化 (icons)」—— 宣传图不该带这句。它只是个状态栏文案（不影响任何功能），
    # 这里直接写成已就绪态。
    shell_window.ShellWindow._check_first_run = lambda self: self.set_status("就绪")  # type: ignore[method-assign]
    from ui_qml.bridge.contract_bridge import ContractBridge

    ContractBridge._start_backfill = lambda self, rows: None  # type: ignore[method-assign]

    win = shell_window.ShellWindow()
    # 不透明底：真窗口是透明材质，不设底色时截图会把背后的桌面一起框进来
    from PySide6.QtGui import QColor

    from ui_qml.theme import registry as theme

    win.setColor(QColor(theme.BG_DARK))
    win.resize(int(width), int(height))
    win.show()
    _spin(2500)

    loaded = len(win._pages)
    print(f"[截图] 应用根 = {root}")
    print(f"[截图] 已装载页面 {loaded} 个：{sorted(win._pages)}")
    if loaded != 7:
        print("[截图] ⚠️ 页面不是 7/7 —— 演示数据可能缺表（见 ui_qml/shell_window.py:_register_pages 的告警）")

    if args.dump_hooks:
        for key, page in win._pages.items():
            hooks = page.hooks
            names = sorted(n for n in dir(hooks) if not n.startswith("_"))
            print(f"[hooks] {key}: type={type(hooks).__name__} 公开成员={names[:40]}")
        win.close()
        return 0

    failures: list[str] = []
    action_failures: list[str] = []

    def _visible_tops() -> set[int]:
        return {id(w) for w in QApplication.topLevelWidgets() if w is not win and w.isVisible() and not w.isMinimized()}

    for name, page_key, actions in shots:
        if not win.navigate_to(page_key):
            print(f"[{name}] ❌ 没有页面 {page_key}")
            failures.append(name)
            continue
        _spin(900)
        hooks = win._pages[page_key].hooks
        descs: list[str] = []
        before = _visible_tops()
        for action in actions:
            desc = _run_action(hooks, win, action)
            if desc.startswith("❌"):
                # 动作没生效的图不能用（内容与图注不符），必须当失败
                action_failures.append(f"{name}: {desc}")
            descs.append(desc)
            _spin(1200)
        _spin(400)
        # 有些动作打开的是**独立顶层窗口**（可制造物品浏览窗、贸易购物车），抓主窗口看不到它们。
        # 只认「这次动作**新打开**」的窗口 —— 否则前一张留下的窗口会被后面每张都抓到。
        opened = [w for w in QApplication.topLevelWidgets() if id(w) in (_visible_tops() - before)]
        image: Any  # QPixmap（grabWindow）与 QImage（QWidget.grab）两种，别让 mypy 按首个分支定死
        if opened:
            shot_window: Any = opened[-1]
            shot_window.raise_()
            shot_window.activateWindow()
            _spin(900)
            image = shot_window.grab()
            descs.append(f"拍到独立窗口 {type(shot_window).__name__}")
            # 拍完就关：留着会让「新打开的窗口」这条判据在后面每张图里都命中同一个窗口
            shot_window.close()
            _spin(150)
        else:
            image = win.grabWindow()
        target = out_dir / f"{name}.png"
        ok = not image.isNull() and bool(image.save(str(target)))
        print(
            f"[{name}] {'OK' if ok else 'FAIL'} page={page_key} actions={' | '.join(descs) or '（原样）'} -> {target.name}"
        )
        if not ok:
            failures.append(name)

    win.close()
    print(f"\n完成 {len(shots) - len(failures)}/{len(shots)}；失败：{failures or '无'}")
    if action_failures:
        print("动作未生效（这些图不可用）：")
        for item in action_failures:
            print("   ", item)
    print(f"输出目录：{out_dir}")
    return 1 if (failures or action_failures) else 0


if __name__ == "__main__":
    sys.exit(main())
