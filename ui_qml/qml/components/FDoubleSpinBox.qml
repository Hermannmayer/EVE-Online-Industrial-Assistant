import QtQuick
import QtQuick.Controls
import QtQuick.Shapes

/* Fluent 小数微调框 —— 用主题色覆盖背景与上下按钮。

   Qt 官方样式的这三块（背景 / 上按钮 / 下按钮）都是中性灰图集，不跟主题。
   只覆盖这三处，contentItem 交回 Qt（它负责数值文本的测量与编辑）。

   ⚠️ **不要覆盖 contentItem**：`SpinBox.qml` 在样式里给内容项绑定了 `text` /
   `validator` / `inputMethodHints`，在派生类型里重写它会把那些绑定一起丢掉
   （实测：文字变空、校验器消失，框直接不可用）。

   真正要处理的是**两套内边距叠加**：样式给内容项自带 `leftPadding: 10 /
   rightPadding: 26`，控件级再设 8 / 22 —— 84px 宽的框里文字可用宽只剩
   `84-8-22-10-26 = 18px`，而 "1.00" 实测要 24px，于是**首位数字被裁**，
   界面上显示成「.00」（实测：真窗口 1400px 下两个倍率框都是 `.00`）。
   控件级内边距因此设 0：定位交回样式的内容项内边距（10 / 26 已足够让文字
   避开右侧上下箭头，箭头位置本就是下面显式写死的 `root.width - width - 2`）。
*/
DoubleSpinBox {
    id: root

    // Qt 的 SpinBox.editable 默认是 false——只能用箭头，**不能打字**。
    // Widgets 版的 QDoubleSpinBox 是可输入的，不设这个就是功能退化（用户实测报过）。
    editable: true

    implicitHeight: 32
    // 归零（见文件头）：样式的内容项已自带 10 / 26，再叠控件级的内边距会把文字挤掉
    leftPadding: 0
    rightPadding: 0
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
