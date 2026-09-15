import QtQuick
import QtQuick.Layouts
import "../components"

/* 星系搜索选择对话框（阶段 4）。
 *
 * 供机库设置 / 生产计划设施选择复用：输入名称 → 选一行 → 确定，返回 (星系 id, 名称)。
 *
 * 排版交给 `FDialogFrame`（主体 + 校验提示 + 取消/确定），它同时把「确定」接到桥的
 * `accept()` 上；中段的「过滤框 + 可选表格 + 状态行」复用 `FPickList`
 * （物品搜索用的是同一份）。未选中时「确定」置灰 —— 比 Widgets 版「点了没反应」明确。
 */

FDialogFrame {
    id: frame

    readonly property var ss: typeof bridge !== "undefined" ? bridge : null

    dlg: frame.ss
    acceptText: qsTr("确定")
    acceptEnabled: frame.ss ? frame.ss.hasSelection : false

    FPickList {
        Layout.fillWidth: true
        Layout.fillHeight: true
        source: frame.ss
        columns: frame.ss ? frame.ss.columns : []
        placeholder: qsTr("输入星系名（如 Jita / 吉他）...")
        filterEnabled: frame.ss ? frame.ss.dataReady : false
    }
}
