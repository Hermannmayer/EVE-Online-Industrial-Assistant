import QtQuick
import QtQuick.Layouts
import QtQuick.Shapes
import "../components"

/* 价格走势图对话框（阶段 4b）。
 *
 * 原版是 QtCharts（`QLineSeries` + 双 `QValueAxis`），这里用 QML 场景图重绘。
 *
 * **为什么不用 Canvas**：Qt 的 Canvas 是画进离屏纹理再贴回来的，和 `layer.enabled`
 * 同一类实现 —— 实测在本仓的 offscreen 截图路径（`scripts/ui_snapshot.py`）下
 * **整块画布是空的**（连 `fillRect` 铺满都截不到），和 `icon_provider` 头部记的
 * 「带 layer 的 item 在 offscreen 下整个消失」是同一个坑。改用 `Shape` + `PathPolyline`
 * 画折线、`Rectangle` 画网格：都是场景图几何节点，截图里看得到，这也是项目里
 * `FArrowButton` / `FCheckBox` 已经在用的画法。
 *
 * **几何计算全在桥里**（`price_chart_bridge.plot_model`）：轴范围、刻度、每个点
 * 归一化到 0..1 的坐标都由 Python 算好，这里只做「归一化 × 绘图区尺寸」的落点，
 * 所以本文件里不准出现任何取整/求最值之类的算法。
 *
 * 配色与线序对齐原 `_apply_chart_theme`：价格线用主色、成交量线用橙；成交量先声明
 * 会画在下面，免得压住价格线（兄弟节点的层叠顺序 = 声明顺序）。图例仍在底部。
 */

