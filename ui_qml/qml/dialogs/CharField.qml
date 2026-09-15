import QtQuick
import QtQuick.Layouts
import "../components"

/* 「角色」这一行：角色下拉。
 *
 * 科研三框与「加入制造计划」框都要这一行 —— 抽出来避免重复。
 * 只依赖桥的 `charOptions` / `charIndex` / `setCharIndex`。
 */

RowLayout {
    id: root

    //: 对话框桥
    property var dlg: null
    property int labelWidth: Math.round(88 * Theme.fontScale)
    property int boxWidth: Math.round(260 * Theme.fontScale)

    Layout.fillWidth: true
    spacing: Theme.spacingSm

    Text {
        Layout.preferredWidth: root.labelWidth
        horizontalAlignment: Text.AlignRight
        text: qsTr("角色:")
        color: Theme.textPrimary
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(12 * Theme.fontScale)
    }

    FComboBox {
        objectName: "charBox"
        Layout.preferredWidth: root.boxWidth
        model: root.dlg ? root.dlg.charOptions : []
        currentIndex: root.dlg ? root.dlg.charIndex : 0
        onActivated: if (root.dlg)
            root.dlg.setCharIndex(currentIndex)
    }

    Item {
        Layout.fillWidth: true
    }
}
