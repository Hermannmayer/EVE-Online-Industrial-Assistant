import QtQuick

/* 带标题的分区面板 —— `FSection` 的「锚点版」。外观逐项相同（描边圆角 + 灰色小标题），
 * **唯一区别是内容容器**：
 *
 *   - `FSection` 把子项收进内层 `ColumnLayout` → 只能写 `Layout.*`；
 *     写 `anchors.fill: parent` 会被布局**静默忽略**，子项塌成自己的 implicitHeight
 *     （实测：整块表格/图表变成一条 20px 高的线，只剩表头，看着像「没数据」）。
 *   - `FPanel` 把子项收进一个普通 `Item` → 子项可以 `anchors.fill: parent`。
 *
 * 选择标准：面板里要放**一整块自己管布局的内容**（表格、图表、占用条）用 `FPanel`；
 * 放若干行依次排列的控件用 `FSection`。
 */
Rectangle {
    id: root

    default property alias contentData: content.data
    property string title: ""

    implicitWidth: 240
    implicitHeight: 120
    radius: Theme.radius
    color: Theme.bgSurface
    border.width: 1
    border.color: Theme.border

    Text {
        id: titleText
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: Theme.spacingSm
        height: visible ? Math.round(13 * Theme.fontScale) + 4 : 0
        visible: root.title !== ""
        verticalAlignment: Text.AlignVCenter
        text: root.title
        color: Theme.textSecondary
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(12 * Theme.fontScale)
        elide: Text.ElideRight
    }

    Item {
        id: content
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: titleText.bottom
        anchors.bottom: parent.bottom
        anchors.margins: Theme.spacingSm
        // 标题不可见时 titleText 高度为 0，内容自然顶到上边距，不需要另写分支
    }
}
