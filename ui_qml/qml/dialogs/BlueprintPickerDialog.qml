import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 绑定库存蓝图（阶段 4）。
 *
 * 一条产线独占一张库存蓝图：勾选 parallels 张可用蓝图。
 * 被其他活跃计划占用的行禁勾选；自己已绑定的默认勾选。
 *
 * **勾选阶段不落库，点「完成」才写**（2026-09-27 改）。原实现每次勾选都写库 + 让桥
 * 重建整个行模型，而这里的 `model` 是普通 var 列表 → `ListView` 整体重建、滚动位置
 * **回顶**：用户滑到中段勾第一格，列表直接跳回最顶端，多选根本没法用。现在：
 *   1. 行数据是**常量**（`bridge.rows`），勾选不碰它 → 滚动位置不再被重置；
 *   2. 勾选态由桥单独持有，`checkRevision` 心跳 + `bridge.isChecked(index)` 回读 ——
 *      超需回滚、右键批量勾选都能同步回每个复选框；
 *   3. 写库在 `accept()`（「完成」），「取消」/点 X 不写任何东西。
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

    /* 文本列宽度：下标与 `bridge.headers` 一一对应
     * （类型 / ME / TE / 可用流程 / 机库 / 状态），`-1` = 该列吸收剩余宽度。
     * **表头与行共用这一份**，改一处两边同时对齐 —— 原先两边都写死 `colAvail`(90px)，
     * 2 个字的「类型」也占 90px、而「机库/状态」挤在右侧，看着就是错位 + 不紧凑。
     * 余量只给**最后一列**（状态）：放中间任何一列都会在表格中段留一条空档。 */
    readonly property var colWidths: [
        Math.round(52 * Theme.fontScale),
        Math.round(44 * Theme.fontScale),
        Math.round(44 * Theme.fontScale),
        Math.round(86 * Theme.fontScale),
        Math.round(96 * Theme.fontScale),
        -1
    ]
    //: 各列对齐：数值列居中/靠右、文本列靠左（表头与行同口径）
    readonly property var colAlign: [
        Text.AlignLeft,
        Text.AlignHCenter,
        Text.AlignHCenter,
        Text.AlignRight,
        Text.AlignLeft,
        Text.AlignLeft
    ]

    function colWidth(index) {
        return index >= 0 && index < frame.colWidths.length ? frame.colWidths[index] : -1;
    }

    function colAlignOf(index) {
        return index >= 0 && index < frame.colAlign.length ? frame.colAlign[index] : Text.AlignLeft;
    }

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
        for (let i = 0; i < frame.selRows.length; ++i) {
            if (frame.bp.isChecked(frame.selRows[i]))
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

                    Layout.preferredWidth: frame.colWidth(index)
                    Layout.fillWidth: frame.colWidth(index) < 0
                    horizontalAlignment: frame.colAlignOf(index)
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
                            rowMenu.popupSoon();
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

                        /* 勾选态由桥持有（超需回滚、右键批量都要能同步回来），QML 只负责画：
                         * 初值取模型里的 `checked`（= 打开时的绑定集，行数据是常量，这条绑定
                         * 不会被重建冲掉）；用户点一下 → 交给桥 → 再把桥的回读值写回自己
                         * （`checked` 一旦被赋值就与初值绑定脱钩，这是 QML 的正常语义）。
                         * `Connections` 那条心跳负责**别的行**改动引起的同步。 */
                        FCheckBox {
                            id: checkBox
                            anchors.centerIn: parent
                            enabled: rowItem.modelData.checkable
                            checked: rowItem.modelData.checked
                            onToggled: {
                                if (!frame.bp)
                                    return
                                frame.bp.toggle(rowItem.modelData.index, checked)
                                checkBox.checked = frame.bp.isChecked(rowItem.modelData.index)
                            }

                            Connections {
                                target: frame.bp
                                function onCheckRevisionChanged() {
                                    checkBox.checked = frame.bp ? frame.bp.isChecked(rowItem.modelData.index) : false
                                }
                            }
                        }
                    }

                    Repeater {
                        model: rowItem.modelData.cells

                        Text {
                            required property var modelData
                            required property int index

                            Layout.preferredWidth: frame.colWidth(index)
                            Layout.fillWidth: frame.colWidth(index) < 0
                            horizontalAlignment: frame.colAlignOf(index)
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
