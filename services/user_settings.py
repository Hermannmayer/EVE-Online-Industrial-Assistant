"""用户设置集中读写 — settings.json。

现有各调用方（TopToolbar 等）各自 json 读改写同一文件，本模块提供集中读写，
不强迁既有调用方；新增的默认机库设置等统一走这里。
"""

import json
import os
from collections.abc import Callable
from datetime import datetime

from core.logger import log
from core.paths import data_dir

SETTINGS_PATH = os.path.join(data_dir(), "settings.json")

# settings.json 结构版本：键结构变更时 +1，并在 _SETTINGS_MIGRATIONS 注册升级函数。
# v0→v1：无实际结构变更，仅落 settings_version 键，为后续迁移留版本基准。
SETTINGS_SCHEMA_VERSION = 1
_SETTINGS_MIGRATIONS: dict[int, Callable[[dict], dict]] = {}


def _migrate_settings(data: dict) -> dict:
    """惰性升级 settings 结构：版本 < CURRENT 时逐级迁移并落盘。

    迁移函数只做键名映射/结构调整，保留所有未知键，绝不丢弃用户数据。
    """
    version = int(data.get("settings_version", 0) or 0)
    if version >= SETTINGS_SCHEMA_VERSION:
        return data
    for v in range(version, SETTINGS_SCHEMA_VERSION):
        mig = _SETTINGS_MIGRATIONS.get(v)
        if mig:
            data = mig(data) or data
    data["settings_version"] = SETTINGS_SCHEMA_VERSION
    _write_all(data)
    return data


def _read_raw() -> dict | None:
    """读原始 JSON：文件不存在 → {}；存在但读不出来（损坏/被占用）→ None。

    区分这两种情况很重要：写入前的 read-modify-write 只有在「文件不存在」时
    才可以从空字典起步；「读失败」时若也当作空，就会把用户其余设置全部抹掉。
    """
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _backup_corrupt() -> None:
    """settings.json 读不出来时先另存现场，再让调用方重建。"""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = f"{SETTINGS_PATH}.corrupt-{stamp}"
    try:
        os.replace(SETTINGS_PATH, backup)
        log.warning("settings.json 无法解析，已备份为 %s 后重建", backup)
    except OSError:
        log.exception("备份损坏的 settings.json 失败")


def load_settings() -> dict:
    """读取 settings.json，文件不存在或损坏时返回 {}；结构过期时先升级再返回。"""
    if not os.path.exists(SETTINGS_PATH):
        return {}  # 不存在 → 不触发迁移写盘（保持与历史行为一致）
    data = _read_raw()
    if data is None:
        return {}
    return _migrate_settings(data)


def _write_all(data: dict) -> None:
    """全量写盘（含删除键）。"""
    os.makedirs(os.path.dirname(SETTINGS_PATH) or ".", exist_ok=True)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_settings(data: dict) -> None:
    """read-modify-write：把传入键合并进现有 settings.json（保留其它键）。

    读取失败（文件损坏/被占用）时先备份现场再重建，绝不用空字典静默覆盖——
    否则一次读失败就会丢掉用户全部设置。
    """
    merged = _read_raw()
    if merged is None:
        _backup_corrupt()
        merged = {}
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
    data = _read_raw()
    if data is None:
        _backup_corrupt()
        data = {}
    if hangar_id is None:
        data.pop(key, None)
    else:
        data[key] = int(hangar_id)
    _write_all(data)


# ════════════════════════════════════════════════════════════════
#  价格来源设置（与生产规划页工具栏「双行价格设置」共用同一份 settings.json）
# ════════════════════════════════════════════════════════════════


def _price_setting_defaults() -> dict:
    """价格设置的默认值（hub 取贸易中心列表首项）。"""
    from core.constants import TRADE_HUBS

    hub = TRADE_HUBS[0] if TRADE_HUBS else "Jita"
    return {
        "mat_hub": hub,
        "mat_price_type": "sell",
        "mat_mult": 1.0,
        "prod_hub": hub,
        "prod_price_type": "sell",
        "prod_mult": 1.0,
    }


def get_price_settings() -> dict:
    """价格来源设置 {mat_hub, mat_price_type, mat_mult, prod_hub, prod_price_type, prod_mult}。

    **必须补齐缺失键**，不能只回吐 settings.json 里存了什么：调用方普遍写成
    `ps["mat_hub"]`（旧实现由工具栏控件保证全量键），没存过设置的用户会拿到空
    dict，那些下标访问立刻 KeyError —— 实测会让工业页**整页加载失败**（报 'mat_hub'）。
    """
    stored = load_settings().get("price_settings") or {}
    merged = _price_setting_defaults()
    merged.update({k: v for k, v in stored.items() if k in merged})
    return merged


def get_material_price_mult() -> float:
    """材料价格调整系数（默认 1.0）。

    仓库页的成本定价控件与生产规划页工具栏共用**同一个**值：一处改，另一处跟着变。
    非数值 / 缺失 / 非正数一律回落 1.0（settings.json 可手改，不能信）。
    """
    raw = get_price_settings().get("mat_mult")
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 1.0
    return value if value > 0 else 1.0


def set_material_price_mult(value: float) -> None:
    """写回材料价格调整系数（读-改-写，只动 price_settings.mat_mult，保留其它键）。"""
    settings = load_settings()
    price_settings = dict(settings.get("price_settings") or {})
    price_settings["mat_mult"] = float(value)
    save_settings({"price_settings": price_settings})


#: ESI 同步是否把军团钱包计入总资产。**默认关**：军团钱包是共享账户，不是个人净资产；
#: 而且读它需要 `esi-wallet.read_corporation_wallets.v1`，角色还得有军团会计类角色。
_INCLUDE_CORP_WALLET_KEY = "esi_include_corp_wallet"


def get_include_corp_wallet() -> bool:
    """ESI 同步是否合计军团钱包（默认 False）。settings.json 可手改，只认真值。"""
    return load_settings().get(_INCLUDE_CORP_WALLET_KEY) is True


def set_include_corp_wallet(value: bool) -> None:
    """写回「含军团钱包」开关（读-改-写，保留其它键）。"""
    save_settings({_INCLUDE_CORP_WALLET_KEY: bool(value)})
