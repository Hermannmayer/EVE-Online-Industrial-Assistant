import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 批量对比对话框（阶段 4b）。
 *
 * 对照 Widgets 版 `ui_pyside6/views/compare/compare_dialog.py::CompareDialog`：
 * 搜索添加区 → 已添加列表 → 参数行 → 进度条 → 对比结果表 → 状态行，
 * 表格右键「复制行 / 复制全部 / 查看物品」。
 *
 * 业务动作一律不在这里实现：每次交互都调 `cmp.<方法>`，由
 * `ui_qml/bridge/compare_bridge.py` 转给既有 worker / service。
 *
 * 表格**没有**复用 `FSummaryTable`，而是与 `WatchlistPage` / `PlanTablePane` 同款地
 * 直接用 `TableView` + `HorizontalHeaderView` + `FTableClickArea` 组装。原因：
 * 原表的「物品」列要画物品图标、数值列要右对齐、整行要能右键 ——
 * 这三样 `FSummaryTable` 都不提供（它的单元格只有文本 + 居中对齐 + 行内按钮）。
 * 展示规则本身仍只有一份：模型是 `CompareTableModel` 的子类，见
 * `ui_qml/models/compare_qml_model.py`。
 *
 * 与原版的差异（有意，逐条给理由）：
 *   1. 表格拉伸的是「物品」列。原版是 `setStretchLastSection(True)`，被拉伸的是
 *      最窄的「状态」列（90px 占满右侧空白，真正长的物品名反被截断）——
 *      QML 侧统一按「弹性列给最长的那一列」重排过，列名/顺序/宽度一字未改。
 *   2. 表头点了不排序。原版 `setSortingEnabled(True)` 其实**也是**空转：
 *      `CompareTableModel` 没实现 `sort()`，`QAbstractItemModel::sort` 是空操作，
 *      点表头只换了个排序箭头。QML 表头干脆不画那个箭头。
 */

