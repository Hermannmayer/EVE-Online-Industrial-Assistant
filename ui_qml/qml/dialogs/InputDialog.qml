import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 取值对话框（阶段 4b）—— `QInputDialog` 的 QML 替代。
 *
 * 五种形态共用一个文件，由桥的 `mode` 决定显示哪个输入控件：
 *   text / multiline（多行） / int / double / choice（下拉单选）
 *
 * 排版复用 `FDialogFrame`（主体 + 校验提示 + 取消/确定），输入控件全部用现成的
 * `FTextField` / `FSpinBox` / `FDoubleSpinBox` / `FComboBox`，本文件只负责按 mode 切换。
 * 只有 `multiline` 没有现成组件，就地拼了一个 `Flickable + TextArea`（见下）。
 */

FDialogFrame {
    id: frame

    readonly property var inp: typeof bridge !== "undefined" ? bridge : null
    readonly property string mode: frame.inp ? frame.inp.mode : "text"

    dlg: frame.inp
    acceptText: qsTr("确定")

    Text {
        Layout.fillWidth: true
        text: frame.inp ? frame.inp.label : ""
        color: Theme.textPrimary
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(12 * Theme.fontScale)
        wrapMode: Text.WordWrap
    }

    FTextField {
        id: textField
        objectName: "inputText"
        Layout.fillWidth: true
        visible: frame.mode === "text"
        // 回写时加不等值判断：不加就是「设 text → textChanged → setText → 属性变 → 重绑」的循环
        onTextChanged: if (frame.inp && text !== frame.inp.text)
            frame.inp.setText(text)
        Component.onCompleted: {
            if (frame.inp)
                text = frame.inp.text;
            forceActiveFocus();
        }
    }

    FSpinBox {
        objectName: "inputInt"
        Layout.fillWidth: true
        visible: frame.mode === "int"
        from: frame.inp ? Math.round(frame.inp.minimum) : 0
        to: frame.inp ? Math.round(frame.inp.maximum) : 100
        value: frame.inp ? Math.round(frame.inp.value) : 0
        // valueModified 只在用户操作时发（程序化赋值不发），所以不会与上面的绑定打环
        onValueModified: if (frame.inp)
            frame.inp.setValue(value)
    }

    FDoubleSpinBox {
        objectName: "inputDouble"
        Layout.fillWidth: true
        visible: frame.mode === "double"
        from: frame.inp ? frame.inp.minimum : 0
        to: frame.inp ? frame.inp.maximum : 100
        decimals: frame.inp ? frame.inp.decimals : 1
        value: frame.inp ? frame.inp.value : 0
        onValueModified: if (frame.inp)
            frame.inp.setValue(value)
    }

    FComboBox {
        objectName: "inputChoice"
        Layout.fillWidth: true
        visible: frame.mode === "choice"
        model: frame.inp ? frame.inp.choices : []
        currentIndex: frame.inp ? frame.inp.choiceIndex : 0
        onActivated: if (frame.inp)
            frame.inp.setChoiceIndex(currentIndex)
    }

    /* 多行文本（`MODE_MULTILINE`，对齐 `QInputDialog.getMultiLineText`）。
     *
     * 组件库里只有单行下划线式的 `FTextField`，所以照 `BatchPriceDialog` 的做法
     * 就地拼一个 `Flickable + TextArea`（颜色全取 `Theme.*`，外框自绘）。
     * 高度给死：对话框本身是固定尺寸的，`Layout.fillHeight` 会让它随窗口拉伸。
     */
    Rectangle {
        objectName: "inputMultiline"
        Layout.fillWidth: true
        Layout.preferredHeight: Math.round(120 * Theme.fontScale)
        visible: frame.mode === "multiline"
        color: Theme.bgSurface
        border.width: 1
        border.color: Theme.border
        radius: Theme.radius

        Flickable {
            anchors.fill: parent
            anchors.margins: Theme.spacingSm
            clip: true
            contentWidth: width
            contentHeight: multilineArea.implicitHeight
            boundsBehavior: Flickable.StopAtBounds

            ScrollBar.vertical: ScrollBar {
                policy: ScrollBar.AsNeeded
            }

            // 官方 idiom：多行输入要能滚动就得挂在这层 Flickable 上（TextArea 自己不会滚）。
            // 去掉自带背景（外框由上面的 Rectangle 负责），否则会多出一层方角底板。
            TextArea.flickable: TextArea {
                id: multilineArea
                objectName: "inputMultilineArea"
                wrapMode: TextArea.Wrap
                background: null
                color: Theme.textPrimary
                selectionColor: Theme.primary
                selectedTextColor: Theme.textOnPrimary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(12 * Theme.fontScale)
                // 与单行那个同一条护栏：回写时加不等值判断，否则
                // 「设 text → textChanged → setText → 属性变 → 重绑」会成环
                onTextChanged: if (frame.inp && text !== frame.inp.text)
                    frame.inp.setText(text)
                Component.onCompleted: {
                    if (frame.inp)
                        text = frame.inp.text;
                    forceActiveFocus();
                }
            }
        }
    }
}
