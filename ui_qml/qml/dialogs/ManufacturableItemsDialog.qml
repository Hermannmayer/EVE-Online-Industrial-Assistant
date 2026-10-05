import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 可制造物品浏览器 —— 覆盖在游戏上使用的浮窗。
 *
 * 布局：工具栏（刷新计算 + **内联的评分设置**「中心 / 人物 / 设施税」+ 最右「置顶」）
 * → 筛选行（搜索 / 类别 / 库存 / 日销量 / 利润率下限 / 状态）→ 3px 进度条 →
 * 左「可制造分类树」右「表单」的可拖动分栏。
 *
 * 与其它窗口统一的四件事（用户要求「按钮逻辑统一」）：
 *   1. 功能按钮靠左、**置顶复选框贴最右**（与 `AllItemsDialog.qml` / `ProcurementWindow.qml`
 *      同款）；没有二级「设置」对话框，设置项直接铺在工具栏。
 *   2. 内联设置控件用 `onActivated / onValueModified` 主动回写，**不写属性绑定**
 *      （写成 `currentIndex: model.indexOf(...)` 会被绑定立刻冲回去，见 `FPriceSourceRow.qml`）。
 *   3. 已按需求删掉「批量对比」「导出」两个按钮。
 *   4. **末列不再吃满剩余宽度**：列宽由桥按内容实测（`QFontMetrics`），越窄越好 ——
 *      这个窗口要在游戏界面上层显示，不能遮住后面的游戏数据。
 *
 * 表格列：图标 / 中文名 / English / 买价(hub) / 卖价(hub) / 成本 / 收入 / 产能·天 /
 * 日订单量 / 日成交量 / 状态 / 利润率%（已按需求删掉「均价 / 体积 / 日利润 / 收益」）。
 * 「日订单量 / 日成交量」是近 7 日平均（`order_count` / `volume`），由主界面右上角的
 * 「更新价格」统一拉取到本地 —— 本窗口零 ESI 请求。
 *
 * 业务一律不在这里实现：每次交互都调 `mi.<方法>`，由桥转给既有 worker / service。
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
    //: 底部状态脚注的高（见文件末尾那个 `statusText`）
    readonly property int statusH: Math.max(18, fntSmall + 7)

    /* 列宽：`TableView` 的 provider 与点击区必须同口径。
     * **不再把剩余宽度补给末列**（那是「列固定宽 + 铺满视口」的老口径）：宽度由桥按
     * 内容实测，表格右侧留白好过把每一列都拉宽 —— 这是覆盖在游戏上的浮窗。 */
    function colWidth(col) {
        const cols = page.mi ? page.mi.columns : []
        return col < cols.length ? cols[col].width : 0
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
        anchors.bottomMargin: page.statusH  // 给底部的状态脚注让位
        spacing: 1

        // ═══════════════════════════════════════════════════════
        //  1. 工具栏：**一行**装下功能按钮 + 搜索 + 全部筛选 + 内联设置 + 最右「置顶」
        // ═══════════════════════════════════════════════════════

        RowLayout {
            objectName: "mfgToolbar"
            Layout.fillWidth: true
            spacing: Theme.spacingXs

            FButton {
                objectName: "refreshButton"
                text: qsTr("刷新计算")
                onClicked: if (page.mi)
                    page.mi.refreshScores()
            }

            /* 搜索框：**做成一眼能看见的**（用户要求「更明显一点」）——
             * 铺一层浅底 + 圆角 + 1px 边框（聚焦转主题色），前面挂放大镜。
             * 这是这一行里唯一 `Layout.fillWidth` 的控件：窗口拉宽时先喂它。 */
            FTextField {
                id: searchField
                objectName: "searchField"
                Layout.fillWidth: true
                Layout.minimumWidth: 190
                Layout.preferredWidth: 240
                leftPadding: 26
                placeholderText: qsTr("搜索物品名称 / ID…")
                // 回写时加不等值判断：不加就是「设 text → textChanged → setSearchText → 属性变 → 重绑」的循环
                text: page.mi ? page.mi.searchText : ""
                onTextChanged: if (page.mi && text !== page.mi.searchText)
                    page.mi.setSearchText(text)

                background: Rectangle {
                    color: Theme.bgSurfaceLight
                    radius: Theme.radiusSmall
                    border.width: 1
                    border.color: searchField.activeFocus ? Theme.primary : Theme.border
                }

                /* 放大镜走图标 provider（`image://phosphor/<name>`，与外壳同一套）。
                 * **不能用 `🔍` 字符**：真平台上它会渲染成一个彩色圆点（emoji 回退），
                 * 出图核对时一眼就看出来了。`c` 必须 encodeURIComponent（见 ShellIconButton）。 */
                Image {
                    anchors.left: parent.left
                    anchors.leftMargin: 8
                    anchors.verticalCenter: parent.verticalCenter
                    width: 14
                    height: 14
                    sourceSize.width: 14
                    sourceSize.height: 14
                    fillMode: Image.PreserveAspectFit
                    source: "image://phosphor/magnifying-glass?c="
                            + encodeURIComponent(Theme.hex(Theme.textSecondary)) + "&s=14"
                }            }

            // ── 筛选（原「筛选行」，按用户要求与上面并成一行）──
            Text {
                text: qsTr("类别:")
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntSmall
            }

            FComboBox {
                objectName: "categoryBox"
                implicitWidth: 130
                model: page.mi ? page.mi.categories : []
                currentIndex: page.mi ? page.mi.categoryIndex : 0
                onActivated: if (page.mi)
                    page.mi.setCategoryIndex(currentIndex)
            }

            Text {
                text: qsTr("库存:")
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntSmall
            }

            FComboBox {
                objectName: "stockBox"
                implicitWidth: 120
                model: page.mi ? page.mi.stockFilters : []
                currentIndex: page.mi ? page.mi.stockFilterIndex : 0
                onActivated: if (page.mi)
                    page.mi.setStockFilterIndex(currentIndex)
            }

            Text {
                text: qsTr("日销量:")
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntSmall
            }

            FComboBox {
                objectName: "salesBox"
                implicitWidth: 92
                model: page.mi ? page.mi.salesFilters : []
                currentIndex: page.mi ? page.mi.salesFilterIndex : 0
                onActivated: if (page.mi)
                    page.mi.setSalesFilterIndex(currentIndex)
            }

            Text {
                text: qsTr("利润率 ≥")
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntSmall
            }

            /* 阈值输入框：**空 = 不筛**（不能拿 0 当默认 —— 那会把亏损行默认滤掉）。
             * 不限制只能输数字：非法输入桥侧一律当作「不筛」，比弹校验提示省事。 */
            FTextField {
                id: marginField
                objectName: "marginField"
                implicitWidth: 52
                placeholderText: qsTr("不限")
                text: page.mi ? page.mi.minMarginText : ""
                onTextChanged: if (page.mi && text !== page.mi.minMarginText)
                    page.mi.setMinMarginText(text)
            }

            Text {
                text: qsTr("%")
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntSmall
            }

            // ── 内联设置：中心 / 人物 / 设施税（原「设置」二级对话框的三个字段）──
            Text {
                text: qsTr("中心:")
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntSmall
            }

            FComboBox {
                objectName: "hubBox"
                implicitWidth: 92
                model: page.mi ? page.mi.hubs : []
                currentIndex: page.mi ? page.mi.hubIndex : 0
                onActivated: if (page.mi)
                    page.mi.setHubIndex(currentIndex)
            }

            Text {
                text: qsTr("人物:")
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntSmall
            }

            FComboBox {
                objectName: "charBox"
                implicitWidth: 110
                model: page.mi ? page.mi.characters : []
                currentIndex: page.mi ? page.mi.charIndex : 0
                onActivated: if (page.mi)
                    page.mi.setCharIndex(currentIndex)
            }

            Text {
                text: qsTr("设施税:")
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntSmall
            }

            FDoubleSpinBox {
                objectName: "taxBox"
                implicitWidth: 76
                from: 0
                to: 100
                decimals: 2
                value: page.mi ? page.mi.tax : 0
                onValueModified: if (page.mi)
                    page.mi.setTax(value)
            }

            Item {
                Layout.fillWidth: true
                Layout.minimumWidth: 8
            }

            FCheckBox {
                objectName: "pinBox"
                text: qsTr("置顶")
                checked: page.mi ? page.mi.pinned : false
                onToggled: if (page.mi)
                    page.mi.setPinned(checked)
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
        //  4. 左树 + 右表
        // ═══════════════════════════════════════════════════════

        SplitView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: Qt.Horizontal

            // 1px 分隔条
            handle: Rectangle {
                implicitWidth: 1
                implicitHeight: 1
                color: Theme.border
            }

            Rectangle {
                objectName: "treePane"
                SplitView.preferredWidth: 130
                SplitView.minimumWidth: 100
                SplitView.maximumWidth: 240
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
                        //: 当前类别下这个分类里没有可制造物品 → 置灰（仍可点，点了表格给提示）
                        readonly property bool empty: treeRow.modelData.empty === true

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
                            color: (treeRow.empty && !treeRow.selected) ? Theme.textSecondary : Theme.textPrimary
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
                                  // 必须同时挡 `page.mi`：`hcell.sorted` 是派生属性（带缓存），
                                  // 桥变成 null 时它可能还是上一轮的 true
                                  + ((page.mi && hcell.sorted)
                                     ? (page.mi.sortAscending ? " ▲" : " ▼") : "")
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
                    anchors.top: headerView.bottom
                    anchors.bottom: parent.bottom
                    // 列宽按内容实测、末列不铺满：表格宽度自己撑，超出就横向滚动
                    width: Math.min(parent.width, contentWidth)
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
                            rowMenu.typeId = info.typeId
                            rowMenu.itemName = info.name
                            rowMenu.blueprintName = info.blueprintName
                            rowMenu.hasMfgDetail = info.hasMfgDetail
                            const p = mapToItem(page, x, y)
                            rowMenu.x = p.x
                            rowMenu.y = p.y
                            rowMenu.openSoon()
                        }
                    }
                }

                /* 空态：**说清原因**（「这个分类在当前类别下没有物品」与「没有数据」不是一回事），
                 * 子树的置灰标记与它是配套的两半。 */
                Text {
                    anchors.centerIn: parent
                    width: Math.max(120, parent.width - 40)
                    visible: (page.mi ? page.mi.rowCount : 0) === 0
                    text: page.mi ? page.mi.emptyText : qsTr("没有数据")
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.WordWrap
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

    /* 状态行：单开一条**细脚注**，不占工具栏宽度。
     *
     * 为什么挪出来：工具栏按需求并成了一行（刷新 + 搜索 + 4 个筛选 + 3 个设置 + 置顶），
     * 再塞一个 240px 的状态文本就会把「置顶」挤出可视区（出图核对时实测被裁掉）。
     * 状态文本不是筛选项，放脚注更合适。 */
    Text {
        objectName: "statusText"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.leftMargin: Theme.spacingSm
        anchors.rightMargin: Theme.spacingSm
        height: page.statusH
        verticalAlignment: Text.AlignVCenter
        horizontalAlignment: Text.AlignRight
        text: page.mi ? page.mi.statusText : ""
        color: Theme.textSecondary
        font.family: Theme.fontFamily
        font.pixelSize: page.fntSmall
        elide: Text.ElideLeft
    }

    // ═══════════════════════════════════════════════════════════
    //  行右键菜单
    //
    //  少一项「贸易核算明细」：本窗口只建了制造缓存，没有贸易模式。
    //  复制项按需求只保留「名称 / 蓝图名称」（**没有**「复制ID」）。
    // ═══════════════════════════════════════════════════════════

    FMenu {
        id: rowMenu
        objectName: "rowMenu"

        property int row: -1
        property int typeId: 0
        property string itemName: ""
        property string blueprintName: ""
        property bool hasMfgDetail: false

        FMenuItem {
            objectName: "copyNameItem"
            text: qsTr("复制名称: ") + rowMenu.itemName
            onTriggered: if (page.mi)
                page.mi.copyName(rowMenu.row)
        }

        FMenuItem {
            objectName: "copyBlueprintItem"
            // 没有制造蓝图的物品不显示这一项（副标题里带蓝图名，选中前就知道复制的是什么）
            visible: rowMenu.blueprintName !== ""
            text: qsTr("复制蓝图名称: ") + rowMenu.blueprintName
            onTriggered: if (page.mi)
                page.mi.copyBlueprintName(rowMenu.row)
        }

        FMenuItem {
            objectName: "copyRowItem"
            text: qsTr("复制整行")
            onTriggered: if (page.mi)
                page.mi.copyRow(rowMenu.row)
        }

        FMenuSeparator {}

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

        FMenuSeparator {}

        FMenuItem {
            text: qsTr("加入拷贝规划")
            onTriggered: if (page.mi)
                page.mi.addResearch(rowMenu.row, "copying")
        }

        FMenuItem {
            text: qsTr("加入发明规划")
            onTriggered: if (page.mi)
                page.mi.addResearch(rowMenu.row, "invention")
        }

        FMenuItem {
            text: qsTr("加入效率研究规划")
            onTriggered: if (page.mi)
                page.mi.addResearch(rowMenu.row, "research")
        }
    }
}
