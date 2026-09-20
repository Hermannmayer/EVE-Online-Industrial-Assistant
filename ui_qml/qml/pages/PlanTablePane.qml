import QtQuick
import QtQuick.Controls
import "../components"

/* 生产计划表（Fluent） —— 阶段 2a。
 *
 * 对照 Widgets 版 ui_pyside6/views/industry/plan_table.py + plan_table_delegate.py：
 * 19 列、类别染色、图标、备料勾选、折叠、表头排序/列宽拖拽/列可见性、行右键菜单、
 * 单元格内联编辑、待下线按钮，逐项对齐。
 *
 * **业务动作一律不在这里实现**：菜单项和单元格交互都调 `planBridge.<方法>`，
 * 由 `ui_qml/bridge/plan_table_bridge.py` 转给 `PlanTable`，
 * 保证迁移期只有一份业务逻辑。
 *
 * 字体：绑定一律写 `Math.round(N * Theme.fontScale)` 而不是 `Theme.fs(N)`——
 * 后者是 Slot 调用，QML 不追踪其内部的属性读取，改全局字号后不会重算。
 */
Item {
    id: root

    /* 生产计划桥，由 `PageHost` 以 context property `planTableBridge` 注入。
     *
     * **别名的名字不能与 context property 同名**：本文件里声明的同名属性会**遮蔽**
     * context property（QML 查找顺序是「自身属性 → context」），于是它恒为 null，
     * 表现为表格整片空白、**无任何报错**（实测踩过）。
     * 也不能写成 `required property var xxx`——required 属性**不接受**
     * context property 初始化，会直接报「Required property ... was not initialized」。
     *
     * 从阶段 2b 起本组件挂在 `IndustryPage.qml` 里，`planTableBridge` 由那一层的
     * 宿主注入，全树同名，故这里无需父级再显式绑定一次。
     */
    readonly property var planBridge: typeof planTableBridge !== "undefined" ? planTableBridge : null

    readonly property int fntTiny: Math.round(10 * Theme.fontScale)
    readonly property int fntSmall: Math.round(11 * Theme.fontScale)
    readonly property int fntBase: Math.round(12 * Theme.fontScale)
    readonly property int fntRow: Math.round(13 * Theme.fontScale)
    readonly property int rowH: Math.max(26, fntRow + 13)
    readonly property int headerH: Math.max(26, fntSmall + 15)

    // ── 列状态（可变副本，初值来自 planBridge.columns）──
    property var colMeta: []
    property var colWidths: []
    property var colVisible: []
    property bool colsReady: false
    // 产品列：宽度吃满剩余空间，不参与拖拽（对齐 Widgets 版的 Stretch）
    readonly property int productCol: 3
    readonly property int minProductWidth: 120
    // Phosphor 供应器要 `#rrggbb`；QML 的 `String(color)` 给的是 `#aarrggbb`
    readonly property string sortTint: encodeURIComponent(Theme.hex(Theme.primary))

    // ── 内联编辑 ──
    property int editRow: -1
    property int editCol: -1

    // ═══════════════════════════════════════════════════════════
    //  列宽 / 可见性
    // ═══════════════════════════════════════════════════════════

    function initColumns() {
        if (!planBridge)
            return
        const cols = planBridge.columns
        const meta = []
        const widths = []
        const visible = []
        for (let i = 0; i < cols.length; ++i) {
            meta.push(cols[i])
            widths.push(cols[i].width)
            visible.push(cols[i].visible)
        }
        // 用户手动调过的列宽优先；其余按实测内容自适应（QML 没有 resizeToContents）
        const fitted = planBridge.autofitWidths()
        for (let i = 0; i < fitted.length && i < widths.length; ++i) {
            if (fitted[i] > 0 && !planBridge.isColumnWidthUserSet(i))
                widths[i] = fitted[i]
        }
        colMeta = meta
        colWidths = widths
        colVisible = visible
        colsReady = true
        tableView.forceLayout()
    }

    // 产品列宽度 = 视口剩余空间（不小于 120px）
    function productWidth() {
        let used = 0
        for (let i = 0; i < colWidths.length; ++i) {
            if (i === productCol || !colVisible[i])
                continue
            used += colWidths[i]
        }
        return Math.max(minProductWidth, tableView.width - used)
    }

    function widthOf(col) {
        if (!colsReady)
            return 80
        if (!colVisible[col])
            return 0 // QML TableView 没有「隐藏列」，宽度 0 即隐藏
        if (col === productCol)
            return productWidth()
        return colWidths[col]
    }

    function setWidth(col, w) {
        if (!colsReady || col === productCol)
            return
        const meta = colMeta[col]
        const clamped = Math.max(meta.minWidth, meta.maxWidth > 0 ? Math.min(w, meta.maxWidth) : w)
        if (clamped === colWidths[col])
            return
        const next = colWidths.slice()
        next[col] = clamped
        colWidths = next
        tableView.forceLayout()
        if (planBridge)
            planBridge.setColumnWidth(col, clamped)
    }

    function setColumnVisible(col, visible) {
        if (!colsReady)
            return
        const next = colVisible.slice()
        next[col] = visible
        colVisible = next
        tableView.forceLayout()
        if (planBridge)
            planBridge.setColumnVisible(col, visible)
    }

    // ═══════════════════════════════════════════════════════════
    //  选中
    // ═══════════════════════════════════════════════════════════

    /* 菜单作用的行集：右键点中的行不在选中集里时只作用于它
     * （对齐 `QAbstractItemView` 的右键语义 —— 点在未选中行上等同「清空选中集并选中它」）。
     *
     * 选中集经 bridge 从 `TableView` **自己的** `QItemSelectionModel` 读出，
     * 既不在这里另存副本，也不去遍历 delegate 反查：遍历只看得见**当前已加载**的行，
     * 选中后滚出视野的行会被漏掉，批量操作于是静默退化成部分操作。 */
    function rowsForMenu(row) {
        const selected = root.planBridge ? root.planBridge.selectedRows() : []
        return selected.indexOf(row) >= 0 ? selected : [row]
    }

    // ═══════════════════════════════════════════════════════════
    //  菜单
    // ═══════════════════════════════════════════════════════════

    function openRowMenu(row, sceneX, sceneY) {
        rowMenu.state = planBridge ? planBridge.menuState(row) : ({})
        rowMenu.targetRow = row
        rowMenu.targetRows = rowMenu.state.synthetic ? [row] : rowsForMenu(row)
        rowMenu.x = sceneX
        rowMenu.y = sceneY
        rowMenu.open()
    }

    function openHeaderMenu(sceneX, sceneY) {
        headerMenu.x = sceneX
        headerMenu.y = sceneY
        headerMenu.open()
    }

    // ═══════════════════════════════════════════════════════════
    //  内联编辑
    // ═══════════════════════════════════════════════════════════

    function beginEdit(row, col, text) {
        editRow = row
        editCol = col
        inlineEditor.text = String(text || "")
        inlineEditor.visible = true
        inlineEditor.forceActiveFocus()
        inlineEditor.selectAll()
    }

    function commitEdit() {
        if (editRow < 0 || !planBridge) {
            cancelEdit()
            return
        }
        planBridge.commitEdit(editRow, editCol, inlineEditor.text)
        editRow = -1
        editCol = -1
        inlineEditor.visible = false
    }

    function cancelEdit() {
        editRow = -1
        editCol = -1
        inlineEditor.visible = false
    }

    // ═══════════════════════════════════════════════════════════
    //  底色
    // ═══════════════════════════════════════════════════════════

    /* 表格区底色。
     *
     * `TableView` 只画有行的部分，最后一行以下就是**空的**；不铺底色就会直接透出
     * 页面背景（`BG_DARK`）。暗色主题下它是 #0f172a，一整片看过去近似纯黑，
     * 与上面浅一档的行形成「表格消失在黑洞里」的观感（用户反馈「表格背景是黑的」）。
     * 铺成 surface 后表格是一块完整的浅面，行以下的留白与表格同色。 */
    Rectangle {
        anchors.fill: parent
        color: Theme.bgSurface
    }

    Component.onCompleted: initColumns()

    Connections {
        target: root.planBridge
        function onModelChanged() {
            root.cancelEdit()
            tableView.contentY = 0
            // 换模型后按新内容重量一次列宽（用户拖过的列由 bridge 保住）
            root.initColumns()
        }
        function onRowsReset() {
            // 同一个模型换了新数据（`set_plans`）—— 列宽要跟着内容走，
            // 否则首次加载时若模型还是空的，列宽会永远停在「只够放表头」的宽度上
            root.initColumns()
        }
        function onScrollRestoreRequested(y) {
            tableView.contentY = y
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
        model: root.planBridge ? root.planBridge.model : null

        /* 内建选中必须关掉，否则每次点击都会把 bridge 刚设好的选中集抹掉。
         *
         * Qt 6.11 的 `TableView` 内建点击选中**不工作**（最小 QML 复现，与 delegate
         * 有无 handler 无关）：不给 selectionModel 时它恒为 null，`selectionMode`
         * 设成 Single/Extended 也不会自建；自己塞一个进去再点击，`currentRow` 会更新
         * （说明按下确实到了 TableView），但选中集**只被清空、从不写入**。
         * 关掉它的开关是 `selectionBehavior: SelectionDisabled` ——
         * **没有** `selectionMode: TableView.NoSelection` 这个值
         * （该枚举只有 SingleSelection / ContiguousSelection / ExtendedSelection，
         *  写成 NoSelection 会得到 undefined，Qt 只记一条 assign 告警然后静默留原值）。 */
        selectionBehavior: TableView.SelectionDisabled
        // 选中模型由 Python 侧持有（模型换了会换一个，经 modelChanged 通知重绑）
        selectionModel: root.planBridge ? root.planBridge.selectionModel : null
        reuseItems: true
        // 行高随全局字号
        rowHeightProvider: function (row) { return root.rowH }
        columnWidthProvider: function (col) { return root.widthOf(col) }

        onContentYChanged: if (root.planBridge)
            root.planBridge.reportScroll(contentY)

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
            required property bool selected
            required property var model

            implicitWidth: root.widthOf(column)
            implicitHeight: root.rowH

            readonly property bool isReadyBtn: column === 7 && model.statusKey === "ready"
            readonly property bool isPlainText: column !== 0 && column !== 1 && column !== 2 && !isReadyBtn
            readonly property bool clickable: column === 0 || column === 10
                || (column === 3 && (model.foldState !== "" || model.isSynthetic)) || isReadyBtn
            // 选中行的前景必须用 textOnPrimary：选中底色是 PRIMARY，而它是**亮色**
            // （浅色主题 #1a237e 深蓝 / 暗色主题 #38bdf8 亮蓝）。用 textBright 会撞车 ——
            // 浅色主题下 textBright 是近黑色 #0d0f1f，压在深蓝底上等于看不见字。
            readonly property color fgColor: selected ? Theme.textOnPrimary : (model.fg || Theme.textPrimary)
            readonly property int iconSize: Math.round(16 * Theme.fontScale)
            readonly property int pad: Math.round(6 * Theme.fontScale)
            // Phosphor 供应器要 `#rrggbb`；QML 的 `String(color)` 给的是 `#aarrggbb`
            readonly property string iconTint: encodeURIComponent(Theme.hex(Theme.textPrimary))
            readonly property string checkTint: encodeURIComponent(Theme.hex(Theme.textOnPrimary))

            // 背景：斑马纹/选中打底，类别色以**半透明**叠在上面。
            // 不能直接拿类别色当底色 —— 100% 饱和会把文字吃掉
            // （见 PlanQmlModel._TINT_ALPHA 的说明）。
            Rectangle {
                anchors.fill: parent
                color: cell.selected ? Theme.primary : (cell.row % 2 === 1 ? Theme.bgSurface : Theme.bgDark)
            }
            Rectangle {
                anchors.fill: parent
                visible: !cell.selected && cell.model.bg !== ""
                color: cell.model.bg
            }

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: 1
                color: Theme.border
            }

            // ── 备料勾选（列 0）──
            Rectangle {
                visible: cell.column === 0
                anchors.centerIn: parent
                width: Math.round(15 * Theme.fontScale)
                height: width
                radius: 3
                color: cell.model.checked ? Theme.primary : "transparent"
                border.width: 1
                border.color: cell.model.checked ? Theme.primary : Theme.textSecondary

                Image {
                    anchors.centerIn: parent
                    width: Math.round(11 * Theme.fontScale)
                    height: width
                    visible: cell.model.checked
                    source: "image://phosphor/check?c=" + cell.checkTint + "&s=11"
                }
            }

            // ── 类别图标（列 1，居中）──
            Image {
                visible: cell.column === 1
                anchors.centerIn: parent
                width: cell.iconSize
                height: width
                source: cell.model.iconUrl
                sourceSize.width: width
                sourceSize.height: height
                smooth: true
            }

            // ── 物品图标（列 2）──
            Image {
                visible: cell.column === 2
                anchors.centerIn: parent
                width: Math.round(32 * Theme.fontScale)
                height: width
                source: cell.model.iconUrl
                sourceSize.width: width
                sourceSize.height: height
                smooth: true
                fillMode: Image.PreserveAspectFit
            }

            // ── 产品列（列 3）：折叠箭头 + 层级箭头 + 缩进文本 ──
            Image {
                id: foldCaret
                visible: cell.column === 3 && cell.model.foldState !== ""
                anchors.left: parent.left
                anchors.leftMargin: cell.pad + cell.model.indent * 12
                anchors.verticalCenter: parent.verticalCenter
                width: cell.iconSize
                height: width
                source: cell.model.foldState === "collapsed"
                        ? "image://phosphor/caret-right?c=" + cell.iconTint + "&s=16"
                        : "image://phosphor/caret-down?c=" + cell.iconTint + "&s=16"
                sourceSize.width: width
                sourceSize.height: height
            }

            Image {
                visible: cell.column === 3 && cell.model.indent > 0
                anchors.left: foldCaret.visible ? foldCaret.right : parent.left
                anchors.leftMargin: foldCaret.visible ? 2 : cell.pad
                anchors.verticalCenter: parent.verticalCenter
                width: cell.iconSize * 0.75
                height: width
                source: cell.model.iconUrl
                sourceSize.width: width
                sourceSize.height: height
            }

            // ── 通用文本 ──
            Text {
                visible: cell.isPlainText
                anchors.left: cell.column === 3 ? (foldCaret.visible ? foldCaret.right : parent.left) : parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: {
                    if (cell.column !== 3)
                        return cell.pad + Math.round(2 * Theme.fontScale)
                    let x = foldCaret.visible ? foldCaret.width + 2 : 0
                    x += cell.model.indent * 12
                    if (cell.model.indent > 0)
                        x += cell.iconSize * 0.75 + 2
                    return x + cell.pad
                }
                anchors.rightMargin: cell.pad
                text: cell.model.text
                // 对齐：勾选/类别/图标/组号/子级/状态居中，金额右对齐（对齐 Widgets 版的 delegate）
                horizontalAlignment: {
                    if (cell.column === 5 || cell.column === 6 || cell.column === 7 || cell.column === 9)
                        return Text.AlignHCenter
                    if (cell.column >= 12 && cell.column <= 18)
                        return Text.AlignRight
                    return Text.AlignLeft
                }
                elide: Text.ElideRight
                font.family: Theme.fontFamily
                // 全表统一用 fntBase：列宽由 bridge 按 **fs(12)** 实测（见
                // PlanTableBridge.autofitWidths），某列若用更大的字号，量出来的宽度
                // 就装不下它自己的文字，会稳定地被省略成「生产…」（实测踩过）。
                font.pixelSize: root.fntBase
                color: cell.fgColor
                verticalAlignment: Text.AlignVCenter
            }

            // ── 待下线按钮（列 7）──
            Rectangle {
                visible: cell.isReadyBtn
                anchors.centerIn: parent
                width: Math.max(56, parent.width - 12)
                height: Math.round(22 * Theme.fontScale)
                radius: Theme.radiusSmall
                color: readyHover.hovered ? Qt.lighter(Theme.accentOrange, 1.18) : Theme.accentOrange

                Text {
                    anchors.centerIn: parent
                    text: qsTr("待下线")
                    color: Theme.textOnPrimary
                    font.family: Theme.fontFamily
                    font.pixelSize: root.fntBase
                }

                HoverHandler {
                    id: readyHover
                }
            }

            // 悬停手型：可点击的单元格（含待下线按钮）
            HoverHandler {
                cursorShape: cell.clickable ? Qt.PointingHandCursor : Qt.ArrowCursor
            }
        }

        /* 点击命中由 `FTableClickArea` 统一负责，不在 delegate 里挂 TapHandler：
         * 后者在内容甩动/沉降时会整次丢掉点击（详见该组件的说明）。
         *
         * 单击**立即**派发（不为了等双击而拖延，实测延时会从 25ms 变成 431ms）；
         * 代价是双击会先跑一次单击，与旧实现「单/双击两个 TapHandler 都声明了」
         * 的语义一致。
         */
        FTableClickArea {
            objectName: "planClickArea"
            anchors.fill: parent
            rowHeight: root.rowH
            columnWidth: root.widthOf


            onRowClicked: function (row, column) {
                if (!root.planBridge)
                    return
                // 先落选中（Ctrl/Shift 的语义在 bridge 里判，QML 拿不到修饰键），
                // 再执行该单元格自己的动作（勾选/折叠/待下线…）。
                // 不再用 delegate 的 `clickable` 当门槛：Python 的 `_on_cell_clicked_by_pos`
                // 只在 0/10/3/7 有分支，且 col 3 自身还要满足「可折叠」才动 ——
                // 被 QML 排除的那些情形在 Python 里本来就是 no-op，判据留一份就够。
                root.planBridge.selectRow(row)
                root.planBridge.activate(row, column)
            }
            onRowDoubleClicked: function (row, column) {
                if (!root.planBridge)
                    return
                // 可编辑列就地编辑；其余列打开「编辑生产计划」对话框
                // （Widgets 版双击任何位置都开对话框，此处让内联编辑可达）
                if (root.planBridge.isCellEditable(row, column))
                    root.beginEdit(row, column, root.planBridge.cellText(row, column))
                else
                    root.planBridge.doubleClick(row)
            }
            onRowRightClicked: function (row, column, x, y) {
                if (!root.planBridge)
                    return
                const p = mapToItem(root, x, y)
                // 点在选中集外 → 先把选中换成这一行（对齐 QAbstractItemView），
                // 菜单作用的就是高亮着的那几行，所见即所得
                root.planBridge.ensureRowSelected(row)
                root.openRowMenu(row, p.x, p.y)
            }
        }
    }

    // ═══════════════════════════════════════════════════════════
    //  表头
    // ═══════════════════════════════════════════════════════════

    HorizontalHeaderView {
        id: headerView
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: root.headerH
        syncView: tableView
        clip: true

        /* 表头标题一律由下面的 delegate 自己从 `root.colMeta` 取，这个角色**没人读**；
         * 但仍必须指向一个**真实存在**的角色：`HorizontalHeaderView` 的默认值是
         * `"display"`，而 `PlanQmlModel.roleNames()` 里没有它，Qt 会为每个表头项
         * 刷一条「The 'textRole' property contains a role that doesn't exist」告警。 */
        textRole: "text"

        delegate: Item {
            id: hcell

            required property int index

            implicitHeight: root.headerH

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
                anchors.left: parent.left
                // 未排序时**不**为箭头留位：窄列（类别/图标）本来就只够放标题，
                // 恒定预留 16px 会把「类别」挤成「…」
                anchors.right: sortIcon.visible ? sortIcon.left : parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: Math.round(6 * Theme.fontScale)
                anchors.rightMargin: sortIcon.visible ? 2 : Math.round(6 * Theme.fontScale)
                text: root.colMeta.length > hcell.index ? root.colMeta[hcell.index].title : ""
                color: Theme.textPrimary
                elide: Text.ElideRight
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                font.family: Theme.fontFamily
                font.pixelSize: root.fntSmall
            }

            Image {
                id: sortIcon
                anchors.right: parent.right
                anchors.rightMargin: Math.round(6 * Theme.fontScale)
                anchors.verticalCenter: parent.verticalCenter
                width: Math.round(10 * Theme.fontScale)
                height: width
                visible: root.planBridge && root.planBridge.sortColumn === hcell.index
                source: (root.planBridge && root.planBridge.sortAscending)
                        ? "image://phosphor/caret-up?c=" + root.sortTint + "&s=10"
                        : "image://phosphor/caret-down?c=" + root.sortTint + "&s=10"
                sourceSize.width: width
                sourceSize.height: height
            }

            // 排序列高亮
            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: 2
                visible: root.planBridge && root.planBridge.sortColumn === hcell.index
                color: Theme.primary
            }

            HoverHandler {
                cursorShape: Qt.PointingHandCursor
            }

            /* 表头点击：桌面端只用鼠标，不需要 TapHandler 的手势语义。
             * **必须声明在下面那个调列宽的 `resizeHandle` 之前** —— 同层里后声明者在上，
             * 拖拽调宽才不会被本区域吃掉（原先的两个 TapHandler 也在同一位置）。 */
            MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.LeftButton | Qt.RightButton
                onClicked: function (mouse) {
                    if (!root.planBridge)
                        return
                    if (mouse.button === Qt.RightButton) {
                        const p = mapToItem(root, mouse.x, mouse.y)
                        root.openHeaderMenu(p.x, p.y)
                    } else {
                        root.planBridge.sortBy(hcell.index)
                    }
                }
            }

            // 右缘拖拽调列宽（产品列是 Stretch，不给拖）
            Item {
                id: resizeHandle
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                width: Math.round(6 * Theme.fontScale)
                visible: root.colMeta.length > hcell.index && !root.colMeta[hcell.index].product

                HoverHandler {
                    cursorShape: Qt.SplitHCursor
                }

                DragHandler {
                    target: null
                    onActiveChanged: if (active)
                        hcell.startWidth = root.widthOf(hcell.index)
                    onTranslationChanged: if (active)
                        root.setWidth(hcell.index, hcell.startWidth + translation.x)
                }
            }

            property real startWidth: 0
        }
    }

    // ═══════════════════════════════════════════════════════════
    //  内联编辑框
    // ═══════════════════════════════════════════════════════════

    FTextField {
        id: inlineEditor
        objectName: "inlineEditor"
        visible: false
        z: 10
        x: {
            let px = 0
            for (let i = 0; i < root.editCol; ++i)
                px += root.widthOf(i)
            return px - tableView.contentX
        }
        y: root.editRow * root.rowH - tableView.contentY + headerView.height
        width: root.editCol >= 0 ? root.widthOf(root.editCol) : 0
        height: root.rowH
        font.pixelSize: root.fntBase
        horizontalAlignment: TextInput.AlignLeft
        clip: true
        onAccepted: root.commitEdit()
        Keys.onEscapePressed: root.cancelEdit()
        onActiveFocusChanged: if (!activeFocus && visible)
            root.commitEdit()
    }

    // ═══════════════════════════════════════════════════════════
    //  行右键菜单
    // ═══════════════════════════════════════════════════════════

    /* 行右键菜单 —— 按用途分五组，分隔线即组边界：
     *   计划编辑 → 备料与状态 → 智能调整 → 查看 → 删除产线
     *
     * 分组原则：改这条产线本身的（字段/蓝图/备注）在前，改生产状态的（备料/启动/下线）
     * 其次，批量重排子项的（智能调整）单独成组，只读的（核算/复制）再次，
     * 破坏性的「删除产线」单独压到最后。
     *
     * 这里**没有**「设置蓝图等级」「查看蓝图原图的 NPC 卖家」「产线启动小助手」三项：
     * 蓝图等级统一由库存蓝图带出来（等级不再是计划上的可编辑字段），NPC 卖家仍在
     * 蓝图选择弹窗里，小助手在工业页底部状态栏已有按钮。
     *
     * 分隔线一律 `visible: rowMenu.plain`：`FMenuSeparator` 只把**自己**不可见时压成
     * 0 高，不会因为邻近条目隐藏就跟着收 —— 但每一组里至少有一条对普通行恒可见的
     * 条目（编辑/备料/核算/删除），所以组的开关恒等于 `plain`，不需要额外条件。
     * 只有「共享组件合成根」那一支要连分隔线一起关掉（即 `plain` 为假时整条菜单只剩
     * 折叠一项，末尾不能吊着一条分隔线）。 */
    FMenu {
        id: rowMenu
        objectName: "rowMenu"
        property int targetRow: -1
        property var targetRows: []
        property var state: ({})

        //: 普通计划行（非共享组件合成根）。下面所有 `visible` 都以它为准。
        readonly property bool plain: !state.synthetic

        // 共享组件合成根：只有折叠一项
        FMenuItem {
            text: qsTr("展开/折叠共享组件")
            visible: rowMenu.state.synthetic === true
            onTriggered: root.planBridge.toggleSharedCollapse()
        }
        FMenuSeparator { visible: rowMenu.plain }

        // ── 计划编辑 ────────────────────────────────────────────
        FMenuItem {
            text: qsTr("编辑生产计划")
            visible: rowMenu.plain
            onTriggered: root.planBridge.editPlans(rowMenu.targetRows)
        }
        FMenuItem {
            text: qsTr("绑定库存蓝图...")
            visible: rowMenu.plain
            onTriggered: root.planBridge.bindBlueprint(rowMenu.targetRow)
        }
        FMenuItem {
            text: qsTr("添加备注")
            visible: rowMenu.plain
            onTriggered: root.planBridge.addNotes(rowMenu.targetRow)
        }
        FMenuSeparator { visible: rowMenu.plain }

        // ── 备料与状态 ──────────────────────────────────────────
        // 备料勾选对本行恒可见；下面四项按状态**互斥**显示（同组只亮一个）。
        // 四项都要带 `plain`：共享组件合成根不是真计划行，它的 `status` 也会命中
        // 「pending」这些分支，只判状态就会在合成根的菜单里冒出「项目启动」。
        FMenuItem {
            text: rowMenu.state.materialsReady ? qsTr("取消勾选备料") : qsTr("勾选备料")
            visible: rowMenu.plain
            onTriggered: root.planBridge.setMaterialsReady(rowMenu.targetRows, rowMenu.state.materialsReady ? 0 : 1)
        }
        FMenuItem {
            text: qsTr("项目启动")
            visible: rowMenu.plain && rowMenu.state.status === "pending"
            onTriggered: root.planBridge.startPlans(rowMenu.targetRows)
        }
        FMenuItem {
            text: qsTr("撤销启动（返还材料）")
            visible: rowMenu.plain && (rowMenu.state.status === "in_progress" || rowMenu.state.status === "running")
            onTriggered: root.planBridge.undoStartPlans(rowMenu.targetRows)
        }
        FMenuItem {
            text: qsTr("下线")
            visible: rowMenu.plain && rowMenu.state.status === "ready"
            onTriggered: root.planBridge.completePlans(rowMenu.targetRows)
        }
        FMenuItem {
            text: qsTr("设为待生产（复用）")
            visible: rowMenu.plain && (rowMenu.state.status === "completed" || rowMenu.state.status === "done")
            onTriggered: root.planBridge.resetForReusePlans(rowMenu.targetRows)
        }
        FMenuSeparator { visible: rowMenu.plain }

        /* ── 智能调整 ──────────────────────────────────────────
         *
         * 「智能调整」子菜单。
         *
         * **不要给它写 `visible:`**。`Menu` 是 `Popup`，而 `Popup.visible = true` 就是
         * 「打开它」：原先那行 `visible: !rowMenu.state.synthetic` 在每次右键（`state`
         * 被赋值）时重算成 true，Qt 顺手把子菜单弹出来，随后的逻辑再把它收回去 ——
         * 用户看到的正是「二级菜单闪一下然后关闭」。而且实测那行**根本没起到隐藏作用**
         * （嵌套菜单的 visible 由 Qt 托管，恒为 false），纯是害处。
         *
         * 要隐藏条目只能用 `enabled`（置灰），`Popup.visible` 这条路走不通。
         * 也**不要**再加 `onOpened: smartMenu.close()` 那种「开完立刻收」的兜底：
         * 那只是把「不该开」变成「闪一下」，症状还在。
         */
        FMenu {
            id: smartMenu
            objectName: "smartMenu"
            title: qsTr("智能调整")
            enabled: rowMenu.plain
            FMenuItem {
                text: qsTr("母项调整（递归拆解）")
                onTriggered: root.planBridge.decomposeParent(rowMenu.targetRows)
            }
            FMenuItem {
                text: qsTr("子项调整（并行配置）")
                onTriggered: root.planBridge.adjustChildren(rowMenu.targetRows)
            }
            FMenuItem {
                text: qsTr("子项大规模产线并行")
                onTriggered: root.planBridge.massParallel(rowMenu.targetRows)
            }
            FMenuItem {
                text: qsTr("重算子项（按母项当前需求）")
                onTriggered: root.planBridge.recalcChildren(rowMenu.targetRows)
            }
        }

        FMenuSeparator { visible: rowMenu.plain }

        // ── 查看 ────────────────────────────────────────────────
        FMenuItem {
            text: qsTr("查看核算")
            visible: rowMenu.plain
            onTriggered: root.planBridge.viewCostBreakdown(rowMenu.targetRow)
        }
        FMenuItem {
            text: qsTr("复制蓝图名称")
            visible: rowMenu.plain
            onTriggered: root.planBridge.copyBlueprintName(rowMenu.targetRow)
        }
        FMenuSeparator { visible: rowMenu.plain }

        // ── 删除 ────────────────────────────────────────────────
        // 破坏性操作单独压到最后。语义见 `plan_table._delete_rows`：
        // 删本行 + 连带子项 + 解除蓝图绑定，**不动库存材料**（不返还已扣材料）。
        FMenuItem {
            text: qsTr("删除产线")
            visible: rowMenu.plain
            onTriggered: root.planBridge.deletePlans(rowMenu.targetRows)
        }
    }

    // ═══════════════════════════════════════════════════════════
    //  表头右键菜单（列可见性）
    // ═══════════════════════════════════════════════════════════

    FMenu {
        id: headerMenu
        objectName: "headerMenu"

        Repeater {
            model: root.colMeta

            FMenuItem {
                required property int index
                required property var modelData
                text: modelData.title
                checkable: true
                checked: root.colVisible.length > index ? root.colVisible[index] : true
                onToggled: root.setColumnVisible(index, checked)
            }
        }
    }
}
