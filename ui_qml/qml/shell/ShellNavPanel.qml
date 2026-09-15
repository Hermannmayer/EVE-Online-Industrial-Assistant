import QtQuick

/* 左侧导航（阶段 5 批次 6.1）—— Widgets 版是 `ui_pyside6/main_window_nav._build_nav_tree`。

   条目来自 `shell.navItems`（Python 侧的 `NAV_TREE`，单一来源不复制到 QML）；
   底部三个设置入口（机库 / 人物 / 系统）与原版位置一致。
*/
Item {
    id: root

    implicitWidth: 160

    Text {
        id: header
        anchors.top: parent.top
        anchors.topMargin: 8
        anchors.left: parent.left
        anchors.leftMargin: 12
        text: "EVE 商人助手"
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fs(14)
        font.bold: true
        color: Theme.primary
    }

    ListView {
        id: navList
        anchors.top: header.bottom
        anchors.topMargin: 10
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: bottomRow.top
        clip: true
        model: shell.navItems
        boundsBehavior: Flickable.StopAtBounds

        delegate: Item {
            required property var modelData
            width: navList.width
            height: modelData.section ? 24 : 28

            // 分组标题：不可点
            Text {
                anchors.left: parent.left
                anchors.leftMargin: 12
                anchors.verticalCenter: parent.verticalCenter
                visible: modelData.section
                text: modelData.label
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fs(10)
                font.bold: true
                color: Theme.textSecondary
            }

            // 页面行：图标 + 文本，当前页高亮
            Rectangle {
                anchors.fill: parent
                anchors.leftMargin: 4
                anchors.rightMargin: 4
                radius: Theme.radiusSmall
                visible: !modelData.section
                color: {
                    if (!modelData.section && shell.currentKey === modelData.key)
                        return Theme.bgSurfaceLight;
                    return rowMouse.containsMouse ? Theme.bgHover : "transparent";
                }

                Image {
                    id: rowIcon
                    anchors.left: parent.left
                    anchors.leftMargin: 8
                    anchors.verticalCenter: parent.verticalCenter
                    visible: !modelData.section
                    width: 16
                    height: 16
                    sourceSize.width: 16
                    sourceSize.height: 16
                    fillMode: Image.PreserveAspectFit
                    source: !modelData.section && modelData.icon !== "" ?
                            "image://phosphor/" + modelData.icon + "?c=" +
                            encodeURIComponent(Theme.hex(
                                shell.currentKey === modelData.key ? Theme.primary : Theme.textSecondary)) +
                            "&s=16" : ""
                }

                Text {
                    anchors.left: rowIcon.right
                    anchors.leftMargin: 8
                    anchors.right: parent.right
                    anchors.rightMargin: 4
                    anchors.verticalCenter: parent.verticalCenter
                    visible: !modelData.section
                    text: modelData.section ? "" : " " + modelData.label
                    elide: Text.ElideRight
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fs(12)
                    color: shell.currentKey === modelData.key ? Theme.textPrimary : Theme.textSecondary
                }

                MouseArea {
                    id: rowMouse
                    anchors.fill: parent
                    hoverEnabled: !modelData.section
                    enabled: !modelData.section
                    cursorShape: Qt.PointingHandCursor
                    onClicked: shell.navigate(modelData.key)
                }
            }
        }
    }

    // 底部设置入口（与原版同序：机库 → 人物 → 系统，最右是系统）
    Item {
        id: bottomRow
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 44

        ShellIconButton {
            id: sysBtn
            anchors.right: parent.right
            anchors.rightMargin: 8
            anchors.verticalCenter: parent.verticalCenter
            implicitWidth: 36
            implicitHeight: 36
            iconSize: 20
            icon: shell.iconFile("settings")
            tint: Theme.textSecondary
            tooltip: "系统设置"
            onClicked: shell.openSysSettings()
        }
        ShellIconButton {
            id: charBtn
            anchors.right: sysBtn.left
            anchors.rightMargin: 4
            anchors.verticalCenter: parent.verticalCenter
            implicitWidth: 36
            implicitHeight: 36
            iconSize: 20
            icon: shell.iconFile("user")
            tint: Theme.textSecondary
            tooltip: "人物设置"
            onClicked: shell.openCharSettings()
        }
        ShellIconButton {
            id: hangarBtn
            anchors.right: charBtn.left
            anchors.rightMargin: 4
            anchors.verticalCenter: parent.verticalCenter
            implicitWidth: 36
            implicitHeight: 36
            iconSize: 20
            icon: shell.iconFile("hangar")
            tint: Theme.textSecondary
            tooltip: "机库设置：所在星系 / 设施类型 / 改装件 / 设施税 / 默认机库"
            onClicked: shell.openHangarSettings()
        }
    }
}
