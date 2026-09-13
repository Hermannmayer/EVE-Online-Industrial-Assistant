import QtQuick
import QtQuick.Controls

/* Fluent 下拉框 —— 只覆盖**弹出列表**的表面配色，字段本身交回 Qt 官方样式。

   为什么要覆盖：Qt 官方 Fluent 样式的弹出层表面是中性灰图集，不跟主题
   （实测菜单/弹窗底色恒为 #353535），与彩色主题放一起「风格不一」。

   为什么**不**覆盖 contentItem / indicator：那是在和 Qt 内部的尺寸推导较劲——
   实测覆盖 contentItem 后文字被挤成「…」或整段消失。字段的几何/指示器/焦点
   全部交给官方样式，只把弹窗背景换成主题色，风险最小。
*/
ComboBox {
    id: root

    // 量最长条目的宽度。字段本身可能很窄（被网格约束），但**下拉必须能显示完整条目**，
    // 否则长名字会被截成「组…」「产…」（实测：机库名被压到 90px 字段里就是这样）。
    TextMetrics {
        id: itemMetrics
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fs(12)
    }

    readonly property real maxItemWidth: {
        let widest = 0;
        for (let i = 0; i < root.count; ++i) {
            itemMetrics.text = root.textAt(i);
            widest = Math.max(widest, itemMetrics.width);
        }
        return widest;
    }

    popup: Popup {
        // 与字段留 2px 缝：贴死会让下拉看起来像字段本身的一部分
        y: root.height + 2
        // 宽度给足余量：Qt 的 ItemDelegate 除了我设的左右内边距，还有样式自带的其他
        // 占位，逐项算净宽不可靠（实测按「文字宽 + padding」算出的 98px 仍然会截断）。
        // 这里直接用宽松的经验余量 + 一个下限，保证任何机库名都能完整显示。
        width: Math.max(root.width, root.maxItemWidth + 2 * Theme.spacingLg + 2 * padding, 160)
        implicitHeight: Math.min(280, contentItem.implicitHeight + topPadding + bottomPadding)
        // 内边距要小：官方默认带较大 padding，加上条目自身的内边距，
        // 整体看起来就是一圈很宽的边框（用户反馈「边框太大」）。
        padding: 2

        background: Rectangle {
            color: Theme.bgElevated
            border.color: Theme.border
            border.width: 1
            radius: Theme.radius
        }

        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: root.popup.visible ? root.delegateModel : null
            currentIndex: root.highlightedIndex
            ScrollIndicator.vertical: ScrollIndicator {}
        }
    }

    // 让弹窗条目也走主题色（官方委托用的是灰底高亮）
    delegate: ItemDelegate {
        id: item

        required property var modelData
        required property int index

        width: ListView.view ? ListView.view.width : root.width
        // 必须显式给行高与左右内边距：不设会沿用官方样式的默认值——
        // 行高偏大（条目很散），左右内边距更是给图标预留的槽位，
        // 会把文字区挤到只剩几十像素，长名字被截成「组…」（实测踩过）。
        implicitHeight: 30
        leftPadding: Theme.spacingSm
        rightPadding: Theme.spacingSm
        highlighted: root.highlightedIndex === index

        contentItem: Text {
            leftPadding: Theme.spacingSm
            rightPadding: Theme.spacingSm
            text: root.textRole ? String(item.modelData?.[root.textRole] ?? "") : String(item.modelData ?? "")
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fs(12)
            color: Theme.textPrimary
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }

        background: Rectangle {
            radius: Theme.radiusSmall
            color: item.highlighted ? Theme.bgHover : "transparent"
        }
    }

    palette.base: Theme.bgElevated
    palette.text: Theme.textPrimary
    palette.window: Theme.bgElevated
    palette.windowText: Theme.textPrimary
    palette.highlight: Theme.primary
    palette.highlightedText: Theme.textOnPrimary
}
