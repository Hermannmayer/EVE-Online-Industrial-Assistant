"""用户数据的本地备份与导出。

**只备份 `user.db`** —— 那才是用户自己的东西（生产计划 / 机库 / 库存 / 蓝图绑定 /
ESI 令牌 / 快照台账）。`reference.db` 与 `blueprint.db` 是可重下发的 SDE 缓存、
`market.db` 是行情缓存，重建即可，备份它们只是白占空间（单个几百 MB）。

**备份目录单独一层** `<库目录>/backups/user/`，与 `schema_migrations` 的「迁移前快照」
（`<库目录>/backups/<name>-<ts>.db`，保留 5 份）**分开**：两边的保留策略各管各的，
否则用户设「保留 3 份」会把迁移快照一起清掉、迁移回滚就没得退了。

两个调用方（`services/` 里新建模块的门槛，见 CLAUDE.md「克制条款」第 1 条）：
- `ui_qml/bridge/settings_bridge.py` —— 设置页的「立即备份 / 导出」
- `ui_qml/shell_window.py` —— 启动时「每天一次」的自动备份
"""

from __future__ import annotations

import glob
import os
import shutil
import sqlite3
from datetime import date, datetime

from core.logger import log
from services.user_settings import BACKUP_KEEP_DEFAULT

__all__ = [
    "backup_dir",
    "backup_user_db",
    "export_user_db",
    "list_backups",
    "maybe_daily_backup",
    "restore_user_db",
    "user_db_path",
]


def user_db_path() -> str:
    """user.db 路径 —— **调用时**读，不 import 模块常量。

    ⚠️ `tests/conftest.py` 的 `temp_db` / `db_manager` 只替换
    `services.database_manager.DB_PATH_MAP`，**不替换** `core.paths.USR_DB_PATH`。
    直接 `from core.paths import USR_DB_PATH` 会让测试把备份写进用户**真实**的
    `database/backups/`（改一次测试就多几份垃圾，还可能碰到正在运行的应用实例）。
    """
    from services.database_manager import DB_PATH_MAP

    return str(DB_PATH_MAP["user"])


def backup_dir() -> str:
    """本次要写入的备份目录（不存在则创建）。"""
    path = os.path.join(os.path.dirname(user_db_path()), "backups", "user")
    os.makedirs(path, exist_ok=True)
    return path


def list_backups() -> list[str]:
    """已有备份路径，**新的在前**（设置页显示份数用）。"""
    try:
        return sorted(glob.glob(os.path.join(backup_dir(), "user-*.db")), key=os.path.getmtime, reverse=True)
    except OSError:
        return []


def _cleanup(keep: int) -> int:
    """只保留最近 keep 份，返回删掉的份数。删不动仅告警，不阻断备份。"""
    removed = 0
    for old in list_backups()[max(keep, 0) :]:
        try:
            os.remove(old)
            removed += 1
        except OSError:
            log.warning("清理旧备份失败: %s", old, exc_info=True)
    return removed


def backup_user_db(*, keep: int = BACKUP_KEEP_DEFAULT) -> str | None:
    """``VACUUM INTO`` 一份 user.db 的一致快照，返回备份路径；失败返回 None。

    用 `VACUUM INTO` 而不是复制文件：user.db 跑在 WAL 模式下，直接拷 .db 会漏掉
    `-wal` 里还没落盘的事务（拷出来是个缺数据的库）；`VACUUM INTO` 由 SQLite 保证
    一致性，且顺带把碎片压掉。
    """
    src = user_db_path()
    if not os.path.exists(src):
        log.warning("备份用户数据：%s 不存在，跳过", src)
        return None
    try:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = os.path.join(backup_dir(), f"user-{ts}.db")
        # ⚠️ 秒级时间戳会撞车（同一秒内连点两次「立即备份」，或走到 `restore_user_db`
        # 的「先留退路再还原」），撞车时**绝不能覆盖**：还原流程会先把「现在这份」
        # 备份下来，覆盖掉的就是它自己刚建的那一份 —— 还原于是变成拿坏库盖坏库。
        # 撞了就加序号另起一个名字（`list_backups` 的 `user-*.db` 一样匹配得到）。
        if os.path.exists(target):
            for i in range(1, 100):
                alt = os.path.join(backup_dir(), f"user-{ts}-{i}.db")
                if not os.path.exists(alt):
                    target = alt
                    break
        conn = sqlite3.connect(src)
        try:
            conn.execute("VACUUM INTO ?", (target,))
        finally:
            conn.close()
        dropped = _cleanup(keep)
        log.info("已备份用户数据 → %s（清理 %d 份旧备份）", target, dropped)
        return target
    except Exception:
        # sqlite3.Error + OSError：库被占用 / 磁盘满 / 权限不足 —— 备份失败不该拖垮调用方
        log.exception("备份用户数据失败")
        return None


