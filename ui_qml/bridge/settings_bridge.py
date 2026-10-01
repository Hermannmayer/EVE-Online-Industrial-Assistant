"""系统设置对话框的桥（阶段 4b）：主题卡片选择器 + ESI/数据 · 外观 · 默认参数。

对照 Widgets 版 `ui_pyside6/views/settings_view.SettingsDialog` 与
`ui_pyside6/views/theme_selector.ThemeSelector`。两者必须同一个桥族：

- `SettingsDialog` 里**嵌着** `ThemeSelector`，拆成两个模块会留下跨模块的 Widgets 依赖；
- 主题卡片点击要**立刻切主题**（`theme.apply_theme`），再回填到宿主的“应用/确定”流程 ——
  这条链只有放在一起才看得清。

**业务逻辑一行没重写**：全部委托 `ui_qml.theme.registry` 与宿主 main_window 上既有方法
（`_save_settings` / `_start_price_timer` / `_show_init_wizard` …），与原版逐条对齐。

`ThemeSelectorBridge` 不是对话框，只是个 QObject 驱动的组件源（见 `FThemeCards.qml`），
但保留了原 `ThemeSelector` 的同名 Python 访问器（`current_theme_id` / `set_current`），
主流程若要把它单独接到别处，按同样的两个方法驱动即可。
"""

from __future__ import annotations

import os
import weakref
from typing import Any

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot
from PySide6.QtWidgets import QWidget

from services import db_backup, user_settings
from services.user_settings import BACKUP_KEEP_ALLOWED, BACKUP_KEEP_DEFAULT
from ui_qml.dialog_host import DialogBridge, QmlDialog
from ui_qml.file_dialogs import get_save_filename
from ui_qml.theme import registry as theme

__all__ = ["SettingsBridge", "SettingsQmlDialog", "ThemeSelectorBridge"]

_QML_FILE = "dialogs/SettingsDialog.qml"

#: 卡片上预览的三个色块（与 Widgets 版 `_SWATCH_KEYS` 同序同源）
_SWATCH_KEYS = ("BG_SURFACE", "PRIMARY", "TEXT_PRIMARY")


class ThemeSelectorBridge(QObject):
    """主题卡片网格的数据源（对齐 `theme_selector.ThemeSelector` 的对外接口）。

    色值**只能**来自 `theme.THEME_REGISTRY`：卡片要预览“各主题自己长什么样”，
    当前主题的 token 恰好不是它要显示的东西，写死或借用 `Theme.xxx` 都会预览错。
    """

    changed = Signal()
    #: 用户点了某张卡片（切换已即时生效并持久化，此信号只通知宿主要刷新状态）
    themeSelected = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._current_id: str = theme.current_theme()
        # 绑定方法 → theme 内部用 WeakMethod 存，桥被回收时监听自动失效，不必手动注销
        theme.add_theme_listener(self._on_theme_changed)

    # ── QML 读 ────────────────────────────────────────────────

    themes = Property(
        list,
        lambda self: [
            {
                "id": spec["id"],
                "name": spec["name_zh"],
                "badge": "暗" if spec["mode"] == "dark" else "亮",
                "material": spec["material"],
                "swatches": [{"color": spec["colors"][k], "border": spec["colors"]["BORDER"]} for k in _SWATCH_KEYS],
            }
            for spec in theme.THEME_REGISTRY.values()
        ],
        constant=True,
    )

    @Property(str, notify=changed)
    def currentThemeId(self) -> str:
        return self._current_id

    # ── QML 写 ────────────────────────────────────────────────

    @Slot(str)
    def setCurrentTheme(self, theme_id: str) -> None:
        """卡片点击：立即切换。

        `apply_theme` 内部会持久化偏好并通知所有主题监听器（含主窗口重刷 QSS），
        所以这里**不做** Widgets 版那套 `setUpdatesEnabled(False)` 防闪烁 ——
        QML 侧换色由场景图合成，不存在中间态。

        改完由 `_on_theme_changed` 回填 `currentThemeId`，QML 的选中描边自己跟上。
        """
        if theme_id == self._current_id or theme_id not in theme.THEME_REGISTRY:
            return
        theme.apply_theme(theme_id)
        self.themeSelected.emit(theme_id)

    # ── 给 Python 调用方（与原 ThemeSelector 同名）─────────────

    def current_theme_id(self) -> str:
        return self._current_id

    def set_current(self, theme_id: str) -> None:
        """同步选中态（不触发切换/持久化）—— 同原版 `ThemeSelector.set_current`。"""
        self._current_id = theme_id
        self.changed.emit()

    def _on_theme_changed(self) -> None:
        self.set_current(theme.current_theme())


