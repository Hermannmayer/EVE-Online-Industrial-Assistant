"""EVE 挂单导出解析 —— 纯函数（无 DB、无 Qt）。

数据来源：游戏内「钱包 → 订单 → 导出」写出的**本地文件**（CSV）。

解析策略（按优先级）：
1. **表头驱动**：首行若是逗号/制表符分隔且含已知列名，则按列名建「列序→字段」映射，
   逐行按位置取值。列名映射大小写与下划线不敏感，并接受同义名
   （``typeID``/``type_id``、``volRemaining``/``vol_remaining`` 等）。
   列序可任意打乱，缺失列取默认值。
2. **启发式兜底**：无表头（或表头认不出）时，退化为逐行「找最大整数当订单 ID /
   小数当价格 / 两个整数当挂单量·剩余 / 买·卖词当方向 / X 天·X 小时当有效期」的启发式；
   认不出的行计入未识别计数。

两种路径都不抛异常；输出 dict 的键与 ``open_orders`` 表列一致。
"""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path


# ── 输出字段默认值（与 open_orders 表列一致） ──
def _empty_order() -> dict:
    return {
        "order_id": 0,
        "is_buy": 0,
        "price": 0.0,
        "volume_total": 0,
        "volume_remain": 0,
        "location_id": 0,
        "location_name": "",
        "type_id": 0,
        "type_name": "",
        "issued": "",
        "duration": 0,
        "char_id": 0,
        "is_corp": 0,
    }


# ── 列名 → 字段（键为归一化后的列名：小写 + 去空格/下划线） ──
_FIELD_ALIASES: dict[str, set[str]] = {
    "order_id": {"orderid", "order", "订单id", "订单"},
    "is_buy": {"bid", "isbuy", "buy", "direction", "方向", "买卖", "买卖方向"},
    "price": {"price", "单价"},
    "volume_total": {
        "volentered",
        "volumetotal",
        "quantity",
        "qty",
        "挂单量",
        "数量",
        "已挂数量",
    },
    "volume_remain": {
        "volremaining",
        "volumeremaining",
        "remaining",
        "remain",
        "剩余",
        "余量",
    },
    "location_id": {"stationid", "locationid", "station"},
    "location_name": {"stationname", "location", "locationname", "位置", "地点"},
    "type_id": {"typeid", "itemid", "物品id"},
    "type_name": {"typename", "item", "itemname", "物品名称", "名称", "物品"},
    "issued": {"issued", "issueddate", "issuedate", "issuetime", "时间", "发布日期"},
    "duration": {"duration", "有效期"},
    # 归属列。挂单有两个来源（游戏导出 / ESI），且「个人订单-…」与「军团订单-…」是
    # 两份独立导出 —— 不区分就会把另一份里的挂单判成「已成交」。真实表头是 charID / isCorp。
    "char_id": {"charid", "characterid", "角色id"},
    "is_corp": {"iscorp", "iscorporation", "军团"},
}
_ALIAS_TO_FIELD: dict[str, str] = {alias: field for field, aliases in _FIELD_ALIASES.items() for alias in aliases}

# 启发式路径：表头行白名单（归一化后）
_HEADER_TOKENS = set(_ALIAS_TO_FIELD) | {"订单编号"}

_BUY_TOKENS = {"buy", "b", "买", "买单", "买入"}
_SELL_TOKENS = {"sell", "s", "卖", "卖单", "卖出"}
_TRUE_TOKENS = {"1", "true", "yes", "y", "t", "买"}
_FALSE_TOKENS = {"0", "false", "no", "n", "f", "卖"}
_DURATION_RE = re.compile(r"^(\d+)\s*(?:天|日|小时|时|hour|hours|day|days|d|h)$", re.IGNORECASE)
_NUM_RE = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)")
_CURRENCY_RE = re.compile(r"(?i)(isk|星币)$")


def _norm_col(name: str) -> str:
    """归一化列名：小写 + 去空格/下划线（大小写与下划线不敏感）。

    **必须一起去掉 BOM**：真实导出文件是 **UTF-8 带 BOM** 的，用 ``utf-8`` 读时
    首列名会变成 ``\\ufefforderID``，认不出 → 整份文件退化成启发式解析（不报错，只是错）。
    """
    return re.sub(r"[\s_]+", "", name.strip().lstrip("﻿").lower())


#: 游戏把本地化的名字（星域/星系/空间站）包成
#: ``<localized hint="Jita IV - Moon 4 - …">中文名*</localized>``。
#: 直接把这段 markup 存进库会让「位置」列显示成一串标签，所以取值时统一拆掉。
_LOCALIZED_RE = re.compile(r"<localized[^>]*>(.*?)</localized>", re.IGNORECASE | re.DOTALL)
_HINT_RE = re.compile(r'hint="([^"]*)"', re.IGNORECASE)


def _clean_value(raw: str) -> str:
    """拆掉 ``<localized>`` 包装并去掉值尾部那个占位 ``*``。

    优先取标签**内**的文本（那是游戏界面里显示的名字）；没有内文本时退回 ``hint``
    （英文名）。两者都没有就原样返回。
    """
    text = (raw or "").strip()
    if "<localized" not in text.lower():
        return text
    inner = _LOCALIZED_RE.search(text)
    if inner:
        body = inner.group(1).strip()
        if body:
            return body.rstrip("*").strip()
    hint = _HINT_RE.search(text)
    if hint:
        return hint.group(1).strip()
    return text


