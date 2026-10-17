import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 「加入效率研究规划」对话框（阶段 4b 收尾）。
 *
 * 研究类型（ME/TE）+ 目标等级，加上 `ResearchCommonFields.qml` 那套公共字段。
 * 业务与取值在桥（`research_plan_bridge.ResearchPlanBridge`）里。
 */

FDialogFrame {
    id: frame

    readonly property var bp: typeof bridge !== "undefined" ? bridge : null
    readonly property int labelWidth: Math.round(88 * Theme.fontScale)

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

    // ── 研究类型 ──
    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spacingSm

        Text {
            Layout.preferredWidth: frame.labelWidth
            horizontalAlignment: Text.AlignRight
            text: qsTr("研究类型:")
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }
        FComboBox {
            objectName: "kindBox"
            Layout.preferredWidth: Math.round(260 * Theme.fontScale)
            model: frame.bp ? frame.bp.kindOptions : []
            currentIndex: frame.bp ? frame.bp.kindIndex : 0
            onActivated: if (frame.bp)
                frame.bp.setKindIndex(currentIndex)
        }
        Item {
            Layout.fillWidth: true
        }
    }

    // ── 目标等级 ──
    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spacingSm

        Text {
            Layout.preferredWidth: frame.labelWidth
            horizontalAlignment: Text.AlignRight
            text: qsTr("目标等级:")
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }
        FSpinBox {
            objectName: "levelBox"
            Layout.preferredWidth: Math.round(140 * Theme.fontScale)
            from: 1
            to: 10
            value: frame.bp ? frame.bp.level : 1
            onValueModified: if (frame.bp)
                frame.bp.setLevel(value)

            HoverHandler {
                id: levelHover
            }
            ToolTip.visible: levelHover.hovered
            ToolTip.text: qsTr("目标等级（ME 0-10 / TE 0-20，本助手按 1-10 计）")
        }
        Item {
            Layout.fillWidth: true
        }
    }

    // ── 当前等级（01-4：研究时长 = 当前→目标的逐级累计；留 0 = 从零研究）──
    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spacingSm

        Text {
            Layout.preferredWidth: frame.labelWidth
            horizontalAlignment: Text.AlignRight
            text: qsTr("当前等级:")
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }
        FSpinBox {
            objectName: "currentLevelBox"
            Layout.preferredWidth: Math.round(140 * Theme.fontScale)
            from: 0
            to: frame.bp ? frame.bp.currentLevelMax : 0
            value: frame.bp ? frame.bp.currentLevel : 0
            onValueModified: if (frame.bp)
                frame.bp.setCurrentLevel(value)

            HoverHandler {
                id: currentLevelHover
            }
            ToolTip.visible: currentLevelHover.hovered
            ToolTip.text: qsTr("绑定蓝图已到的等级；研究时长按「当前 → 目标」逐级累计，留 0 = 从零开始")
        }
        Item {
            Layout.fillWidth: true
        }
    }

    ResearchCommonFields {
        dlg: frame.bp
    }
}
