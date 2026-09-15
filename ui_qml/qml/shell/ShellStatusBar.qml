import QtQuick

/* 状态栏（阶段 5 批次 6.1）—— 对应 Widgets 版 `QStatusBar` + `_status_label` + `_update_progress`。

   `shell.progressMaximum == 0` 走不确定态（原版 `QProgressBar.setRange(0, 0)`），
   与 `_update_progress` 的用法一致。
*/
Item {
    id: root

    implicitHeight: 24

    Text {
        anchors.left: parent.left
        anchors.leftMargin: 10
        anchors.right: progressBar.left
        anchors.rightMargin: 8
        anchors.verticalCenter: parent.verticalCenter
        text: shell.statusText
        elide: Text.ElideRight
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fs(11)
        color: Theme.textSecondary
    }

    Rectangle {
        id: progressBar
        anchors.right: parent.right
        anchors.rightMargin: 10
        anchors.verticalCenter: parent.verticalCenter
        width: 160
        height: 16
        radius: 2
        visible: shell.progressVisible
        color: Theme.bgSurfaceLight
        border.color: Theme.border
        border.width: 1
        clip: true

        Rectangle {
            id: progressFill
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            visible: !progressBar.indeterminate
            width: progressBar.indeterminate ? parent.width
                 : parent.width * Math.max(0, Math.min(1, shell.progressValue / Math.max(1, shell.progressMaximum)))
            color: Theme.primary
        }

        // 不确定态：一条来回跑的条（原版 setRange(0,0) 的视觉等价物）
        readonly property bool indeterminate: shell.progressMaximum <= 0
        Rectangle {
            visible: progressBar.indeterminate
            width: progressBar.width * 0.35
            height: parent.height
            color: Theme.primary
            SequentialAnimation on x {
                running: progressBar.indeterminate && progressBar.visible
                loops: Animation.Infinite
                NumberAnimation { from: -progressBar.width * 0.35; to: progressBar.width; duration: 1100; easing.type: Easing.InOutQuad }
            }
        }
    }
}
