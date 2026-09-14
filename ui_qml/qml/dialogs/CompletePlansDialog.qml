import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 下线确认（阶段 4）。
 *
 * 清单行由桥算好（产出量 = 流程 × 并行 × 每次产出，口径与 Widgets 版一致），
 * 这里只画；「确认下线」返回选中的产出机库 id。
 */

FDialogFrame {
    id: frame

    readonly property var cp: typeof bridge !== "undefined" ? bridge : null

    dlg: frame.cp
    acceptText: qsTr("确认下线")

    readonly property int colWidthName: Math.round(200 * Theme.fontScale)
    readonly property int colWidthRuns: Math.round(90 * Theme.fontScale)
    readonly property int colWidthQty: Math.round(100 * Theme.fontScale)

    Text {
        Layout.fillWidth: true
        text: frame.cp ? frame.cp.tipText : ""
        color: Theme.textSecondary
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(12 * Theme.fontScale)
        wrapMode: Text.WordWrap
    }

    // ── 清单 ──
    Rectangle {
        Layout.fillWidth: true
        Layout.fillHeight: true
        color: Theme.bgSurface
        radius: Theme.radius
        border.width: 1
        border.color: Theme.border

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 1
            spacing: 0

            // 表头
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: Math.round(26 * Theme.fontScale)
                color: Theme.bgSurfaceLight

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 8
                    anchors.rightMargin: 8
                    spacing: Theme.spacingSm

                    Repeater {
                        model: [
                            {
                                "text": frame.cp ? frame.cp.headers[0] : "",
                                "width": frame.colWidthName,
                                "align": Text.AlignLeft,
                                "fill": false
                            },
                            {
                                "text": frame.cp ? frame.cp.headers[1] : "",
                                "width": frame.colWidthRuns,
                                "align": Text.AlignRight,
                                "fill": false
                            },
                            {
                                "text": frame.cp ? frame.cp.headers[2] : "",
                                "width": frame.colWidthQty,
                                "align": Text.AlignRight,
                                "fill": false
                            },
                            {
                                "text": frame.cp ? frame.cp.headers[3] : "",
                                "width": 0,
                                "align": Text.AlignLeft,
                                "fill": true
                            }
                        ]

                        Text {
                            required property var modelData
                            Layout.preferredWidth: modelData.fill ? 0 : modelData.width
                            Layout.fillWidth: modelData.fill
                            verticalAlignment: Text.AlignVCenter
                            horizontalAlignment: modelData.align
                            text: modelData.text
                            color: Theme.textPrimary
                            font.family: Theme.fontFamily
                            font.pixelSize: Math.round(12 * Theme.fontScale)
                            elide: Text.ElideRight
                        }
                    }
                }
            }

            Flickable {
                Layout.fillWidth: true
                Layout.fillHeight: true
                contentHeight: rowColumn.implicitHeight
                clip: true

                ColumnLayout {
                    id: rowColumn
                    width: parent.width
                    spacing: 0

                    Repeater {
                        model: frame.cp ? frame.cp.rows : []

                        Rectangle {
                            required property var modelData
                            required property int index

                            Layout.fillWidth: true
                            implicitHeight: Math.round(26 * Theme.fontScale)
                            color: index % 2 === 0 ? Theme.bgSurface : Theme.bgDark

                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 8
                                anchors.rightMargin: 8
                                spacing: Theme.spacingSm

                                Text {
                                    Layout.preferredWidth: frame.colWidthName
                                    text: modelData.name
                                    color: Theme.textPrimary
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Math.round(12 * Theme.fontScale)
                                    elide: Text.ElideRight
                                }
                                Text {
                                    Layout.preferredWidth: frame.colWidthRuns
                                    horizontalAlignment: Text.AlignRight
                                    text: modelData.runs
                                    color: Theme.textPrimary
                                    font.family: "Consolas"
                                    font.pixelSize: Math.round(12 * Theme.fontScale)
                                }
                                Text {
                                    Layout.preferredWidth: frame.colWidthQty
                                    horizontalAlignment: Text.AlignRight
                                    text: modelData.qty
                                    color: Theme.textPrimary
                                    font.family: "Consolas"
                                    font.pixelSize: Math.round(12 * Theme.fontScale)
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: modelData.deposit
                                    color: Theme.textSecondary
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Math.round(12 * Theme.fontScale)
                                    elide: Text.ElideRight
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    // ── 产出机库 ──
    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spacingSm

        Text {
            text: qsTr("产出机库:")
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }
        FComboBox {
            Layout.fillWidth: true
            model: frame.cp ? frame.cp.hangarNames : []
            currentIndex: frame.cp ? frame.cp.hangarIndex : 0
            onActivated: if (frame.cp)
                frame.cp.setHangarIndex(currentIndex)
        }
    }

    Text {
        Layout.fillWidth: true
        text: frame.cp ? frame.cp.summaryText : ""
        color: Theme.textSecondary
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(11 * Theme.fontScale)
    }
}
