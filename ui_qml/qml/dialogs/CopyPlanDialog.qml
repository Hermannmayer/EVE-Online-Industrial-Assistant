import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 「加入拷贝规划」对话框（阶段 4b 收尾）。
 *
 * 承载在 `ui_qml/dialog_host.QmlDialog` 里，内容用 FDialogFrame 统一排版；
 * 业务与取值都在桥（`research_plan_bridge.CopyPlanBridge`）里。
 * 角色/机库/设施那四行抽在 `ResearchCommonFields.qml`（三张科研框共用）。
 */

FDialogFrame {
    id: frame

    readonly property var bp: typeof bridge !== "undefined" ? bridge : null
    readonly property int labelWidth: Math.round(88 * Theme.fontScale)
    readonly property int boxWidth: Math.round(140 * Theme.fontScale)

    dlg: frame.bp
    acceptText: qsTr("加入规划")

    // ── 蓝图（只读）──
    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spacingSm

        Text {
            Layout.preferredWidth: frame.labelWidth
            horizontalAlignment: Text.AlignRight
            text: qsTr("蓝图:")
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }
        Text {
            Layout.fillWidth: true
            text: frame.bp ? frame.bp.blueprintName : ""
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
            elide: Text.ElideRight
            textFormat: Text.PlainText
        }
    }

    // ── 产出份数 ──
    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spacingSm

        Text {
            Layout.preferredWidth: frame.labelWidth
            horizontalAlignment: Text.AlignRight
            text: qsTr("产出份数:")
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }
        FSpinBox {
            objectName: "copiesBox"
            Layout.preferredWidth: frame.boxWidth
            from: 1
            to: 1000
            value: frame.bp ? frame.bp.copies : 1
            onValueModified: if (frame.bp)
                frame.bp.setCopies(value)
        }
        Item {
            Layout.fillWidth: true
        }
    }

    // ── 每份流程 ──
    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spacingSm

        Text {
            Layout.preferredWidth: frame.labelWidth
            horizontalAlignment: Text.AlignRight
            text: qsTr("每份流程:")
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }
        FSpinBox {
            id: runsBox
            objectName: "runsBox"
            Layout.preferredWidth: frame.boxWidth
            from: 1
            to: frame.bp ? frame.bp.runsLimit : 1
            value: frame.bp ? frame.bp.runsPerCopy : 1
            onValueModified: if (frame.bp)
                frame.bp.setRunsPerCopy(value)

            HoverHandler {
                id: runsHover
            }
            ToolTip.visible: runsHover.hovered
            ToolTip.text: qsTr("每份 BPC 的授权生产流程数，上限 %1（蓝图拷贝上限）").arg(frame.bp ? frame.bp.runsLimit : 1)
        }
        Text {
            text: qsTr("/ 上限 %1").arg(frame.bp ? frame.bp.runsLimit : 0)
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }
        Item {
            Layout.fillWidth: true
        }
    }

    ResearchCommonFields {
        dlg: frame.bp
    }
}
