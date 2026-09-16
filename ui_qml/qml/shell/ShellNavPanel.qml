import QtQuick

/* 左侧导航（阶段 5 批次 6.1；界面改版第 1 步重排）—— Widgets 版是
   `ui_pyside6/main_window_nav._build_nav_tree`。

   条目来自 `shell.navItems`（Python 侧的 `NAV_TREE`，单一来源不复制到 QML）。
   曾经首项是「核心功能」分组标题，改版已去掉 —— delegate 因此只剩一种行样式。

   顶部是 logo 不是文字：外壳标题栏已经写着「EVE 商人助手」，这里再写一遍是重复。
   logo 路径由 `shell.logoSource` 发过来（深/浅主题各一张），**QML 不拼文件路径** ——
   本文件在 `ui_qml/qml/shell/` 下，`Qt.resolvedUrl` 解析不到 `ui_qml/assets/`，
   拼了会静默空白。

   底部三个设置入口（机库 / 人物 / 系统）改为图标 + 文字并整组居中，
   见 `ShellNavActionButton.qml` 里为什么不能直接用 `ShellIconButton`。
*/
Item {
    id: root

    implicitWidth: 160

    /* 左内边距与标题行文字、工具行左侧控件组**共用一条竖线**（都是 12）：
       批注「此处没有上下对齐（和旁边的字）」说的就是这条线没对齐。
       导航行图标用它定位（行内先缩 4，所以图标再缩 `leftInset - 4`）；
       logo 例外 —— 见下面它为什么居中。 */
    readonly property int leftInset: Theme.spacingMd

    Image {
        id: logo
        anchors.top: parent.top
        anchors.topMargin: Theme.spacingMd
        /* 水平居中。侧栏是 160px 的独立面板，logo 靠左贴在图标列上会挤成一堆；
           居中是用户对着界面明确要求的效果。标题栏文字仍走 chromeInset 那条线。 */
        anchors.horizontalCenter: parent.horizontalCenter
        /* 高度写死（不是靠图片自己的尺寸）：logo 是生成资产，文件还没生成时
           `source` 为空、图片没有固有尺寸，导航列表会往上窜一截。
           40px 高按约 1.42:1 的构图出约 57px 宽；`sourceSize` 一起给，
           让 Qt 从 96px 的原图下采样，边缘比先拉大再缩干净。 */
        height: 40
        sourceSize.height: 40
        fillMode: Image.PreserveAspectFit
        smooth: true
        source: shell.logoSource
    }

    ListView {
        id: navList
        anchors.top: logo.bottom
        anchors.topMargin: Theme.spacingMd
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: bottomRow.top
        clip: true
        model: shell.navItems
        boundsBehavior: Flickable.StopAtBounds

        delegate: Item {
            required property var modelData
            width: navList.width
            height: 28

            // 页面行：图标 + 文本，当前页高亮
            Rectangle {
                anchors.fill: parent
                anchors.leftMargin: 4
                anchors.rightMargin: 4
                radius: Theme.radiusSmall
                color: shell.currentKey === modelData.key
                       ? Theme.bgSurfaceLight
                       : (rowMouse.containsMouse ? Theme.bgHover : "transparent")

                Image {
                    id: rowIcon
                    anchors.left: parent.left
                    anchors.leftMargin: root.leftInset - 4
                    anchors.verticalCenter: parent.verticalCenter
                    width: 16
                    height: 16
                    sourceSize.width: 16
                    sourceSize.height: 16
                    fillMode: Image.PreserveAspectFit
                    /* 配色由桥发过来（`NAV_TREE` 里写的是 token 名，桥解析成色值
                       并做对比度兜底）—— 这里**不再按选中态改色**：选中与否由行底色
                       与文字色表达，图标本身保持各自的彩色。
                       `c` 必须 encodeURIComponent，否则 `#` 被当 URL 片段吃掉。 */
                    source: modelData.icon !== "" ?
                            "image://phosphor/" + modelData.icon + "?c=" +
                            encodeURIComponent(modelData.color) + "&s=16" : ""
                }

                Text {
                    anchors.left: rowIcon.right
                    anchors.leftMargin: 8
                    anchors.right: parent.right
                    anchors.rightMargin: 4
                    anchors.verticalCenter: parent.verticalCenter
                    text: modelData.label
                    elide: Text.ElideRight
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fs(12)
                    color: shell.currentKey === modelData.key ? Theme.textPrimary : Theme.textSecondary
                }

                MouseArea {
                    id: rowMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: shell.navigate(modelData.key)
                }
            }
        }
    }

    // 底部设置入口：图标在上、文字在下，三个一组水平居中
    Item {
        id: bottomRow
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 54

        Row {
            objectName: "navActions"
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 4
            spacing: 2

            ShellNavActionButton {
                icon: shell.iconFile("hangar")
                label: qsTr("机库")
                tooltip: qsTr("机库设置：所在星系 / 设施类型 / 改装件 / 设施税 / 默认机库")
                onClicked: shell.openHangarSettings()
            }
            ShellNavActionButton {
                icon: shell.iconFile("user")
                label: qsTr("人物")
                tooltip: qsTr("人物设置")
                onClicked: shell.openCharSettings()
            }
            ShellNavActionButton {
                icon: shell.iconFile("settings")
                label: qsTr("系统")
                tooltip: qsTr("系统设置")
                onClicked: shell.openSysSettings()
            }
        }
    }
}
