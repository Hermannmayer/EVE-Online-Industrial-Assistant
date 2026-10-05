import QtQuick
import QtQuick.Controls
import QtQuick.Shapes

/* 通用折线图 —— 大盘指数与关注物品共用（**只画，不取数**）。

 * 为什么抽出来：`ui_qml/qml/pages/query/AssetChartPanel.qml` 已经有一套画法，
 * 大盘页与关注页都要用；两处各抄一遍就是两份会漂移的几何（克制条款：骨架第二次出现
 * 就该收敛成共享实现）。

 * **几何在这个组件里算，不在桥里**（与 `AssetChartPanel` 相反，那个的轴范围由 Python 给）：
 * 调用方只需传原始序列（`x` 是序号、`y` 是真实值），轴范围/刻度/归一化都在这里做 ——
 * 两个页面的数据形态差得远，把轴数学放桥里等于要求两个桥各写一遍。
 * ⚠️ **禁用 `Canvas`**：Qt 的 Canvas 画进离屏纹理，本仓离屏截图路径下整块是空的
 * （见 `PriceChartDialog.qml` 头部与 `AssetChartPanel.qml` 的说明）。这里用
 * `Shape + ShapePath + PathPolyline` 画线、`Rectangle` 画网格、`Text` 画轴。

 * 用法：
 *   FLineChart {
 *       series: [{ label: "矿物指数 (MPI)", color: Theme.primary,
 *                  points: [{x: 0, y: 100.0}, {x: 1, y: 101.2}] }]
 *       xLabels: ["07-27", "08-10"]     // 可选，与 points 序号对应
 *       normalize: true                 // 可选：每条线首点归一到 100（对比走势用）
 *       unit: ""                        // 可选：纵轴数值后缀
 *   }
 */