def maybe_daily_backup(*, keep: int = BACKUP_KEEP_DEFAULT, today: str | None = None) -> str | None:
    """「每天最多一次」的自动备份；今天已经备过就返回 None（不重复占空间）。

    `today` 只为测试注入，正常运行走系统日期。
    """
    from services import user_settings

    day = today or date.today().isoformat()
    if user_settings.get_last_backup_date() == day:
        return None
    path = backup_user_db(keep=keep)
    if path:
        # 备成功才记日期：失败（库被占用等）留到下次启动再试，而不是「今天已经试过了」
        user_settings.set_last_backup_date(day)
    return path


def export_user_db(dest_path: str) -> str | None:
    """把 user.db 另存到用户指定位置（同样走 `VACUUM INTO`，保证一致）。

    目标已存在就覆盖 —— 用户在保存框里确认过覆盖了。
    """
    src = user_db_path()
    if not os.path.exists(src):
        return None
    try:
        dest = os.path.abspath(dest_path)
        parent = os.path.dirname(dest)
        if parent:
            os.makedirs(parent, exist_ok=True)
        if os.path.exists(dest):
            os.unlink(dest)
        conn = sqlite3.connect(src)
        try:
            conn.execute("VACUUM INTO ?", (dest,))
        finally:
            conn.close()
        log.info("已导出用户数据 → %s", dest)
        return dest
    except Exception:
        log.exception("导出用户数据失败：%s", dest_path)
        return None


def restore_user_db(backup_path: str, *, keep: int = BACKUP_KEEP_DEFAULT) -> bool:
    """用 ``backup_path`` 覆盖当前 user.db。成功返回 True。

    **还原前先把「现在这个库」也备份一份** —— 否则选错备份就成了单向不可逆操作
    （用户点错一次就再也回不到还原前的状态）。

    还原成功后**必须重启应用**：外壳/页面/桥里全是旧库的数据与缓存，不重启会看到
    「还原了但界面没变」，随后任何一次写回都可能把旧数据盖到新库上。

    ⚠️ 动文件之前必须 `close_all()`：user.db 跑在 WAL 模式，还有连接活着时覆盖 .db
    会得到损坏的库；而残留的 `-wal` 会在下次打开时把**旧事务重放到新库上** ——
    表现成「还原没生效」甚至「数据被搅乱」。
    """
    source = str(backup_path)
    if not os.path.exists(source):
        log.warning("还原失败：备份不存在 %s", source)
        return False
    try:
        # 先确认这是一份能打开的 sqlite 库：拿坏文件覆盖上去等于把用户数据直接毁掉
        probe = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
        try:
            probe.execute("PRAGMA schema_version").fetchone()
        finally:
            probe.close()

        # 留退路：把「现在这个库」也备一份（保留策略与常规备份同一套）
        backup_user_db(keep=keep)

        # ⚠️ 先把连接关掉。不关就会踩到 **WAL**：旧连接里未 checkpoint 的事务在下次读时
        # 会盖过刚写进去的数据 —— 实测还原「成功」了、读出来却仍是还原前的值。
        # 真实应用里 user 库只有 `get_db()` 这一个单例，这一句就够了；测试里的独立
        # `DatabaseManager` 实例由调用方自己先关（见 `tests/test_db_backup.py`）。
        from services.database_manager import get_db

        get_db().close_all()

        # 连接关掉之后，把目标库连同它的 `-wal` / `-shm` 一起删掉再拷 ——
        # **必须删 `-wal`**：它是「比主库更新的已提交事务」，留着的话 SQLite 下次打开
        # 会把旧事务重放到刚拷进来的备份上（实测还原「成功」了、读出来仍是旧值）。
        target = user_db_path()
        for path in (target, target + "-wal", target + "-shm"):
            if os.path.exists(path):
                os.remove(path)
        shutil.copyfile(source, target)

        log.info("已从备份还原用户数据：%s → %s", source, target)
        return True
    except Exception:
        # sqlite3.Error / OSError：备份损坏、库被占用、磁盘满、权限不足
        log.exception("还原用户数据失败：%s", source)
        return False
