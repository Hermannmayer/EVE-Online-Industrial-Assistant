import QtQuick
import QtQuick.Layouts

/* 市场监控页 —— 容器（只做分页签，不画业务）。

 * 两块内容（`ui_qml/monitor_page.py` 注入两个桥）：
 *   1. **大盘**（首页，默认选中）→ `MarketPulsePane.qml`（`pulseBridge`）
 *   2. **关注物品**（子视图）→ `WatchlistPage.qml`（`bridge`）
 *
 * 用户口径：「市场监控首页应该就是这个大盘页，然后再去细分其他内容」——
 * 所以大盘是**默认页签**，关注物品是它下面的第二个视图，两者共用一个导航项。
 *
 * 为什么不用 `FTabBar`：它在 `Layout.fillWidth: true` 下把标签**等分撑满整行**
 * （合同页踩过：1920 宽窗口里两个标签被拉到屏幕两端、选中态只有 1px 细线），
 * 这里沿用合同页的紧凑分段控件（左对齐、选中整块填主色反白）。
 *
 * 两个子视图用 `Loader` 按需加载：切到哪个才建哪个（大盘首屏要跑 QThread 重算，
 * 关注页要读关注表 + 历史，两个都常驻会白花启动时间）。
 */
Item {
    id: container

    readonly property var pulse: typeof pulseBridge !== "undefined" ? pulseBridge : null
    readonly property var watch: typeof bridge !== "undefined" ? bridge : null

    readonly property int fntBase: Math.round(12 * Theme.fontScale)
    readonly property int pad: Theme.spacingSm

    //: 当前页签下标：0 = 大盘（首页），1 = 关注物品
    property int tabIndex: 0

    Rectangle {
        anchors.fill: parent
        color: Theme.bgDark
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // ── 分段页签（左对齐紧凑控件）──────────────────────────
        RowLayout {
            objectName: "monitorTabStripRow"
            Layout.fillWidth: true
            Layout.leftMargin: 2 * container.pad
            Layout.topMargin: container.pad
            spacing: container.pad

            Rectangle {
                objectName: "monitorTabStrip"
                implicitWidth: segRow.implicitWidth + 4
                implicitHeight: segRow.implicitHeight + 4
                radius: Theme.radius
                color: Theme.bgSurface
                border.width: 1
                border.color: Theme.border

                Row {
                    id: segRow
                    anchors.centerIn: parent
                    spacing: 2

                    Repeater {
                        model: [qsTr("大盘"), qsTr("关注物品")]

                        Rectangle {
                            id: seg
                            required property int index
                            required property string modelData

                            readonly property bool active: container.tabIndex === seg.index

                            implicitWidth: segLabel.implicitWidth + 2 * Math.round(16 * Theme.fontScale)
                            // 段高/选中加粗与合同页的 `SegTab` 对齐（同一套「页面级分段页签」，
                            // 两处不一致就是设计语言漂移）。段间距这里保留 2px 而不是 0：
                            // 合同页 3 段带条数徽标、靠 1px 分隔线分段，这里只有 2 段、无徽标。
                            implicitHeight: Math.round(32 * Theme.fontScale)
                            radius: Theme.radiusSmall
                            color: seg.active ? Theme.primary
                                              : (segMouse.containsMouse ? Theme.bgHover : "transparent")

                            Text {
                                id: segLabel
                                anchors.centerIn: parent
                                text: seg.modelData
                                color: seg.active ? Theme.textOnPrimary : Theme.textSecondary
                                font.family: Theme.fontFamily
                                font.pixelSize: container.fntBase
                                font.bold: seg.active
                            }

                            MouseArea {
                                id: segMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: container.tabIndex = seg.index
                            }
                        }
                    }
                }
            }

            Item {
                Layout.fillWidth: true
            }
        }

        // ── 两个子视图 ─────────────────────────────────────────
        StackLayout {
            objectName: "monitorStack"
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: container.tabIndex

            Loader {
                objectName: "pulseLoader"
                asynchronous: false
                source: "MarketPulsePane.qml"
            }

            Loader {
                objectName: "watchLoader"
                asynchronous: false
                // 关注页只在首次切过去时创建（`active` 由页签决定）
                active: container.tabIndex === 1
                source: "WatchlistPage.qml"
            }
        }
    }
}
