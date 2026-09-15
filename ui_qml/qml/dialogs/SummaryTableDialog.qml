import QtQuick
import QtQuick.Layouts
import "../components"

/* 只读汇总表对话框（阶段 4）。
 *
 * 「产出总表」「人物占用」「材料总表」「研究分析」共用这一份：列、行、状态文案都由桥给出，
 * 表格渲染统一交给 `FSummaryTable`（它也被合同详情 / NPC 卖家 / 星系搜索复用）。
 */

Item {
    id: page

    readonly property var table: typeof bridge !== "undefined" ? bridge : null

    function _rows() {
        return page.table ? page.table.rows : []
    }

    Rectangle {
        anchors.fill: parent
        color: Theme.bgDark
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.spacingSm
        spacing: Theme.spacingSm

        // 表格上方的说明行（材料覆盖用它放「关联了哪些计划」）；空串时不占位置
        Text {
            Layout.fillWidth: true
            visible: page.table ? page.table.headerText !== "" : false
            text: page.table ? page.table.headerText : ""
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(11 * Theme.fontScale)
            wrapMode: Text.WordWrap
        }

        FSummaryTable {
            objectName: "summaryTable"
            Layout.fillWidth: true
            Layout.fillHeight: true
            columns: page.table ? page.table.columns : []
            rows: page._rows()
            hasActionColumn: page.table ? page.table.hasActionColumn : false
            actionText: qsTr("复制")
            emptyText: page.table ? page.table.emptyText : ""
            onActionClicked: function (row) {
                if (page.table)
                    page.table.copyRow(row)
            }
        }

        // ── 状态行 + 顶栏动作 + 关闭 ──
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingSm

            Text {
                Layout.fillWidth: true
                text: page.table ? page.table.statusText : ""
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(11 * Theme.fontScale)
                elide: Text.ElideRight
            }

            // 动作反馈（复制成功 / 无待采购 之类）—— 复用桥的 `error` 通道
            Text {
                visible: page.table ? page.table.error !== "" : false
                text: page.table ? page.table.error : ""
                color: Theme.accentYellow
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(11 * Theme.fontScale)
                elide: Text.ElideRight
            }

            FButton {
                text: page.table ? page.table.topActionText : ""
                visible: page.table ? page.table.topActionText !== "" : false
                onClicked: if (page.table)
                    page.table.topAction()
            }

            FButton {
                text: qsTr("关闭")
                onClicked: if (page.table)
                    page.table.reject()
            }
        }
    }
}
