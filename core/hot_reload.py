"""Hot reload helper -- trigger/state file I/O"""
import json
import os
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TRIGGER_FILE = str(_DATA_DIR / ".hot_reload_trigger")
STATE_FILE = str(_DATA_DIR / ".hot_reload_state")


def _ensure_dir():
    os.makedirs(os.path.dirname(TRIGGER_FILE), exist_ok=True)


def is_triggered() -> bool:
    return os.path.exists(TRIGGER_FILE)


def write_trigger():
    _ensure_dir()
    Path(TRIGGER_FILE).touch()


def clear_trigger():
    try:
        os.remove(TRIGGER_FILE)
    except FileNotFoundError:
        pass


def write_state(data: dict):
    _ensure_dir()
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def read_state() -> dict | None:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def clear_state():
    try:
        os.remove(STATE_FILE)
    except FileNotFoundError:
        pass


def clear_all():
    clear_trigger()
    clear_state()
"""Hot reload helper -- trigger/state file I/O"""
import json
from pathlib import Path

__all__ = [
    "is_triggered", "write_trigger", "clear_trigger",
    "write_state", "read_state", "clear_state", "clear_all",
]

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TRIGGER_FILE = _DATA_DIR / ".hot_reload_trigger"
STATE_FILE = _DATA_DIR / ".hot_reload_state"


def _ensure_dir():
    _DATA_DIR.mkdir(parents=True, exist_ok=True)


def is_triggered() -> bool:
    return TRIGGER_FILE.exists()


def write_trigger():
    _ensure_dir()
    TRIGGER_FILE.touch()


def clear_trigger():
    TRIGGER_FILE.unlink(missing_ok=True)


def write_state(data: dict):
    _ensure_dir()
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def read_state() -> dict | None:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def clear_state():
    STATE_FILE.unlink(missing_ok=True)


def clear_all():
    clear_trigger()
    clear_state()
