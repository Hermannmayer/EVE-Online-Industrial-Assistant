#!/usr/bin/env python
"""
new_worktree.py — 建 worktree，并把本地运行数据接过来（默认与主工作区活共享）

用法：
    python scripts/new_worktree.py <名字>               # 从 main 建 worktree-<名字>，数据活共享主工作区
    python scripts/new_worktree.py <名字> --base <ref>  # 指定基点（默认 main）
    python scripts/new_worktree.py <名字> --isolated    # 数据全复制不共享（测 schema 迁移/破坏性实验用）
    python scripts/new_worktree.py attach [路径]        # 给已存在的 worktree 补共享（默认当前目录）
    python scripts/new_worktree.py attach --relink      # 把已分叉的 data/ 条目挪开并重新链接回主工作区
    python scripts/new_worktree.py detach [路径]        # 摘掉指向主工作区的链接（删 worktree 前必跑）
    python scripts/new_worktree.py status               # 看各 worktree 的数据共享状态
    python scripts/new_worktree.py hook-create          # Claude Code WorktreeCreate 钩子入口（stdin JSON）
    python scripts/new_worktree.py hook-remove          # Claude Code WorktreeRemove 钩子入口（stdin JSON）

为什么需要它：
    `data/` 约 700MB 的 SDE 导入产物（universe_data.json / typeIDs.* / sde.zip）和
    `database/` 约 65MB 的库文件都被 .gitignore 排除，新 worktree 里一律不存在。
    而 `database/user.db` 装的是挂机、库存、生产计划、技能这类**不可重建的生产数据** ——
    复制一份到 worktree，两边立刻就分叉，编辑过的东西要重新录一遍。

做法（默认：活共享）：
    1. git worktree add .claude/worktrees/<名字> -b worktree-<名字> <基点>
    2. data/ 里未被 git 跟踪的条目 → 硬链接回主工作区（目录用 junction）
       —— 主工作区写的是这几个 JSON（原地写），硬链接两边同步；大缓存只读，复制纯浪费
    3. database/ → **junction 指向主工作区**，两边共用同一份 user.db
       —— 这是与「复制一份」的关键差别：数据永远一致，不用同步、不会分叉。
          SQLite 侧是正常的多进程 WAL 用法（各连接 PRAGMA journal_mode=WAL + busy_timeout=30s），
          同一目录同一套 -wal/-shm，不会出现「两个进程各持一套 WAL 写同一个库」的损坏场景。
    4. 打印后续步骤（uv sync --dev）

**活共享的代价**：worktree 里跑 app / 跑脚本，写的就是主工作区那套生产数据。
要测 schema 迁移或破坏性操作，用 `--isolated` 建独立副本（或 `python dev.py --fresh`）。

⚠️ 删 worktree 之前必须先 `detach`（Claude Code 建的 worktree 走 WorktreeRemove 钩子自动摘）：
   Windows 递归删除可能顺着 junction/data/caches 把主工作区的数据一起删掉。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKTREES_DIRNAME = ".claude/worktrees"
IS_WINDOWS = os.name == "nt"
DB_COPY_IGNORE = shutil.ignore_patterns("*-wal", "*-shm")
# 只有 user.db 不可重建；ref/mkt/bp 是缓存库，缺了直接重导（见 CLAUDE.md 克制条款第 3 条）
PRECIOUS_DB = "user.db"

SUBCOMMANDS = {"attach", "detach", "status", "hook-create", "hook-remove"}


def log(msg: str) -> None:
    """进度一律走 stderr —— 钩子模式下 stdout 只留 worktree 路径。"""
    print(msg, file=sys.stderr)


def run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    # errors="replace"：mklink 在中文 Windows 上吐 GBK，父进程若开了 UTF-8 模式会解码失败
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True, errors="replace")


def path_exists(p: Path) -> bool:
    """断掉的 junction 在 Path.exists() 上返回 False，这里要的是「有条目在」。"""
    return p.exists() or is_reparse(p)


def is_reparse(p: Path) -> bool:
    """junction / 符号链接。Windows 上 os.path.islink() 对 junction 返回 False，只能看 reparse tag。"""
    try:
        return bool(getattr(os.lstat(p), "st_reparse_tag", 0))
    except OSError:
        return False


def is_link_entry(p: Path) -> bool:
    """指向别处的条目：junction/符号链接，或硬链接（文件 nlink>1；目录的 nlink 是子目录数，不能看）。"""
    try:
        st = os.lstat(p)
    except OSError:
        return False
    if getattr(st, "st_reparse_tag", 0):
        return True
    return not p.is_dir() and st.st_nlink > 1


def unlink_entry(p: Path) -> None:
    """只断开链接本身，绝不递归进目标：junction 用 rmdir，硬链接/符号链接用 unlink。"""
    if is_reparse(p) and p.is_dir():
        os.rmdir(p)
    else:
        os.unlink(p)


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


def setup_data(src_root: Path, dst_root: Path, copy_data: bool, relink: bool = False) -> tuple[int, float, list[str]]:
    """data/ —— 跟踪文件由 git 落地，未跟踪条目按需链接或复制。

    返回 (处理条目数, MB, 已分叉条目)。分叉 = worktree 里已是独立副本（非链接）：
    过去被复制过，或链接被原子写（sde_cache 的 临时文件+os.replace）打断。
    默认只报告不覆盖；relink=True 时把那份挪到 .claude/relinked-<时间>/ 再链接回
    主工作区（同盘 rename，瞬间完成且不丢数据 —— 缓存被原子写换掉是常态，会复发）。
    """
    (dst_root / "data").mkdir(parents=True, exist_ok=True)
    tracked = tracked_under("data")
    kept_dir = dst_root / ".claude" / f"relinked-{time.strftime('%Y%m%d-%H%M%S')}"
    count, size, diverged = 0, 0.0, []
    for src in sorted((src_root / "data").iterdir()):
        rel = f"data/{src.name}"
        if rel in tracked or not is_ignored(rel):
            continue  # 跟踪文件、未忽略文件由 checkout 负责
        dst = dst_root / rel
        if path_exists(dst):
            if copy_data or is_link_entry(dst):
                continue
            diverged.append(rel)
            if not relink:
                continue
            kept = kept_dir / rel
            kept.parent.mkdir(parents=True, exist_ok=True)
            dst.rename(kept)  # 同盘 rename：不复制、不丢
        if copy_data:
            if src.is_dir():
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
        else:
            link(src, dst)
        count += 1
        size += sum(f.stat().st_size for f in src.rglob("*") if f.is_file()) if src.is_dir() else src.stat().st_size
    if diverged and relink:
        log(f"  分叉的 {len(diverged)} 项已挪到 {kept_dir}（确认无误可自行删除）")
        diverged = []
    return count, size / 1024 / 1024, diverged


def setup_database(src_root: Path, dst_root: Path, isolate: bool) -> str:
    """database/ —— 默认 junction 到主工作区（同一份 user.db），--isolated 才整目录复制。"""
    src, dst = src_root / "database", dst_root / "database"
    src.mkdir(parents=True, exist_ok=True)
    if isolate:
        shutil.copytree(src, dst, ignore=DB_COPY_IGNORE)
        mb = sum(f.stat().st_size for f in dst.rglob("*") if f.is_file()) / 1024 / 1024
        return f"独立复制（{mb:.0f} MB，与主工作区分叉）"
    link(src, dst)
    return "junction → 主工作区（与 main 同一份）"


def backup_user_db(main_db: Path, wt_db: Path, label: str) -> str | None:
    """worktree 里已有的 user.db 与主工作区不同 → 存一份到主工作区 database/backups/。"""
    src, dst = wt_db / PRECIOUS_DB, main_db / PRECIOUS_DB
    if not src.is_file():
        return None
    if dst.is_file() and _md5(src) == _md5(dst):
        return None  # 本来就一样，没什么可留的
    backup_dir = main_db / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"wt-{label}-{time.strftime('%Y%m%d-%H%M%S')}-{PRECIOUS_DB}"
    shutil.copy2(src, target)
    return str(target)


def _md5(p: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.md5()
    with open(p, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def attach(wt: Path, isolated: bool = False, relink: bool = False) -> int:
    """把已存在的 worktree 接到主工作区的数据上（新建时走 create，这里是补做/修）。"""
    root = main_worktree(REPO_ROOT)
    if wt.resolve() == root.resolve():
        log("❌ 这是主工作区本身，不用 attach")
        return 1
    if not (wt / ".git").exists():
        log(f"❌ 不是 git worktree：{wt}")
        return 1

    n_data, mb_data, diverged = setup_data(root, wt, isolated, relink)
    log(f"data/：新接 {n_data} 项（{mb_data:.0f} MB），分叉 {len(diverged)} 项")
    for rel in diverged:
        log(f"  ⚠️ {rel} 是 worktree 自己的副本，未覆盖 —— 想统一到 main：{sys.argv[0]} attach --relink")

    src_db, wt_db = root / "database", wt / "database"
    if is_reparse(wt_db):
        log("database/：已是 junction（与 main 同一份）")
    elif wt_db.is_dir():
        if isolated:
            log("database/：--isolated，保留 worktree 自己的副本")
        else:
            saved = backup_user_db(src_db, wt_db, wt.name)
            if saved:
                log(f"database/：worktree 原有 user.db 与 main 不同 → 已备份到 {saved}")
            shutil.rmtree(wt_db)
            log(f"database/：{setup_database(root, wt, False)}")
    else:
        log(f"database/：{setup_database(root, wt, isolated)}")
    return 0


def detach(wt: Path) -> int:
    """摘掉所有指向主工作区的链接 —— 删 worktree 前必跑，否则递归删除会删穿主工作区。

    摘完这个 worktree 就没有 data/ 缓存与 database/ 了（app 会当全新环境初始化），
    它是给「即将删除」用的，不是共享开关。
    """
    dropped = []
    data_dir = wt / "data"
    if data_dir.is_dir():
        for entry in sorted(data_dir.iterdir()):
            if is_link_entry(entry):
                unlink_entry(entry)
                dropped.append(f"data/{entry.name}")
    db_dir = wt / "database"
    if is_reparse(db_dir):
        unlink_entry(db_dir)
        dropped.append("database/")
    log(f"已摘链接 {len(dropped)} 项：{', '.join(dropped) if dropped else '（无）'}")
    return 0


def status() -> int:
    """列出所有 worktree 的数据共享状态。"""
    root = main_worktree(REPO_ROOT)
    out = run(["git", "worktree", "list", "--porcelain"], cwd=root).stdout
    for block in out.split("\n\n"):
        if not block.strip():
            continue
        wt = next((Path(ln[9:]) for ln in block.splitlines() if ln.startswith("worktree ")), None)
        if wt is None:
            continue
        if wt.resolve() == root.resolve():
            log(f"{wt}\n    主工作区（数据源头，其他 worktree 指向这里）")
            continue
        db = wt / "database"
        if is_reparse(db):
            db_desc = "junction → main ✅"
        elif db.is_dir():
            db_desc = "独立副本 ⚠️"
        else:
            db_desc = "缺失 ⚠️"
        linked = diverged = 0
        data_dir = wt / "data"
        if data_dir.is_dir():
            tracked = tracked_under("data")
            for entry in data_dir.iterdir():
                if f"data/{entry.name}" in tracked:
                    continue
                if is_link_entry(entry):
                    linked += 1
                elif (root / "data" / entry.name).exists():
                    diverged += 1  # 主工作区也有、却是独立副本 —— 这才是分叉
        log(f"{wt}\n    database/ {db_desc}｜data/ 链接 {linked} 项、分叉 {diverged} 项")
    return 0


def create(name: str, base: str, isolated: bool) -> int:
    root = main_worktree(REPO_ROOT)
    target = root / WORKTREES_DIRNAME / name
    branch = f"worktree-{name}"

    if path_exists(target):
        log(f"❌ 目标已存在：{target}")
        return 1

    log(f"[1/4] 建 worktree：{target}（分支 {branch}，基点 {base}）")
    target.parent.mkdir(parents=True, exist_ok=True)
    r = run(["git", "worktree", "add", "-b", branch, str(target), base], cwd=root, check=False)
    if r.returncode != 0:
        log(r.stderr.strip())
        return 1

    log(f"[2/4] data/ 未跟踪条目 → {'复制' if isolated else '硬链接回主工作区'}")
    n_data, mb_data, _ = setup_data(root, target, isolated)

    log("[3/4] database/ →")
    log(f"      {setup_database(root, target, isolated)}")

    log(f"[4/4] 完成：data/ {n_data} 项（{mb_data:.0f} MB）")
    log(f"\n下一步：\n    cd {target}\n    uv sync --dev")
    print(str(target))  # stdout 最后一行 = worktree 路径（钩子靠这行取值）
    return 0


def hook_create() -> int:
    """WorktreeCreate 钩子：stdin 收 {name, cwd}，stdout 最后一行回 worktree 路径。"""
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        log(f"❌ 钩子输入不是 JSON：{e}")
        return 1
    name = str(payload.get("name") or "").strip()
    if not name:
        log("❌ 钩子输入缺 name")
        return 1
    return create(name, "main", False)


def hook_remove() -> int:
    """WorktreeRemove 钩子：先摘链接再删，避免删穿主工作区。"""
    try:
        payload = json.load(sys.stdin)
        wt = Path(payload["worktree_path"])
    except (json.JSONDecodeError, KeyError) as e:
        log(f"❌ 钩子输入无效：{e!r}")
        return 1
    root = main_worktree(REPO_ROOT)
    detach(wt)
    run(["git", "-C", str(root), "worktree", "remove", "--force", str(wt)], check=False)
    if path_exists(wt):
        try:
            os.rmdir(wt)
        except OSError:
            if any(wt.iterdir()):
                log(f"❌ 删除失败，目录仍有内容：{wt}")
                return 1
            # Windows 不允许删除「正被当作进程工作目录」的目录：链接已摘、内容已清空，
            # 只剩空壳不算失败，会话退出后 rmdir 掉即可。
            log(f"⚠️ {wt} 只剩空壳（内容已清空，会话退出后可 rmdir 删掉）")
    run(["git", "-C", str(root), "worktree", "prune"], check=False)
    return 0


def main() -> int:
    argv = sys.argv[1:]
    if argv and argv[0] in SUBCOMMANDS:
        cmd, argv = argv[0], argv[1:]
        if cmd == "hook-create":
            return hook_create()
        if cmd == "hook-remove":
            return hook_remove()
        if cmd == "status":
            return status()
        ap = argparse.ArgumentParser(prog=f"new_worktree.py {cmd}", description=f"{cmd} worktree 数据链接")
        ap.add_argument("path", nargs="?", default=".", help="worktree 路径（默认当前目录）")
        if cmd == "attach":
            ap.add_argument("--relink", action="store_true", help="把已分叉的条目挪开并重新链接回主工作区")
        args = ap.parse_args(argv)
        path = Path(args.path).resolve()
        return attach(path, relink=args.relink) if cmd == "attach" else detach(path)

    ap = argparse.ArgumentParser(description="建 worktree 并带上本地运行数据")
    ap.add_argument("name", help="worktree 名（目录 .claude/worktrees/<name>，分支 worktree-<name>）")
    ap.add_argument("--base", default="main", help="基点 ref（默认 main）")
    ap.add_argument("--isolated", action="store_true", help="数据全复制不共享（测 schema 迁移/破坏性实验用）")
    args = ap.parse_args(argv)
    return create(args.name, args.base, args.isolated)


if __name__ == "__main__":
    sys.exit(main())
