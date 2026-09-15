import QtQuick
import QtQuick.Layouts

/* 对话框内容的统一骨架（阶段 4）。
 *
 * 窗口行为（模态/居中/Esc/标题栏）由 `ui_qml/dialog_host.QmlDialog` 那一层负责，
 * 这里只统一**内容**的排版：主体区（默认属性）+ 校验提示 + 取消/确定按钮行。
 * 这样每个对话框的 QML 只写自己的字段，不必重复这 20 行。
 *
 * 用法：
 *     FDialogFrame {
 *         dlg: bridge
 *         acceptText: qsTr("启动")
 *         Text { text: "..." }      // 直接写主体，会进 body
 *     }
 */
ColumnLayout {
    id: root

    default property alias bodyData: body.data

    //: 对话框桥（`DialogBridge` 子类）—— 按钮与校验提示都从它取
    property var dlg: null
    property string acceptText: qsTr("确定")
    property string cancelText: qsTr("取消")
    property bool acceptVisible: true
    property bool acceptEnabled: true
    property bool cancelVisible: true

    /* 可选的第三个按钮（默认不显示）。
     * 只有「系统设置」这类**改了不关窗**的对话框需要它（原版是 QDialogButtonBox 的 Apply）；
     * 默认关着，所以其余对话框的按钮行与从前逐像素一致。
     * 放在取消/确定左侧：右对齐的「取消 · 确定」是这里既有的形状，插到中间会把主次打乱。*/
    property bool applyVisible: false
    property string applyText: qsTr("应用")

    signal applyRequested()

    anchors.fill: parent
    anchors.margins: Theme.spacingMd
    spacing: Theme.spacingSm

    ColumnLayout {
        id: body
        Layout.fillWidth: true
        Layout.fillHeight: true
        spacing: Theme.spacingSm
    }

    // 校验提示：桥里 `set_error()` 非空即显示（对齐 Widgets 版的 QMessageBox 拦截）
    Text {
        Layout.fillWidth: true
        visible: root.dlg ? root.dlg.error !== "" : false
        text: root.dlg ? root.dlg.error : ""
        color: Theme.accentRed
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(12 * Theme.fontScale)
        wrapMode: Text.WordWrap
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spacingSm

        Item {
            Layout.fillWidth: true
        }

        FButton {
            text: root.applyText
            visible: root.applyVisible
            onClicked: root.applyRequested()
        }

        FButton {
            text: root.cancelText
            visible: root.cancelVisible
            onClicked: if (root.dlg)
                root.dlg.reject()
        }

        FButton {
            text: root.acceptText
            primary: true
            visible: root.acceptVisible
            enabled: root.acceptEnabled
            onClicked: if (root.dlg)
                root.dlg.accept()
        }
    }
}
