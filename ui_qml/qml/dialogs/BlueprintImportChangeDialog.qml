import QtQuick
import QtQuick.Layouts
import "../components"

/* 蓝图导入完成 — 变动汇总（阶段 4b）。
 *
 * 对照 Widgets 版 `BlueprintImportChangeDialog`：顶部汇总行（共 N 项变化 / 增加 / 减少 /
 * 新增 / 删除）+ 只读表（蓝图 / 属性 / 数量 前 → 后，增绿减红）+ 关闭。
 *
 * 表格渲染复用通用 `FSummaryTable`（与产出总表 / 材料总表同一份），这里只摆位置。
 * 原版只有一颗「关闭」按钮（走 reject），所以关掉 FDialogFrame 的确定键。
 * 汇总文案与行都在桥里算好（`_build_summary` 复用原类，不外迁）。
 */

FDialogFrame {
    id: frame

    readonly property var cb: typeof bridge !== "undefined" ? bridge : null

    dlg: frame.cb
    acceptVisible: false
    cancelText: qsTr("关闭")

    Text {
        Layout.fillWidth: true
        text: frame.cb ? frame.cb.headerText : ""
        color: Theme.textSecondary
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(11 * Theme.fontScale)
        wrapMode: Text.WordWrap
    }

    FSummaryTable {
        objectName: "changeTable"
        Layout.fillWidth: true
        Layout.fillHeight: true
        columns: frame.cb ? frame.cb.columns : []
        rows: frame.cb ? frame.cb.rows : []
        emptyText: frame.cb ? frame.cb.emptyText : ""
    }

    Text {
        Layout.fillWidth: true
        visible: frame.cb ? frame.cb.statusText !== "" : false
        text: frame.cb ? frame.cb.statusText : ""
        color: Theme.textSecondary
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(11 * Theme.fontScale)
        elide: Text.ElideRight
    }
}
