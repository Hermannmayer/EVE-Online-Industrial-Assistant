import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 「加入发明规划」对话框（阶段 4b 收尾）。
 *
 * 产物选择 + 解码器 + 预期成功率 + 流程数×并行数 + 预期结果，加上 `ResearchCommonFields.qml` 那套公共字段。
 * 业务与取值在桥（`research_plan_bridge.InventionPlanBridge`）里。
 *
 * 预期成功率随产物/解码器变化由**桥**重算（对齐原 `_refresh_probability`），
 * 所以这里不写 `value:` 绑定，改用 `Connections` 在桥变化时把值推回来 ——
 * 微调框一旦被用户改过，声明式绑定就断了，反过来再算就推不回来。
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

    // ── 产物说明（只读）──
    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spacingSm

        Text {
            Layout.preferredWidth: frame.labelWidth
            horizontalAlignment: Text.AlignRight
            text: qsTr("产物:")
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }
        Text {
            Layout.fillWidth: true
            text: frame.bp ? frame.bp.outcomeSummary : ""
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
            wrapMode: Text.WordWrap
        }
    }

    // ── 发明产物 ──
    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spacingSm

        Text {
            Layout.preferredWidth: frame.labelWidth
            horizontalAlignment: Text.AlignRight
            text: qsTr("发明产物:")
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }
        FComboBox {
            objectName: "outcomeBox"
            Layout.fillWidth: true
            model: frame.bp ? frame.bp.outcomeLabels : []
            currentIndex: frame.bp ? frame.bp.outcomeIndex : 0
            onActivated: if (frame.bp)
                frame.bp.setOutcomeIndex(currentIndex)
        }
    }

    // ── 解码器 ──
    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spacingSm

        Text {
            Layout.preferredWidth: frame.labelWidth
            horizontalAlignment: Text.AlignRight
            text: qsTr("解码器:")
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }
        FComboBox {
            objectName: "decryptorBox"
            Layout.fillWidth: true
            model: frame.bp ? frame.bp.decryptorLabels : []
            currentIndex: frame.bp ? frame.bp.decryptorIndex : 0
            onActivated: if (frame.bp)
                frame.bp.setDecryptorIndex(currentIndex)
        }
    }

    // ── 预期成功率 ──
    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spacingSm

        Text {
            Layout.preferredWidth: frame.labelWidth
            horizontalAlignment: Text.AlignRight
            text: qsTr("预期成功率:")
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }
        FDoubleSpinBox {
            id: rateBox
            objectName: "rateBox"
            Layout.preferredWidth: Math.round(140 * Theme.fontScale)
            from: 0.01
            to: 100.0
            decimals: 1
            stepSize: 0.1
            onValueModified: if (frame.bp)
                frame.bp.setRate(value)

            Connections {
                target: frame.bp
                enabled: frame.bp !== null

                function onInventionChanged() {
                    if (rateBox.value !== frame.bp.rate)
                        rateBox.value = frame.bp.rate;
                }
            }
        }
        Text {
            text: "%"
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }
        Item {
            Layout.fillWidth: true
        }
    }

    // ── 成功率提示 ──
    Text {
        Layout.fillWidth: true
        text: frame.bp ? frame.bp.rateHint : ""
        color: Theme.textSecondary
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(12 * Theme.fontScale)
        wrapMode: Text.WordWrap
    }

    // ── 流程数 × 并行数（与制造同一口径：总尝试 = 每线尝试次数 × 并行作业数）──
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
            Layout.preferredWidth: Math.round(88 * Theme.fontScale)
            from: 1
            to: 10000
            value: frame.bp ? frame.bp.attempts : 1
            onValueModified: if (frame.bp)
                frame.bp.setAttempts(value)

            HoverHandler {
                id: runsHover
            }
            ToolTip.visible: runsHover.hovered
            ToolTip.text: qsTr("每条并行产线要跑几次发明尝试（每次消耗 1 个输入 BPC 流程 + 一份数据核心）")
        }
        Text {
            text: qsTr("×")
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }
        FSpinBox {
            objectName: "parBox"
            Layout.preferredWidth: Math.round(88 * Theme.fontScale)
            from: 1
            to: 100
            value: frame.bp ? frame.bp.parallels : 1
            onValueModified: if (frame.bp)
                frame.bp.setParallels(value)

            HoverHandler {
                id: parHover
            }
            ToolTip.visible: parHover.hovered
            ToolTip.text: qsTr("并行作业数（需要同样多的输入 BPC，每张流程数不少于每线尝试次数）")
        }
        Text {
            text: qsTr("并行")
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }
        Item {
            Layout.fillWidth: true
        }
    }

    // ── 预期结果 ──
    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spacingSm

        Text {
            Layout.preferredWidth: frame.labelWidth
            Layout.alignment: Qt.AlignTop
            horizontalAlignment: Text.AlignRight
            text: qsTr("预期结果:")
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }
        Text {
            objectName: "expectedSummary"
            Layout.fillWidth: true
            text: frame.bp ? frame.bp.expectedSummary : ""
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
            wrapMode: Text.WordWrap
            lineHeight: 1.35
        }
    }

    ResearchCommonFields {
        dlg: frame.bp
    }

    Component.onCompleted: if (frame.bp)
        rateBox.value = frame.bp.rate
}
