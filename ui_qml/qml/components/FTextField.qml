import QtQuick
import QtQuick.Controls

/* Fluent 输入框 —— 用主题色覆盖背景（下划线式）。

   只覆盖 background，**保留** Qt 的 contentItem（它负责文本测量/选中/滚动），
   覆盖 contentItem 会把输入区尺寸搞坏（FComboBox 上踩过）。
*/
TextField {
    id: root

    implicitHeight: 32
    leftPadding: Theme.spacingSm
    rightPadding: Theme.spacingSm
    topPadding: Theme.spacingXs
    bottomPadding: Theme.spacingXs
    font.family: Theme.fontFamily
    font.pixelSize: Theme.fs(12)
    color: Theme.textPrimary
    placeholderTextColor: Theme.textSecondary
    selectionColor: Theme.primary
    selectedTextColor: Theme.textOnPrimary

    background: Rectangle {
        color: "transparent"

        // Fluent 的输入框是下划线式：静止 1px 中性线，获得焦点转主题色并加粗
        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: root.activeFocus ? 2 : 1
            color: root.activeFocus ? Theme.primary : Theme.border

            Behavior on color {
                ColorAnimation {
                    duration: Theme.reducedMotion ? 0 : Theme.durationFast
                    easing.type: Easing.OutCubic
                }
            }
        }
    }
}
