import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 合同页签的公共主体 —— 拍卖 / 物品交换 / 运输三张表只差「绑哪个 model、要哪些筛选」，
 * 表格骨架、物品明细、右键菜单、进度条完全一样，所以收成一个组件（与 `PlanTablePane` 同款做法）。
 *
 * 业务动作一律不在这里实现：每次交互都调 `pane.c.<方法>`，由 `contract_bridge.py` 转给
 * worker / service。本文件只负责「显示什么、去哪儿取」。
 */

Item {
    id: pane

    //: 便于按页签定位（测试与排查用；三个实例同名会让 findChild 拿到第一个）
    objectName: "contractTabPane_" + tabKey

    //: 页签 key，与 bridge 的 `_TAB_KEYS` 一致
    required property string tabKey
    //: 合同桥，由 `ContractPage` 传进来（不读 context property —— 那会在组件里被同名属性遮蔽）
    property var c: null
    //: 该页签的列定义（由 bridge 下发，单一来源在 contract_models）
    property var columns: []
    //: 该页签的行模型
    property var model: null
    //: 当前选中行 —— 下方物品面板显示的是它的物品，不给高亮用户不知道在看哪一行
    property int currentRow: -1

    readonly property bool isCourier: tabKey === "courier"
    readonly property int fntBase: Math.round(12 * Theme.fontScale)
    readonly property int fntSmall: Math.round(11 * Theme.fontScale)
    readonly property int rowH: Math.max(24, Math.round(13 * Theme.fontScale) + 11)
    readonly property int headerH: Math.max(24, fntSmall + 13)
    readonly property int gap: Theme.spacingSm

    function colWidth(col) {
        return col < pane.columns.length ? pane.columns[col].width : 100
    }

    Rectangle {
        anchors.fill: parent
        color: Theme.bgDark
    }

    /* 两张表共用：文本 + 可选取色 + 斑马纹。`model` 由 TableView 按行给下来。 */
    component TableCell: Item {
        id: tcell
        required property int row
        required property int column
        required property var model

        //: 该表格的列定义来源 —— 总表是 `pane.columns`，物品表是 `itemColumns`
        //: （两张表列数不同，混用会把「图标列」标到别的列上）
        property var columnsMeta: pane.columns

        implicitHeight: pane.rowH

        readonly property bool isCurrent: pane.currentRow === tcell.row
        //: 该列前面画物品图标（列定义由桥下发，单一来源在 contract_models）
        readonly property bool asIcons: tcell.columnsMeta.length > tcell.column
                                        && tcell.columnsMeta[tcell.column].icons === true
        readonly property var iconList: tcell.asIcons ? (tcell.model.iconUrls || []) : []

        Rectangle {
            anchors.fill: parent
            color: tcell.isCurrent
                   ? Theme.primary
                   : (tcell.model.bg !== undefined && tcell.model.bg ? tcell.model.bg : Theme.bgSurface)
        }
        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 1
            color: Theme.border
        }

        /* 「物品」列：主物品的图标（有就画，涂装之类本来就没有图）—— 文字照常显示，
         * 由下面的 Text 负责，这里只把文字往右让开。 */
        Row {
            id: iconRow
            visible: tcell.iconList.length > 0
            anchors.left: parent.left
            anchors.leftMargin: Math.round(5 * Theme.fontScale)
            anchors.verticalCenter: parent.verticalCenter
            spacing: Math.round(2 * Theme.fontScale)

            Repeater {
                model: tcell.iconList

                delegate: Image {
                    required property string modelData
                    anchors.verticalCenter: parent.verticalCenter
                    width: Math.round(18 * Theme.fontScale)
                    height: width
                    source: modelData
                    sourceSize.width: width
                    sourceSize.height: height
                    fillMode: Image.PreserveAspectFit
                    smooth: true
                }
            }
        }

        Text {
            anchors.fill: parent
            anchors.leftMargin: iconRow.visible ? iconRow.width + Math.round(11 * Theme.fontScale)
                                                : Math.round(6 * Theme.fontScale)
            anchors.rightMargin: Math.round(6 * Theme.fontScale)
            verticalAlignment: Text.AlignVCenter
            horizontalAlignment: tcell.model.alignRight ? Text.AlignRight : Text.AlignLeft
            text: tcell.model.text !== undefined ? tcell.model.text : ""
            color: tcell.isCurrent ? Theme.textOnPrimary : (tcell.model.fg ? tcell.model.fg : Theme.textPrimary)
            font.family: tcell.model.mono === true ? "Consolas" : Theme.fontFamily
            font.pixelSize: pane.fntBase
            elide: Text.ElideRight
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // ═══════════════════════════════════════════════
        //  筛选栏（各页签不同）
        // ═══════════════════════════════════════════════

        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 2 * pane.gap
            Layout.rightMargin: 2 * pane.gap
            Layout.topMargin: pane.gap
            Layout.bottomMargin: pane.gap
            spacing: pane.gap

            Text {
                text: qsTr("价格:")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: pane.fntBase
                visible: !pane.isCourier
            }
            FDoubleSpinBox {
                implicitWidth: 150
                from: 0
                to: 1e13
                decimals: 0
                visible: !pane.isCourier
                value: pane.c ? pane.c.priceMin : 0
                onValueModified: if (pane.c) pane.c.setPriceMin(value)
            }
            Text {
                text: "~"
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: pane.fntBase
                visible: !pane.isCourier
            }
            FDoubleSpinBox {
                implicitWidth: 150
                from: 0
                to: 1e13
                decimals: 0
                visible: !pane.isCourier
                value: pane.c ? pane.c.priceMax : 0
                onValueModified: if (pane.c) pane.c.setPriceMax(value)
            }

            // 蓝图筛选用体积启发式（蓝图固定 0.01 m³）—— 不需要先拉物品就能筛
            FCheckBox {
                text: qsTr("只看蓝图合同")
                visible: pane.tabKey === "exchange"
                checked: pane.c ? pane.c.blueprintOnly : false
                onToggled: if (pane.c) pane.c.setBlueprintOnly(checked)
            }

            Text {
                text: qsTr("剩余至少:")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: pane.fntBase
            }
            FSpinBox {
                implicitWidth: 90
                from: 0
                to: 720
                value: pane.c ? pane.c.minHoursLeft : 0
                onValueModified: if (pane.c) pane.c.setMinHoursLeft(value)
            }
            Text {
                text: qsTr("小时")
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: pane.fntBase
            }

            // 运输页的跳数口径 —— **选了口径才算**（本地 BFS 虽快，但没必要替用户决定）
            Text {
                text: qsTr("跳数口径:")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: pane.fntBase
                visible: pane.isCourier
            }
            FComboBox {
                implicitWidth: 150
                visible: pane.isCourier
                model: pane.c ? pane.c.jumpModes : []
                currentIndex: pane.c ? pane.c.jumpModeIndex : 0
                onActivated: if (pane.c) pane.c.setJumpModeIndex(currentIndex)
            }
            Text {
                text: qsTr("最低安全:")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: pane.fntBase
                visible: pane.isCourier && pane.c && pane.c.jumpModeIndex === 3
            }
            FDoubleSpinBox {
                implicitWidth: 100
                from: -1.0
                to: 1.0
                decimals: 2
                stepSize: 0.05
                visible: pane.isCourier && pane.c && pane.c.jumpModeIndex === 3
                value: pane.c ? pane.c.minSecurity : 0.45
                onValueModified: if (pane.c) pane.c.setMinSecurity(value)
            }

            Item {
                Layout.fillWidth: true
            }

            FButton {
                text: qsTr("应用筛选")
                onClicked: if (pane.c) pane.c.applyFilters()
            }
        }

        // ═══════════════════════════════════════════════
        //  合同表（+ 物品明细）
        // ═══════════════════════════════════════════════

        SplitView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.leftMargin: 2 * pane.gap
            Layout.rightMargin: 2 * pane.gap
            Layout.bottomMargin: pane.gap
            orientation: Qt.Vertical

            handle: Rectangle {
                implicitHeight: pane.isCourier ? 0 : 4
                visible: !pane.isCourier
                color: SplitHandle.pressed || SplitHandle.hovered ? Theme.primary : Theme.border
            }

            Item {
                SplitView.preferredHeight: pane.isCourier ? pane.height : Math.round(pane.height * 0.6)
                SplitView.minimumHeight: 120

                Rectangle {
                    anchors.fill: parent
                    color: Theme.bgSurface
                    radius: Theme.radius
                }
                /* 外框单独一层、z 高于表头与表体 —— 它们都是 anchors.fill 且声明在后，
                 * 把边框加在底色矩形上会被整个盖掉。纯 Rectangle 不吞鼠标事件。 */
                Rectangle {
                    anchors.fill: parent
                    z: 1
                    color: "transparent"
                    radius: Theme.radius
                    border.width: 1
                    border.color: Theme.border
                }

                HorizontalHeaderView {
                    id: header
                    objectName: "contractHeader_" + pane.tabKey
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    height: pane.headerH
                    syncView: table
                    clip: true
                    textRole: "text"

                    delegate: Item {
                        id: chead
                        required property int index
                        implicitHeight: pane.headerH

                        readonly property var meta: index < pane.columns.length ? pane.columns[index] : null
                        readonly property bool sorted: pane.c !== null && pane.c.sortColumn === chead.index

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
                        }
                        Text {
                            anchors.fill: parent
                            anchors.leftMargin: 6
                            anchors.rightMargin: 6
                            verticalAlignment: Text.AlignVCenter
                            // 排序箭头画在表头里：光能点、看不出按哪列排过，等于没排
                            // 必须同时挡 `pane.c`：`chead.sorted` 是派生属性（带缓存），
                            // 桥变成 null 时它可能还是上一轮的 true，见 TradePage.qml 同款说明
                            text: (chead.meta ? chead.meta.title : "")
                                  + ((pane.c && chead.sorted)
                                     ? (pane.c.sortAscending ? " ▲" : " ▼") : "")
                            color: chead.sorted ? Theme.primary : Theme.textPrimary
                            font.family: Theme.fontFamily
                            font.pixelSize: pane.fntSmall
                            elide: Text.ElideRight
                        }
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: if (pane.c) pane.c.sortBy(chead.index)
                        }
                    }
                }

                TableView {
                    id: table
                    objectName: "contractTable_" + pane.tabKey
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: header.bottom
                    anchors.bottom: parent.bottom

                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    model: pane.model
                    selectionBehavior: TableView.SelectionDisabled
                    reuseItems: true
                    rowHeightProvider: function (row) { return pane.rowH }
                    columnWidthProvider: function (col) { return pane.colWidth(col) }

                    /* 表第一次拿到实际尺寸时，让模型重播一次。
                     *
                     * 修的是这个静默缺陷：**数据比首次布局先到**时（页面 `Component.onCompleted`
                     * 就发起查库，可能快过窗口 show），`TableView` 的 `contentItem` 会停在 0×0
                     * 且此后不自愈 —— 点击区 `anchors.fill = parent` 跟着变成 0×0，
                     * 界面看着完全正常，但**点哪一行都没反应**。
                     *
                     * 实测只有**模型重置**能重算；`forceLayout()`、重挂 `model`、
                     * 监听 `modelReset` 都无效（后两者见 2026-09-20 的排查）。
                     * 正常顺序（先布局后数据）下 `_layoutDone` 早已为真，这里不触发。 */
                    property bool _layoutDone: false
                    function _ensureLaidOut() {
                        if (_layoutDone || width <= 0 || height <= 0)
                            return
                        _layoutDone = true
                        if (pane.model)
                            pane.model.notifyReset()
                    }
                    onWidthChanged: _ensureLaidOut()
                    onHeightChanged: _ensureLaidOut()

                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                    ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AsNeeded }

                    delegate: TableCell {
                        implicitWidth: pane.colWidth(column)
                    }

                    // 命中固定在按下那一刻（见 FTableClickArea 的说明）
                    FTableClickArea {
                        objectName: "contractClickArea_" + pane.tabKey
                        anchors.fill: parent
                        rowHeight: pane.rowH
                        columnWidth: pane.colWidth

                        onRowClicked: function (row, _column) {
                            pane.currentRow = row
                            if (pane.c) pane.c.selectContract(row)
                        }
                        /* 双击 = 复制发布者。游戏内搜合同只能按发布者搜（ID 搜不到），
                         * 而这一页唯一的动作就是「看中了 → 去游戏里找它」。
                         * 物品明细在下方面板里，不再另开二级窗口。 */
                        onRowDoubleClicked: function (row, _column) {
                            pane.currentRow = row
                            if (pane.c) pane.c.copyIssuer(row)
                        }
                        onRowRightClicked: function (row, _column, x, y) {
                            const p = mapToItem(pane, x, y)
                            rowMenu.row = row
                            rowMenu.x = p.x
                            rowMenu.y = p.y
                            rowMenu.openSoon()
                        }
                    }
                }
            }

            // ── 物品明细（运输合同没有物品，整块不显示）──
            Item {
                visible: !pane.isCourier
                SplitView.minimumHeight: 100

                Rectangle {
                    anchors.fill: parent
                    color: Theme.bgSurface
                    radius: Theme.radius
                }
                Rectangle {
                    anchors.fill: parent
                    z: 1
                    color: "transparent"
                    radius: Theme.radius
                    border.width: 1
                    border.color: Theme.border
                }

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: pane.headerH
                        color: Theme.bgSurface

                        Text {
                            anchors.left: parent.left
                            anchors.leftMargin: pane.gap
                            anchors.verticalCenter: parent.verticalCenter
                            text: qsTr("合同物品（选中上方合同查看；单价按该星域市价，缺价回落 Jita）")
                            color: Theme.textSecondary
                            font.family: Theme.fontFamily
                            font.pixelSize: pane.fntBase
                            font.bold: true
                        }
                    }

                    Item {
                        Layout.fillWidth: true
                        Layout.fillHeight: true

                        HorizontalHeaderView {
                            id: itemHeader
                            objectName: "itemHeader_" + pane.tabKey
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            height: pane.headerH
                            syncView: itemTable
                            clip: true
                            textRole: "text"

                            delegate: Item {
                                id: ihead
                                required property int index
                                implicitHeight: pane.headerH

                                readonly property var meta: (pane.c && pane.c.itemColumns.length > index)
                                                             ? pane.c.itemColumns[index] : null
                                readonly property bool sorted: pane.c !== null && pane.c.itemSortColumn === ihead.index

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
                                }
                                Text {
                                    anchors.fill: parent
                                    anchors.leftMargin: 6
                                    anchors.rightMargin: 6
                                    verticalAlignment: Text.AlignVCenter
                                    // 同上面材料表头：派生属性 `sorted` 会滞后，源头要自己验
                                    text: (ihead.meta ? ihead.meta.title : "")
                                          + ((pane.c && ihead.sorted)
                                             ? (pane.c.itemSortAscending ? " ▲" : " ▼") : "")
                                    color: ihead.sorted ? Theme.primary : Theme.textPrimary
                                    font.family: Theme.fontFamily
                                    font.pixelSize: pane.fntSmall
                                    elide: Text.ElideRight
                                }
                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: if (pane.c) pane.c.itemSortBy(ihead.index)
                                }
                            }
                        }

                        TableView {
                            id: itemTable
                            objectName: "itemTable_" + pane.tabKey
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: itemHeader.bottom
                            anchors.bottom: parent.bottom

                            clip: true
                            boundsBehavior: Flickable.StopAtBounds
                            model: pane.c ? pane.c.itemModel : null
                            selectionBehavior: TableView.SelectionDisabled
                            reuseItems: true
                            rowHeightProvider: function (row) { return pane.rowH }
                            columnWidthProvider: function (col) {
                                const cols = pane.c ? pane.c.itemColumns : []
                                return col < cols.length ? cols[col].width : 100
                            }

                            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                            delegate: TableCell {
                                columnsMeta: pane.c ? pane.c.itemColumns : []
                                implicitWidth: {
                                    const cols = pane.c ? pane.c.itemColumns : []
                                    return column < cols.length ? cols[column].width : 100
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    // ═══════════════════════════════════════════════
    //  行右键菜单
    // ═══════════════════════════════════════════════

    FMenu {
        id: rowMenu
        objectName: "contractRowMenu_" + pane.tabKey
        property int row: -1

        FMenuItem {
            text: qsTr("复制发布者")
            onTriggered: if (pane.c) pane.c.copyIssuer(rowMenu.row)
        }
        FMenuItem {
            text: qsTr("复制物品列表")
            onTriggered: if (pane.c) pane.c.copyItems()
        }
        FMenuSeparator {}
        FMenuItem {
            text: qsTr("加入关注列表")
            onTriggered: if (pane.c) pane.c.addItemsToWatchlist()
        }
    }
}
