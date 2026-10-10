import QtQuick
import QtQuick.Controls

/* 生产计划甘特图 —— 按 BOM 依赖串行排期。
 *
 * 排期算法**不在 QML 里**：`services/plan_gantt.build_rows()` 算好每根柱形条的
 * start / duration / endText，这里只负责画。原实现是 QWidget + QPainter 自绘
 * （阶段 2b 随 Widgets 目录一并删除）。
 *
 * 尺寸口径与原实现逐项对齐：
 *   LABEL_WIDTH=200 / ROW_HEIGHT=32 / HEADER_HEIGHT=40
 *   时间轴按 maxHours 均分；末端完成时刻的宽度要**先从可用宽度里扣掉**，
 *   否则最长的柱形条会顶到右边界、标签被挤出可视区（原注释里的踩坑记录）。
 */
Item {
    id: root

    // 由 bridge 注入：每项 { name, start, duration, endText }
    property var rows: []
    property int maxHours: 48
    //: 横轴起点的绝对时刻（UTC 毫秒，由 bridge 注入）—— 刻度按它换算成「几月几号」，
    //: 与柱形条用的是同一个「现在」，否则刻度会整体偏掉。
    property double axisStartMs: 0
    //: 每**天**一个刻度（改造前是每 12 小时，用户要求改成日期刻度）
    readonly property int tickStep: 24

    readonly property int labelWidth: 200
    readonly property int rowHeight: 32
    readonly property int headerHeight: 40

    /* 时间粒度：每小时占多少像素。由图表下方的「时间粒度」滑块驱动 ——
     * 拉大看细节（超出宽度就横向滚动），拉小看全局。默认 12 与改造前的隐式下限一致。 */
    property real pxPerHourBase: 12
    //: 轴至少铺满一整天，否则刻度只剩一两根，看不出时间感
    readonly property real hourSpan: Math.max(maxHours, 24)

    TextMetrics {
        id: endLabelMetrics
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(10 * Theme.fontScale)
        text: "99-99 99:99"
    }

    readonly property real endLabelWidth: endLabelMetrics.width + 8
    readonly property real contentW: Math.max(width, labelWidth + hourSpan * pxPerHourBase + 10 + endLabelWidth)
    readonly property real axisWidth: contentW - labelWidth - 10 - endLabelWidth
    // 刻度线与柱形条共用这一个比例，改分母时不要只改一处
    readonly property real pxPerHour: maxHours > 0 ? axisWidth / maxHours : 0

    // 甘特条配色（按行号取，循环）
    readonly property var barColors: [
        Theme.primary, Theme.accentGreen, Theme.accentOrange,
        Theme.accentCyan, Theme.accentRed, Theme.accentPurple
    ]

    Flickable {
        id: flick
        anchors.fill: parent
        contentWidth: root.contentW
        contentHeight: root.headerHeight + root.rows.length * root.rowHeight + 10
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar {
            policy: ScrollBar.AsNeeded
        }
        ScrollBar.horizontal: ScrollBar {
            policy: ScrollBar.AsNeeded
        }

        Rectangle {
            anchors.fill: parent
            color: Theme.bgSurface
        }

        Text {
            anchors.centerIn: parent
            visible: root.rows.length === 0
            text: qsTr("暂无数据")
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }

        // ── 时间刻度 ──────────────────────────────────────────
        Repeater {
            model: Math.floor(root.maxHours / root.tickStep) + 1

            Item {
                required property int index
                readonly property real xPos: root.labelWidth + index * root.tickStep * root.pxPerHour
                visible: root.rows.length > 0

                Text {
                    x: parent.xPos - 15
                    y: 5
                    width: 30
                    height: 15
                    horizontalAlignment: Text.AlignHCenter
                    // 日期刻度（改造前是「0h / 12h / 24h」）：轴起点 + n 天
                    text: Qt.formatDateTime(new Date(root.axisStartMs + parent.index * root.tickStep * 3600000), "MM-dd")
                    color: Theme.textSecondary
                    font.family: Theme.fontFamily
                    font.pixelSize: Math.round(10 * Theme.fontScale)
                }

                Rectangle {
                    x: parent.xPos
                    y: root.headerHeight
                    width: 1
                    height: flick.contentHeight - root.headerHeight
                    color: Theme.border
                    opacity: 0.6
                }
            }
        }

        // ── 行 ────────────────────────────────────────────────
        Repeater {
            model: root.rows

            Item {
                id: rowItem
                required property int index
                required property var modelData

                y: root.headerHeight + index * root.rowHeight
                width: flick.contentWidth
                height: root.rowHeight

                readonly property real startX: root.labelWidth + (modelData.start || 0) * root.pxPerHour
                readonly property real barW: Math.max((modelData.duration || 0) * root.pxPerHour, 4)

                Rectangle {
                    x: 0
                    y: 0
                    width: flick.contentWidth
                    height: 1
                    color: Theme.border
                }

                Text {
                    x: 5
                    width: root.labelWidth - 10
                    height: root.rowHeight
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                    text: rowItem.modelData.name
                    color: Theme.textPrimary
                    font.family: Theme.fontFamily
                    font.pixelSize: Math.round(12 * Theme.fontScale)
                }

                Rectangle {
                    x: rowItem.startX
                    y: 3
                    width: rowItem.barW
                    height: root.rowHeight - 6
                    color: root.barColors[rowItem.index % root.barColors.length]

                    Text {
                        anchors.fill: parent
                        visible: parent.width > 40
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        text: Math.round(rowItem.modelData.duration) + "h"
                        color: Theme.textOnPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: Math.round(11 * Theme.fontScale)
                    }
                }

                // 末端预计完成时刻（条外右侧）
                Text {
                    x: rowItem.startX + rowItem.barW + 4
                    y: 3
                    width: root.endLabelWidth
                    height: root.rowHeight - 6
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                    text: rowItem.modelData.endText || ""
                    color: Theme.textPrimary
                    font.family: Theme.fontFamily
                    font.pixelSize: Math.round(10 * Theme.fontScale)
                }
            }
        }
    }
}
