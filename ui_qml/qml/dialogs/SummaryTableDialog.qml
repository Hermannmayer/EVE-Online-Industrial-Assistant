import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 只读汇总表对话框（阶段 4）。
 *
 * 「产出总表」「人物占用」「材料总表」共用这一份：列宽、行、状态文案都由桥给出，
 * 单元格的颜色（利润正负 / 状态语义 / 溢出标橙）也在桥里算好，这里只画。
 */

Item {
    id: page

    readonly property var table: typeof bridge !== "undefined" ? bridge : null

    //: 列宽合计（含单元格左右内边距），用于给「吃满剩余空间」的那列算宽度
    readonly property int cellPadding: Math.round(12 * Theme.fontScale)
    readonly property int fixedWidth: {
        let total = 0
        const cols = page.table ? page.table.columns : []
        for (let i = 0; i < cols.length; ++i) {
            if (cols[i].width > 0)
                total += cols[i].width + page.cellPadding
        }
        return total + page.cellPadding
    }

    function colWidth(col) {
        const cols = page.table ? page.table.columns : []
        if (col >= cols.length)
            return 0
        if (cols[col].width > 0)
            return cols[col].width
        // 未指定宽度的列平分剩余空间
        let flexible = 0
        for (let i = 0; i < cols.length; ++i) {
            if (cols[i].width <= 0)
                flexible += 1
        }
        return flexible > 0 ? Math.max(80, (page.width - page.fixedWidth) / flexible) : 80
    }

    Rectangle {
        anchors.fill: parent
        color: Theme.bgDark
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.spacingSm
        spacing: Theme.spacingSm

        // ── 表头 ──
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: Math.round(26 * Theme.fontScale)
            color: Theme.bgSurfaceLight

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Theme.spacingSm
                anchors.rightMargin: Theme.spacingSm
                spacing: 0

                Repeater {
                    model: page.table ? page.table.columns : []

                    Text {
                        required property var modelData
                        required property int index
                        Layout.preferredWidth: page.colWidth(index)
                        verticalAlignment: Text.AlignVCenter
                        horizontalAlignment: Text.AlignHCenter
                        text: modelData.title
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: Math.round(12 * Theme.fontScale)
                        elide: Text.ElideRight
                    }
                }
            }
        }

        // ── 数据行 ──
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: Theme.bgSurface
            radius: Theme.radius
            border.width: 1
            border.color: Theme.border

            ListView {
                id: rowList
                anchors.fill: parent
                anchors.margins: 1
                clip: true
                model: page.table ? page.table.rows : []
                boundsBehavior: Flickable.StopAtBounds

                ScrollBar.vertical: ScrollBar {
                    policy: ScrollBar.AsNeeded
                }

                delegate: Item {
                    id: rowItem
                    required property var modelData
                    required property int index

                    width: rowList.width
                    implicitHeight: Math.round(24 * Theme.fontScale)

                    Rectangle {
                        anchors.fill: parent
                        color: rowItem.index % 2 === 0 ? Theme.bgSurface : Theme.bgDark
                    }

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: Theme.spacingSm
                        anchors.rightMargin: Theme.spacingSm
                        spacing: 0

                        Repeater {
                            model: rowItem.modelData.cells

                            Item {
                                id: cellItem
                                required property var modelData
                                required property int index

                                // 最后一列在有行内动作时渲染成按钮（材料总表的「复制采购」）
                                readonly property bool showAction: page.table !== null
                                                                  && page.table.hasActionColumn
                                                                  && index === rowItem.modelData.cells.length - 1

                                Layout.preferredWidth: page.colWidth(index)
                                Layout.fillHeight: true

                                Text {
                                    anchors.fill: parent
                                    visible: !cellItem.showAction
                                    verticalAlignment: Text.AlignVCenter
                                    horizontalAlignment: Text.AlignHCenter
                                    text: cellItem.modelData.text
                                    color: cellItem.modelData.color !== "" ? cellItem.modelData.color : Theme.textPrimary
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Math.round(12 * Theme.fontScale)
                                    elide: Text.ElideRight
                                }

                                FButton {
                                    anchors.centerIn: parent
                                    visible: cellItem.showAction
                                    implicitWidth: Math.round(52 * Theme.fontScale)
                                    implicitHeight: Math.round(22 * Theme.fontScale)
                                    text: qsTr("复制")
                                    onClicked: if (page.table)
                                        page.table.copyRow(rowItem.index)
                                }
                            }
                        }
                    }
                }
            }

            // 空态
            Text {
                anchors.centerIn: parent
                visible: page.table ? page.table.rowCount === 0 : false
                text: qsTr("没有数据")
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(12 * Theme.fontScale)
            }
        }

        // ── 状态行 + 顶栏动作 + 关闭 ──
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingSm

            Text {
                Layout.fillWidth: true
                text: page.table ? page.table.statusText : ""
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(11 * Theme.fontScale)
                elide: Text.ElideRight
            }

            // 动作反馈（复制成功 / 无待采购 之类）—— 复用桥的 `error` 通道
            Text {
                visible: page.table ? page.table.error !== "" : false
                text: page.table ? page.table.error : ""
                color: Theme.accentYellow
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(11 * Theme.fontScale)
                elide: Text.ElideRight
            }

            FButton {
                text: page.table ? page.table.topActionText : ""
                visible: page.table ? page.table.topActionText !== "" : false
                onClicked: if (page.table)
                    page.table.topAction()
            }

            FButton {
                text: qsTr("关闭")
                onClicked: if (page.table)
                    page.table.reject()
            }
        }
    }
}
