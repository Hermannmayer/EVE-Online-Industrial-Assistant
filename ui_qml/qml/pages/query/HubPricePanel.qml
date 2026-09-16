import QtQuick
import QtQuick.Controls

/* 详情面板 · 五个默认贸易中心的价格（卖单 / 买单各一行，带柱形条）。
 *
 * 对应界面标注图「5 个默认贸易中心的价格（带柱形图显示）／卖单和买单价／
 * 每个中心两行／左侧中心带所在帝国的图标」。
 *
 * **帝国图标用带色圆点**：本仓没有帝国旗帜位图资产，为一张 8px 的点新增 4 个 PNG
 * 并不划算，而圆点用主题里的强调色就能表达「哪个帝国」且四色可辨
 * （Amarr 黄 / Caldari 青 / Gallente 绿 / Minmatar 红，映射在桥的纯函数里）。
 *
 * 柱长与最优标记**全部由桥算好**（`hubRows[].buyPos/sellPos/bestBuy/bestSell`），
 * 这里只做「归一化 × 可用宽度」的落点，不出现任何取最值/取整。
 */
Item {
    id: root

    //: `bridge.detail`
    property var detail: null

    readonly property var rows: detail ? detail.hubRows : []
    readonly property int fntSmall: Math.round(11 * Theme.fontScale)
    readonly property int fntBase: Math.round(12 * Theme.fontScale)
    readonly property int rowH: Math.max(40, Math.round(15 * Theme.fontScale) + 25)
    readonly property int headH: Math.max(20, fntSmall + 10)
    readonly property int dotSize: Math.max(7, Math.round(8 * Theme.fontScale))
    readonly property int nameW: Math.round(58 * Theme.fontScale)

    Column {
        anchors.fill: parent
        spacing: 0

        // ── 表头 ──────────────────────────────────────────────
        Item {
            width: parent.width
            height: root.headH

            Text {
                x: root.dotSize + Theme.spacingXs
                width: root.nameW
                height: parent.height
                verticalAlignment: Text.AlignVCenter
                text: qsTr("中心")
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: root.fntSmall
                elide: Text.ElideRight
            }
            Text {
                x: root.dotSize + Theme.spacingXs + root.nameW
                width: (parent.width - x) / 2
                height: parent.height
                verticalAlignment: Text.AlignVCenter
                horizontalAlignment: Text.AlignRight
                text: qsTr("卖单 ↑")
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: root.fntSmall
                elide: Text.ElideRight
            }
            Text {
                x: root.dotSize + Theme.spacingXs + root.nameW + (parent.width - root.dotSize - Theme.spacingXs - root.nameW) / 2
                width: (parent.width - root.dotSize - Theme.spacingXs - root.nameW) / 2
                height: parent.height
                verticalAlignment: Text.AlignVCenter
                horizontalAlignment: Text.AlignRight
                text: qsTr("买单 ↓")
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: root.fntSmall
                elide: Text.ElideRight
            }

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: 1
                color: Theme.border
            }
        }

        // ── 行 ────────────────────────────────────────────────
        Item {
            width: parent.width
            height: parent.height - root.headH

            Text {
                anchors.centerIn: parent
                width: parent.width - 2 * Theme.spacingSm
                visible: root.rows.length === 0
                text: root.detail ? qsTr("选择一行查看该物品在各贸易中心的价格") : ""
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: root.fntSmall
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
            }

            ListView {
                id: hubList
                anchors.fill: parent
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                model: root.rows
                ScrollBar.vertical: ScrollBar {
                    policy: ScrollBar.AsNeeded
                }

                delegate: Item {
                    id: hubRow
                    required property var modelData
                    width: hubList.width
                    height: root.rowH

                    readonly property real restW: Math.max(1, width - root.dotSize - Theme.spacingXs - root.nameW)
                    readonly property real colW: restW / 2

                    // 卖单（左）
                    Rectangle {
                        anchors.left: parent.left
                        anchors.verticalCenter: parent.verticalCenter
                        width: root.dotSize
                        height: width
                        radius: width / 2
                        color: hubRow.modelData.empireColor
                        opacity: 0.9
                    }

                    Text {
                        x: root.dotSize + Theme.spacingXs
                        width: root.nameW
                        height: parent.height
                        verticalAlignment: Text.AlignVCenter
                        text: hubRow.modelData.hub
                        color: hubRow.modelData.bestSell ? Theme.accentGreen : Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: root.fntBase
                        font.bold: hubRow.modelData.bestSell || hubRow.modelData.bestBuy
                        elide: Text.ElideRight

                        HoverHandler {
                            id: hubHover
                        }
                        ToolTip.visible: hubHover.hovered
                        ToolTip.text: qsTr("%1 · %2").arg(hubRow.modelData.hub).arg(hubRow.modelData.empire)
                    }

                    Repeater {
                        model: [
                            {
                                "text": hubRow.modelData.sellText,
                                "pos": hubRow.modelData.sellPos,
                                "best": hubRow.modelData.bestSell
                            },
                            {
                                "text": hubRow.modelData.buyText,
                                "pos": hubRow.modelData.buyPos,
                                "best": hubRow.modelData.bestBuy
                            }
                        ]

                        Item {
                            id: priceCell
                            required property int index
                            required property var modelData

                            x: root.dotSize + Theme.spacingXs + root.nameW + index * hubRow.colW
                            width: hubRow.colW
                            height: hubRow.height

                            Rectangle {
                                visible: priceCell.modelData.pos > 0
                                anchors.right: parent.right
                                anchors.verticalCenter: parent.verticalCenter
                                width: Math.max(1, Math.round((parent.width - 6) * priceCell.modelData.pos))
                                height: Math.max(3, Math.round(parent.height * 0.34))
                                radius: Theme.radiusSmall
                                color: index === 0 ? Theme.accentRed : Theme.accentGreen
                                opacity: 0.30
                            }

                            Text {
                                anchors.fill: parent
                                anchors.rightMargin: Math.round(6 * Theme.fontScale)
                                verticalAlignment: Text.AlignVCenter
                                horizontalAlignment: Text.AlignRight
                                text: priceCell.modelData.text
                                color: priceCell.modelData.best
                                       ? (index === 0 ? Theme.accentGreen : Theme.accentRed)
                                       : Theme.textPrimary
                                font.family: Theme.fontFamily
                                font.pixelSize: root.fntBase
                                font.bold: priceCell.modelData.best
                                elide: Text.ElideRight
                            }
                        }
                    }
                }
            }
        }
    }
}
