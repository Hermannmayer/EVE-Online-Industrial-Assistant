"""Hot reload helper -- trigger/state file I/O"""

import json
import os
import tempfile
from pathlib import Path

from core.paths import data_dir

_DATA_DIR = Path(data_dir())
TRIGGER_FILE = str(_DATA_DIR / ".hot_reload_trigger")
STATE_FILE = str(_DATA_DIR / ".hot_reload_state")


def _ensure_dir():
    os.makedirs(os.path.dirname(TRIGGER_FILE), exist_ok=True)


def _atomic_write(path: str, content: str) -> None:
    """原子写文件：临时文件 + os.replace，避免读到半写内容。"""
    _ensure_dir()
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".hot_reload_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def is_triggered() -> bool:
    return os.path.exists(TRIGGER_FILE)


def write_trigger():
    _atomic_write(TRIGGER_FILE, "")


def clear_trigger():
    try:
        os.remove(TRIGGER_FILE)
    except FileNotFoundError:
        pass


def write_state(data: dict):
    _atomic_write(STATE_FILE, json.dumps(data, ensure_ascii=False, indent=2))


def read_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
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
