import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 「选择要移动的物品」对话框（阶段 4b-3）。
 *
 * 这是「来自其他机库」右键项的第二级弹出：列出该机库现有物品（名称 + 数量），
 * 勾选要移入的行。对应 Widgets 版 `ImportReviewDialog._add_from_hangar` 里现搭的
 * 那个 QDialog —— 一并迁过来，否则它会从 QML 对话框里冒出一个纯 Widgets 窗口。
 *
 * 新勾选框默认全选（原版如此）；没有行选中态，勾选即结果，所以不需要命中区。
 *
 * **勾选不重建行模型**（2026-09-27）：勾选只打桥的 `checkRevision` 心跳，复选框按心跳回读。
 * 原先 `setChecked()` 会发 `stateChanged`（`rows` 的通知信号）→ 这里的 `model` 是普通 var
 * 列表 → `ListView` 整体重建 → **滚动位置回顶**：滑到中段点一格，列表跳回最顶端。
 */

FDialogFrame {
    id: frame

    readonly property var hp: typeof bridge !== "undefined" ? bridge : null

    dlg: frame.hp
    acceptText: qsTr("确定")

    Rectangle {
        Layout.fillWidth: true
        Layout.fillHeight: true
        color: Theme.bgSurface
        radius: Theme.radius
        border.width: 1
        border.color: Theme.border

        ListView {
            id: rowList
            anchors.fill: parent
            anchors.margins: 1
            clip: true
            model: frame.hp ? frame.hp.rows : []
            boundsBehavior: Flickable.StopAtBounds

            ScrollBar.vertical: ScrollBar {
                policy: ScrollBar.AsNeeded
            }

            delegate: Item {
                id: rowItem
                required property var modelData
                required property int index

                width: rowList.width
                implicitHeight: Math.round(30 * Theme.fontScale)

                Rectangle {
                    anchors.fill: parent
                    color: rowItem.index % 2 === 0 ? Theme.bgSurface : Theme.bgDark
                }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: Theme.spacingSm
                    anchors.rightMargin: Theme.spacingSm
                    spacing: Theme.spacingSm

                    /* 勾选态由桥持有（`modelData.checked` 只是打开那一刻的初值），QML 只负责
                     * 画：点一下 → 交给桥 → 回读桥的值；`Component.onCompleted` 的回读管
                     * 「行被 ListView 回收后重建」（不回读会显示成打开时的旧值），
                     * `Connections` 那条心跳管其它行的改动。 */
                    FCheckBox {
                        id: checkBox
                        checked: rowItem.modelData.checked
                        onToggled: {
                            if (!frame.hp)
                                return
                            frame.hp.setChecked(rowItem.index, checked)
                            checkBox.checked = frame.hp.isChecked(rowItem.index)
                        }

                        Component.onCompleted: if (frame.hp)
                            checkBox.checked = frame.hp.isChecked(rowItem.index)

                        Connections {
                            target: frame.hp
                            function onCheckRevisionChanged() {
                                checkBox.checked = frame.hp ? frame.hp.isChecked(rowItem.index) : false
                            }
                        }
                    }

                    Text {
                        Layout.fillWidth: true
                        verticalAlignment: Text.AlignVCenter
                        text: rowItem.modelData.name
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: Math.round(12 * Theme.fontScale)
                        elide: Text.ElideRight
                    }

                    Text {
                        Layout.preferredWidth: Math.round(120 * Theme.fontScale)
                        verticalAlignment: Text.AlignVCenter
                        horizontalAlignment: Text.AlignRight
                        text: rowItem.modelData.qtyText
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: Math.round(12 * Theme.fontScale)
                    }
                }
            }
        }
    }
}
