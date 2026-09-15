import QtQuick
import QtQuick.Layouts
import "../components"

/* 星系搜索选择对话框（阶段 4）。
 *
 * 供机库设置 / 生产计划设施选择复用：输入名称 → 选一行 → 确定，返回 (星系 id, 名称)。
 *
 * 排版直接复用 `FDialogFrame`（主体 + 校验提示 + 取消/确定），它同时负责把
 * 「确定」接到桥的 `accept()` 上；表格渲染复用 `FSummaryTable`。
 * 未选中任何行时「确定」置灰 —— 比 Widgets 版「点了没反应」明确。
 */

FDialogFrame {
    id: frame

    readonly property var ss: typeof bridge !== "undefined" ? bridge : null

    dlg: frame.ss
    acceptText: qsTr("确定")
    acceptEnabled: frame.ss ? frame.ss.hasSelection : false

    FTextField {
        objectName: "systemSearchField"
        Layout.fillWidth: true
        placeholderText: qsTr("输入星系名（如 Jita / 吉他）...")
        enabled: frame.ss ? frame.ss.dataReady : false
        onTextChanged: if (frame.ss)
            frame.ss.setQuery(text)
    }

    FSummaryTable {
        objectName: "systemTable"
        Layout.fillWidth: true
        Layout.fillHeight: true
        columns: frame.ss ? frame.ss.columns : []
        rows: frame.ss ? frame.ss.rows : []
        selectable: true
        currentRow: frame.ss ? frame.ss.currentRow : -1
        emptyText: ""
        onRowClicked: function (row) {
            if (frame.ss)
                frame.ss.selectRow(row)
        }
        onRowDoubleClicked: function (row) {
            if (frame.ss)
                frame.ss.activateRow(row)
        }
    }

    Text {
        Layout.fillWidth: true
        text: frame.ss ? frame.ss.statusText : ""
        color: Theme.textSecondary
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(11 * Theme.fontScale)
        wrapMode: Text.WordWrap
    }
}
