import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 可制造物品浏览器（阶段 4b）—— 对照
 * `ui_pyside6/views/manufacturable_items_dialog.py::ManufacturableItemsDialog`。
 *
 * 工具栏（刷新计算 / 设置 / 批量对比 / 导出 / 钉，居中）→ 筛选行（搜索 + 类别 + 状态）→
 * 3px 进度条 → 左「可制造分类树」右「表单（基础列 + 制造列）」的可拖动分栏。
 * 表的列固定是 基础列 + 制造列（这个窗口只做制造评分），没有全物品窗口的模式切换。
 *
 * 业务一律不在这里实现：每次交互都调 `mi.<方法>`，由
 * `ui_qml/bridge/manufacturable_items_bridge.py` 转给既有 worker / service / 原模型。
 * 分类树、线程收尾、「加入制造列表」落库与「制造材料」明细都与全物品窗口同一份实现。
 *
 * 与原版逐条对齐 / 有意不同的地方：
 *   1. **分类树是「带缩进的平表」**（QML 没有树控件），展开状态在桥里按 id 记。
 *   2. **表头可点排序**：排序规则仍走 `Proxy.lessThan`（原 `setSortingEnabled(True)`）。
 *   3. **末列吃满剩余宽度**：即原版 `setStretchLastSection(True)` 的行为。
 *   4. **Ctrl+C / Ctrl+A 用 `Shortcut`** 实现（原版是 `keyPressEvent`）：
 *      Ctrl+C 复制当前行；Ctrl+A 原版是「全选 + 复制」，QML 表只有单行选中，
 *      于是直接复制整表 —— 同一件事的超集。
 *   5. 行点击一律走 `FTableClickArea`，分类树同理（见该组件头部）。
 */

