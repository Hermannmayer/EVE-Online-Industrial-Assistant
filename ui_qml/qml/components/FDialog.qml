import QtQuick
import QtQuick.Controls
import QtQuick.Effects
import QtQuick.Layouts

/* Fluent 对话框 —— 用主题色覆盖表面。

   同 FMenu/FComboBox：Qt 官方样式的对话框表面是中性灰图集、不跟主题。
   这里覆盖 background / header，**保留** Qt 的模态、焦点陷阱、标准按钮行为，
   以及 contentItem 的尺寸推导（不要覆盖 contentItem，那个坑在 FComboBox 里踩过）。

   用法：把 Dialog 换成本组件，内容直接放进默认属性即可（默认挂在 contentItem 里）。
*/
Dialog {
    id: root

    default property alias dialogContent: body.data

    modal: true
    anchors.centerIn: parent
    padding: Theme.spacingLg
    implicitWidth: 360

    background: Item {
        // 浮起面 + 柔和阴影，让对话框真的「浮」在页面之上
        Rectangle {
            id: surface
            anchors.fill: parent
            color: Theme.bgElevated
            border.color: Theme.border
            border.width: 1
            radius: Theme.radius * 1.5

            layer.enabled: true
            layer.effect: MultiEffect {
                shadowEnabled: true
                shadowBlur: Theme.elevationBlur(3)
                shadowVerticalOffset: Theme.elevationOffset(3)
                shadowColor: Qt.rgba(0, 0, 0, Theme.elevationAlpha(3))
                autoPaddingEnabled: true
            }
        }
    }

    header: Text {
        visible: root.title.length > 0
        text: root.title
        color: Theme.textBright
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fs(16)
        font.weight: Font.DemiBold
        elide: Text.ElideRight
        topPadding: Theme.spacingLg
        leftPadding: Theme.spacingLg
        rightPadding: Theme.spacingLg
    }

    // 内容容器：调用方写的内容都落在这里，自动带主题字体
    contentItem: ColumnLayout {
        id: body
        spacing: Theme.spacingMd
    }

    // footer 交给 Qt：它会按 standardButtons 自动生成 DialogButtonBox。
    // 自己塞 footer 反而会让 standardButtons / onAccepted 失效。
}
