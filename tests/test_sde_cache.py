"""SDE 缓存工具测试 — tools/downloaders/sde_cache.py

覆盖:
  - load_yaml 进程内缓存（避免初始化反复解析 typeIDs.yaml 大文件）
  - clear_yaml_cache 释放缓存
"""

from unittest.mock import patch

import yaml

from tools.downloaders.sde_cache import clear_yaml_cache, load_yaml


def _make_loader(tmp_path, monkeypatch, filename="test.yaml", content="key: value"):
    """写临时 YAML 文件并把 cache_path 指向临时目录"""
    (tmp_path / filename).write_text(content, encoding="utf-8")
    monkeypatch.setattr("tools.downloaders.sde_cache.cache_path", lambda name: str(tmp_path / name))


class TestLoadYamlCache:
    def test_parses_once_and_reuses(self, tmp_path, monkeypatch):
        """同一文件二次加载走缓存，yaml.load 只执行一次"""
        _make_loader(tmp_path, monkeypatch)
        clear_yaml_cache()

        calls = {"n": 0}
        real_load = yaml.load

        def counting_load(stream, Loader=None):
            calls["n"] += 1
            return real_load(stream, Loader=Loader)

        with patch("tools.downloaders.sde_cache.yaml.load", side_effect=counting_load):
            first = load_yaml("test.yaml")
            second = load_yaml("test.yaml")

        assert calls["n"] == 1
        assert first is second  # 共享同一缓存对象
        clear_yaml_cache()

    def test_clear_yaml_cache_forces_reparse(self, tmp_path, monkeypatch):
        """clear_yaml_cache 后再次加载会重新解析"""
        _make_loader(tmp_path, monkeypatch)
        clear_yaml_cache()

        calls = {"n": 0}
        real_load = yaml.load

        def counting_load(stream, Loader=None):
            calls["n"] += 1
            return real_load(stream, Loader=Loader)

        with patch("tools.downloaders.sde_cache.yaml.load", side_effect=counting_load):
            load_yaml("test.yaml")
            load_yaml("test.yaml")
            assert calls["n"] == 1

            clear_yaml_cache()
            load_yaml("test.yaml")
            assert calls["n"] == 2

        clear_yaml_cache()

    def test_missing_file_returns_empty(self, tmp_path, monkeypatch):
        """文件不存在返回空 dict"""
        clear_yaml_cache()
        monkeypatch.setattr("tools.downloaders.sde_cache.cache_path", lambda name: str(tmp_path / name))
        assert load_yaml("nonexistent.yaml") == {}
        clear_yaml_cache()
