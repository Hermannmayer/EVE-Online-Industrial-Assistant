import QtQuick
import QtQuick.Effects

/* Fluent 卡片。
   规范对应：rounded-md / border border-[#e1e1e1] / bg-white /
             hover:-translate-y-1 + 阴影扩张 / Reveal 边框提亮
   所有颜色与尺寸取自 Theme 单例，禁止字面量。
*/
Item {
    id: root

    default property alias contentData: content.data

    // 静止层 1，悬停升至 4（阴影扩张）
    property int baseElevation: 1
    property bool interactive: true
    property alias radius: bg.radius
    property alias borderWidth: bg.border.width

    implicitWidth: 240
    implicitHeight: 120

    HoverHandler {
        id: hover
        enabled: root.interactive
    }

    // 上浮容器：布局定位 root，内部整体上移，避免与布局系统抢几何
    Item {
        id: inner
        anchors.fill: parent
        y: (hover.hovered && root.interactive) ? -Theme.spacingXs : 0

        Behavior on y {
            NumberAnimation {
                duration: Theme.reducedMotion ? 0 : Theme.durationCard
                easing.type: Easing.OutCubic
            }
        }

        Rectangle {
            id: bg
            anchors.fill: parent
            radius: Theme.radius
            // 浮起表面：比页面底色**亮**，这样阴影 + 明度差一起读出「浮起」。
            // 用 Theme.bgSurface（比 bgDark 暗）会让卡片像凹坑 —— 实测过。
            // Reveal：悬停时再提亮一档。
            color: (hover.hovered && root.interactive)
                   ? Qt.lighter(Theme.bgElevated, 1.14)
                   : Theme.bgElevated
            border.width: 1
            // Reveal：悬停时边框提亮
            border.color: (hover.hovered && root.interactive)
                          ? Qt.lighter(Theme.border, 2.0)
                          : Qt.lighter(Theme.border, 1.45)

            Behavior on color {
                ColorAnimation {
                    duration: Theme.reducedMotion ? 0 : Theme.durationCard
                    easing.type: Easing.OutCubic
                }
            }

            layer.enabled: true
            layer.effect: MultiEffect {
                shadowEnabled: true
                shadowBlur: (hover.hovered && root.interactive)
                            ? Theme.elevationBlur(4) : Theme.elevationBlur(root.baseElevation)
                shadowVerticalOffset: (hover.hovered && root.interactive)
                                      ? Theme.elevationOffset(4) : Theme.elevationOffset(root.baseElevation)
                shadowColor: Qt.rgba(0, 0, 0, (hover.hovered && root.interactive)
                                              ? Theme.elevationAlpha(4) : Theme.elevationAlpha(root.baseElevation))
                autoPaddingEnabled: true

                Behavior on shadowBlur {
                    NumberAnimation {
                        duration: Theme.reducedMotion ? 0 : Theme.durationCard
                        easing.type: Easing.OutCubic
                    }
                }
            }
        }
    }

    // 内容与背景平级，避免被当作阴影源
    Item {
        id: content
        anchors.fill: parent
        anchors.margins: Theme.spacingMd
    }
}