Item {
    id: page

    readonly property var pc: typeof bridge !== "undefined" ? bridge : null
    //: 有数据才画；空模型直接走「暂无数据」那行
    readonly property var chart: (page.pc && !page.pc.plot.isEmpty) ? page.pc.plot : null

    //: 折线颜色；下标与桥给的 series 顺序绑定（0=日均价, 1=成交量）
    function seriesColor(index) {
        return index === 0 ? Theme.primary : Theme.accentOrange
    }

    //: 序列 → 绘图区内的像素点列（输入是 0..1 归一化坐标）
    function polyline(series, w, h) {
        const points = []
        if (!series)
            return points
        const src = series.points
        for (let i = 0; i < src.length; ++i)
            points.push(Qt.point(src[i].x * w, (1 - src[i].y) * h))
        return points
    }

    Rectangle {
        anchors.fill: parent
        color: Theme.bgDark
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.spacingMd
        spacing: Theme.spacingSm

        // ── 标题 + 状态 ──
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingSm

            Text {
                Layout.fillWidth: true
                text: page.pc ? page.pc.headerText : ""
                color: Theme.primary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(14 * Theme.fontScale)
                font.weight: Font.DemiBold
                elide: Text.ElideRight
            }

            Text {
                text: page.pc ? page.pc.statusText : ""
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(11 * Theme.fontScale)
            }
        }

        // ── 绘图区（原 QChart 的 plotArea 底色是 BG_SURFACE）──
        Rectangle {
            id: chartBox
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: Theme.bgSurface
            radius: Theme.radius
            border.width: 1
            border.color: Theme.border

            // 留白：左边放价格刻度、右边放成交量刻度、下面放日期
            readonly property real padL: Math.round(78 * Theme.fontScale)
            readonly property real padR: Math.round(78 * Theme.fontScale)
            readonly property real padT: Math.round(10 * Theme.fontScale)
            readonly property real padB: Math.round(24 * Theme.fontScale)
            readonly property real plotW: Math.max(0, width - padL - padR)
            readonly property real plotH: Math.max(0, height - padT - padB)
            readonly property int labelPx: Math.round(10 * Theme.fontScale)

            // 横向网格 + 左轴价格刻度 / 右轴成交量刻度
            Repeater {
                model: page.chart ? page.chart.priceTicks : []

                Item {
                    required property var modelData

                    x: 0
                    y: chartBox.padT + (1 - modelData.pos) * chartBox.plotH
                    width: chartBox.width
                    height: 1

                    Rectangle {
                        x: chartBox.padL
                        width: chartBox.plotW
                        height: 1
                        color: Theme.border
                    }

                    Text {
                        x: 0
                        y: -height / 2
                        width: chartBox.padL - 6
                        height: Math.round(14 * Theme.fontScale)
                        horizontalAlignment: Text.AlignRight
                        verticalAlignment: Text.AlignVCenter
                        text: modelData.label
                        color: Theme.textSecondary
                        font.family: Theme.fontFamily
                        font.pixelSize: chartBox.labelPx
                    }
                }
            }

            Repeater {
                model: page.chart ? page.chart.volumeTicks : []

                Text {
                    required property var modelData

                    x: chartBox.padL + chartBox.plotW + 6
                    y: chartBox.padT + (1 - modelData.pos) * chartBox.plotH - height / 2
                    width: chartBox.padR - 8
                    height: Math.round(14 * Theme.fontScale)
                    horizontalAlignment: Text.AlignLeft
                    verticalAlignment: Text.AlignVCenter
                    text: modelData.label
                    color: Theme.textSecondary
                    font.family: Theme.fontFamily
                    font.pixelSize: chartBox.labelPx
                }
            }

            // 纵向网格 + 日期
            Repeater {
                model: page.chart ? page.chart.xTicks : []

                Item {
                    required property var modelData

                    x: chartBox.padL + modelData.pos * chartBox.plotW
                    y: chartBox.padT
                    width: 1
                    height: chartBox.plotH

                    Rectangle {
                        width: 1
                        height: chartBox.plotH
                        color: Theme.border
                    }

                    Text {
                        x: -width / 2
                        y: chartBox.plotH + 4
                        width: Math.round(72 * Theme.fontScale)
                        height: Math.round(14 * Theme.fontScale)
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        text: modelData.label
                        color: Theme.textSecondary
                        font.family: Theme.fontFamily
                        font.pixelSize: chartBox.labelPx
                    }
                }
            }

            // 成交量（先声明 = 画在下面）
            Shape {
                x: chartBox.padL
                y: chartBox.padT
                width: chartBox.plotW
                height: chartBox.plotH
                antialiasing: true
                visible: page.chart !== null

                ShapePath {
                    strokeColor: page.seriesColor(1)
                    strokeWidth: 2
                    fillColor: "transparent"
                    capStyle: ShapePath.RoundCap
                    joinStyle: ShapePath.RoundJoin
                    PathPolyline {
                        path: page.chart ? page.polyline(page.chart.series[1], chartBox.plotW, chartBox.plotH) : []
                    }
                }
            }

            // 日均价
            Shape {
                x: chartBox.padL
                y: chartBox.padT
                width: chartBox.plotW
                height: chartBox.plotH
                antialiasing: true
                visible: page.chart !== null

                ShapePath {
                    strokeColor: page.seriesColor(0)
                    strokeWidth: 2
                    fillColor: "transparent"
                    capStyle: ShapePath.RoundCap
                    joinStyle: ShapePath.RoundJoin
                    PathPolyline {
                        path: page.chart ? page.polyline(page.chart.series[0], chartBox.plotW, chartBox.plotH) : []
                    }
                }
            }

            Text {
                anchors.centerIn: parent
                visible: page.chart === null
                text: qsTr("暂无数据")
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(12 * Theme.fontScale)
            }
        }

        // ── 图例（原 QChart legend 在底部）──
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingLg

            Repeater {
                model: page.chart ? page.chart.series : []

                RowLayout {
                    required property var modelData
                    required property int index
                    spacing: Theme.spacingXs

                    Rectangle {
                        Layout.alignment: Qt.AlignVCenter
                        Layout.preferredWidth: 16
                        Layout.preferredHeight: 3
                        color: page.seriesColor(index)
                    }

                    Text {
                        text: modelData.label
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: Math.round(11 * Theme.fontScale)
                    }
                }
            }

            Item {
                Layout.fillWidth: true
            }
        }

        RowLayout {
            Layout.fillWidth: true

            Item {
                Layout.fillWidth: true
            }

            FButton {
                text: qsTr("关闭")
                onClicked: if (page.pc)
                    page.pc.reject()
            }
        }
    }
}
