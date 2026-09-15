import QtQuick
import QtQuick.Layouts
import "../components"

/* 合同详情对话框（阶段 4）。
 *
 * 上半是合同本身的字段（编号/标题、类型状态价格、时间与站点），下半是合同内物品表。
 * 物品走后台线程加载（`ContractItemsLoadWorker`），所以状态行会先显示「正在加载…」。
 *
 * 窗口行为在 `QmlDialog` 那一层；表格渲染复用 `FSummaryTable`。
 */

Item {
    id: page

    readonly property var ct: typeof bridge !== "undefined" ? bridge : null

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
            text: page.ct ? page.ct.headerText : ""
            color: Theme.primary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(15 * Theme.fontScale)
            font.weight: Font.DemiBold
            elide: Text.ElideRight
        }

        Text {
            Layout.fillWidth: true
            text: page.ct ? page.ct.detailText : ""
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
            wrapMode: Text.WordWrap
        }

        Text {
            Layout.fillWidth: true
            text: page.ct ? page.ct.datesText : ""
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
            wrapMode: Text.WordWrap
        }

        Text {
            Layout.fillWidth: true
            text: qsTr("合同物品:")
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
            font.weight: Font.DemiBold
        }

        FSummaryTable {
            objectName: "itemTable"
            Layout.fillWidth: true
            Layout.fillHeight: true
            columns: page.ct ? page.ct.columns : []
            rows: page.ct ? page.ct.rows : []
            emptyText: page.ct ? page.ct.emptyText : ""
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingSm

            Text {
                Layout.fillWidth: true
                text: page.ct ? page.ct.statusText : ""
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(11 * Theme.fontScale)
                elide: Text.ElideRight
            }

            FButton {
                text: qsTr("关闭")
                onClicked: if (page.ct)
                    page.ct.reject()
            }
        }
    }
}
