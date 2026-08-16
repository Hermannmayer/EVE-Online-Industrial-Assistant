"""机库设置对话框 — 独立一级入口（全局工具栏「🏭 机库设置」）。

每个机库可配置：所在星系（SCI）、设施类型（结构本体基础加成）、结构改装件
（材料/时间效率钻机，加成数值来自 structure_rigs 表）、设施税。
另有「默认机库」Tab：科研/制造材料/制造产出/商业 4 个默认机库（读写 settings.json）。
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import ui_pyside6.theme as theme
from services import inventory_manager, user_settings
from services.hangar_industry_config import (
    STRUCTURE_BASE,
    get_rig_catalog,
    resolve_hangar_industry_config,
    validate_rig_set,
)

_DEFAULT_HANGAR_KEYS = [
    ("default_research_hangar_id", "科研机库"),
    ("default_mat_hangar_id", "制造材料机库"),
    ("default_deposit_hangar_id", "制造产出机库"),
    ("default_trade_hangar_id", "商业机库"),
]


def _system_name(solar_system_id: int | None) -> str:
    """查询星系显示名（中文 (英文)，机库列表/配置面板显示）。"""
    from services.name_resolver import resolve_system_display_name

    return resolve_system_display_name(solar_system_id)


class _HangarEditor(QWidget):
    """单个机库的配置面板（星系/设施类型/设施税/改装件）。"""

    def __init__(self, hangar: dict, parent=None):
        super().__init__(parent)
        self._hangar = hangar
        self._rig_cbs: list[tuple[QCheckBox, dict]] = []  # (cb, rig_catalog_item)
        self._build_ui()
        self._load_current()

    # ── UI ─────────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # 星系
        sys_group = QGroupBox("所在星系（成本指数）")
        sg = QHBoxLayout(sys_group)
        self._sys_label = QLabel("未设置")
        sg.addWidget(self._sys_label, 1)
        sel_btn = QPushButton("选择星系…")
        sel_btn.clicked.connect(self._on_select_system)
        sg.addWidget(sel_btn)
        clear_btn = QPushButton("清除")
        clear_btn.clicked.connect(self._on_clear_system)
        sg.addWidget(clear_btn)
        layout.addWidget(sys_group)

        # 设施类型
        fac_group = QGroupBox("设施类型（结构本体加成）")
        fg = QFormLayout(fac_group)
        self._facility_combo = QComboBox()
        self._facility_combo.addItem("NPC 空间站", "npc")
        self._facility_combo.addItem("莱塔卢 (Raitaru, 中)", "raitaru")
        self._facility_combo.addItem("阿兹贝尔 (Azbel, 大)", "azbel")
        self._facility_combo.addItem("索迪约 (Sotiyo, 超大)", "sotiyo")
        self._facility_combo.currentIndexChanged.connect(self._on_facility_changed)
        fg.addRow("设施类型:", self._facility_combo)
        self._fac_base_label = QLabel("")
        fg.addRow("本体加成:", self._fac_base_label)
        layout.addWidget(fac_group)

        # 设施税
        tax_group = QGroupBox("设施税")
        tg = QHBoxLayout(tax_group)
        self._tax_spin = QDoubleSpinBox()
        self._tax_spin.setRange(0, 100)
        self._tax_spin.setDecimals(3)
        self._tax_spin.setSuffix(" %")
        self._tax_spin.setValue(0.25)
        tg.addWidget(self._tax_spin)
        self._tax_default_cb = QCheckBox("跟随默认（不单独设置）")
        self._tax_default_cb.setChecked(True)
        self._tax_default_cb.toggled.connect(lambda c: self._tax_spin.setEnabled(not c))
        tg.addWidget(self._tax_default_cb)
        tg.addStretch()
        layout.addWidget(tax_group)

        # 结构改装件
        rig_group = QGroupBox("结构改装件（每制造类别最多 1 个）")
        rg = QVBoxLayout(rig_group)
        self._rig_scroll = QScrollArea()
        self._rig_scroll.setWidgetResizable(True)
        self._rig_container = QWidget()
        self._rig_layout = QVBoxLayout(self._rig_container)
        self._rig_layout.setContentsMargins(0, 0, 0, 0)
        self._rig_scroll.setWidget(self._rig_container)
        rg.addWidget(self._rig_scroll, 1)
        layout.addWidget(rig_group, 1)

        # 加成汇总 + 保存
        self._summary_label = QLabel("")
        self._summary_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
        layout.addWidget(self._summary_label)

    # ── 加载 ───────────────────────────────────────────────

    def _load_current(self):
        cfg = resolve_hangar_industry_config(self._hangar["id"])
        ftype = cfg["facility_type"] or "npc"
        idx = self._facility_combo.findData(ftype)
        if idx >= 0:
            self._facility_combo.setCurrentIndex(idx)
        # 星系
        sys_name = _system_name(self._hangar.get("solar_system_id"))
        self._sys_label.setText(sys_name or "未设置")
        # 设施税
        if cfg["facility_tax"] is not None:
            self._tax_spin.setValue(float(cfg["facility_tax"]))
            self._tax_default_cb.setChecked(False)
        else:
            self._tax_default_cb.setChecked(True)
        self._tax_spin.setEnabled(not self._tax_default_cb.isChecked())
        # 改件（按设施类型重建 + 勾选已配置）
        self._on_facility_changed()
        self._check_rigs(cfg["rig_ids"])
        self._update_summary()

    # ── 改件区 ─────────────────────────────────────────────

    def _on_facility_changed(self):
        """设施类型切换 → 重建改件区（NPC 禁用）"""
        ftype = self._facility_combo.currentData()
        base = STRUCTURE_BASE.get(ftype or "npc")
        # 清空
        while self._rig_layout.count():
            item = self._rig_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._rig_cbs = []
        # 本体加成说明
        if base:
            self._fac_base_label.setText(f"材料 {base['mat']} / 成本 {base['cost']} / 时间 {base['time']}（NPC=1.0）")
        if not base or not base["rig_size"]:
            self._fac_base_label.setText("NPC 空间站无结构本体加成，不可装配改装件")
            self._summary_label.setText("NPC 空间站无结构改装件")
            return
        # 按类别分组填充
        catalog = get_rig_catalog(ftype)
        grouped: dict[str, list[dict]] = {}
        for item in catalog:
            grouped.setdefault(item["category_key"], []).append(item)
        for cat_key, items in grouped.items():
            group = QGroupBox(items[0]["category_label"] if items else cat_key)
            gl = QVBoxLayout(group)
            gl.setContentsMargins(8, 4, 8, 4)
            for item in items:
                bonus_parts = []
                if item["mat_bonus"]:
                    bonus_parts.append(f"材料 {item['mat_bonus']:+.1f}%")
                if item["time_bonus"]:
                    bonus_parts.append(f"时间 {item['time_bonus']:+.0f}%")
                bonus_txt = "、".join(bonus_parts) if bonus_parts else "加成未拉取（运行数据初始化）"
                cb = QCheckBox(f"{item['zh_name']}  [{bonus_txt}]")
                cb.setProperty("rig_type_id", item["type_id"])
                cb.toggled.connect(lambda checked, c=cb, gl=gl: self._on_rig_toggled(checked, c, gl))
                gl.addWidget(cb)
                self._rig_cbs.append((cb, item))
            self._rig_layout.addWidget(group)
        self._rig_layout.addStretch()

    def _on_rig_toggled(self, checked: bool, cb: QCheckBox, group_layout: QVBoxLayout):
        """同类别互斥：勾选一个时取消同组其它"""
        if not checked:
            return
        for i in range(group_layout.count()):
            item = group_layout.itemAt(i)
            if item is None:
                continue
            w = item.widget()
            if isinstance(w, QCheckBox) and w is not cb:
                w.blockSignals(True)
                w.setChecked(False)
                w.blockSignals(False)

    def _check_rigs(self, rig_ids: list[int]):
        for cb, _item in self._rig_cbs:
            cb.setChecked(int(cb.property("rig_type_id")) in rig_ids)

    def _selected_rig_ids(self) -> list[int]:
        return [int(cb.property("rig_type_id")) for cb, _ in self._rig_cbs if cb.isChecked()]

    # ── 星系 ───────────────────────────────────────────────

    def _on_select_system(self):
        from ui_pyside6.dialogs.system_search_dialog import SystemSearchDialog

        dlg = SystemSearchDialog(self, "设置机库星系")
        if dlg.exec():
            sel = dlg.get_selected()
            if sel:
                inventory_manager.update_hangar_system(self._hangar["id"], sel[0])
                self._sys_label.setText(sel[1])

    def _on_clear_system(self):
        inventory_manager.update_hangar_system(self._hangar["id"], None)
        self._sys_label.setText("未设置")

    # ── 汇总 ───────────────────────────────────────────────

    def _update_summary(self):
        cfg = resolve_hangar_industry_config(self._hangar["id"])
        self._summary_label.setText(
            f"当前加成: 材料 {cfg['structure_mat_saving']} / 时间 {cfg['structure_time_mod']} / "
            f"安装费 {cfg['structure_cost_mult']} | 设施税 "
            f"{cfg['facility_tax'] if cfg['facility_tax'] is not None else '跟随默认'}"
        )

    # ── 保存 ───────────────────────────────────────────────

    def validate(self) -> list[str]:
        """校验当前勾选；返回违规列表（空=合法）。"""
        ftype = self._facility_combo.currentData()
        return validate_rig_set(self._selected_rig_ids(), ftype)

    def save(self) -> None:
        ftype = self._facility_combo.currentData()
        tax = None if self._tax_default_cb.isChecked() else self._tax_spin.value()
        rig_ids = self._selected_rig_ids()
        inventory_manager.update_hangar_config(self._hangar["id"], ftype, tax, rig_ids)
        self._update_summary()


class HangarSettingsDialog(QDialog):
    """机库设置对话框 — 机库配置（星系/设施/改装件/税）+ 默认机库"""

    def __init__(self, main_window, parent=None):
        super().__init__(parent or main_window)
        self.setWindowTitle("机库设置")
        self.setMinimumSize(760, 560)
        self.resize(860, 620)
        self.setObjectName("hangar_settings_dialog")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_hangar_tab(), "机库配置")
        self._tabs.addTab(self._build_defaults_tab(), "默认机库")
        layout.addWidget(self._tabs, 1)

        btns = QHBoxLayout()
        btns.addStretch()
        self._save_btn = QPushButton("保存")
        self._save_btn.clicked.connect(self._on_save)
        btns.addWidget(self._save_btn)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(cancel_btn)
        layout.addLayout(btns)

        theme.add_theme_listener(self._on_theme_changed)

    # ── Tab 1: 机库配置 ────────────────────────────────────

    def _build_hangar_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(4, 4, 4, 4)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        # 机库增删改（新建/重命名/删除）——仓库管理页已移除，统一在此维护
        mgmt_btns = QHBoxLayout()
        mgmt_btns.setSpacing(4)
        self._new_hangar_btn = QPushButton("新建机库")
        self._new_hangar_btn.clicked.connect(self._on_new_hangar)
        mgmt_btns.addWidget(self._new_hangar_btn)
        self._rename_hangar_btn = QPushButton("重命名")
        self._rename_hangar_btn.clicked.connect(self._on_rename_hangar)
        mgmt_btns.addWidget(self._rename_hangar_btn)
        self._delete_hangar_btn = QPushButton("删除")
        self._delete_hangar_btn.clicked.connect(self._on_delete_hangar)
        mgmt_btns.addWidget(self._delete_hangar_btn)
        left_layout.addLayout(mgmt_btns)

        self._hangar_list = QListWidget()
        left_layout.addWidget(self._hangar_list, 1)
        splitter.addWidget(left)

        self._stack = QStackedWidget()
        splitter.addWidget(self._stack)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter)

        self._editors: dict[int, _HangarEditor] = {}
        self._hangar_list.currentRowChanged.connect(self._on_hangar_selected)

        self._reload_hangars()
        return w

    def _reload_hangars(self):
        """刷新机库列表与配置面板"""
        self._hangar_list.clear()
        while self._stack.count():
            w = self._stack.widget(0)
            self._stack.removeWidget(w)
            w.deleteLater()
        self._editors.clear()
        hangars = inventory_manager.get_hangars()
        # 星系名映射
        sys_names = self._system_names([h["solar_system_id"] for h in hangars if h.get("solar_system_id")])
        for h in hangars:
            label = h["name"]
            sid = h.get("solar_system_id")
            if sid and sid in sys_names:
                label = f"{label} ({sys_names[sid]})"
            self._hangar_list.addItem(label)
            editor = _HangarEditor(h)
            self._editors[h["id"]] = editor
            self._stack.addWidget(editor)
        if hangars:
            self._hangar_list.setCurrentRow(0)
        self._refresh_defaults_combos()

    def _refresh_defaults_combos(self) -> None:
        """按当前机库列表重建「默认机库」下拉（保留已选值；新建/删除后同步）。"""
        if not hasattr(self, "_default_combos"):
            return
        hangars = inventory_manager.get_hangars()
        for combo in self._default_combos.values():
            current = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("未设置", -1)
            new_selected = -1
            for h in hangars:
                combo.addItem(h["name"], h["id"])
                if h["id"] == current:
                    new_selected = h["id"]
            combo.setCurrentIndex(combo.findData(new_selected))
            combo.blockSignals(False)

    def _system_names(self, solar_system_ids: list[int]) -> dict[int, str]:
        from services.name_resolver import resolve_system_display_names_batch

        return resolve_system_display_names_batch(solar_system_ids)

    def _on_hangar_selected(self, row: int):
        if 0 <= row < self._stack.count():
            self._stack.setCurrentIndex(row)

    # ── 机库增删改（新建/重命名/删除）────────────────────────

    def _on_new_hangar(self):
        name, ok = QInputDialog.getText(self, "新建机库", "机库名:")
        if not (ok and name.strip()):
            return
        rid = inventory_manager.create_hangar(name.strip())
        if rid == -1:
            QMessageBox.warning(self, "提示", "机库名已存在")
            return
        self._reload_hangars()
        # 选中新建机库（列表行文本 = 名称，新机库无星系名后缀）
        for i in range(self._hangar_list.count()):
            if self._hangar_list.item(i).text() == name.strip():
                self._hangar_list.setCurrentRow(i)
                break

    def _on_rename_hangar(self):
        row = self._hangar_list.currentRow()
        if row < 0 or row >= len(self._editors):
            return
        hangar_id = list(self._editors)[row]
        old = self._hangar_list.item(row).text()
        name, ok = QInputDialog.getText(self, "重命名", "新名称:", text=old)
        if ok and name.strip() and name != old:
            inventory_manager.rename_hangar(hangar_id, name.strip())
            self._reload_hangars()

    def _on_delete_hangar(self):
        row = self._hangar_list.currentRow()
        if row < 0 or row >= len(self._editors):
            return
        hangar_id = list(self._editors)[row]
        name = self._hangar_list.item(row).text()
        reply = QMessageBox.question(
            self,
            "确认",
            f"删除机库「{name}」及其所有物品？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            inventory_manager.delete_hangar(hangar_id)
            self._reload_hangars()

    # ── Tab 2: 默认机库 ────────────────────────────────────

    def _build_defaults_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(8)

        group = QGroupBox("默认机库（决定材料来源 / 产品去向）")
        form = QFormLayout(group)
        self._default_combos: dict[str, QComboBox] = {}
        hangars = inventory_manager.get_hangars()
        for key, label in _DEFAULT_HANGAR_KEYS:
            combo = QComboBox()
            combo.addItem("未设置", -1)
            for h in hangars:
                combo.addItem(h["name"], h["id"])
            form.addRow(f"{label}:", combo)
            self._default_combos[key] = combo
        layout.addWidget(group)

        settings = user_settings.load_settings()
        for key, combo in self._default_combos.items():
            val = settings.get(key)
            if val is not None:
                idx = combo.findData(int(val))
                if idx >= 0:
                    combo.setCurrentIndex(idx)
        layout.addStretch()
        return w

    # ── 保存 ───────────────────────────────────────────────

    def _on_save(self):
        # 校验所有机库的改件配置
        for editor in self._editors.values():
            problems = editor.validate()
            if problems:
                QMessageBox.warning(self, "配置无效", "机库配置有误：\n" + "\n".join(problems[:5]))
                return
        # 保存机库配置
        for editor in self._editors.values():
            editor.save()
        # 保存默认机库
        for key, combo in self._default_combos.items():
            hangar_id = combo.currentData()
            user_settings.set_default_hangar_id(key, None if hangar_id == -1 else int(hangar_id))
        self.accept()

    # ── 主题 ───────────────────────────────────────────────

    def _on_theme_changed(self):
        """主题切换时刷新内联样式（表格/列表走全局 QSS）"""
        for editor in self._editors.values():
            editor._summary_label.setStyleSheet(f"color: {theme.TEXT_SECONDARY};")
