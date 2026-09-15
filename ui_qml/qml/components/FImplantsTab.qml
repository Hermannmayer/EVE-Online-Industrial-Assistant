import QtQuick
import QtQuick.Layouts

/* 人物设置「增效体」Tab —— 三个插槽下拉（对齐 `char_settings_pages.ImplantsPage`）。
 *
 * `source`（`ImplantsBridge`）的契约：
 *   slots  [{title, options:[{label, typeId, bonusDesc}], index}]   options[0] 恒为「-- 无 --」
 *   setSlotIndex(slot, index)
 *
 * 加成那行**不经过桥**：选项是静态的，直接由下拉的当前下标在本地取 `bonusDesc`。
 * 原版之所以要接 `currentIndexChanged` 回写，是因为 Widgets 的 QLabel 不会自己重算；
 * QML 里能被绑定，多一次往返反而会让「刚选完就重建下拉」。
 */

ColumnLayout {
    id: root

    property var source: null

    spacing: Theme.spacingSm

    Text {
        Layout.fillWidth: true
        text: qsTr("增效体插槽")
        color: Theme.primary
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(16 * Theme.fontScale)
        font.bold: true
    }

    Text {
        Layout.fillWidth: true
        text: qsTr("选择植入的工业增效体（最多 3 个），每个提供不同的生产/贸易加成")
        color: Theme.textSecondary
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(12 * Theme.fontScale)
        wrapMode: Text.WordWrap
    }

    Repeater {
        model: root.source ? root.source.slots : []

        FSection {
            id: slot

            required property var modelData
            required property int index

            title: modelData.title

            FComboBox {
                id: implantBox

                objectName: "implantBox" + slot.index
                Layout.fillWidth: true
                model: slot.modelData.options
                textRole: "label"
                currentIndex: slot.modelData.index
                onActivated: if (root.source)
                    root.source.setSlotIndex(slot.index, currentIndex)
            }

            Text {
                Layout.fillWidth: true
                text: {
                    const options = slot.modelData.options;
                    const i = implantBox.currentIndex;
                    return (i >= 0 && i < options.length) ? (options[i].bonusDesc || "") : "";
                }
                color: Theme.accentGreen
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(11 * Theme.fontScale)
                wrapMode: Text.WordWrap
            }
        }
    }

    Item {
        Layout.fillHeight: true
    }
}
