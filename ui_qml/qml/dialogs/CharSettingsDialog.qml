import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 人物设置对话框（阶段 4b）：多角色切换 + 技能 / 增效体 / 市场费率三个 Tab。
 *
 * 对照 Widgets 版 `ui_pyside6/views/char_settings_view.CharSettingsDialog`：
 * 顶部角色栏（下拉 / 名字框 / 添加 / 删除）+ 三个 Tab + 底部保存/取消。
 * 三个 Tab 的正文是 `components/` 下的 `FSkillsTab` / `FImplantsTab` / `FMarketTab`，
 * 各自绑到宿主桥暴露的从属桥（`skills` / `implants` / `market`）上。
 *
 * 「保存」走 `bridge.accept()`（桥里落盘并弹一次保存成功），所以这里把
 * `acceptText` 写成「保存」而不是「确定」。
 */

FDialogFrame {
    id: frame

    readonly property var cb: typeof bridge !== "undefined" ? bridge : null

    dlg: frame.cb
    acceptText: qsTr("保存")

    // ═══════════════════════════════════════════════════
    //  顶部角色栏
    // ═══════════════════════════════════════════════════

    Rectangle {
        Layout.fillWidth: true
        implicitHeight: charBar.implicitHeight + 2 * Theme.spacingSm
        color: Theme.bgSurface
        radius: Theme.radius

        RowLayout {
            id: charBar

            anchors.fill: parent
            anchors.leftMargin: Theme.spacingMd
            anchors.rightMargin: Theme.spacingMd
            spacing: Theme.spacingSm

            Text {
                text: qsTr("当前人物:")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(12 * Theme.fontScale)
                verticalAlignment: Text.AlignVCenter
            }

            FComboBox {
                id: charBox

                objectName: "characterBox"
                Layout.preferredWidth: Math.round(150 * Theme.fontScale)
                model: frame.cb ? frame.cb.characterNames : []
                currentIndex: frame.cb ? frame.cb.characterIndex : -1
                onActivated: if (frame.cb)
                    frame.cb.switchCharacter(currentIndex)
            }

            FTextField {
                id: nameField

                objectName: "characterNameField"
                Layout.preferredWidth: Math.round(160 * Theme.fontScale)
                text: frame.cb ? frame.cb.characterName : ""
            }

            /* 角色换了就把名字框拉回当前角色名。原版在 `_on_char_switch` 里
             * `setText(name)` 做了同一件事 —— 少了这一步，用户在里面打过字之后
             * 换角色，框里会留着上一个人的名字。*/
            Connections {
                target: frame.cb

                function onStateChanged() {
                    nameField.text = frame.cb.characterName;
                }
            }

            FButton {
                objectName: "addCharacterButton"
                text: qsTr("+ 添加")
                onClicked: if (frame.cb)
                    frame.cb.addCharacter()
            }

            FButton {
                objectName: "deleteCharacterButton"
                text: qsTr("删除")
                enabled: frame.cb ? frame.cb.canDelete : false
                onClicked: if (frame.cb)
                    frame.cb.deleteCharacter()
            }

            Item {
                Layout.fillWidth: true
            }
        }
    }

    // ═══════════════════════════════════════════════════
    //  三个 Tab
    // ═══════════════════════════════════════════════════

    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spacingSm

        TabBar {
            id: tabBar

            TabButton {
                text: qsTr("技能")
            }
            TabButton {
                text: qsTr("增效体")
            }
            TabButton {
                text: qsTr("市场费率")
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

        FSkillsTab {
            objectName: "skillsTab"
            source: frame.cb ? frame.cb.skills : null
        }

        FImplantsTab {
            objectName: "implantsTab"
            source: frame.cb ? frame.cb.implants : null
        }

        FMarketTab {
            objectName: "marketTab"
            source: frame.cb ? frame.cb.market : null
        }
    }
}
