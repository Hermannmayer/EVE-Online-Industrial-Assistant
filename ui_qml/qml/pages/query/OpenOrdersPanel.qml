import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../components"

/* 空闲态仪表盘 · 挂单列表（**买单 / 卖单各一张表**）。
 *
 * 对应界面标注图「挂单列表 / 读取订单（按钮）／游戏的订单通过游戏内导出按钮在…
 * 要考虑多份导出的信息去重问题，区分买单和卖单／通过记录联动资产记录和钱包记录／
 * 读取后弹出窗口确认订单情况（是卖出还是取消挂单）」。
 *
 * 数据来自游戏内「钱包 → 订单 → 导出」写出的本地文件，**目录固定**
 * `Documents\EVE\logs\Marketlogs`（用户要求：不再提供自定义目录输入框，
 * 免得那一行长期占着面板、还要为一个几乎不变的值留输入框）。
 * **去重靠订单 ID 做主键** —— 反复导入同一份导出是幂等的。
 *
 * 导入后由桥弹「订单变动」确认框（`dialogs/OrderChangeDialog.qml`）：逐条选
 * 「买到了 / 卖完了」或「手动撤销」，确认后桥按成交增减钱包余额。
 * 弹窗在桥里弹（`OrderChangeQmlDialog`）：服务函数是无 parent 的、validate 档会在
 * 无 QApplication 下直调它们（见 `docs/dev/flows.md`），所以交互只能由持有 shell 的桥做。
 */
Item {
    id: root

    //: `bridge.dashboard`
    property var dashboard: null

    readonly property int fntSmall: Math.round(11 * Theme.fontScale)
    readonly property int barH: Math.max(22, Math.round(14 * Theme.fontScale) + 8)
    readonly property int rowH: Math.max(20, fntSmall + 9)
    readonly property int headRowH: Math.max(18, fntSmall + 6)

    //: 两张表各自一行标题（「买单 · N 笔」/「卖单 · N 笔」）。与详情页 OrderPanel 同做法。
    readonly property var heads: dashboard ? dashboard.openOrderHeads : []
    //: 列宽比：物品 / 价格 / 剩余·总量 / 位置（**没有方向列** —— 表本身就是方向）
    readonly property var ratios: [2.6, 1.5, 1.6, 2.4]

    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.spacingXs

        // ── 读取订单 ──────────────────────────────────────────
        RowLayout {
            Layout.fillWidth: true
            height: root.barH
            spacing: Theme.spacingXs

            FButton {
                objectName: "readOrdersButton"
                text: qsTr("读取订单")
                primary: true
                Layout.preferredHeight: root.barH
                enabled: root.dashboard !== null && !root.dashboard.busy
                onClicked: if (root.dashboard)
                    root.dashboard.readOrders()
            }

            Text {
                Layout.fillWidth: true
                verticalAlignment: Text.AlignVCenter
                text: root.dashboard ? root.dashboard.statusText : ""
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: root.fntSmall
                elide: Text.ElideRight

                HoverHandler {
                    id: statusHover
                }
                ToolTip.visible: statusHover.hovered
                ToolTip.text: root.dashboard ? root.dashboard.statusText : ""
            }
        }

        // ── 钱包余额（手填，参与资产快照；订单变动也会自动加减）──
        RowLayout {
            Layout.fillWidth: true
            height: root.barH
            spacing: Theme.spacingXs

            Text {
                text: qsTr("钱包余额")
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: root.fntSmall
            }

            FTextField {
                id: walletField
                objectName: "walletField"
                Layout.fillWidth: true
                Layout.preferredHeight: root.barH
                placeholderText: qsTr("填写当前钱包 ISK，用于资产折线图")
                text: root.dashboard ? root.dashboard.walletText : ""
                onAccepted: if (root.dashboard)
                    root.dashboard.setWalletText(text)
            }

            FButton {
                text: qsTr("记录")
                Layout.preferredHeight: root.barH
                onClicked: if (root.dashboard)
                    root.dashboard.setWalletText(walletField.text)
            }
        }

        // ── 买单（上）────────────────────────────────────────
        Text {
            Layout.fillWidth: true
            Layout.preferredHeight: root.headRowH
            verticalAlignment: Text.AlignVCenter
            text: qsTr("买单 · %1 笔").arg(root.dashboard ? root.dashboard.buyOrderCount : 0)
            color: Theme.accentGreen
            font.family: Theme.fontFamily
            font.pixelSize: root.fntSmall
        }

        PanelTable {
            objectName: "buyOrdersTable"
            Layout.fillWidth: true
            Layout.fillHeight: true
            headers: root.heads
            ratios: root.ratios
            rows: root.dashboard ? root.dashboard.buyOrderRows : []
            emptyText: root.dashboard ? root.dashboard.buyEmptyText : ""
        }

        // ── 卖单（下）────────────────────────────────────────
        Text {
            Layout.fillWidth: true
            Layout.preferredHeight: root.headRowH
            verticalAlignment: Text.AlignVCenter
            text: qsTr("卖单 · %1 笔").arg(root.dashboard ? root.dashboard.sellOrderCount : 0)
            color: Theme.accentRed
            font.family: Theme.fontFamily
            font.pixelSize: root.fntSmall
        }

        PanelTable {
            objectName: "sellOrdersTable"
            Layout.fillWidth: true
            Layout.fillHeight: true
            headers: root.heads
            ratios: root.ratios
            rows: root.dashboard ? root.dashboard.sellOrderRows : []
            emptyText: root.dashboard ? root.dashboard.sellEmptyText : ""
        }

        // ── 汇总 ──────────────────────────────────────────────
        Text {
            Layout.fillWidth: true
            height: root.rowH
            verticalAlignment: Text.AlignVCenter
            horizontalAlignment: Text.AlignRight
            text: root.dashboard ? root.dashboard.openOrderSummary : ""
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: root.fntSmall
            elide: Text.ElideRight
        }
    }
}
