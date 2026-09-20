import QtQuick
import QtQuick.Layouts
import "../components"

/* 物品搜索对话框（阶段 4b）。
 *
 * 搜索 item 表（含 terminology 注册的基础矿物）→ 选一行 → 选定，
 * 返回 `{type_id, zh_name, en_name}`。库存修正对话框用它处理「未匹配」行。
 *
 * 中段复用 `FPickList`（与星系搜索同一份）。「选定」在**只搜到一条**时也可点 ——
 * 原 Widgets 版就是这行为：唯一结果直接采用，不必再点一行。
 */

FDialogFrame {
    id: frame

    readonly property var si: typeof bridge !== "undefined" ? bridge : null

    dlg: frame.si
    acceptText: qsTr("选定")
    acceptEnabled: frame.si ? (frame.si.hasSelection || frame.si.rows.length === 1) : false

    FPickList {
        Layout.fillWidth: true
        Layout.fillHeight: true
        source: frame.si
        columns: frame.si ? frame.si.columns : []
        placeholder: qsTr("输入物品名称（中文/英文）...")
    }
}
