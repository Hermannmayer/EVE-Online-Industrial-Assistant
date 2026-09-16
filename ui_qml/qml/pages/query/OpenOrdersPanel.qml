import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../components"

/* 空闲态仪表盘 · 挂单列表。
 *
 * 对应界面标注图「挂单列表 / 读取订单（按钮）／游戏的订单通过游戏内导出按钮在…
 * 要考虑多份导出的信息去重问题，区分买单和卖单／通过记录联动资产记录和钱包记录／
 * 读取后弹出窗口确认订单情况（是卖出还是取消挂单）」。
 *
 * 数据来自游戏内「钱包 → 订单 → 导出」写出的本地文件（默认
 * `Documents\EVE\logs\Marketlogs`，可在下方改成自己的目录）。**去重靠订单 ID 做主键**
 * —— 反复导入同一份导出是幂等的；「这次导出里没出现的旧订单」由桥统计后弹窗问用户
 * 是否标记为已结束，**不自动删**。
 *
 * 弹窗在桥里弹（`FMessageDialog.question`）：服务函数是无 parent 的、validate 档会在
 * 无 QApplication 下直调它们（见 `docs/dev/flows.md`），所以确认只能由持有 shell 的桥做。
 */
Item {
    id: root

    //: `bridge.dashboard`
    property var dashboard: null

    readonly property int fntSmall: Math.round(11 * Theme.fontScale)
    readonly property int barH: Math.max(22, Math.round(14 * Theme.fontScale) + 8)
    readonly property int rowH: Math.max(20, fntSmall + 9)

    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.spacingXs

        // ── 读取订单 ──────────────────────────────────────────
        RowLayout {
            Layout.fillWidth: true
            height: root.barH
            spacing: Theme.spacingXs

            FButton {
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

        // ── 导出目录（可改）──────────────────────────────────
        RowLayout {
            Layout.fillWidth: true
            height: root.barH
            spacing: Theme.spacingXs

            Text {
                text: qsTr("导出目录")
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: root.fntSmall
            }

            FTextField {
                id: dirField
                Layout.fillWidth: true
                Layout.preferredHeight: root.barH
                placeholderText: qsTr("留空则用默认目录 Documents\\EVE\\logs\\Marketlogs")
                text: root.dashboard ? root.dashboard.exportDir : ""
                onAccepted: if (root.dashboard)
                    root.dashboard.setExportDir(text)
            }

            FButton {
                text: qsTr("应用")
                Layout.preferredHeight: root.barH
                onClicked: if (root.dashboard)
                    root.dashboard.setExportDir(dirField.text)
            }
        }

        // ── 钱包余额（手填，参与资产快照）────────────────────
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

        // ── 挂单表 ────────────────────────────────────────────
        PanelTable {
            Layout.fillWidth: true
            Layout.fillHeight: true
            headers: root.dashboard ? root.dashboard.openOrderHeads : []
            ratios: [1.2, 2.4, 0.9, 1.4, 1.3, 2.6]
            rows: root.dashboard ? root.dashboard.openOrderRows : []
            emptyText: qsTr("暂无挂单记录 —— 在游戏「钱包 → 订单」点导出，再点上面的「读取订单」")
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
