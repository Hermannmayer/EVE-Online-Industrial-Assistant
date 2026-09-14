import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 「标签: 值」明细对话框（阶段 4）。
 *
 * 研究分析这类只读明细用它：值可以多行（材料清单 / 解码器选项都是多行文本），
 * 所以整体可滚动。字段与强调规则都由桥给出。
 */

Item {
    id: page

    readonly property var form: typeof bridge !== "undefined" ? bridge : null

    Rectangle {
        anchors.fill: parent
        color: Theme.bgDark
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.spacingSm
        spacing: Theme.spacingSm

        Flickable {
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentHeight: fieldColumn.implicitHeight
            clip: true
            boundsBehavior: Flickable.StopAtBounds

            ScrollBar.vertical: ScrollBar {
                policy: ScrollBar.AsNeeded
            }

            ColumnLayout {
                id: fieldColumn
                width: parent.width
                spacing: Theme.spacingXs

                Repeater {
                    model: page.form ? page.form.fields : []

                    RowLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: Theme.spacingSm

                        Text {
                            Layout.preferredWidth: Math.round(120 * Theme.fontScale)
                            Layout.alignment: Qt.AlignTop
                            horizontalAlignment: Text.AlignRight
                            text: modelData.label
                            color: Theme.textSecondary
                            font.family: Theme.fontFamily
                            font.pixelSize: Math.round(12 * Theme.fontScale)
                            wrapMode: Text.WordWrap
                        }

                        Text {
                            Layout.fillWidth: true
                            text: modelData.value
                            color: modelData.strong === true ? Theme.primary : Theme.textPrimary
                            font.family: Theme.fontFamily
                            font.pixelSize: Math.round(12 * Theme.fontScale)
                            font.bold: modelData.strong === true
                            wrapMode: Text.WordWrap
                        }
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true

            Item {
                Layout.fillWidth: true
            }
            FButton {
                text: qsTr("关闭")
                onClicked: if (page.form)
                    page.form.reject()
            }
        }
    }
}
