import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 系统设置对话框（阶段 4b）：ESI 与数据 / 外观 / 默认参数 三个标签页。
 *
 * 对照 Widgets 版 `ui_pyside6/views/settings_view.SettingsDialog`：
 * - 标签页、表单字段、三个按钮（确定 / 取消 / 应用）逐条对齐；
 * - 「应用」不关窗，走 `FThemeCards` 的 `applyRequested`（`FDialogFrame` 里那个可选按钮）；
 * - 「外观」页嵌 `FThemeCards`（原版嵌 `ThemeSelector`），点卡片**即时换肤**，
 *   「应用/确定」只是兜底写回宿主。
 *
 * 更新间隔的「关闭」不是另起一个控件：原版用 `QSpinBox.setSpecialValueText("关闭")`，
 * QML 的 `SpinBox` 没有该属性，改用 `textFromValue`/`valueFromText` 担同一件事。
 */

FDialogFrame {
    id: frame

    readonly property var sb: typeof bridge !== "undefined" ? bridge : null

    dlg: frame.sb
    applyVisible: true
    onApplyRequested: if (frame.sb)
        frame.sb.apply()

    /* 标签栏靠左收窄（与存储页同一处理）：铺满整行会让三个 TabButton 平分宽度、
     * 上半区看着一大片空。收窄之后必须用 `FTabBar`——普通 `TabBar` 把宽度等分给每个
     * 按钮而不看各自的 `implicitWidth`，「ESI 与数据」会被截成「ESI 与…」（真窗口实测到）。*/
    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spacingSm

        FTabBar {
            id: tabBar

            TabButton {
                text: qsTr("ESI 与数据")
            }
            TabButton {
                text: qsTr("外观")
            }
            TabButton {
                text: qsTr("默认参数")
            }
        }

        Item {
            Layout.fillWidth: true
        }
    }

    StackLayout {
        Layout.fillWidth: true
        Layout.fillHeight: true
        currentIndex: tabBar.currentIndex

        // ═══════════════════════════════════════════════════
        //  Tab 1：ESI 与数据
        // ═══════════════════════════════════════════════════

        ColumnLayout {
            spacing: Theme.spacingMd

            FSection {
                title: qsTr("价格更新")

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.spacingSm

                    Text {
                        text: qsTr("更新间隔:")
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: Math.round(12 * Theme.fontScale)
                    }

                    FSpinBox {
                        objectName: "intervalSpin"
                        Layout.preferredWidth: Math.round(120 * Theme.fontScale)
                        from: 0
                        to: frame.sb ? frame.sb.intervalMax : 1440
                        stepSize: 5
                        value: frame.sb ? frame.sb.interval : 0
                        textFromValue: function (v) {
                            return v === 0 ? qsTr("关闭") : v + qsTr(" 分钟");
                        }
                        valueFromText: function (t) {
                            const n = parseInt(t, 10);
                            return isNaN(n) ? 0 : Math.max(0, Math.min(n, frame.sb ? frame.sb.intervalMax : 1440));
                        }
                        onValueModified: if (frame.sb)
                            frame.sb.setInterval(value)
                    }

                    Item {
                        Layout.fillWidth: true
                    }
                }

                FCheckBox {
                    objectName: "autoUpdateCheck"
                    text: qsTr("启用自动更新")
                    checked: frame.sb ? frame.sb.autoUpdate : false
                    onToggled: if (frame.sb)
                        frame.sb.setAutoUpdate(checked)
                }
            }

            Item {
                Layout.fillHeight: true
            }
        }

        // ═══════════════════════════════════════════════════
        //  Tab 2：外观
        // ═══════════════════════════════════════════════════

        ColumnLayout {
            spacing: Theme.spacingMd

            FSection {
                title: qsTr("主题")

                FThemeCards {
                    Layout.fillWidth: true
                    source: frame.sb ? frame.sb.themeSelector : null
                }
            }

            FSection {
                title: qsTr("字体大小")

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.spacingSm

                    Text {
                        text: qsTr("全局字号:")
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: Math.round(12 * Theme.fontScale)
                    }

                    FSpinBox {
                        objectName: "fontSizeSpin"
                        Layout.preferredWidth: Math.round(90 * Theme.fontScale)
                        from: frame.sb ? frame.sb.fontSizeMin : 10
                        to: frame.sb ? frame.sb.fontSizeMax : 20
                        value: frame.sb ? frame.sb.fontSize : 13
                        onValueModified: if (frame.sb)
                            frame.sb.setFontSize(value)
                    }

                    Item {
                        Layout.fillWidth: true
                    }
                }
            }

            Item {
                Layout.fillHeight: true
            }
        }

        // ═══════════════════════════════════════════════════
        //  Tab 3：默认参数
        // ═══════════════════════════════════════════════════

        ColumnLayout {
            spacing: Theme.spacingMd

            FSection {
                title: qsTr("工具")

                FButton {
                    objectName: "initWizardButton"
                    text: qsTr("数据初始化")
                    onClicked: if (frame.sb)
                        frame.sb.openInitWizard()
                }

                FButton {
                    objectName: "aboutButton"
                    text: qsTr("关于")
                    onClicked: if (frame.sb)
                        frame.sb.openAbout()
                }
            }

            Item {
                Layout.fillHeight: true
            }
        }
    }
}
