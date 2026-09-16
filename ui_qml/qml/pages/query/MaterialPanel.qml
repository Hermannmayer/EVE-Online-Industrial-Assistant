import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../components"

/* 详情面板 · 制造所需的材料与价格。
 *
 * 对应界面标注图「制造所需的材料 / 制造数量输入框（默认为 1）/ 价格中心下拉框选择 /
 * 各种材料价格（买单、卖单）/ 总计、价格」。
 *
 * 数量与价格中心都是**先改桥、再由桥重算**（`setMaterialQty` / `setMaterialHubIndex`），
 * 本文件不自己乘数量 —— 那样买入价与卖出价会各乘一遍、与「总计」对不上。
 */
Item {
    id: root

    //: `bridge.detail`
    property var detail: null

    readonly property int fntSmall: Math.round(11 * Theme.fontScale)
    readonly property int fntBase: Math.round(12 * Theme.fontScale)
    readonly property int barH: Math.max(24, Math.round(14 * Theme.fontScale) + 10)

    //: 材料行 → 表格单元格（字段映射，不做任何格式化 —— 文本已由桥算好）
    readonly property var materialCells: {
        const src = root.detail ? root.detail.materialRows : []
        const out = []
        for (let i = 0; i < src.length; ++i) {
            const r = src[i]
            out.push({
                "cells": [
                    { "text": String(r.name), "align": "left" },
                    { "text": String(r.qtyText), "align": "right" },
                    { "text": String(r.buyText), "align": "right", "color": String(Theme.accentGreen) },
                    { "text": String(r.sellText), "align": "right", "color": String(Theme.accentRed) },
                    { "text": String(r.totalSellText), "align": "right" }
                ]
            })
        }
        return out
    }

    Column {
        anchors.fill: parent
        spacing: Theme.spacingXs

        // ── 数量 + 价格中心 ────────────────────────────────────
        RowLayout {
            width: parent.width
            height: root.barH
            spacing: Theme.spacingSm

            Text {
                text: qsTr("制造数量")
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: root.fntSmall
            }

            FSpinBox {
                id: qtyBox
                from: 1
                to: 1000000
                Layout.preferredWidth: Math.round(96 * Theme.fontScale)
                Layout.preferredHeight: Math.round(26 * Theme.fontScale)
                value: root.detail ? root.detail.materialQty : 1
                onValueModified: if (root.detail)
                    root.detail.setMaterialQty(value)
            }

            Text {
                text: qsTr("价格中心")
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: root.fntSmall
            }

            FComboBox {
                id: hubBox
                Layout.preferredWidth: Math.round(88 * Theme.fontScale)
                Layout.preferredHeight: Math.round(26 * Theme.fontScale)
                model: root.detail ? root.detail.hubNames : []

                /* **不要用绑定写 currentIndex**：模型是先空后有的
                 * （`detail.hubNames` 在桥建好之前是 `[]`），而在空模型上把 currentIndex
                 * 置 0 会被 Qt 夹成 **-1**，之后模型填上了也**不会自动纠正** ——
                 * 实测表现是下拉框里显示灰色的占位文字，而不是当前的价格中心。
                 * 工具栏那个「区域」下拉没这个问题，纯粹因为它的 model 一开始就是满的。
                 * 所以这里改成显式同步（模型变化 / 桥的内容变化 / 首次加载各同步一次）。 */
                function syncHubIndex() {
                    if (!root.detail || count <= 0)
                        return
                    currentIndex = Math.max(0, Math.min(root.detail.materialHubIndex, count - 1))
                }

                onCountChanged: syncHubIndex()
                Component.onCompleted: syncHubIndex()
                onActivated: if (root.detail)
                    root.detail.setMaterialHubIndex(currentIndex)

                // 桥的内容变了（换物品、价格中心回落后端）也同步一次，避免下拉与后端脱节
                Connections {
                    target: root.detail
                    function onChanged() {
                        hubBox.syncHubIndex()
                    }
                }
            }

            Item {
                Layout.fillWidth: true
            }
        }

        // ── 材料表 ────────────────────────────────────────────
        PanelTable {
            width: parent.width
            height: parent.height - root.barH - root.totalH - 2 * Theme.spacingXs
            headers: [qsTr("材料"), qsTr("数量"), qsTr("买单价"), qsTr("卖单价"), qsTr("合计 (卖价)")]
            ratios: [2.2, 1.0, 1.3, 1.3, 1.6]
            rows: root.materialCells
            emptyText: root.detail && root.detail.typeId > 0
                       ? qsTr("该物品没有制造配方") : qsTr("选择一行查看制造材料")
        }

        // ── 总计、价格 ────────────────────────────────────────
        Item {
            id: totalBox
            width: parent.width
            height: root.fntBase + 10

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                height: 1
                color: Theme.border
            }

            Text {
                anchors.fill: parent
                verticalAlignment: Text.AlignVCenter
                horizontalAlignment: Text.AlignRight
                text: root.detail ? root.detail.materialSummary : ""
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: root.fntBase
                elide: Text.ElideRight
            }
        }
    }
}
