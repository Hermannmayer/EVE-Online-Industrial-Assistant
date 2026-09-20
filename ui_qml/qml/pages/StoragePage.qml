import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 仓库管理页 —— 阶段 3（最后一个页面）。
 *
 * 对照 Widgets 版 `ui_pyside6/views/inventory/`：
 *   顶部共享机库选择器 + 两个 Tab
 *     · 机库管理：5 个操作按钮 + 8 列物品表（含统计）
 *     · 蓝图管理：粘贴导入 / 刷新计算 + 三个过滤器 + 搜索 + 11 列蓝图表
 *
 * **业务动作一律不在这里实现**：每次交互都调 `inv.<方法>`，
 * 由 `ui_qml/bridge/inventory_bridge.py` 转给既有 service / worker。
 *
 * **多选由桥实现**（这是唯一真正需要多选的页面）：桥把选中集灌进**模型的
 * `selected` 角色**，delegate 直接读 `model.selected` —— 走 `dataChanged` 是
 * TableView 的原生刷新机制。修饰键在 Python 侧读（QML 拿不到）。
 *
 * 别改用「QML 派生的选中集合 + 逐格 indexOf」：那条路不只是慢（一次选中变化
 * 200 次跨 QML/Python 调用），实测那个派生绑定**根本不随选中变化重算**，
 * 表现为点了行、高亮不动（看着像选中了别的行）。
 *
 * **点击命中也由 `FTableClickArea` 统一负责**，不在 delegate 里挂 TapHandler：
 * 后者在内容甩动/沉降时会整次丢掉点击（详见该组件的说明）。
 *
 * 各类对话框（库存修正审阅、材料覆盖、蓝图导入审查、科研计划…）仍是 Widgets，
 * 属阶段 4；本页只负责把参数凑齐后交给桥。
 */
