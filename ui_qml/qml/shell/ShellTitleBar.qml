import QtQuick

/* 标题行（阶段 5 批次 6.1）—— Widgets 版是 `ui_pyside6/title_bar.py`。

   空区可拖动、双击最大化。拖动**不直接** `startSystemMove()`，而是把屏幕坐标交给
   Python 判一次（`shell.beginMove(globalX, globalY)`）：最大化时系统拖动循环不会自动
   「还原成最大化前的尺寸再跟手」（那是原生标题栏的行为，`startSystemMove` 绕开了它），
   由 Python 判超阈值后先还原再起拖，见 `ShellWindowBridge.beginMove`。

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
        id: dragArea
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton
        property real pressX: 0
        property real pressY: 0
        onPressed: (mouse) => {
            // 新的一次按下：先复位 Python 侧的交棒标记（上一次拖动结束后它还是置位的）
            shell.endMove();
            /* `mouse.x/y` 是相对本 MouseArea 的坐标；拖动区从窗口原点铺满整行，
               所以它就等于窗口内坐标 —— Python 那边用它算「光标在窗口的哪个横向比例」。
               **不要用 `mouse.scenePosition`**：本机 Qt 6.11 上它是 undefined，
               取 `.x` 会抛 TypeError，`shell.beginMove` 那一行整个不执行，
               表现成「按住标题栏完全拖不动」。 */
            dragArea.pressX = mouse.x;
            dragArea.pressY = mouse.y;
        }
        onPositionChanged: (mouse) => {
            if (!pressed)
                return;
            // 阈值判定、以及「同一次按下只起拖一次」的守卫都在 Python（`ShellWindow.begin_move`）：
            // 系统拖动循环已经跑起来之后再调一次 `startSystemMove()`，其中的 `ReleaseCapture()`
            // 会把循环掐断。返回 true 表示已交棒。
            shell.beginMove(dragArea.pressX, dragArea.pressY, mouse.x, mouse.y);
        }
        onReleased: shell.endMove()
        onCanceled: shell.endMove()
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
