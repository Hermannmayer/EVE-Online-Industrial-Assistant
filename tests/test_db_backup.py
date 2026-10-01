"""用户数据备份/导出（`services/db_backup`）的护栏。

备份是**不可逆操作的对立面**：它唯一的用途是在用户数据出问题时能回退。所以这里
钉死三件事 —— 备份出来的是**能打开、内容完整**的库；保留策略**只删自己的目录**；
「每天一次」不会变成「每次启动一次」。
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from services import db_backup


def _seed(db_manager) -> str:
    with db_manager.connect("user") as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY, v TEXT)")
        conn.execute("INSERT INTO t (v) VALUES ('hello')")
    return db_backup.user_db_path()


def test_backup_writes_a_consistent_copy_in_its_own_directory(db_manager):
    """备份落到 `<库目录>/backups/user/`，且是可打开、内容完整的库。

    特意与 `schema_migrations` 的迁移前快照（`backups/<name>-<ts>.db`）**分一层目录**：
    两边的保留策略各管各的，否则用户设「保留 3 份」会把迁移快照一起清掉，
    迁移失败时就退不回去了。
    """
    src = _seed(db_manager)
    path = db_backup.backup_user_db()

    assert path is not None and os.path.exists(path)
    assert os.path.dirname(path) == os.path.join(os.path.dirname(src), "backups", "user")

    conn = sqlite3.connect(path)
    try:
        assert conn.execute("SELECT v FROM t").fetchone()[0] == "hello"
    finally:
        conn.close()


def test_backup_keeps_only_the_requested_number(db_manager):
    """保留策略：只留最近 keep 份。"""
    _seed(db_manager)
    # 手工造「更早的备份」并把 mtime 压到 1970 年代（真实备份是秒级时间戳，
    # 同一秒连备两次会撞同名文件，没法在一条用例里造出多份真备份）
    d = db_backup.backup_dir()
    for i in range(4):
        p = Path(d) / f"user-2020010{i}-000000.db"
        p.write_text("")
        os.utime(p, (1000 + i, 1000 + i))

    fresh = db_backup.backup_user_db(keep=2)
    assert fresh is not None

    left = db_backup.list_backups()
    assert len(left) == 2, left
    assert left[0] == fresh, "最新的那份必须留着"


def test_daily_backup_runs_at_most_once_per_day(db_manager):
    """「每天一次」：同一天第二次调用不再备份（否则每次启动都堆一份）。"""
    _seed(db_manager)

    assert db_backup.maybe_daily_backup(today="2026-09-28") is not None
    assert db_backup.maybe_daily_backup(today="2026-09-28") is None, "同一天不该备第二次"
    assert db_backup.maybe_daily_backup(today="2026-09-29") is not None, "换一天要照常备"


def test_export_copies_to_the_chosen_path(tmp_path, db_manager):
    """导出到用户指定路径（保存框已确认过覆盖），内容同样完整。"""
    _seed(db_manager)
    dest = tmp_path / "out" / "my-user-data.db"

    assert db_backup.export_user_db(str(dest)) == str(dest)

    conn = sqlite3.connect(str(dest))
    try:
        assert conn.execute("SELECT v FROM t").fetchone()[0] == "hello"
    finally:
        conn.close()


def test_restore_writes_the_backup_back_and_keeps_a_way_out(db_manager):
    """还原要把备份内容写回 user.db，并且**先把还原前那份也存下来**。

    回归背景（2026-09-28，用户要求）：「只能备份不能还原」等于只占空间。而还原是
    **覆盖用户数据**的动作 —— 选错一份备份就该还能退回来，所以还原前必须自动再备一份。
    """
    _seed(db_manager)
    good = db_backup.backup_user_db()
    assert good is not None

    # 模拟一次误操作：把库改得面目全非
    with db_manager.connect("user") as conn:
        conn.execute("DELETE FROM t")
        conn.execute("INSERT INTO t (v) VALUES ('bad')")
    # 还原前先关连接 —— 真实应用里 `restore_user_db` 自己会 `get_db().close_all()`，
    # 但这里是 fixture 的**独立** DatabaseManager 实例，它不会替我们关；
    # 留着未 checkpoint 的 WAL，还原写进去的新数据会被旧事务盖住。
    db_manager.close_all()

    assert db_backup.restore_user_db(good) is True

    conn = sqlite3.connect(db_backup.user_db_path())
    try:
        assert conn.execute("SELECT v FROM t").fetchone()[0] == "hello", "备份内容没写回去"
    finally:
        conn.close()

    # 还原前那一份（内容 'bad'）必须也在备份目录里 —— 否则还原错了没有退路
    assert len(db_backup.list_backups()) >= 2, db_backup.list_backups()


def test_restore_refuses_a_missing_or_broken_file(tmp_path, db_manager):
    """备份不存在 / 不是合法 sqlite → 拒绝还原，绝不拿坏文件覆盖用户数据。"""
    _seed(db_manager)

    assert db_backup.restore_user_db(str(tmp_path / "nope.db")) is False

    junk = tmp_path / "junk.db"
    junk.write_bytes(b"this is definitely not a sqlite database")
    assert db_backup.restore_user_db(str(junk)) is False

    # 库必须原样还在
    conn = sqlite3.connect(db_backup.user_db_path())
    try:
        assert conn.execute("SELECT v FROM t").fetchone()[0] == "hello"
    finally:
        conn.close()
