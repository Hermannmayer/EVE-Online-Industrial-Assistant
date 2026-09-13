import QtQuick
import QtQuick.Shapes

/* 微调框的上下箭头按钮 —— 自绘，避免用 Qt 的中性灰图集。

   用 Shape 画折线而不是「▲▼」字符：不受字体是否含该字形影响
   （项目里被字体字形坑过，见 ui-blueprint 的 glyph 章节）。
*/
Item {
    id: root

    property bool hovered: false
    property bool pressed: false
    property bool flipped: false
    // 不能叫 enabled：FArrowButton 的根是 Item，而 Item 自带 enabled，重名会让
    // QML 编译器卡死（实测：页面上只要有这个控件，QQuickWidget.setSource 就死锁）。
    property bool active: true

    Rectangle {
        anchors.fill: parent
        radius: Theme.radiusSmall
        color: root.hovered && root.active ? Theme.bgHover : "transparent"
        opacity: root.pressed ? 0.7 : 1.0
    }

    Shape {
        anchors.centerIn: parent
        width: 10
        height: 6
        // flipped=true 表示「上」箭头（形状本身画成朝下，再上下翻转）
        transform: Scale { origin.x: 5; origin.y: 3; yScale: root.flipped ? -1 : 1 }

        ShapePath {
            strokeColor: root.active ? Theme.textSecondary : Theme.border
            strokeWidth: 1.6
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            joinStyle: ShapePath.RoundJoin
            startX: 0.5
            startY: 0.8
            PathLine { x: 5; y: 5.2 }
            PathLine { x: 9.5; y: 0.8 }
        }
    }
}
