"""机库设置对话框冒烟测试（slow — 需 Qt）"""

from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QMessageBox

pytestmark = pytest.mark.ui

DEFAULT_CFG: dict = {
    "structure_mat_saving": 1.0,
    "structure_time_mod": 1.0,
    "structure_cost_mult": 1.0,
    "facility_tax": None,
    "facility_type": None,
    "rig_ids": [],
}

MOCK_HANGARS = [
    {
        "id": 1,
        "name": "制造仓",
        "notes": "",
        "solar_system_id": None,
        "facility_type": None,
        "facility_tax": None,
        "rigs": None,
    }
]


def test_hangar_list_shows_system_pair(qapp):
    """机库列表条目带星系中英对照后缀（吉他 (Jita)）"""
    from ui_pyside6.views.hangar_settings_view import HangarSettingsDialog

    hangar = {
        "id": 1,
        "name": "制造仓",
        "notes": "",
        "solar_system_id": 30000142,
        "facility_type": None,
        "facility_tax": None,
        "rigs": None,
    }
    with (
        patch("ui_pyside6.views.hangar_settings_view.inventory_manager.get_hangars", return_value=[hangar]),
        patch("services.hangar_industry_config.get_rig_catalog", return_value=[]),
        patch("ui_pyside6.views.hangar_settings_view.resolve_hangar_industry_config", return_value=DEFAULT_CFG),
        patch(
            "services.name_resolver.resolve_system_display_names_batch",
            return_value={30000142: "吉他 (Jita)"},
        ),
    ):
        dlg = HangarSettingsDialog(None)
        assert dlg._hangar_list.item(0).text() == "制造仓 (吉他 (Jita))"
        dlg.deleteLater()


def test_hangar_settings_dialog_constructs(qapp):
    """对话框可构造，含机库列表 + 配置面板 + 默认机库 tab"""
    from ui_pyside6.views.hangar_settings_view import HangarSettingsDialog

    with (
        patch("services.inventory_manager.get_hangars", return_value=MOCK_HANGARS),
        patch("services.hangar_industry_config.get_rig_catalog", return_value=[]),
        patch("ui_pyside6.views.hangar_settings_view.resolve_hangar_industry_config", return_value=DEFAULT_CFG),
        patch("ui_pyside6.views.hangar_settings_view.inventory_manager.get_hangars", return_value=MOCK_HANGARS),
    ):
        dlg = HangarSettingsDialog(None)
        assert dlg is not None
        assert dlg._hangar_list.count() == 1
        assert dlg._stack.count() == 1
        assert len(dlg._default_combos) == 4  # 科研/制造材料/制造产出/商业
        dlg.deleteLater()


def test_hangar_settings_dialog_has_mgmt_buttons(qapp):
    """机库设置对话框含新建/重命名/删除入口（从仓库管理页迁入）"""
    from ui_pyside6.views.hangar_settings_view import HangarSettingsDialog

    with (
        patch("services.inventory_manager.get_hangars", return_value=MOCK_HANGARS),
        patch("services.hangar_industry_config.get_rig_catalog", return_value=[]),
        patch("ui_pyside6.views.hangar_settings_view.resolve_hangar_industry_config", return_value=DEFAULT_CFG),
        patch("ui_pyside6.views.hangar_settings_view.inventory_manager.get_hangars", return_value=MOCK_HANGARS),
    ):
        dlg = HangarSettingsDialog(None)
        assert hasattr(dlg, "_new_hangar_btn")
        assert hasattr(dlg, "_rename_hangar_btn")
        assert hasattr(dlg, "_delete_hangar_btn")
        dlg.deleteLater()


