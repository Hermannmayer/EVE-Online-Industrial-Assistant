import QtQuick
import QtQuick.Controls

/* 面板内的紧凑表格 —— 查询页的详情面板与空闲态仪表盘共用。
 *
 * 数据形状（由桥的纯函数算好，这里**不做任何格式化/取最值**）：
 *
 *     headers : ["中心", "买单", "卖单"]
 *     ratios  : [1.0, 1.2, 1.2]          // 每列相对宽度，空 = 等分
 *     rows    : [{ cells: [
 *         { text: "Jita", color: "", align: "left",  barPos: 0.0, barColor: "" },
 *         { text: "1,234.00", color: "#4ade80", align: "right", barPos: 0.82, barColor: "#4ade80" }
 *     ]}]
 *
 * `barPos` ∈ 0..1 时在单元格底部画一条横条（柱形图），`barColor` 空则用该格文字色。
 * **不用 Canvas**：它在离屏截图路径下整块不可见（见 `PriceChartDialog.qml` 头注释），
 * 柱形只用一个 `Rectangle` 即可，是场景图几何节点，截图里看得到。
 *
 * 颜色一律由桥从 `ui_qml.theme.registry` 取，本文件只做 `opacity` 压暗，不改色值。
 */
Item {
    id: root

    property var headers: []
    property var rows: []
    property var ratios: []
    property string emptyText: ""

    readonly property int fntSmall: Math.round(11 * Theme.fontScale)
    readonly property int fntBase: Math.round(12 * Theme.fontScale)
    readonly property int rowH: Math.max(22, fntBase + 11)
    readonly property int headerH: Math.max(20, fntSmall + 10)
    readonly property int padH: Math.round(6 * Theme.fontScale)

    /* 每列像素宽 —— 算一次供所有格复用。
     * 写成块绑定（而不是逐个格调 colX()）是因为本组件的行数×列数可能上百，
     * 每格重扫一遍列宽在滚动时是实打实的开销（计划表踩过同一个坑）。 */
    readonly property var colWidths: {
        const n = root.headers.length
        if (n === 0)
            return []
        let sum = 0
        const out = []
        for (let i = 0; i < n; ++i) {
            const r = (root.ratios.length === n) ? Number(root.ratios[i]) : 1.0
            out.push(r > 0 ? r : 0.0)
            sum += out[i]
        }
        if (sum <= 0) {
            for (let j = 0; j < n; ++j)
                out[j] = root.width / n
            return out
        }
        for (let k = 0; k < n; ++k)
            out[k] = root.width * out[k] / sum
        return out
    }

    readonly property var colOffsets: {
        const out = []
        let x = 0
        for (let i = 0; i < root.colWidths.length; ++i) {
            out.push(x)
            x += root.colWidths[i]
        }
        return out
    }

    Column {
        anchors.fill: parent
        spacing: 0

        // ── 表头 ──────────────────────────────────────────────
        Item {
            width: parent.width
            height: root.headerH
            visible: root.headers.length > 0

            Repeater {
                model: root.headers

                Text {
                    required property int index
                    required property var modelData
                    x: root.colOffsets[index]
                    width: root.colWidths[index] - root.padH
                    height: parent.height
                    verticalAlignment: Text.AlignVCenter
                    horizontalAlignment: Text.AlignLeft
                    text: String(modelData)
                    color: Theme.textSecondary
                    font.family: Theme.fontFamily
                    font.pixelSize: root.fntSmall
                    elide: Text.ElideRight
                }
            }

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: 1
                color: Theme.border
            }
        }

        // ── 表体 ──────────────────────────────────────────────
        Item {
            width: parent.width
            height: parent.height - root.headerH

            Text {
                anchors.centerIn: parent
                width: parent.width - 2 * Theme.spacingSm
                visible: root.rows.length === 0 && root.emptyText !== ""
                text: root.emptyText
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: root.fntSmall
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
            }

            ListView {
                id: body
                anchors.fill: parent
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                model: root.rows
                ScrollBar.vertical: ScrollBar {
                    policy: ScrollBar.AsNeeded
                }

                delegate: Item {
                    id: rowItem
                    required property var modelData
                    width: body.width
                    height: root.rowH

                    readonly property var cells: rowItem.modelData && rowItem.modelData.cells
                                                 ? rowItem.modelData.cells : []

                    Repeater {
                        model: rowItem.cells

                        Item {
                            id: cellItem
                            required property int index
                            required property var modelData

                            x: root.colOffsets[index]
                            width: root.colWidths[index]
                            height: rowItem.height

                            readonly property string cellColor: (cellItem.modelData && cellItem.modelData.color)
                                                                ? String(cellItem.modelData.color)
                                                                : String(Theme.textPrimary)
                            readonly property real barPos: (cellItem.modelData && cellItem.modelData.barPos)
                                                           ? Number(cellItem.modelData.barPos) : 0

                            /* 柱形：贴单元格底、从**左**起算（买单/卖单同向，便于横向比长度）。
                             * 只画在 `barPos > 0` 的格上；`opacity` 压暗而不是改色 ——
                             * 改色就得在 QML 里调 rgba，那等于把配色搬出 registry。 */
                            Rectangle {
                                visible: cellItem.barPos > 0
                                anchors.left: parent.left
                                anchors.verticalCenter: parent.verticalCenter
                                width: Math.max(1, Math.round((parent.width - root.padH) * cellItem.barPos))
                                height: Math.max(3, Math.round(parent.height * 0.42))
                                radius: Theme.radiusSmall
                                color: (cellItem.modelData && cellItem.modelData.barColor)
                                       ? String(cellItem.modelData.barColor) : cellItem.cellColor
                                opacity: 0.32
                            }

                            Text {
                                anchors.fill: parent
                                anchors.leftMargin: root.padH
                                anchors.rightMargin: root.padH
                                verticalAlignment: Text.AlignVCenter
                                horizontalAlignment: (cellItem.modelData && cellItem.modelData.align === "right")
                                                     ? Text.AlignRight : Text.AlignLeft
                                text: cellItem.modelData ? String(cellItem.modelData.text) : ""
                                color: cellItem.cellColor
                                font.family: Theme.fontFamily
                                font.pixelSize: root.fntBase
                                elide: Text.ElideRight
                            }
                        }
                    }
                }
            }
        }
    }
}
