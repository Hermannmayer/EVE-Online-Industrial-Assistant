import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 移库对话框（阶段 4b）。
 *
 * 形状是「勾选框 + 图标 + 名称 + 几个数字列 + 每行一个数量微调框」的**异质表**，
 * 不是只读汇总表，所以这里自己摆行，不用 `FSummaryTable`。结构照
 * `BlueprintPickerDialog.qml`（同为「勾选框 + 每行可交互」的表）：
 *   - 行点击命中用声明在**内容之前**的普通 `MouseArea`（垫在下面），勾选框与微调框
 *     的点击才不会被它抢走。**不能用 `FTableClickArea`**：它要求锚在整张表上、按内容
 *     坐标算行号，塞进 delegate 里每行都只会算成第 0 行。
 *   - 「选中哪些行」是纯 UI 状态（`selRows`），桥只管勾选与数量。
 *
 * clamp（剪贴板数量超出源库现有）在桥里算好：`capped` 行的名称带「（源库不足）」后缀，
 * 微调框上限就是源库现有量。
 */

FDialogFrame {
    id: frame

    readonly property var bp: typeof bridge !== "undefined" ? bridge : null

    dlg: frame.bp
    acceptText: qsTr("确定移库")
    acceptEnabled: frame.bp ? frame.bp.canAccept : true

    //: 右键菜单作用的行号（Ctrl+左键多选）
    property var selRows: []

    readonly property int colCheck: Math.round(36 * Theme.fontScale)
    readonly property int colIcon: Math.round(32 * Theme.fontScale)
    readonly property int colNum: Math.round(90 * Theme.fontScale)

    //: 列宽；-1 = 名称列吃满剩余空间
    function colW(i) {
        if (i === 0)
            return frame.colCheck;
        if (i === 1)
            return frame.colIcon;
        if (i === 2)
            return -1;
        return frame.colNum;
    }

    function rowIsUnmatched(i) {
        if (!frame.bp)
            return false;
        const rows = frame.bp.rows;
        return i >= 0 && i < rows.length && !rows[i].matched;
    }

    // ── 来源机库选择 ──
    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spacingSm

        Text {
            text: qsTr("来源机库:")
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }

        FComboBox {
            objectName: "sourceBox"
            Layout.preferredWidth: Math.round(240 * Theme.fontScale)
            textRole: "label"
            model: frame.bp ? frame.bp.sources : []
            currentIndex: frame.bp ? frame.bp.sourceIndex : 0
            onActivated: if (frame.bp)
                frame.bp.setSourceIndex(currentIndex)
        }

        Item {
            Layout.fillWidth: true
        }
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
                model: frame.bp ? frame.bp.headers : []

                Text {
                    required property var modelData
                    required property int index

                    Layout.preferredWidth: frame.colW(index) > 0 ? frame.colW(index) : -1
                    Layout.fillWidth: frame.colW(index) < 0
                    horizontalAlignment: index === 2 ? Text.AlignLeft : Text.AlignHCenter
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

    // ── 行区 ──
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
                implicitHeight: Math.round(32 * Theme.fontScale)

                readonly property bool rowSelected: frame.selRows.indexOf(rowItem.index) >= 0

                Rectangle {
                    anchors.fill: parent
                    color: rowItem.rowSelected ? Theme.bgHover
                           : (rowItem.index % 2 === 0 ? Theme.bgSurface : Theme.bgDark)
                }

                // 点空白处选中该行（Ctrl 多选）；右键开菜单。
                // 声明在内容之前 = 垫在下面，勾选框 / 微调框自己的点击不会被它抢走。
                MouseArea {
                    anchors.fill: parent
                    acceptedButtons: Qt.LeftButton | Qt.RightButton

                    onClicked: function (mouse) {
                        if (mouse.button === Qt.RightButton) {
                            if (frame.selRows.indexOf(rowItem.index) < 0)
                                frame.selRows = [rowItem.index];
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

                    // 勾选（未匹配行没有）
                    Item {
                        Layout.preferredWidth: frame.colCheck
                        Layout.fillHeight: true

                        FCheckBox {
                            anchors.centerIn: parent
                            visible: rowItem.modelData.matched
                            checked: rowItem.modelData.checked
                            onToggled: if (frame.bp)
                                frame.bp.setRowChecked(rowItem.index, checked)
                        }
                    }

                    // 图标
                    Item {
                        Layout.preferredWidth: frame.colIcon
                        Layout.fillHeight: true

                        Image {
                            anchors.centerIn: parent
                            width: Math.round(24 * Theme.fontScale)
                            height: width
                            source: rowItem.modelData.icon
                            sourceSize.width: width
                            sourceSize.height: height
                            smooth: true
                            visible: rowItem.modelData.icon !== ""
                        }
                    }

                    // 名称
                    Text {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        verticalAlignment: Text.AlignVCenter
                        horizontalAlignment: Text.AlignLeft
                        text: rowItem.modelData.nameText
                        color: rowItem.modelData.nameColor !== "" ? rowItem.modelData.nameColor : Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: Math.round(12 * Theme.fontScale)
                        elide: Text.ElideRight
                    }

                    // 剪贴板数量
                    Text {
                        Layout.preferredWidth: frame.colNum
                        Layout.fillHeight: true
                        horizontalAlignment: Text.AlignRight
                        verticalAlignment: Text.AlignVCenter
                        text: rowItem.modelData.clipText
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: Math.round(12 * Theme.fontScale)
                    }

                    // 源库现有
                    Text {
                        Layout.preferredWidth: frame.colNum
                        Layout.fillHeight: true
                        horizontalAlignment: Text.AlignRight
                        verticalAlignment: Text.AlignVCenter
                        text: rowItem.modelData.srcText
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: Math.round(12 * Theme.fontScale)
                    }

                    // 移动数量（已匹配行是微调框，未匹配行给「-」）
                    Item {
                        Layout.preferredWidth: frame.colNum
                        Layout.fillHeight: true

                        FSpinBox {
                            anchors.verticalCenter: parent.verticalCenter
                            width: parent.width
                            visible: rowItem.modelData.matched
                            from: 0
                            to: Math.max(rowItem.modelData.maxQty, 0)
                            value: rowItem.modelData.moveQty
                            onValueModified: if (frame.bp)
                                frame.bp.setRowQty(rowItem.index, value)
                        }

                        Text {
                            anchors.centerIn: parent
                            visible: !rowItem.modelData.matched
                            text: rowItem.modelData.clipText
                            color: Theme.textSecondary
                            font.family: Theme.fontFamily
                            font.pixelSize: Math.round(12 * Theme.fontScale)
                        }
                    }

                    // 单位成本
                    Text {
                        Layout.preferredWidth: frame.colNum
                        Layout.fillHeight: true
                        horizontalAlignment: Text.AlignRight
                        verticalAlignment: Text.AlignVCenter
                        text: rowItem.modelData.costText
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: Math.round(12 * Theme.fontScale)
                    }

                    // 目标现有
                    Text {
                        Layout.preferredWidth: frame.colNum
                        Layout.fillHeight: true
                        horizontalAlignment: Text.AlignRight
                        verticalAlignment: Text.AlignVCenter
                        text: rowItem.modelData.targetText
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: Math.round(12 * Theme.fontScale)
                    }
                }
            }
        }

        // 空态（没有其他机库可移动时，统计行文案就是那句提示）
        Text {
            anchors.centerIn: parent
            width: parent.width - 2 * Theme.spacingMd
            horizontalAlignment: Text.AlignHCenter
            visible: frame.bp ? frame.bp.rows.length === 0 : false
            text: frame.bp ? frame.bp.summaryText : ""
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
            wrapMode: Text.WordWrap
        }
    }

    // ── 统计行 ──
    Text {
        Layout.fillWidth: true
        visible: frame.bp ? frame.bp.rows.length > 0 : false
        text: frame.bp ? frame.bp.summaryText : ""
        color: Theme.textSecondary
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(11 * Theme.fontScale)
        elide: Text.ElideRight
    }

    // 右键菜单：未匹配且只选了一行 → 可搜索匹配；删除永远可用
    FMenu {
        id: rowMenu

        FMenuItem {
            text: qsTr("搜索匹配物品…")
            visible: frame.selRows.length === 1 && frame.rowIsUnmatched(frame.selRows[0])
            onTriggered: if (frame.bp)
                frame.bp.searchMatch(frame.selRows[0])
        }

        MenuItem {
            text: frame.selRows.length > 1 ? qsTr("删除选中行 (%1)").arg(frame.selRows.length) : qsTr("删除该行")
            onTriggered: if (frame.bp)
                frame.bp.deleteRows(frame.selRows)
        }
    }
}
