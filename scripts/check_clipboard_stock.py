r"""诊断：读当前剪贴板 → 软件解析出的物品数量 vs 库里的数量。

用来排查「明明有货却让我买」这类报障：先在游戏里「仓库 → 物品」全选复制（Ctrl+A / Ctrl+C），再跑：

    .venv\Scripts\python.exe scripts\check_clipboard_stock.py            # 默认查莫尔石 11399
    .venv\Scripts\python.exe scripts\check_clipboard_stock.py --type 34 --name 三钛合金

只读剪贴板 + 只读数据库（副本），不写任何东西。同一种物品在剪贴板里有多堆时会逐堆列出，
并给出各堆之和 —— 那是软件应该累加后入库的数量。
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def read_clipboard() -> str:
    """读系统剪贴板文本（尽量不依赖 Qt：优先 tkinter，回退 PowerShell Get-Clipboard）。"""
    try:
        import tkinter

        root = tkinter.Tk()
        root.withdraw()
        text = root.clipboard_get()
        root.destroy()
        return str(text or "")
    except Exception:
        import subprocess

        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return out.stdout or ""


def main() -> int:
    parser = argparse.ArgumentParser(description="诊断剪贴板库存 vs 软件库存")
    parser.add_argument("--type", type=int, default=11399, help="要核对的 type_id（默认 11399 莫尔石）")
    parser.add_argument("--name", default="莫尔石", help="该 type_id 的名称（仅用于显示）")
    args = parser.parse_args()

    # 1) 剪贴板原文
    raw = read_clipboard()
    print(f"=== 剪贴板长度 {len(raw)} 字符，非空行 {len([x for x in raw.splitlines() if x.strip()])} 行 ===")
    if not raw.strip():
        print("!! 剪贴板是空的 —— 先在游戏里全选复制再跑本脚本")
        return 1

    # 2) 软件解析（与 App 走同一条代码路径，但用只读副本的库，绝不碰真库）
    tmp = os.path.join(tempfile.gettempdir(), "eve_clip_check")
    os.makedirs(os.path.join(tmp, "database"), exist_ok=True)
    for name in ("reference.db", "user.db"):
        src = os.path.join(ROOT, "database", name)
        if os.path.exists(src):
            import shutil

            shutil.copy2(src, os.path.join(tmp, "database", name))
            for suffix in ("-wal", "-shm"):
                if os.path.exists(src + suffix):
                    shutil.copy2(src + suffix, os.path.join(tmp, "database", name + suffix))
    os.environ["EVE_ASSISTANT_APP_ROOT"] = tmp

    from services.inventory_clipboard_service import parse_clipboard

    parsed, filtered = parse_clipboard(raw)
    print(f"=== 软件从剪贴板解析出 {len(parsed)} 行材料（过滤掉 {filtered} 行蓝图）===")

    hit = [r for r in parsed if int(r.get("type_id") or 0) == args.type]
    print(f"\n--- 本脚本关心的物品：{args.name} (type_id={args.type}) ---")
    if hit:
        for r in hit:
            print(f"  剪贴板里解析到：{r.get('raw_name')} → type_id={r.get('type_id')} qty={r.get('qty')}")
    else:
        print("  !! 剪贴板里**没有**解析出这个物品")
        same_name = [r for r in parsed if args.name in str(r.get("raw_name") or "")]
        if same_name:
            print("  但名字里含它的行有：")
            for r in same_name:
                print(f"    {r.get('raw_name')} → type_id={r.get('type_id')} qty={r.get('qty')}")

    # 3) 真库（只读）里现在的数量
    uc = sqlite3.connect(f"file:{os.path.join(ROOT, 'database', 'user.db')}?mode=ro", uri=True)
    rows = uc.execute(
        "SELECT hangar_id, quantity, created_at FROM inventory_items WHERE type_id=?", (args.type,)
    ).fetchall()
    print("\n--- 软件数据库里现在记的数量 ---")
    if rows:
        for hid, qty, ts in rows:
            print(f"  机库 {hid}: {qty:,}（最后写入 {ts}）")
    else:
        print("  （数据库里没有这个物品的行）")

    total = sum(q for _h, q, _t in rows)
    clip = sum(int(r.get("qty") or 0) for r in hit)
    print(f"\n=== 结论：剪贴板 {clip:,} vs 软件库 {total:,} ===")
    if clip == total:
        print("  两者一致 → 你上次粘贴的就是这个数；若游戏里显示的不是它，问题在「游戏复制的清单」本身")
    else:
        print("  两者不一致 → 软件库存是旧的，重新做一次「库存修正（全量粘贴）」即可对齐")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
