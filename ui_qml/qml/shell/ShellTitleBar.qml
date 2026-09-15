import QtQuick

/* 标题行（阶段 5 批次 6.1）—— Widgets 版是 `ui_pyside6/title_bar.py`。

   空区可拖动、双击最大化：拖动交给 Python 的 `startSystemMove()`
   （一次性 SC_MOVE，比逐帧改窗口位置稳），与 Widgets 版的取舍一致。

   最大化/还原图标由 `shell.maximized` 驱动；置顶的 checked 由 `shell.pinned` 驱动
   —— 都是**外壳的真实状态**，不是按钮自己的局部状态。
*/
Item {
    id: root

    implicitHeight: 32

    Text {
        anchors.left: parent.left
        anchors.leftMargin: 12
        anchors.verticalCenter: parent.verticalCenter
        text: shell.appTitle
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fs(13)
        font.bold: true
        color: Theme.textPrimary
    }

    // 拖动区铺满整行；右上角的按钮浮在它之上、自己吃掉点击
    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton
        onPressed: shell.startMove()
        onDoubleClicked: shell.maximizeOrRestore()
    }

    Row {
        anchors.right: parent.right
        anchors.rightMargin: 4
        anchors.verticalCenter: parent.verticalCenter
        spacing: 2

        ShellIconButton {
            icon: "pin"
            tooltip: "窗口置顶（点击切换开/关）"
            checkable: true
            checked: shell.pinned
            tint: shell.pinned ? Theme.textOnPrimary : Theme.textPrimary
            onClicked: shell.togglePin()
        }
        ShellIconButton {
            icon: "minus"
            tooltip: "最小化"
            onClicked: shell.minimize()
        }
        ShellIconButton {
            icon: shell.maximized ? "restore" : "maximize"
            tooltip: shell.maximized ? "还原" : "最大化"
            onClicked: shell.maximizeOrRestore()
        }
        ShellIconButton {
            icon: "close"
            tooltip: "关闭"
            dangerHover: true
            onClicked: shell.closeWindow()
        }
    }
}
