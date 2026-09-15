import QtQuick
import QtQuick.Controls

/* Fluent 滑杆 —— 用主题色重画轨道与滑块。
 *
 * 本项目此前没有 QML 滑杆。Qt 官方 Fluent 样式的滑杆走的是中性灰图集
 * （与 `FSpinBox` 覆盖上下按钮、`FCheckBox` 自绘对勾是同一类问题），
 * 所以这里按 F 系列的一贯做法只覆盖 `background` 与 `handle`，其余交给官方样式。
 *
 * 用在「人物设置 → 技能」的 0..5 等级行上（原 `char_settings_pages.SkillSlider` 里的
 * `QSlider`），因此保留 `stepSize` / `snapMode` 由调用方设定的能力。
 */

Slider {
    id: root

    implicitHeight: 28

    background: Rectangle {
        x: root.leftPadding
        y: root.topPadding + root.availableHeight / 2 - height / 2
        implicitWidth: 120
        implicitHeight: 4
        width: root.availableWidth
        height: implicitHeight
        radius: height / 2
        color: Theme.border

        Rectangle {
            width: root.visualPosition * parent.width
            height: parent.height
            radius: height / 2
            color: Theme.primary
        }
    }

    handle: Rectangle {
        x: root.leftPadding + root.visualPosition * (root.availableWidth - width)
        y: root.topPadding + root.availableHeight / 2 - height / 2
        implicitWidth: 16
        implicitHeight: 16
        radius: width / 2
        color: root.pressed ? Qt.darker(Theme.primary, 1.15) : Theme.primary
        // 描一圈页面底色：滑块压在轨道上时才分得出层次
        border.width: 1
        border.color: Theme.bgSurface

        Behavior on color {
            ColorAnimation {
                duration: Theme.reducedMotion ? 0 : Theme.durationFast
                easing.type: Easing.OutCubic
            }
        }
    }
}
