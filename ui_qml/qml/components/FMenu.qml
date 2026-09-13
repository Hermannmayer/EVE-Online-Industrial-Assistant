import QtQuick
import QtQuick.Controls

/* Fluent 菜单 —— 用主题色覆盖 Qt 官方样式的表面。

   为什么必须覆盖：Qt 的 FluentWinUI3 样式把菜单/弹窗的表面画成**中性的灰色图集**
   （实测菜单底色恒为 #353535，且不受 QPalette 影响）。本项目主题是彩色底
   （深色 slate-900 / 浅色白），两者放一起就是「菜单是灰的、其余是彩的」——
   用户反馈的「二级菜单风格不一」就是它。

   这里只覆盖 background 与条目配色，键盘导航/快捷键/子菜单等行为仍由 Qt 提供。
*/
Menu {
    id: root

    // 与固定 32px 行高对齐，避免条目忽高忽低
    implicitWidth: Math.max(180, implicitContentWidth + leftPadding + rightPadding)

    background: Rectangle {
        implicitWidth: 180
        color: Theme.bgElevated
        border.color: Theme.border
        border.width: 1
        radius: Theme.radius
    }

    delegate: MenuItem {
        id: item

        implicitHeight: 32
        leftPadding: Theme.spacingMd
        rightPadding: Theme.spacingMd

        contentItem: Text {
            text: item.text
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fs(12)
            color: item.enabled ? Theme.textPrimary : Theme.textSecondary
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }

        background: Rectangle {
            radius: Theme.radiusSmall
            color: item.highlighted ? Theme.bgHover : "transparent"
        }
    }

    // 分隔线也要跟着主题，默认是灰的
    // （Menu 的 contentItem 里由 MenuSeparator 的隐式委托渲染，这里统一给高度与配色）
    palette.window: Theme.bgElevated
    palette.windowText: Theme.textPrimary
    palette.base: Theme.bgElevated
    palette.text: Theme.textPrimary
    palette.highlight: Theme.primary
    palette.highlightedText: Theme.textOnPrimary
}
