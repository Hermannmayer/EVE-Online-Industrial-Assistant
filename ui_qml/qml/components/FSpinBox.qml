import QtQuick
import QtQuick.Controls
import QtQuick.Shapes

/* Fluent 整数微调框 —— 用主题色覆盖背景与上下按钮。

   Qt 官方样式的这三块（背景 / 上按钮 / 下按钮）都是中性灰图集，不跟主题。
   只覆盖这三处，contentItem 交回 Qt（它负责数值文本的测量与编辑）。
*/
SpinBox {
    id: root

    // Qt 的 SpinBox.editable 默认是 false——只能用箭头，**不能打字**。
    // Widgets 版的 QDoubleSpinBox 是可输入的，不设这个就是功能退化（用户实测报过）。
    editable: true

    implicitHeight: 32
    leftPadding: Theme.spacingSm
    rightPadding: 22
    font.family: Theme.fontFamily
    font.pixelSize: Theme.fs(12)

    background: Rectangle {
        color: "transparent"

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: root.activeFocus ? 2 : 1
            color: root.activeFocus ? Theme.primary : Theme.border
        }
    }

    up.indicator: FArrowButton {
        x: root.width - width - 2
        y: 3
        width: 16
        height: (root.height - 6) / 2
        hovered: root.up.hovered
        pressed: root.up.pressed
        flipped: true
        active: root.value < root.to
    }

    down.indicator: FArrowButton {
        x: root.width - width - 2
        y: 3 + (root.height - 6) / 2
        width: 16
        height: (root.height - 6) / 2
        hovered: root.down.hovered
        pressed: root.down.pressed
        active: root.value > root.from
    }
}
