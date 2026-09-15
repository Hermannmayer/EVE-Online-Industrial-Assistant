import QtQuick
import QtQuick.Layouts
import "../components"

/* 评分设置对话框（阶段 4b）—— 制造与贸易共用这一份。
 *
 * 对照 Widgets 版 `ui_pyside6/views/score_dialogs.py` 的 `MfgDlg` / `TradeDlg`：
 * 上半是两种模式共有的物品图标 + 区域 + 人物，
 * 制造模式多一行「设施税」，贸易模式多「卖出区域 / 买价 / 卖价」三行。
 * 由桥的 `isTrade` 决定显示哪一组 —— 与 `InputDialog.qml` 按 `mode` 切控件同一个套路。
 *
 * 与 Widgets 版的排版差异（有意，不影响取值）：
 *   1. 税率的「 %」原版是 `QDoubleSpinBox.setSuffix()`，QML 的 SpinBox 没有 suffix
 *      属性。这里把「%」放成紧跟其后的一个 Text —— 自定义 `textFromValue` 会和
 *      FDoubleSpinBox 自带的 DoubleValidator（按 decimals 校验）打架，改后缀等于
 *      顺带改了输入解析，不值得为两个字冒险。
 *   2. 图标行在原版是 `addStretch / label / addStretch` 的居中行；这里用
 *      `Layout.alignment` 居中，效果一致。
 */

FDialogFrame {
    id: frame

    readonly property var sc: typeof bridge !== "undefined" ? bridge : null

    dlg: frame.sc
    acceptText: qsTr("确定")

    Image {
        Layout.alignment: Qt.AlignHCenter
        visible: frame.sc ? frame.sc.hasIcon : false
        source: frame.sc ? frame.sc.iconUrl : ""
        width: 32
        height: 32
        sourceSize.width: 32
        sourceSize.height: 32
        smooth: true
        fillMode: Image.PreserveAspectFit
    }

    // ── 制造：中心 ── / ── 贸易：买入 ──
    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spacingSm

        Text {
            text: frame.sc && frame.sc.isTrade ? qsTr("买入:") : qsTr("中心:")
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }

        FComboBox {
            objectName: "hubBox"
            Layout.fillWidth: true
            model: frame.sc ? frame.sc.hubs : []
            currentIndex: frame.sc ? frame.sc.hubIndex : 0
            onActivated: if (frame.sc)
                frame.sc.setHubIndex(currentIndex)
        }
    }

    // ── 贸易：卖出区域 ──
    RowLayout {
        Layout.fillWidth: true
        visible: frame.sc ? frame.sc.isTrade : false
        spacing: Theme.spacingSm

        Text {
            text: qsTr("卖出:")
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }

        FComboBox {
            objectName: "sellHubBox"
            Layout.fillWidth: true
            model: frame.sc ? frame.sc.hubs : []
            currentIndex: frame.sc ? frame.sc.sellHubIndex : 0
            onActivated: if (frame.sc)
                frame.sc.setSellHubIndex(currentIndex)
        }
    }

    // ── 贸易：买价类型 ──
    RowLayout {
        Layout.fillWidth: true
        visible: frame.sc ? frame.sc.isTrade : false
        spacing: Theme.spacingSm

        Text {
            text: qsTr("买价:")
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }

        FComboBox {
            objectName: "buySideBox"
            Layout.fillWidth: true
            model: frame.sc ? frame.sc.sides : []
            currentIndex: frame.sc ? frame.sc.buySideIndex : 0
            onActivated: if (frame.sc)
                frame.sc.setBuySideIndex(currentIndex)
        }
    }

    // ── 贸易：卖价类型 ──
    RowLayout {
        Layout.fillWidth: true
        visible: frame.sc ? frame.sc.isTrade : false
        spacing: Theme.spacingSm

        Text {
            text: qsTr("卖价:")
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }

        FComboBox {
            objectName: "sellSideBox"
            Layout.fillWidth: true
            model: frame.sc ? frame.sc.sides : []
            currentIndex: frame.sc ? frame.sc.sellSideIndex : 0
            onActivated: if (frame.sc)
                frame.sc.setSellSideIndex(currentIndex)
        }
    }

    // ── 制造：设施税 ──
    RowLayout {
        Layout.fillWidth: true
        visible: frame.sc ? !frame.sc.isTrade : false
        spacing: Theme.spacingSm

        Text {
            text: qsTr("设施税:")
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }

        FDoubleSpinBox {
            objectName: "taxBox"
            Layout.fillWidth: true
            from: 0
            to: 100
            decimals: 2
            value: frame.sc ? frame.sc.tax : 0
            onValueModified: if (frame.sc)
                frame.sc.setTax(value)
        }

        Text {
            text: qsTr("%")
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }
    }

    // ── 共有：人物 ──
    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spacingSm

        Text {
            text: qsTr("人物:")
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }

        FComboBox {
            objectName: "charBox"
            Layout.fillWidth: true
            model: frame.sc ? frame.sc.characters : []
            currentIndex: frame.sc ? frame.sc.charIndex : 0
            onActivated: if (frame.sc)
                frame.sc.setCharIndex(currentIndex)
        }
    }

    Item {
        Layout.fillHeight: true
    }
}
