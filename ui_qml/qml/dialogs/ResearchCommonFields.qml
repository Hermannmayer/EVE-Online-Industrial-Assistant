import QtQuick
import QtQuick.Layouts
import "../components"

/* 三张科研对话框（拷贝 / 发明 / 研究）共用的字段组：
 * 角色 / 材料机库 / 输出机库 / 设施 + 底部提示。
 *
 * 对照 Widgets 版 `_ResearchDialogBase._add_common_fields()` —— 那块是三个子类共用的。
 * QML 里抽成一个组件，免得三份 .qml 各抄一遍（>30 行重复是项目明令禁止的）。
 *
 * 只依赖桥的公共 API（`_ResearchBridgeBase`：charOptions/hangarOptions/facilityOptions
 * 与对应 setter），三个桥都继承它，所以把桥整个传进来即可。提示文案走桥的 `tip` 属性，
 * 一处定义、三处显示。角色行/设施行再往下抽成 `CharField` / `FacilityField`，与
 * 「加入制造计划」框共用。
 */

ColumnLayout {
    id: root

    //: 科研对话框的桥（`_ResearchBridgeBase` 子类）
    property var dlg: null

    Layout.fillWidth: true
    spacing: Theme.spacingSm

    readonly property int labelWidth: Math.round(88 * Theme.fontScale)
    readonly property int boxWidth: Math.round(260 * Theme.fontScale)

    CharField {
        dlg: root.dlg
        labelWidth: root.labelWidth
        boxWidth: root.boxWidth
    }

    // ── 材料机库 / 输出机库 ──
    Repeater {
        model: [
            {
                "label": qsTr("材料机库:"),
                "index": root.dlg ? root.dlg.matIndex : 0,
                "setter": "setMatIndex"
            },
            {
                "label": qsTr("输出机库:"),
                "index": root.dlg ? root.dlg.outIndex : 0,
                "setter": "setOutIndex"
            }
        ]

        RowLayout {
            required property var modelData
            Layout.fillWidth: true
            spacing: Theme.spacingSm

            Text {
                Layout.preferredWidth: root.labelWidth
                horizontalAlignment: Text.AlignRight
                text: modelData.label
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(12 * Theme.fontScale)
            }
            FComboBox {
                Layout.preferredWidth: root.boxWidth
                model: root.dlg ? root.dlg.hangarOptions : []
                currentIndex: modelData.index
                onActivated: if (root.dlg)
                    root.dlg[modelData.setter](currentIndex)
            }
            Item {
                Layout.fillWidth: true
            }
        }
    }

    FacilityField {
        dlg: root.dlg
        labelWidth: root.labelWidth
        boxWidth: root.boxWidth
    }

    // ── 提示 ──
    Text {
        Layout.fillWidth: true
        text: root.dlg ? root.dlg.tip : ""
        color: Theme.textSecondary
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(12 * Theme.fontScale)
        wrapMode: Text.WordWrap
    }
}
