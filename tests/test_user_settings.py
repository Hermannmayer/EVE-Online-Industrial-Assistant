"""用户设置集中读写测试 — services/user_settings.py

覆盖:
  - load_settings 缺文件返回 {}
  - save_settings read-modify-write 保留既有键
  - get/set default hangar id
  - set None → pop 键（对齐 TopToolbar -1 pop 语义）
"""

import json

import pytest

import services.user_settings as us


@pytest.fixture
def settings_path(tmp_path, monkeypatch):
    """将 SETTINGS_PATH 指向临时文件"""
    path = tmp_path / "settings.json"
    monkeypatch.setattr(us, "SETTINGS_PATH", str(path))
    return path


def test_load_settings_missing_returns_empty(settings_path):
    """settings.json 不存在 → 返回 {}"""
    assert us.load_settings() == {}


def test_load_settings_invalid_json_returns_empty(settings_path):
    """损坏的 settings.json → 返回 {} 而非抛异常"""
    settings_path.write_text("{ not valid json", encoding="utf-8")
    assert us.load_settings() == {}


def test_save_settings_preserves_existing_keys(settings_path):
    """save_settings 是 read-modify-write：只更新传入键，保留其它键"""
    us.save_settings({"default_mat_hangar_id": 5, "price_settings": {"hub": "Jita"}})
    us.save_settings({"default_deposit_hangar_id": 3})

    data = us.load_settings()
    assert data["default_mat_hangar_id"] == 5
    assert data["default_deposit_hangar_id"] == 3
    assert data["price_settings"] == {"hub": "Jita"}


def test_get_set_default_hangar_id(settings_path):
    """set 后 get 返回对应值，且已持久化到磁盘"""
    assert us.get_default_hangar_id("default_mat_hangar_id") is None

    us.set_default_hangar_id("default_mat_hangar_id", 7)
    assert us.get_default_hangar_id("default_mat_hangar_id") == 7
    on_disk = json.loads(settings_path.read_text(encoding="utf-8"))
    assert on_disk["default_mat_hangar_id"] == 7


def test_set_default_hangar_id_none_pops_key(settings_path):
    """set None → 从 settings.json 删除该键（对齐 TopToolbar -1 pop 语义）"""
    us.set_default_hangar_id("default_mat_hangar_id", 7)
    us.set_default_hangar_id("default_mat_hangar_id", None)

    data = us.load_settings()
    assert "default_mat_hangar_id" not in data
    assert us.get_default_hangar_id("default_mat_hangar_id") is None


def test_set_none_preserves_other_keys(settings_path):
    """pop 指定键时不影响其它设置"""
    us.set_default_hangar_id("default_mat_hangar_id", 7)
    us.save_settings({"other": "value"})
    us.set_default_hangar_id("default_mat_hangar_id", None)

    data = us.load_settings()
    assert "default_mat_hangar_id" not in data
    assert data.get("other") == "value"


# ────────────────────────────────────────────
#  settings 版本迁移
# ────────────────────────────────────────────


def test_load_migrates_missing_version_preserves_keys(settings_path):
    """无 settings_version 键的旧文件 → 升级到当前版本、原键保留、磁盘写回"""
    settings_path.write_text(json.dumps({"theme": "dark", "default_mat_hangar_id": 5}), encoding="utf-8")

    data = us.load_settings()

    assert data["settings_version"] == us.SETTINGS_SCHEMA_VERSION
    assert data["theme"] == "dark"
    assert data["default_mat_hangar_id"] == 5
    on_disk = json.loads(settings_path.read_text(encoding="utf-8"))
    assert on_disk["settings_version"] == us.SETTINGS_SCHEMA_VERSION
    assert on_disk["theme"] == "dark"


def test_load_current_version_does_not_rewrite(settings_path):
    """已是最新版本 → 读取不落盘（mtime 不变）"""
    settings_path.write_text(json.dumps({"settings_version": us.SETTINGS_SCHEMA_VERSION, "a": 1}), encoding="utf-8")
    mtime = settings_path.stat().st_mtime_ns

    us.load_settings()

    assert settings_path.stat().st_mtime_ns == mtime


def test_registered_migration_runs_and_keeps_unknown(settings_path, monkeypatch):
    """注册的迁移函数生效：键名映射执行 + 未知键保留"""
    def _migrate_v0(data):
        if "old_key" in data:
            data["new_key"] = data.pop("old_key")
        return data

    monkeypatch.setitem(us._SETTINGS_MIGRATIONS, 0, _migrate_v0)
    settings_path.write_text(json.dumps({"old_key": "v", "keep": 1}), encoding="utf-8")

    data = us.load_settings()

    assert data["settings_version"] == us.SETTINGS_SCHEMA_VERSION
    assert data["new_key"] == "v"
    assert "old_key" not in data
    assert data["keep"] == 1, "未知键应保留，绝不丢弃"
