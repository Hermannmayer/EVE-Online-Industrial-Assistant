import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 「设施」这一行：可编辑下拉（可从机库名里挑，也可直接输入）。
 *
 * 科研三框与「加入制造计划」框都要这一行 —— 抽出来，可编辑下拉的 placeholder
 * 处理只写一份（那是踩过坑的地方，见 `Component.onCompleted` 注释）。
 * 只依赖桥的 `facilityOptions` / `setFacility`。
 */

RowLayout {
    id: root

    //: 对话框桥
    property var dlg: null
    property int labelWidth: Math.round(88 * Theme.fontScale)
    property int boxWidth: Math.round(260 * Theme.fontScale)
    property string labelText: qsTr("设施:")

    Layout.fillWidth: true
    spacing: Theme.spacingSm

    Text {
        Layout.preferredWidth: root.labelWidth
        horizontalAlignment: Text.AlignRight
        text: root.labelText
        color: Theme.textPrimary
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(12 * Theme.fontScale)
    }

    FComboBox {
        id: facBox
        objectName: "facilityBox"
        Layout.preferredWidth: root.boxWidth
        editable: true
        // 与原版一致：不预选任何一项，起点是空输入
        currentIndex: -1
        model: root.dlg ? root.dlg.facilityOptions : []
        // 只把输入单向推给桥。**不**把 bridge.facility 反绑到 editText：
        // 反向绑定会被用户打字打断（QML 里写过一次就断链），单向没这问题。
        onEditTextChanged: if (root.dlg)
            root.dlg.setFacility(editText)
        onActivated: if (root.dlg)
            root.dlg.setFacility(currentText)
    }

    Item {
        Layout.fillWidth: true
    }

    Component.onCompleted: {
        // 给可编辑下拉补 placeholder —— Qt 的 ComboBox 没有 placeholderText 属性，
        // 但样式给的 contentItem 是 TextField（QQuickTextField 带该属性）。
        // 只在原地赋值、**不替换** contentItem，绕开 FComboBox 顶部注释里说的测量坑。
        const ci = facBox.contentItem;
        if (ci && ci.placeholderText !== undefined)
            ci.placeholderText = qsTr("选择或输入设施名称");
    }
}
