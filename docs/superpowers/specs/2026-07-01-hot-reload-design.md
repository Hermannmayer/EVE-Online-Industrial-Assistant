# Hot Reload 开发模式设计文�?
## 概述

在现�?`dev.py` 进程重启机制的基础上，增加**优雅关停 + 状态保�?恢复**的握手协议，
使文件变更后重启进程对用户近乎无缝：当前页面、搜索内容、表格排序和滚动位置自动恢复�?
## 设计目标

- 文件变更 �?自动重启进程 < 3 �?- 重启后恢复：当前页面、搜索文字、表格排序列/方向、滚动位置、区域选择
- 零新增外部依�?- 最小侵入：不改动现有架构，只在 MainWindow 和各 View 上加序列化方�?
## 架构设计

### 核心思路：文件系统握�?
dev.py 检测到 .py 文件变更
  |
  +-- 写入 data/.hot_reload_trigger
  +-- 等待旧进程退�?
(运行中的 MainWindow �?500ms 轮询 .hot_reload_trigger)
  -> 检测到触发标记
  -> save_state() -> 写入 data/.hot_reload_state
  -> 删除 .hot_reload_trigger
  -> QApplication.quit()

dev.py 检测到进程退出（5 秒超时，超时�?ǿ����ֹ (proc.kill\(\))�?  +-- 启动新进程：python Main.py --hot-reload

MainWindow.__init__ 末尾
  +-- 检�?data/.hot_reload_state 存在
  +-- restore_state() -> 恢复页面/搜索/表格状�?  +-- 删除 .hot_reload_state

### 文件说明

| 文件 / 模块 | 角色 |
|---|-------|
| core/hot_reload.py | 常量（trigger/state 文件路径）、读写帮助函�?|
| dev.py | watchdog 检测到变更 -> 写入 trigger -> 等进程退�?-> 新进�?|
| Main.py | 解析 --hot-reload CLI 参数，传�?MainWindow |
| MainWindow | 状态保�?恢复、轮�?timer、握手关�?|
| 7 个页�?View | 各自�?save_state() / restore_state() |

## 详细设计

### 1. core/hot_reload.py

新增模块，定义共享常量和工具函数�?
```python
TRIGGER_FILE = Path("data/.hot_reload_trigger")
STATE_FILE = Path("data/.hot_reload_state")

def is_triggered() -> bool
def write_state(data: dict) -> None
def read_state() -> dict | None
def clear_trigger() -> None
def write_trigger() -> None
def clear_state() -> None
```

### 2. dev.py 修改

�?watchdog 的事件处理中，将直接�?proc.terminate() + 新进程改为：

```python
# 写入 trigger 文件
hot_reload.write_trigger()
# 等进程优雅退出（最�?5 秒）
if proc and proc.poll() is None:
    try:
        proc.wait(5)
    except subprocess.TimeoutExpired:
        proc.terminate()
        proc.wait(3)
# 启动新进�?proc = start_app(debug)
```

轮询模式（无 watchdog）也做同样改动�?
### 3. Main.py 修改

```python
# 新增 CLI 参数
HOT_RELOAD = "--hot-reload" in sys.argv
# 传给 MainWindow
window = MainWindow(hot_reload=HOT_RELOAD)
```

### 4. MainWindow 修改

#### 初始�?
```python
def __init__(self, hot_reload: bool = False):
    self._hot_reload_enabled = hot_reload
    ...
    # 末尾启动轮询 timer
    if self._hot_reload_enabled:
        self._hot_reload_timer = QTimer(self)
        self._hot_reload_timer.timeout.connect(self._check_hot_reload)
        self._hot_reload_timer.start(500)
        # 尝试恢复状�?        state = hot_reload.read_state()
        if state:
            self.restore_state(state)
            hot_reload.clear_state()
```

#### 新增方法

