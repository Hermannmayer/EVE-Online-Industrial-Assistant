import QtQuick
import QtQuick.Controls
import QtQuick.Shapes

/* Fluent 复选框 —— 用主题色重画指示器。

   Qt 官方样式的选中框/对勾是中性灰图集，不跟主题，所以这里自绘。
   对勾用 Shape 而非「✓」字符：不受字体是否含该字形影响。
*/
CheckBox {
    id: root

    implicitHeight: 28
    spacing: Theme.spacingSm
    font.family: Theme.fontFamily
    font.pixelSize: Theme.fs(12)

    indicator: Rectangle {
        id: box

        implicitWidth: 18
        implicitHeight: 18
        x: root.leftPadding
        y: root.topPadding + (root.availableHeight - height) / 2
        radius: Theme.radiusSmall
        color: root.checked ? Theme.primary : "transparent"
        border.width: root.checked ? 0 : 1
        border.color: root.hovered ? Theme.primary : Theme.border

        Behavior on color {
            ColorAnimation {
                duration: Theme.reducedMotion ? 0 : Theme.durationFast
                easing.type: Easing.OutCubic
            }
        }
        Behavior on border.color {
            ColorAnimation {
                duration: Theme.reducedMotion ? 0 : Theme.durationFast
                easing.type: Easing.OutCubic
            }
        }

        Shape {
            anchors.centerIn: parent
            width: 12
            height: 12
            visible: root.checked

            ShapePath {
                strokeColor: Theme.textOnPrimary
                strokeWidth: 2
                fillColor: "transparent"
                capStyle: ShapePath.RoundCap
                joinStyle: ShapePath.RoundJoin
                startX: 1
                startY: 6
                PathLine { x: 4.5; y: 9.5 }
                PathLine { x: 11; y: 2.5 }
            }
        }
    }

    contentItem: Text {
        leftPadding: box.width + root.spacing
        text: root.text
        font: root.font
        color: root.enabled ? Theme.textPrimary : Theme.textSecondary
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
}
