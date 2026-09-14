import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 子项大规模产线并行（阶段 4）。
 *
 * 两种模式反推每个子项的并行数：按「可用产线数」分配 / 按「目标工期」反推。
 * 与「子项并行配置」不同，这里**不逐行编辑**：改模式或参数 → 点「计算预览」
 * → 看整表结果 → 确认应用。所以确定按钮只在算过预览后可用。
 */

FDialogFrame {
    id: frame

    readonly property var mp: typeof bridge !== "undefined" ? bridge : null

    dlg: frame.mp
    acceptText: qsTr("确认应用")
    // 没算过预览就没得应用（桥里 apply 也再兜一道）
    acceptEnabled: frame.mp ? frame.mp.hasPreview : false

    readonly property int colName: Math.round(200 * Theme.fontScale)
    readonly property int colNum: Math.round(110 * Theme.fontScale)

    // ── 模式 / 参数 / 计算 ──
    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spacingSm

        Text {
            text: qsTr("模式:")
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }

        FComboBox {
            id: modeBox
            Layout.preferredWidth: Math.round(160 * Theme.fontScale)
            model: frame.mp ? frame.mp.modes : []
            currentIndex: frame.mp ? frame.mp.modeIndex : 0
            onActivated: {
                if (!frame.mp)
                    return;
                frame.mp.setModeIndex(currentIndex);
                // 换模式后参数回到 10（与 Widgets 版一致）——桥里的 value 不是绑定，
                // 因为用户编辑过之后绑定就断了，这里显式同步一次最稳。
                paramSpin.value = frame.mp.paramValue;
            }
        }

        Text {
            text: qsTr("参数:")
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }

        FSpinBox {
            id: paramSpin
            Layout.preferredWidth: Math.round(130 * Theme.fontScale)
            from: 1
            to: frame.mp ? frame.mp.paramMax : 1000
            Component.onCompleted: value = frame.mp ? frame.mp.paramValue : 10
            onValueModified: if (frame.mp)
                frame.mp.setParamValue(value)
        }

        Text {
            Layout.preferredWidth: Math.round(60 * Theme.fontScale)
            text: frame.mp ? frame.mp.paramSuffix : ""
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }

        FButton {
            text: qsTr("计算预览")
            onClicked: if (frame.mp)
                frame.mp.computePreview()
        }

        Item {
            Layout.fillWidth: true
        }
    }

    // 不达标提示（Widgets 版是算完弹 QMessageBox，这里常驻一行，改参数时也能看见）
    Text {
        Layout.fillWidth: true
        visible: frame.mp ? frame.mp.anyShort : false
        text: qsTr("部分子项调整后仍不满足母项需求，请在确认前核实。")
        color: Theme.accentYellow
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

            Repeater {
                model: frame.mp ? frame.mp.headers : []

                Text {
                    required property var modelData
                    required property int index

                    Layout.preferredWidth: index === 0
                                          ? frame.colName
                                          : (index === frame.mp.headers.length - 1 ? -1 : frame.colNum)
                    Layout.fillWidth: index === frame.mp.headers.length - 1
                    horizontalAlignment: index === 0 || index === frame.mp.headers.length - 1
                                         ? Text.AlignLeft : Text.AlignRight
                    verticalAlignment: Text.AlignVCenter
                    text: modelData
                    color: Theme.textPrimary
                    font.family: Theme.fontFamily
                    font.pixelSize: Math.round(12 * Theme.fontScale)
                    elide: Text.ElideRight
                }
            }
        }
    }

    // ── 预览行 ──
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
            model: frame.mp ? frame.mp.rows : []
            boundsBehavior: Flickable.StopAtBounds

            ScrollBar.vertical: ScrollBar {
                policy: ScrollBar.AsNeeded
            }

            delegate: Item {
                id: rowItem
                required property var modelData
                required property int index

                width: rowList.width
                implicitHeight: Math.round(24 * Theme.fontScale)

                Rectangle {
                    anchors.fill: parent
                    color: rowItem.index % 2 === 0 ? Theme.bgSurface : Theme.bgDark
                }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: Theme.spacingSm
                    anchors.rightMargin: Theme.spacingSm
                    spacing: Theme.spacingSm

                    Repeater {
                        model: rowItem.modelData.cells

                        Text {
                            required property var modelData
                            required property int index

                            Layout.preferredWidth: index === 0
                                                  ? frame.colName
                                                  : (index === rowItem.modelData.cells.length - 1 ? -1 : frame.colNum)
                            Layout.fillWidth: index === rowItem.modelData.cells.length - 1
                            horizontalAlignment: index === 0 || index === rowItem.modelData.cells.length - 1
                                                 ? Text.AlignLeft : Text.AlignRight
                            verticalAlignment: Text.AlignVCenter
                            text: modelData.text
                            color: modelData.color !== "" ? modelData.color : Theme.textPrimary
                            font.family: index === 0 || index === rowItem.modelData.cells.length - 1
                                         ? Theme.fontFamily : "Consolas"
                            font.pixelSize: Math.round(12 * Theme.fontScale)
                            elide: Text.ElideRight
                        }
                    }
                }
            }
        }

        // 空态：还没点「计算预览」
        Text {
            anchors.centerIn: parent
            visible: frame.mp ? !frame.mp.hasPreview : true
            text: qsTr("选好模式与参数后点「计算预览」")
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }
    }
}
