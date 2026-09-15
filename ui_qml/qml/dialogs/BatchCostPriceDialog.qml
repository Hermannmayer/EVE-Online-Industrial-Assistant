import QtQuick
import QtQuick.Layouts
import "../components"

/* 批量设置成本价对话框（阶段 4b）。
 *
 * 价格来源 = 吉他卖价 / 买价 / 均价 → 按市场价 × 材料倍率；或「手动输入价格」→ 直接给一个数。
 * 换来源时隐藏/显示对应那一行（原 Widgets 版是 `_on_source_changed` 里逐个 setVisible）。
 *
 * 「材料倍率」与生产规划页工具栏那个是**同一个设置**，点确定时写回（见桥的 `accept`）。
 */

FDialogFrame {
    id: frame

    readonly property var bp: typeof bridge !== "undefined" ? bridge : null

    dlg: frame.bp
    acceptText: qsTr("确定")

    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spacingSm

        Text {
            text: qsTr("价格来源:")
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }

        FComboBox {
            objectName: "sourceBox"
            Layout.preferredWidth: Math.round(180 * Theme.fontScale)
            textRole: "label"
            model: frame.bp ? frame.bp.sources : []
            currentIndex: frame.bp ? frame.bp.sourceIndex : 0
            onActivated: if (frame.bp)
                frame.bp.setSourceIndex(currentIndex)
        }

        Item {
            Layout.fillWidth: true
        }
    }

    RowLayout {
        Layout.fillWidth: true
        visible: frame.bp ? !frame.bp.isManual : true
        spacing: Theme.spacingSm

        Text {
            text: qsTr("材料倍率（× 市场价）:")
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }

        FDoubleSpinBox {
            objectName: "multiplierBox"
            Layout.preferredWidth: Math.round(140 * Theme.fontScale)
            from: frame.bp ? frame.bp.multiplierMin : 0.1
            to: frame.bp ? frame.bp.multiplierMax : 10.0
            decimals: 2
            stepSize: 0.05
            value: frame.bp ? frame.bp.multiplier : 1.0
            onValueModified: if (frame.bp)
                frame.bp.setMultiplier(value)
        }

        Item {
            Layout.fillWidth: true
        }
    }

    RowLayout {
        Layout.fillWidth: true
        visible: frame.bp ? frame.bp.isManual : false
        spacing: Theme.spacingSm

        Text {
            text: qsTr("价格 (ISK):")
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }

        FDoubleSpinBox {
            objectName: "manualBox"
            Layout.preferredWidth: Math.round(170 * Theme.fontScale)
            from: 0
            to: frame.bp ? frame.bp.manualMax : 1e12
            decimals: 2
            stepSize: 1000
            value: frame.bp ? frame.bp.manualPrice : 0
            onValueModified: if (frame.bp)
                frame.bp.setManualPrice(value)
        }

        Item {
            Layout.fillWidth: true
        }
    }

    Text {
        Layout.fillWidth: true
        text: qsTr("材料倍率与生产规划页的「材料倍率」是同一个设置，确定后写回。")
        color: Theme.textSecondary
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(11 * Theme.fontScale)
        wrapMode: Text.WordWrap
    }
}
