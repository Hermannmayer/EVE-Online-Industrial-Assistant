import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/* 单行价格来源设置：<标签> [Hub▾] [价格类型▾] [倍率]。
 *
 * 材料行与成品行各一个实例，标签不同。原实现是 `price_source_widget.py`
 * 的 `PriceSourceRow`（阶段 2b 删除）。
 *
 * **不使用属性绑定同步状态**：`hub`/`priceType`/`mult` 是「入参」，
 * 用 `applySettings()` 赋值即可；若写成 `currentIndex: model.indexOf(root.hub)`
 * 这类绑定，用户在界面上的选择会被绑定立刻冲回去（切不动的经典表现）。
 * 用户改动走 `activated` / `valueModified`，只在这两个信号里对外汇报。
 */
RowLayout {
    id: root

    property string label: ""
    property var hubs: []
    property var priceTypes: []
    property string hub: ""
    property string priceType: "sell"
    property real mult: 1.0

    signal hubEdited(string value)
    signal priceTypeEdited(string value)
    signal multEdited(real value)

    spacing: Theme.spacingXs

    function applySettings(hubValue: string, typeValue: string, multValue: real): void {
        var hi = root.hubs.indexOf(hubValue)
        if (hi >= 0 && hi !== hubCombo.currentIndex)
            hubCombo.currentIndex = hi
        var ti = 0
        for (var i = 0; i < root.priceTypes.length; ++i) {
            if (root.priceTypes[i].value === typeValue) {
                ti = i
                break
            }
        }
        if (ti !== typeCombo.currentIndex)
            typeCombo.currentIndex = ti
        if (Math.abs(multSpin.value - multValue) > 0.0001)
            multSpin.value = multValue
    }

    Text {
        text: root.label
        color: Theme.textPrimary
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(12 * Theme.fontScale)
        font.bold: true
    }

    FComboBox {
        id: hubCombo
        model: root.hubs
        implicitWidth: Math.max(80, maxItemWidth + 2 * Theme.spacingLg)
        onActivated: root.hubEdited(currentText)
    }

    FComboBox {
        id: typeCombo
        model: root.priceTypes
        textRole: "label"
        implicitWidth: Math.max(72, maxItemWidth + 2 * Theme.spacingLg)
        onActivated: root.priceTypeEdited(root.priceTypes[currentIndex].value)
    }

    FDoubleSpinBox {
        id: multSpin
        from: 0.1
        to: 10.0
        stepSize: 0.05
        decimals: 2
        implicitWidth: 84
        onValueModified: root.multEdited(value)
    }
}
