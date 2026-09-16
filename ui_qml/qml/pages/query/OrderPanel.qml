import QtQuick
import QtQuick.Controls
import "../../components"

/* 详情面板 · 实时订单列表（左「卖单」/ 右「买单」，各取最优 5 条）。
 *
 * 对应界面标注图「订单列表 / 卖单 / 买单 / 5 个 / 复制卖单、买单价格按钮」。
 *
 * 取数走 ESI 实时（`ui_qml/workers/order_workers.py`），无本地订单表 —— 断网时这里显示
 * 失败文案而不是空白，见 `detail.orderStatus`。渲染用既有的纯函数
 * `ui_qml/bridge/order_popup_bridge.order_rows()`，与订单弹窗逐格同源。
 */
Item {
    id: root

    //: `bridge.detail`
    property var detail: null

    readonly property var heads: detail ? detail.orderHeads : []
    readonly property int fntSmall: Math.round(11 * Theme.fontScale)
    readonly property int barH: Math.max(22, Math.round(14 * Theme.fontScale) + 8)
    readonly property int labelH: Math.max(16, fntSmall + 6)

    Column {
        anchors.fill: parent
        spacing: Theme.spacingXs

        // ── 顶部：状态文案 + 两侧的「复制最优价」按钮 ──────────
        Row {
            width: parent.width
            height: root.barH
            spacing: Theme.spacingSm

            Text {
                height: parent.height
                width: Math.max(40, parent.width - copySell.width - copyBuy.width - 2 * Theme.spacingSm)
                verticalAlignment: Text.AlignVCenter
                text: root.detail && root.detail.busy ? qsTr("正在获取…")
                                                      : (root.detail ? root.detail.orderStatus : "")
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: root.fntSmall
                elide: Text.ElideRight
            }

            FButton {
                id: copySell
                height: parent.height
                text: qsTr("复制卖单价 %1").arg(root.detail ? root.detail.bestSellText : "—")
                enabled: root.detail !== null && root.detail.sellOrderCount > 0
                onClicked: if (root.detail)
                    root.detail.copyPrice(1)
            }

            FButton {
                id: copyBuy
                height: parent.height
                text: qsTr("复制买单价 %1").arg(root.detail ? root.detail.bestBuyText : "—")
                enabled: root.detail !== null && root.detail.buyOrderCount > 0
                onClicked: if (root.detail)
                    root.detail.copyPrice(0)
            }
        }

        // ── 两侧标题（「卖单」「买单」塞不进「#/价格/数量/空间站」的列里，单起一行）──
        Row {
            width: parent.width
            height: root.labelH
            spacing: Theme.spacingSm

            Text {
                width: (parent.width - Theme.spacingSm) / 2
                height: parent.height
                verticalAlignment: Text.AlignVCenter
                text: qsTr("卖单 · %1 条").arg(root.detail ? root.detail.sellOrderCount : 0)
                color: Theme.accentRed
                font.family: Theme.fontFamily
                font.pixelSize: root.fntSmall
            }

            Text {
                width: (parent.width - Theme.spacingSm) / 2
                height: parent.height
                verticalAlignment: Text.AlignVCenter
                text: qsTr("买单 · %1 条").arg(root.detail ? root.detail.buyOrderCount : 0)
                color: Theme.accentGreen
                font.family: Theme.fontFamily
                font.pixelSize: root.fntSmall
            }
        }

        // ── 两侧订单表 ────────────────────────────────────────
        Row {
            width: parent.width
            height: parent.height - root.barH - root.labelH - 2 * Theme.spacingXs
            spacing: Theme.spacingSm

            PanelTable {
                width: (parent.width - Theme.spacingSm) / 2
                height: parent.height
                headers: root.heads
                ratios: [0.5, 1.4, 1.0, 2.6]
                rows: root.detail ? root.detail.sellOrderRows : []
                emptyText: root.detail && root.detail.typeId > 0 ? qsTr("暂无卖单") : ""
            }

            PanelTable {
                width: (parent.width - Theme.spacingSm) / 2
                height: parent.height
                headers: root.heads
                ratios: [0.5, 1.4, 1.0, 2.6]
                rows: root.detail ? root.detail.buyOrderRows : []
                emptyText: root.detail && root.detail.typeId > 0 ? qsTr("暂无买单") : ""
            }
        }
    }
}
