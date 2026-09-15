import QtQuick
import QtQuick.Controls

/* 外壳里的小图标按钮（标题栏 / 导航栏底部 / 工具行共用，阶段 5 批次 6.1）。

   图标走 `image://phosphor/<name>?c=<hex>&s=<px>`。**`c` 必须 encodeURIComponent**：
   不然 `#` 会被当作 URL 片段分隔符吃掉，颜色静默退回默认的次要文字色
   —— 不报错，只是「设了色没生效」（仓库里已有几处这么写的，别再添）。

   本组件**无内部状态**：`checked` 由调用方绑定到桥的真实状态，点击只发信号，
   免得出现「按钮亮了但外壳没真置顶」这种两套状态。
*/
Item {
    id: root

    property string icon: ""
    property string label: ""            // 非空则图标 + 文字并排
    property color tint: Theme.textPrimary
    property color labelTint: tint
    property string tooltip: ""
    property bool checkable: false
    property bool checked: false
    property int iconSize: 14
    property int padH: 6
    property bool dangerHover: false     // 悬停变红（关闭按钮）

    signal clicked()

    implicitWidth: root.label === "" ? 28 : (root.padH * 2 + root.iconSize + 4 + labelText.implicitWidth)
    implicitHeight: 28

    Rectangle {
        anchors.fill: parent
        radius: Theme.radiusSmall
        color: {
            if (mouse.containsMouse)
                return root.dangerHover ? Theme.accentRed
                     : (root.checked ? Theme.bgSurfaceLight : Theme.bgHover);
            return root.checked ? Theme.bgSurfaceLight : "transparent";
        }

        Image {
            id: iconImage
            anchors.left: parent.left
            anchors.leftMargin: root.padH
            anchors.verticalCenter: parent.verticalCenter
            width: root.iconSize
            height: root.iconSize
            sourceSize.width: root.iconSize
            sourceSize.height: root.iconSize
            fillMode: Image.PreserveAspectFit
            source: root.icon === "" ? "" :
                    "image://phosphor/" + root.icon + "?c=" +
                    encodeURIComponent(Theme.hex(
                        mouse.containsMouse && root.dangerHover ? Theme.textOnPrimary
                      : (root.checked && root.checkable ? Theme.textOnPrimary : root.tint))) +
                    "&s=" + root.iconSize
        }

        Text {
            id: labelText
            anchors.left: iconImage.right
            anchors.leftMargin: 4
            anchors.verticalCenter: parent.verticalCenter
            visible: root.label !== ""
            text: root.label
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fs(12)
            color: mouse.containsMouse && root.dangerHover ? Theme.textOnPrimary
                 : (root.checked && root.checkable ? Theme.textOnPrimary : root.labelTint)
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
