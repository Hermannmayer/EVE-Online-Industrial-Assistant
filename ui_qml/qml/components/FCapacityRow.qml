import QtQuick

/* 产线占用单行：角色名 + 各线型标签 + 容量方块 + 右侧状态徽章。
 *
 * 逐项对齐 `production_launcher.CapacitySlotBar` 的 paintEvent（阶段 2c 删除）：
 *   - 方块区按各类产线容量**比例**分配宽度，各行纵向对齐；
 *   - 超出该角色容量（max）的格子不绘制（格子数即该角色产能）；
 *   - 已占用 = 渐变块 + 描边；空闲可达 = 实心浅块（BG_HOVER，比底色亮、不描边）；
 *   - 状态徽章 = 中性底 + 左侧 3px 语义色条 + **文字**承担语义（不靠颜色单独区分）。
 *
 * 几何全部按控件实际宽度反算，字号/窗口宽度变化时不截断。
 */
Item {
    id: root

    // 由 bridge 注入
    property string charName: ""
    property int nameWidth: 76
    // [{ label, color, active, max, cap }]
    property var lines: []
    property string statusText: ""
    property color statusColor: Theme.textPrimary
    property int slotTotal: 1

    readonly property int gapXs: Theme.spacingXs
    readonly property int gapSm: Theme.spacingSm
    readonly property int gapMd: Theme.spacingMd
    readonly property int fntBody: Math.round(14 * Theme.fontScale)
    readonly property real blockH: Math.max(14, fntBody + 1)
    readonly property real badgeH: 22
    readonly property real blockGap: 3

    implicitHeight: Math.max(32, Math.round(blockH) + 14)

    // ── 几何反算（与 paintEvent 同口径） ──────────────────────

    TextMetrics {
        id: labelMetrics
        font.family: Theme.fontFamily
        font.pixelSize: root.fntBody
    }

    /* 线型标签列宽。
     *
     * **必须是普通属性 + 主动测量，不能写成绑定**：绑定体里给 `labelMetrics.text`
     * 赋值会改动 `labelMetrics.width`，而它又是这个绑定读取的值，Qt 判定为绑定循环
     * （与 `FComboBox.maxItemWidth` 同一类问题，实测告警 `Binding loop detected`）。
     */
    property real labelW: 0

    function measureLabelW() {
        let widest = 0
        for (let i = 0; i < root.lines.length; ++i) {
            labelMetrics.text = root.lines[i].label
            widest = Math.max(widest, labelMetrics.width)
        }
        labelW = widest + root.gapXs
    }

    onLinesChanged: measureLabelW()
    Component.onCompleted: measureLabelW()

    TextMetrics {
        id: badgeMetrics
        font.family: Theme.fontFamily
        font.pixelSize: root.fntBody
        text: root.statusText
    }

    readonly property real badgeW: badgeMetrics.width + 2 * root.gapMd + 5
    readonly property real blocksX: root.gapSm + root.nameWidth + root.gapMd
    // 可用宽度必须扣掉全部标签与组间留白，否则格子会画到右侧徽章底下
    readonly property real availW: width - blocksX - badgeW - 2 * root.gapSm
                                   - root.lines.length * (labelW + root.gapSm)
    readonly property real stride: (availW > 0 && slotTotal > 0) ? availW / slotTotal : 0
    readonly property real blockW: Math.max(4, stride - blockGap)
    readonly property real effStride: blockW + blockGap

    // 第 i 个线型组的方块起点 x
    function groupX(index) {
        return blocksX + index * (labelW + gapSm) + index * (root.lines[index].cap * effStride)
    }

    // ── 状态徽章 ─────────────────────────────────────────────

    Item {
        id: badge
        anchors.right: parent.right
        anchors.rightMargin: root.gapSm
        anchors.verticalCenter: parent.verticalCenter
        width: root.badgeW
        height: root.badgeH

        Rectangle {
            anchors.fill: parent
            radius: 4
            color: Theme.bgSurfaceLight
        }

        Rectangle {
            x: 3
            y: 5
            width: 3
            height: badge.height - 10
            color: root.statusColor
        }

        Text {
            anchors.fill: parent
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            text: root.statusText
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: root.fntBody
        }
    }

    // ── 角色名 ───────────────────────────────────────────────

    Text {
        x: root.gapSm
        width: root.nameWidth
        height: parent.height
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
        text: root.charName
        color: Theme.textPrimary
        font.family: Theme.fontFamily
        font.pixelSize: root.fntBody
        font.bold: true
    }

    // ── 各线型：标签 + 容量方块 ──────────────────────────────

    Repeater {
        model: root.lines

        Item {
            id: lineItem
            required property int index
            required property var modelData

            x: root.groupX(index)
            y: 0
            width: root.labelW + modelData.cap * root.effStride
            height: root.height

            Text {
                x: 0
                width: root.labelW
                height: parent.height
                verticalAlignment: Text.AlignVCenter
                text: lineItem.modelData.label
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: root.fntBody
            }

            Repeater {
                model: lineItem.modelData.cap

                Item {
                    id: block
                    required property int index

                    readonly property bool reachable: block.index < lineItem.modelData.max
                    readonly property bool used: block.index < lineItem.modelData.active
                    readonly property real blockY: (lineItem.height - root.blockH) / 2

                    x: root.labelW + block.index * root.effStride
                    y: block.blockY
                    width: root.blockW
                    height: root.blockH
                    visible: block.reachable

                    // 空闲但可达：明显的浅格（BG_HOVER 比底色亮），不加描边
                    Rectangle {
                        anchors.fill: parent
                        visible: !block.used
                        radius: Math.min(3, root.blockW / 2)
                        color: Theme.bgHover
                    }

                    // 已占用：渐变填充 + 描边
                    Rectangle {
                        anchors.fill: parent
                        visible: block.used
                        radius: Math.min(3, root.blockW / 2)
                        border.width: 1
                        border.color: Qt.darker(lineItem.modelData.color, 1.35)
                        gradient: Gradient {
                            GradientStop {
                                position: 0.0
                                color: Qt.lighter(lineItem.modelData.color, 1.35)
                            }
                            GradientStop {
                                position: 1.0
                                color: Qt.darker(lineItem.modelData.color, 1.1)
                            }
                        }
                    }
                }
            }
        }
    }
}
