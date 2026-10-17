import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 全物品浏览器（阶段 4b）—— **只作为查询页工作区的内嵌面板**使用。

 * 筛选行（搜索 + 类别 + 状态）→ 3px 进度条 → 左「市场分类树」右「物品表」的可拖动分栏。
 * 原独立窗形态（`AllItemsQmlDialog`）无生产入口，已随死代码清理删除：本文件现在只由
 * `QueryPage.qml` 内嵌实例化，工具栏按钮 / 置顶 / 右键菜单一并移除（它们只服务于独立窗）。
 *
 * 业务一律不在这里实现：每次交互都调 `ai.<方法>`，由
 * `ui_qml/bridge/all_items_bridge.py` 转给既有 worker / service / 原模型。
 *
 * 与原版逐条对齐 / 有意不同的地方：
 *   1. **不再有「制造评分 / 设置 / 贸易评分 / 设置 / 批量对比 / 导出 / 置顶」工具栏**：
 *      这些按钮只在已删除的独立窗里出现过；内嵌态按用户要求不带。
 *   2. **分类树是「带缩进的平表」**：QML 没有树控件，桥把树压成
 *      `treeRows`（`depth` / `hasChildren` 都在行上），箭头点击走 `toggleTreeNode`。
 *      展开/折叠状态由桥持有，与原版 `QTreeWidget` 的默认（全折叠）一致。
 *   3. **表头可点排序**：排序规则仍走 `Proxy.lessThan`（原 `setSortingEnabled(True)`）。
 *   4. **末列吃满剩余宽度**：即原版 `setStretchLastSection(True)` 的行为，
 *      列多到超出视口时没有剩余，就等于声明宽度。
 *   5. 行点击一律走 `FTableClickArea`（按**按下那一刻**的行号派发）—— 见该组件头部；
 *      分类树同理（它也是 ListView，滚过之后 delegate 上的 MouseArea 会点错行）。
 */