#: 导出文件名里认得出的标记（小写比较）。**中文标记不能少**：国服客户端导出的文件名
#: 就是中文的（``个人订单-2026.09.16 1232.txt`` / ``军团订单-…``），只认 ``order``
#: 会让国服用户永远找不到自己刚导出的文件，而且不报任何错。
_NAME_MARKERS = ("order", "订单")


def read_export_text(path: str | Path) -> str:
    """读导出文件 → 文本。**按 BOM/编码逐档尝试**。

    真实文件是 **UTF-8 (BOM)**；但不同客户端/版本出现过 UTF-16 与本地代码页，
    所以按 ``utf-8-sig`` → ``utf-16`` → ``gbk`` → ``utf-8(errors=replace)`` 依次试，
    以「能解码出含逗号的多行文本」为成功判据，全失败时返回最后一档的尽力结果。
    """
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "utf-16", "gbk"):
        try:
            text = raw.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
        if "," in text or "\t" in text:
            return text
    return raw.decode("utf-8", errors="replace")


# ════════════════════════════════════════════════════════════════
#  数值/枚举解析
# ════════════════════════════════════════════════════════════════


def _normalize_number(token: str) -> str | None:
    """把带千分位/货币后缀的数值串归一为可 ``float()`` 的纯数字串；失败返回 None。

    支持 ``1,234.56``（英式）与 ``1 234,56``（欧式）。
    """
    s = _CURRENCY_RE.sub("", token.strip()).strip()
    if not s:
        return None
    s = s.replace(" ", "")  # 欧式千分位空格
    has_comma = "," in s
    has_dot = "." in s
    if has_comma and has_dot:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")  # 欧式：点千分位、逗号小数
        else:
            s = s.replace(",", "")  # 英式：逗号千分位
    elif has_comma:
        parts = s.split(",")
        head = parts[0].lstrip("+-")
        if head.isdigit() and all(len(p) == 3 for p in parts[1:]):
            s = s.replace(",", "")  # 每段 3 位 → 千分位
        else:
            s = s.replace(",", ".")  # 否则当小数分隔
    if not _NUM_RE.fullmatch(s):
        return None
    return s


def _to_float(token: str) -> float | None:
    s = _normalize_number(token)
    if s is None:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _to_int(token: str) -> int | None:
    s = _normalize_number(token)
    if s is None or "." in s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _to_bool(token: str) -> int | None:
    low = token.strip().lower()
    if low in _TRUE_TOKENS:
        return 1
    if low in _FALSE_TOKENS:
        return 0
    return None


def _to_duration(token: str) -> int | None:
    m = _DURATION_RE.match(token.strip())
    if m:
        return int(m.group(1))
    return _to_int(token)


# ════════════════════════════════════════════════════════════════
#  表头驱动解析
# ════════════════════════════════════════════════════════════════


def _split_csv_line(line: str, delim: str) -> list[str]:
    """按分隔符拆一行 CSV（正确处理引号包裹的字段）。"""
    return next(csv.reader(io.StringIO(line), delimiter=delim))


def _header_mapping(cols: list[str]) -> dict[int, str]:
    """列序 → 字段。至少命中 2 个已知列名才认定为表头（否则返回空 dict）。"""
    mapping: dict[int, str] = {}
    used: set[str] = set()
    for idx, col in enumerate(cols):
        field = _ALIAS_TO_FIELD.get(_norm_col(col))
        if field and field not in used:
            mapping[idx] = field
            used.add(field)
    return mapping if len(mapping) >= 2 else {}


def _assign(row: dict, field: str, val: str) -> None:
    val = _clean_value(val)
    if val == "":
        return
    if field in ("location_name", "type_name", "issued"):
        row[field] = val
        return
    if field in ("is_buy", "is_corp"):
        b = _to_bool(val)
        if b is not None:
            row[field] = b
        return
    if field == "price":
        f = _to_float(val)
        if f is not None:
            row["price"] = f
        return
    if field == "duration":
        d = _to_duration(val)
        if d is not None:
            row["duration"] = d
        return
    i = _to_int(val)
    if i is None:
        # 真实导出里「剩余量」是**浮点串**（实测 `volRemaining` 为 `340.0`），而 `_to_int`
        # 见到小数点就返回 None —— 该列会**静默变成 0**（挂单列表显示「剩余 0」）。
        # 这里按字段语义允许取整；启发式路径仍要求纯整数，所以不动 `_to_int` 本身。
        f = _to_float(val)
        i = int(f) if f is not None else None
    if i is not None:
        row[field] = i


def _parse_with_header(lines: list[str], delim: str, mapping: dict[int, str]) -> tuple[list[dict], int]:
    orders: list[dict] = []
    unparsed = 0
    for line in lines:
        if not line.strip():
            continue
        cells = _split_csv_line(line, delim)
        row = _empty_order()
        for idx, field in mapping.items():
            if idx < len(cells):
                _assign(row, field, cells[idx].strip())
        if row["order_id"] == 0:
            unparsed += 1
            continue
        orders.append(row)
    return orders, unparsed


