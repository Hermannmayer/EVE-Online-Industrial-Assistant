import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 查看核算（成本明细，阶段 4）。
 *
 * 左边材料清单（6 列），右边三块「标签: 值」明细（制造作业费 / 市场费用 / 汇总）。
 * 只读查看器：**非模态**（调用方 `show()` 而非 `exec()`），所以没有「确定」，
 * 只有「关闭」。
 *
 * 所有数字与颜色都在桥里算好（含 +利润染绿/-利润染红、作业费与市场费用合计加粗），
 * 这里只排版。
 */

FDialogFrame {
    id: frame

    readonly property var cb: typeof bridge !== "undefined" ? bridge : null

    dlg: frame.cb
    acceptVisible: false
    cancelText: qsTr("关闭")

    readonly property int colQty: Math.round(72 * Theme.fontScale)
    readonly property int colPct: Math.round(84 * Theme.fontScale)
    readonly property int colIsk: Math.round(96 * Theme.fontScale)
    readonly property int labelWidth: Math.round(130 * Theme.fontScale)

    // 顶部状态行（计划设定 + 材料种数 + 评分 + 利润 + 利润率；或加载失败提示）
    Text {
        Layout.fillWidth: true
        text: frame.cb ? frame.cb.statusText : ""
        color: Theme.textSecondary
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(12 * Theme.fontScale)
        font.bold: true
        wrapMode: Text.WordWrap
    }

    RowLayout {
        Layout.fillWidth: true
        Layout.fillHeight: true
        spacing: Theme.spacingSm

        // ── 左：材料清单 ──
        // preferredWidth 必须给实数：只写 fillWidth + stretchFactor 时，两个子项都从
        // 0 基准拉伸，实测落到 50/50，材料表末列被挤没（Widgets 版是 580:360）。
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.preferredWidth: Math.round(560 * Theme.fontScale)
            Layout.horizontalStretchFactor: 3
            color: Theme.bgSurface
            radius: Theme.radius
            border.width: 1
            border.color: Theme.border

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: Theme.spacingSm
                spacing: Theme.spacingXs

                Text {
                    text: qsTr("材料清单")
                    color: Theme.textSecondary
                    font.family: Theme.fontFamily
                    font.pixelSize: Math.round(12 * Theme.fontScale)
                }

                // 表头
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: Math.round(26 * Theme.fontScale)
                    color: Theme.bgSurfaceLight

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: Theme.spacingSm
                        anchors.rightMargin: Theme.spacingSm
                        spacing: Theme.spacingXs

                        Repeater {
                            model: frame.cb ? frame.cb.materialHeaders : []

                            Text {
                                required property var modelData
                                required property int index

                                Layout.preferredWidth: index === 0 ? -1 : (index === 2 ? frame.colPct : (index >= 4 ? frame.colIsk : frame.colQty))
                                Layout.fillWidth: index === 0
                                horizontalAlignment: index === 0 ? Text.AlignLeft : Text.AlignRight
                                text: modelData
                                color: Theme.textPrimary
                                font.family: Theme.fontFamily
                                font.pixelSize: Math.round(12 * Theme.fontScale)
                                elide: Text.ElideRight
                            }
                        }
                    }
                }

                // 数据行
                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    color: Theme.bgDark
                    radius: Theme.radiusSmall
                    border.width: 1
                    border.color: Theme.border

                    ListView {
                        id: matList
                        anchors.fill: parent
                        anchors.margins: 1
                        clip: true
                        model: frame.cb ? frame.cb.materialRows : []
                        boundsBehavior: Flickable.StopAtBounds

                        ScrollBar.vertical: ScrollBar {
                            policy: ScrollBar.AsNeeded
                        }

                        delegate: Item {
                            id: matRow
                            required property var modelData
                            required property int index

                            width: matList.width
                            implicitHeight: Math.round(24 * Theme.fontScale)

                            Rectangle {
                                anchors.fill: parent
                                color: matRow.index % 2 === 0 ? Theme.bgSurface : Theme.bgDark
                            }

                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: Theme.spacingSm
                                anchors.rightMargin: Theme.spacingSm
                                spacing: Theme.spacingXs

                                Repeater {
                                    model: matRow.modelData.cells

                                    Text {
                                        required property var modelData
                                        required property int index

                                        Layout.preferredWidth: index === 0 ? -1 : (index === 2 ? frame.colPct : (index >= 4 ? frame.colIsk : frame.colQty))
                                        Layout.fillWidth: index === 0
                                        horizontalAlignment: index === 0 ? Text.AlignLeft : Text.AlignRight
                                        verticalAlignment: Text.AlignVCenter
                                        text: modelData.text
                                        color: modelData.color !== "" ? modelData.color : Theme.textPrimary
                                        font.family: index === 0 ? Theme.fontFamily : "Consolas"
                                        font.pixelSize: Math.round(12 * Theme.fontScale)
                                        elide: Text.ElideRight
                                    }
                                }
                            }
                        }
                    }

                    Text {
                        anchors.centerIn: parent
                        visible: frame.cb ? frame.cb.materialRows.length === 0 : true
                        text: qsTr("没有材料明细")
                        color: Theme.textSecondary
                        font.family: Theme.fontFamily
                        font.pixelSize: Math.round(12 * Theme.fontScale)
                    }
                }
            }
        }

        // ── 右：三块明细（可滚动，窄屏时不挤掉内容）──
        Flickable {
            id: rightPane
            Layout.preferredWidth: Math.round(380 * Theme.fontScale)
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.horizontalStretchFactor: 2
            clip: true
            contentHeight: rightCol.implicitHeight
            boundsBehavior: Flickable.StopAtBounds

            ScrollBar.vertical: ScrollBar {
                policy: ScrollBar.AsNeeded
            }

            ColumnLayout {
                id: rightCol
                width: rightPane.width
                spacing: Theme.spacingSm

                FSection {
                    title: qsTr("制造作业费")

                    FFieldList {
                        fields: frame.cb ? frame.cb.jobFields : []
                        labelWidth: frame.labelWidth
                    }
                }

                FSection {
                    title: qsTr("市场费用")

                    FFieldList {
                        fields: frame.cb ? frame.cb.marketFields : []
                        labelWidth: frame.labelWidth
                    }
                }

                FSection {
                    title: qsTr("汇总")

                    FFieldList {
                        fields: frame.cb ? frame.cb.summaryFields : []
                        labelWidth: frame.labelWidth
                    }
                }

                Item {
                    Layout.fillWidth: true
                    Layout.preferredHeight: Theme.spacingSm
                }
            }
        }
    }
}
