import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Shapes
import "../../components"

/* 空闲态仪表盘 · 资产折线图。
 *
 * 对应界面标注图：
 *   上「资产（表格显示）」、中折线、左「金额（根据筛选的金额自适应单位和刻度）」、
 *   右「筛选项：按时间跨度 近7天 本月 本年 总」、
 *   下「数据示例和筛选项（通过点击筛选）／1 总计资产（按照卖单计算）2 挂单金额（买单、卖单）
 *      3 库存材料金额 4 钱包余额／以上显示的线条颜色都不一样」。
 *   第五项「运行中产线价值」是按用户后续要求补的（只取制造中产线的材料占用 × 卖单价）。
 *
 * **几何全在桥里**（复用 `ui_qml/bridge/price_chart_bridge.py` 的
 * `nice_range` / `axis_values` / `map_values` / `pick_indices`）：轴范围、刻度、每个点的
 * 归一化坐标都是 Python 算好的 0..1，这里只做「归一化 × 绘图区尺寸」的落点。
 *
 * **不用 Canvas**：Qt 的 Canvas 画进离屏纹理，在本仓的 offscreen 截图路径下整块是空的
 * （见 `PriceChartDialog.qml:6-23` 与 `ui_qml/icon_provider.py` 头部）。折线用
 * `Shape` + `ShapePath` + `PathPolyline`，网格与轴用 `Rectangle` + `Text` —— 都是场景图
 * 几何节点，截图里看得到。
 *
 * 高度用 `id` 互相推导（不用「总高减去一串常数」）：顶部有「资产（表格显示）」标题行
 * （右边挂着「刷新」按钮），底部有**两行**控件（数据示例一行、时间跨度一行），
 * 串成一行在 416px 的列宽里会溢出、右边的档位被切掉。
 */
