import QtQuick
import QtQuick.Controls
import "../../components"

/* 详情面板 · 精炼产物与价格（底部「总计、价格」）。
 *
 * 对应界面标注图「精炼产物、价格 / 总计、价格」。数量默认 1（与查询页的选中行 1 件一致），
 * 产率与产出量由 `services/refining_service.py` 按技能与设施口径算好，
 * 这里只渲染，不做任何计算。
 */
Item {
    id: root

    //: `bridge.detail`
    property var detail: null

    readonly property int fntSmall: Math.round(11 * Theme.fontScale)
    readonly property int fntBase: Math.round(12 * Theme.fontScale)
    readonly property int totalH: Math.max(20, fntBase + 10)

    Column {
        anchors.fill: parent
        spacing: Theme.spacingXs

        PanelTable {
            width: parent.width
            height: parent.height - root.totalH - Theme.spacingXs
            headers: [qsTr("产出材料"), qsTr("数量"), qsTr("产率"), qsTr("价值 (ISK)")]
            ratios: [2.2, 1.0, 0.9, 1.6]
            rows: root.detail ? root.detail.refineRows : []
            emptyText: root.detail && root.detail.typeId > 0
                       ? qsTr("该物品不可精炼") : qsTr("选择一行查看精炼产物")
        }

        // ── 总计、价格 ────────────────────────────────────────
        Item {
            width: parent.width
            height: root.totalH

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                height: 1
                color: Theme.border
            }

            Row {
                anchors.fill: parent
                spacing: Theme.spacingSm

                Repeater {
                    model: root.detail ? root.detail.refineTotalRows : []

                    Text {
                        required property var modelData
                        height: parent.height
                        width: Math.max(60, (parent.width - 3 * Theme.spacingSm) / 4)
                        verticalAlignment: Text.AlignVCenter
                        horizontalAlignment: Text.AlignRight
                        text: String(modelData.label) + " " + String(modelData.valueText)
                        color: modelData.color && String(modelData.color) !== ""
                               ? String(modelData.color) : Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: root.fntBase
                        elide: Text.ElideRight
                    }
                }
            }
        }
    }
}
