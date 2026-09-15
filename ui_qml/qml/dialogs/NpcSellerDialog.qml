import QtQuick
import QtQuick.Layouts
import "../components"

/* 蓝图 NPC 卖家对话框（阶段 4）。
 *
 * 选贸易中心 → 从 ESI 拉该蓝图的卖单 → 筛出 NPC 公司的直售单（BPO）。
 * 取数在后台线程里（`NpcOrderWorker`），期间状态行显示「正在从 ESI 获取卖单…」。
 *
 * 「非 NPC 直售」不是错误而是常态（T2 等高阶蓝图没有 NPC 直售），所以空表也走
 * 状态行给一句解释，不用错误通道。
 *
 * 窗口行为在 `QmlDialog` 那一层；表格渲染复用 `FSummaryTable`。
 */

Item {
    id: page

    readonly property var npc: typeof bridge !== "undefined" ? bridge : null

    Rectangle {
        anchors.fill: parent
        color: Theme.bgDark
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.spacingMd
        spacing: Theme.spacingSm

        Text {
            Layout.fillWidth: true
            text: page.npc ? page.npc.headerText : ""
            color: Theme.primary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(14 * Theme.fontScale)
        }

        Text {
            Layout.fillWidth: true
            text: page.npc ? page.npc.noteText : ""
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(11 * Theme.fontScale)
            wrapMode: Text.WordWrap
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingSm

            Text {
                text: qsTr("贸易中心:")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(12 * Theme.fontScale)
            }

            FComboBox {
                id: hubCombo
                Layout.preferredWidth: Math.round(160 * Theme.fontScale)
                textRole: "label"
                model: page.npc ? page.npc.hubs : []
                currentIndex: page.npc ? page.npc.hubIndex : 0
                onActivated: function (index) {
                    if (page.npc)
                        page.npc.setHub(index)
                }
            }

            FButton {
                text: qsTr("刷新")
                enabled: page.npc ? !page.npc.loading : false
                onClicked: if (page.npc)
                    page.npc.refresh()
            }

            Item {
                Layout.fillWidth: true
            }
        }

        FSummaryTable {
            objectName: "orderTable"
            Layout.fillWidth: true
            Layout.fillHeight: true
            columns: page.npc ? page.npc.columns : []
            rows: page.npc ? page.npc.rows : []
            emptyText: ""
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingSm

            Text {
                Layout.fillWidth: true
                text: page.npc ? page.npc.statusText : ""
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(11 * Theme.fontScale)
                wrapMode: Text.WordWrap
            }

            FButton {
                text: qsTr("关闭")
                onClicked: if (page.npc)
                    page.npc.reject()
            }
        }
    }
}
