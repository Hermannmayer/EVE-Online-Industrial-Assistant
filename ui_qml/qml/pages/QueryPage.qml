import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 物品查询页 —— 阶段 3。
 *
 * 对照 Widgets 版 `ui_pyside6/views/query/query_page.py`：
 *   工具栏（全物品 / 搜索框+候选 / 搜索 / 清空 / 批量查价 / 区域）
 *   + 进度条 + 状态行 + 结果表（8 列，可排序、右键菜单、双击看实时订单）。
 *
 * **业务动作一律不在这里实现**：每次交互都调 `query.<方法>`，
 * 由 `ui_qml/bridge/query_bridge.py` 转给既有的 worker / service。
 *
 * 行的「选中」只有**当前行**（原版虽然设了 ExtendedSelection，但右键菜单取的是
 * `indexAt(pos)` 那一行，批量操作并不存在），所以这里用一个 QML 侧属性即可，
 * 不需要搬计划表那套 QItemSelectionModel。
 */
Item {
    id: page

    /* 查询桥，由 `PageHost` 以 context property `bridge` 注入。
     * 别名不与 context property 同名（同名声明会遮蔽它，恒为 null 且无报错）。 */
    readonly property var query: typeof bridge !== "undefined" ? bridge : null

    readonly property int fntBase: Math.round(12 * Theme.fontScale)
    readonly property int fntSmall: Math.round(11 * Theme.fontScale)
    readonly property int rowH: Math.max(28, Math.round(13 * Theme.fontScale) + 15)
    readonly property int headerH: Math.max(26, fntSmall + 15)

    //: 当前行（右键菜单与高亮用）
    property int currentRow: -1

    // 整页不透明底（宿主是透明清屏的 QQuickWidget，见 IndustryPage 的同款说明）
    Rectangle {
        anchors.fill: parent
        color: Theme.bgDark
    }

    /* 列宽：provider 与点击区必须同口径 —— 两处各算一次会错位。 */
    function colWidth(col) {
        const cols = page.query ? page.query.columns : []
        return col < cols.length ? cols[col].width : 80
    }

    function rowsForMenu(row) {
        return [row]
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // ═══════════════════════════════════════════════════════
        //  1. 工具栏
        // ═══════════════════════════════════════════════════════

        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.spacingSm
            Layout.rightMargin: Theme.spacingSm
            Layout.topMargin: Theme.spacingSm
            Layout.bottomMargin: Theme.spacingSm
            spacing: Theme.spacingSm

            FButton {
                id: allItemsButton
                text: qsTr("全物品")
                onClicked: if (page.query)
                    page.query.openAllItems()

                HoverHandler {
                    id: allItemsHover
                }
                ToolTip.visible: allItemsHover.hovered
                ToolTip.text: qsTr("打开全物品浏览器")
            }

            FTextField {
                id: searchInput
                Layout.fillWidth: true
                placeholderText: qsTr("输入物品名称/ID/类别搜索...")
                onTextChanged: if (page.query)
                    page.query.onTextChanged(text)
                onAccepted: if (page.query)
                    page.query.search()
                Keys.onEscapePressed: suggestPopup.close()
            }

            FButton {
                text: qsTr("搜索")
                primary: true
                onClicked: if (page.query)
                    page.query.search()
            }

            FButton {
                text: qsTr("清空")
                onClicked: {
                    searchInput.text = ""
                    if (page.query)
                        page.query.clear()
                }
            }

            FButton {
                id: batchPriceButton
                text: qsTr("批量查价")
                onClicked: if (page.query)
                    page.query.openBatchPrice()

                HoverHandler {
                    id: batchHover
                }
                ToolTip.visible: batchHover.hovered
                ToolTip.text: qsTr("一次性查询多个物品的价格")
            }

            Item {
                Layout.fillWidth: true
            }

            Text {
                text: qsTr("区域:")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntBase
            }

            FComboBox {
                id: regionCombo
                implicitWidth: 96
                model: page.query ? page.query.regions : []
                currentIndex: page.query ? page.query.regionIndex : 0
                onActivated: if (page.query)
                    page.query.setRegionIndex(currentIndex)
            }
        }

        // ═══════════════════════════════════════════════════════
        //  2. 进度条（查询中显示，3px 不确定态）
        // ═══════════════════════════════════════════════════════

        Rectangle {
            id: progressTrack
            Layout.fillWidth: true
            height: 3
            visible: page.query ? page.query.busy : false
            color: Theme.bgSurfaceLight

            Rectangle {
                id: progressBlob
                width: Math.max(40, progressTrack.width * 0.3)
                height: parent.height
                color: Theme.primary

                NumberAnimation on x {
                    from: -progressBlob.width
                    to: progressTrack.width
                    duration: 900
                    loops: Animation.Infinite
                    running: progressTrack.visible
                }
            }
        }

        // ═══════════════════════════════════════════════════════
        //  3. 状态行
        // ═══════════════════════════════════════════════════════

        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.spacingSm
            Layout.rightMargin: Theme.spacingSm
            Layout.topMargin: 2
            Layout.bottomMargin: 2
            spacing: Theme.spacingSm

            Text {
                text: page.query ? page.query.countText : ""
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntSmall
            }

            Item {
                Layout.fillWidth: true
            }

            Text {
                Layout.maximumWidth: Math.max(120, page.width * 0.6)
                text: page.query ? page.query.statusText : ""
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntSmall
                elide: Text.ElideRight
                horizontalAlignment: Text.AlignRight
            }
        }

        // ═══════════════════════════════════════════════════════
        //  4. 结果表
        // ═══════════════════════════════════════════════════════

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            /* 外框内缩：与「价格监控」页同款观感（表格区被一块带描边的面裹住，
             * 而不是通铺到页边）。内缩量取本页工具栏用的同一个 spacingSm。 */
            Layout.leftMargin: Theme.spacingSm
            Layout.rightMargin: Theme.spacingSm
            Layout.bottomMargin: Theme.spacingSm

            Rectangle {
                anchors.fill: parent
                color: Theme.bgSurface
                radius: Theme.radius
            }

            /* 边框单独画一层、且 `z` 高于表头与表体。
             *
             * 不能像别处那样把 border 加在底色矩形上：表头 `HorizontalHeaderView` 与
             * `TableView` 都是 `anchors.fill/top: parent`，声明在底色之后，会把 1px 的
             * 边框线**整个盖掉** —— 实测「价格监控」页的上边框就是这么消失的
             * （左右边框幸运地没被盖住，所以看上去像有框）。
             * 纯 `Rectangle` 不带 MouseArea，不吞鼠标事件，覆盖在上层不影响点表。 */
            Rectangle {
                anchors.fill: parent
                z: 1
                color: "transparent"
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
                // 标题由 delegate 自己从 `columns` 取；这个角色**没人读**，
                // 但必须指向模型里真实存在的角色（Qt 的默认值是 "display"，
                // 模型里没有，会为每个表头项刷一条 assign 告警）
                textRole: "text"

                delegate: Item {
                    id: hcell
                    required property int index
                    implicitHeight: page.headerH

                    readonly property var meta: page.query && page.query.columns.length > hcell.index
                                                 ? page.query.columns[hcell.index] : null
                    readonly property bool sorted: page.query && page.query.sortColumn === hcell.index

                    Rectangle {
                        anchors.fill: parent
                        color: Theme.bgSurface

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
                        Rectangle {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            height: 2
                            visible: hcell.sorted
                            color: Theme.primary
                        }
                    }

                    Text {
                        anchors.fill: parent
                        anchors.leftMargin: Math.round(6 * Theme.fontScale)
                        anchors.rightMargin: Math.round(6 * Theme.fontScale)
                        verticalAlignment: Text.AlignVCenter
                        horizontalAlignment: Text.AlignLeft
                        text: (hcell.meta ? hcell.meta.title : "")
                              + (hcell.sorted ? (page.query.sortAscending ? " ▲" : " ▼") : "")
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: page.fntSmall
                        elide: Text.ElideRight
                    }

                    HoverHandler {
                        cursorShape: Qt.PointingHandCursor
                    }

                    MouseArea {
                        anchors.fill: parent
                        acceptedButtons: Qt.LeftButton
                        onClicked: if (page.query) {
                            // 首次点该列从升序开始；再点同一列反向（与 QTableView 一致）
                            const asc = page.query.sortColumn === hcell.index ? !page.query.sortAscending : true
                            page.query.sortBy(hcell.index, asc)
                        }
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
                model: page.query ? page.query.model : null
                // Qt 的内建点击选中在 6.11 上不工作（详见 PlanTableBridge 的说明），
                // 这张表只需要「当前行」，高亮由 delegate 读 page.currentRow 自己画
                selectionBehavior: TableView.SelectionDisabled
                reuseItems: true
                rowHeightProvider: function (row) { return page.rowH }
                columnWidthProvider: function (col) { return page.colWidth(col) }

                ScrollBar.vertical: ScrollBar {
                    policy: ScrollBar.AsNeeded
                }

                delegate: Item {
                    id: cell

                    required property int row
                    required property int column
                    required property bool selected
                    required property var model

                    implicitWidth: cell.colMeta ? cell.colMeta.width : 80
                    implicitHeight: page.rowH

                    readonly property bool isCurrent: page.currentRow === row
                    readonly property var colMeta: page.query && page.query.columns.length > cell.column
                                                  ? page.query.columns[cell.column] : null

                    Rectangle {
                        anchors.fill: parent
                        color: cell.isCurrent ? Theme.primary : (cell.model.bg || Theme.bgSurface)
                    }

                    Rectangle {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        height: 1
                        color: Theme.border
                    }

                    Image {
                        visible: cell.column === 0
                        anchors.centerIn: parent
                        width: Math.round(24 * Theme.fontScale)
                        height: width
                        source: cell.model.iconUrl
                        sourceSize.width: width
                        sourceSize.height: height
                        smooth: true
                        fillMode: Image.PreserveAspectFit
                    }

                    Text {
                        visible: cell.column !== 0
                        anchors.fill: parent
                        anchors.leftMargin: Math.round(8 * Theme.fontScale)
                        anchors.rightMargin: Math.round(6 * Theme.fontScale)
                        verticalAlignment: Text.AlignVCenter
                        horizontalAlignment: cell.model.alignRight ? Text.AlignRight : Text.AlignLeft
                        text: cell.model.text
                        color: cell.isCurrent ? Theme.textOnPrimary : (cell.model.fg || Theme.textPrimary)
                        font.family: cell.model.mono ? "Consolas" : Theme.fontFamily
                        font.pixelSize: page.fntBase
                        elide: Text.ElideRight
                    }

                    HoverHandler {
                        cursorShape: Qt.PointingHandCursor
                    }

                }

                /* 行点击命中固定在按下那一刻（见 FTableClickArea 的说明）。
                 * 原先在 delegate 里挂 TapHandler，配 ReleaseWithinBounds 时
                 * 内容一移动整次点击就被丢掉。 */
                FTableClickArea {
                    objectName: "queryClickArea"
                    anchors.fill: parent
                    rowHeight: page.rowH
                    columnWidth: page.colWidth

                    onRowClicked: function (row, _column) {
                        page.currentRow = row
                    }
                    onRowDoubleClicked: function (row, _column) {
                        page.currentRow = row
                        if (page.query)
                            page.query.rowDoubleClicked(row)
                    }
                    onRowRightClicked: function (row, _column, x, y) {
                        page.currentRow = row
                        const p = mapToItem(page, x, y)
                        rowMenu.state = page.query ? page.query.menuState(row) : ({})
                        rowMenu.targetRow = row
                        rowMenu.x = p.x
                        rowMenu.y = p.y
                        rowMenu.openSoon()
                    }
                }
            }
        }
    }

    // ═══════════════════════════════════════════════════════════
    //  搜索候选 / 历史（贴在输入框下方）
    // ═══════════════════════════════════════════════════════════

    Popup {
        id: suggestPopup
        objectName: "suggestPopup"
        // 以输入框为父项：位置由 Qt 在 open 时换算，**不要**用 mapToItem 手算坐标
        // （函数调用不被绑定依赖追踪，只在创建时求值一次，会永远贴在左上角）
        parent: searchInput
        x: 0
        y: searchInput.height + 2
        width: Math.max(searchInput.width, 260)
        padding: 2
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        readonly property var items: page.query && page.query.suggestions.length > 0
                                     ? page.query.suggestions
                                     : (page.query && searchInput.text.length === 0 ? page.query.history : [])
        readonly property bool showingHistory: !(page.query && page.query.suggestions.length > 0)

        visible: items.length > 0

        background: Rectangle {
            color: Theme.bgElevated
            border.color: Theme.border
            border.width: 1
            radius: Theme.radius
        }

        contentItem: ListView {
            clip: true
            implicitHeight: Math.min(280, contentHeight)
            model: suggestPopup.items
            ScrollIndicator.vertical: ScrollIndicator {}

            delegate: ItemDelegate {
                id: suggestItem
                required property var modelData
                width: ListView.view.width
                implicitHeight: 28

                contentItem: Text {
                    leftPadding: Theme.spacingSm
                    rightPadding: Theme.spacingSm
                    verticalAlignment: Text.AlignVCenter
                    text: suggestPopup.showingHistory
                          ? qsTr("历史: %1").arg(String(suggestItem.modelData))
                          : String(suggestItem.modelData.text)
                    color: Theme.textPrimary
                    font.family: Theme.fontFamily
                    font.pixelSize: page.fntBase
                    elide: Text.ElideRight
                }

                background: Rectangle {
                    radius: Theme.radiusSmall
                    color: suggestItem.highlighted ? Theme.bgHover : "transparent"
                }

                onClicked: {
                    if (page.query)
                        page.query.pickSuggestion(suggestPopup.showingHistory
                                                  ? String(suggestItem.modelData)
                                                  : String(suggestItem.modelData.text))
                    searchInput.forceActiveFocus()
                }
            }
        }
    }

    // ═══════════════════════════════════════════════════════════
    //  右键菜单（用 FMenuItem：不可见时不占高度）
    // ═══════════════════════════════════════════════════════════

    FMenu {
        id: rowMenu
        objectName: "rowMenu"
        property int targetRow: -1
        property var state: ({})

        FMenuItem {
            text: qsTr("复制名称")
            onTriggered: page.query.copyName(rowMenu.targetRow)
        }
        FMenuItem {
            text: qsTr("复制 Type ID")
            onTriggered: page.query.copyTypeId(rowMenu.targetRow)
        }
        FMenuItem {
            text: qsTr("复制买单价格")
            visible: rowMenu.state.hasBuy === true
            onTriggered: page.query.copyBuy(rowMenu.targetRow)
        }
        FMenuItem {
            text: qsTr("复制卖单价格")
            visible: rowMenu.state.hasSell === true
            onTriggered: page.query.copySell(rowMenu.targetRow)
        }
        FMenuSeparator {}

        FMenuItem {
            text: qsTr("查看实时订单")
            onTriggered: page.query.viewOrders(rowMenu.targetRow)
        }
        FMenuItem {
            text: qsTr("查看制造配方")
            onTriggered: page.query.viewManufacturing(rowMenu.state.typeId)
        }
        FMenuSeparator {}

        FMenuItem {
            text: qsTr("复制整行 (TSV)")
            onTriggered: page.query.copyRowTsv(rowMenu.targetRow)
        }
    }
}
