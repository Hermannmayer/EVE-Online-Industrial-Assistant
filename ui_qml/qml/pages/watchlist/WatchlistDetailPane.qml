import QtQuick
import QtQuick.Controls
import "../../components"

/* 关注 Tab 的**右详情面板**（关注页 = 左窄列表 + 本面板，见 `WatchlistPage.qml`）。

   数据全部来自 `ui_qml/bridge/watchlist_bridge.py`（本组件只画，不取数、不写库）：

     ① 价格对比表：`watch.detail.rows`（当前 / 加入时 / 30 / 90 / 180 天前 +
        涨跌绝对值 + 涨跌%，每行带口径标签）
     ② 主物品折线：`watch.priceSeries`（成交均价）+ `watch.volumeSeries`（成交量）
     ③ 勾选「显示制造材料」→ `watch.materialRows` / `watch.materialSeries`（BOM 2 级展开，
        子项**基期=100** 归一化叠加由 `FLineChart` 的 `normalize: true` 完成）

   **缺数据一律显示 `—`**（桥给的就是 `—`，本组件不做 0 兜底）。

   两条有意为之的选择，写在这里免得后人「优化」回去：

   - **成交量另开一个面板**，不叠在价格图上：`FLineChart` 只有一根 y 轴（`normalize` 又是
     全图开关），价格（个位数 ~ 上亿）与成交量（可到上千万）差 5~6 个数量级，叠在一起
     必然有一条被压成直线。
   - 内容用 `Flickable + Column`，**不用 `ScrollView`**：ScrollView 会把子项宽度与内容的
     implicitWidth 绑成环（见 `TradeCartWindow.qml` 的同款说明），整块内容会塌成隐式宽度。
*/

