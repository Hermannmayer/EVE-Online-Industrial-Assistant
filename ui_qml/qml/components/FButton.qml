import QtQuick
import QtQuick.Controls
import QtQuick.Effects

/* Fluent 按钮。
   规范对应：rounded-md / 小阴影 / font-semibold / duration-150 ease-out /
             hover:-translate-y-0.5 / active:scale-[0.97] + shadow-none /
             focus:ring-2 focus:ring-offset-2

   `scale` 不参与布局，因此按压缩放不会引发布局抖动。
   主/次通过 `primary` 区分（规范：bg-[#0078d4] text-white vs bg-white + border）。
*/
Button {
    id: root

    property bool primary: false

    // 用 TextMetrics 独立量文字，不依赖 contentItem 的 implicitWidth。
    // 依赖 contentItem 会引入「控件尺寸 ← 内容尺寸 ← 控件尺寸」的惰性依赖，
    // 实测会导致 Row 里的按钮拿不到宽度（width 停在 0，整行位置变成未定义）。
    TextMetrics {
        id: labelMetrics
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fs(13)
        font.weight: Font.DemiBold
        text: root.text
    }

    implicitHeight: 32
    implicitWidth: Math.max(88, Math.ceil(labelMetrics.width) + Theme.spacingLg * 2)

    // active:scale-[0.97]
    scale: down ? 0.97 : 1.0
    Behavior on scale {
        NumberAnimation {
            duration: Theme.reducedMotion ? 0 : Theme.durationFast
            easing.type: Easing.OutCubic
        }
    }

    HoverHandler { id: hover }

    background: Item {
        anchors.fill: parent

        // hover:-translate-y-0.5（2px）
        Rectangle {
            id: surface
            anchors.fill: parent
            y: (hover.hovered && !root.down) ? -2 : 0

            radius: Theme.radius
            color: root.primary
                   ? (root.down ? Qt.darker(Theme.primary, 1.25)
                                : (hover.hovered ? Qt.darker(Theme.primary, 1.12) : Theme.primary))
                   : (root.down ? Theme.bgSurfaceLight
                                : (hover.hovered ? Theme.bgHover : Theme.bgSurface))
            border.width: root.primary ? 0 : 1
            border.color: hover.hovered ? Qt.lighter(Theme.border, 1.6) : Theme.border

            Behavior on y {
                NumberAnimation {
                    duration: Theme.reducedMotion ? 0 : Theme.durationFast
                    easing.type: Easing.OutCubic
                }
            }
            Behavior on color {
                ColorAnimation {
                    duration: Theme.reducedMotion ? 0 : Theme.durationFast
                    easing.type: Easing.OutCubic
                }
            }

            layer.enabled: true
            layer.effect: MultiEffect {
                // active 时 shadow-none；hover 时阴影增强
                shadowEnabled: !root.down
                shadowBlur: hover.hovered ? Theme.elevationBlur(4) : Theme.elevationBlur(1)
                shadowVerticalOffset: hover.hovered ? Theme.elevationOffset(4) : Theme.elevationOffset(1)
                shadowColor: Qt.rgba(0, 0, 0, hover.hovered
                                              ? Theme.elevationAlpha(4) : Theme.elevationAlpha(1))
                autoPaddingEnabled: true

                Behavior on shadowBlur {
                    NumberAnimation {
                        duration: Theme.reducedMotion ? 0 : Theme.durationFast
                        easing.type: Easing.OutCubic
                    }
                }
            }
        }

        // focus:ring-2 focus:ring-offset-2
        Rectangle {
            anchors.fill: surface
            anchors.margins: -Theme.focusRingOffset
            radius: surface.radius + Theme.focusRingOffset
            color: "transparent"
            border.width: Theme.focusRingWidth
            border.color: Theme.primary
            visible: root.visualFocus
        }
    }

    contentItem: Text {
        id: label
        text: root.text
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fs(13)
        font.weight: Font.DemiBold
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        color: root.primary ? Theme.textOnPrimary : Theme.textPrimary
        opacity: root.enabled ? 1.0 : 0.4
    }
}