Item {
    id: page

    //: 对比桥，由 `PageHost` 以 context property `bridge` 注入。
    //: 别名不与 context property 同名（同名声明会遮蔽它，恒为 null 且无报错）。
    readonly property var cmp: typeof bridge !== "undefined" ? bridge : null

    readonly property int fntBase: Math.round(12 * Theme.fontScale)
    readonly property int fntSmall: Math.round(11 * Theme.fontScale)
    readonly property int rowH: Math.max(26, Math.round(13 * Theme.fontScale) + 13)
    readonly property int headerH: Math.max(26, fntSmall + 15)
    readonly property int pad: Theme.spacingSm

    /* 列宽：provider 与点击区必须同口径 —— 两处各算一次会错位。
     * 「物品」列吃满剩余空间（不小于原版给的 160）。 */
    function colWidth(col) {
        const cols = page.cmp ? page.cmp.columns : []
        if (col >= cols.length)
            return 0
        if (col === 0) {
            let used = 0
            for (let i = 1; i < cols.length; ++i)
                used += cols[i].width
            return Math.max(cols[0].width, tableView.width - used)
        }
        return cols[col].width
    }

    Rectangle {
        anchors.fill: parent
        color: Theme.bgDark
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: page.pad
        spacing: page.pad

        // ═══════════════════════════════════════════════════════
        //  1. 搜索 + 添加
        // ═══════════════════════════════════════════════════════

        RowLayout {
            Layout.fillWidth: true
            spacing: page.pad

            FTextField {
                id: searchInput
                objectName: "searchInput"
                Layout.fillWidth: true
                placeholderText: qsTr("搜索物品名称或ID...")
                // 回写时加不等值判断：不加就是「设 text → textChanged → setSearchText → 属性变 → 重绑」的循环
                text: page.cmp ? page.cmp.searchText : ""
                onTextChanged: if (page.cmp && text !== page.cmp.searchText)
                    page.cmp.setSearchText(text)
                onAccepted: if (page.cmp)
                    page.cmp.runSearch()
            }

            FButton {
                objectName: "addBtn"
                text: qsTr("添加")
                primary: true
                onClicked: if (page.cmp)
                    page.cmp.addFirstMatch()
            }
        }

        // ═══════════════════════════════════════════════════════
        //  2. 已添加物品
        // ═══════════════════════════════════════════════════════

        RowLayout {
            Layout.fillWidth: true
            spacing: page.pad

            Text {
                text: qsTr("已添加:")
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntSmall
            }

            FButton {
                objectName: "clearBtn"
                text: qsTr("清空")
                onClicked: if (page.cmp)
                    page.cmp.clearItems()
            }

            Item {
                Layout.fillWidth: true
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: page.cmp ? page.cmp.itemListHeight : 0
            color: Theme.bgSurface
            radius: Theme.radiusSmall
            border.width: 1
            border.color: Theme.border

            ListView {
                id: itemList
                anchors.fill: parent
                anchors.margins: 1
                clip: true
                model: page.cmp ? page.cmp.items : []
                boundsBehavior: Flickable.StopAtBounds

                ScrollBar.vertical: ScrollBar {
                    policy: ScrollBar.AsNeeded
                }

                delegate: Item {
                    id: itemRow

                    required property var modelData
                    required property int index

                    width: itemList.width
                    height: Math.round(20 * Theme.fontScale)

                    Text {
                        anchors.left: parent.left
                        anchors.right: removeBtn.left
                        anchors.leftMargin: 6
                        anchors.rightMargin: 4
                        anchors.verticalCenter: parent.verticalCenter
                        text: (itemRow.index + 1) + ". " + itemRow.modelData.name
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: page.fntSmall
                        elide: Text.ElideRight
                    }

                    /* 行内「移除」：原版是一个 18×18 的扁平按钮 + close 图标。
                     * FButton 有 88px 的最小宽度，塞不进这一行，所以就地组合
                     * 图标 + MouseArea（不是新造基础控件，只是这一处的排版）。 */
                    Item {
                        id: removeBtn
                        objectName: "removeBtn" + itemRow.index
                        width: Math.round(18 * Theme.fontScale)
                        height: width
                        anchors.right: parent.right
                        anchors.rightMargin: 4
                        anchors.verticalCenter: parent.verticalCenter

                        Rectangle {
                            anchors.fill: parent
                            radius: width / 2
                            color: removeArea.containsMouse ? Theme.accentRed : "transparent"
                        }

                        Image {
                            anchors.centerIn: parent
                            width: Math.round(12 * Theme.fontScale)
                            height: width
                            source: "image://phosphor/x?c="
                                    + encodeURIComponent(Theme.hex(removeArea.containsMouse ? Theme.textOnPrimary : Theme.accentRed))
                                    + "&s=12"
                            sourceSize.width: width
                            sourceSize.height: height
                            smooth: true
                        }

                        MouseArea {
                            id: removeArea
                            anchors.fill: parent
                            hoverEnabled: true
                            onClicked: if (page.cmp)
                                page.cmp.removeItem(itemRow.index)
                        }
                    }
                }
            }
        }

        // ═══════════════════════════════════════════════════════
        //  3. 参数行
        // ═══════════════════════════════════════════════════════

        RowLayout {
            Layout.fillWidth: true
            spacing: page.pad

            Text {
                text: qsTr("类型:")
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntSmall
            }

            FComboBox {
                objectName: "modeBox"
                implicitWidth: 110
                model: page.cmp ? page.cmp.modeNames : []
                currentIndex: page.cmp ? page.cmp.modeIndex : 0
                onActivated: if (page.cmp)
                    page.cmp.setModeIndex(currentIndex)
            }

            Text {
                text: qsTr("区域:")
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntSmall
            }

            FComboBox {
                objectName: "hubBox"
                implicitWidth: 100
                model: page.cmp ? page.cmp.hubs : []
                currentIndex: page.cmp ? page.cmp.hubIndex : 0
                onActivated: if (page.cmp)
                    page.cmp.setHubIndex(currentIndex)
            }

            Text {
                text: qsTr("角色:")
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntSmall
            }

            FComboBox {
                objectName: "charBox"
                implicitWidth: 100
                model: page.cmp ? page.cmp.characters : []
                currentIndex: page.cmp ? page.cmp.charIndex : 0
                onActivated: if (page.cmp)
                    page.cmp.setCharIndex(currentIndex)
            }

            Text {
                visible: page.cmp ? page.cmp.showMeTe : false
                text: qsTr("ME:")
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntSmall
            }

            FSpinBox {
                objectName: "meBox"
                implicitWidth: 70
                visible: page.cmp ? page.cmp.showMeTe : false
                from: 0
                to: 10
                value: page.cmp ? page.cmp.me : 0
                onValueModified: if (page.cmp)
                    page.cmp.setMe(value)
            }

            Text {
                visible: page.cmp ? page.cmp.showMeTe : false
                text: qsTr("TE:")
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntSmall
            }

            FSpinBox {
                objectName: "teBox"
                implicitWidth: 70
                visible: page.cmp ? page.cmp.showMeTe : false
                from: 0
                to: 20
                value: page.cmp ? page.cmp.te : 0
                onValueModified: if (page.cmp)
                    page.cmp.setTe(value)
            }

            Text {
                text: qsTr("税%:")
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntSmall
            }

            FDoubleSpinBox {
                objectName: "taxBox"
                implicitWidth: 80
                from: 0
                to: 100
                decimals: 2
                value: page.cmp ? page.cmp.tax : 0
                onValueModified: if (page.cmp)
                    page.cmp.setTax(value)
            }

            Item {
                Layout.fillWidth: true
            }

            FButton {
                objectName: "compareBtn"
                text: qsTr("开始对比")
                primary: true
                enabled: page.cmp ? page.cmp.canCompare : false
                onClicked: if (page.cmp)
                    page.cmp.compare()
            }

            FButton {
                objectName: "exportBtn"
                text: qsTr("导出CSV")
                enabled: page.cmp ? page.cmp.exportEnabled : false
                onClicked: if (page.cmp)
                    page.cmp.exportCsv()
            }
        }

        // ═══════════════════════════════════════════════════════
        //  4. 进度条（原版是 3px 高的 QProgressBar，算完就藏起来）
        // ═══════════════════════════════════════════════════════

        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: 3
            visible: page.cmp ? page.cmp.progressVisible : false

            Rectangle {
                anchors.fill: parent
                color: Theme.bgSurface
            }

            Rectangle {
                height: parent.height
                width: (page.cmp && page.cmp.progressMax > 0)
                       ? parent.width * (page.cmp.progressValue / page.cmp.progressMax) : 0
                color: Theme.primary
            }
        }

        // ═══════════════════════════════════════════════════════
        //  5. 对比结果表
        // ═══════════════════════════════════════════════════════

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            Rectangle {
                anchors.fill: parent
                color: Theme.bgDark
                radius: Theme.radius
                border.width: 1
                border.color: Theme.border
            }

            HorizontalHeaderView {
                id: headerView
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                height: page.headerH
                syncView: tableView
                clip: true
                // 标题由 delegate 自己取；这个角色没人读，但必须真实存在（Qt 默认 "display" 不在模型里）
                textRole: "text"

                delegate: Item {
                    id: hcell
                    required property int index
                    implicitHeight: page.headerH

                    readonly property var colMeta: (page.cmp && page.cmp.columns.length > hcell.index)
                                                   ? page.cmp.columns[hcell.index] : null

                    Rectangle {
                        anchors.fill: parent
                        color: Theme.bgSurfaceLight

                        Rectangle {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            height: 1
                            color: Theme.border
                        }
                        Rectangle {
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.bottom: parent.bottom
                            width: 1
                            color: Theme.border
                        }
                    }

                    Text {
                        anchors.fill: parent
                        anchors.leftMargin: 6
                        anchors.rightMargin: 6
                        verticalAlignment: Text.AlignVCenter
                        horizontalAlignment: Text.AlignHCenter
                        text: hcell.colMeta ? hcell.colMeta.title : ""
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: page.fntSmall
                        font.bold: true
                        elide: Text.ElideRight
                    }
                }
            }

            TableView {
                id: tableView
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: headerView.bottom
                anchors.bottom: parent.bottom

                clip: true
                boundsBehavior: Flickable.StopAtBounds
                model: page.cmp ? page.cmp.model : null
                // 内建选中在 Qt 6.11 上不工作（详见 PlanTableBridge 的说明），
                // 本对话框也不需要选中态 —— 行操作全靠右键菜单
                selectionBehavior: TableView.SelectionDisabled
                reuseItems: true
                rowHeightProvider: function (row) { return page.rowH }
                columnWidthProvider: function (col) { return page.colWidth(col) }

                ScrollBar.vertical: ScrollBar {
                    policy: ScrollBar.AsNeeded
                }
                ScrollBar.horizontal: ScrollBar {
                    policy: ScrollBar.AsNeeded
                }

                delegate: Item {
                    id: cell

                    required property int row
                    required property int column
                    required property var model

                    //: 物品列画了图标，文字要给它让位
                    readonly property bool withIcon: cell.column === 0 && cell.model.iconUrl !== ""

                    implicitWidth: page.colWidth(cell.column)
                    implicitHeight: page.rowH

                    Rectangle {
                        anchors.fill: parent
                        color: cell.row % 2 === 0 ? Theme.bgDark : Theme.bgSurface
                    }

                    Image {
                        visible: cell.withIcon
                        anchors.left: parent.left
                        anchors.leftMargin: 4
                        anchors.verticalCenter: parent.verticalCenter
                        width: Math.round(18 * Theme.fontScale)
                        height: width
                        source: cell.withIcon ? cell.model.iconUrl : ""
                        sourceSize.width: width
                        sourceSize.height: height
                        smooth: true
                        fillMode: Image.PreserveAspectFit
                    }

                    Text {
                        anchors.fill: parent
                        anchors.leftMargin: cell.withIcon ? Math.round(26 * Theme.fontScale) : 6
                        anchors.rightMargin: 6
                        verticalAlignment: Text.AlignVCenter
                        horizontalAlignment: cell.model.alignRight ? Text.AlignRight : Text.AlignLeft
                        text: cell.model.text
                        color: cell.model.fg !== "" ? cell.model.fg : Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: page.fntBase
                        elide: Text.ElideRight
                    }

                    HoverHandler {
                        cursorShape: Qt.PointingHandCursor
                    }
                }

                // 行点击命中固定在按下那一刻（见 FTableClickArea 的说明）
                FTableClickArea {
                    objectName: "compareClickArea"
                    anchors.fill: parent
                    owner: tableView
                    rowHeight: page.rowH
                    columnWidth: page.colWidth

                    onRowRightClicked: function (row, _column, x, y) {
                        if (!page.cmp)
                            return
                        const info = page.cmp.rowInfo(row)
                        if (!info.valid)
                            return
                        rowMenu.row = row
                        rowMenu.typeId = info.typeId
                        rowMenu.itemName = info.name
                        const p = mapToItem(page, x, y)
                        rowMenu.x = p.x
                        rowMenu.y = p.y
                        rowMenu.openSoon()
                    }
                }
            }
        }

        // ═══════════════════════════════════════════════════════
        //  6. 状态行
        // ═══════════════════════════════════════════════════════

        Text {
            objectName: "statusText"
            Layout.fillWidth: true
            text: page.cmp ? page.cmp.statusText : ""
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: page.fntSmall
            elide: Text.ElideRight
        }
    }

    // 换模式会换一套列：TableView 的 columnWidthProvider 是函数，属性变了要显式重排
    Connections {
        target: page.cmp

        function onColumnsChanged() {
            tableView.forceLayout()
        }
    }

    // ═══════════════════════════════════════════════════════════
    //  行右键菜单
    // ═══════════════════════════════════════════════════════════

    FMenu {
        id: rowMenu
        objectName: "rowMenu"

        property int row: -1
        property int typeId: 0
        property string itemName: ""

        FMenuItem {
            text: qsTr("复制行数据")
            onTriggered: if (page.cmp)
                page.cmp.copyRow(rowMenu.row)
        }

        FMenuItem {
            text: qsTr("复制全部 (CSV)")
            onTriggered: if (page.cmp)
                page.cmp.copyAllCsv()
        }

        FMenuSeparator {}

        FMenuItem {
            text: qsTr("查看物品 ") + rowMenu.itemName
            visible: rowMenu.typeId > 0
            onTriggered: if (page.cmp)
                page.cmp.openItemDetail(rowMenu.row)
        }
    }
}
