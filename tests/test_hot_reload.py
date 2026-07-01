import pytest
from core import hot_reload


@pytest.fixture(autouse=True)
def _isolate_data_dir(monkeypatch, tmp_path):
    """Redirect hot_reload file operations to a temp directory."""
    monkeypatch.setattr(hot_reload, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(hot_reload, "TRIGGER_FILE", tmp_path / ".hot_reload_trigger")
    monkeypatch.setattr(hot_reload, "STATE_FILE", tmp_path / ".hot_reload_state")


def test_write_and_read_state():
    state = {"version": 1, "current_page": "query", "pages": {"query": {"search_text": "test"}}}
    hot_reload.write_state(state)
    assert hot_reload.read_state() == state
    hot_reload.clear_state()
    assert hot_reload.read_state() is None


def test_trigger_cycle():
    hot_reload.clear_trigger()
    assert not hot_reload.is_triggered()
    hot_reload.write_trigger()
    assert hot_reload.is_triggered()
    hot_reload.clear_trigger()
    assert not hot_reload.is_triggered()


def test_clear_all():
    hot_reload.write_trigger()
    hot_reload.write_state({"k": "v"})
    hot_reload.clear_all()
    assert not hot_reload.is_triggered()
    assert hot_reload.read_state() is None
