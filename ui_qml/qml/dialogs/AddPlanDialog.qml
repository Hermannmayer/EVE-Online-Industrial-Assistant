import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 「加入制造计划」对话框（阶段 4b 收尾）。
 *
 * 对照 Widgets 版 `ui_pyside6/dialogs/industry_dialogs.py` 的 `AddPlanDialog`。
 * 取值为 `{runs, parallels, me, te, char}`，落在桥
 * （`industry_dialogs_bridge.AddPlanBridge`）里。角色行与科研三框共用 `CharField`。
 *
 * 「设施」输入框已移除：它是纯展示标签，不参与任何数值计算，且落库时为空会自动
 * 回填材料机库名（见 `services/plan_service.py` 的 facility 回填）。
 */

FDialogFrame {
    id: frame

    readonly property var bp: typeof bridge !== "undefined" ? bridge : null
    readonly property int labelWidth: Math.round(88 * Theme.fontScale)

    dlg: frame.bp

    // ── 物品（只读）──
    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spacingSm

        Text {
            Layout.preferredWidth: frame.labelWidth
            horizontalAlignment: Text.AlignRight
            text: qsTr("物品:")
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }
        Text {
            Layout.fillWidth: true
            text: frame.bp ? frame.bp.productName : ""
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
            elide: Text.ElideRight
            textFormat: Text.PlainText
        }
    }

    // ── 评分摘要（只读）──
    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spacingSm

        Text {
            Layout.preferredWidth: frame.labelWidth
            horizontalAlignment: Text.AlignRight
            text: qsTr("评分:")
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }
        Text {
            Layout.fillWidth: true
            text: frame.bp ? frame.bp.scoreLabel : ""
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
            elide: Text.ElideRight
            textFormat: Text.PlainText
        }
    }

    // ── 流程数 ──
    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spacingSm

        Text {
            Layout.preferredWidth: frame.labelWidth
            horizontalAlignment: Text.AlignRight
            text: qsTr("流程数:")
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }
        FSpinBox {
            objectName: "runsBox"
            Layout.preferredWidth: Math.round(140 * Theme.fontScale)
            from: 1
            to: 10000
            value: frame.bp ? frame.bp.runs : 1
            onValueModified: if (frame.bp)
                frame.bp.setRuns(value)
        }
        Item {
            Layout.fillWidth: true
        }
    }

    // ── 并行数 ──
    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spacingSm

        Text {
            Layout.preferredWidth: frame.labelWidth
            horizontalAlignment: Text.AlignRight
            text: qsTr("并行数:")
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }
        FSpinBox {
            objectName: "parBox"
            Layout.preferredWidth: Math.round(140 * Theme.fontScale)
            from: 1
            to: 100
            value: frame.bp ? frame.bp.parallels : 1
            onValueModified: if (frame.bp)
                frame.bp.setParallels(value)
        }
        Item {
            Layout.fillWidth: true
        }
    }

    // ── 蓝图参数：ME / TE 挤在一行（与原版一致）──
    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spacingSm

        Text {
            Layout.preferredWidth: frame.labelWidth
            horizontalAlignment: Text.AlignRight
            text: qsTr("蓝图参数:")
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }
        Text {
            text: qsTr("材料效率(ME):")
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }
        FSpinBox {
            objectName: "meBox"
            Layout.preferredWidth: Math.round(90 * Theme.fontScale)
            from: 0
            to: 10
            value: frame.bp ? frame.bp.me : 0
            onValueModified: if (frame.bp)
                frame.bp.setMe(value)

            HoverHandler {
                id: meHover
            }
            ToolTip.visible: meHover.hovered
            ToolTip.text: qsTr("材料效率等级（0-10）")
        }
        Text {
            text: qsTr("时间效率(TE):")
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }
        FSpinBox {
            objectName: "teBox"
            Layout.preferredWidth: Math.round(90 * Theme.fontScale)
            from: 0
            to: 20
            value: frame.bp ? frame.bp.te : 0
            onValueModified: if (frame.bp)
                frame.bp.setTe(value)

            HoverHandler {
                id: teHover
            }
            ToolTip.visible: teHover.hovered
            ToolTip.text: qsTr("时间效率等级（0-20）")
        }
        Item {
            Layout.fillWidth: true
        }
    }

    CharField {
        dlg: frame.bp
        labelWidth: frame.labelWidth
        boxWidth: Math.round(220 * Theme.fontScale)
    }
}