Item {
    id: pane

    //: 关注桥（由页面以属性传入；**不要**与 context property 同名，同名会遮蔽它）
    property var watch: null

    readonly property int fntBase: Math.round(12 * Theme.fontScale)
    readonly property int fntSmall: Math.round(11 * Theme.fontScale)
    readonly property int fntTitle: Math.round(14 * Theme.fontScale)
    readonly property int rowH: Math.max(24, Math.round(12 * Theme.fontScale) + 12)
    readonly property int headerH: Math.max(24, fntSmall + 14)
    readonly property int pad: Theme.spacingSm

    readonly property var detail: pane.watch ? pane.watch.detail : null
    readonly property bool hasDetail: !!(pane.detail && pane.detail.valid)
    readonly property var detailRows: (pane.detail && pane.detail.rows) ? pane.detail.rows : []
    readonly property var priceSeries: pane.watch ? pane.watch.priceSeries : []
    readonly property var volumeSeries: pane.watch ? pane.watch.volumeSeries : []
    readonly property var chartLabels: pane.watch ? pane.watch.chartLabels : []
    readonly property bool showMaterials: pane.watch ? pane.watch.showMaterials : false
    readonly property var materialRows: pane.watch ? pane.watch.materialRows : []
    readonly property var materialSeries: pane.watch ? pane.watch.materialSeries : []
    readonly property string materialHint: pane.watch ? pane.watch.materialHint : ""

    /* 选中物品的 type_id —— 用它判断「换物品了」再回填备注框。
       不让备注框直接绑 `detail.note`：那样每 60 秒轮询都会把正在输入的内容冲掉。 */
    readonly property int selectedTypeId: (pane.detail && pane.detail.valid) ? pane.detail.typeId : 0

    onSelectedTypeIdChanged: noteField.text = (pane.detail && pane.detail.note) ? pane.detail.note : ""

    //: 对比表 5 列的宽度权重 —— 表头与数据行共用这一份，改一处即可
    readonly property var cmpWeights: [0.24, 0.16, 0.20, 0.20, 0.20]
    //: 材料表 6 列（名称 / 层级 / 数量 / 挂单价 / 30 天前 / 涨跌%）
    readonly property var matWeights: [0.30, 0.08, 0.16, 0.16, 0.15, 0.15]

    function cmpWidth(i) {
        return Math.round(cmpTable.width * pane.cmpWeights[i])
    }

    function matWidth(i) {
        return Math.round(matTable.width * pane.matWeights[i])
    }

    /*: 涨跌染色：正 = 涨（绿）、负 = 跌（红）、算不出（null/undefined/0）= 次要色。
       注意对比表的涨跌是**相对当前**：负值意味着那一档比现在贵（当时更高）。 */
    function deltaColor(value) {
        if (value === null || value === undefined || value === 0)
            return Theme.textSecondary
        return value > 0 ? Theme.accentGreen : Theme.accentRed
    }

    //: 右详情里的阈值按钮 → 由页面弹弹层（弹层目标行 = 当前选中行）
    signal thresholdRequested(string kind)

    // ── 两个小单元格（表头 / 数据），只在本文件内用 ────────────────

    component HeadCell: Item {
        id: hcell
        property string text: ""
        property bool alignRight: false

        implicitHeight: pane.headerH

        Rectangle {
            anchors.fill: parent
            color: Theme.bgSurface
        }
        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 1
            color: Theme.border
        }
        Text {
            anchors.fill: parent
            anchors.leftMargin: 6
            anchors.rightMargin: 6
            verticalAlignment: Text.AlignVCenter
            horizontalAlignment: hcell.alignRight ? Text.AlignRight : Text.AlignLeft
            text: hcell.text
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: pane.fntSmall
            elide: Text.ElideRight
        }
    }

    component DataCell: Item {
        id: dcell
        property string text: ""
        property bool alignRight: false
        property color fg: Theme.textPrimary
        property color cellBg: "transparent"
        //: 层级缩进（材料表用）
        property int indent: 0

        implicitHeight: pane.rowH

        Rectangle {
            anchors.fill: parent
            color: dcell.cellBg
        }
        Text {
            anchors.fill: parent
            anchors.leftMargin: 6 + dcell.indent
            anchors.rightMargin: 6
            verticalAlignment: Text.AlignVCenter
            horizontalAlignment: dcell.alignRight ? Text.AlignRight : Text.AlignLeft
            text: dcell.text
            color: dcell.fg
            font.family: dcell.alignRight ? "Consolas" : Theme.fontFamily
            font.pixelSize: pane.fntBase
            elide: Text.ElideRight
        }
    }

    Flickable {
        id: flick
        anchors.fill: parent
        clip: true
        contentHeight: pane.hasDetail ? bodyCol.height : emptyText.height
        ScrollBar.vertical: ScrollBar {
            policy: ScrollBar.AsNeeded
        }

        // ── 空态：没选中任何关注 ────────────────────────────────
        Text {
            id: emptyText
            width: flick.width
            height: Math.round(90 * Theme.fontScale)
            visible: !pane.hasDetail
            text: qsTr("在左侧选择一项关注，这里显示它的价格对比、走势与制造材料")
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: pane.fntBase
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            wrapMode: Text.WordWrap
        }

        Column {
            id: bodyCol
            width: flick.width
            visible: pane.hasDetail
            spacing: Theme.spacingMd

            // ═══════════════════════════════════════════════════
            //  0. 头部：名称 + 备注 + 阈值入口
            // ═══════════════════════════════════════════════════

            Column {
                width: parent.width
                spacing: Theme.spacingXs

                Row {
                    spacing: pane.pad

                    Text {
                        text: pane.hasDetail ? pane.detail.name : ""
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: pane.fntTitle
                        font.bold: true
                    }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: pane.hasDetail ? ("Type " + pane.detail.typeId) : ""
                        color: Theme.textSecondary
                        font.family: Theme.fontFamily
                        font.pixelSize: pane.fntSmall
                    }
                }

                Row {
                    spacing: pane.pad

                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: qsTr("备注")
                        color: Theme.textSecondary
                        font.family: Theme.fontFamily
                        font.pixelSize: pane.fntSmall
                    }
                    FTextField {
                        id: noteField
                        width: 200
                        placeholderText: qsTr("可选（回车/失焦提交）")
                        Component.onCompleted: noteField.text = (pane.detail && pane.detail.note) ? pane.detail.note : ""
                        onEditingFinished: if (pane.watch)
                            pane.watch.setRowNote(noteField.text)
                    }
                    FButton {
                        text: qsTr("设置买价阈值")
                        onClicked: pane.thresholdRequested("buy")
                    }
                    FButton {
                        text: qsTr("设置卖价阈值")
                        onClicked: pane.thresholdRequested("sell")
                    }
                }
            }

            // ═══════════════════════════════════════════════════
            //  1. 价格对比表：当前 / 加入时 / 30 / 90 / 180 天前
            // ═══════════════════════════════════════════════════

            Column {
                width: parent.width
                spacing: Theme.spacingXs

                Text {
                    text: qsTr("价格对比")
                    color: Theme.textPrimary
                    font.family: Theme.fontFamily
                    font.pixelSize: pane.fntBase
                    font.bold: true
                }

                Column {
                    id: cmpTable
                    width: parent.width
                    spacing: 0

                    Row {
                        HeadCell {
                            width: pane.cmpWidth(0)
                            text: qsTr("档位")
                        }
                        HeadCell {
                            width: pane.cmpWidth(1)
                            text: qsTr("口径")
                        }
                        HeadCell {
                            width: pane.cmpWidth(2)
                            text: qsTr("价格")
                            alignRight: true
                        }
                        HeadCell {
                            width: pane.cmpWidth(3)
                            text: qsTr("涨跌")
                            alignRight: true
                        }
                        HeadCell {
                            width: pane.cmpWidth(4)
                            text: qsTr("涨跌%")
                            alignRight: true
                        }
                    }

                    Repeater {
                        model: pane.detailRows

                        delegate: Row {
                            required property var modelData
                            required property int index

                            DataCell {
                                width: pane.cmpWidth(0)
                                text: String(modelData.label)
                                cellBg: index % 2 ? Theme.bgDark : Theme.bgSurface
                            }
                            DataCell {
                                width: pane.cmpWidth(1)
                                text: String(modelData.caliber)
                                fg: Theme.textSecondary
                                cellBg: index % 2 ? Theme.bgDark : Theme.bgSurface
                            }
                            DataCell {
                                width: pane.cmpWidth(2)
                                text: String(modelData.text)
                                alignRight: true
                                cellBg: index % 2 ? Theme.bgDark : Theme.bgSurface
                            }
                            DataCell {
                                width: pane.cmpWidth(3)
                                text: String(modelData.deltaText)
                                alignRight: true
                                fg: pane.deltaColor(modelData.delta)
                                cellBg: index % 2 ? Theme.bgDark : Theme.bgSurface
                            }
                            DataCell {
                                width: pane.cmpWidth(4)
                                text: String(modelData.pctText)
                                alignRight: true
                                fg: pane.deltaColor(modelData.delta)
                                cellBg: index % 2 ? Theme.bgDark : Theme.bgSurface
                            }
                        }
                    }
                }

                Text {
                    width: parent.width
                    text: pane.hasDetail ? pane.detail.hint : ""
                    color: Theme.textSecondary
                    font.family: Theme.fontFamily
                    font.pixelSize: pane.fntSmall
                    wrapMode: Text.WordWrap
                }
            }

            // ═══════════════════════════════════════════════════
            //  2. 主物品折线：成交均价 + 成交量（**两个面板**，理由见文件头）
            // ═══════════════════════════════════════════════════

            Text {
                text: qsTr("成交均价（近 180 天）")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: pane.fntBase
                font.bold: true
            }
            FLineChart {
                objectName: "priceChart"
                width: parent.width
                height: Math.round(170 * Theme.fontScale)
                series: pane.priceSeries
                xLabels: pane.chartLabels
                emptyText: qsTr("本地没有成交历史（先「更新价格」）")
            }

            Text {
                text: qsTr("成交量（近 180 天）")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: pane.fntBase
                font.bold: true
            }
            FLineChart {
                objectName: "volumeChart"
                width: parent.width
                height: Math.round(130 * Theme.fontScale)
                series: pane.volumeSeries
                xLabels: pane.chartLabels
                emptyText: qsTr("本地没有成交历史（先「更新价格」）")
            }

            // ═══════════════════════════════════════════════════
            //  3. 制造材料：BOM 逐级展开 + 基期=100 归一化叠加
            // ═══════════════════════════════════════════════════

            FCheckBox {
                id: materialBox
                text: qsTr("显示制造材料")
                checked: pane.showMaterials
                onClicked: if (pane.watch)
                    pane.watch.setShowMaterials(checked)
            }

            Text {
                width: parent.width
                visible: pane.showMaterials
                text: pane.materialHint
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: pane.fntSmall
                wrapMode: Text.WordWrap
            }

            /* 子项折线：`normalize: true` → 每条线按**自己的首点**归一到 100（见 FLineChart.valuesOf）。
               绝对值在下面的材料表里。 */
            FLineChart {
                objectName: "materialChart"
                width: parent.width
                height: Math.round(200 * Theme.fontScale)
                visible: pane.showMaterials
                normalize: true
                series: pane.materialSeries
                emptyText: qsTr("本地没有材料挂单快照（先「更新价格」）")
            }

            Column {
                id: matTable
                width: parent.width
                visible: pane.showMaterials && pane.materialRows.length > 0
                spacing: 0

                Row {
                    HeadCell {
                        width: pane.matWidth(0)
                        text: qsTr("材料")
                    }
                    HeadCell {
                        width: pane.matWidth(1)
                        text: qsTr("层级")
                        alignRight: true
                    }
                    HeadCell {
                        width: pane.matWidth(2)
                        text: qsTr("数量")
                        alignRight: true
                    }
                    HeadCell {
                        width: pane.matWidth(3)
                        text: qsTr("挂单价")
                        alignRight: true
                    }
                    HeadCell {
                        width: pane.matWidth(4)
                        text: qsTr("30 天前")
                        alignRight: true
                    }
                    HeadCell {
                        width: pane.matWidth(5)
                        text: qsTr("涨跌%")
                        alignRight: true
                    }
                }

                Repeater {
                    model: pane.materialRows

                    delegate: Row {
                        required property var modelData
                        required property int index

                        DataCell {
                            width: pane.matWidth(0)
                            text: String(modelData.name)
                            indent: Number(modelData.indent) || 0
                            cellBg: index % 2 ? Theme.bgDark : Theme.bgSurface
                        }
                        DataCell {
                            width: pane.matWidth(1)
                            text: String(modelData.level)
                            alignRight: true
                            fg: Theme.textSecondary
                            cellBg: index % 2 ? Theme.bgDark : Theme.bgSurface
                        }
                        DataCell {
                            width: pane.matWidth(2)
                            text: String(modelData.qtyText)
                            alignRight: true
                            cellBg: index % 2 ? Theme.bgDark : Theme.bgSurface
                        }
                        DataCell {
                            width: pane.matWidth(3)
                            text: String(modelData.priceText)
                            alignRight: true
                            cellBg: index % 2 ? Theme.bgDark : Theme.bgSurface
                        }
                        DataCell {
                            width: pane.matWidth(4)
                            text: String(modelData.agoText)
                            alignRight: true
                            cellBg: index % 2 ? Theme.bgDark : Theme.bgSurface
                        }
                        DataCell {
                            width: pane.matWidth(5)
                            text: String(modelData.pctText)
                            alignRight: true
                            fg: pane.deltaColor(modelData.pct)
                            cellBg: index % 2 ? Theme.bgDark : Theme.bgSurface
                        }
                    }
                }
            }

            Item {
                width: parent.width
                height: pane.pad
            }
        }
    }
}