def _hold_host(widget: Any) -> tuple[weakref.ref[Any] | None, Any]:
    """决定怎么持有宿主：**QWidget 宿主必须弱引用**，其余原样强引用。

    为什么 QWidget 特殊：`SettingsQmlDialog` 会把宿主当作对话框的 Qt 父窗口
    （`parent=parent or main_window`，为了居中/模态），于是
    「宿主（C++ 父）→ 对话框（Python 包装）→ 桥 → 宿主」连成一个**跨所有权的引用环**。
    Python 的 GC 会在**任意分配点**收这个环，而析构顺序会跨过 Qt 的父子边界 ——
    实测直接 access violation，且崩点还在**别处**（`-m ui` 全量档偶发崩在 storage 页的
    fixture 拆除里，一路追到这里）。

    普通 Python 对象（测试替身、控制器）没有 Qt 父子关系，连不成环，强引用无害；
    对它弱引用反而有害：`SettingsBridge(_Host())` 这种「宿主是临时对象」的写法会立刻丢失宿主，
    桥静默空转（原有用例当场变红）。
    """
    if isinstance(widget, QWidget):
        return weakref.ref(widget), None
    return None, widget


class SettingsBridge(DialogBridge):
    """系统设置对话框的桥。宿主 main_window 可为 None（只读展示，不落设置）。"""

    stateChanged = Signal()

    def __init__(self, main_window: Any = None) -> None:
        super().__init__()
        self.set_title("系统设置")
        self._mw_ref, self._mw_strong = _hold_host(main_window)
        self._themes = ThemeSelectorBridge(self)
        self._interval = 0
        self._auto_update = False
        self._font_size = theme.BASE_FONT_PX
        #: 备份设置**直接落 `services.user_settings`**，不走宿主 `_save_settings()` ——
        #: 那三个键（间隔/自动更新/区域）属于外壳，备份不属于，塞进去就是两个来源。
        self._backup_enabled = True
        self._backup_keep = BACKUP_KEEP_DEFAULT
        #: 「立即备份 / 导出」的结果回显（失败也要说话，否则用户以为点了没反应）
        self._backup_status = ""
        self.reload_state()

    @property
    def _mw(self) -> Any:
        """当前宿主（QWidget 宿主可能已被回收 → None）。见 `_hold_host` 的说明。"""
        return self._mw_ref() if self._mw_ref is not None else self._mw_strong

    # ── 主题选择器（内嵌组件）──────────────────────────────────

    @Property(QObject, constant=True)
    def themeSelector(self) -> ThemeSelectorBridge:
        return self._themes

    # ── 表单字段 ──────────────────────────────────────────────

    @Property(int, notify=stateChanged)
    def interval(self) -> int:
        return self._interval

    #: 原 `QSpinBox.setRange(0, 1440)`；步长 5 由 QML 侧写（与 `setSingleStep(5)` 对应）
    intervalMax = Property(int, lambda self: 1440, constant=True)

    @Property(bool, notify=stateChanged)
    def autoUpdate(self) -> bool:
        return self._auto_update

    @Property(int, notify=stateChanged)
    def fontSize(self) -> int:
        return self._font_size

    #: 原 `QSpinBox.setRange(10, 20)`
    fontSizeMin = Property(int, lambda self: 10, constant=True)
    fontSizeMax = Property(int, lambda self: 20, constant=True)

    @Slot(int)
    def setInterval(self, minutes: int) -> None:
        self._interval = int(minutes)
        self.stateChanged.emit()

    @Slot(bool)
    def setAutoUpdate(self, enabled: bool) -> None:
        self._auto_update = bool(enabled)
        self.stateChanged.emit()

    @Slot(int)
    def setFontSize(self, px: int) -> None:
        self._font_size = int(px)
        self.stateChanged.emit()

    # ── 用户数据备份（设置页「备份」标签）──────────────────────

    @Property(bool, notify=stateChanged)
    def backupEnabled(self) -> bool:
        """是否每天自动备份用户数据（user.db）。"""
        return self._backup_enabled

    @Property(int, notify=stateChanged)
    def backupKeep(self) -> int:
        """最多保留几份备份。"""
        return self._backup_keep

    #: 保留份数的可选项 —— 设置页的下拉只给这几个（白名单在 `user_settings` 里兜底）
    backupKeepOptions = Property(list, lambda self: list(BACKUP_KEEP_ALLOWED), constant=True)

    @Property(str, notify=stateChanged)
    def backupStatus(self) -> str:
        """上一次「立即备份 / 导出」的结果文案；空串 = 本次打开还没操作过。"""
        return self._backup_status

    @Slot(bool)
    def setBackupEnabled(self, enabled: bool) -> None:
        """开关**即时落盘** —— 与主题卡片同样「点了就生效」，不吃「应用/确定」。"""
        self._backup_enabled = bool(enabled)
        user_settings.set_backup_enabled(self._backup_enabled)
        self.stateChanged.emit()

    @Slot(int)
    def setBackupKeep(self, keep: int) -> None:
        """保留份数即时落盘；**回读**一次，让白名单兜底后的真实值回到界面。"""
        user_settings.set_backup_keep(int(keep))
        self._backup_keep = user_settings.get_backup_keep()
        self.stateChanged.emit()

    @Slot()
    def backupNow(self) -> None:
        """立即备份一份 —— 手动入口**不受「每天一次」限制**（用户点了就该备）。"""
        path = db_backup.backup_user_db(keep=self._backup_keep)
        if path is None:
            self._set_backup_status("备份失败，详见日志")
            return
        self._set_backup_status(f"已备份 {os.path.basename(path)}（现有 {len(db_backup.list_backups())} 份）")

    @Slot()
    def exportNow(self) -> None:
        """把 user.db 导出到用户选定的位置（原生保存框）。"""
        parent = self._mw if isinstance(self._mw, QWidget) else None
        dest = get_save_filename(parent, "eve-user-data.db", "SQLite 数据库 (*.db)")
        if not dest:
            return
        path = db_backup.export_user_db(dest)
        self._set_backup_status(f"已导出到 {path}" if path else "导出失败，详见日志")

    @Property(list, notify=stateChanged)
    def backupItems(self) -> list[str]:
        """已有备份的**文件名**（新的在前）—— 设置页那个「还原到」下拉直接用。

        随 `stateChanged` 重读：点完「立即备份」列表立刻多一份，不用重开设置。
        """
        return [os.path.basename(p) for p in db_backup.list_backups()]

    @Slot(int)
    def restoreBackup(self, index: int) -> None:
        """用选中的那份备份覆盖当前用户数据。

        `restore_user_db` **会先把「现在这个库」也备一份**，所以选错了还能退回来。
        还原成功后**必须重启应用**：外壳/页面/桥里全是旧库的数据与缓存，不重启会看到
        「还原了但界面没变」，之后任何一次写回都可能把旧数据盖到新库上。
        """
        paths = db_backup.list_backups()
        if not 0 <= index < len(paths):
            return
        target = paths[index]
        if not db_backup.restore_user_db(target):
            self._set_backup_status("还原失败，详见日志")
            return
        self._set_backup_status(f"已还原 {os.path.basename(target)} —— 请重启应用让界面读到新数据")

    def _set_backup_status(self, text: str) -> None:
        self._backup_status = text
        self.stateChanged.emit()

    # ── 状态同步 ──────────────────────────────────────────────

    def reload_state(self) -> None:
        """从 main_window / theme 读当前设置（原 `_load_state`）。

        用 `getattr` 取默认值而不是直接取属性：宿主可能是测试替身或精简窗口，
        缺字段时应当保持出厂值，而不是把对话框整个炸掉。
        """
        if self._mw is not None:
            self._interval = int(getattr(self._mw, "_update_interval_minutes", 0))
            self._auto_update = bool(getattr(self._mw, "_auto_update_enabled", False))
        self._font_size = round(theme.BASE_FONT_PX * theme.FONT_SCALE)
        self._backup_enabled = user_settings.get_backup_enabled()
        self._backup_keep = user_settings.get_backup_keep()
        self._themes.set_current(theme.current_theme())
        self.stateChanged.emit()

    # ── 按钮 ──────────────────────────────────────────────────

    @Slot()
    def apply(self) -> None:
        """「应用」：写回宿主与主题（不关窗）—— 逐条对齐原 `_on_apply`。"""
        mw = self._mw
        if mw is None:
            return

        if hasattr(mw, "_update_interval_minutes"):
            mw._update_interval_minutes = self._interval
        if hasattr(mw, "_auto_update_enabled"):
            mw._auto_update_enabled = self._auto_update

        # 主题：卡片点击已即时生效，这里只兜底（例如 Python 侧改了选择器状态）
        new_theme = self._themes.current_theme_id()
        if new_theme != theme.current_theme():
            theme.apply_theme(new_theme)
            self._notify_theme_changed()

        # 全局字号：改缩放并重放主题（`set_font_scale` 内部就会重放，各页面随之重套样式）
        new_scale = self._font_size / theme.BASE_FONT_PX
        if abs(new_scale - theme.FONT_SCALE) > 1e-6:
            theme.set_font_scale(new_scale)
            theme.save_font_scale(new_scale)
            self._notify_theme_changed()

        if hasattr(mw, "_save_settings"):
            mw._save_settings()

        # 重启 / 停掉价格定时器（间隔为 0 视为关闭）
        if self._auto_update and self._interval > 0:
            if hasattr(mw, "_start_price_timer"):
                mw._start_price_timer()
        elif hasattr(mw, "_stop_price_timer"):
            mw._stop_price_timer()

        status = getattr(mw, "_status_label", None)
        if status is not None:
            status.setText(f"设置已保存（间隔: {self._interval} 分钟）")

    @Slot()
    def accept(self) -> None:
        """「确定」：先应用再关窗（原 `_on_save` → `_on_apply` + `accept`）。"""
        self.apply()
        self.accepted.emit()

    @Slot()
    def openInitWizard(self) -> None:
        """「数据初始化」：先关掉设置，等 exec 返回、主事件循环恢复后再弹向导。

        直接在这里 show 会在 exec 的嵌套循环里再开一个模态窗，原版就是用
        `QTimer.singleShot(0)` 排到下一个事件循环 —— 这条时序不能省。
        """
        mw = self._mw
        if mw is None or not hasattr(mw, "_show_init_wizard"):
            return
        self.accepted.emit()  # 关掉本对话框，退出 exec
        QTimer.singleShot(0, mw._show_init_wizard)

    @Slot()
    def openAbout(self) -> None:
        mw = self._mw
        if mw is not None and hasattr(mw, "_show_about"):
            mw._show_about()

    def _notify_theme_changed(self) -> None:
        mw = self._mw
        if mw is not None and hasattr(mw, "_on_theme_changed"):
            mw._on_theme_changed()


class SettingsQmlDialog(QmlDialog):
    """QML 版系统设置。`SettingsDialog(main_window, parent)` 的调用方原样可用。"""

    def __init__(self, main_window: Any, parent: Any = None) -> None:
        bridge = SettingsBridge(main_window)
        # 原版 `super().__init__(parent or main_window)`：没给 parent 就拿主窗口兜底（居中用）
        super().__init__(_QML_FILE, bridge, parent=parent or main_window, size=(560, 520))
        self._settings_bridge = bridge