Item {
    id: page

    /* 全物品桥。查询页以 `ai: page.query.allItems` 显式注入 —— 页面上下文里的
     * `bridge` 是 `QueryBridge`（不是本面板的桥）。所以这里**不能 `readonly`**。 */
    property var ai: typeof bridge !== "undefined" ? bridge : null

    readonly property int fntSmall: Math.round(11 * Theme.fontScale)
    readonly property int fntBase: Math.round(12 * Theme.fontScale)
    readonly property int rowH: Math.max(26, Math.round(13 * Theme.fontScale) + 13)
    readonly property int headerH: Math.max(26, fntSmall + 15)
    //: 分类树的行高；`FTableClickArea` 的命中口径依赖它恒定
    readonly property int treeRowH: Math.max(20, Math.round(13 * Theme.fontScale) + 8)
    //: 分类树每层的缩进；也是「箭头列」的宽度（点击区分列用）
    readonly property int treeIndent: Math.round(12 * Theme.fontScale)

    /* 列宽：`TableView` 的 provider 与点击区必须同口径 —— 两处各算一次会错位。
     * 末列吃满剩余空间（见文件头第 4 条）。 */
    function colWidth(col) {
        const cols = page.ai ? page.ai.columns : []
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

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 2
        spacing: 1

        // ═══════════════════════════════════════════════════════
        //  1. 筛选行（含状态行 —— 原版状态就在这一行的右端）
        // ═══════════════════════════════════════════════════════

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingXs

            /* 本面板的搜索框**一直显示**（含内嵌态）。
             *
             * 与查询页工具栏那个框的分工：页面那个是「输入物品名 → 候选 → 详情」，
             * 本框是「在当前列表里筛」。内嵌时由 `QueryPage` 把**页面那个**藏起来 ——
             * 同一时刻页面上只有一个搜索框（用户要求），而两个语义各归各的，不会出现
             * 「搜了物品名却去筛全物品表」这种错位。类别 / 状态筛选也是本面板独有的。 */
            Text {
                text: qsTr("搜索:")
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntSmall
            }

            FTextField {
                id: searchField
                objectName: "searchField"
                Layout.fillWidth: true
                placeholderText: qsTr("名称/ID...")
                // 回写时加不等值判断：不加就是「设 text → textChanged → setSearchText → 属性变 → 重绑」的循环
                text: page.ai ? page.ai.searchText : ""
                onTextChanged: if (page.ai && text !== page.ai.searchText)
                    page.ai.setSearchText(text)
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
                model: page.ai ? page.ai.categories : []
                currentIndex: page.ai ? page.ai.categoryIndex : 0
                onActivated: if (page.ai)
                    page.ai.setCategoryIndex(currentIndex)
            }

            Text {
                objectName: "statusText"
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignRight
                text: page.ai ? page.ai.statusText : ""
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntSmall
                elide: Text.ElideRight
            }
        }

        // ═══════════════════════════════════════════════════════
        //  3. 进度条（原版是 3px 高的 QProgressBar，算完就藏起来）
        // ═══════════════════════════════════════════════════════

        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: 3
            visible: page.ai ? page.ai.progressVisible : false

            Rectangle {
                anchors.fill: parent
                color: Theme.bgSurface
            }

            Rectangle {
                height: parent.height
                color: Theme.primary
                width: (page.ai && page.ai.progressMax > 0)
                       ? parent.width * (page.ai.progressValue / page.ai.progressMax) : 0
            }
        }

        // ═══════════════════════════════════════════════════════
        //  4. 左树 + 右表（原版是 QSplitter，初始 [140, 960]，树宽 100–250）
        // ═══════════════════════════════════════════════════════

        SplitView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: Qt.Horizontal

            // 1px 分隔条（原版 `QSplitter.setHandleWidth(1)`）；Controls 2 的
            // SplitView 没有 handleWidth 属性，只能这样给 handle 定宽
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
                    model: page.ai ? page.ai.treeRows : []
                    boundsBehavior: Flickable.StopAtBounds

                    ScrollBar.vertical: ScrollBar {
                        policy: ScrollBar.AsNeeded
                    }

                    delegate: Item {
                        id: treeRow

                        required property var modelData
                        required property int index

                        readonly property bool selected: page.ai && page.ai.selectedTreeId === treeRow.modelData.id

                        width: treeList.width
                        height: page.treeRowH

                        Rectangle {
                            anchors.fill: parent
                            color: treeRow.selected ? Theme.primary : "transparent"
                        }

                        // 展开标记占「箭头列」的位置；点击区分列也以它为准
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

                    /* 点击命中固定在按下那一刻。第 0 列 = 展开标记，其余 = 选中该分类。
                     * 覆盖在 ListView 上是**内联子项**（挂在 contentItem 下），
                     * 坐标已是内容坐标，不必再传 owner。 */
                    FTableClickArea {
                        objectName: "treeClickArea"
                        anchors.fill: parent
                        rowHeight: page.treeRowH
                        columnWidth: function (col) {
                            return col === 0 ? page.treeIndent + 2 : treeList.width;
                        }
                        onRowClicked: function (row, column) {
                            if (!page.ai)
                                return
                            if (column === 0)
                                page.ai.toggleTreeNode(row)
                            else
                                page.ai.selectTreeNode(row)
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
                    // 标题由 delegate 自己取；这个角色没人读，但必须真实存在（Qt 默认 "display" 不在模型里）
                    textRole: "text"

                    delegate: Item {
                        id: hcell
                        required property int index
                        implicitHeight: page.headerH

                        readonly property var colMeta: (page.ai && page.ai.columns.length > hcell.index)
                                                       ? page.ai.columns[hcell.index] : null
                        readonly property bool sorted: page.ai && page.ai.sortColumn === hcell.index

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
                                  // 必须同时挡 `page.ai`：`hcell.sorted` 是派生属性（带缓存），
                                  // 桥变成 null 时它可能还是上一轮的 true，见 TradePage.qml 同款说明
                                  + ((page.ai && hcell.sorted)
                                     ? (page.ai.sortAscending ? " ▲" : " ▼") : "")
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
                            onClicked: if (page.ai)
                                page.ai.sortByColumn(hcell.index)
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
                    model: page.ai ? page.ai.model : null
                    // 内建选中在 Qt 6.11 上不工作（详见 PlanTableBridge 的说明）：
                    // 「当前行」由桥按点击行号自己记，选中态画在 delegate 上
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

                        //: 图标列画了图，文字要给它让位
                        readonly property bool withIcon: cell.column === 0 && cell.model.iconUrl !== ""
                        readonly property bool selected: page.ai && page.ai.selectedRow === cell.row

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

                    // 行点击命中固定在按下那一刻（见 FTableClickArea 的说明）
                    FTableClickArea {
                        objectName: "tableClickArea"
                        anchors.fill: parent
                        owner: tableView
                        rowHeight: page.rowH
                        columnWidth: page.colWidth

                        onRowClicked: function (row, column) {
                            if (page.ai)
                                page.ai.clickCell(row, column)
                        }

                        onRowDoubleClicked: function (row, _column) {
                            if (page.ai)
                                page.ai.openMaterials(row)
                        }
                    }
                }

                // 空态：状态行已经说了「共 N 条」，这里只画一句提示
                Text {
                    anchors.centerIn: parent
                    visible: (page.ai ? page.ai.rowCount : 0) === 0
                    text: qsTr("没有数据")
                    color: Theme.textSecondary
                    font.family: Theme.fontFamily
                    font.pixelSize: page.fntBase
                }
            }
        }
    }

    // 换模式 / 换分类会换一整套列：`columnWidthProvider` 是函数，属性变了要显式重排
    Connections {
        // `page.ai` 在**内嵌实例**的初始化早期可能还是 `undefined`（父项属性尚未赋值完），
        // 直接当 target 会报「Unable to assign [undefined] to QObject*」—— 归一成 null。
        target: page.ai ? page.ai : null

        function onStateChanged() {
            tableView.forceLayout()
        }
    }
}
