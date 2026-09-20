import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 发明结果回填（阶段 4）。
 *
 * 期望值只适合事前估算，这里让用户按游戏实际结果回填 —— 三个完成入口
 * （计划表单行 / 工业页批量下线 / 采购页一键完成）都经 `plan_execution.complete_plan`，
 * 未回填时它返回 `code='need_outcome'` 拒绝静默完成，由调用方弹本对话框。
 */

FDialogFrame {
    id: frame

    readonly property var inv: typeof bridge !== "undefined" ? bridge : null

    dlg: frame.inv
    acceptText: qsTr("确认并完成")

    // ── 只读信息行 ──
    Repeater {
        model: frame.inv ? frame.inv.rows : []

        RowLayout {
            required property var modelData
            Layout.fillWidth: true
            spacing: Theme.spacingSm

            Text {
                Layout.preferredWidth: Math.round(96 * Theme.fontScale)
                horizontalAlignment: Text.AlignRight
                text: modelData.label
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(12 * Theme.fontScale)
            }
            Text {
                Layout.fillWidth: true
                text: modelData.value
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(12 * Theme.fontScale)
                elide: Text.ElideRight
            }
        }
    }

    // ── 实际结果：成功几条产线（实际流程数由桥换算，只读展示）──
    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spacingSm

        Text {
            Layout.preferredWidth: Math.round(96 * Theme.fontScale)
            horizontalAlignment: Text.AlignRight
            text: qsTr("成功产线数:")
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }
        FSpinBox {
            objectName: "successBox"
            Layout.preferredWidth: 120
            from: 0
            // 一条产线最多成功一次 → 上限就是本计划的尝试次数
            to: frame.inv && frame.inv.attempts > 0 ? frame.inv.attempts : 1000000
            value: frame.inv ? frame.inv.successes : 0
            onValueModified: if (frame.inv)
                frame.inv.setSuccesses(value)

            HoverHandler {
                id: runsHover
            }
            ToolTip.visible: runsHover.hovered
            ToolTip.text: qsTr("按游戏里实际成功的产线条数填写（上限 = 本计划尝试次数）；一条都没成功就填 0")
        }

        Text {
            text: frame.inv ? qsTr("= %1 流程").arg(frame.inv.actualRuns) : ""
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }

        FButton {
            text: qsTr("发明失败")
            onClicked: if (frame.inv)
                frame.inv.markFailed()

            HoverHandler {
                id: failHover
            }
            ToolTip.visible: failHover.hovered
            ToolTip.text: qsTr("把成功数置 0（材料与输入蓝图流程已被消耗，这是游戏事实）")
        }

        Item {
            Layout.fillWidth: true
        }
    }

    // ── 提示（失败 / 与期望差太多 / 正常）──
    Text {
        Layout.fillWidth: true
        text: frame.inv ? frame.inv.hintText : ""
        color: Theme.accentYellow
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(12 * Theme.fontScale)
        wrapMode: Text.WordWrap
    }
}
