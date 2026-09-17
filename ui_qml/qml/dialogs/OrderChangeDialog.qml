import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 订单变动确认对话框 —— 读订单后逐条选定「成交 / 手动撤销」。
 *
 * 对照原实现：原先只有一个「是 / 否」问答（「要把没出现的旧订单标记为已结束吗」），
 * 既分不出「卖出成交」和「自己撤销」，也没法据此调钱包。这里换成一张表：
 *
 *   物品 | 方向 | 价格 | 变动数量 | 变动 | 处置[买到了 / 卖完了 ▾]
 *
 * 每行的处置是三选一下拉（实际两项：成交 / 手动撤销），默认「成交」。
 * 顶部一行汇总（消失 N 条 / 变少 M 条 + 预计钱包变化），底部给「应用变动」。
 *
 * **行区用 Flickable + Column + Repeater，不用 ListView**，与 `ImportReviewDialog.qml`
 * 同一条理由：这里的行内要放 `FComboBox`，行号与控件坐标绑定在声明式子项上最稳。
 *
 * 颜色一律取自 `Theme`（铁律），本文件不写任何色值。
 */

FDialogFrame {
    id: frame

    readonly property var oc: typeof bridge !== "undefined" ? bridge : null

    dlg: frame.oc
    acceptText: qsTr("应用变动")
    cancelText: qsTr("取消")
    acceptEnabled: frame.oc ? frame.oc.hasRows : false

    readonly property int fntSmall: Math.round(11 * Theme.fontScale)
    readonly property int fntBase: Math.round(12 * Theme.fontScale)
    readonly property int rowH: Math.round(30 * Theme.fontScale)
    //: 各列宽度（与表头共用，改一处即可）
    readonly property var colW: [
        Math.round(190 * Theme.fontScale),   // 物品
        Math.round(44 * Theme.fontScale),    // 方向
        Math.round(104 * Theme.fontScale),   // 价格
        Math.round(80 * Theme.fontScale),    // 变动数量
        Math.round(112 * Theme.fontScale),   // 变动
        -1                                   // 处置（吃满剩余）
    ]
    //: 处置下拉的宽度上限 —— 只有两个选项，占满整列会看着空荡
    readonly property int outcomeW: Math.round(188 * Theme.fontScale)

    function colX(index) {
        let x = 0;
        for (let i = 0; i < index; ++i) {
            const w = frame.colW[i];
            if (w > 0)
                x += w;
        }
        return x;
    }

    // ── 汇总 + 预计钱包变化 ─────────────────────────────────
    Text {
        Layout.fillWidth: true
        text: frame.oc ? frame.oc.summary : ""
        color: Theme.textSecondary
        font.family: Theme.fontFamily
        font.pixelSize: frame.fntSmall
        wrapMode: Text.WordWrap
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spacingMd

        Text {
            text: frame.oc ? frame.oc.walletText : ""
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: frame.fntBase
        }

        Item {
            Layout.fillWidth: true
        }

        Text {
            text: frame.oc ? frame.oc.deltaText : ""
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: frame.fntBase
            font.bold: true
        }
    }

    // ── 表头 ────────────────────────────────────────────────
    Rectangle {
        Layout.fillWidth: true
        implicitHeight: Math.round(24 * Theme.fontScale)
        color: Theme.bgSurfaceLight
        radius: Theme.radiusSmall

        Repeater {
            model: [qsTr("物品"), qsTr("方向"), qsTr("价格"), qsTr("变动数量"), qsTr("变动"), qsTr("处置")]

            Text {
                required property int index
                required property var modelData
                x: frame.colX(index) + Theme.spacingSm
                width: (frame.colW[index] > 0 ? frame.colW[index] : frame.width - frame.colX(index))
                       - 2 * Theme.spacingSm
                height: parent.height
                verticalAlignment: Text.AlignVCenter
                text: String(modelData)
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: frame.fntSmall
                elide: Text.ElideRight
            }
        }
    }

    // ── 变动条目 ────────────────────────────────────────────
    Rectangle {
        Layout.fillWidth: true
        Layout.fillHeight: true
        color: Theme.bgSurface
        border.width: 1
        border.color: Theme.border
        radius: Theme.radius

        Flickable {
            anchors.fill: parent
            anchors.margins: 1
            clip: true
            contentWidth: width
            contentHeight: rowColumn.implicitHeight
            boundsBehavior: Flickable.StopAtBounds

            ScrollBar.vertical: ScrollBar {
                policy: ScrollBar.AsNeeded
            }

            Column {
                id: rowColumn
                width: parent.width
                spacing: 0

                Repeater {
                    model: frame.oc ? frame.oc.rows : []

                    Item {
                        id: changeRow
                        required property int index
                        required property var modelData

                        width: rowColumn.width
                        height: frame.rowH

                        Rectangle {
                            anchors.fill: parent
                            color: index % 2 === 0 ? "transparent" : Theme.bgSurfaceLight
                            opacity: index % 2 === 0 ? 1.0 : 0.5
                        }

                        Text {
                            x: frame.colX(0) + Theme.spacingSm
                            width: frame.colW[0] - 2 * Theme.spacingSm
                            height: parent.height
                            verticalAlignment: Text.AlignVCenter
                            text: changeRow.modelData.name
                            color: Theme.textPrimary
                            font.family: Theme.fontFamily
                            font.pixelSize: frame.fntBase
                            elide: Text.ElideRight

                            HoverHandler {
                                id: nameHover
                            }
                            ToolTip.visible: nameHover.hovered
                            ToolTip.text: qsTr("订单 ID %1").arg(changeRow.modelData.orderId)
                        }

                        Text {
                            x: frame.colX(1) + Theme.spacingSm
                            width: frame.colW[1] - 2 * Theme.spacingSm
                            height: parent.height
                            verticalAlignment: Text.AlignVCenter
                            text: changeRow.modelData.is_buy ? qsTr("买") : qsTr("卖")
                            color: changeRow.modelData.is_buy ? Theme.accentGreen : Theme.accentRed
                            font.family: Theme.fontFamily
                            font.pixelSize: frame.fntBase
                        }

                        Text {
                            x: frame.colX(2) + Theme.spacingSm
                            width: frame.colW[2] - 2 * Theme.spacingSm
                            height: parent.height
                            verticalAlignment: Text.AlignVCenter
                            horizontalAlignment: Text.AlignRight
                            text: changeRow.modelData.priceText
                            color: Theme.textPrimary
                            font.family: Theme.fontFamily
                            font.pixelSize: frame.fntBase
                            elide: Text.ElideRight
                        }

                        Text {
                            x: frame.colX(3) + Theme.spacingSm
                            width: frame.colW[3] - 2 * Theme.spacingSm
                            height: parent.height
                            verticalAlignment: Text.AlignVCenter
                            horizontalAlignment: Text.AlignRight
                            text: changeRow.modelData.volumeText
                            color: Theme.textPrimary
                            font.family: Theme.fontFamily
                            font.pixelSize: frame.fntBase
                            elide: Text.ElideRight
                        }

                        Text {
                            x: frame.colX(4) + Theme.spacingSm
                            width: frame.colW[4] - 2 * Theme.spacingSm
                            height: parent.height
                            verticalAlignment: Text.AlignVCenter
                            text: changeRow.modelData.kindText
                            color: Theme.textSecondary
                            font.family: Theme.fontFamily
                            font.pixelSize: frame.fntSmall
                            elide: Text.ElideRight
                        }

                        FComboBox {
                            id: outcomeBox
                            objectName: "outcomeBox"
                            x: frame.colX(5) + Theme.spacingSm
                            width: Math.min(frame.outcomeW,
                                            Math.max(120, rowColumn.width - frame.colX(5) - 2 * Theme.spacingSm))
                            anchors.verticalCenter: parent.verticalCenter
                            model: frame.oc ? frame.oc.choices : []
                            currentIndex: changeRow.modelData.outcomeIndex
                            onActivated: if (frame.oc)
                                frame.oc.setOutcomeIndex(changeRow.index, currentIndex)
                        }
                    }
                }

                Text {
                    width: parent.width
                    height: frame.rowH
                    visible: frame.oc ? !frame.oc.hasRows : false
                    verticalAlignment: Text.AlignVCenter
                    horizontalAlignment: Text.AlignHCenter
                    text: qsTr("本次导入没有发现订单变动")
                    color: Theme.textSecondary
                    font.family: Theme.fontFamily
                    font.pixelSize: frame.fntSmall
                }
            }
        }
    }
}