Item {
    id: page

    readonly property var inv: typeof bridge !== "undefined" ? bridge : null

    readonly property int fntBase: Math.round(12 * Theme.fontScale)
    readonly property int fntSmall: Math.round(11 * Theme.fontScale)
    readonly property int rowH: Math.max(28, Math.round(13 * Theme.fontScale) + 15)
    readonly property int headerH: Math.max(26, fntSmall + 15)
    readonly property int gap: Theme.spacingSm


    // 整页不透明底（宿主是透明清屏的 QQuickWidget，见 IndustryPage 的同款说明）
    Rectangle {
        anchors.fill: parent
        color: Theme.bgDark
    }

    /* 表格 delegate：文本 + 选中/当前高亮 + 图标 + 斑马纹。
     * `selectedRow` 由使用处给（两张表各自的选中判定）。 */
    component Cell: Item {
        id: tcell
        required property int row
        required property int column
        required property var model
        property bool selectedRow: false
        property int iconColumn: 0
        property bool wideIcon: false

        implicitHeight: page.rowH

        Rectangle {
            anchors.fill: parent
            color: tcell.selectedRow ? Theme.primary : (tcell.model.bg ? tcell.model.bg : Theme.bgSurface)
        }
        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 1
            color: Theme.border
        }

        Image {
            visible: tcell.column === tcell.iconColumn
            anchors.centerIn: parent
            width: tcell.wideIcon ? Math.round(28 * Theme.fontScale) : Math.round(20 * Theme.fontScale)
            height: width
            source: tcell.model.iconUrl
            sourceSize.width: width
            sourceSize.height: height
            smooth: true
            fillMode: Image.PreserveAspectFit
        }

        Text {
            visible: tcell.column !== tcell.iconColumn
            anchors.fill: parent
            anchors.leftMargin: Math.round(6 * Theme.fontScale)
            anchors.rightMargin: Math.round(6 * Theme.fontScale)
            verticalAlignment: Text.AlignVCenter
            horizontalAlignment: tcell.model.alignRight ? Text.AlignRight : Text.AlignLeft
            text: tcell.model.text !== undefined ? tcell.model.text : ""
            color: tcell.selectedRow ? Theme.textOnPrimary : (tcell.model.fg ? tcell.model.fg : Theme.textPrimary)
            font.family: Theme.fontFamily
            font.pixelSize: page.fntBase
            elide: Text.ElideRight
        }
    }

    /* 列宽：provider 与 delegate 必须同口径 —— 两处各算一次会错位。
     * 名称列吃满剩余空间（对齐 Widgets 版的 StretchLastSection 语义）。 */
    function itemColWidth(col) {
        const cols = inv ? inv.itemColumns : []
        if (col >= cols.length)
            return 0
        if (col === 1) {
            let used = 0
            for (let i = 0; i < cols.length; ++i) {
                if (i !== 1)
                    used += cols[i].width
            }
            return Math.max(140, itemTable.width - used)
        }
        return cols[col].width
    }

    function bpColWidth(col) {
        const cols = inv ? inv.blueprintColumns : []
        return col < cols.length ? cols[col].width : 80
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: page.gap

        // ═══════════════════════════════════════════════════════
        //  共享机库选择器
        // ═══════════════════════════════════════════════════════

        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: page.gap
            Layout.rightMargin: page.gap
            Layout.topMargin: page.gap
            spacing: page.gap

            Text {
                text: qsTr("机库:")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntBase
            }
            FComboBox {
                implicitWidth: 220
                model: page.inv ? page.inv.hangarNames : []
                currentIndex: page.inv ? page.inv.hangarIndex : 0
                onActivated: if (page.inv)
                    page.inv.setHangarIndex(currentIndex)
            }
            Item {
                Layout.fillWidth: true
            }
        }

        /* 标签栏靠左收窄，别铺满整行：`Layout.fillWidth: true` 会让两个 TabButton
         * 各撑到窗口一半宽，上半区看着一大片空荡（用户反馈「上面空的、不紧凑」）。*/
        RowLayout {
            Layout.fillWidth: true
            spacing: page.gap

            // 收窄的标签栏用 `FTabBar`（普通 `TabBar` 会等分宽度、截掉最长的标签）
            FTabBar {
                id: tabBar

                TabButton {
                    text: qsTr("机库管理")
                }
                TabButton {
                    text: qsTr("蓝图管理")
                }
            }
            Item {
                Layout.fillWidth: true
            }
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: tabBar.currentIndex

            // ═══════════════════════════════════════════════════
            //  Tab 1：机库管理
            // ═══════════════════════════════════════════════════

            ColumnLayout {
                spacing: page.gap

                RowLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: page.gap
                    Layout.rightMargin: page.gap
                    spacing: page.gap

                    FButton {
                        text: qsTr("库存修正")
                        onClicked: if (page.inv)
                            page.inv.runClipboardImport("full")
                    }
                    FButton {
                        text: qsTr("增量粘贴")
                        onClicked: if (page.inv)
                            page.inv.runClipboardImport("incremental")

                        HoverHandler {
                            id: incHover
                        }
                        ToolTip.visible: incHover.hovered
                        ToolTip.text: qsTr("读取剪贴板（游戏内复制物品 Ctrl+C），按增量累加的方式加入当前机库（只增不减）")
                    }
                    FButton {
                        text: qsTr("从剪贴板导入")
                        onClicked: if (page.inv)
                            page.inv.importPurchasesFromClipboard()

                        HoverHandler {
                            id: buyImportHover
                        }
                        ToolTip.visible: buyImportHover.hovered
                        ToolTip.text: qsTr("在游戏「钱包 → 交易记录」里 Ctrl+A/C 复制后点这里：把负 ISK 的买入行按单价（成本）入到指定机库")
                    }
                    FButton {
                        text: qsTr("查看规划缺失材料")
                        onClicked: if (page.inv)
                            page.inv.openMaterialCoverage()
                    }
                    FButton {
                        text: qsTr("手动添加物品")
                        onClicked: if (page.inv)
                            page.inv.addItemManually()
                    }

                    Item {
                        Layout.fillWidth: true
                    }

                    Text {
                        text: page.inv ? page.inv.itemCountText : ""
                        color: Theme.textSecondary
                        font.family: Theme.fontFamily
                        font.pixelSize: page.fntBase
                    }
                }

                Text {
                    Layout.fillWidth: true
                    Layout.leftMargin: 2 * page.gap
                    text: page.inv ? page.inv.itemTotalText : ""
                    color: Theme.primary
                    font.family: Theme.fontFamily
                    font.pixelSize: Math.round(13 * Theme.fontScale)
                    font.bold: true
                }

                Item {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.leftMargin: page.gap
                    Layout.rightMargin: page.gap
                    Layout.bottomMargin: page.gap

                    Rectangle {
                        anchors.fill: parent
                        color: Theme.bgSurface
                        radius: Theme.radius
                        border.width: 1
                        border.color: Theme.border
                    }

                    HorizontalHeaderView {
                        id: itemHeader
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        height: page.headerH
                        syncView: itemTable
                        clip: true
                        textRole: "text"

                        delegate: Item {
                            id: ih
                            required property int index
                            implicitHeight: page.headerH

                            readonly property var meta: (page.inv && page.inv.itemColumns.length > ih.index)
                                                        ? page.inv.itemColumns[ih.index] : null

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
                                horizontalAlignment: ih.index >= 2 ? Text.AlignRight : Text.AlignLeft
                                text: (ih.meta ? ih.meta.title : "")
                                      + (page.inv && page.inv.itemSortColumn === ih.index
                                         ? (page.inv.itemSortAscending ? " ▲" : " ▼") : "")
                                color: Theme.textPrimary
                                font.family: Theme.fontFamily
                                font.pixelSize: page.fntSmall
                                elide: Text.ElideRight
                            }

                            MouseArea {
                                anchors.fill: parent
                                acceptedButtons: Qt.LeftButton
                                // 只让可排序的列表头可点（可排序列由模型给出，只有一份判据）
                                enabled: page.inv ? page.inv.itemSortableColumns.indexOf(ih.index) >= 0 : false
                                onClicked: if (page.inv)
                                    page.inv.sortItems(ih.index)
                            }
                        }
                    }

                    TableView {
                        id: itemTable
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: itemHeader.bottom
                        anchors.bottom: parent.bottom

                        clip: true
                        boundsBehavior: Flickable.StopAtBounds
                        model: page.inv ? page.inv.itemModel : null
                        selectionBehavior: TableView.SelectionDisabled
                        reuseItems: true
                        rowHeightProvider: function (row) { return page.rowH }
                        columnWidthProvider: function (col) { return page.itemColWidth(col) }

                        ScrollBar.vertical: ScrollBar {
                            policy: ScrollBar.AsNeeded
                        }
                        ScrollBar.horizontal: ScrollBar {
                            policy: ScrollBar.AsNeeded
                        }
                        delegate: Cell {
                            wideIcon: true
                            selectedRow: model.selected === true
                            implicitWidth: page.itemColWidth(column)
                        }

                        /* 点击命中固定在按下那一刻（见 FTableClickArea 的说明）：
                         * delegate 内的 TapHandler 会在内容甩动/沉降时整次丢失点击。 */
                        FTableClickArea {
                            objectName: "itemClickArea"
                            anchors.fill: parent
                            rowHeight: page.rowH
                            columnWidth: page.itemColWidth

                            onRowClicked: function (row, _column) {
                                if (page.inv)
                                    page.inv.selectItemRow(row)
                            }
                            onRowRightClicked: function (row, _column, x, y) {
                                if (!page.inv)
                                    return
                                const p = mapToItem(page, x, y)
                                itemMenu.state = page.inv.itemMenuState(row)
                                itemMenu.targetRows = page.inv.itemsForMenu(row)
                                itemMenu.row = row
                                itemMenu.x = p.x
                                itemMenu.y = p.y
                                itemMenu.openSoon()
                            }
                        }
                    }
                }
            }

            // ═══════════════════════════════════════════════════
            //  Tab 2：蓝图管理
            // ═══════════════════════════════════════════════════

            ColumnLayout {
                spacing: page.gap

                RowLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: page.gap
                    Layout.rightMargin: page.gap
                    spacing: page.gap

                    FButton {
                        text: qsTr("粘贴导入蓝图")
                        onClicked: if (page.inv)
                            page.inv.pasteBlueprints()
                    }
                    FButton {
                        text: qsTr("刷新计算")
                        onClicked: if (page.inv)
                            page.inv.refreshEconomics()
                    }
                    Item {
                        Layout.fillWidth: true
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: page.gap
                    Layout.rightMargin: page.gap
                    spacing: page.gap

                    Text {
                        text: qsTr("类型:")
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: page.fntBase
                    }
                    FComboBox {
                        implicitWidth: 110
                        model: page.inv ? page.inv.typeFilters : []
                        currentIndex: page.inv ? page.inv.typeFilterIndex : 0
                        onActivated: if (page.inv)
                            page.inv.setTypeFilterIndex(currentIndex)
                    }

                    Text {
                        text: qsTr("科技等级:")
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: page.fntBase
                    }
                    FComboBox {
                        implicitWidth: 90
                        model: page.inv ? page.inv.techFilters : []
                        currentIndex: page.inv ? page.inv.techFilterIndex : 0
                        onActivated: if (page.inv)
                            page.inv.setTechFilterIndex(currentIndex)
                    }

                    Text {
                        text: qsTr("市场分类:")
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: page.fntBase
                    }
                    FComboBox {
                        Layout.fillWidth: true
                        model: page.inv ? page.inv.marketCategories.map(c => c.name) : []
                        currentIndex: page.inv ? page.inv.marketFilterIndex : 0
                        onActivated: if (page.inv)
                            page.inv.setMarketFilterIndex(currentIndex)
                    }

                    Text {
                        text: qsTr("搜索:")
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: page.fntBase
                    }
                    FTextField {
                        Layout.preferredWidth: 220
                        placeholderText: qsTr("输入蓝图/产物名称...")
                        onTextChanged: if (page.inv)
                            page.inv.setBlueprintSearch(text)
                    }
                }

                Item {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.leftMargin: page.gap
                    Layout.rightMargin: page.gap

                    Rectangle {
                        anchors.fill: parent
                        color: Theme.bgSurface
                        radius: Theme.radius
                        border.width: 1
                        border.color: Theme.border
                    }

                    HorizontalHeaderView {
                        id: bpHeader
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        height: page.headerH
                        syncView: bpTable
                        clip: true
                        textRole: "text"

                        delegate: Item {
                            id: bh
                            required property int index
                            implicitHeight: page.headerH

                            readonly property var meta: (page.inv && page.inv.blueprintColumns.length > bh.index)
                                                        ? page.inv.blueprintColumns[bh.index] : null

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
                                horizontalAlignment: bh.index >= 2 ? Text.AlignRight : Text.AlignLeft
                                text: (bh.meta ? bh.meta.title : "")
                                      + (page.inv && page.inv.blueprintSortColumn === bh.index
                                         ? (page.inv.blueprintSortAscending ? " ▲" : " ▼") : "")
                                color: Theme.textPrimary
                                font.family: Theme.fontFamily
                                font.pixelSize: page.fntSmall
                                elide: Text.ElideRight
                            }

                            MouseArea {
                                anchors.fill: parent
                                acceptedButtons: Qt.LeftButton
                                // 只让可排序的列表头可点（可排序列由模型给出，只有一份判据）
                                enabled: page.inv ? page.inv.blueprintSortableColumns.indexOf(bh.index) >= 0 : false
                                onClicked: if (page.inv)
                                    page.inv.sortBlueprints(bh.index)
                            }
                        }
                    }

                    TableView {
                        id: bpTable
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: bpHeader.bottom
                        anchors.bottom: parent.bottom

                        clip: true
                        boundsBehavior: Flickable.StopAtBounds
                        model: page.inv ? page.inv.blueprintModel : null
                        selectionBehavior: TableView.SelectionDisabled
                        reuseItems: true
                        rowHeightProvider: function (row) { return page.rowH }
                        columnWidthProvider: function (col) { return page.bpColWidth(col) }

                        ScrollBar.vertical: ScrollBar {
                            policy: ScrollBar.AsNeeded
                        }
                        ScrollBar.horizontal: ScrollBar {
                            policy: ScrollBar.AsNeeded
                        }

                        delegate: Cell {
                            iconColumn: 0
                            selectedRow: model.selected === true
                            implicitWidth: page.bpColWidth(column)
                        }

                        // 同上：命中固定在按下那一刻
                        FTableClickArea {
                            objectName: "bpClickArea"
                            anchors.fill: parent
                            rowHeight: page.rowH
                            columnWidth: page.bpColWidth

                            onRowClicked: function (row, column) {
                                if (!page.inv)
                                    return
                                page.inv.selectBlueprintRow(row)
                                if (column !== 0)
                                    page.inv.copyBlueprintCell(row)
                            }
                            onRowRightClicked: function (row, _column, x, y) {
                                if (!page.inv)
                                    return
                                const p = mapToItem(page, x, y)
                                bpMenu.state = page.inv.blueprintMenuState(row)
                                bpMenu.targetRows = page.inv.blueprintsForMenu(row)
                                bpMenu.row = row
                                bpMenu.x = p.x
                                bpMenu.y = p.y
                                bpMenu.openSoon()
                            }
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: 2 * page.gap
                    Layout.rightMargin: 2 * page.gap
                    Layout.bottomMargin: page.gap

                    Text {
                        text: page.inv ? page.inv.blueprintCountText : ""
                        color: Theme.textSecondary
                        font.family: Theme.fontFamily
                        font.pixelSize: page.fntBase
                    }
                    Item {
                        Layout.fillWidth: true
                    }
                }
            }
        }
    }

    // ═══════════════════════════════════════════════════════════
    //  机库行右键菜单
    // ═══════════════════════════════════════════════════════════

    FMenu {
        id: itemMenu
        objectName: "itemMenu"
        property int row: -1
        property var state: ({})
        property var targetRows: []

        FMenuItem {
            text: qsTr("编辑数量")
            visible: itemMenu.state.single === true
            onTriggered: page.inv.editItemQuantity(itemMenu.row)
        }
        FMenuItem {
            text: qsTr("编辑成本价")
            onTriggered: page.inv.editItemsCost(itemMenu.targetRows)
        }
        FMenuItem {
            text: itemMenu.state.count > 1 ? qsTr("删除 (%1)").arg(itemMenu.state.count) : qsTr("删除")
            onTriggered: page.inv.deleteItems(itemMenu.targetRows)
        }

        FMenu {
            title: itemMenu.state.count > 1
                   ? qsTr("移动到 (%1)").arg(itemMenu.state.count) : qsTr("移动到")
            Repeater {
                model: itemMenu.state.moveTargets || []
                FMenuItem {
                    required property var modelData
                    text: modelData.name
                    onTriggered: page.inv.moveItems(itemMenu.targetRows, modelData.id)
                }
            }
        }

        FMenuSeparator {}
        FMenuItem {
            text: qsTr("复制名称")
            onTriggered: page.inv.copyItemNames(itemMenu.targetRows)
        }
        FMenuItem {
            text: qsTr("复制 type_id")
            onTriggered: page.inv.copyItemTypeIds(itemMenu.targetRows)
        }
    }

    // ═══════════════════════════════════════════════════════════
    //  蓝图行右键菜单
    // ═══════════════════════════════════════════════════════════

    FMenu {
        id: bpMenu
        objectName: "bpMenu"
        property int row: -1
        property var state: ({})
        property var targetRows: []

        FMenuItem {
            text: qsTr("研究分析")
            onTriggered: page.inv.showResearchAnalysis(bpMenu.targetRows)
        }
        FMenuSeparator {}
        FMenuItem {
            text: bpMenu.state.count > 1 ? qsTr("删除行 (%1)").arg(bpMenu.state.count) : qsTr("删除行")
            onTriggered: page.inv.deleteBlueprints(bpMenu.targetRows)
        }
        FMenuSeparator {}
        FMenuItem {
            text: qsTr("修改蓝图所在机库")
            onTriggered: page.inv.moveBlueprints(bpMenu.targetRows)
        }
        FMenuItem {
            text: qsTr("修改蓝图每流程成本")
            onTriggered: page.inv.setBlueprintCostPerRun(bpMenu.targetRows)
        }
        FMenuItem {
            text: qsTr("自动填写每流程成本(T2发明)")
            onTriggered: page.inv.autoFillCostPerRun(bpMenu.targetRows)
        }
        FMenuSeparator {}
        FMenuItem {
            text: qsTr("加入制造业规划")
            onTriggered: page.inv.addToManufacturingPlan(bpMenu.targetRows)
        }
        FMenuItem {
            text: qsTr("加入拷贝规划")
            onTriggered: page.inv.addCopyPlan(bpMenu.targetRows)
        }
        FMenuItem {
            text: qsTr("加入发明规划")
            onTriggered: page.inv.addInventionPlan(bpMenu.targetRows)
        }
        FMenuItem {
            text: qsTr("加入效率研究规划")
            onTriggered: page.inv.addResearchPlan(bpMenu.targetRows)
        }
        FMenuSeparator {}
        FMenuItem {
            text: qsTr("修改蓝图等级")
            onTriggered: page.inv.editBlueprintLevels(bpMenu.targetRows)
        }
        FMenuItem {
            text: qsTr("修改流程数")
            onTriggered: page.inv.editBlueprintRuns(bpMenu.targetRows)
        }
    }
}
