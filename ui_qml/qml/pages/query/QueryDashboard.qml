import QtQuick
import QtQuick.Layouts
import "../../components"

/* 空闲态仪表盘 —— 查询页**没有搜索/没有结果**时占据整个主工作区。
 *
 * 对应界面标注图「当没有进行物品查询的时候，底下显示上面的资产和产线，还有挂单列表的详情；
 * 当输入物品查找的时候，底下就自动隐藏，实现正常的物品查询功能」。
 *
 * 三块横排：产线详情（人物、产线占用）| 资产折线图 | 挂单列表。
 * 宽度**不按 1:1:1 平分**：折线图是主体（要看清走势与刻度），另外两块是列表。
 *
 * 刷新由本文件驱动，而不是桥里自建定时器：只有本面板**可见**时才跑，
 * 切到结果态/别的页面就停 —— 空闲态在后台空转会对 SQLite 反复取数。
 */
Item {
    id: root

    //: `bridge.dashboard`
    property var dashboard: null

    readonly property int gap: Theme.spacingSm

    //: 可见即刷新一次，之后每 60s 一次
    onVisibleChanged: if (visible && root.dashboard) {
        root.dashboard.refresh()
        pollTimer.restart()
    } else {
        pollTimer.stop()
    }

    Timer {
        id: pollTimer
        interval: 60000
        repeat: true
        running: false
        onTriggered: if (root.dashboard)
            root.dashboard.refresh()
    }

    RowLayout {
        anchors.fill: parent
        spacing: root.gap

        /* 两侧**必须显式 fillWidth: false**：`FSection` 自己声明了 `Layout.fillWidth: true`，
         * 三个都 fill 的话「多出来的宽度」会被**均分**，`preferredWidth` 只决定基准宽 ——
         * 实测比例会从 24 : 52 : 34 漂成 37 : 11 : 52（中间那张图被挤成一条）。
         * 只留中间 fill，多余宽度才全给折线图。
         *
         * 两侧收到 22% / 24%：折线图是这一屏的主体（用户明确要求「占绝大部分」），
         * 另外两块是列表，窄一点不影响读。产线详情收到 22% 也**必须**配
         * `occupancyByLine` 的「按产线类型分行」—— 按人物分行（`FCapacityRow` 那套）
         * 在那个宽度下格子会压到标签上、徽章叠在标签上（实测）。 */
        FPanel {
            title: qsTr("产线详情")
            Layout.fillWidth: false
            Layout.fillHeight: true
            Layout.preferredWidth: Math.round(root.width * 0.22)

            OccupancyPanel {
                anchors.fill: parent
                dashboard: root.dashboard
            }
        }

        FPanel {
            title: qsTr("资产折线图")
            Layout.fillWidth: true
            Layout.fillHeight: true

            AssetChartPanel {
                anchors.fill: parent
                dashboard: root.dashboard
            }
        }

        FPanel {
            title: qsTr("挂单列表")
            Layout.fillWidth: false
            Layout.fillHeight: true
            Layout.preferredWidth: Math.round(root.width * 0.24)

            OpenOrdersPanel {
                anchors.fill: parent
                dashboard: root.dashboard
            }
        }
    }
}
