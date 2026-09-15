import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 制造材料明细（阶段 4b）—— 对照 `ui_pyside6/views/all_items_view.py::MatDlg`。
 *
 * 标题行 → 材料列表（图标 + 「名称 x数量 @ 单价 = 小计」）→ 总成本 → 关闭。
 * 数据一律由 `ui_qml/bridge/all_items_bridge.py` 的 `MatBridge` 取好
 * （取数走 `blueprint_repo.get_manufacturing_materials`，一份实现）。
 *
 * 没有制造蓝图时只显示一行红字（原版连列表都不建）。
 */

FDialogFrame {
    id: frame

    readonly property var mt: typeof bridge !== "undefined" ? bridge : null

    dlg: frame.mt
    acceptText: qsTr("关闭")
    // 纯展示：只有「关闭」一个动作
    cancelVisible: false

    Text {
        objectName: "itemTitle"
        Layout.fillWidth: true
        text: frame.mt ? frame.mt.itemTitle : ""
        color: Theme.primary
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(13 * Theme.fontScale)
        font.bold: true
        elide: Text.ElideRight
    }

    Text {
        objectName: "noBlueprintText"
        Layout.fillWidth: true
        visible: frame.mt ? !frame.mt.found : false
        text: qsTr("此物品无制造蓝图")
        color: Theme.accentRed
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(12 * Theme.fontScale)
    }

    Rectangle {
        objectName: "materialList"
        Layout.fillWidth: true
        Layout.fillHeight: true
        visible: frame.mt ? frame.mt.found : false
        color: Theme.bgSurface
        radius: Theme.radius
        border.width: 1
        border.color: Theme.border

        ListView {
            id: list
            anchors.fill: parent
            anchors.margins: 1
            clip: true
            model: frame.mt ? frame.mt.rows : []
            boundsBehavior: Flickable.StopAtBounds

            ScrollBar.vertical: ScrollBar {
                policy: ScrollBar.AsNeeded
            }

            delegate: Item {
                id: row

                required property var modelData

                width: list.width
                height: Math.round(32 * Theme.fontScale)

                Image {
                    id: icon
                    anchors.left: parent.left
                    anchors.leftMargin: Theme.spacingSm
                    anchors.verticalCenter: parent.verticalCenter
                    width: Math.round(28 * Theme.fontScale)
                    height: width
                    source: row.modelData.iconUrl
                    sourceSize.width: width
                    sourceSize.height: height
                    smooth: true
                    fillMode: Image.PreserveAspectFit
                }

                Text {
                    anchors.left: icon.right
                    anchors.leftMargin: Theme.spacingSm
                    anchors.right: parent.right
                    anchors.rightMargin: Theme.spacingSm
                    anchors.verticalCenter: parent.verticalCenter
                    text: row.modelData.text
                    color: Theme.textPrimary
                    font.family: Theme.fontFamily
                    font.pixelSize: Math.round(12 * Theme.fontScale)
                    elide: Text.ElideRight
                }
            }
        }
    }

    Text {
        objectName: "totalText"
        Layout.fillWidth: true
        visible: frame.mt ? frame.mt.found : false
        text: frame.mt ? frame.mt.totalText : ""
        color: Theme.accentGreen
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(12 * Theme.fontScale)
        font.bold: true
    }
}
