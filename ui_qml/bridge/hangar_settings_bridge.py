"""机库设置对话框的桥（阶段 4b 收尾）：机库配置（星系 / 设施 / 改件 / 税）+ 默认机库。

对照 Widgets 版 `ui_pyside6/views/hangar_settings_view.py` 的三个类：

- `HangarSettingsDialog` → `HangarSettingsQmlDialog`（宿主签名 `(main_window, parent=None)` 逐字不变）。
- `_HangarEditor` → 本桥里「每个机库一份工作状态」（`_configs`）+ QML 里的编辑区区块。
  Widgets 版把**所有** editor 都实例化并常驻 `QStackedWidget`，所以切机库时未保存的编辑
  不丢；这里同样把全部机库的工作状态都存在桥里，切行只换读哪一份，保存时一次性回落。
- `_DeleteHangarDialog` → 桥里的「两步确认」：`requestDelete()` 开确认条，`confirmDelete()`
  才真删（引用明细与改指下拉都在确认条里）。**不再弹 `QMessageBox` / 二级窗口** ——
  弹出它的机库设置本身已经是 QML 页面了。

`QInputDialog.getText` 换成 `InputQmlDialog.get_text`；`QMessageBox.warning` 换成桥的
`set_error` 通道。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Property, Signal, Slot

from services import inventory_manager, user_settings
from services.hangar_industry_config import (
    FACILITY_TYPE_LABELS,
    STRUCTURE_BASE,
    get_rig_catalog,
    resolve_hangar_industry_config,
    validate_rig_set,
)
from services.name_resolver import resolve_system_display_names_batch
from ui_qml.dialog_host import DialogBridge, QmlDialog

__all__ = [
    "HangarSettingsBridge",
    "HangarSettingsQmlDialog",
    "base_bonus_text",
    "rig_label",
]

_QML_FILE = "dialogs/HangarSettingsDialog.qml"

#: 「默认机库」Tab 的四行（逐字照搬原模块的 `_DEFAULT_HANGAR_KEYS`）
_DEFAULT_HANGAR_KEYS: list[tuple[str, str]] = [
    ("default_research_hangar_id", "科研机库"),
    ("default_mat_hangar_id", "制造材料机库"),
    ("default_deposit_hangar_id", "制造产出机库"),
    ("default_trade_hangar_id", "商业机库"),
]

#: 设施类型下拉的顺序（显示名取 `FACILITY_TYPE_LABELS`，与原 `addItem` 调用顺序一致）
_FACILITY_ORDER: tuple[str, ...] = ("npc", "raitaru", "azbel", "sotiyo")

#: 「不修改引用」那一项的 id —— 与 `_DeleteHangarDialog` 里 `addItem(..., None)` 同义
_NO_REPOINT = None


def base_bonus_text(facility_type: str | None) -> str:
    """「本体加成」说明行（逐字对齐原 `_on_facility_changed` 的两段赋值）。

    原实现先无条件写一行加成、再用第二个 `if` 覆盖成 NPC 文案；这里直接算出最终值，
    输出与原版一致（NPC 站永远显示「无结构本体加成」）。
    """
    base = STRUCTURE_BASE.get(facility_type or "npc")
    if not base or not base["rig_size"]:
        return "NPC 空间站无结构本体加成，不可装配改装件"
    return f"材料 {base['mat']} / 成本 {base['cost']} / 时间 {base['time']}（NPC=1.0）"


def rig_label(item: dict) -> str:
    """改件复选框文案（逐字对齐原 `_on_facility_changed` 里的拼装）。纯函数，便于单测。"""
    parts: list[str] = []
    if item["mat_bonus"]:
        parts.append(f"材料 {item['mat_bonus']:+.1f}%")
    if item["time_bonus"]:
        parts.append(f"时间 {item['time_bonus']:+.0f}%")
    bonus = "、".join(parts) if parts else "加成未拉取（运行数据初始化）"
    return f"{item['zh_name']}  [{bonus}]"


def summary_text(cfg: dict) -> str:
    """底部加成汇总（逐字对齐原 `_update_summary` 的拼接）。"""
    tax = cfg["facility_tax"] if cfg["facility_tax"] is not None else "跟随默认"
    return (
        f"当前加成: 材料 {cfg['structure_mat_saving']} / 时间 {cfg['structure_time_mod']} / "
        f"安装费 {cfg['structure_cost_mult']} | 设施税 {tax}"
    )


class HangarSettingsBridge(DialogBridge):
    """机库设置的 QML 后端。"""

    #: 机库列表（含星系后缀）与选中行重载
    hangarsChanged = Signal()
    #: 换机库 —— 只动编辑区的「读哪一份」
    currentChanged = Signal()
    #: 当前机库的可编辑字段变了（设施 / 税 / 改件 / 星系 / 汇总）
    editorChanged = Signal()
    #: 「默认机库」四行的选项或选中变了
    defaultsChanged = Signal()
    #: 删除确认条的开合
    confirmChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.set_title("机库设置")
        self._hangars: list[dict] = []
        self._labels: list[str] = []
        self._current_row = -1
        #: 每个机库的工作状态：切机库不丢未保存的编辑（对齐 Widgets 版常驻的 _HangarEditor）
        self._configs: dict[int, dict] = {}
        #: 星系显示名缓存（列表后缀与编辑区标签共用一次批量查询）
        self._system_texts: dict[int, str] = {}
        #: 改件目录缓存（同一设施类型不重复查库）
        self._catalogs: dict[str, list[dict]] = {}
        self._defaults: dict[str, dict] = {}
        self._pending_delete: dict | None = None
        #: 编辑区重建键。QML 里微调框 / 下拉的 `value:` / `currentIndex:` 是声明式绑定，
        #: 用户手动改一次就会**打断**绑定；换机库时若不重建，控件会留着上一个机库的值
        #: （`TransferDialog` 靠 ListView 重建规避，这里没有可用的 ListView）。
        self._editor_key = 0

        self._reload_hangars()
        self._build_defaults()

    # ══════════════════════════════════════════════════════════
    #  给 QML 的只读状态
    # ══════════════════════════════════════════════════════════

    @Property(list, constant=True)
    def facilityOptions(self) -> list[dict]:
        """设施类型下拉的选项（顺序即 `_FACILITY_ORDER`，`setFacilityIndex` 按同一序取）。"""
        return [{"label": FACILITY_TYPE_LABELS.get(key, key), "value": key} for key in _FACILITY_ORDER]

    @Property(list, notify=hangarsChanged)
    def hangarLabels(self) -> list[str]:
        return list(self._labels)

    @Property(int, notify=currentChanged)
    def currentRow(self) -> int:
        return self._current_row

    @Property(bool, notify=hangarsChanged)
    def hasHangars(self) -> bool:
        return bool(self._hangars)

    @Property(int, notify=currentChanged)
    def editorKey(self) -> int:
        """编辑区重建键（换机库 / 重载列表时变），QML 用它当 `Repeater` 的模型强制重建。"""
        return self._editor_key

    @Property(int, notify=editorChanged)
    def facilityIndex(self) -> int:
        cfg = self._current_config()
        if cfg is None:
            return 0
        ftype = cfg["facility_type"]
        return _FACILITY_ORDER.index(ftype) if ftype in _FACILITY_ORDER else 0

    @Property(str, notify=editorChanged)
    def baseBonusText(self) -> str:
        cfg = self._current_config()
        return base_bonus_text(cfg["facility_type"] if cfg else None)

    @Property(str, notify=editorChanged)
    def systemText(self) -> str:
        hangar = self._current_hangar()
        if hangar is None:
            return "未设置"
        return self._system_texts.get(int(hangar["id"]), "") or "未设置"

    @Property(bool, notify=editorChanged)
    def taxFollowDefault(self) -> bool:
        cfg = self._current_config()
        return bool(cfg["tax_follow_default"]) if cfg else True

    @Property(float, notify=editorChanged)
    def taxValue(self) -> float:
        cfg = self._current_config()
        return float(cfg["tax_value"]) if cfg else 0.25

    @Property(list, notify=editorChanged)
    def rigGroups(self) -> list[dict]:
        """改件区：按制造类别分组 → `[{label, items: [{typeId, text, checked}]}]`。"""
        cfg = self._current_config()
        if cfg is None:
            return []
        catalog = self._catalog(cfg["facility_type"])
        checked = {int(r) for r in cfg["rig_ids"]}
        grouped: dict[str, list[dict]] = {}
        for item in catalog:
            grouped.setdefault(item["category_key"], []).append(item)
        return [
            {
                "label": items[0]["category_label"] if items else "",
                "items": [
                    {"typeId": int(it["type_id"]), "text": rig_label(it), "checked": int(it["type_id"]) in checked}
                    for it in items
                ],
            }
            for items in grouped.values()
        ]

    @Property(str, notify=editorChanged)
    def summaryText(self) -> str:
        cfg = self._current_config()
        return str(cfg["summary"]) if cfg else ""

    @Property(list, notify=defaultsChanged)
    def defaultRows(self) -> list[dict]:
        """默认机库四行 → `[{key, label, options: [{label, id}], index}]`。"""
        rows: list[dict] = []
        for row in self._defaults.values():
            ids = [o["id"] for o in row["options"]]
            selected = row["selected"]
            rows.append(
                {
                    "key": row["key"],
                    "label": row["label"],
                    "options": [dict(o) for o in row["options"]],
                    "index": ids.index(selected) if selected in ids else 0,
                }
            )
        return rows

    # ── 删除确认条 ──

    @Property(bool, notify=confirmChanged)
    def confirmVisible(self) -> bool:
        return self._pending_delete is not None

    @Property(str, notify=confirmChanged)
    def confirmTitle(self) -> str:
        return str(self._pending_delete["title"]) if self._pending_delete else ""

    @Property(list, notify=confirmChanged)
    def confirmReferences(self) -> list[str]:
        return list(self._pending_delete["references"]) if self._pending_delete else []

    @Property(str, notify=confirmChanged)
    def confirmNote(self) -> str:
        return str(self._pending_delete["note"]) if self._pending_delete else ""

    @Property(bool, notify=confirmChanged)
    def showRepoint(self) -> bool:
        """只有「被引用」的机库才给改指下拉 —— 与 Widgets 版只在有引用时弹该对话框一致。"""
        return bool(self._pending_delete and self._pending_delete["references"])

    @Property(list, notify=confirmChanged)
    def repointOptions(self) -> list[dict]:
        return [dict(o) for o in self._pending_delete["options"]] if self._pending_delete else []

    @Property(int, notify=confirmChanged)
    def repointIndex(self) -> int:
        return int(self._pending_delete["index"]) if self._pending_delete else 0

    # ══════════════════════════════════════════════════════════
    #  加载
    # ══════════════════════════════════════════════════════════

    def _reload_hangars(self, *, select_row: int | None = None, select_id: int | None = None) -> None:
        """重取机库列表 + 重建全部工作状态（原 `_reload_hangars`）。

        原版每次重载都会**重建全部 editor**（未保存的编辑随之丢弃）—— 新建 / 重命名 /
        删除之后重建是刻意的（那些操作会改 id 与列表），这里保持一致。

        `select_id` 给「新建机库」用：新机库的 id 只有落库后才知道，按 id 找回行号
        （原版是按列表文本找的，重名不可能但有星系后缀时会找不中）。
        """
        self._hangars = [dict(h) for h in inventory_manager.get_hangars()]
        sids = [int(h["solar_system_id"]) for h in self._hangars if h.get("solar_system_id")]
        names = resolve_system_display_names_batch(sids)

        self._labels = []
        self._system_texts = {}
        self._configs = {}
        for hangar in self._hangars:
            hid = int(hangar["id"])
            sid = hangar.get("solar_system_id")
            text = names.get(int(sid), "") if sid else ""
            self._system_texts[hid] = text
            self._labels.append(f"{hangar['name']} ({text})" if text else str(hangar["name"]))
            self._configs[hid] = self._load_config(hangar)

        self._catalogs.clear()
        self._editor_key += 1
        if select_id is not None:
            select_row = next((i for i, h in enumerate(self._hangars) if int(h["id"]) == int(select_id)), None)
        if select_row is not None and 0 <= select_row < len(self._hangars):
            self._current_row = select_row
        else:
            self._current_row = 0 if self._hangars else -1
        self._refresh_defaults()
        self.hangarsChanged.emit()
        self.currentChanged.emit()
        self.editorChanged.emit()

    def _load_config(self, hangar: dict) -> dict:
        """读该机库的既有配置 → 工作状态（对应 `_HangarEditor._load_current`）。"""
        cfg = resolve_hangar_industry_config(hangar["id"])
        ftype = str(cfg["facility_type"] or "npc")
        # 非法设施类型（理论上不会出现：该列只由本对话框写）归一到 NPC，
        # 否则下拉的 currentIndex 会是 -1、显示成空框。
        if ftype not in _FACILITY_ORDER:
            ftype = "npc"
        tax = cfg["facility_tax"]
        return {
            "facility_type": ftype,
            "tax_follow_default": tax is None,
            # 原版「跟随默认」时微调框留在构造期的 0.25（`setValue(0.25)`），照搬
            "tax_value": float(tax) if tax is not None else 0.25,
            "rig_ids": [int(r) for r in cfg["rig_ids"]],
            "summary": summary_text(cfg),
        }

    def _build_defaults(self) -> None:
        """「默认机库」四行的初始选项与选中值（原 `_build_defaults_tab`）。"""
        settings = user_settings.load_settings()
        self._defaults = {}
        for key, label in _DEFAULT_HANGAR_KEYS:
            val = settings.get(key)
            self._defaults[key] = {
                "key": key,
                "label": label,
                "selected": int(val) if val is not None else -1,
                "options": [],
            }
        self._refresh_defaults()

    def _refresh_defaults(self) -> None:
        """按当前机库列表重建四行下拉（保留已选值；新建 / 删除后同步）。

        已选机库若已被删除，把原值作为一个可见项保留 —— 否则保存时会被静默清空
        （用户感知为「默认机库设置老是丢失」）。构造期 `_defaults` 还是空的，直接返回。
        """
        if not self._defaults:
            return
        known = {int(h["id"]) for h in self._hangars}
        for row in self._defaults.values():
            selected = int(row["selected"])
            options: list[dict] = [{"label": "未设置", "id": -1}]
            options.extend({"label": str(h["name"]), "id": int(h["id"])} for h in self._hangars)
            if selected != -1 and selected not in known:
                options.append({"label": f"（已删除的机库 #{selected}）", "id": selected})
            row["options"] = options
        self.defaultsChanged.emit()

    # ── 内部取值 ──────────────────────────────────────────────

    def _current_hangar(self) -> dict | None:
        if 0 <= self._current_row < len(self._hangars):
            return self._hangars[self._current_row]
        return None

    def _current_config(self) -> dict | None:
        hangar = self._current_hangar()
        return self._configs.get(int(hangar["id"])) if hangar is not None else None

    def _catalog(self, facility_type: str) -> list[dict]:
        if facility_type not in self._catalogs:
            self._catalogs[facility_type] = list(get_rig_catalog(facility_type))
        return self._catalogs[facility_type]

    # ══════════════════════════════════════════════════════════
    #  机库列表 / 选中
    # ══════════════════════════════════════════════════════════

    @Slot(int)
    def selectHangar(self, row: int) -> None:
        if not 0 <= row < len(self._hangars) or row == self._current_row:
            return
        self._current_row = row
        self._editor_key += 1
        self.currentChanged.emit()
        self.editorChanged.emit()

    # ══════════════════════════════════════════════════════════
    #  编辑区
    # ══════════════════════════════════════════════════════════

    @Slot(int)
    def setFacilityIndex(self, index: int) -> None:
        """换设施类型 → 清空已选改件（原版重建改件区后不会回勾，等同清空）。"""
        cfg = self._current_config()
        if cfg is None or not 0 <= index < len(_FACILITY_ORDER):
            return
        ftype = _FACILITY_ORDER[index]
        if ftype == cfg["facility_type"]:
            return
        cfg["facility_type"] = ftype
        cfg["rig_ids"] = []
        if not STRUCTURE_BASE.get(ftype, {}).get("rig_size"):
            cfg["summary"] = "NPC 空间站无结构改装件"
        self.editorChanged.emit()

    @Slot(bool)
    def setTaxFollowDefault(self, follow: bool) -> None:
        cfg = self._current_config()
        if cfg is None:
            return
        cfg["tax_follow_default"] = bool(follow)
        self.editorChanged.emit()

    @Slot(float)
    def setTaxValue(self, value: float) -> None:
        cfg = self._current_config()
        if cfg is None:
            return
        cfg["tax_value"] = float(value)
        self.editorChanged.emit()

    @Slot(int, bool)
    def setRigChecked(self, type_id: int, checked: bool) -> None:
        """勾选 / 取消一个改件；同制造类别互斥（原 `_on_rig_toggled` 的等价物）。

        用 `type_id` 而不是「组号 + 行号」：QML 那边嵌套 `Repeater` 的组号容易在模型
        重建后错位，而 type_id 是稳定标识。
        """
        cfg = self._current_config()
        if cfg is None:
            return
        catalog = self._catalog(cfg["facility_type"])
        item = next((c for c in catalog if int(c["type_id"]) == int(type_id)), None)
        if item is None:
            return
        same_category = {int(c["type_id"]) for c in catalog if c["category_key"] == item["category_key"]}
        rigs = [int(r) for r in cfg["rig_ids"] if int(r) not in same_category]
        if checked:
            rigs.append(int(type_id))
        order = {int(c["type_id"]): i for i, c in enumerate(catalog)}
        cfg["rig_ids"] = sorted(rigs, key=lambda r: order.get(r, 0))
        self.editorChanged.emit()

    @Slot()
    def pickSystem(self) -> None:
        """「选择星系…」—— 复用已迁好的星系搜索对话框（原 `_on_select_system`）。"""
        from ui_qml.bridge.system_search_bridge import SystemSearchQmlDialog

        dialog = SystemSearchQmlDialog(self.host_widget(), "设置机库星系")
        if dialog.exec():
            selected = dialog.get_selected()
            if selected:
                self.apply_system(int(selected[0]), str(selected[1]))

    def apply_system(self, solar_system_id: int, system_name: str) -> None:
        """落库 + 刷新显示（从 `pickSystem` 抽出来，便于单测不依赖真弹窗）。"""
        hangar = self._current_hangar()
        if hangar is None:
            return
        hid = int(hangar["id"])
        inventory_manager.update_hangar_system(hid, int(solar_system_id))
        hangar["solar_system_id"] = int(solar_system_id)
        self._system_texts[hid] = system_name
        self._labels[self._current_row] = f"{hangar['name']} ({system_name})" if system_name else str(hangar["name"])
        self.hangarsChanged.emit()
        self.editorChanged.emit()

    @Slot()
    def clearSystem(self) -> None:
        hangar = self._current_hangar()
        if hangar is None:
            return
        hid = int(hangar["id"])
        inventory_manager.update_hangar_system(hid, None)
        hangar["solar_system_id"] = None
        self._system_texts[hid] = ""
        self._labels[self._current_row] = str(hangar["name"])
        self.hangarsChanged.emit()
        self.editorChanged.emit()

    # ══════════════════════════════════════════════════════════
    #  增 / 改 / 删
    # ══════════════════════════════════════════════════════════

    @Slot()
    def newHangar(self) -> None:
        from ui_qml.bridge.input_dialog import InputQmlDialog

        name, ok = InputQmlDialog.get_text(self.host_widget(), "新建机库", "机库名:")
        if not (ok and name.strip()):
            return
        new_id = inventory_manager.create_hangar(name.strip())
        if new_id == -1:
            self.set_error("机库名已存在")
            return
        self.set_error("")
        self._reload_hangars(select_id=int(new_id))

    @Slot()
    def renameHangar(self) -> None:
        from ui_qml.bridge.input_dialog import InputQmlDialog

        hangar = self._current_hangar()
        if hangar is None:
            return
        old = self._labels[self._current_row]
        name, ok = InputQmlDialog.get_text(self.host_widget(), "重命名", "新名称:", text=old)
        if ok and name.strip() and name != old:
            inventory_manager.rename_hangar(int(hangar["id"]), name.strip())
            self._reload_hangars(select_row=self._current_row)

    @Slot()
    def requestDelete(self) -> None:
        """第一步：算引用明细并开确认条（原 `_on_delete_hangar` 的前半段）。"""
        hangar = self._current_hangar()
        if hangar is None:
            return
        hid = int(hangar["id"])
        name = self._labels[self._current_row]
        references = list(inventory_manager.hangar_references(hid))
        if references:
            title = f"「{name}」正被以下位置引用："
            note = "删除会一并移除该机库内的物品与蓝图（不可撤销）。"
            others = [h for h in inventory_manager.get_hangars() if int(h["id"]) != hid]
            options: list[dict] = [{"label": "不修改（保留原引用）", "id": _NO_REPOINT}]
            options.extend({"label": str(h["name"]), "id": int(h["id"])} for h in others)
        else:
            # 无引用：与原版一样只问一句，不给改指下拉
            title = f"删除机库「{name}」及其所有物品？"
            note = ""
            options = []
        self._pending_delete = {
            "id": hid,
            "references": references,
            "title": title,
            "note": note,
            "options": options,
            "index": 0,
        }
        self.set_error("")
        self.confirmChanged.emit()

    @Slot()
    def confirmDelete(self) -> None:
        """第二步：真删。有引用时带上改指目标（原 `_DeleteHangarDialog` + `delete_hangar`）。"""
        pending = self._pending_delete
        if pending is None:
            return
        references = list(pending["references"])
        repoint = self.repoint_to()
        self._pending_delete = None
        if references:
            inventory_manager.delete_hangar(int(pending["id"]), repoint_to=repoint)
        else:
            inventory_manager.delete_hangar(int(pending["id"]))
        self._reload_hangars()
        self.confirmChanged.emit()

    @Slot()
    def cancelDelete(self) -> None:
        if self._pending_delete is None:
            return
        self._pending_delete = None
        self.confirmChanged.emit()

    @Slot(int)
    def setRepointIndex(self, index: int) -> None:
        if self._pending_delete is None or not 0 <= index < len(self._pending_delete["options"]):
            return
        self._pending_delete["index"] = int(index)
        self.confirmChanged.emit()

    def repoint_to(self) -> int | None:
        """确认条里选中的替换机库 id；「不修改」返回 None（名字与原访问器一致）。

        无引用的那条路径根本没有下拉（`options` 为空），也要返回 None ——
        否则 `confirmDelete` 会在这里越界。
        """
        pending = self._pending_delete
        if pending is None or not pending["options"]:
            return None
        value = pending["options"][int(pending["index"])]["id"]
        return int(value) if value is not None else None

    # ══════════════════════════════════════════════════════════
    #  默认机库
    # ══════════════════════════════════════════════════════════

    @Slot(str, int)
    def setDefaultIndex(self, key: str, index: int) -> None:
        row = self._defaults.get(key)
        if row is None or not 0 <= index < len(row["options"]):
            return
        row["selected"] = int(row["options"][index]["id"])
        self.defaultsChanged.emit()

    # ══════════════════════════════════════════════════════════
    #  保存
    # ══════════════════════════════════════════════════════════

    @Slot()
    def accept(self) -> None:
        """保存：先校验**所有**机库的改件，再逐个落库 + 写默认机库（原 `_on_save`）。"""
        for cfg in self._configs.values():
            problems = validate_rig_set([int(r) for r in cfg["rig_ids"]], cfg["facility_type"])
            if problems:
                self.set_error("机库配置有误：\n" + "\n".join(problems[:5]))
                return
        for hid, cfg in self._configs.items():
            tax = None if cfg["tax_follow_default"] else float(cfg["tax_value"])
            inventory_manager.update_hangar_config(hid, cfg["facility_type"], tax, [int(r) for r in cfg["rig_ids"]])
        for key, row in self._defaults.items():
            selected = int(row["selected"])
            user_settings.set_default_hangar_id(key, None if selected == -1 else selected)
        # 保存成功 → 清掉可能还挂在界面上的一条旧提示（如「机库名已存在」）
        self.set_error("")
        self.accepted.emit()


class HangarSettingsQmlDialog(QmlDialog):
    """QML 版「机库设置」。`HangarSettingsDialog(main_window, parent=None)` 的调用方只换类名。"""

    def __init__(self, main_window: Any, parent: Any = None) -> None:
        bridge = HangarSettingsBridge()
        super().__init__(_QML_FILE, bridge, parent=parent or main_window, size=(860, 620))
        self._hangar_bridge = bridge
