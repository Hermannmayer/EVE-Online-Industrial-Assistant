import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/* 人物设置「技能」Tab —— 左分类列表 + 右技能滑杆（对齐 `char_settings_pages.SkillsPage`）。
 *
 * `source`（`SkillsBridge`）的契约：
 *   categories / categoryIndex / categoryTitle   左侧分类
 *   rows [{name, level}] / maxLevel              右侧技能行
 *   nameWidthMin / nameWidthMax                  技能名列的对齐宽度夹取区间
 *   setCategory(index) / setSkillLevel(row, level)
 *
 * **技能名列宽度在 QML 里量**：原版用 `text_width()` 逐名测量取最长（保证纵向不截断）。
 * 量法与 `FComboBox` 一致 —— 普通属性 + 主动测量，**不能写成绑定**：
 * 绑定体里给 `TextMetrics.text` 赋值会改动同一个绑定读的 `width`，
 * Qt 判定为绑定循环（FComboBox 上真踩过这个告警）。
 */

RowLayout {
    id: root

    property var source: null

    //: 技能名列宽度（按当前分类的最长技能名量出，夹在 nameWidthMin..nameWidthMax）
    property real nameWidth: Math.round(140 * Theme.fontScale)

    spacing: Theme.spacingSm

    function measureNameWidth() {
        if (!root.source)
            return;
        const rows = root.source.rows;
        let widest = 0;
        for (let i = 0; i < rows.length; ++i) {
            nameMetrics.text = rows[i].name;
            widest = Math.max(widest, nameMetrics.width);
        }
        const minW = Math.round(root.source.nameWidthMin * Theme.fontScale);
        const maxW = Math.round(root.source.nameWidthMax * Theme.fontScale);
        root.nameWidth = widest > 0 ? Math.max(minW, Math.min(Math.ceil(widest) + 16, maxW)) : minW;
    }

    TextMetrics {
        id: nameMetrics
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(12 * Theme.fontScale)
    }

    Component.onCompleted: measureNameWidth()

    // 换分类 / 换角色时才重建行（拖动滑杆不发 changed，见桥的 docstring）
    Connections {
        target: root.source

        function onChanged() {
            root.measureNameWidth();
        }
    }

    // ═══════════════════════════════════════════════════
    //  左：技能分类
    // ═══════════════════════════════════════════════════

    Rectangle {
        Layout.preferredWidth: Math.round(160 * Theme.fontScale)
        Layout.fillHeight: true
        color: Theme.bgSurface
        radius: Theme.radius

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: Theme.spacingXs
            spacing: Theme.spacingXs

            Text {
                text: qsTr("技能分类")
                color: Theme.primary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(12 * Theme.fontScale)
                font.bold: true
            }

            ListView {
                id: categoryList

                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                model: root.source ? root.source.categories : []
                currentIndex: root.source ? root.source.categoryIndex : -1

                delegate: Item {
                    id: categoryRow

                    required property var modelData
                    required property int index

                    readonly property bool current: categoryList.currentIndex === index

                    width: categoryList.width
                    height: Math.round(28 * Theme.fontScale)

                    HoverHandler {
                        id: categoryHover
                    }

                    Rectangle {
                        anchors.fill: parent
                        radius: Theme.radiusSmall
                        color: categoryRow.current ? Theme.bgSurfaceLight : (categoryHover.hovered ? Theme.bgHover : "transparent")
                    }

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: Theme.spacingXs
                        anchors.rightMargin: Theme.spacingXs
                        spacing: Theme.spacingXs

                        Image {
                            Layout.preferredWidth: 16
                            Layout.preferredHeight: 16
                            sourceSize.width: 16
                            sourceSize.height: 16
                            source: "image://phosphor/" + categoryRow.modelData.icon + "?c=" + Theme.hex(Theme.textSecondary) + "&s=16"
                        }

                        Text {
                            Layout.fillWidth: true
                            text: categoryRow.modelData.name
                            color: categoryRow.current ? Theme.textBright : Theme.textPrimary
                            font.family: Theme.fontFamily
                            font.pixelSize: Math.round(12 * Theme.fontScale)
                            elide: Text.ElideRight
                            verticalAlignment: Text.AlignVCenter
                        }
                    }

                    TapHandler {
                        onTapped: if (root.source)
                            root.source.setCategory(categoryRow.index)
                    }
                }
            }
        }
    }

    // ═══════════════════════════════════════════════════
    //  右：当前分类的技能滑杆
    // ═══════════════════════════════════════════════════

    Rectangle {
        Layout.fillWidth: true
        Layout.fillHeight: true
        color: Theme.bgSurface
        radius: Theme.radius

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: Theme.spacingSm
            spacing: Theme.spacingXs

            Text {
                Layout.fillWidth: true
                text: root.source ? root.source.categoryTitle : qsTr("选择左侧分类")
                color: Theme.primary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(14 * Theme.fontScale)
                font.bold: true
            }

            Flickable {
                Layout.fillWidth: true
                Layout.fillHeight: true
                contentWidth: width
                contentHeight: skillColumn.implicitHeight
                clip: true

                ColumnLayout {
                    id: skillColumn

                    width: parent.width
                    spacing: Theme.spacingXs

                    Repeater {
                        model: root.source ? root.source.rows : []

                        RowLayout {
                            id: skillRow

                            required property var modelData
                            required property int index

                            Layout.fillWidth: true
                            spacing: Theme.spacingSm

                            Text {
                                Layout.preferredWidth: root.nameWidth
                                text: skillRow.modelData.name
                                color: Theme.textPrimary
                                font.family: Theme.fontFamily
                                font.pixelSize: Math.round(12 * Theme.fontScale)
                                elide: Text.ElideRight
                                verticalAlignment: Text.AlignVCenter
                            }

                            FSlider {
                                id: levelSlider

                                objectName: "skillSlider" + skillRow.index
                                Layout.preferredWidth: Math.round(120 * Theme.fontScale)
                                from: 0
                                to: root.source ? root.source.maxLevel : 0
                                stepSize: 1
                                snapMode: Slider.SnapAlways
                                value: skillRow.modelData.level
                                // 只认用户拖动：`onValueChanged` 会被赋值回填触发，形成回环
                                onMoved: if (root.source)
                                    root.source.setSkillLevel(skillRow.index, Math.round(value))
                            }

                            Text {
                                Layout.preferredWidth: Math.round(20 * Theme.fontScale)
                                text: String(Math.round(levelSlider.value))
                                color: Theme.primary
                                font.family: Theme.fontFamily
                                font.pixelSize: Math.round(12 * Theme.fontScale)
                                font.bold: true
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }

                            Item {
                                Layout.fillWidth: true
                            }
                        }
                    }
                }
            }
        }
    }
}
