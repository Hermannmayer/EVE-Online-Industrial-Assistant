import QtQuick
import QtQuick.Layouts
import "../components"

/* 订单弹窗（阶段 4b）。
 *
 * 双击物品行弹出：上半兑现买单、下半兑现卖单，各取该物品在贸易中心的前 5 条；
 * 右上角「走势图」再弹价格历史（`PriceChartQmlDialog`）—— 三级链的最后一层。
 *
 * 窗口行为在 `QmlDialog` 那一层（宿主设了 `Qt.Popup`：点窗外自动关，与原版一致），
 * 表格渲染复用 `FSummaryTable`。空表不是错误：该物品可能确实没人挂单，
 * 由各表的 `emptyText` 说明，不再像原版那样往列表里塞一行占位项。
 */

Item {
    id: page

    readonly property var op: typeof bridge !== "undefined" ? bridge : null

    Rectangle {
        anchors.fill: parent
        color: Theme.bgDark
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.spacingMd
        spacing: Theme.spacingSm

        // ── 标题 + 走势图 ──
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingSm

            Text {
                Layout.fillWidth: true
                text: page.op ? page.op.title : ""
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(13 * Theme.fontScale)
                elide: Text.ElideRight
            }

            /* 原版这颗按钮是「图标 + 走势图」，这里只留文字：
             * `FButton` 的 contentItem 是它自己重写的纯 `Text`，`Button.icon` 会被
             * 整个忽略（设了也不显示）。要带图标就得另造一个按钮控件，而基础控件
             * 只该有一份 —— 「走势图」三个字已经说清动作了。 */
            FButton {
                text: qsTr("走势图")
                onClicked: if (page.op)
                    page.op.openChart()
            }
        }

        // ── 买单（上半区）──
        Text {
            Layout.fillWidth: true
            text: qsTr("买单 (Buy)")
            color: Theme.accentGreen
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
            font.weight: Font.DemiBold
        }

        FSummaryTable {
            objectName: "buyTable"
            Layout.fillWidth: true
            Layout.fillHeight: true
            columns: page.op ? page.op.columns : []
            rows: page.op ? page.op.buyRows : []
            emptyText: qsTr("无买单数据")
        }

        // ── 卖单（下半区）──
        Text {
            Layout.fillWidth: true
            text: qsTr("卖单 (Sell)")
            color: Theme.accentRed
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
            font.weight: Font.DemiBold
        }

        FSummaryTable {
            objectName: "sellTable"
            Layout.fillWidth: true
            Layout.fillHeight: true
            columns: page.op ? page.op.columns : []
            rows: page.op ? page.op.sellRows : []
            emptyText: qsTr("无卖单数据")
        }
    }
}
