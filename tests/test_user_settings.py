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

pytestmark = pytest.mark.fast


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


def test_settings_path_isolated_from_real_data():
    """回归：测试必须写临时 settings.json，绝不碰用户真实数据。

    背景：tests/test_ui_main_window.py 用 patch 替换 load_settings 后构造
    MainWindow；MainWindow.__init__ → apply_theme → save_settings 是
    read-modify-write，此时读到 patch 的返回值，于是把真实 data/settings.json
    全量覆盖成那个字典（用户的默认机库等设置被静默擦除）。
    """
    from core.paths import data_dir

    assert not us.SETTINGS_PATH.startswith(data_dir())


def test_save_settings_backs_up_corrupt_file(settings_path):
    """读取失败时先备份现场再写 —— 绝不用空字典覆盖用户其它设置。"""
    settings_path.write_text("{ 这不是合法 JSON", encoding="utf-8")

    us.save_settings({"theme": "one-dark"})

    assert json.loads(settings_path.read_text(encoding="utf-8")) == {"theme": "one-dark"}
    backups = list(settings_path.parent.glob("settings.json.corrupt-*"))
    assert len(backups) == 1
    assert "这不是合法 JSON" in backups[0].read_text(encoding="utf-8")


def test_set_default_hangar_id_backs_up_corrupt_file(settings_path):
    """同一保护也覆盖 set_default_hangar_id（它同样先读后写）。"""
    settings_path.write_text("坏文件", encoding="utf-8")

    us.set_default_hangar_id("default_mat_hangar_id", 4)

    assert json.loads(settings_path.read_text(encoding="utf-8")) == {"default_mat_hangar_id": 4}
    assert len(list(settings_path.parent.glob("settings.json.corrupt-*"))) == 1


class TestMaterialPriceMult:
    """材料倍率 —— 与生产规划页工具栏共用同一个 settings.json 字段。

    仓库页的导入预览与「批量设置成本价」都从这里读初值、确认时写回，
    所以「改一处两处都变」；非数值/非正数一律回落 1.0。
    """

    def test_default_is_one(self):
        assert us.get_material_price_mult() == 1.0

    def test_roundtrip(self):
        us.set_material_price_mult(1.25)
        assert us.get_material_price_mult() == pytest.approx(1.25)

    def test_invalid_falls_back_to_one(self):
        us.save_settings({"price_settings": {"mat_mult": "abc"}})
        assert us.get_material_price_mult() == 1.0
        us.save_settings({"price_settings": {"mat_mult": 0}})
        assert us.get_material_price_mult() == 1.0
        us.save_settings({"price_settings": {"mat_mult": -2}})
        assert us.get_material_price_mult() == 1.0

    def test_set_preserves_sibling_and_top_level_keys(self):
        us.save_settings({"price_settings": {"mat_hub": "Amarr", "prod_hub": "Rens"}, "theme": "one-dark"})
        us.set_material_price_mult(0.8)

        s = us.load_settings()
        assert s["price_settings"]["mat_hub"] == "Amarr"
        assert s["price_settings"]["prod_hub"] == "Rens"
        assert s["price_settings"]["mat_mult"] == pytest.approx(0.8)
        assert s["theme"] == "one-dark"