Item {
    id: root

    //: `bridge.dashboard`
    property var dashboard: null

    readonly property var plot: (dashboard && !dashboard.assetPlot.isEmpty) ? dashboard.assetPlot : null
    readonly property var seriesRows: dashboard ? dashboard.assetSeries : []
    readonly property var summaryRows: dashboard ? dashboard.assetSummaryRows : []
    readonly property var rangeLabels: dashboard ? dashboard.rangeLabels : []

    readonly property int fntSmall: Math.round(11 * Theme.fontScale)
    readonly property int fntBase: Math.round(12 * Theme.fontScale)
    readonly property int padL: Math.round(72 * Theme.fontScale)
    readonly property int padR: Math.round(14 * Theme.fontScale)
    readonly property int padT: Math.round(8 * Theme.fontScale)
    readonly property int padB: Math.round(22 * Theme.fontScale)
    readonly property int plotW: Math.max(0, chartBox.width - padL - padR)
    readonly property int plotH: Math.max(0, chartBox.height - padT - padB)
    readonly property int rowH: Math.max(20, fntSmall + 9)
    readonly property int gap: Theme.spacingXs

    /* 归一化坐标 → 绘图区像素点。
     * `x*w` 与 `(1-y)*h` 是全部转换，本文件里不出现任何取整/求最值。 */
    function polyline(series, w, h) {
        const points = []
        if (!series || !series.points)
            return points
        const src = series.points
        for (let i = 0; i < src.length; ++i)
            points.push(Qt.point(src[i].x * w, (1 - src[i].y) * h))
        return points
    }

    Column {
        anchors.fill: parent
        spacing: root.gap

        // ── 资产（表格显示）────────────────────────────────────
        RowLayout {
            id: summaryHead
            width: parent.width
            height: root.rowH
            spacing: Theme.spacingXs

            Text {
                Layout.fillWidth: true
                verticalAlignment: Text.AlignVCenter
                text: qsTr("资产（表格显示）")
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: root.fntSmall
                elide: Text.ElideRight
            }

            //: 手动刷新：强制重读资产快照（定时器那 60s 的轮询等不及时用）
            FButton {
                objectName: "assetRefreshButton"
                Layout.preferredHeight: Math.max(20, root.fntSmall + 8)
                text: qsTr("刷新")
                onClicked: if (root.dashboard)
                    root.dashboard.reloadAssets()
            }
        }

        Column {
            id: summaryBox
            width: parent.width
            // 5 行封顶，但别超过面板的三分之一（面板很矮时把图留给折线）
            height: Math.min(root.rowH * Math.min(root.summaryRows.length, 5),
                             Math.max(root.rowH, parent.height * 0.34))
            spacing: 0
            clip: true

            Repeater {
                model: root.summaryRows

                Item {
                    required property var modelData
                    width: parent.width
                    height: root.rowH

                    Rectangle {
                        anchors.left: parent.left
                        anchors.verticalCenter: parent.verticalCenter
                        width: Math.round(8 * Theme.fontScale)
                        height: width
                        radius: width / 2
                        color: modelData.color
                    }

                    Text {
                        x: Math.round(14 * Theme.fontScale)
                        width: Math.max(40, parent.width * 0.34)
                        height: parent.height
                        verticalAlignment: Text.AlignVCenter
                        text: modelData.label
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: root.fntSmall
                        elide: Text.ElideRight
                    }

                    Text {
                        x: Math.round(14 * Theme.fontScale) + Math.max(40, parent.width * 0.34)
                        width: Math.max(40, parent.width * 0.30)
                        height: parent.height
                        verticalAlignment: Text.AlignVCenter
                        horizontalAlignment: Text.AlignRight
                        text: modelData.valueText
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: root.fntSmall
                        elide: Text.ElideRight
                    }

                    Text {
                        anchors.right: parent.right
                        width: Math.max(40, parent.width * 0.32)
                        height: parent.height
                        verticalAlignment: Text.AlignVCenter
                        horizontalAlignment: Text.AlignRight
                        text: modelData.deltaText
                        color: modelData.deltaPos ? Theme.accentGreen : Theme.accentRed
                        font.family: Theme.fontFamily
                        font.pixelSize: root.fntSmall
                        elide: Text.ElideRight
                    }
                }
            }
        }

        Rectangle {
            x: 0
            width: parent.width
            height: 1
            color: Theme.border
        }

        // ── 折线绘图区 ────────────────────────────────────────
        Item {
            id: chartBox
            width: parent.width
            height: Math.max(60, parent.height
                                - summaryHead.height - summaryBox.height
                                - legendBox.height - rangeBox.height
                                - 4 * root.gap - 2)

            // 无数据 / 加载中
            Text {
                anchors.centerIn: parent
                width: parent.width - 2 * Theme.spacingSm
                visible: root.plot === null
                text: root.dashboard ? root.dashboard.assetEmptyText : ""
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: root.fntSmall
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
            }

            // 横网格 + 左轴刻度（金额，单位由桥按量级自适应成 K/M/B）
            Repeater {
                model: root.plot ? root.plot.yTicks : []

                Item {
                    required property var modelData
                    x: 0
                    y: root.padT + (1 - modelData.pos) * root.plotH
                    width: chartBox.width
                    height: 1

                    Rectangle {
                        anchors.left: parent.left
                        anchors.leftMargin: root.padL
                        anchors.right: parent.right
                        anchors.rightMargin: root.padR
                        height: 1
                        color: Theme.border
                        opacity: 0.5
                    }

                    Text {
                        x: 0
                        width: root.padL - Theme.spacingXs
                        height: Math.round(14 * Theme.fontScale)
                        y: -height / 2
                        verticalAlignment: Text.AlignVCenter
                        horizontalAlignment: Text.AlignRight
                        text: modelData.label
                        color: Theme.textSecondary
                        font.family: Theme.fontFamily
                        font.pixelSize: root.fntSmall
                        elide: Text.ElideRight
                    }
                }
            }

            // 纵向网格：**每个数据点一根**（吃 `xLines`，不是采样的 `xTicks`）
            Repeater {
                model: root.plot ? root.plot.xLines : []

                Item {
                    required property var modelData
                    x: root.padL + modelData.pos * root.plotW
                    y: root.padT
                    width: 1
                    height: root.plotH

                    Rectangle {
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        width: 1
                        color: Theme.border
                        opacity: 0.35
                    }
                }
            }

            /* 日期标签：吃采样的 `xTicks`（≤6 个，`xLines` 有 90 个时不能都当标签）。
             * **标签位置向内对齐、刻度 x 不动**：`padR` 只有 14px，而 `"2026-09-25"`
             * 实测宽约 58px（半宽 29px），居中会把最后一个标签压到右侧挂单面板上
             * （祖先 `FPanel` 没有 `clip`，溢出会直接盖到邻居上）。
             * 首标签左对齐、末标签右对齐，中段仍居中 —— 竖线仍落在 `padL + pos*plotW`。 */
            Repeater {
                model: root.plot ? root.plot.xTicks : []

                Text {
                    required property var modelData
                    required property int index
                    readonly property bool _first: index === 0
                    readonly property bool _last: root.plot ? index === root.plot.xTicks.length - 1 : false
                    x: root.padL + modelData.pos * root.plotW
                       - (_first ? 0 : (_last ? width : width / 2))
                    y: root.padT + root.plotH + Theme.spacingXs
                    text: modelData.label
                    color: Theme.textSecondary
                    font.family: Theme.fontFamily
                    font.pixelSize: root.fntSmall
                }
            }

            /* 折线：**倒序声明** —— 先声明的画在下面，让列表里靠前的线压在上层
             * （「总资产」在最上面，值最大，压住其它三条最好看）。 */
            Repeater {
                model: root.plot ? root.plot.series.slice().reverse() : []

                Shape {
                    required property var modelData

                    x: root.padL
                    y: root.padT
                    width: root.plotW
                    height: root.plotH
                    antialiasing: true
                    visible: root.plot !== null

                    ShapePath {
                        strokeColor: modelData.color
                        strokeWidth: 2
                        fillColor: "transparent"
                        capStyle: ShapePath.RoundCap
                        joinStyle: ShapePath.RoundJoin
                        PathPolyline {
                            path: root.plot ? root.polyline(modelData, root.plotW, root.plotH) : []
                        }
                    }
                }
            }
        }

        // ── 数据示例（点击切换显隐）────────────────────────────
        Row {
            id: legendBox
            width: parent.width
            height: root.rowH
            spacing: Theme.spacingXs

            Repeater {
                model: root.seriesRows

                FButton {
                    required property int index
                    required property var modelData
                    height: parent.height
                    /* 宽度按**线的条数**均分（早先写死 /4，加到第 5 条「运行中产线价值」
                     * 之后会溢出、最右边那个 chip 被切掉）。 */
                    width: Math.max(40, (legendBox.width - (root.seriesRows.length - 1) * legendBox.spacing)
                                         / Math.max(1, root.seriesRows.length))
                    text: modelData.label
                    // 没选中的压暗，一眼看出哪几条在图上
                    opacity: modelData.visible ? 1.0 : 0.45
                    onClicked: if (root.dashboard)
                        root.dashboard.toggleSeries(index)

                    HoverHandler {
                        id: chipHover
                    }
                    ToolTip.visible: chipHover.hovered
                    ToolTip.text: (modelData.visible ? qsTr("点击隐藏「%1」")
                                                     : qsTr("点击显示「%1」")).arg(modelData.label)
                                 + (modelData.latestText !== "" ? "\n" + qsTr("最新：") + modelData.latestText : "")
                }
            }
        }

        // ── 时间跨度 ──────────────────────────────────────────
        Row {
            id: rangeBox
            width: parent.width
            height: root.rowH
            spacing: Theme.spacingXs

            Text {
                height: parent.height
                width: Math.round(56 * Theme.fontScale)
                verticalAlignment: Text.AlignVCenter
                text: qsTr("时间跨度")
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: root.fntSmall
            }

            Repeater {
                model: root.rangeLabels

                FButton {
                    required property int index
                    required property var modelData
                    height: parent.height
                    width: Math.max(36, (rangeBox.width - Math.round(56 * Theme.fontScale)
                                         - 4 * rangeBox.spacing) / 4)
                    text: String(modelData)
                    primary: root.dashboard !== null && root.dashboard.rangeIndex === index
                    onClicked: if (root.dashboard)
                        root.dashboard.setRangeIndex(index)
                }
            }
        }
    }
}
