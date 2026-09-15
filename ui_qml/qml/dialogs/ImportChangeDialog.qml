import QtQuick
import QtQuick.Layouts
import "../components"

/* 导入完成变动汇总对话框（阶段 4b-3）。
 *
 * 对照 Widgets 版 `ui_pyside6/views/inventory/review_dialog.py::ImportChangeDialog`：
 * 表格上方一行汇总（共 N 项变化 / 增加 / 减少 / 成功导入 / 跨机库移动），
 * 下面只读表（名称 / 数量 前→后 / 成本 前→后），行数少了不加装饰。
 *
 * 形状与只读汇总表一致，行与列都由桥给出（复用 `FSummaryTable` 与 `SummaryTableBridge`），
 * 本文件只做「汇总说明行 + 表 + 关闭」。原版只有一个 Close 按钮，故这里关掉「确定」、
 * 把「取消」改名成「关闭」——`DialogBridge.reject()` 与原版的 reject 语义相同。
 */

FDialogFrame {
    id: frame

    readonly property var ch: typeof bridge !== "undefined" ? bridge : null

    dlg: frame.ch
    acceptVisible: false
    cancelText: qsTr("关闭")

    Text {
        Layout.fillWidth: true
        text: frame.ch ? frame.ch.headerText : ""
        color: Theme.textSecondary
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(11 * Theme.fontScale)
        wrapMode: Text.WordWrap
    }

    FSummaryTable {
        objectName: "changeTable"
        Layout.fillWidth: true
        Layout.fillHeight: true
        columns: frame.ch ? frame.ch.columns : []
        rows: frame.ch ? frame.ch.rows : []
        emptyText: frame.ch ? frame.ch.emptyText : ""
    }
}
