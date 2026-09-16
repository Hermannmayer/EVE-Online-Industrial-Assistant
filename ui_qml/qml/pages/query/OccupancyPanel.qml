import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../components"

/* 空闲态仪表盘 · 产线详情（人物、产线占用情况）+ 底部的快捷启动/下线。
 *
 * 对应界面标注图「产线详情 / 人物、产线占用情况」与「提供快捷的下线和开始产线按钮」。
 *
 * 占用方块直接复用 `FCapacityRow`（与产线启动小助手同一块视觉），数据形状也逐字相同
 * （`{name, nameWidth, lines:[{label,color,active,max,cap}], statusText, statusColor, slotTotal}`）
 * —— 唯一区别是那边的行来自 `launcher_bridge`，这边来自 `dashboard`。
 */
Item {
    id: root

    //: `bridge.dashboard`
    property var dashboard: null

    readonly property var occRows: dashboard ? dashboard.occupancyRows : []
    readonly property var quickRows: dashboard ? dashboard.quickRows : []

    readonly property int fntSmall: Math.round(11 * Theme.fontScale)
    readonly property int fntBase: Math.round(12 * Theme.fontScale)
    readonly property int quickH: Math.max(22, fntBase + 10)
    readonly property int headH: Math.max(20, fntSmall + 10)

    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.spacingXs

        // ── 占用汇总 ──────────────────────────────────────────
        Text {
            Layout.fillWidth: true
            height: root.headH
            verticalAlignment: Text.AlignVCenter
            text: root.dashboard ? root.dashboard.occupancySummary : ""
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: root.fntSmall
            elide: Text.ElideRight
        }

        // ── 每角色一行占用 ────────────────────────────────────
        ListView {
            id: occList
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            model: root.occRows
            spacing: Theme.spacingXs
            ScrollBar.vertical: ScrollBar {
                policy: ScrollBar.AsNeeded
            }

            delegate: FCapacityRow {
                required property var modelData
                width: occList.width
                charName: modelData.name
                nameWidth: modelData.nameWidth
                lines: modelData.lines
                statusText: modelData.statusText
                statusColor: modelData.statusColor
                slotTotal: modelData.slotTotal
            }

            Text {
                anchors.centerIn: parent
                width: parent.width - 2 * Theme.spacingSm
                visible: root.occRows.length === 0
                text: qsTr("没有可用的产线容量数据")
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: root.fntSmall
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
            }
        }

        // ── 快捷启动 / 下线 ───────────────────────────────────
        Rectangle {
            Layout.fillWidth: true
            height: 1
            color: Theme.border
        }

        Text {
            Layout.fillWidth: true
            height: root.headH
            verticalAlignment: Text.AlignVCenter
            text: qsTr("快捷操作（可启动 / 可下线）")
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: root.fntSmall
        }

        ListView {
            id: quickList
            Layout.fillWidth: true
            Layout.preferredHeight: Math.max(root.quickH, Math.min(3, Math.max(1, root.quickRows.length)) * root.quickH)
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            model: root.quickRows
            ScrollBar.vertical: ScrollBar {
                policy: ScrollBar.AsNeeded
            }

            Text {
                anchors.centerIn: parent
                width: parent.width - 2 * Theme.spacingSm
                visible: root.quickRows.length === 0
                text: qsTr("当前没有可启动或可下线的产线")
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: root.fntSmall
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
            }

            delegate: RowLayout {
                id: quickRow
                required property int index
                required property var modelData
                width: quickList.width
                height: root.quickH
                spacing: Theme.spacingXs

                Text {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 40
                    verticalAlignment: Text.AlignVCenter
                    text: quickRow.modelData.name
                    color: Theme.textPrimary
                    font.family: Theme.fontFamily
                    font.pixelSize: root.fntBase
                    elide: Text.ElideRight

                    HoverHandler {
                        id: nameHover
                    }
                    ToolTip.visible: nameHover.hovered
                    ToolTip.text: quickRow.modelData.name + "\n" + quickRow.modelData.statusText
                }

                Text {
                    Layout.preferredWidth: Math.round(64 * Theme.fontScale)
                    verticalAlignment: Text.AlignVCenter
                    horizontalAlignment: Text.AlignRight
                    text: quickRow.modelData.statusText
                    color: Theme.textSecondary
                    font.family: Theme.fontFamily
                    font.pixelSize: root.fntSmall
                    elide: Text.ElideRight
                }

                FButton {
                    Layout.preferredHeight: Math.round(20 * Theme.fontScale)
                    text: quickRow.modelData.actionText
                    primary: quickRow.modelData.action === "start"
                    /* 确认框在**桥**里弹（`FMessageDialog.question`），不在这边：
                     * 服务函数是无 parent 的、validate 档会在无 QApplication 下直调它们
                     * （见 `docs/dev/flows.md`），所以「确认」得由持有 shell 的桥来做；
                     * 桥已经知道这一行是什么、要做什么，QML 只要交出下标。 */
                    onClicked: if (root.dashboard)
                        root.dashboard.quickAction(quickRow.index)
                }
            }
        }
    }
}
