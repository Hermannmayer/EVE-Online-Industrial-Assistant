# Hot Reload Development Mode -- Implementation Plan

> Use subagent-driven-development or executing-plans to implement task by task.
> Steps use `- [ ]` syntax for tracking.

**Goal:** Graceful process restart + UI state save/restore on file changes

**Architecture:** File-based handshake: dev.py writes trigger, MainWindow polls, save_state, quit, dev.py restarts, restore_state

**Stack:** Python 3.14, PySide6, subprocess, watchdog

---

### Task 1: Create core/hot_reload.py

**Files** Create: core/hot_reload.py. Test: tests/test_hot_reload.py

- [ ] **Step 1: Write and run the failing test**

Create tests/test_hot_reload.py with:
- test_write_and_read_state: write state, read back, clear, assert None
- test_trigger_cycle: clear -> not triggered -> write -> triggered -> clear -> not triggered
- test_clear_all: write trigger+state -> clear_all -> both gone

Run: `pytest tests/test_hot_reload.py -v` -> ImportError

- [ ] **Step 2: Create core/hot_reload.py**

```python
"""Hot reload helper -- trigger/state file I/O"""
import json, os
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TRIGGER_FILE = str(_DATA_DIR / ".hot_reload_trigger")
STATE_FILE = str(_DATA_DIR / ".hot_reload_state")

def _ensure_dir():
    os.makedirs(os.path.dirname(TRIGGER_FILE), exist_ok=True)

def is_triggered() -> bool:
    return os.path.exists(TRIGGER_FILE)

def write_trigger():
    _ensure_dir(); Path(TRIGGER_FILE).touch()

def clear_trigger():
    try: os.remove(TRIGGER_FILE)
    except FileNotFoundError: pass

def write_state(data: dict):
    _ensure_dir()
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def read_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None

def clear_state():
    try: os.remove(STATE_FILE)
    except FileNotFoundError: pass

def clear_all():
    clear_trigger(); clear_state()
```

- [ ] **Step 3: Run tests** -> `pytest tests/test_hot_reload.py -v` -> 3 passed
- [ ] **Step 4: Commit**

```bash
git add core/hot_reload.py tests/test_hot_reload.py
git commit -m "feat: add hot_reload helper module (trigger/state file I/O)"
```

---

### Task 2: Modify dev.py -- graceful shutdown

**Files:** Modify: dev.py

- [ ] **Step 1: Replace terminate with trigger + wait**

In watchdog handler (RestartHandler.on_modified), change direct terminate to:
```python
from core.hot_reload import write_trigger
write_trigger()
try:
    proc.wait(5)
except subprocess.TimeoutExpired:
    proc.terminate()
    try:
        proc.wait(3)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(2)
```

Same change in the polling fallback section (lines ~120-140).

- [ ] **Step 2: Lint** `ruff check dev.py` -> no errors
- [ ] **Step 3: Commit** `git add dev.py && git commit -m "feat: graceful shutdown protocol"`

---

### Task 3: Modify Main.py -- pass --hot-reload flag

**Files:** Modify: Main.py

- [ ] **Step 1: Add before MainWindow():**
```python
HOT_RELOAD = "--hot-reload" in sys.argv
```
Change `MainWindow()` to `MainWindow(hot_reload=HOT_RELOAD)`

- [ ] **Step 2: Commit**

---

### Task 4: Modify main_window.py

**Files:** Modify: ui_pyside6/main_window.py

- [ ] **Step 1: Update __init__**

Change `def __init__(self):` to `def __init__(self, hot_reload: bool = False):`

At end of __init__ (after add_theme_listener, before _check_first_run), add:
```python
# -- Hot reload --
self._hot_reload_enabled = hot_reload
if self._hot_reload_enabled:
    self._hot_reload_timer = QTimer(self)
    self._hot_reload_timer.timeout.connect(self._check_hot_reload)
    self._hot_reload_timer.start(500)
    from core import hot_reload as _hr
    state = _hr.read_state()
    if state:
        self.restore_state(state)
        _hr.clear_state()
```

