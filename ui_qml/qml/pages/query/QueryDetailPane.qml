import QtQuick
import QtQuick.Layouts
import "../../components"

/* 详情面板 —— 查询**有结果**时占据主工作区下半部（上半部仍是结果表）。
 *
 * 对应界面标注图「当有物品查询时显示以上界面」的四块：
 *   左上 5 个默认贸易中心的价格   右上 订单列表
 *   左下 精炼产物、价格           右下 制造所需的材料
 *
 * 左右两列的宽度**不相等**（左窄右宽）：左侧两块是「两三个数字一行的短表」，
 * 右侧的订单表有「空间站」这种长文本列、材料表有五列，平分会让左侧大片留白。
 *
 * 每块都用 `FSection`（描边圆角 + 灰色小标题）而不是 `FCard`：`FCard` 的背景带
 * `layer.enabled` + `MultiEffect` 阴影，而本仓已记录「带 layer 的 item 在离屏
 * 截图路径下整个消失」（见 `ui_qml/icon_provider.py` 头部）—— 用它会让
 * `scripts/shell_snapshot.py` 拍出来的面板**整块空白**，等于没有验收手段。
 */
Item {
    id: root

    //: `bridge.detail`
    property var detail: null

    //: 左列占宽（0..1）
    readonly property real leftRatio: 0.28
    //: 上排占高（0..1）
    readonly property real topRatio: 0.58

    readonly property int gap: Theme.spacingSm

    RowLayout {
        anchors.fill: parent
        spacing: root.gap

        // ══ 左列 ══════════════════════════════════════════════
        ColumnLayout {
            Layout.fillWidth: false
            Layout.fillHeight: true
            Layout.preferredWidth: Math.round(root.width * root.leftRatio)
            spacing: root.gap

            FPanel {
                title: qsTr("5 个默认贸易中心的价格")
                Layout.fillWidth: true
                Layout.fillHeight: false
                Layout.preferredHeight: Math.round(root.height * root.topRatio - root.gap)

                HubPricePanel {
                    anchors.fill: parent
                    detail: root.detail
                }
            }

            FPanel {
                title: qsTr("精炼产物、价格")
                Layout.fillWidth: true
                Layout.fillHeight: true

                RefinePanel {
                    anchors.fill: parent
                    detail: root.detail
                }
            }
        }

        // ══ 右列 ══════════════════════════════════════════════
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: root.gap

            FPanel {
                title: qsTr("订单列表")
                Layout.fillWidth: true
                Layout.fillHeight: false
                Layout.preferredHeight: Math.round(root.height * root.topRatio - root.gap)

                OrderPanel {
                    anchors.fill: parent
                    detail: root.detail
                }
            }

            FPanel {
                title: qsTr("制造所需的材料")
                Layout.fillWidth: true
                Layout.fillHeight: true

                MaterialPanel {
                    anchors.fill: parent
                    detail: root.detail
                }
            }
        }
    }
}
