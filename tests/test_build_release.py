"""build_release.organize_release — 发行包内容白名单（P2-1 回归）

背景：原实现整目录 copytree `data/`，且 `database/` 缺失时静默跳过 ——
干净检出上打出的包 `database/` 是空目录、`data/` 里混着构建机当时存在的 SDE 原料，
而 README 向用户承诺「发行包已内置静态数据」。
"""

import sqlite3
from pathlib import Path

import pytest

import build_release as br

pytestmark = pytest.mark.fast


def _make_src(tmp_path: Path) -> Path:
    """造一个「仓库根」：含模板库、白名单文件，以及不该入包的东西"""
    (tmp_path / "database").mkdir()
    for name in ("reference.db", "blueprint.db", "user.db"):  # user.db 属运行数据 → 不入包
        sqlite3.connect(str(tmp_path / "database" / name)).close()
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "terminology.json").write_text("{}", encoding="utf-8")
    (tmp_path / "data" / "mfg_browser_settings.json").write_text("{}", encoding="utf-8")
    (tmp_path / "data" / "sde.zip").write_bytes(b"x" * 10)  # SDE 原料 → 不入包
    (tmp_path / "data" / "universe_data.json").write_text("{}", encoding="utf-8")
    (tmp_path / "data" / "caches").mkdir()
    (tmp_path / "README.md").write_text("readme", encoding="utf-8")
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "EVE商人助手.exe").write_bytes(b"exe")
    return tmp_path


def _patch_paths(monkeypatch, src: Path, tmp_path: Path) -> Path:
    release = tmp_path / "release"
    monkeypatch.setattr(br, "PROJECT_ROOT", str(src))
    monkeypatch.setattr(br, "DIST_DIR", str(src / "dist"))
    monkeypatch.setattr(br, "BUILD_EXE_DIR", str(src / "build_exe"))
    monkeypatch.setattr(br, "RELEASE_DIR", str(release))
    return release


def test_organize_release_copies_whitelist_only(tmp_path, monkeypatch):
    """产物只含白名单文件：模板库 2 个 + data 2 个 + exe/README"""
    src = _make_src(tmp_path)
    release = _patch_paths(monkeypatch, src, tmp_path)

    br.organize_release()

    assert sorted(p.name for p in (release / "database").iterdir()) == ["blueprint.db", "reference.db"]
    assert sorted(p.name for p in (release / "data").iterdir()) == [
        "mfg_browser_settings.json",
        "terminology.json",
    ]
    assert (release / "EVE商人助手.exe").exists()
    assert (release / "README.md").exists()


def test_organize_release_fails_without_template_db(tmp_path, monkeypatch):
    """模板库缺失必须让构建失败，而不是静默产出空 database/"""
    src = _make_src(tmp_path)
    (src / "database" / "reference.db").unlink()
    _patch_paths(monkeypatch, src, tmp_path)

    with pytest.raises(SystemExit):
        br.organize_release()


def test_organize_release_fails_without_whitelisted_data_file(tmp_path, monkeypatch):
    """白名单文件缺失同样失败（不产出「看起来正常」的残缺包）"""
    src = _make_src(tmp_path)
    (src / "data" / "terminology.json").unlink()
    _patch_paths(monkeypatch, src, tmp_path)

    with pytest.raises(SystemExit):
        br.organize_release()


def test_organize_release_checkpoints_wal_before_copy(tmp_path, monkeypatch):
    """源库还有未 checkpoint 的 WAL 时，产物里的库必须含这些写入

    实测：打包时源库存在 4.1MB 的 reference.db-wal。只复制主文件时，
    未合并进主库的写入会静默丢失 —— 用户拿到的是少了数据的模板库。
    """
    src = _make_src(tmp_path)
    db = src / "database" / "reference.db"
    db.unlink()
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE t (v INTEGER)")
    conn.execute("INSERT INTO t VALUES (1)")
    conn.commit()
    try:  # 连接保持打开：写入此刻还在 -wal 里，未 checkpoint 进主库
        release = _patch_paths(monkeypatch, src, tmp_path)
        br.organize_release()

        copied = sqlite3.connect(str(release / "database" / "reference.db"))
        try:
            assert copied.execute("SELECT count(*) FROM t").fetchone()[0] == 1
        finally:
            copied.close()
    finally:
        conn.close()
