import QtQuick
import QtQuick.Layouts
import "../components"

/* 「人物占用情况」对话框（工业页底部按钮「人物占用」）。
 *
 * 内容就是查询页空闲态仪表盘左栏那块「产线详情」—— 同一个 `OccupancyPanel`、
 * 同一套「每人物一块、块内制造 / 科研 / 反应容量条」的渲染，不另做一份表格：
 * 早先那张表有「队列时长 / 技能等级」两列常年 N/A，且只统计**正在生产**的计划。
 *
 * 口径由桥决定（`ui_qml.bridge.char_usage_bridge`）：这里按**已规划**算 ——
 * 待生产 / 生产中 / 待下线的计划都占着产线，排产阶段就能看出谁的线会超。
 */

Item {
    id: page

    readonly property var occ: typeof bridge !== "undefined" ? bridge : null

    Rectangle {
        anchors.fill: parent
        color: Theme.bgDark
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.spacingSm
        spacing: Theme.spacingSm

        OccupancyPanel {
            Layout.fillWidth: true
            Layout.fillHeight: true
            occupancyBridge: page.occ
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingSm

            Text {
                Layout.fillWidth: true
                text: qsTr("按「已规划」统计：待生产 / 生产中 / 待下线的计划都占着产线")
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(11 * Theme.fontScale)
                elide: Text.ElideRight
            }

            FButton {
                text: qsTr("关闭")
                onClicked: if (page.occ)
                    page.occ.reject()
            }
        }
    }
}
