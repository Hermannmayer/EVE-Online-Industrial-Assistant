"""查询页的搜索历史（纯文件 I/O，零 Qt）。

原先在 `ui_pyside6/views/query/query_search.py`：它只依赖 `core.paths`，
放在 UI 层里没有道理，QML 侧也要用。
"""

import json
import time as _time
from pathlib import Path

from core.paths import search_history_file

HISTORY_FILE = Path(search_history_file())
MAX_HISTORY = 20


def add_search_history(query: str):
    """保存搜索历史到文件"""
    try:
        history = []
        if HISTORY_FILE.exists():
            history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        history = [h for h in history if h.get("query") != query]
        history.insert(0, {"query": query, "time": _time.time()})
        if len(history) > MAX_HISTORY:
            history = history[:MAX_HISTORY]
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def load_search_history() -> list:
    """从文件加载搜索历史"""
    try:
        if HISTORY_FILE.exists():
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
    except Exception:
        pass
    return []


def clear_search_history():
    """清空搜索历史文件"""
    try:
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        HISTORY_FILE.write_text("[]", encoding="utf-8")
    except Exception:
        pass


# ═══════════════════════════════════════
#  搜索结果格式化
# ═══════════════════════════════════════