def test_new_hangar_from_dialog(qapp):
    """对话框内新建机库 → create_hangar 被调用，机库列表刷新并选中新机库"""
    from ui_pyside6.views.hangar_settings_view import HangarSettingsDialog

    new_id: int = 99
    created = {"done": False}

    def fake_get_hangars():
        if created["done"]:
            return MOCK_HANGARS + [{"id": new_id, "name": "装配仓", "notes": "", "solar_system_id": None}]
        return MOCK_HANGARS

    def fake_create(_name: str) -> int:
        created["done"] = True
        return new_id

    with (
        patch("ui_pyside6.views.hangar_settings_view.QInputDialog.getText", return_value=("装配仓", True)),
        patch(
            "ui_pyside6.views.hangar_settings_view.inventory_manager.create_hangar", side_effect=fake_create
        ) as create,
        patch("ui_pyside6.views.hangar_settings_view.inventory_manager.get_hangars", side_effect=fake_get_hangars),
        patch("services.hangar_industry_config.get_rig_catalog", return_value=[]),
        patch("ui_pyside6.views.hangar_settings_view.resolve_hangar_industry_config", return_value=DEFAULT_CFG),
    ):
        dlg = HangarSettingsDialog(None)
        dlg._on_new_hangar()
        create.assert_called_once_with("装配仓")
        assert dlg._hangar_list.count() == 2
        # 新机库被选中
        assert dlg._hangar_list.currentItem().text() == "装配仓"
        dlg.deleteLater()


def test_rename_hangar_from_dialog(qapp):
    """对话框内重命名 → rename_hangar 被调用"""
    from ui_pyside6.views.hangar_settings_view import HangarSettingsDialog

    with (
        patch("services.inventory_manager.get_hangars", return_value=MOCK_HANGARS),
        patch("services.hangar_industry_config.get_rig_catalog", return_value=[]),
        patch("ui_pyside6.views.hangar_settings_view.resolve_hangar_industry_config", return_value=DEFAULT_CFG),
        patch("ui_pyside6.views.hangar_settings_view.inventory_manager.get_hangars", return_value=MOCK_HANGARS),
        patch("ui_pyside6.views.hangar_settings_view.QInputDialog.getText", return_value=("新制造仓", True)),
        patch("ui_pyside6.views.hangar_settings_view.inventory_manager.rename_hangar") as rename,
    ):
        dlg = HangarSettingsDialog(None)
        dlg._hangar_list.setCurrentRow(0)
        dlg._on_rename_hangar()
        rename.assert_called_once_with(1, "新制造仓")
        dlg.deleteLater()


def test_delete_hangar_from_dialog(qapp):
    """对话框内删除机库 → delete_hangar 被调用"""
    from ui_pyside6.views.hangar_settings_view import HangarSettingsDialog

    with (
        patch("services.inventory_manager.get_hangars", return_value=MOCK_HANGARS),
        patch("services.hangar_industry_config.get_rig_catalog", return_value=[]),
        patch("ui_pyside6.views.hangar_settings_view.resolve_hangar_industry_config", return_value=DEFAULT_CFG),
        patch("ui_pyside6.views.hangar_settings_view.inventory_manager.get_hangars", return_value=MOCK_HANGARS),
        patch(
            "ui_pyside6.views.hangar_settings_view.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes,
        ),
        patch("ui_pyside6.views.hangar_settings_view.inventory_manager.delete_hangar") as delete,
    ):
        dlg = HangarSettingsDialog(None)
        dlg._hangar_list.setCurrentRow(0)
        dlg._on_delete_hangar()
        delete.assert_called_once_with(1)
        dlg.deleteLater()


def test_hangar_editor_save(qapp, main_window):
    """编辑面板保存 → update_hangar_config 被调用"""
    from ui_pyside6.views.hangar_settings_view import _HangarEditor

    hangar = dict(MOCK_HANGARS[0])
    with (
        patch("services.hangar_industry_config.get_rig_catalog", return_value=[]),
        patch("ui_pyside6.views.hangar_settings_view.resolve_hangar_industry_config", return_value=DEFAULT_CFG),
        patch("ui_pyside6.views.hangar_settings_view.inventory_manager.update_hangar_config") as upd,
        patch("ui_pyside6.views.hangar_settings_view.inventory_manager.update_hangar_system"),
    ):
        editor = _HangarEditor(hangar)
        editor.save()
        upd.assert_called_once()
        editor.deleteLater()