Item {
    id: page

    //: 可制造物品桥，由 `PageHost` 以 context property `bridge` 注入。
    //: 别名不与 context property 同名（同名声明会遮蔽它，恒为 null 且无报错）。
    readonly property var mi: typeof bridge !== "undefined" ? bridge : null

    readonly property int fntSmall: Math.round(11 * Theme.fontScale)
    readonly property int fntBase: Math.round(12 * Theme.fontScale)
    readonly property int rowH: Math.max(26, Math.round(13 * Theme.fontScale) + 13)
    readonly property int headerH: Math.max(26, fntSmall + 15)
    readonly property int treeRowH: Math.max(20, Math.round(13 * Theme.fontScale) + 8)
    readonly property int treeIndent: Math.round(12 * Theme.fontScale)

    /* 列宽：`TableView` 的 provider 与点击区必须同口径。末列吃满剩余空间
     * （原版 `setStretchLastSection(True)`；列超出视口时没有剩余，等于原宽）。 */
    function colWidth(col) {
        const cols = page.mi ? page.mi.columns : []
        if (col >= cols.length)
            return 0
        if (col !== cols.length - 1)
            return cols[col].width
        let used = 0
        for (let i = 0; i < col; ++i)
            used += cols[i].width
        return Math.max(cols[col].width, tableView.width - used)
    }

    Rectangle {
        anchors.fill: parent
        color: Theme.bgDark
    }

    // ── 键盘快捷键（原 `keyPressEvent`）──
    Shortcut {
        sequences: ["Ctrl+C"]
        onActivated: if (page.mi)
            page.mi.copySelection()
    }

    Shortcut {
        sequences: ["Ctrl+A"]
        onActivated: if (page.mi)
            page.mi.copyAll()
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 2
        spacing: 1

        // ═══════════════════════════════════════════════════════
        //  1. 工具栏（原版两侧各一个 stretch —— 按钮居中）
        // ═══════════════════════════════════════════════════════

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingXs

            Item {
                Layout.fillWidth: true
            }

            FButton {
                objectName: "refreshButton"
                text: qsTr("刷新计算")
                onClicked: if (page.mi)
                    page.mi.refreshScores()
            }

            FButton {
                objectName: "settingsButton"
                text: qsTr("设置")
                onClicked: if (page.mi)
                    page.mi.openMfgSettings()
            }

            FButton {
                objectName: "compareButton"
                text: qsTr("批量对比")
                onClicked: if (page.mi)
                    page.mi.openCompare()
            }

            FButton {
                objectName: "exportButton"
                text: qsTr("导出")
                onClicked: if (page.mi)
                    page.mi.exportData()
            }

            FButton {
                objectName: "pinButton"
                text: page.mi ? page.mi.pinLabel : qsTr("钉")
                onClicked: if (page.mi)
                    page.mi.setPinned(!page.mi.pinned)
            }

            Item {
                Layout.fillWidth: true
            }
        }

        // ═══════════════════════════════════════════════════════
        //  2. 筛选行（状态行也在这一行的右端）
        // ═══════════════════════════════════════════════════════

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingXs

            FTextField {
                id: searchField
                objectName: "searchField"
                Layout.fillWidth: true
                placeholderText: qsTr("搜索物品名称/ID...")
                // 回写时加不等值判断：不加就是「设 text → textChanged → setSearchText → 属性变 → 重绑」的循环
                text: page.mi ? page.mi.searchText : ""
                onTextChanged: if (page.mi && text !== page.mi.searchText)
                    page.mi.setSearchText(text)
            }

            Text {
                text: qsTr("类别:")
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntSmall
            }

            FComboBox {
                objectName: "categoryBox"
                implicitWidth: 190
                model: page.mi ? page.mi.categories : []
                currentIndex: page.mi ? page.mi.categoryIndex : 0
                onActivated: if (page.mi)
                    page.mi.setCategoryIndex(currentIndex)
            }

            Text {
                objectName: "statusText"
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignRight
                text: page.mi ? page.mi.statusText : ""
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntSmall
                elide: Text.ElideRight
            }
        }

        // ═══════════════════════════════════════════════════════
        //  3. 进度条（原版是 3px 高的 QProgressBar）
        // ═══════════════════════════════════════════════════════

        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: 3
            visible: page.mi ? page.mi.progressVisible : false

            Rectangle {
                anchors.fill: parent
                color: Theme.bgSurface
            }

            Rectangle {
                height: parent.height
                color: Theme.primary
                width: (page.mi && page.mi.progressMax > 0)
                       ? parent.width * (page.mi.progressValue / page.mi.progressMax) : 0
            }
        }

        // ═══════════════════════════════════════════════════════
        //  4. 左树 + 右表（原版是 QSplitter，初始 [140, 960]，树宽 100–250）
        // ═══════════════════════════════════════════════════════

        SplitView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: Qt.Horizontal

            // 1px 分隔条（原版 `QSplitter.setHandleWidth(1)`）
            handle: Rectangle {
                implicitWidth: 1
                implicitHeight: 1
                color: Theme.border
            }

            Rectangle {
                objectName: "treePane"
                SplitView.preferredWidth: 140
                SplitView.minimumWidth: 100
                SplitView.maximumWidth: 250
                color: Theme.bgSurface
                border.width: 1
                border.color: Theme.border

                ListView {
                    id: treeList
                    anchors.fill: parent
                    anchors.margins: 1
                    clip: true
                    model: page.mi ? page.mi.treeRows : []
                    boundsBehavior: Flickable.StopAtBounds

                    ScrollBar.vertical: ScrollBar {
                        policy: ScrollBar.AsNeeded
                    }

                    delegate: Item {
                        id: treeRow

                        required property var modelData

                        readonly property bool selected: page.mi && page.mi.selectedTreeId === treeRow.modelData.id

                        width: treeList.width
                        height: page.treeRowH

                        Rectangle {
                            anchors.fill: parent
                            color: treeRow.selected ? Theme.primary : "transparent"
                        }

                        Text {
                            id: arrow
                            anchors.left: parent.left
                            anchors.leftMargin: 2
                            anchors.verticalCenter: parent.verticalCenter
                            width: page.treeIndent
                            text: treeRow.modelData.hasChildren
                                  ? (treeRow.modelData.expanded ? "▾" : "▸") : ""
                            color: Theme.textSecondary
                            font.family: Theme.fontFamily
                            font.pixelSize: page.fntSmall
                            horizontalAlignment: Text.AlignHCenter
                        }

                        Text {
                            anchors.left: arrow.right
                            anchors.leftMargin: 2 + treeRow.modelData.depth * page.treeIndent
                            anchors.right: parent.right
                            anchors.rightMargin: 4
                            anchors.verticalCenter: parent.verticalCenter
                            text: treeRow.modelData.name
                            color: Theme.textPrimary
                            font.family: Theme.fontFamily
                            font.pixelSize: page.fntSmall
                            elide: Text.ElideRight
                        }
                    }

                    FTableClickArea {
                        objectName: "treeClickArea"
                        anchors.fill: parent
                        rowHeight: page.treeRowH
                        columnWidth: function (col) {
                            return col === 0 ? page.treeIndent + 2 : treeList.width;
                        }
                        onRowClicked: function (row, column) {
                            if (!page.mi)
                                return
                            if (column === 0)
                                page.mi.toggleTreeNode(row)
                            else
                                page.mi.selectTreeNode(row)
                        }
                    }
                }
            }

            Item {
                objectName: "tablePane"
                SplitView.fillWidth: true

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
                    textRole: "text"

                    delegate: Item {
                        id: hcell
                        required property int index
                        implicitHeight: page.headerH

                        readonly property var colMeta: (page.mi && page.mi.columns.length > hcell.index)
                                                       ? page.mi.columns[hcell.index] : null
                        readonly property bool sorted: page.mi && page.mi.sortColumn === hcell.index

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
                            text: (hcell.colMeta ? hcell.colMeta.title : "")
                                  + (hcell.sorted ? (page.mi.sortAscending ? " ▲" : " ▼") : "")
                            color: Theme.textPrimary
                            font.family: Theme.fontFamily
                            font.pixelSize: page.fntSmall
                            font.bold: true
                            elide: Text.ElideRight
                        }

                        MouseArea {
                            objectName: "headerClick" + hcell.index
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: if (page.mi)
                                page.mi.sortByColumn(hcell.index)
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
                    model: page.mi ? page.mi.model : null
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

                        readonly property bool withIcon: cell.column === 0 && cell.model.iconUrl !== ""
                        readonly property bool selected: page.mi && page.mi.selectedRow === cell.row

                        implicitWidth: page.colWidth(cell.column)
                        implicitHeight: page.rowH

                        Rectangle {
                            anchors.fill: parent
                            color: cell.selected ? Theme.primary
                                                 : (cell.row % 2 === 0 ? Theme.bgDark : Theme.bgSurface)
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

                    FTableClickArea {
                        objectName: "tableClickArea"
                        anchors.fill: parent
                        owner: tableView
                        rowHeight: page.rowH
                        columnWidth: page.colWidth

                        onRowClicked: function (row, column) {
                            if (page.mi)
                                page.mi.clickCell(row, column)
                        }

                        onRowDoubleClicked: function (row, _column) {
                            if (page.mi)
                                page.mi.openMaterials(row)
                        }

                        onRowRightClicked: function (row, _column, x, y) {
                            if (!page.mi)
                                return
                            const info = page.mi.rowInfo(row)
                            if (!info.valid)
                                return
                            rowMenu.row = row
                            rowMenu.hasMfgDetail = info.hasMfgDetail
                            const p = mapToItem(page, x, y)
                            rowMenu.x = p.x
                            rowMenu.y = p.y
                            rowMenu.open()
                        }
                    }
                }

                Text {
                    anchors.centerIn: parent
                    visible: (page.mi ? page.mi.rowCount : 0) === 0
                    text: qsTr("没有数据")
                    color: Theme.textSecondary
                    font.family: Theme.fontFamily
                    font.pixelSize: page.fntBase
                }
            }
        }
    }

    // 换分类 / 换数据都会换整套行：`columnWidthProvider` 是函数，属性变了要显式重排
    Connections {
        target: page.mi

        function onStateChanged() {
            tableView.forceLayout()
        }
    }

    // ═══════════════════════════════════════════════════════════
    //  行右键菜单（原 `_ctx`：这个窗口专为制造评分设计，明细始终可见）
    // ═══════════════════════════════════════════════════════════

    FMenu {
        id: rowMenu
        objectName: "rowMenu"

        property int row: -1
        property bool hasMfgDetail: false

        FMenuItem {
            text: qsTr("制造核算明细")
            visible: rowMenu.hasMfgDetail
            onTriggered: if (page.mi)
                page.mi.showBreakdown(rowMenu.row)
        }

        FMenuSeparator {}

        FMenuItem {
            text: qsTr("加入制造列表")
            onTriggered: if (page.mi)
                page.mi.addToPlan(rowMenu.row)
        }
    }
}
