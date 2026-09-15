import QtQuick
import QtQuick.Layouts

/* 主题卡片网格 —— 对齐 Widgets 版 `ui_pyside6/views/theme_selector.ThemeSelector`。
 *
 * 一行三张卡：三个色块预览 + 中文名 + 暗/亮角标 + 材质小字，点一张即切主题。
 *
 * **色值来自桥**（桥再取自 `theme.THEME_REGISTRY`），不是 `Theme.xxx`：
 * 卡片要展示的是「那一套主题长什么样」，用当前主题的 token 会把所有卡画成同一个样子。
 *
 * `source`（桥）的契约：
 *   themes           [{id, name, badge, material, swatches:[{color,border}]}]
 *   currentThemeId   当前主题 id（选中态）
 *   setCurrentTheme(id)  点击切主题（即时生效并持久化）
 *
 * 卡片本体复用 `FCard`（自带阴影/悬浮/按压）；选中态是叠在卡面上的一圈主题色描边。
 * 描边用负 margin 顶到卡片外沿：`FCard` 的内容区是内缩 `spacingMd` 的，
 * 不抵消就成了一圈内嵌的框，看着像另一个控件。
 */

GridLayout {
    id: root

    property var source: null

    columns: 3
    columnSpacing: Theme.spacingSm
    rowSpacing: Theme.spacingSm

    Repeater {
        model: root.source ? root.source.themes : []

        FCard {
            id: card

            required property var modelData

            readonly property bool selected: root.source ? root.source.currentThemeId === modelData.id : false

            Layout.preferredWidth: Math.round(148 * Theme.fontScale)
            Layout.preferredHeight: Math.round(88 * Theme.fontScale)

            TapHandler {
                onTapped: if (root.source)
                    root.source.setCurrentTheme(card.modelData.id)
            }

            Rectangle {
                anchors.fill: parent
                anchors.margins: -Theme.spacingMd
                color: "transparent"
                radius: Theme.radius
                border.width: 2
                border.color: Theme.primary
                visible: card.selected
            }

            ColumnLayout {
                anchors.fill: parent
                spacing: Theme.spacingXs

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.spacingXs

                    Repeater {
                        model: card.modelData.swatches

                        Rectangle {
                            required property var modelData

                            Layout.preferredWidth: Math.round(32 * Theme.fontScale)
                            Layout.preferredHeight: Math.round(20 * Theme.fontScale)
                            color: modelData.color
                            radius: Theme.radiusSmall
                            border.width: 1
                            border.color: modelData.border
                        }
                    }

                    Item {
                        Layout.fillWidth: true
                    }

                    Rectangle {
                        implicitWidth: badge.implicitWidth + 2 * Theme.spacingXs
                        implicitHeight: badge.implicitHeight + 2
                        radius: height / 2
                        color: "transparent"
                        border.width: 1
                        border.color: Theme.border

                        Text {
                            id: badge
                            anchors.centerIn: parent
                            text: card.modelData.badge
                            color: Theme.textSecondary
                            font.family: Theme.fontFamily
                            font.pixelSize: Math.round(10 * Theme.fontScale)
                        }
                    }
                }

                Text {
                    Layout.fillWidth: true
                    text: card.modelData.name
                    color: Theme.textPrimary
                    font.family: Theme.fontFamily
                    font.pixelSize: Math.round(12 * Theme.fontScale)
                    elide: Text.ElideRight
                }

                Text {
                    Layout.fillWidth: true
                    text: card.modelData.material
                    color: Theme.textSecondary
                    font.family: Theme.fontFamily
                    font.pixelSize: Math.round(10 * Theme.fontScale)
                    elide: Text.ElideRight
                }

                Item {
                    Layout.fillHeight: true
                }
            }
        }
    }
}
