"""build_release.organize_release — 发行包内容白名单（P2-1 回归）

背景：原实现整目录 copytree `data/`，且 `database/` 缺失时静默跳过 ——
干净检出上打出的包 `database/` 是空目录、`data/` 里混着构建机当时存在的 SDE 原料，
而 README 向用户承诺「发行包已内置静态数据」。
"""

from pathlib import Path

import pytest

import build_release as br

pytestmark = pytest.mark.fast


def _make_src(tmp_path: Path) -> Path:
    """造一个「仓库根」：含模板库、白名单文件，以及不该入包的东西"""
    (tmp_path / "database").mkdir()
    (tmp_path / "database" / "reference.db").write_bytes(b"ref")
    (tmp_path / "database" / "blueprint.db").write_bytes(b"bp")
    (tmp_path / "database" / "user.db").write_bytes(b"user")  # 运行数据 → 不入包
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