```python
def _check_hot_reload(self):
    if hot_reload.is_triggered():
        self._do_hot_reload()

def _do_hot_reload(self):
    state = self.save_state()
    hot_reload.write_state(state)
    hot_reload.clear_trigger()
    QApplication.quit()

def save_state(self) -> dict:
    state = {
        "version": 1,
        "current_page": ...,
        "region": self._region_combo.currentText(),
        "pages": {},
    }
    for key, page in self._pages.items():
        if hasattr(page, "save_state"):
            state["pages"][key] = page.save_state()
    return state

def restore_state(self, data: dict):
    if "region" in data:
        idx = self._region_combo.findText(data["region"])
        if idx >= 0:
            self._region_combo.setCurrentIndex(idx)
    key = data.get("current_page")
    if key and key in self._pages:
        item = ...  # 找到对应�?nav item
        self._nav_tree.setCurrentItem(item)
        self.content_stack.setCurrentWidget(self._pages[key])
    for key, pdata in data.get("pages", {}).items():
        if key in self._pages and hasattr(self._pages[key], "restore_state"):
            self._pages[key].restore_state(pdata)
```

### 5. �?View �?save_state / restore_state

统一签名�?
```python
def save_state(self) -> dict:
    """�?JSON 序列化的状�?""

def restore_state(self, data: dict) -> None:
    """从字典恢�?UI 状态，�?__init__ 完成后调�?""
```

各页面保存的内容�?
| View | save_state 字段 |
|------|-----------------|
| QueryPage | search_text, sort_column, sort_order, v_scroll |
| EstimatePage | clipboard_text, sort_column, sort_order, v_scroll |
| IndustryPage | tab_index, bp_selector_index, sort_column, sort_order, v_scroll |
| TradePage | sort_column, sort_order, v_scroll |
| WatchlistPage | sort_column, sort_order, v_scroll |
| ContractPage | sort_column, sort_order, v_scroll |
| InventoryPage | sort_column, sort_order, v_scroll |

获取表格状态：

```python
header = table.horizontalHeader()
sort_col = header.sortIndicatorSection()
sort_order = 1 if header.sortIndicatorOrder() == Qt.AscendingOrder else 0
v_scroll = table.verticalScrollBar().value()

# 恢复
table.sortByColumn(col, Qt.AscendingOrder if order == 1 else Qt.DescendingOrder)
table.verticalScrollBar().setValue(v_scroll)
```

## 不保存的状�?
- 后台 QThread / 异步 worker（重启后�?_init_price_check 等自动重建）
- 数据库连接（重启重建�?- 托盘图标（重启后 _init_tray_icon 重建�?- 窗口几何（使用现有的 theme.save_window_geometry 机制，在 hot-reload 场景跳过以保证一致性）

## 握手容错

1. 进程未正常退出：dev.py �?proc.wait(5) 超时后执�?proc.terminate() + 再等 3 秒，仍不退出则 ǿ����ֹ (proc.kill\(\))
2. trigger 文件残留：main() 启动时会检测并清理残留�?trigger �?state 文件
3. state 文件损坏：json.load 失败时静默忽略，回退到正常启�?4. 手动关闭窗口：closeEvent 中无条件清理 trigger 文件

## 文件改动清单

```
新增:
  core/hot_reload.py       �?40 �?
修改:
  dev.py                   �?-15/+25 �?  Main.py                  �?+5 �?  main_window.py           �?+80 �?  query_view.py            �?+35 �?  estimate_view.py         �?+35 �?  industry_view.py         �?+40 �?  trade_view.py            �?+30 �?  watchlist_view.py        �?+30 �?  contract_view.py         �?+30 �?  inventory_view.py        �?+30 �?```

## 验收标准

1. python dev.py 启动 -> 文件变更 -> 自动重启 -> 页面/搜索状态恢�?2. python Main.py --hot-reload 首次启动 -> 没有 state 文件 -> 正常显示
3. 修改 QSS/theme 或逻辑代码 -> 触发重启 -> 恢复状�?4. 手动关闭窗口后触�?-> 清理 trigger 文件，无残留
