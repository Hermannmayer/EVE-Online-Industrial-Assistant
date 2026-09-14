import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 绑定库存蓝图（阶段 4）。
 *
 * 一条产线独占一张库存蓝图：勾选 parallels 张可用蓝图，**勾选即实时落库**
 * （勾选集 = 最终绑定集）。被其他活跃计划占用的行禁勾选；自己已绑定的默认勾选。
 *
 * 右键菜单对**选中行**批量操作（勾选 / 取消勾选 / 仅保留所选）。选中态是纯 UI
 * 状态，留在 QML（`selRows`）——桥只管「哪几张被勾上」这个业务事实。
 */

FDialogFrame {
    id: frame

    readonly property var bp: typeof bridge !== "undefined" ? bridge : null

    dlg: frame.bp
    acceptText: qsTr("完成")

    //: 右键菜单作用的行号（Ctrl+左键多选）
    property var selRows: []
    //: 打开菜单前算一次「所选里是否有已勾选的」——菜单项按它决定是否显示
    property bool menuAnyChecked: false

    readonly property int colCheck: Math.round(36 * Theme.fontScale)
    readonly property int colSmall: Math.round(56 * Theme.fontScale)
    readonly property int colAvail: Math.round(90 * Theme.fontScale)

    function tokenColor(token) {
        switch (token) {
        case "GREEN":
            return Theme.accentGreen;
        case "ACCENT_RED":
            return Theme.accentRed;
        case "ACCENT_ORANGE":
            return Theme.accentOrange;
        case "TEXT_SECONDARY":
            return Theme.textSecondary;
        default:
            return Theme.textPrimary;
        }
    }

    function anySelectedChecked() {
        if (!frame.bp)
            return false;
        const rows = frame.bp.rows;
        for (let i = 0; i < frame.selRows.length; ++i) {
            const row = rows[frame.selRows[i]];
            if (row && row.checked)
                return true;
        }
        return false;
    }

    // 需求说明
    Text {
        Layout.fillWidth: true
        text: frame.bp ? frame.bp.needLabel : ""
        color: Theme.textPrimary
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(12 * Theme.fontScale)
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
                Layout.preferredWidth: frame.colCheck
                horizontalAlignment: Text.AlignHCenter
                text: qsTr("勾选")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(12 * Theme.fontScale)
            }
            Repeater {
                model: frame.bp ? frame.bp.headers : []

                Text {
                    required property var modelData
                    required property int index

                    Layout.preferredWidth: index === frame.bp.headers.length - 1 ? -1 : frame.colAvail
                    Layout.fillWidth: index === frame.bp.headers.length - 1
                    text: modelData
                    color: Theme.textPrimary
                    font.family: Theme.fontFamily
                    font.pixelSize: Math.round(12 * Theme.fontScale)
                    elide: Text.ElideRight
                }
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

        ListView {
            id: rowList
            anchors.fill: parent
            anchors.margins: 1
            clip: true
            model: frame.bp ? frame.bp.rows : []
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

                //: 右键菜单作用的行（Ctrl+左键可多选）
                readonly property bool rowSelected: frame.selRows.indexOf(rowItem.index) >= 0

                Rectangle {
                    anchors.fill: parent
                    color: rowItem.rowSelected
                           ? Theme.bgHover
                           : (rowItem.index % 2 === 0 ? Theme.bgSurface : Theme.bgDark)
                }

                // 点空白处选中该行（Ctrl 多选）；右键直接开批量菜单。
                // 声明在内容之前 = 垫在下面，复选框自己的点击不会被它抢走。
                MouseArea {
                    anchors.fill: parent
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    onClicked: function (mouse) {
                        if (mouse.button === Qt.RightButton) {
                            if (frame.selRows.indexOf(rowItem.index) < 0)
                                frame.selRows = [rowItem.index];
                            frame.menuAnyChecked = frame.anySelectedChecked();
                            rowMenu.popup();
                        } else if (mouse.modifiers & Qt.ControlModifier) {
                            const next = frame.selRows.slice();
                            const at = next.indexOf(rowItem.index);
                            if (at >= 0)
                                next.splice(at, 1);
                            else
                                next.push(rowItem.index);
                            frame.selRows = next;
                        } else {
                            frame.selRows = [rowItem.index];
                        }
                    }
                }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: Theme.spacingSm
                    anchors.rightMargin: Theme.spacingSm
                    spacing: Theme.spacingSm

                    Item {
                        Layout.preferredWidth: frame.colCheck
                        Layout.fillHeight: true

                        FCheckBox {
                            anchors.centerIn: parent
                            enabled: rowItem.modelData.checkable
                            checked: rowItem.modelData.checked
                            onToggled: if (frame.bp)
                                frame.bp.toggle(rowItem.index, checked)
                        }
                    }

                    Repeater {
                        model: rowItem.modelData.cells

                        Text {
                            required property var modelData
                            required property int index

                            Layout.preferredWidth: index === rowItem.modelData.cells.length - 1 ? -1 : frame.colAvail
                            Layout.fillWidth: index === rowItem.modelData.cells.length - 1
                            verticalAlignment: Text.AlignVCenter
                            text: modelData.text
                            color: rowItem.modelData.disabled
                                   ? Theme.textSecondary
                                   : (modelData.color !== "" ? modelData.color : Theme.textPrimary)
                            font.family: Theme.fontFamily
                            font.pixelSize: Math.round(12 * Theme.fontScale)
                            elide: Text.ElideRight
                        }
                    }
                }
            }
        }

        // 空态：没有可选蓝图 / 无法确定蓝图类型
        Text {
            anchors.centerIn: parent
            width: parent.width - 2 * Theme.spacingMd
            horizontalAlignment: Text.AlignHCenter
            visible: !(frame.bp && frame.bp.hasOptions)
            text: frame.bp ? frame.bp.emptyHint : ""
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
            wrapMode: Text.WordWrap
        }
    }

    // ── 状态行 + 查看NPC卖家 ──
    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spacingSm

        Text {
            Layout.fillWidth: true
            text: frame.bp ? frame.bp.statusText : ""
            color: frame.bp ? frame.tokenColor(frame.bp.statusToken) : Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
            font.bold: true
            elide: Text.ElideRight
        }

        FButton {
            text: qsTr("查看NPC卖家")
            visible: frame.bp ? frame.bp.canNpcSeller : false
            onClicked: if (frame.bp)
                frame.bp.npcSeller()
        }
    }

    // 右键批量勾选菜单（对齐 Widgets 版：勾选 / 取消勾选 / 仅保留所选）
    FMenu {
        id: rowMenu

        MenuItem {
            text: qsTr("勾选所选蓝图")
            onTriggered: if (frame.bp)
                frame.bp.checkRows(frame.selRows)
        }
        MenuItem {
            text: qsTr("取消勾选所选蓝图")
            onTriggered: if (frame.bp)
                frame.bp.uncheckRows(frame.selRows)
        }
        MenuSeparator {}
        FMenuItem {
            text: qsTr("仅保留所选（取消其他）")
            visible: frame.menuAnyChecked
            onTriggered: if (frame.bp)
                frame.bp.onlyKeep(frame.selRows)
        }
    }
}
