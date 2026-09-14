import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 子项并行配置（阶段 4）。
 *
 * 只需设置「并行产线数」——「每条流程」自动生成以覆盖母项需求，总产出实时刷新，
 * 有子项不达标时「保存」按钮禁用。
 */

FDialogFrame {
    id: frame

    readonly property var cp: typeof bridge !== "undefined" ? bridge : null

    dlg: frame.cp
    acceptText: qsTr("保存")

    readonly property int colName: Math.round(200 * Theme.fontScale)
    readonly property int colNum: Math.round(110 * Theme.fontScale)
    readonly property int colPar: Math.round(120 * Theme.fontScale)

    Text {
        Layout.fillWidth: true
        text: frame.cp ? frame.cp.tipText : ""
        color: Theme.textSecondary
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(11 * Theme.fontScale)
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
                Layout.preferredWidth: frame.colName
                text: frame.cp ? frame.cp.headers[0] : ""
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(12 * Theme.fontScale)
            }
            Text {
                Layout.preferredWidth: frame.colNum
                horizontalAlignment: Text.AlignRight
                text: frame.cp ? frame.cp.headers[1] : ""
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(12 * Theme.fontScale)
            }
            Text {
                Layout.preferredWidth: frame.colNum
                horizontalAlignment: Text.AlignRight
                text: frame.cp ? frame.cp.headers[2] : ""
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(12 * Theme.fontScale)
            }
            Text {
                Layout.preferredWidth: frame.colPar
                horizontalAlignment: Text.AlignHCenter
                text: frame.cp ? frame.cp.headers[3] : ""
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(12 * Theme.fontScale)
            }
            Text {
                Layout.preferredWidth: frame.colNum
                horizontalAlignment: Text.AlignRight
                text: frame.cp ? frame.cp.headers[4] : ""
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(12 * Theme.fontScale)
            }
            Text {
                Layout.fillWidth: true
                text: frame.cp ? frame.cp.headers[5] : ""
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(12 * Theme.fontScale)
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
                    model: frame.cp ? frame.cp.rows : []

                    Rectangle {
                        id: rowBox
                        required property var modelData
                        required property int index

                        Layout.fillWidth: true
                        implicitHeight: Math.round(30 * Theme.fontScale)
                        color: index % 2 === 0 ? Theme.bgSurface : Theme.bgDark

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: Theme.spacingSm
                            anchors.rightMargin: Theme.spacingSm
                            spacing: Theme.spacingSm

                            Text {
                                Layout.preferredWidth: frame.colName
                                verticalAlignment: Text.AlignVCenter
                                text: rowBox.modelData.duration !== ""
                                      ? rowBox.modelData.name + "（时长 " + rowBox.modelData.duration + "）"
                                      : rowBox.modelData.name
                                color: Theme.textPrimary
                                font.family: Theme.fontFamily
                                font.pixelSize: Math.round(12 * Theme.fontScale)
                                elide: Text.ElideRight
                            }
                            Text {
                                Layout.preferredWidth: frame.colNum
                                horizontalAlignment: Text.AlignRight
                                verticalAlignment: Text.AlignVCenter
                                text: rowBox.modelData.demand.toLocaleString(Qt.locale(), 'f', 0)
                                color: Theme.textPrimary
                                font.family: "Consolas"
                                font.pixelSize: Math.round(12 * Theme.fontScale)
                            }
                            Text {
                                Layout.preferredWidth: frame.colNum
                                horizontalAlignment: Text.AlignRight
                                verticalAlignment: Text.AlignVCenter
                                text: rowBox.modelData.output.toLocaleString(Qt.locale(), 'f', 0)
                                color: Theme.textPrimary
                                font.family: "Consolas"
                                font.pixelSize: Math.round(12 * Theme.fontScale)
                            }
                            FSpinBox {
                                Layout.preferredWidth: frame.colPar
                                from: 1
                                to: 1000
                                value: rowBox.modelData.parallels
                                onValueModified: if (frame.cp)
                                    frame.cp.setParallels(rowBox.index, value)
                            }
                            Text {
                                Layout.preferredWidth: frame.colNum
                                horizontalAlignment: Text.AlignRight
                                verticalAlignment: Text.AlignVCenter
                                text: rowBox.modelData.runs.toLocaleString(Qt.locale(), 'f', 0)
                                color: Theme.textSecondary
                                font.family: "Consolas"
                                font.pixelSize: Math.round(12 * Theme.fontScale)
                            }
                            Text {
                                Layout.fillWidth: true
                                verticalAlignment: Text.AlignVCenter
                                text: rowBox.modelData.check
                                color: rowBox.modelData.checkToken !== ""
                                       ? (rowBox.modelData.checkToken === "ACCENT_RED"
                                          ? Theme.accentRed : Theme.accentGreen)
                                       : Theme.textPrimary
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

    // 有子项不达标时禁用「保存」（与 Widgets 版同一规则）
    acceptEnabled: frame.cp ? frame.cp.canAccept : true
}
