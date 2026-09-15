import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 批量查价对话框（阶段 4b）。
 *
 * 粘一批物品名 / ID（每行一个）→ 逐条查市场最新价 → 预览 → 导出 CSV。
 * 取数、千分位格式化、CSV 落盘全在原模块与本桥里，本文件只画。
 *
 * 两处与 Widgets 版不同：
 * - 输入区是多行文本框（原 `QPlainTextEdit`）。组件库里只有单行下划线式的 `FTextField`，
 *   而这里必须能粘贴整列，故就地拼一个 `Flickable + TextArea`（颜色全取 `Theme.*`）。
 * - 末尾多一个「关闭」按钮（原版只有窗口 X / Esc）—— 与已迁移的汇总表、NPC 卖家对话框
 *   一致，关窗语义不变（`reject`，`exec()` 返回值调用方从不读）。
 */

FDialogFrame {
    id: frame

    readonly property var bp: typeof bridge !== "undefined" ? bridge : null

    dlg: frame.bp
    acceptText: qsTr("关闭")
    // 没有「取消」语义：查询是唯一动作，随时可以关窗
    cancelVisible: false

    Text {
        Layout.fillWidth: true
        text: qsTr("输入物品名称或 ID（每行一个，支持粘贴）:")
        color: Theme.textPrimary
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(12 * Theme.fontScale)
    }

    Rectangle {
        Layout.fillWidth: true
        Layout.preferredHeight: Math.round(110 * Theme.fontScale)
        color: Theme.bgSurface
        border.width: 1
        border.color: Theme.border
        radius: Theme.radius

        Flickable {
            id: inputFlick
            anchors.fill: parent
            anchors.margins: Theme.spacingSm
            clip: true
            contentWidth: width
            contentHeight: inputArea.implicitHeight
            boundsBehavior: Flickable.StopAtBounds

            ScrollBar.vertical: ScrollBar {
                policy: ScrollBar.AsNeeded
            }

            // 官方 idiom：多行输入要能滚动就得挂在这层 Flickable 上（TextArea 自己不会滚）。
            // 去掉自带背景（外框由上面的 Rectangle 负责），否则会多出一层方角底板
            TextArea.flickable: TextArea {
                id: inputArea
                objectName: "inputArea"
                placeholderText: qsTr("例如:\n三神裔无畏舰\nTritanium\n10000002\nPlex")
                wrapMode: TextArea.Wrap
                background: null
                color: Theme.textPrimary
                placeholderTextColor: Theme.textSecondary
                selectionColor: Theme.primary
                selectedTextColor: Theme.textOnPrimary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(12 * Theme.fontScale)
                // 只单向推给桥（桥不会回写文本），故不绑 text，免得来回触发
                onTextChanged: if (frame.bp)
                    frame.bp.setInputText(text)
            }
        }
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spacingSm

        FButton {
            objectName: "queryButton"
            text: qsTr("查询")
            primary: true
            enabled: frame.bp ? !frame.bp.busy : false
            onClicked: if (frame.bp)
                frame.bp.query()
        }

        Item {
            Layout.fillWidth: true
        }

        FButton {
            objectName: "exportButton"
            text: qsTr("导出 CSV")
            enabled: frame.bp ? frame.bp.exportEnabled : false
            onClicked: if (frame.bp)
                frame.bp.exportCsv()
        }
    }

    // 原版是 3px 细进度条（无文字）。`FSummaryTable` 之下不再有别的组件，就地画一条
    Rectangle {
        objectName: "progressBar"
        Layout.fillWidth: true
        Layout.preferredHeight: 3
        visible: frame.bp ? frame.bp.progressVisible : false
        color: Theme.bgSurface

        Rectangle {
            height: parent.height
            radius: 1
            color: Theme.primary
            width: frame.bp && frame.bp.progressTotal > 0
                   ? parent.width * (frame.bp.progressCurrent / frame.bp.progressTotal)
                   : 0
        }
    }

    FSummaryTable {
        objectName: "priceTable"
        Layout.fillWidth: true
        Layout.fillHeight: true
        columns: frame.bp ? frame.bp.columns : []
        rows: frame.bp ? frame.bp.rows : []
        // 空态交给状态行（与 NPC 卖家对话框同口径），免得两头都说「没有数据」
        emptyText: ""
    }

    Text {
        objectName: "statusLabel"
        Layout.fillWidth: true
        text: frame.bp ? frame.bp.statusText : ""
        color: Theme.textSecondary
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(11 * Theme.fontScale)
        wrapMode: Text.WordWrap
    }
}
