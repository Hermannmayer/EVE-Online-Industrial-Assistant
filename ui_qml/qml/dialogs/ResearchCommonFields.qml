import QtQuick
import QtQuick.Layouts
import "../components"

/* 三张科研对话框（拷贝 / 发明 / 研究）共用的字段组：
 * 角色 / 材料机库 / 输出机库 + 底部提示。
 *
 * 对照 Widgets 版 `_ResearchDialogBase._add_common_fields()` —— 那块是三个子类共用的。
 * QML 里抽成一个组件，免得三份 .qml 各抄一遍（>30 行重复是项目明令禁止的）。
 *
 * 只依赖桥的公共 API（`_ResearchBridgeBase`：charOptions/hangarOptions 与对应 setter），
 * 三个桥都继承它，所以把桥整个传进来即可。提示文案走桥的 `tip` 属性，一处定义、三处显示。
 * 角色行再往下抽成 `CharField`，与「加入制造计划」框共用。
 *
 * ⚠️ 机库两行**必须**是显式控件、`currentIndex` 写成对桥属性的声明式绑定：
 * Repeater 的 `currentIndex` 只在建项时求值一次，桥改了索引（材料机库带动输出机库）
 * QML 不会跟。绑定能吃 `fieldsChanged` 信号，所以跟随是自动的，不需要 `Connections`
 * 里手写赋值（那种写法会打断绑定）。
 */

ColumnLayout {
    id: root

    //: 科研对话框的桥（`_ResearchBridgeBase` 子类）
    property var dlg: null

    Layout.fillWidth: true
    spacing: Theme.spacingSm

    readonly property int labelWidth: Math.round(88 * Theme.fontScale)
    readonly property int boxWidth: Math.round(260 * Theme.fontScale)
    readonly property int fntBase: Math.round(12 * Theme.fontScale)

    CharField {
        dlg: root.dlg
        labelWidth: root.labelWidth
        boxWidth: root.boxWidth
    }

    // ── 材料机库 ──
    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spacingSm

        Text {
            Layout.preferredWidth: root.labelWidth
            horizontalAlignment: Text.AlignRight
            text: qsTr("材料机库:")
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: root.fntBase
        }
        FComboBox {
            id: matBox
            objectName: "matHangarBox"
            Layout.preferredWidth: root.boxWidth
            model: root.dlg ? root.dlg.hangarOptions : []
            currentIndex: root.dlg ? root.dlg.matIndex : 0
            onActivated: if (root.dlg)
                root.dlg.setMatIndex(currentIndex)
        }
        Item {
            Layout.fillWidth: true
        }
    }

    // ── 输出机库（默认跟随材料机库，手工选过之后不再跟随）──
    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spacingSm

        Text {
            Layout.preferredWidth: root.labelWidth
            horizontalAlignment: Text.AlignRight
            text: qsTr("输出机库:")
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: root.fntBase
        }
        FComboBox {
            id: outBox
            objectName: "outHangarBox"
            Layout.preferredWidth: root.boxWidth
            model: root.dlg ? root.dlg.hangarOptions : []
            currentIndex: root.dlg ? root.dlg.outIndex : 0
            onActivated: if (root.dlg)
                root.dlg.setOutIndex(currentIndex)
        }
        Item {
            Layout.fillWidth: true
        }
    }

    // ── 提示 ──
    Text {
        Layout.fillWidth: true
        text: root.dlg ? root.dlg.tip : ""
        color: Theme.textSecondary
        font.family: Theme.fontFamily
        font.pixelSize: root.fntBase
        wrapMode: Text.WordWrap
    }
}
