import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 编辑生产计划（阶段 4 的第一个 QML 对话框）。
 *
 * 承载在 `ui_qml/dialog_host.QmlDialog` 里 —— 窗口行为（模态/居中/Esc）是 QDialog 的，
 * 这里只画内容。业务与校验都在 `bridge`（`plan_edit_bridge.py`）里，
 * 与 Widgets 版 `PlanEditDialog.get_updated_data()` 同形。
 *
 * 用的是自己的 `bridge` 而不是页面那套（对话框由 Python 侧 `exec()` 调用）。
 */

Item {
    id: root

    readonly property var dlg: typeof bridge !== "undefined" ? bridge : null

    readonly property int fntBase: Math.round(12 * Theme.fontScale)
    readonly property int gap: Theme.spacingSm
    readonly property int labelWidth: Math.round(88 * Theme.fontScale)

    /* 对话框底色。**必须自己铺**：宿主 `PageHost` 透明清屏 + `WA_TranslucentBackground`，
     * 没画到的地方直接透出窗口背后，真窗口抓屏是纯黑（离屏快照反而看不出来，会被补成
     * 调色板底色）。本对话框比 `FDialogFrame` 早，没走那个骨架，所以在这儿自己补一块。*/
    Rectangle {
        anchors.fill: parent
        color: Theme.bgDark
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.spacingMd
        spacing: root.gap

        // ── 产品名称（只读）──
        RowLayout {
            Layout.fillWidth: true
            spacing: root.gap

            Text {
                Layout.preferredWidth: root.labelWidth
                horizontalAlignment: Text.AlignRight
                text: qsTr("产品名称")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: root.fntBase
            }
            Text {
                Layout.fillWidth: true
                text: root.dlg ? root.dlg.productLabel : ""
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: root.fntBase
                elide: Text.ElideRight
                textFormat: Text.PlainText
            }
        }

        // ── 流程数 ──
        RowLayout {
            Layout.fillWidth: true
            spacing: root.gap

            Text {
                Layout.preferredWidth: root.labelWidth
                horizontalAlignment: Text.AlignRight
                text: root.dlg ? root.dlg.runsLabel : qsTr("流程数")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: root.fntBase
            }
            FSpinBox {
                Layout.preferredWidth: 140
                from: 1
                to: 99999
                value: root.dlg ? root.dlg.runs : 1
                onValueModified: if (root.dlg)
                    root.dlg.setRuns(value)

                HoverHandler {
                    id: runsHover
                }
                ToolTip.visible: runsHover.hovered && text !== ""
                ToolTip.text: root.dlg ? root.dlg.runsTip : ""
            }
            Item {
                Layout.fillWidth: true
            }
        }

        // ── 并行数 / 产出份数 ──
        RowLayout {
            Layout.fillWidth: true
            spacing: root.gap

            Text {
                Layout.preferredWidth: root.labelWidth
                horizontalAlignment: Text.AlignRight
                text: root.dlg ? root.dlg.parallelLabel : qsTr("并行数")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: root.fntBase
            }
            FSpinBox {
                Layout.preferredWidth: 140
                from: 1
                to: 100
                value: root.dlg ? root.dlg.parallels : 1
                onValueModified: if (root.dlg)
                    root.dlg.setParallels(value)

                HoverHandler {
                    id: parHover
                }
                ToolTip.visible: parHover.hovered && (root.dlg ? root.dlg.parallelTip !== "" : false)
                ToolTip.text: root.dlg ? root.dlg.parallelTip : ""
            }
            Item {
                Layout.fillWidth: true
            }
        }

        // ── 批量模式：显式勾选才同步流程/并行 ──
        RowLayout {
            Layout.fillWidth: true
            visible: root.dlg ? root.dlg.batchMode : false
            spacing: root.gap

            Item {
                Layout.preferredWidth: root.labelWidth
            }
            FCheckBox {
                text: qsTr("同步流程数与并行数到所有选中行")
                checked: root.dlg ? root.dlg.syncRuns : false
                onToggled: if (root.dlg)
                    root.dlg.setSyncRuns(checked)
            }
        }

        // ── 人物 ──
        RowLayout {
            Layout.fillWidth: true
            spacing: root.gap

            Text {
                Layout.preferredWidth: root.labelWidth
                horizontalAlignment: Text.AlignRight
                text: qsTr("人物")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: root.fntBase
            }
            FComboBox {
                Layout.preferredWidth: 200
                model: root.dlg ? root.dlg.chars : []
                currentIndex: root.dlg ? root.dlg.charIndex : 0
                onActivated: if (root.dlg)
                    root.dlg.setCharIndex(currentIndex)
            }
            Item {
                Layout.fillWidth: true
            }
        }

        // ── 产出机库 / 材料机库 ──
        Repeater {
            model: [
                {
                    "label": qsTr("产出机库"),
                    "index": root.dlg ? root.dlg.depositIndex : 0,
                    "setter": "setDepositIndex"
                },
                {
                    "label": qsTr("材料机库"),
                    "index": root.dlg ? root.dlg.matIndex : 0,
                    "setter": "setMatIndex"
                }
            ]

            RowLayout {
                required property var modelData
                Layout.fillWidth: true
                spacing: root.gap

                Text {
                    Layout.preferredWidth: root.labelWidth
                    horizontalAlignment: Text.AlignRight
                    text: modelData.label
                    color: Theme.textPrimary
                    font.family: Theme.fontFamily
                    font.pixelSize: root.fntBase
                }
                FComboBox {
                    Layout.preferredWidth: 260
                    model: root.dlg ? root.dlg.hangars : []
                    currentIndex: modelData.index
                    onActivated: if (root.dlg)
                        root.dlg[modelData.setter](currentIndex)
                }
                Item {
                    Layout.fillWidth: true
                }
            }
        }

        // ── 备注 ──
        RowLayout {
            Layout.fillWidth: true
            spacing: root.gap

            Text {
                Layout.preferredWidth: root.labelWidth
                Layout.alignment: Qt.AlignTop
                horizontalAlignment: Text.AlignRight
                text: qsTr("备注")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: root.fntBase
            }
            FTextField {
                id: notesField
                Layout.fillWidth: true
                placeholderText: qsTr("备注信息…")
                text: root.dlg ? root.dlg.notes : ""
                onTextChanged: if (root.dlg)
                    root.dlg.setNotes(text)
            }
        }

        // ── 校验提示 ──
        Text {
            Layout.fillWidth: true
            visible: (root.dlg ? root.dlg.error : "") !== ""
            text: root.dlg ? root.dlg.error : ""
            color: Theme.accentRed
            font.family: Theme.fontFamily
            font.pixelSize: root.fntBase
            horizontalAlignment: Text.AlignRight
        }

        Item {
            Layout.fillHeight: true
        }

        // ── 按钮 ──
        RowLayout {
            Layout.fillWidth: true
            spacing: root.gap

            Item {
                Layout.fillWidth: true
            }
            FButton {
                text: qsTr("取消")
                onClicked: if (root.dlg)
                    root.dlg.reject()
            }
            FButton {
                text: qsTr("确定")
                primary: true
                onClicked: if (root.dlg)
                    root.dlg.accept()
            }
        }
    }
}