# ════════════════════════════════════════════════════════════════
#  启发式兜底解析（无表头时）
# ════════════════════════════════════════════════════════════════


def _split_heuristic(line: str) -> list[str]:
    if "\t" in line:
        return [p.strip() for p in line.split("\t") if p.strip()]
    return [p.strip() for p in re.split(r" {2,}", line) if p.strip()]


def _is_header_row(parts: list[str]) -> bool:
    lows = [_norm_col(p) for p in parts]
    hits = sum(1 for x in lows if x in _HEADER_TOKENS)
    return lows[0] in _HEADER_TOKENS or hits >= 2


def _parse_heuristic_row(parts: list[str]) -> dict | None:
    ints: list[int] = []
    floats: list[float] = []
    strings: list[str] = []
    is_buy = 0
    duration = 0

    for p in parts:
        low = p.lower()
        if low in _BUY_TOKENS:
            is_buy = 1
            continue
        if low in _SELL_TOKENS:
            is_buy = 0
            continue
        d = _DURATION_RE.match(p)
        if d:
            duration = int(d.group(1))
            continue
        iv = _to_int(p)
        if iv is not None:
            ints.append(iv)
            continue
        fv = _to_float(p)
        if fv is not None:
            floats.append(fv)
            continue
        strings.append(p)

    if not ints and not floats:
        return None  # 无任何数字 → 无法解析

    order_id = max(ints) if ints else 0
    if order_id:
        ints.remove(order_id)

    row = _empty_order()
    row["order_id"] = order_id
    row["is_buy"] = is_buy
    row["price"] = floats[0] if floats else 0.0
    row["duration"] = duration
    row["location_name"] = strings[0] if strings else ""

    if len(ints) >= 2:
        top2 = sorted(ints, reverse=True)[:2]
        row["volume_total"], row["volume_remain"] = top2[0], top2[1]
    elif len(ints) == 1:
        row["volume_total"] = row["volume_remain"] = ints[0]
    return row


def _parse_heuristic(lines: list[str]) -> tuple[list[dict], int]:
    orders: list[dict] = []
    unparsed = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        parts = _split_heuristic(stripped)
        if not parts:
            continue
        if _is_header_row(parts):
            continue
        row = _parse_heuristic_row(parts)
        if row is None:
            unparsed += 1
            continue
        orders.append(row)
    return orders, unparsed


# ════════════════════════════════════════════════════════════════
#  公开 API
# ════════════════════════════════════════════════════════════════


def parse_order_export(raw: str) -> tuple[list[dict], int]:
    """解析 EVE 挂单导出文本 → ``(订单列表, 未识别行数)``。

    优先按表头解析（CSV）；无表头时退化为启发式。**不抛异常**。
    表头行本身既不计入订单、也不计入未识别计数。
    """
    text = raw.lstrip("﻿")  # 去 UTF-8 BOM
    lines = text.splitlines()
    first = next((i for i, ln in enumerate(lines) if ln.strip()), None)
    if first is None:
        return [], 0

    header = lines[first]
    delim = "\t" if "\t" in header else ("," if "," in header else None)
    if delim is not None:
        mapping = _header_mapping(_split_csv_line(header, delim))
        if mapping:
            return _parse_with_header(lines[first + 1 :], delim, mapping)

    return _parse_heuristic(lines)


def _default_export_dir() -> str:
    """EVE 订单导出默认目录。

    Windows：``%USERPROFILE%\\Documents\\EVE\\logs\\Marketlogs``；
    macOS/其它：``~/Documents/EVE/logs/Marketlogs``。
    两者都可用 ``Path.home()`` 表达（Windows 下 ``Path.home()`` 即 USERPROFILE），
    不硬编码盘符。
    """
    return str(Path.home() / "Documents" / "EVE" / "logs" / "Marketlogs")


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def find_latest_export(directory: str | None = None) -> str | None:
    """返回目录下最新的订单导出文件路径（按 mtime）；没有则 None。

    匹配名字含下列任一标记（不分大小写）且后缀为 ``.txt``/``.csv`` 的文件：
    ``order`` / ``订单``。

    ⚠️ **中文标记不能少**：国服客户端的导出文件名就是中文的，实测为
    ``个人订单-2026.09.16 1232.txt``（英文客户端是 ``My Orders - …``）。只认 ``order``
    会让国服用户永远找不到自己刚导出的文件，而且**不报任何错**（只是「没找到」）。

    目录不存在 → None，不抛异常。``directory`` 为 None 时用默认导出目录。
    """
    if directory is None:
        directory = _default_export_dir()
    base = Path(directory)
    if not base.is_dir():
        return None
    candidates = [
        p
        for p in base.iterdir()
        if p.is_file() and p.suffix.lower() in {".txt", ".csv"} and any(m in p.name.lower() for m in _NAME_MARKERS)
    ]
    if not candidates:
        return None
    return str(max(candidates, key=_safe_mtime))
