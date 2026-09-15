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

    /* 打开右键菜单的**唯一推荐入口** —— 别直接调 `popup()` / `open()`。
     *
     * 为什么必须延迟一拍：那一次右键的「按下+释放」如果比菜单先到、或与菜单的创建同批
     * 被投递，落点又在某个条目上，Qt 会把它当成对该条目的**点击**。二级菜单项位于菜单
     * 末尾，菜单在鼠标点弹出（`popup()` 默认如此；`open()` 的调用点也都把 x/y 设成点击
     * 坐标），一旦 Qt 因贴近屏幕底边把菜单**向上翻转**，指针就正好落在二级项上 ——
     * 二级菜单被这次点击展开，又被随之而来的事件收掉，肉眼就是「闪一下然后关闭」。
     *
     * `Qt.callLater` 把弹出推到本轮事件处理之后：那时原始点击早已派发完毕，菜单才出现，
     * 自然吃不到它。用户报的就是这个现象（实测：二级菜单**只**在鼠标点击其条目时展开，
     * `trigger()` / `currentIndex` / 高亮都不会）。
     */
    function openSoon() {
        Qt.callLater(function () {
            root.open();
        });
    }

    //: 与 `openSoon` 同源，只是保留 `popup()` 的「在鼠标处弹出」语义（见上）。
    function popupSoon() {
        Qt.callLater(function () {
            root.popup();
        });
    }

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