def test_stale_default_hangar_not_silently_cleared(qapp):
    """回归：默认机库指向已删除的机库时，保存不得静默清空该设置。

    场景：机库被删/重建后 id 变化 → 下拉框解析不到 → 旧实现会写回 None，
    用户感知为「默认机库设置老是丢失」。
    """
    from ui_pyside6.views.hangar_settings_view import HangarSettingsDialog

    with (
        patch("services.inventory_manager.get_hangars", return_value=MOCK_HANGARS),
        patch("services.hangar_industry_config.get_rig_catalog", return_value=[]),
        patch("ui_pyside6.views.hangar_settings_view.resolve_hangar_industry_config", return_value=DEFAULT_CFG),
        patch("ui_pyside6.views.hangar_settings_view.inventory_manager.get_hangars", return_value=MOCK_HANGARS),
        patch("ui_pyside6.views.hangar_settings_view.inventory_manager.update_hangar_config"),
        patch(
            "ui_pyside6.views.hangar_settings_view.user_settings.load_settings",
            return_value={"default_mat_hangar_id": 42},  # 42 不在 MOCK_HANGARS 中
        ),
        patch("ui_pyside6.views.hangar_settings_view.user_settings.set_default_hangar_id") as m_set,
    ):
        dlg = HangarSettingsDialog(None)
        combo = dlg._default_combos["default_mat_hangar_id"]
        assert combo.currentData() == 42  # 保留原值，不静默回落「未设置」
        assert "已删除" in combo.currentText()
        dlg._on_save()

    written = {c.args[0]: c.args[1] for c in m_set.call_args_list}
    assert written["default_mat_hangar_id"] == 42
    dlg.deleteLater()


def test_delete_referenced_hangar_offers_repoint(qapp):
    """删除被引用的机库 → 弹引用对话框，选替换机库后 delete_hangar 带 repoint_to。"""
    from ui_pyside6.views.hangar_settings_view import HangarSettingsDialog

    with (
        patch("ui_pyside6.views.hangar_settings_view.inventory_manager.get_hangars", return_value=MOCK_HANGARS),
        patch("services.hangar_industry_config.get_rig_catalog", return_value=[]),
        patch("ui_pyside6.views.hangar_settings_view.resolve_hangar_industry_config", return_value=DEFAULT_CFG),
        patch(
            "ui_pyside6.views.hangar_settings_view.inventory_manager.hangar_references",
            return_value=["默认材料机库"],
        ),
        patch("ui_pyside6.views.hangar_settings_view.inventory_manager.delete_hangar") as m_del,
        patch("ui_pyside6.views.hangar_settings_view._DeleteHangarDialog") as m_dlg,
    ):
        m_dlg.return_value.exec.return_value = 1
        m_dlg.return_value.repoint_to.return_value = 9
        dlg = HangarSettingsDialog(None)
        dlg._hangar_list.setCurrentRow(0)
        dlg._on_delete_hangar()

    m_dlg.assert_called_once()
    assert m_dlg.call_args.args[1] == ["默认材料机库"]  # 引用明细传给了对话框
    m_del.assert_called_once_with(1, repoint_to=9)
    dlg.deleteLater()


def test_delete_unreferenced_hangar_simple_confirm(qapp):
    """无引用的机库 → 仍是简单确认框，不弹引用对话框。"""
    from ui_pyside6.views.hangar_settings_view import HangarSettingsDialog

    with (
        patch("ui_pyside6.views.hangar_settings_view.inventory_manager.get_hangars", return_value=MOCK_HANGARS),
        patch("services.hangar_industry_config.get_rig_catalog", return_value=[]),
        patch("ui_pyside6.views.hangar_settings_view.resolve_hangar_industry_config", return_value=DEFAULT_CFG),
        patch("ui_pyside6.views.hangar_settings_view.inventory_manager.hangar_references", return_value=[]),
        patch("ui_pyside6.views.hangar_settings_view.inventory_manager.delete_hangar") as m_del,
        patch("ui_pyside6.views.hangar_settings_view._DeleteHangarDialog") as m_dlg,
        patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes),
    ):
        dlg = HangarSettingsDialog(None)
        dlg._hangar_list.setCurrentRow(0)
        dlg._on_delete_hangar()

    m_dlg.assert_not_called()
    m_del.assert_called_once_with(1)
    dlg.deleteLater()
