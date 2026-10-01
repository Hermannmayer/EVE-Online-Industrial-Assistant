import QtQuick
import QtQuick.Layouts
import "../components"

/* 母项拆解对话框（阶段 4a 收尾）。
 *
 * 预览递归拆解出的子项产线（需求/流程/并行/ME-TE/利润/蓝图），
 * 每行一个「移除」按钮 = 本轮不内造该组件、改外购；确认后落库并重放子项。
 *
 * 表格渲染复用 `FSummaryTable`（行内动作列就是「移除」按钮）；
 * 排版复用 `FDialogFrame`（主体 + 校验提示 + 取消/确定）。
 */

FDialogFrame {
    id: frame

    readonly property var pd: typeof bridge !== "undefined" ? bridge : null

    /* 批量移除并清空选中集。参数是 QML 的 JS 数组 → 桥侧收 `QVariantList`。
     * 单行删除（行内「移除」按钮）与批量走同一条路，避免两份语义漂移。 */
    function removeRows(rows) {
        if (!frame.pd || !rows || rows.length === 0)
            return
        frame.pd.removeRows(rows)
        decomposeTable.selectedRows = []
    }

    dlg: frame.pd
    acceptText: qsTr("确认拆解")
    acceptVisible: frame.pd ? !frame.pd.isEmpty : false
    cancelText: frame.pd && frame.pd.isEmpty ? qsTr("关闭") : qsTr("取消")

    Text {
        Layout.fillWidth: true
        // 桥给的是带 <b> 的富文本（原 Widgets 版的加粗摘要）；AutoText 会识别并渲染
        text: frame.pd ? frame.pd.headerText : ""
        textFormat: Text.AutoText
        color: Theme.primary
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(13 * Theme.fontScale)
        wrapMode: Text.WordWrap
    }

    FSummaryTable {
        id: decomposeTable
        objectName: "decomposeTable"
        Layout.fillWidth: true
        Layout.fillHeight: true
        visible: frame.pd ? !frame.pd.isEmpty : false
        columns: frame.pd ? frame.pd.columns : []
        rows: frame.pd ? frame.pd.rows : []
        hasActionColumn: true
        actionText: qsTr("移除")
        emptyText: frame.pd ? frame.pd.emptyText : ""
        onActionClicked: function (row) {
            frame.removeRows([row]);
        }
        onRowDoubleClicked: function (row, _column) {
            frame.removeRows([row]);
        }
    }

    /* 多选批量移除。鼠标语义（Ctrl 切换 / Shift 连选）在 `FSummaryTable` 里维护，
     * 这里只把当前选中集交给桥 —— 桥按行号**降序**删，顺序删会因下标前移而漏删。 */
    FButton {
        Layout.alignment: Qt.AlignRight
        visible: decomposeTable.selectedRows.length > 0
        text: qsTr("移除选中行（%1）").arg(decomposeTable.selectedRows.length)
        onClicked: frame.removeRows(decomposeTable.selectedRows)
    }

    Text {
        Layout.fillWidth: true
        visible: frame.pd ? frame.pd.isEmpty : false
        text: frame.pd ? frame.pd.emptyText : ""
        color: Theme.textSecondary
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(12 * Theme.fontScale)
        wrapMode: Text.WordWrap
    }

    Text {
        Layout.fillWidth: true
        visible: frame.pd ? !frame.pd.isEmpty : false
        text: frame.pd ? frame.pd.tipText : ""
        color: Theme.textSecondary
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(11 * Theme.fontScale)
        wrapMode: Text.WordWrap
    }

    Text {
        Layout.fillWidth: true
        visible: frame.pd ? frame.pd.statusText !== "" : false
        text: frame.pd ? frame.pd.statusText : ""
        color: Theme.accentOrange
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(11 * Theme.fontScale)
        wrapMode: Text.WordWrap
    }
}
