import QtQuick
import QtQuick.Layouts

/* 人物设置「市场费率」Tab —— 4 大交易中心声望 + 自动算出的费率（对齐 `MarketPage`）。
 *
 * `source`（`MarketBridge`）的契约：
 *   hubs     [{key, name, factionLabel, corpLabel, faction, corp}]  只在换角色时重建
 *   results  [文本]  费率文案，改声望或改技能都只重算这一项
 *   standingMin / standingMax  声望范围
 *   setFactionStanding(hub, value) / setCorpStanding(hub, value)
 *
 * 拆成两个属性是**故意的**：合成一个 `hubs` 数组的话，每改一次声望都要重建列表，
 * 正在输入的那个微调框会被删掉、焦点与半截输入一起丢。
 */

ColumnLayout {
    id: root

    property var source: null

    spacing: Theme.spacingSm

    Text {
        Layout.fillWidth: true
        text: qsTr("市场费率配置")
        color: Theme.primary
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(16 * Theme.fontScale)
        font.bold: true
    }

    Text {
        Layout.fillWidth: true
        text: qsTr("为每个交易中心设置派系声望和军团声望，自动计算经纪人费率和销售税率")
        color: Theme.textSecondary
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(12 * Theme.fontScale)
        wrapMode: Text.WordWrap
    }

    Flickable {
        Layout.fillWidth: true
        Layout.fillHeight: true
        contentWidth: width
        contentHeight: hubColumn.implicitHeight
        clip: true

        ColumnLayout {
            id: hubColumn

            width: parent.width
            spacing: Theme.spacingMd

            Repeater {
                model: root.source ? root.source.hubs : []

                FSection {
                    id: hub

                    required property var modelData
                    required property int index

                    title: modelData.name

                    GridLayout {
                        Layout.fillWidth: true
                        columns: 2
                        columnSpacing: Theme.spacingSm
                        rowSpacing: Theme.spacingXs

                        Text {
                            text: hub.modelData.factionLabel
                            color: Theme.textPrimary
                            font.family: Theme.fontFamily
                            font.pixelSize: Math.round(12 * Theme.fontScale)
                            verticalAlignment: Text.AlignVCenter
                        }

                        FDoubleSpinBox {
                            objectName: "factionSpin" + hub.index
                            Layout.preferredWidth: Math.round(140 * Theme.fontScale)
                            from: root.source ? root.source.standingMin : -10
                            to: root.source ? root.source.standingMax : 10
                            stepSize: 0.1
                            decimals: 2
                            value: hub.modelData.faction
                            onValueModified: if (root.source)
                                root.source.setFactionStanding(hub.index, value)
                        }

                        Text {
                            text: hub.modelData.corpLabel
                            color: Theme.textPrimary
                            font.family: Theme.fontFamily
                            font.pixelSize: Math.round(12 * Theme.fontScale)
                            verticalAlignment: Text.AlignVCenter
                        }

                        FDoubleSpinBox {
                            objectName: "corpSpin" + hub.index
                            Layout.preferredWidth: Math.round(140 * Theme.fontScale)
                            from: root.source ? root.source.standingMin : -10
                            to: root.source ? root.source.standingMax : 10
                            stepSize: 0.1
                            decimals: 2
                            value: hub.modelData.corp
                            onValueModified: if (root.source)
                                root.source.setCorpStanding(hub.index, value)
                        }

                        Text {
                            Layout.columnSpan: 2
                            Layout.fillWidth: true
                            text: root.source ? root.source.results[hub.index] : ""
                            color: Theme.accentGreen
                            font.family: Theme.fontFamily
                            font.pixelSize: Math.round(11 * Theme.fontScale)
                            wrapMode: Text.WordWrap
                        }
                    }
                }
            }
        }
    }
}
