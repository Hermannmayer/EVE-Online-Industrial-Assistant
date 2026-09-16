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

    /* 左内边距由 `Main.qml` 传进来（和工具行左侧控件组、导航栏 logo 同一条竖线）。
       写死 12 的话，哪天主工具栏换了内缩，标题就会和下面的字错开一格。 */
    property int leftInset: 12

    Text {
        anchors.left: parent.left
        anchors.leftMargin: root.leftInset
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
            icon: shell.iconFile("pin")
            tooltip: "窗口置顶（点击切换开/关）"
            checkable: true
            checked: shell.pinned
            tint: shell.pinned ? Theme.textOnPrimary : Theme.textPrimary
            onClicked: shell.togglePin()
        }
        ShellIconButton {
            icon: shell.iconFile("minus")
            tooltip: "最小化"
            onClicked: shell.minimize()
        }
        ShellIconButton {
            icon: shell.iconFile(shell.maximized ? "restore" : "maximize")
            tooltip: shell.maximized ? "还原" : "最大化"
            onClicked: shell.maximizeOrRestore()
        }
        ShellIconButton {
            icon: shell.iconFile("close")
            tooltip: "关闭"
            dangerHover: true
            onClicked: shell.closeWindow()
        }
    }
}
