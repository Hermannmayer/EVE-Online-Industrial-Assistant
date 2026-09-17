#!/usr/bin/env python
"""
new_worktree.py — 建 worktree 并把本地运行数据一起带过去

用法：
    python scripts/new_worktree.py <名字>                 # 从 main 建 worktree-<名字>
    python scripts/new_worktree.py <名字> --base <ref>    # 指定基点（默认 main）
    python scripts/new_worktree.py <名字> --copy-data     # data/ 也用复制（默认硬链接）

为什么需要它：
    `data/` 约 700MB 的 SDE 导入产物（universe_data.json / typeIDs.* / sde.zip）和
    `database/` 约 65MB 的库文件都被 .gitignore 排除，新 worktree 里一律不存在，
    不处理就得重新拉一遍 SDE。

做法：
    1. git worktree add .claude/worktrees/<名字> -b worktree-<名字> <base>
    2. data/ 里未被 git 跟踪的条目 → 硬链接回主工作区（目录用 junction）
       —— 只读缓存，复制 700MB 纯属浪费；app 若整文件重写，链接自动退化成私有副本
    3. database/ → 整目录复制一份
       —— 刻意不共享：SQLite 的 -wal/-shm 按目录走，只硬链接库文件会让两个进程
          各持一套 WAL 写同一个库，存在损坏风险。65MB 复制得起。
    4. 打印后续步骤（uv sync --dev）
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKTREES_DIRNAME = ".claude/worktrees"
IS_WINDOWS = os.name == "nt"


def run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    # errors="replace"：mklink 在中文 Windows 上吐 GBK，父进程若开了 UTF-8 模式会解码失败
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True, errors="replace")


def main_worktree(repo: Path) -> Path:
    """主工作区路径（worktree list 的第一条）。脚本可能在任一 worktree 里被调用。"""
    out = run(["git", "worktree", "list", "--porcelain"], cwd=repo).stdout
    for line in out.splitlines():
        if line.startswith("worktree "):
            return Path(line[len("worktree ") :].strip())
    raise SystemExit("❌ 找不到主工作区（git worktree list 无输出）")


def link(src: Path, dst: Path) -> None:
    """把 dst 指向 src：目录用 junction，文件用硬链接（Windows 下均不需要管理员）。"""
    if IS_WINDOWS:
        flag = "/J" if src.is_dir() else "/H"
        run(["cmd", "/c", "mklink", flag, str(dst), str(src)])
    else:
        os.symlink(src, dst)


def tracked_under(path: str) -> set[str]:
    out = run(["git", "ls-files", "-z", path]).stdout
    return {p for p in out.split("\0") if p}


def is_ignored(path: str) -> bool:
    """git check-ignore -q：命中忽略规则返回 0。"""
    return run(["git", "check-ignore", "-q", path], check=False).returncode == 0


def setup_data(src_root: Path, dst_root: Path, copy_data: bool) -> tuple[int, float]:
    """data/ —— 跟踪文件由 git 落地，未跟踪条目按需链接或复制。"""
    (dst_root / "data").mkdir(parents=True, exist_ok=True)
    tracked = tracked_under("data")
    count, size = 0, 0.0
    for src in sorted((src_root / "data").iterdir()):
        rel = f"data/{src.name}"
        if rel in tracked or not is_ignored(rel):
            continue  # 跟踪文件、未忽略文件由 checkout 负责
        dst = dst_root / rel
        if dst.exists():
            continue
        if copy_data:
            if src.is_dir():
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
        else:
            link(src, dst)
        count += 1
        size += sum(f.stat().st_size for f in src.rglob("*") if f.is_file()) if src.is_dir() else src.stat().st_size
    return count, size / 1024 / 1024


def setup_database(src_root: Path, dst_root: Path) -> float:
    """database/ —— 整目录复制。-wal/-shm 不复制：那是运行时日志，拷过来的快照反而不一致。"""
    src, dst = src_root / "database", dst_root / "database"
    if not src.is_dir():
        dst.mkdir(parents=True, exist_ok=True)
        return 0.0
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("*-wal", "*-shm"))
    return sum(f.stat().st_size for f in dst.rglob("*") if f.is_file()) / 1024 / 1024


def main() -> int:
    ap = argparse.ArgumentParser(description="建 worktree 并带上本地运行数据")
    ap.add_argument("name", help="worktree 名（目录 .claude/worktrees/<name>，分支 worktree-<name>）")
    ap.add_argument("--base", default="main", help="基点 ref（默认 main）")
    ap.add_argument("--copy-data", action="store_true", help="data/ 也用复制而非硬链接")
    args = ap.parse_args()

    root = main_worktree(REPO_ROOT)
    target = root / WORKTREES_DIRNAME / args.name
    branch = f"worktree-{args.name}"

    if target.exists():
        print(f"❌ 目标已存在：{target}")
        return 1

    print(f"[1/4] 建 worktree：{target}（分支 {branch}，基点 {args.base}）")
    target.parent.mkdir(parents=True, exist_ok=True)
    r = run(["git", "worktree", "add", "-b", branch, str(target), args.base], cwd=root, check=False)
    if r.returncode != 0:
        print(r.stderr.strip())
        return 1

    print(f"[2/4] data/ 未跟踪条目 → {'复制' if args.copy_data else '硬链接回主工作区'}")
    n_data, mb_data = setup_data(root, target, args.copy_data)

    print("[3/4] database/ → 整目录复制")
    mb_db = setup_database(root, target)

    print(f"[4/4] 完成：data/ {n_data} 项（{mb_data:.0f} MB）、database/（{mb_db:.0f} MB）")
    print(f"\n下一步：\n    cd {target}\n    uv sync --dev")
    return 0


if __name__ == "__main__":
    sys.exit(main())
