import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../components"

/* 空闲态仪表盘 · 产线详情（人物、产线占用情况）+ 底部的快捷启动/下线。
 *
 * 对应界面标注图「产线详情 / 人物、产线占用情况」与「提供快捷的下线和开始产线按钮」。
 *
 * **每种产线类型一行**，不是每人物一行。原因：`FCapacityRow`（产线启动小助手里那块）
 * 要放「角色名 + 三类产线各自的标签与格子 + 状态徽章」，实测在 260px 的左栏里格子会压到
 * 「科研 / 反应」标签、徽章叠在标签上。人物本来就没几个，转置过来每类产线只占一行，
 * 占地小得多，也不会互相挤。
 *
 * 行内是「一个角色一段」的容量条：段内 `max` 个槽位、前 `active` 个点亮，段间留缝，
 * 一眼能看出**是谁在用、用了几个**。宽度不够时（槽位窄到画不出来）**降级**成
 * 一条按占用比例填充的整条 —— 宁可少画分段，也不要画出一坨叠在一起的方块。
 * 逐人物的数字始终在 tooltip 里，降级不会丢信息。
 */
Item {
    id: root

    //: `bridge.dashboard`
    property var dashboard: null

    readonly property var lineRows: dashboard ? dashboard.occupancyByLine : []
    readonly property var quickRows: dashboard ? dashboard.quickRows : []

    readonly property int fntSmall: Math.round(11 * Theme.fontScale)
    readonly property int fntBase: Math.round(12 * Theme.fontScale)
    readonly property int rowH: Math.max(22, Math.round(13 * Theme.fontScale) + 10)
    readonly property int quickH: Math.max(22, fntBase + 10)
    readonly property int headH: Math.max(18, fntSmall + 7)
    readonly property int dotSize: Math.max(7, Math.round(8 * Theme.fontScale))
    readonly property int labelW: Math.round(34 * Theme.fontScale)
    readonly property int countW: Math.round(46 * Theme.fontScale)
    readonly property int segGap: Theme.spacingXs
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

        // ── 每种产线一行 ──────────────────────────────────────
        ListView {
            id: lineList
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            model: root.lineRows
            spacing: 2
            ScrollBar.vertical: ScrollBar {
                policy: ScrollBar.AsNeeded
            }

            delegate: Item {
                id: lineRow
                required property int index
                required property var modelData

                width: lineList.width
                height: root.rowH

                //: 容量条可用宽度 = 整行减去 色点 / 标签 / 计数 / 间距
                readonly property real barW: Math.max(0, width - root.dotSize - root.labelW
                                                     - root.countW - 3 * Theme.spacingXs)

                /* 槽位宽：段内槽位**紧贴**（不留缝，否则 26 个槽位的缝比槽还宽），
                 * 只在角色之间留 `segGap`。 */
                readonly property int segCount: Math.max(1, (lineRow.modelData.chars || []).length)
                /* ⚠️ 用 `Number()` 而**不是** `int()`：QML 的 JS 全局里没有 `int()` 这个函数
                 * （只有 `Number` / `parseInt` / `Math.*`）。写 `int(x)` 会让整条绑定抛
                 * ReferenceError，而 QML 对绑定错误是**静默**的（属性停在默认值 0）——
                 * 表现就是容量条一个槽位都画不出来、只剩一条空轨道，不报任何错。 */
                readonly property int slotCount: Math.max(0, Math.floor(Number(lineRow.modelData.cap) || 0))
                readonly property real slotGaps: (lineRow.segCount - 1) * root.segGap
                readonly property real slotW: lineRow.slotCount > 0
                                              ? (lineRow.barW - lineRow.slotGaps) / lineRow.slotCount
                                              : 0
                //: 画不出清晰的槽位 → 退化成一条按比例填充的整条
                readonly property bool degraded: lineRow.slotW < root.minSlotW
                readonly property real ratio: lineRow.slotCount > 0
                                              ? Math.min(1, lineRow.modelData.active / lineRow.slotCount)
                                              : 0

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

                // ── 容量条 ────────────────────────────────────
                Item {
                    id: barBox
                    anchors.left: lineLabel.right
                    anchors.leftMargin: Theme.spacingXs
                    anchors.verticalCenter: parent.verticalCenter
                    width: lineRow.barW
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

                    // 正常态：逐角色分段的槽位条
                    Row {
                        visible: !lineRow.degraded
                        anchors.left: parent.left
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: root.segGap

                        Repeater {
                            model: lineRow.modelData.chars

                            Row {
                                id: seg
                                required property var modelData
                                spacing: 0

                                Repeater {
                                    model: Math.max(0, Math.floor(Number(seg.modelData.max) || 0))

                                    Rectangle {
                                        required property int index
                                        width: Math.max(1, lineRow.slotW)
                                        height: barBox.height
                                        // 空槽位画成透明：让下面的轨道透出来。
                                        // 用 `bgHover` 实心会把空槽画得**比轨道还亮**，
                                        // 「0/2」那两行看着像用了 1 格（实测）。
                                        color: index < Number(seg.modelData.active || 0)
                                               ? lineRow.modelData.color
                                               : "transparent"
                                    }
                                }
                            }
                        }
                    }
                }

                Text {
                    anchors.right: parent.right
                    width: root.countW
                    height: parent.height
                    verticalAlignment: Text.AlignVCenter
                    horizontalAlignment: Text.AlignRight
                    text: lineRow.modelData.active + "/" + lineRow.modelData.cap
                    color: lineRow.modelData.active > lineRow.modelData.cap
                           ? Theme.accentRed : Theme.textSecondary
                    font.family: Theme.fontFamily
                    font.pixelSize: root.fntSmall
                    elide: Text.ElideRight
                }

                HoverHandler {
                    id: lineHover
                }

                ToolTip.visible: lineHover.hovered
                ToolTip.text: lineRow.modelData.label + "\n" + lineRow.modelData.detailText
            }

            Text {
                anchors.centerIn: parent
                width: parent.width - 2 * Theme.spacingSm
                visible: root.lineRows.length === 0
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
            Layout.preferredHeight: 1
            color: Theme.border
        }

        Text {
            Layout.fillWidth: true
            Layout.preferredHeight: root.headH
            verticalAlignment: Text.AlignVCenter
            text: qsTr("快捷操作（可启动 / 可下线）")
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: root.fntSmall
        }

        ListView {
            id: quickList
            Layout.fillWidth: true
            Layout.preferredHeight: Math.max(root.quickH,
                                             Math.min(3, Math.max(1, root.quickRows.length)) * root.quickH)
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
                    Layout.preferredWidth: Math.round(52 * Theme.fontScale)
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