Item {
    id: chart

    //: `[{label: string, color: color, points: [{x: real, y: real}]}]`；`x` 是序号（0..n-1）
    property var series: []
    //: 横轴标签（与 `points` 的序号一一对应；空则不画）
    property var xLabels: []
    //: 开启后每条线按首点归一化到 100（多物品/多指数对比必须开，否则量级差异压成一条直线）
    property bool normalize: false
    //: 纵轴数值后缀（如 " % "）
    property string unit: ""
    property bool showLegend: true
    //: 图例可否点击切换显隐（默认可以 —— 线一多就没法看，用户要求「点名字显示/隐藏那条线」）
    property bool legendClickable: true
    //: 图表左上角的补充说明（例如「基期 2026-03-04 = 100」）；空则不画
    property string baseNote: ""
    //: 被点掉的线（存 `label`；组件内部状态，不落盘）
    property var hiddenLabels: []
    //: 鼠标悬停命中的**x 序号**（-1 = 没悬停）：竖线、圆点、数值气泡都看它
    property int hoverIndex: -1
    //: 没有任何点时显示的文案
    property string emptyText: qsTr("暂无数据")

    readonly property int fntSmall: Math.round(11 * Theme.fontScale)
    readonly property int fntBase: Math.round(12 * Theme.fontScale)
    readonly property int padL: Math.round(64 * Theme.fontScale)
    readonly property int padR: Math.round(14 * Theme.fontScale)
    readonly property int padT: Math.round(8 * Theme.fontScale)
    readonly property int padB: Math.round(22 * Theme.fontScale)
    readonly property int legendLineH: Math.max(18, fntSmall + 8)
    readonly property int legendGap: Math.round(6 * Theme.fontScale)
    //: 图例按**最多两行**预留高度（Flow 自动换行）：五条线一行放不下，会给「文字超出框」
    readonly property int legendH: showLegend ? legendLineH * 2 : 0
    readonly property int plotW: Math.max(0, width - padL - padR)
    readonly property int plotH: Math.max(0, height - padT - padB - legendH)

    //: 面板里有没有可画的点（QML 里判断用；桥不该重复算）
    readonly property bool hasData: {
        const rows = chart.series || []
        for (let i = 0; i < rows.length; ++i) {
            if (rows[i] && rows[i].points && rows[i].points.length > 0)
                return true
        }
        return false
    }

    //: 图例被点掉之后**实际参与绘制**的线（轴范围也跟着它走，否则隐藏的线会把尺度带偏）
    readonly property var visibleSeries: {
        const rows = chart.series || []
        const hidden = chart.hiddenLabels || []
        return rows.filter(function (row, index) {
            const key = row && row.label !== undefined ? row.label : String(index)
            return hidden.indexOf(key) < 0
        })
    }

    //: 点一下图例：显示 ↔ 隐藏（全隐藏时允许，用户自己再点回来）
    function toggleLabel(label, index) {
        if (!chart.legendClickable)
            return
        const key = (label !== undefined && label !== null && label !== "") ? label : String(index)
        const next = (chart.hiddenLabels || []).slice()
        const at = next.indexOf(key)
        if (at >= 0)
            next.splice(at, 1)
        else
            next.push(key)
        chart.hiddenLabels = next
    }

    function isHidden(label, index) {
        const key = (label !== undefined && label !== null && label !== "") ? label : String(index)
        return (chart.hiddenLabels || []).indexOf(key) >= 0
    }

    /* 一条线归一化后的纵值：`normalize` 时首点当 100，首点为 0/缺失则退回原始值。 */
    function valuesOf(row) {
        const out = []
        if (!row || !row.points)
            return out
        const base = row.points.length > 0 ? row.points[0].y : 0
        for (let i = 0; i < row.points.length; ++i) {
            const v = row.points[i].y
            out.push((chart.normalize && base) ? (v / base) * 100 : v)
        }
        return out
    }

    //: 全部**可见**线的纵值范围（空数据给 0..1，避免除零）—— 隐藏的线不该带偏尺度
    function valueRange() {
        let lo = Number.POSITIVE_INFINITY
        let hi = Number.NEGATIVE_INFINITY
        const rows = chart.visibleSeries
        for (let i = 0; i < rows.length; ++i) {
            const vs = chart.valuesOf(rows[i])
            for (let j = 0; j < vs.length; ++j) {
                if (vs[j] < lo)
                    lo = vs[j]
                if (vs[j] > hi)
                    hi = vs[j]
            }
        }
        if (!isFinite(lo) || !isFinite(hi))
            return { lo: 0, hi: 1 }
        if (lo === hi)  // 全平线：给一点高度，别把它压成 0 高度
            return { lo: lo - 1, hi: hi + 1 }
        return { lo: lo, hi: hi }
    }

    /* 把 [lo,hi] 抬成"好看"的刻度：步长取 1/2/5×10^n，返回 {lo, hi, step, ticks:[{pos,label}]}。
     * `pos` 是 0..1（0 在底部），与 `AssetChartPanel` 的 `yTicks` 同语义。 */
    function axisFor(lo, hi, maxTicks) {
        const span = hi - lo
        const raw = span / Math.max(2, maxTicks || 4)
        const mag = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10))
        const norm = raw / mag
        const step = (norm <= 1 ? 1 : (norm <= 2 ? 2 : (norm <= 5 ? 5 : 10))) * mag
        const niceLo = Math.floor(lo / step) * step
        const niceHi = Math.ceil(hi / step) * step
        const ticks = []
        for (let v = niceLo; v <= niceHi + step / 2; v += step) {
            ticks.push({
                pos: (v - niceLo) / Math.max(1e-9, niceHi - niceLo),
                label: chart.formatValue(v)
            })
        }
        return { lo: niceLo, hi: niceHi, step: step, ticks: ticks }
    }

    /* 数值 → 轴标签：按量级用 K/M/B（指数是 100 上下、价格可能上亿，同一套格式化）。 */
    function formatValue(v) {
        const abs = Math.abs(v)
        if (abs >= 1e9)
            return (v / 1e9).toFixed(abs >= 1e10 ? 0 : 1) + "B"
        if (abs >= 1e6)
            return (v / 1e6).toFixed(abs >= 1e7 ? 0 : 1) + "M"
        if (abs >= 1e3)
            return (v / 1e3).toFixed(abs >= 1e4 ? 0 : 1) + "K"
        if (abs >= 100)
            return v.toFixed(0)
        return v.toFixed(2)
    }

    //: 一条线的归一化像素点（x 序号 → 绘图区宽度均匀铺开）
    function pixelsOf(row, axis) {
        const points = []
        const vs = chart.valuesOf(row)
        if (vs.length === 0)
            return points
        const span = vs.length > 1 ? vs.length - 1 : 1
        for (let i = 0; i < vs.length; ++i) {
            const px = span === 0 ? 0 : (i / span) * chart.plotW
            const py = (1 - (vs[i] - axis.lo) / Math.max(1e-9, axis.hi - axis.lo)) * chart.plotH
            points.push(Qt.point(px, py))
        }
        return points
    }

    //: 采样横轴标签（最多 6 个，别把 180 个日期都画出来）
    function xTickIndexes(count) {
        const out = []
        if (count <= 0)
            return out
        const want = Math.min(6, count)
        for (let k = 0; k < want; ++k)
            out.push(Math.round(k * (count - 1) / Math.max(1, want - 1)))
        const uniq = []
        for (let i = 0; i < out.length; ++i) {
            if (uniq.indexOf(out[i]) < 0)
                uniq.push(out[i])
        }
        return uniq
    }

    readonly property var _range: valueRange()
    readonly property var _axis: axisFor(_range.lo, _range.hi, 4)
    readonly property int _pointCount: {
        const rows = chart.series || []
        let n = 0
        for (let i = 0; i < rows.length; ++i) {
            if (rows[i] && rows[i].points)
                n = Math.max(n, rows[i].points.length)
        }
        return n
    }

    Rectangle {
        anchors.fill: parent
        color: "transparent"
        border.width: 1
        border.color: Theme.border
        radius: Theme.radius
    }

    Text {
        objectName: "flineChartEmpty"
        anchors.centerIn: parent
        visible: !chart.hasData
        text: chart.emptyText
        color: Theme.textSecondary
        font.family: Theme.fontFamily
        font.pixelSize: chart.fntSmall
    }

    Item {
        id: plotBox
        objectName: "flineChart"
        anchors.fill: parent
        anchors.topMargin: chart.padT
        anchors.leftMargin: chart.padL
        anchors.rightMargin: chart.padR
        anchors.bottomMargin: chart.padB + chart.legendH
        visible: chart.hasData
        clip: true

        // 横向网格线（**只画线**：纵轴刻度文字必须画在 plotBox 之外，见下方）
        Repeater {
            model: chart.hasData ? chart._axis.ticks : []

            Item {
                required property var modelData
                x: 0
                y: (1 - modelData.pos) * plotBox.height
                width: plotBox.width
                height: 1

                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    height: 1
                    color: Theme.border
                    opacity: 0.5
                }
            }
        }

        // 折线：倒序声明（先声明的在下层），让列表里靠前的线压在上面；
        // 只画 `visibleSeries`（图例点掉的线不画，轴范围也跟着它）
        Repeater {
            model: chart.hasData ? chart.visibleSeries.slice().reverse() : []

            Shape {
                required property var modelData
                anchors.fill: parent
                antialiasing: true

                ShapePath {
                    strokeColor: modelData.color
                    strokeWidth: 2
                    fillColor: "transparent"
                    capStyle: ShapePath.RoundCap
                    joinStyle: ShapePath.RoundJoin
                    PathPolyline {
                        path: chart.pixelsOf(modelData, chart._axis)
                    }
                }
            }
        }

        /* ── 悬停读数：竖线 + 该 x 上每条可见线的数值 ───────────────
         * 用户口径：「希望看到具体的数值，鼠标放在这条线上可以有一个小悬浮提示」。
         * 这里不做「命中某条线」的判定（线很细、很难点中），而是**按最近的 x** 给出
         * 该日期上全部可见线的值 —— 多线对比时这才是想看的。
         * `HoverHandler` 不占布局，也不会挡住图例/分段按钮的点击。 */
        HoverHandler {
            id: plotHover
            enabled: chart.hasData
            onPointChanged: {
                const n = chart._pointCount
                if (n <= 1 || plotBox.width <= 0) {
                    chart.hoverIndex = -1
                    return
                }
                const ratio = Math.max(0, Math.min(1, point.position.x / plotBox.width))
                chart.hoverIndex = Math.round(ratio * (n - 1))
            }
            onHoveredChanged: if (!hovered)
                chart.hoverIndex = -1
        }

        // 竖线（十字线的竖边）
        Rectangle {
            objectName: "flineCrosshair"
            visible: chart.hoverIndex >= 0 && chart._pointCount > 1
            width: 1
            height: plotBox.height
            color: Theme.textSecondary
            opacity: 0.7
            x: chart._pointCount > 1 ? (chart.hoverIndex / (chart._pointCount - 1)) * plotBox.width : 0
        }

        // 该 x 上的点（每条可见线一个圆点，方便看出「值落在哪」）
        Repeater {
            model: chart.hoverIndex >= 0 ? chart.visibleSeries : []

            Rectangle {
                required property var modelData

                readonly property var _vals: chart.valuesOf(modelData)

                visible: chart.hoverIndex >= 0 && chart.hoverIndex < _vals.length
                width: Math.round(7 * Theme.fontScale)
                height: width
                radius: width / 2
                color: modelData.color
                x: (chart._pointCount > 1 ? (chart.hoverIndex / (chart._pointCount - 1)) * plotBox.width : 0) - width / 2
                y: (1 - (_vals[chart.hoverIndex] - chart._axis.lo) / Math.max(1e-9, chart._axis.hi - chart._axis.lo))
                   * plotBox.height - height / 2
            }
        }
    }

    /* 悬停气泡：日期 + 每条可见线的数值（原始值，归一化时同时给归一化值）。
     * 放在绘图区之外的**根 Item** 上，位置跟着竖线走，但会被左右边界夹住不越界。 */
    Rectangle {
        id: hoverTip

        objectName: "flineHoverTip"
        visible: chart.hoverIndex >= 0 && chart.hasData
        z: 10
        width: Math.min(hoverCol.implicitWidth + 2 * Math.round(8 * Theme.fontScale), chart.width - 8)
        height: hoverCol.implicitHeight + 2 * Math.round(6 * Theme.fontScale)
        radius: Theme.radiusSmall
        color: Theme.bgSurfaceLight
        border.width: 1
        border.color: Theme.border
        // 贴着竖线右侧；靠近右边界时翻到左侧；上下的 4px 只是别贴边
        x: Math.max(4, Math.min(chart.padL + (chart._pointCount > 1
                                              ? (chart.hoverIndex / (chart._pointCount - 1)) * chart.plotW
                                              : 0) + 10,
                                chart.width - width - 4))
        y: Math.max(4, chart.padT + 6)

        Column {
            id: hoverCol
            anchors.centerIn: parent
            spacing: 2

            Text {
                text: (chart.xLabels && chart.hoverIndex >= 0 && chart.xLabels.length > chart.hoverIndex)
                      ? chart.xLabels[chart.hoverIndex] : ""
                color: Theme.textBright
                font.family: Theme.fontFamily
                font.pixelSize: chart.fntSmall
                font.bold: true
            }

            Repeater {
                model: hoverTip.visible ? chart.visibleSeries : []

                Row {
                    required property var modelData

                    readonly property var _vals: chart.valuesOf(modelData)
                    readonly property real _shown: (chart.hoverIndex >= 0 && chart.hoverIndex < _vals.length)
                                                   ? _vals[chart.hoverIndex] : 0
                    readonly property real _raw: (modelData.points && chart.hoverIndex >= 0
                                                  && chart.hoverIndex < modelData.points.length)
                                                 ? modelData.points[chart.hoverIndex].y : 0

                    spacing: 4

                    Rectangle {
                        anchors.verticalCenter: parent.verticalCenter
                        width: Math.round(7 * Theme.fontScale)
                        height: width
                        radius: width / 2
                        color: modelData.color
                    }

                    Text {
                        /* 归一化模式下「指数/归一值」和原始价**都要给**：前者看相对走势，
                         * 后者才是能下单的数字。 */
                        text: modelData.label + "  " + chart.formatValue(parent._shown)
                              + (chart.normalize ? "（原值 " + chart.formatValue(parent._raw) + "）" : "")
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: chart.fntSmall
                    }
                }
            }
        }
    }

    /* 纵轴刻度文字：画在**根 Item** 上（绘图区左侧留白里）。
     * ⚠️ 不能写在 `plotBox` 里 —— 它 `clip: true`，`x: -padL` 的文字会被整条裁掉，
     * 表现就是「只有横轴没有纵轴」。 */
    Repeater {
        model: chart.hasData ? chart._axis.ticks : []

        Text {
            required property var modelData
            x: 0
            width: chart.padL - Theme.spacingXs
            height: Math.round(14 * Theme.fontScale)
            y: chart.padT + (1 - modelData.pos) * chart.plotH - height / 2
            verticalAlignment: Text.AlignVCenter
            horizontalAlignment: Text.AlignRight
            text: modelData.label + chart.unit
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: chart.fntSmall
            elide: Text.ElideRight
        }
    }

    /* 横轴日期标签：**必须画在 `plotBox` 之外** —— `plotBox` 有 `clip: true`，
     * 标签原本写在 `y: plotBox.height + …`（即绘图区下方），会被整条裁掉，
     * 于是用户「看不到横轴的日期」。这里挪到根 Item 上，x 仍与竖线对齐。 */
    Repeater {
        model: (chart.hasData && chart.hoverIndex < 0) ? chart.xTickIndexes(chart._pointCount) : []

        Text {
            required property var modelData
            required property int index
            readonly property bool _first: index === 0
            readonly property bool _last: index === (chart.xTickIndexes(chart._pointCount).length - 1)
            x: chart.padL + (chart._pointCount > 1 ? (modelData / (chart._pointCount - 1)) * chart.plotW : 0)
               - (_first ? 0 : (_last ? width : width / 2))
            y: chart.padT + chart.plotH + Theme.spacingXs
            text: (chart.xLabels && chart.xLabels.length > modelData) ? chart.xLabels[modelData] : ""
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: chart.fntSmall
        }
    }

    /* 基期/口径说明（可选）：用户问「100 是从什么日期开始的」——图上必须自己写出来，
     * 不能只把基期日期藏在小卡片里。 */
    Text {
        objectName: "flineChartBaseNote"
        anchors.left: parent.left
        anchors.leftMargin: chart.padL
        anchors.top: parent.top
        anchors.topMargin: Math.max(2, chart.padT - 2)
        text: chart.baseNote
        visible: chart.baseNote !== "" && chart.hasData
        color: Theme.textSecondary
        font.family: Theme.fontFamily
        font.pixelSize: chart.fntSmall
        elide: Text.ElideRight
    }

    // 图例：色点 + 名称 + 末值（归一化时标「=100」）；**可点击切换该线显示/隐藏**。
    // 用 `Flow` 而**不是** `Row`：五条线各带「现值 · 30 日涨跌」，一行放不下会直接画到面板外面
    // （用户报「文字超出框」）；Flow 自动换行 + clip 兜底，最多两行，超出的截断。
    Flow {
        id: legend
        anchors.left: parent.left
        anchors.leftMargin: chart.padL
        anchors.right: parent.right
        anchors.rightMargin: chart.padR
        anchors.bottom: parent.bottom
        height: chart.legendH
        spacing: chart.legendGap
        clip: true
        visible: chart.hasData && chart.showLegend

        Repeater {
            model: chart.hasData ? chart.series : []

            Row {
                id: legendItem

                required property var modelData
                required property int index

                readonly property bool off: chart.isHidden(legendItem.modelData.label, legendItem.index)

                spacing: 4
                height: legend.height
                opacity: legendItem.off ? 0.45 : 1.0

                Rectangle {
                    anchors.verticalCenter: parent.verticalCenter
                    width: Math.round(8 * Theme.fontScale)
                    height: width
                    radius: width / 2
                    color: legendItem.modelData.color
                    // 隐藏的线：色点画成空心，一眼看出这条被点掉了
                    border.width: legendItem.off ? 1 : 0
                    border.color: legendItem.modelData.color
                    opacity: legendItem.off ? 0 : 1
                }

                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    /* 图例只写名字 + 可选 `note`（现值 · 涨跌）。
                     * **不写「（基期=100）」**：基期在图上方的 `baseNote` 里已经统一说明一次
                     * （用户口径：「基期=100，就没必要每个都显示这个吧」），每条都挂既啰嗦、
                     * 又把一行占满容易溢出。 */
                    text: legendItem.modelData.label
                          + (legendItem.modelData.note ? "  " + legendItem.modelData.note : "")
                    color: legendItem.off ? Theme.textSecondary : Theme.textPrimary
                    font.family: Theme.fontFamily
                    font.pixelSize: chart.fntSmall
                    font.strikeout: legendItem.off
                }

                /* 点击切换显隐用 `TapHandler`/`HoverHandler`，**不要用 MouseArea + anchors.fill**：
                 * 图例是位置器（Flow），位置器里设 anchors 的子项会参与布局竞争 —— 实测
                 * 加了个 `anchors.fill: parent` 的 MouseArea 之后**整条图例都不见了**。
                 * 输入处理器不占布局空间，正好合适。 */
                TapHandler {
                    objectName: "flineLegendToggle"
                    enabled: chart.legendClickable
                    cursorShape: chart.legendClickable ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onTapped: chart.toggleLabel(legendItem.modelData.label, legendItem.index)
                }

                HoverHandler {
                    id: legendHover
                    enabled: chart.legendClickable
                }

                /* ToolTip 必须挂在**Item**（这个 Row）上 —— 挂在 HoverHandler 上会告警
                 * 「QML HoverHandler: ToolTip attached …」（处理器不是 Item）。 */
                ToolTip.visible: legendHover.hovered && chart.legendClickable
                ToolTip.text: legendItem.off ? qsTr("点击显示这条线") : qsTr("点击隐藏这条线")
                ToolTip.delay: 400
            }
        }
    }
}
