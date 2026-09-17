import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../components"

/* 空闲态仪表盘 · 产线详情（**每人物一块，块内制造 / 科研 / 反应三行**）。
 *
 * 对应界面标注图「产线详情 / 人物、产线占用情况」。早先的版本是「每种产线类型一行」，
 * 那样在竖排的左栏里下半截全是空白（实测左栏约 260px、只有 3 行数据），
 * 而每个人的占用只能塞进 tooltip。现在**每人一块**：
 *
 *     ┌ 人物A                                生产中 ┐
 *     │ ● 制造 ████████░░░░  6/8   待下线 1   空 2 │
 *     │ ● 科研 ██░░░░░░░░░░  1/5              空 4 │
 *     │ ● 反应 ░░░░░░░░░░░░  0/1              空 1 │
 *     └ ───────────────────────────────────────── ┘
 *
 * - 条子按**统一的槽位宽**画（分母取该线型里最大的那个人），所以不同人物的条**等长可比**；
 *   条子里点亮的格数 = 该人物该线型已占用的产线数（`active`），总格数 = 该人物上限（`max`）。
 * - 行尾两个提示：「待下线 N」（该人物该线型下 `status=='ready'` 的计划数，橙色）与
 *   「空 N」（还能再上几条线，灰字）。两者都为 0 时不占位置。
 * - 人物多的时候整块列表滚动（`ListView` + 按需滚动条）。
 * - 面板太窄、格子画不清时降级为一条按占用比例填充的整条（信息不丢，逐人物数字在 tooltip 里）。
 */
