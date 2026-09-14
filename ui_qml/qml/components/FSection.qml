import QtQuick
import QtQuick.Layouts

/* 带标题的分区容器 —— 对齐 Widgets 版 `QGroupBox` 的外观（描边圆角 + 灰色小标题）。
 *
 * 与 `FCard` 同款：`default property alias` 把使用处声明的子项收进内层 ColumnLayout，
 * 于是调用方直接写内容即可：
 *
 *     FSection {
 *         title: "跨区域价格对比"
 *         Text { text: "…" }
 *     }
 */
Rectangle {
    id: root

    default property alias contentData: box.data

    property string title: ""

    // 放在布局里时默认吃满宽度（分区容器总是整行），高度随内容
    Layout.fillWidth: true

    implicitWidth: box.implicitWidth + 2 * Theme.spacingSm
    implicitHeight: box.implicitHeight + 2 * Theme.spacingSm
    radius: Theme.radius
    color: Theme.bgSurface
    border.width: 1
    border.color: Theme.border

    ColumnLayout {
        id: box
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: Theme.spacingSm
        spacing: Theme.spacingSm

        Text {
            Layout.fillWidth: true
            visible: root.title !== ""
            text: root.title
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }
    }
}
