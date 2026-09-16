import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 批量设置蓝图等级（批次 7.3）—— 原 `plan_table.py::_batch_set_me_te` 里手搭的 QDialog。
 *
 * ME 0..10 / TE 0..20，各一根滑杆 + 一个数字框，**两者双向联动**。
 * 窗口行为在 `QmlDialog` 那一层，这里只用 `FDialogFrame` 排主体 + 按钮。
 * 取值与范围都在桥（`me_te_dialog.py`）。
 */

FDialogFrame {
    id: frame

    readonly property var b: typeof bridge !== "undefined" ? bridge : null

    dlg: frame.b
    acceptText: qsTr("确定")

    /* 已绑产线的计划才显示：说清这里改的是「未绑定产线」的兜底值。
       原版是按 `first.get("bound_blueprint_ids")` 决定加不加这条 QLabel。 */
    Text {
        Layout.fillWidth: true
        visible: frame.b ? frame.b.hint !== "" : false
        text: frame.b ? frame.b.hint : ""
        color: Theme.textSecondary
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(11 * Theme.fontScale)
        wrapMode: Text.WordWrap
    }

    Text {
        Layout.fillWidth: true
        text: qsTr("材料效率(ME) 0-10:")
        color: Theme.textPrimary
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(12 * Theme.fontScale)
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spacingSm

        FSlider {
            id: meSlider
            objectName: "meSlider"
            Layout.fillWidth: true
            from: frame.b ? frame.b.meMin : 0
            to: frame.b ? frame.b.meMax : 10
            stepSize: 1
            snapMode: Slider.SnapAlways
            // 只认用户拖动：`onValueChanged` 会被下面的回填触发，形成回环
            onMoved: if (frame.b)
                frame.b.setMe(Math.round(value))
        }

        FSpinBox {
            id: meSpin
            objectName: "meSpin"
            Layout.preferredWidth: 76
            from: frame.b ? frame.b.meMin : 0
            to: frame.b ? frame.b.meMax : 10
            // valueModified 只在用户操作时发（程序化赋值不发），不会与回填打环
            onValueModified: if (frame.b)
                frame.b.setMe(Math.round(value))
        }
    }

    Text {
        Layout.fillWidth: true
        text: qsTr("时间效率(TE) 0-20:")
        color: Theme.textPrimary
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(12 * Theme.fontScale)
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spacingSm

        FSlider {
            id: teSlider
            objectName: "teSlider"
            Layout.fillWidth: true
            from: frame.b ? frame.b.teMin : 0
            to: frame.b ? frame.b.teMax : 20
            stepSize: 1
            snapMode: Slider.SnapAlways
            onMoved: if (frame.b)
                frame.b.setTe(Math.round(value))
        }

        FSpinBox {
            id: teSpin
            objectName: "teSpin"
            Layout.preferredWidth: 76
            from: frame.b ? frame.b.teMin : 0
            to: frame.b ? frame.b.teMax : 20
            onValueModified: if (frame.b)
                frame.b.setTe(Math.round(value))
        }
    }

    Item {
        Layout.fillHeight: true
    }

    /* 滑杆 ↔ 数字框的双向联动 —— **桥是唯一真值源**，两个控件都只是它的视图。
     *
     * 刻意**不**写成 PartialStartDialog / ScoreParamsDialog 那种
     * `value: bridge.xxx` 的一对一绑定：那边每个字段只有一个控件，回填链断不掉；
     * 这里一根滑杆要跟着另一个数字框走。Qt Quick 的 Slider 在用户拖动时直接给
     * `value` 赋值，而**向已绑定的属性赋值会摘掉那条 QML 绑定** —— 于是
     * 「数字框改 → 滑杆跟着走」在第一次拖动滑杆之后就断了（数字框仍会跟着滑杆走，
     * 方向反过来的那半条静默失效，离屏截图看不出来）。
     *
     * 改成：两个控件都不绑 `value`，用户操作只往桥上推，桥发 `valuesChanged`
     * 时由这里把值推回两侧。程序化赋值既不触发 Slider.moved 也不触发
     * SpinBox.valueModified，所以这条环是单向收敛的，不会自激。
     */
    Connections {
        target: frame.b

        function onValuesChanged() {
            if (!frame.b)
                return;
            meSlider.value = frame.b.meValue;
            meSpin.value = frame.b.meValue;
            teSlider.value = frame.b.teValue;
            teSpin.value = frame.b.teValue;
        }
    }

    // 初始值：控件不绑 `value`，所以首帧要手动铺一次（原版是构造时 setValue）
    Component.onCompleted: {
        if (!frame.b)
            return;
        meSlider.value = frame.b.meValue;
        meSpin.value = frame.b.meValue;
        teSlider.value = frame.b.teValue;
        teSpin.value = frame.b.teValue;
    }
}
