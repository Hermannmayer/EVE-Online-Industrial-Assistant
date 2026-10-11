import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 发明结果回填（**列表版**，批量下线用）。
 *
 * 单条版见 InventionOutcomeDialog.qml —— 那个仍在单行下线 / 小助手路径上。
 * 批量下线一次可能下线十几条发明计划，逐条弹窗就是 N 次「确认 + 关闭」；
 * 这里一屏列完：每行填自己的成功产线数，右侧实时换算实际流程数。
 *
 * 行列表用 Flickable + ColumnLayout + Repeater（照 ChildParallelDialog），**不用 ListView**：
 * 行内是可编辑控件，ListView 回收重建会把用户输入连带绑定一起丢掉。
 * 行数据是常量（`bridge.rows`），成功数真值在桥里；批量「全部失败」后各行靠
 * `valueChanged` 心跳回读（同 BlueprintPickerDialog 的勾选态）。
 */

FDialogFrame {
    id: frame

    readonly property var inv: typeof bridge !== "undefined" ? bridge : null

    dlg: frame.inv
    acceptText: qsTr("确认并完成")
    acceptEnabled: frame.inv ? frame.inv.canAccept : true

    // ── 列宽（表头与行共用这一份，改一处两边同时对齐）──
    readonly property int colNum: Math.round(76 * Theme.fontScale)
    readonly property int colDec: Math.round(120 * Theme.fontScale)
    readonly property int colPer: Math.round(104 * Theme.fontScale)
    readonly property int colSpin: Math.round(112 * Theme.fontScale)
    readonly property int colOut: Math.round(112 * Theme.fontScale)
    readonly property int colFail: Math.round(96 * Theme.fontScale)
    readonly property int rowHeight: Math.round(36 * Theme.fontScale)

    // ── 顶部提示：与单条版同口径（失败行的消耗不退）──
    Text {
        Layout.fillWidth: true
        text: frame.inv ? frame.inv.hintText : ""
        color: frame.inv && frame.inv.totalBpc > 0 ? Theme.textSecondary : Theme.accentYellow
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fs(12)
        wrapMode: Text.WordWrap
    }

    // ── 表头 ──
    Rectangle {
        Layout.fillWidth: true
        implicitHeight: Math.round(26 * Theme.fontScale)
        color: Theme.bgSurfaceLight

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: Theme.spacingSm
            anchors.rightMargin: Theme.spacingSm
            spacing: Theme.spacingSm

            Text {
                Layout.fillWidth: true
                text: qsTr("产物")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fs(12)
            }
            Text {
                Layout.preferredWidth: frame.colNum
                horizontalAlignment: Text.AlignRight
                text: qsTr("总尝试次数")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fs(12)
            }
            Text {
                Layout.preferredWidth: frame.colDec
                text: qsTr("解码器")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fs(12)
            }
            Text {
                Layout.preferredWidth: frame.colPer
                horizontalAlignment: Text.AlignRight
                text: qsTr("每次成功产出")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fs(12)
            }
            Text {
                Layout.preferredWidth: frame.colSpin
                horizontalAlignment: Text.AlignHCenter
                text: qsTr("成功产线数")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fs(12)
            }
            Text {
                Layout.preferredWidth: frame.colOut
                horizontalAlignment: Text.AlignRight
                text: qsTr("实际流程数")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fs(12)
            }
            Text {
                Layout.preferredWidth: frame.colFail
                horizontalAlignment: Text.AlignHCenter
                text: qsTr("操作")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fs(12)
            }
        }
    }

    // ── 行 ──
    Rectangle {
        Layout.fillWidth: true
        Layout.fillHeight: true
        color: Theme.bgSurface
        radius: Theme.radius
        border.width: 1
        border.color: Theme.border

        Flickable {
            anchors.fill: parent
            anchors.margins: 1
            contentHeight: rowColumn.implicitHeight
            clip: true
            boundsBehavior: Flickable.StopAtBounds

            ScrollBar.vertical: ScrollBar {
                policy: ScrollBar.AsNeeded
            }

            ColumnLayout {
                id: rowColumn
                width: parent.width
                spacing: 0

                Repeater {
                    model: frame.inv ? frame.inv.rows : []

                    Rectangle {
                        id: rowBox
                        required property var modelData
                        required property int index

                        //: 本行当前成功产线数（真值在桥里；这里是给「= N 流程」实时换算用）
                        property int successes: rowBox.modelData.successes

                        Layout.fillWidth: true
                        implicitHeight: frame.rowHeight
                        color: rowBox.index % 2 === 0 ? Theme.bgSurface : Theme.bgDark

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: Theme.spacingSm
                            anchors.rightMargin: Theme.spacingSm
                            spacing: Theme.spacingSm

                            Text {
                                Layout.fillWidth: true
                                verticalAlignment: Text.AlignVCenter
                                text: rowBox.modelData.name
                                color: Theme.textPrimary
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fs(12)
                                elide: Text.ElideRight
                            }
                            Text {
                                Layout.preferredWidth: frame.colNum
                                horizontalAlignment: Text.AlignRight
                                verticalAlignment: Text.AlignVCenter
                                text: rowBox.modelData.attempts
                                color: Theme.textSecondary
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fs(12)
                            }
                            Text {
                                Layout.preferredWidth: frame.colDec
                                verticalAlignment: Text.AlignVCenter
                                text: rowBox.modelData.decryptor
                                color: Theme.textSecondary
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fs(12)
                                elide: Text.ElideRight
                            }
                            Text {
                                Layout.preferredWidth: frame.colPer
                                horizontalAlignment: Text.AlignRight
                                verticalAlignment: Text.AlignVCenter
                                text: qsTr("%1 流程").arg(rowBox.modelData.runsPerBpc)
                                color: Theme.textSecondary
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fs(12)
                            }
                            FSpinBox {
                                id: successSpin
                                Layout.preferredWidth: frame.colSpin
                                from: 0
                                // 一条产线最多成功一次 → 上限就是本计划的**总**尝试次数（runs × 并行数）
                                to: rowBox.modelData.attempts
                                value: rowBox.successes
                                onValueModified: {
                                    rowBox.successes = value;
                                    if (frame.inv)
                                        frame.inv.setSuccesses(rowBox.index, value);
                                }

                                HoverHandler {
                                    id: spinHover
                                }
                                ToolTip.visible: spinHover.hovered
                                ToolTip.text: qsTr("按游戏里实际成功的产线条数填写（上限 = 本计划总尝试次数 runs×并行）；一条都没成功就填 0")
                            }
                            Text {
                                Layout.preferredWidth: frame.colOut
                                horizontalAlignment: Text.AlignRight
                                verticalAlignment: Text.AlignVCenter
                                text: qsTr("= %1 流程").arg(rowBox.successes * rowBox.modelData.runsPerBpc)
                                color: rowBox.successes > 0 ? Theme.textPrimary : Theme.textSecondary
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fs(12)
                            }
                            FButton {
                                Layout.preferredWidth: frame.colFail
                                compact: true
                                text: qsTr("发明失败")
                                onClicked: if (frame.inv)
                                    frame.inv.markFailed(rowBox.index)

                                HoverHandler {
                                    id: failHover
                                }
                                ToolTip.visible: failHover.hovered
                                ToolTip.text: qsTr("把该行成功数置 0（材料与输入蓝图流程已被消耗，这是游戏事实）")
                            }
                        }

                        /* 桥是成功数的真值源：逐行编辑只影响本行，但「全部失败」要同步所有行 ——
                         * 靠这一条心跳回读。`successSpin.value` 在用户编辑后绑定已断，必须显式赋值。 */
                        Connections {
                            target: frame.inv
                            function onValueChanged() {
                                if (!frame.inv)
                                    return;
                                const v = frame.inv.successAt(rowBox.index);
                                rowBox.successes = v;
                                successSpin.value = v;
                            }
                        }
                    }
                }
            }
        }
    }

    // ── 批量操作 + 合计 ──
    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spacingSm

        FButton {
            text: qsTr("全部发明失败")
            onClicked: if (frame.inv)
                frame.inv.markAllFailed()

            HoverHandler {
                id: allFailHover
            }
            ToolTip.visible: allFailHover.hovered
            ToolTip.text: qsTr("把本批所有行的成功数一次置 0（材料与输入蓝图流程已被消耗，这是游戏事实）")
        }

        Text {
            Layout.fillWidth: true
            horizontalAlignment: Text.AlignRight
            text: frame.inv
                  ? qsTr("合计 %1 张 BPC / %2 流程").arg(frame.inv.totalBpc).arg(frame.inv.totalRuns)
                  : ""
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fs(12)
        }
    }
}
