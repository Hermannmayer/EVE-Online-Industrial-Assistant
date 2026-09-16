import QtQuick
import QtQuick.Controls

/* 导航栏底部入口按钮（界面改版第 1 步）—— 图标在上、中文标签在下。

   为什么不直接用 `ShellIconButton`：那个是「图标在左、文字在右」，
   `implicitWidth` 按文案伸算（`padH*2 + iconSize + 4 + 文字宽`），
   160px 的侧栏里三个并排放不下。这里改成竖排 + 固定宽度，三个才排得进并居中。

   与 `ShellIconButton` 保持同一条契约：**无内部状态** —— 没有 `checked`，
   点击只发 `clicked()`，状态一律由调用方绑到桥的真实属性，
   免得出现「按钮亮了但外壳没照做」这种两套状态。
*/
Item {
    id: root

    property string icon: ""
    property string label: ""
    property color tint: Theme.textSecondary
    property string tooltip: ""
    property int iconSize: 18

    signal clicked()

    implicitWidth: 46
    implicitHeight: 46

    Rectangle {
        anchors.fill: parent
        radius: Theme.radiusSmall
        color: mouse.containsMouse ? Theme.bgHover : "transparent"

        /* 图标与标签整块居中：两组各自 `anchors.horizontalCenter`，
           高度差（图标略高、标签略矮）不会把这一列顶歪。 */
        Image {
            id: iconImage
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.top: parent.top
            anchors.topMargin: 6
            width: root.iconSize
            height: root.iconSize
            sourceSize.width: root.iconSize
            sourceSize.height: root.iconSize
            fillMode: Image.PreserveAspectFit
            // `c` 必须 encodeURIComponent：`#` 会被当成 URL 片段分隔符吃掉，
            // 颜色静默退回默认值 —— 不报错，只是「设了色没生效」
            source: root.icon === "" ? "" :
                    "image://phosphor/" + root.icon + "?c=" +
                    encodeURIComponent(Theme.hex(root.tint)) + "&s=" + root.iconSize
        }

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.top: iconImage.bottom
            anchors.topMargin: 2
            text: root.label
            font.family: Theme.fontFamily
            // 不写 Theme.fs()：那个是函数调用，不进绑定依赖追踪，改字号不会重算
            font.pixelSize: Math.round(10 * Theme.fontScale)
            color: root.tint
        }
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }

    ToolTip.visible: mouse.containsMouse && root.tooltip !== ""
    ToolTip.text: root.tooltip
    ToolTip.delay: 500
}
