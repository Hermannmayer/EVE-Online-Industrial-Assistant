import QtQuick
import QtQuick.Layouts

/* 一列「标签: 值」结果行 —— 贸易页两个 Tab 的评分 / 利润卡片共用。
 *
 * 展示规则（哪个值标红加粗、用哪个语义色）**留在 Python 侧**：
 * 桥直接给出 `{label, value, color, strong}`，这里只负责画。
 *
 * 字号一律写 `Math.round(N * Theme.fontScale)`：`Theme.fs()` 是 Slot 调用，
 * QML 不追踪它内部的属性读取，改全局字号后不会重算。
 */
ColumnLayout {
    id: root

    property var fields: []

    spacing: Theme.spacingXs

    Repeater {
        model: root.fields

        RowLayout {
            required property var modelData

            Layout.fillWidth: true
            spacing: Theme.spacingSm

            Text {
                Layout.preferredWidth: Math.round(88 * Theme.fontScale)
                text: modelData.label
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(12 * Theme.fontScale)
                elide: Text.ElideRight
            }

            Text {
                Layout.fillWidth: true
                text: modelData.value
                color: modelData.color || Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(12 * Theme.fontScale)
                font.bold: modelData.strong === true
            }
        }
    }
}
