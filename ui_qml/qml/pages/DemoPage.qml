import QtQuick
import QtQuick.Controls
import "../components"

/* 阶段 0 验证页：确认 Theme 单例、FCard、FButton 与新对话框可正常工作。
   不承载业务，阶段 1 起由真实页面（估价页）取代。
*/
Item {
    id: page

    Rectangle {
        anchors.fill: parent
        color: Theme.bgDark
    }

    Column {
        anchors.centerIn: parent
        spacing: Theme.spacingLg

        FCard {
            width: 320
            height: 150

            Column {
                anchors.centerIn: parent
                spacing: Theme.spacingMd

                Text {
                    text: qsTr("Fluent 卡片")
                    color: Theme.textPrimary
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fs(16)
                    font.weight: Font.DemiBold
                    anchors.horizontalCenter: parent.horizontalCenter
                }

                Text {
                    text: qsTr("阴影 / 上浮 / Reveal 边框")
                    color: Theme.textSecondary
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fs(12)
                    anchors.horizontalCenter: parent.horizontalCenter
                }

                Row {
                    spacing: Theme.spacingSm
                    anchors.horizontalCenter: parent.horizontalCenter

                    FButton {
                        text: qsTr("主按钮")
                        primary: true
                    }

                    FButton {
                        text: qsTr("次按钮")
                    }
                }
            }
        }

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: qsTr("主题：%1　材质：%2　圆角：%3").arg(Theme.themeId).arg(Theme.material).arg(Theme.radius)
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fs(11)
        }
    }
}