Item {
    id: root

    //: `bridge.dashboard`
    property var dashboard: null

    readonly property var charBlocks: dashboard ? dashboard.occupancyByChar : []

    readonly property int fntSmall: Math.round(11 * Theme.fontScale)
    readonly property int fntBase: Math.round(12 * Theme.fontScale)
    readonly property int headH: Math.max(20, fntBase + 8)
    readonly property int lineH: Math.max(18, fntSmall + 7)
    readonly property int blockGap: Math.max(4, Theme.spacingXs + 2)
    readonly property int dotSize: Math.max(6, Math.round(7 * Theme.fontScale))
    readonly property int labelW: Math.round(30 * Theme.fontScale)
    readonly property int countW: Math.round(42 * Theme.fontScale)
    readonly property int hintW: Math.round(56 * Theme.fontScale)
    //: 槽位窄于此值就降级成整条比例条（画出来也看不清）
    readonly property real minSlotW: 3

    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.spacingXs

        // ── 占用汇总 ──────────────────────────────────────────
        Text {
            Layout.fillWidth: true
            Layout.preferredHeight: root.headH
            verticalAlignment: Text.AlignVCenter
            text: root.dashboard ? root.dashboard.occupancySummary : ""
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: root.fntSmall
            elide: Text.ElideRight
        }

        // ── 每人物一块 ────────────────────────────────────────
        ListView {
            id: charList
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            model: root.charBlocks
            spacing: 0
            ScrollBar.vertical: ScrollBar {
                policy: ScrollBar.AsNeeded
            }

            delegate: Item {
                id: charBlock
                required property int index
                required property var modelData

                /* ⚠️ 必须**防着 modelData 还是 null 的那一刻**：第一次求值时 `modelData`
                 * 可能尚未注入，裸写 `modelData.lines.length` 会抛 TypeError ——
                 * 而 QML 对绑定错误是**静默**的，`height` 会停在 0，
                 * 表现就是「每个人物一块」一个都画不出来（空面板，无任何报错）。
                 * 实测：真窗口下 delegate height = 0、contentHeight = 0，汇总却说「2 人物」。 */
                readonly property var lines: (charBlock.modelData && charBlock.modelData.lines)
                                             ? charBlock.modelData.lines : []
                /* 块高 = 头行 + 每线一行 + 块间距 + 一条分隔线 */
                width: charList.width
                height: root.headH + charBlock.lines.length * root.lineH + root.blockGap + 1

                // ── 头行：人物名 + 状态徽章 ────────────────────
                Text {
                    id: nameText
                    anchors.left: parent.left
                    anchors.top: parent.top
                    height: root.headH
                    width: Math.max(40, parent.width - badge.width - 2 * Theme.spacingXs)
                    verticalAlignment: Text.AlignVCenter
                    text: charBlock.modelData.name
                    color: Theme.textPrimary
                    font.family: Theme.fontFamily
                    font.pixelSize: root.fntBase
                    font.bold: true
                    elide: Text.ElideRight
                }

                Item {
                    id: badge
                    anchors.right: parent.right
                    anchors.top: parent.top
                    height: root.headH
                    width: badgeText.width + 2 * Theme.spacingSm + 5

                    Rectangle {
                        anchors.fill: parent
                        radius: Theme.radiusSmall
                        color: Theme.bgSurfaceLight
                    }

                    Rectangle {
                        x: 2
                        y: 4
                        width: 3
                        height: badge.height - 8
                        color: charBlock.modelData.statusColor
                    }

                    Text {
                        id: badgeText
                        anchors.centerIn: parent
                        text: charBlock.modelData.statusText
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: root.fntSmall
                    }
                }

                // ── 三行：制造 / 科研 / 反应 ───────────────────
                Repeater {
                    model: charBlock.lines

                    Item {
                        id: lineRow
                        required property int index
                        required property var modelData

                        x: 0
                        y: root.headH + index * root.lineH
                        width: charBlock.width
                        height: root.lineH

                        //: 提示区宽度：只有真的要显示提示时才占位，否则把宽度让给条子
                        readonly property bool hasReady: !!lineRow.modelData.readyText
                        readonly property int hintWUsed: lineRow.hasReady ? root.hintW : 0

                        //: 容量条可用宽度 = 整行减去 色点 / 标签 / 计数 / 提示 / 间距
                        readonly property real barW: Math.max(0, width - root.dotSize - root.labelW
                                                             - root.countW - lineRow.hintWUsed
                                                             - 4 * Theme.spacingXs)
                        readonly property int slots: Math.max(0, Math.floor(Number(lineRow.modelData.max) || 0))
                        readonly property int span: Math.max(slots, Math.floor(Number(lineRow.modelData.cap) || 0))
                        //: 槽位宽按**统一分母**（该线型最大上限）算 → 各人的条等长可比
                        readonly property real slotW: lineRow.span > 0 ? lineRow.barW / lineRow.span : 0
                        readonly property bool degraded: lineRow.slotW < root.minSlotW
                        readonly property real ratio: lineRow.slots > 0
                                                      ? Math.min(1, Number(lineRow.modelData.active) / lineRow.slots)
                                                      : 0
                        readonly property real barWidthUsed: lineRow.degraded
                                                              ? lineRow.barW
                                                              : lineRow.span * lineRow.slotW

                        Rectangle {
                            anchors.left: parent.left
                            anchors.verticalCenter: parent.verticalCenter
                            width: root.dotSize
                            height: width
                            radius: width / 2
                            color: lineRow.modelData.color
                        }

                        Text {
                            id: lineLabel
                            anchors.left: parent.left
                            anchors.leftMargin: root.dotSize + Theme.spacingXs
                            width: root.labelW
                            height: parent.height
                            verticalAlignment: Text.AlignVCenter
                            text: lineRow.modelData.label
                            color: Theme.textPrimary
                            font.family: Theme.fontFamily
                            font.pixelSize: root.fntSmall
                            elide: Text.ElideRight
                        }

                        // ── 容量条 ────────────────────────────────
                        Item {
                            id: barBox
                            anchors.left: lineLabel.right
                            anchors.leftMargin: Theme.spacingXs
                            anchors.verticalCenter: parent.verticalCenter
                            width: lineRow.barWidthUsed
                            height: Math.max(4, Math.round(parent.height * 0.5))

                            // 轨道（也让「一个都没用」时这条行有个形状，不至于看起来缺数据）
                            Rectangle {
                                anchors.fill: parent
                                radius: Theme.radiusSmall
                                color: Theme.bgHover
                                opacity: 0.55
                            }

                            // 降级态：一条按比例填充的整条
                            Rectangle {
                                visible: lineRow.degraded
                                anchors.left: parent.left
                                anchors.verticalCenter: parent.verticalCenter
                                width: Math.round(parent.width * lineRow.ratio)
                                height: parent.height
                                radius: Theme.radiusSmall
                                color: lineRow.modelData.color
                            }

                            // 正常态：槽位（点亮 = 已占用）
                            Row {
                                visible: !lineRow.degraded
                                anchors.left: parent.left
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 0

                                Repeater {
                                    model: lineRow.degraded ? 0 : lineRow.slots

                                    Rectangle {
                                        required property int index
                                        width: Math.max(1, lineRow.slotW)
                                        height: barBox.height
                                        // 空槽位画成透明：让下面的轨道透出来。
                                        // 用 `bgHover` 实心会把空槽画得**比轨道还亮**，
                                        // 「0/2」那两行看着像用了 1 格（实测）。
                                        color: index < Number(lineRow.modelData.active || 0)
                                               ? lineRow.modelData.color
                                               : "transparent"
                                    }
                                }
                            }
                        }

                        Text {
                            anchors.left: barBox.right
                            anchors.leftMargin: Theme.spacingXs
                            width: root.countW
                            height: parent.height
                            verticalAlignment: Text.AlignVCenter
                            horizontalAlignment: Text.AlignRight
                            text: lineRow.modelData.active + "/" + lineRow.modelData.max
                            color: Number(lineRow.modelData.active) > Number(lineRow.modelData.max)
                                   ? Theme.accentRed : Theme.textSecondary
                            font.family: Theme.fontFamily
                            font.pixelSize: root.fntSmall
                            elide: Text.ElideRight
                        }

                        //: 「待下线 N」—— 该人物该线型下可下线的计划数（用户明确要的提示）
                        Text {
                            anchors.right: parent.right
                            width: root.hintW
                            height: parent.height
                            visible: lineRow.hasReady
                            verticalAlignment: Text.AlignVCenter
                            horizontalAlignment: Text.AlignRight
                            text: lineRow.modelData.readyText
                            color: Theme.accentOrange
                            font.family: Theme.fontFamily
                            font.pixelSize: root.fntSmall
                            elide: Text.ElideRight
                        }

                        HoverHandler {
                            id: lineHover
                        }

                        ToolTip.visible: lineHover.hovered
                        ToolTip.text: lineRow.modelData.detailText
                    }
                }

                // ── 块分隔线 ──────────────────────────────────
                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    height: 1
                    color: Theme.border
                    opacity: 0.6
                }
            }

            Text {
                anchors.centerIn: parent
                width: parent.width - 2 * Theme.spacingSm
                visible: root.charBlocks.length === 0
                text: qsTr("没有可用的产线容量数据")
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: root.fntSmall
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
            }
        }
    }
}
