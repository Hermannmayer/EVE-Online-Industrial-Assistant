import QtQuick
import QtQuick.Layouts
import "../components"

/* 手动添加物品对话框（阶段 4b）。
 *
 * 上半搜索选物品（复用物品搜索那一套：`FPickList` + `ItemSearchBridge`），
 * 下半填数量与成本价。选中物品时按市场价自动带出成本价（原 `_on_row_selected` 的行为）。
 */

FDialogFrame {
    id: frame

    readonly property var ai: typeof bridge !== "undefined" ? bridge : null

    dlg: frame.ai
    acceptText: qsTr("添加")
    acceptEnabled: frame.ai ? frame.ai.hasSelection : false

    FPickList {
        Layout.fillWidth: true
        Layout.fillHeight: true
        source: frame.ai
        columns: frame.ai ? frame.ai.columns : []
        placeholder: qsTr("输入物品名称（中文/英文）...")
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spacingSm

        Text {
            text: qsTr("数量:")
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }

        FSpinBox {
            objectName: "qtyBox"
            Layout.preferredWidth: Math.round(140 * Theme.fontScale)
            from: 1
            to: 2000000000
            value: frame.ai ? frame.ai.quantity : 1
            onValueModified: if (frame.ai)
                frame.ai.setQuantity(value)
        }

        Text {
            text: qsTr("成本价 (ISK):")
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }

        FDoubleSpinBox {
            objectName: "costBox"
            Layout.preferredWidth: Math.round(170 * Theme.fontScale)
            from: 0
            to: 1e12
            decimals: 2
            stepSize: 1000
            value: frame.ai ? frame.ai.cost : 0
            onValueModified: if (frame.ai)
                frame.ai.setCost(value)
        }

        Item {
            Layout.fillWidth: true
        }
    }
}
