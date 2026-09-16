import QtQuick
import QtQuick.Layouts

/* 消息对话框（批次 7.1）—— `QMessageBox` 的 QML 替代。
 *
 * 排版复用 `FDialogFrame`（主体 + 校验提示 + 取消/确定按钮行）。
 * 桥是 `MessageBridge`：正文、种类（决定徽标颜色）、要不要「取消」按钮。
 *
 * 按钮文案随种类变：普通消息只有「确定」；`question` 是「是 / 否」，
 * 对齐原版 `StandardButton.Yes | No` 的两个选项。
 *
 * 颜色一律取自 `Theme`（铁律），本文件不写任何色值。
 */
FDialogFrame {
    id: frame

    readonly property var msg: typeof bridge !== "undefined" ? bridge : null
    readonly property string kind: frame.msg ? frame.msg.kind : "info"
    readonly property bool isQuestion: frame.kind === "question"

    dlg: frame.msg
    acceptText: frame.isQuestion ? qsTr("是") : qsTr("确定")
    cancelText: qsTr("否")
    // 危险确认（原版 `defaultButton=No`）焦点落在「否」，回车不误放行
    defaultReject: frame.msg ? frame.msg.defaultReject : false

    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spacingMd

        // 徽标：圆底 + 单个字符。不引新资源，也不依赖图标 provider（对话框引擎里未必注册）。
        Rectangle {
            Layout.alignment: Qt.AlignTop
            implicitWidth: 22
            implicitHeight: 22
            radius: width / 2
            color: frame.kind === "warn" ? Theme.accentOrange : frame.kind === "question" ? Theme.primary : Theme.accentCyan

            Text {
                anchors.centerIn: parent
                text: frame.kind === "warn" ? "!" : frame.kind === "question" ? "?" : "i"
                color: Theme.textOnPrimary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(14 * Theme.fontScale)
                font.weight: Font.Bold
            }
        }

        Text {
            Layout.fillWidth: true
            text: frame.msg ? frame.msg.title : ""
            color: Theme.textBright
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(14 * Theme.fontScale)
            font.weight: Font.DemiBold
            wrapMode: Text.WordWrap
        }
    }

    Text {
        Layout.fillWidth: true
        Layout.fillHeight: true
        text: frame.msg ? frame.msg.text : ""
        color: Theme.textPrimary
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(12 * Theme.fontScale)
        wrapMode: Text.WordWrap
    }
}
