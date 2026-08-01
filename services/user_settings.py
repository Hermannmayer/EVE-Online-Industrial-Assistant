"""用户设置集中读写 — settings.json。

现有各调用方（TopToolbar 等）各自 json 读改写同一文件，本模块提供集中读写，
不强迁既有调用方；新增的默认机库设置等统一走这里。
"""

import json
import os

from core.paths import data_dir

SETTINGS_PATH = os.path.join(data_dir(), "settings.json")


def load_settings() -> dict:
    """读取 settings.json，文件不存在或损坏时返回 {}。"""
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _write_all(data: dict) -> None:
    """全量写盘（含删除键）。"""
    os.makedirs(os.path.dirname(SETTINGS_PATH) or ".", exist_ok=True)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_settings(data: dict) -> None:
    """read-modify-write：把传入键合并进现有 settings.json（保留其它键）。"""
    merged = load_settings()
    merged.update(data or {})
    _write_all(merged)


def get_default_hangar_id(key: str) -> int | None:
    """读取默认机库设置（default_*_hangar_id 键）。"""
    value = load_settings().get(key)
    return int(value) if value is not None else None


def set_default_hangar_id(key: str, hangar_id: int | None) -> None:
    """写默认机库设置；None 时删除该键（对齐 TopToolbar -1 pop 语义）。

    注意：删除键必须全量写盘，不能走 save_settings 的 read-modify-write
    （后者会重新读盘，把待删除的键又合并回来）。
    """
    data = load_settings()
    if hangar_id is None:
        data.pop(key, None)
    else:
        data[key] = int(hangar_id)
    _write_all(data)