- [ ] **Step 2: closeEvent clearing** -- add at start of closeEvent:
```python
from core import hot_reload as _hr
_hr.clear_trigger()
```

- [ ] **Step 3: Add new methods** -- after _check_first_run:

```python
def _check_hot_reload(self):
    from core import hot_reload as _hr
    if _hr.is_triggered():
        self._do_hot_reload()

def _do_hot_reload(self):
    from core import hot_reload as _hr
    state = self.save_state()
    _hr.write_state(state)
    _hr.clear_trigger()
    QApplication.quit()

def save_state(self) -> dict:
    state = {"version": 1, "current_page": "", "pages": {}}
    current = self._nav_tree.currentItem()
    if current:
        key = current.data(0, Qt.ItemDataRole.UserRole)
        if key:
            state["current_page"] = key
    for key, page in self._pages.items():
        if hasattr(page, "save_state"):
            try:
                state["pages"][key] = page.save_state()
            except Exception:
                pass
    return state

def restore_state(self, data: dict):
    key = data.get("current_page")
    if key and key in self._pages:
        for item in self._nav_items:
            if item.data(0, Qt.ItemDataRole.UserRole) == key:
                self._nav_tree.setCurrentItem(item)
                break
        self.content_stack.setCurrentWidget(self._pages[key])
    for pkey, pdata in data.get("pages", {}).items():
        if pkey in self._pages and hasattr(self._pages[pkey], "restore_state"):
            try:
                self._pages[pkey].restore_state(pdata)
            except Exception:
                pass
```

- [ ] **Step 4: Lint + Commit**

---

### Tasks 5-11: View save_state/restore_state

Each view page gets two methods:

```python
def save_state(self) -> dict:
    data = {}
    # collect widget state
    return data

def restore_state(self, data: dict) -> None:
    if not data: return
    # restore widget state
```

| Task | View | Page class | State to save |
|------|------|------------|---------------|
| 5 | query_view.py | QueryPage | search_text, sort_column/sort_order, v_scroll |
| 6 | estimate_view.py | EstimatePage | clipboard_text, sort_column/sort_order, v_scroll |
| 7 | industry_view.py | IndustryPage | tab_index, search_text, me, te, mat_hub, sell_hub, mat_price_type, tax, sort/scroll |
| 8 | trade_view.py | TradePage | tab_index |
| 9 | watchlist_view.py | WatchlistPage | sort_column, sort_order, v_scroll |
| 10 | contract_view.py | ContractPage | region, type, search_text |
| 11 | inventory_view.py | InventoryPage | tab_index, hangar_index |

For table sort/scroll save/restore pattern:
```python
header = self._table.horizontalHeader()
data["sort_column"] = header.sortIndicatorSection()
data["sort_order"] = 1 if header.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder else 0
vs = self._table.verticalScrollBar()
if vs: data["v_scroll"] = vs.value()

# restore:
col = data.get("sort_column", -1)
if col >= 0:
    order = Qt.SortOrder.AscendingOrder if data.get("sort_order", 1) == 1 else Qt.SortOrder.DescendingOrder
    self._table.sortByColumn(col, order)
sv = data.get("v_scroll", 0)
if sv:
    QTimer.singleShot(100, lambda: self._table.verticalScrollBar().setValue(sv))
```

Each task: write code, lint, commit individually.

---

### Task 12: Final Verification

- [ ] **Step 1:** `ruff check .` -> no errors
- [ ] **Step 2:** `pytest` -> all pass
- [ ] **Step 3:** Run `python dev.py --debug`, modify any .py file -> auto restart -> state restored
- [ ] **Step 4:** Final commit: `git add -A && git commit -m "chore: finalize hot reload implementation"`
