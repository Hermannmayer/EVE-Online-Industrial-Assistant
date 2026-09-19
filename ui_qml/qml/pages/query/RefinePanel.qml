import QtQuick
import QtQuick.Controls
import "../../components"

/* 详情面板 · 精炼产物与价格（底部「总计、价格」）。
 *
 * 对应界面标注图「精炼产物、价格 / 总计、价格」。
 *
 * **产率不是常数**：它由所选**人物的提炼技能**与**精炼站点**共同决定
 * （`core/eve_formulas.calc_refining_yield`：基础 ×(1+3%×提炼学概论) ×(1+2%×提炼效率理论)，
 * 上限按 NPC 站 / 玩家结构分别施加）。所以顶部给人物 / 数量 / 站点三个输入，
 * 一律**先改桥、再由桥重算**（`setRefineCharIndex` / `setRefineQty` / `setRefineFacility`），
 * 与材料面板的「制造数量 / 价格中心」同一条约定：本文件只渲染，不做任何计算。
 *
 * 人物的提炼技能在**人物设置 → 精炼**分类里填（`char_settings_common.SKILL_CATEGORIES`）。
 */
Item {
    id: root

    //: `bridge.detail`
    property var detail: null

    readonly property int fntSmall: Math.round(11 * Theme.fontScale)
    readonly property int fntBase: Math.round(12 * Theme.fontScale)
    readonly property int barH: Math.max(24, Math.round(14 * Theme.fontScale) + 10)
    readonly property int totalH: Math.max(20, fntBase + 10)
    //: 输入区占两行（人物+数量 / 站点）—— 左列只有约 0.28 屏宽，三件控件挤一行会互相压
    readonly property int inputH: root.barH * 2 + Theme.spacingXs
    readonly property int labelW: Math.round(34 * Theme.fontScale)

    /* 精炼行 → 表格单元格（字段映射，不做任何格式化 —— 文本已由桥算好）。
     *
     * **不能直接把 `refineRows` 喂给 `PanelTable`**：那个组件的 delegate 只读
     * `modelData.cells`（见 `PanelTable.qml` 的数据形状说明），而 `refine_rows()` 产出的是
     * `{name, qtyText, sourceName, yieldText, valueText, profitText, profitPos}` —— 没有
     * `cells`。直接喂进去每行都是空 Item，而 `rows.length > 0` 又把 `emptyText` 藏了，
     * 面板就只剩表头。字段映射与 `MaterialPanel` 同款。
     *
     * 只渲染表头声明的那四列。`sourceName` / `profitText` / `profitPos` 不在这里用：
     * 本桥只精炼**单个**物品，来源与利润对每个产出行都相同，逐行重复没有信息量，
     * 利润已在下方总计行给出。 */
    readonly property var refineCells: {
        const src = root.detail ? root.detail.refineRows : []
        const out = []
        for (let i = 0; i < src.length; ++i) {
            const r = src[i]
            out.push({
                "cells": [
                    { "text": String(r.name), "align": "left" },
                    { "text": String(r.qtyText), "align": "right" },
                    { "text": String(r.yieldText), "align": "right" },
                    { "text": String(r.valueText), "align": "right" }
                ]
            })
        }
        return out
    }

    Column {
        anchors.fill: parent
        spacing: Theme.spacingXs

        // ══ 输入：人物 / 数量 / 站点 ══════════════════════════
        Column {
            width: parent.width
            spacing: Theme.spacingXs

            Row {
                width: parent.width
                height: root.barH
                spacing: Theme.spacingSm

                Text {
                    width: root.labelW
                    height: parent.height
                    verticalAlignment: Text.AlignVCenter
                    text: qsTr("人物")
                    color: Theme.textSecondary
                    font.family: Theme.fontFamily
                    font.pixelSize: root.fntSmall
                }

                /* **不要用绑定写 `currentIndex`**：人物列表是先空后有的
                 * （`detail.charNames` 在桥读完 `char_config.json` 之前是 `[]`），而在空模型上
                 * 把 `currentIndex` 置 0 会被 Qt 夹成 **-1**，之后模型填上了也**不会自动纠正**。
                 * 与 `MaterialPanel` 的价格中心下拉同一个坑，故同样显式同步。 */
                FComboBox {
                    id: charBox
                    width: Math.max(72, parent.width - 2 * root.labelW - qtyBox.width - 3 * Theme.spacingSm)
                    height: parent.height
                    model: root.detail ? root.detail.charNames : []

                    function syncIndex() {
                        if (!root.detail || count <= 0)
                            return
                        currentIndex = Math.max(0, Math.min(root.detail.refineCharIndex, count - 1))
                    }

                    onCountChanged: syncIndex()
                    Component.onCompleted: syncIndex()
                    onActivated: if (root.detail)
                        root.detail.setRefineCharIndex(currentIndex)

                    // 换物品 / 桥内容变了也同步一次，避免下拉与后端脱节
                    Connections {
                        target: root.detail
                        function onChanged() {
                            charBox.syncIndex()
                        }
                    }
                }

                Text {
                    width: root.labelW
                    height: parent.height
                    verticalAlignment: Text.AlignVCenter
                    text: qsTr("数量")
                    color: Theme.textSecondary
                    font.family: Theme.fontFamily
                    font.pixelSize: root.fntSmall
                }

                FSpinBox {
                    id: qtyBox
                    width: Math.round(78 * Theme.fontScale)
                    height: parent.height
                    from: 1
                    to: 1000000
                    value: root.detail ? root.detail.refineQty : 1
                    onValueModified: if (root.detail)
                        root.detail.setRefineQty(value)
                }
            }

            Row {
                width: parent.width
                height: root.barH
                spacing: Theme.spacingSm

                Text {
                    width: root.labelW
                    height: parent.height
                    verticalAlignment: Text.AlignVCenter
                    text: qsTr("站点")
                    color: Theme.textSecondary
                    font.family: Theme.fontFamily
                    font.pixelSize: root.fntSmall
                }

                FComboBox {
                    id: facilityBox
                    width: parent.width - root.labelW - Theme.spacingSm
                    height: parent.height
                    //: 0 = NPC 空间站（基础产率低、上限低）；1 = 玩家设施 / Upwell 结构
                    model: [qsTr("NPC 空间站"), qsTr("玩家设施")]
                    // 模型是静态的（不像人物列表先空后有），可以直接用绑定
                    currentIndex: root.detail && root.detail.refineFacility ? 1 : 0
                    onActivated: if (root.detail)
                        root.detail.setRefineFacility(currentIndex === 1)
                }
            }
        }

        // ══ 产出表 ════════════════════════════════════════════
        PanelTable {
            width: parent.width
            height: parent.height - root.inputH - root.totalH - 2 * Theme.spacingXs
            headers: [qsTr("产出材料"), qsTr("数量"), qsTr("产率"), qsTr("价值 (ISK)")]
            ratios: [2.2, 1.0, 0.9, 1.6]
            rows: root.refineCells
            emptyText: root.detail && root.detail.typeId > 0
                       ? qsTr("该物品不可精炼") : qsTr("选择物品查看精炼产物")
        }

        // ── 总计、价格 ────────────────────────────────────────
        Item {
            width: parent.width
            height: root.totalH

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                height: 1
                color: Theme.border
            }

            Row {
                anchors.fill: parent
                spacing: Theme.spacingSm

                Repeater {
                    model: root.detail ? root.detail.refineTotalRows : []

                    Text {
                        required property var modelData
                        height: parent.height
                        width: Math.max(60, (parent.width - 3 * Theme.spacingSm) / 4)
                        verticalAlignment: Text.AlignVCenter
                        horizontalAlignment: Text.AlignRight
                        text: String(modelData.label) + " " + String(modelData.valueText)
                        color: modelData.color && String(modelData.color) !== ""
                               ? String(modelData.color) : Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: root.fntBase
                        elide: Text.ElideRight
                    }
                }
            }
        }
    }
}
