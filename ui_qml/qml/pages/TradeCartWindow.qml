import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import "../components"

/* 贸易购物车窗口 —— 非模态工具窗，常与游戏同屏（顶部有「置顶」）。

 * 数据全在 `TradeCartController`（`ui_qml/views/trade_cart_window.py`）里，这里只画与转发。
 * 按**方向**分组：同一个起点/终点组合一块，每块一份统计栏 —— A→B、B→A、B→C 天然各成一块。
 * 行内「数量」可改、「已购买」可标记；双击名称复制（往游戏里贴单子用）。
 */
Window {
    id: win

    width: 820
    height: 560
    minimumWidth: 660
    minimumHeight: 300
    title: qsTr("贸易购物车")
    // 窗口清屏色 = 页面底色：首帧之前也不会闪一下白底
    color: Theme.bgDark
    visible: false // 由控制器 `show()` 打开（构造完不该自己冒出来）

    readonly property var cart: typeof bridge !== "undefined" ? bridge : null
    readonly property int fntBase: Math.round(12 * Theme.fontScale)
    readonly property int fntSmall: Math.round(11 * Theme.fontScale)
    readonly property int pad: Theme.spacingSm

    onVisibleChanged: if (win.cart)
        win.cart.onWindowVisibleChanged(win.visible)

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.spacingMd
        spacing: win.pad

        // ── 顶部：标题 + 清理 + 置顶 ───────────────────────────
        RowLayout {
            Layout.fillWidth: true
            spacing: win.pad

            Text {
                text: qsTr("贸易购物车")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(14 * Theme.fontScale)
                font.weight: Font.DemiBold
            }

            Item {
                Layout.fillWidth: true
            }

            FButton {
                objectName: "clearPurchasedButton"
                compact: true
                text: qsTr("清理已购买")
                onClicked: if (win.cart)
                    win.cart.clearPurchased()
            }

            FCheckBox {
                objectName: "pinBox"
                text: qsTr("置顶")
                checked: win.cart ? win.cart.pinned : false
                onToggled: if (win.cart)
                    win.cart.setPinned(checked)
            }
        }

        Text {
            objectName: "emptyHint"
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: win.cart ? win.cart.isEmpty : true
            text: qsTr("购物车是空的 — 在「市场贸易」页的排行表里点每行的「加入购物车」")
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: win.fntBase
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            wrapMode: Text.WordWrap
        }

        // ── 分组列表 ──────────────────────────────────────────
        Flickable {
            id: groupFlick
            objectName: "groupScroll"
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: win.cart ? !win.cart.isEmpty : false
            clip: true
            contentHeight: groupCol.height
            ScrollBar.vertical: ScrollBar {}

            Column {
                id: groupCol
                // 用 Flickable 是因为 ScrollView 会把自己的子项宽度与内容的 implicitWidth
                // 绑成一个环（`parent.width` 与 `availableWidth` 都会塌成隐式宽 583px，
                // 整块内容只铺左半屏）。Flickable 不自动管内容尺寸，这里显式绑，没有环。
                width: groupFlick.width
                spacing: Theme.spacingMd

                Repeater {
                    model: win.cart ? win.cart.groups : []

                    delegate: Column {
                        id: grp
                        required property int index
                        required property var modelData

                        readonly property var rows: grp.modelData ? grp.modelData.rows : []

                        width: groupCol.width
                        spacing: win.pad

                        Text {
                            width: parent.width
                            text: grp.modelData ? grp.modelData.label : ""
                            color: Theme.textPrimary
                            font.family: Theme.fontFamily
                            font.pixelSize: win.fntBase
                            font.weight: Font.DemiBold
                        }

                        //: 表头（与下面的行共用同一串宽度，改一处即可）
                        RowLayout {
                            width: parent.width
                            spacing: win.pad

                            Item { Layout.preferredWidth: 28 }
                            Text {
                                Layout.fillWidth: true
                                text: qsTr("名称")
                                color: Theme.textSecondary
                                font.family: Theme.fontFamily
                                font.pixelSize: win.fntSmall
                            }
                            Text {
                                Layout.preferredWidth: 90
                                text: qsTr("价差")
                                color: Theme.textSecondary
                                font.family: Theme.fontFamily
                                font.pixelSize: win.fntSmall
                                horizontalAlignment: Text.AlignRight
                            }
                            Text {
                                Layout.preferredWidth: 104
                                text: qsTr("数量")
                                color: Theme.textSecondary
                                font.family: Theme.fontFamily
                                font.pixelSize: win.fntSmall
                                horizontalAlignment: Text.AlignRight
                            }
                            Text {
                                Layout.preferredWidth: 110
                                text: qsTr("总计金额")
                                color: Theme.textSecondary
                                font.family: Theme.fontFamily
                                font.pixelSize: win.fntSmall
                                horizontalAlignment: Text.AlignRight
                            }
                            Item { Layout.preferredWidth: 76 }
                        }

                        Repeater {
                            model: grp.rows

                            delegate: RowLayout {
                                id: line
                                required property int index
                                required property var modelData

                                width: grp.width
                                spacing: win.pad

                                Image {
                                    Layout.preferredWidth: 28
                                    Layout.preferredHeight: 28
                                    source: line.modelData ? line.modelData.iconUrl : ""
                                    sourceSize.width: 28
                                    sourceSize.height: 28
                                    smooth: true
                                    fillMode: Image.PreserveAspectFit
                                }

                                // 双击复制名称；右键开行菜单
                                Text {
                                    id: nameText
                                    Layout.fillWidth: true
                                    text: line.modelData ? line.modelData.name : ""
                                    color: (line.modelData && line.modelData.purchased)
                                           ? Theme.textSecondary : Theme.textPrimary
                                    font.family: Theme.fontFamily
                                    font.pixelSize: win.fntBase
                                    elide: Text.ElideRight
                                    font.strikeout: line.modelData ? line.modelData.purchased : false

                                    MouseArea {
                                        anchors.fill: parent
                                        acceptedButtons: Qt.LeftButton | Qt.RightButton
                                        onDoubleClicked: if (win.cart)
                                            win.cart.copyName(grp.index, line.index)
                                        onClicked: function (mouse) {
                                            if (mouse.button === Qt.RightButton) {
                                                rowMenu.groupIndex = grp.index
                                                rowMenu.rowIndex = line.index
                                                rowMenu.itemName = nameText.text
                                                rowMenu.x = mouse.x
                                                rowMenu.y = mouse.y
                                                rowMenu.openSoon()
                                            }
                                        }
                                    }
                                }

                                Text {
                                    Layout.preferredWidth: 90
                                    text: line.modelData ? line.modelData.spreadText : ""
                                    color: Theme.textPrimary
                                    font.family: Theme.fontFamily
                                    font.pixelSize: win.fntBase
                                    horizontalAlignment: Text.AlignRight
                                }

                                FSpinBox {
                                    Layout.preferredWidth: 104
                                    from: 1
                                    to: 100000000
                                    value: line.modelData ? line.modelData.qty : 1
                                    onValueModified: if (win.cart)
                                        win.cart.setQty(grp.index, line.index, value)
                                }

                                Text {
                                    Layout.preferredWidth: 110
                                    text: line.modelData ? line.modelData.amountText : ""
                                    color: Theme.textPrimary
                                    font.family: Theme.fontFamily
                                    font.pixelSize: win.fntBase
                                    horizontalAlignment: Text.AlignRight
                                }

                                FButton {
                                    Layout.preferredWidth: 76
                                    compact: true
                                    text: (line.modelData && line.modelData.purchased)
                                          ? qsTr("已购买") : qsTr("标记购买")
                                    primary: !(line.modelData && line.modelData.purchased)
                                    onClicked: if (win.cart)
                                        win.cart.togglePurchased(grp.index, line.index)
                                }
                            }
                        }

                        Text {
                            width: parent.width
                            text: grp.modelData ? grp.modelData.summary : ""
                            color: Theme.textSecondary
                            font.family: Theme.fontFamily
                            font.pixelSize: win.fntSmall
                        }

                        Rectangle {
                            width: parent.width
                            height: 1
                            color: Theme.border
                        }
                    }
                }
            }
        }

        // ── 底部：整车汇总 ────────────────────────────────────
        Text {
            objectName: "summaryText"
            Layout.fillWidth: true
            text: win.cart ? win.cart.summaryText : ""
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: win.fntBase
            font.weight: Font.DemiBold
        }

        Text {
            objectName: "hintText"
            Layout.fillWidth: true
            text: win.cart ? win.cart.hintText : ""
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: win.fntSmall
            elide: Text.ElideRight
        }
    }

    FMenu {
        id: rowMenu
        objectName: "rowMenu"

        property int groupIndex: -1
        property int rowIndex: -1
        property string itemName: ""

        FMenuItem {
            text: qsTr("复制名称: ") + rowMenu.itemName
            onTriggered: if (win.cart)
                win.cart.copyName(rowMenu.groupIndex, rowMenu.rowIndex)
        }

        FMenuItem {
            text: qsTr("从购物车移除")
            onTriggered: if (win.cart)
                win.cart.removeItem(rowMenu.groupIndex, rowMenu.rowIndex)
        }
    }
}
