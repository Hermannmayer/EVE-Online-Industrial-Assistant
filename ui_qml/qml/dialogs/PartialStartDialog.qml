import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 部分启动（阶段 4）。
 *
 * 窗口行为在 `QmlDialog` 那一层；这里只用 `FDialogFrame` 排主体 + 按钮。
 * 业务与取值都在 `bridge`（`partial_start_bridge.py`）。
 */

FDialogFrame {
    id: frame

    readonly property var ps: typeof bridge !== "undefined" ? bridge : null

    dlg: frame.ps
    acceptText: qsTr("启动")

    Text {
        Layout.fillWidth: true
        text: frame.ps ? frame.ps.tipText : ""
        color: Theme.textPrimary
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(13 * Theme.fontScale)
        wrapMode: Text.WordWrap
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spacingSm

        Text {
            text: qsTr("启动条数:")
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }
        FSpinBox {
            Layout.preferredWidth: 140
            from: 1
            to: frame.ps ? frame.ps.maxLines : 1
            value: frame.ps ? frame.ps.lines : 1
            onValueModified: if (frame.ps)
                frame.ps.setLines(value)
        }
        Item {
            Layout.fillWidth: true
        }
    }

    Text {
        Layout.fillWidth: true
        text: frame.ps ? frame.ps.summaryText : ""
        color: Theme.textSecondary
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(11 * Theme.fontScale)
        wrapMode: Text.WordWrap
    }
}
