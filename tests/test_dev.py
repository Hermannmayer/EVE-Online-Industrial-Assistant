"""Tests for dev.py hot-reload launcher."""

from unittest.mock import MagicMock

import pytest

import dev


def test_build_args_includes_hot_reload():
    args = dev.build_args(debug=False)
    assert str(dev.ROOT / "Main.py") in args
    assert "--hot-reload" in args
    assert "--debug" not in args


def test_build_args_debug_combo():
    args = dev.build_args(debug=True)
    assert "--hot-reload" in args
    assert "--debug" in args


def test_start_app_passes_args_to_popen(monkeypatch):
    captured = {}

    def fake_popen(args, **kw):
        captured["args"] = args
        captured["kw"] = kw
        return MagicMock()

    monkeypatch.setattr(dev.subprocess, "Popen", fake_popen)
    dev.start_app(debug=True)
    assert captured["kw"]["cwd"] == dev.ROOT
    assert "--hot-reload" in captured["args"]
    assert "--debug" in captured["args"]


def test_start_app_clears_trigger(monkeypatch):
    monkeypatch.setattr(dev, "clear_trigger", MagicMock())
    monkeypatch.setattr(dev.subprocess, "Popen", MagicMock())
    dev.start_app()
    dev.clear_trigger.assert_called_once_with()


def test_main_acquires_and_releases_dev_lock(monkeypatch, tmp_path):
    monkeypatch.setattr(dev, "DEV_LOCK", tmp_path / "dev.lock")
    monkeypatch.setattr(dev, "_run", MagicMock())
    calls = []
    monkeypatch.setattr(dev, "try_lock", lambda **kw: calls.append(("try", kw)) or True)
    monkeypatch.setattr(dev, "unlock", lambda **kw: calls.append(("unlock", kw)))
    dev.main()
    assert calls == [
        ("try", {"lock_file": tmp_path / "dev.lock"}),
        ("unlock", {"lock_file": tmp_path / "dev.lock"}),
    ]
    dev._run.assert_called_once_with()


def test_main_exits_1_when_lock_failed(monkeypatch, tmp_path):
    monkeypatch.setattr(dev, "DEV_LOCK", tmp_path / "dev.lock")
    monkeypatch.setattr(dev, "try_lock", lambda **kw: False)
    monkeypatch.setattr(dev, "_run", MagicMock())
    with pytest.raises(SystemExit) as e:
        dev.main()
    assert e.value.code == 1
