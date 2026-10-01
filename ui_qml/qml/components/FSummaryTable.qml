import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

/* 只读汇总表 —— 表头 + 数据行 + 可选行内按钮 + 空态。
 *
 * 从 `SummaryTableDialog.qml` 里抽出来：那四个汇总对话框（产出总表 / 人物占用 /
 * 材料总表 / 研究分析）与本次迁过来的三个残留对话框（合同详情 / NPC 卖家 / 星系搜索）
 * 形状完全一致 —— 一组等宽列、每格一个文本（可带颜色）、可选一个行内按钮。
 * 与其把同一套渲染写七遍，不如只留这一份；各对话框只管把数据接进来。
 *
 * 只画，不管数据来源，也不管对话框外壳（窗口行为在 `QmlDialog` 那一层）。
 *
 * 行以**单元格列表**给出（`[{text, color}]`）：颜色是「利润为正染绿 / 状态按语义染色 /
 * 有溢出标橙」这类规则算出来的，留在 Python 侧与 Widgets 版逐条对齐。
 *
 * 点击一律走 `FTableClickArea`（按**按下那一刻**的行号派发）—— 原因见该组件头部。
 */

Item {
    id: root

    //: 列定义 [{title, width}]；width = 0 表示吃满剩余空间
    property var columns: []
    //: 行 [{cells: [{text, color}]}]
    property var rows: []
    //: 最后一列渲染成按钮而不是文本
    property bool hasActionColumn: false
    //: 行内按钮文案
    property string actionText: qsTr("复制")
    //: 表头是否显示（极简列表可关掉）
    property bool headerVisible: true
    //: 统一行高；`FTableClickArea` 的命中依赖它恒定
    property real rowHeight: Math.round(24 * Theme.fontScale)
    //: 无数据时的提示文案
    property string emptyText: qsTr("没有数据")
    //: 当前选中行（-1 = 无）；调用方用 `selectRow` 改、读 `currentRow` 做高亮
    property int currentRow: -1
    //: 行是否可选中（选中态画高亮底）
    property bool selectable: false

    /* 多选选中的行号（升序）。默认空数组 = 没有任何行被选中 ——
     * 因此不碰多选的既有使用者行为一字未变（高亮判据里这一项恒不成立）。 */
    property var selectedRows: []
    //: Shift 连选的锚点（上一次「点中」的行）；-1 = 还没点过
    property int selAnchor: -1

    signal selectionChanged()

    //: 闭区间 [a, b] 的行号（Shift 连选用；与 `BlueprintPickerDialog.rangeRows` 同口径）
    function rangeRows(a, b) {
        const lo = Math.min(a, b)
        const hi = Math.max(a, b)
        const out = []
        for (let i = lo; i <= hi; ++i)
            out.push(i)
        return out
    }

    /* 行点击 → 维护选中集。语义逐条对齐 `BlueprintPickerDialog.qml:213-231`：
     *   普通 = 只选它 ｜ Ctrl = 切换该行 ｜ Shift = 从锚点连选到本行（替换选中集、锚点不动，
     *   于是连续 Shift 可以扩也可以缩）。
     * 修饰键只能从点击区拿（见 `FTableClickArea.lastModifiers`）。 */
    function handleRowClicked(row) {
        const mods = clickArea.lastModifiers
        if ((mods & Qt.ShiftModifier) && root.selAnchor >= 0) {
            root.selectedRows = root.rangeRows(root.selAnchor, row)
        } else if (mods & Qt.ControlModifier) {
            const next = root.selectedRows.slice()
            const at = next.indexOf(row)
            if (at >= 0)
                next.splice(at, 1)
            else
                next.push(row)
            next.sort(function (a, b) {
                return a - b
            })
            root.selectedRows = next
            root.selAnchor = row
        } else {
            root.selectedRows = [row]
            root.selAnchor = row
        }
        root.selectionChanged()
    }

    /* 可排序的列号列表（空 = 表头不可点，行为与加这个特性之前完全一样）。
     * 排序列在表头上带 ▲/▼；点击只**发信号**，排哪一份数据由调用方决定
     * （各表的数据源不同：有的是模型的 sort()，有的是桥里排一遍列表）。 */
    property var sortableColumns: []
    property int sortColumn: -1
    property bool sortAscending: true

    signal rowClicked(int row)
    //: 带上列号：有的表「双击 = 复制该格」，需要知道点的是哪一列
    signal rowDoubleClicked(int row, int column)
    signal rowRightClicked(int row)
    signal actionClicked(int row)
    signal sortRequested(int column)

    //: 单元格左右内边距合计（`colWidth` 与命中口径共用）
    readonly property int cellPadding: Math.round(12 * Theme.fontScale)

    //: 固定列宽合计；「吃满剩余空间」的列据此平分剩下的宽度
    readonly property int fixedWidth: {
        let total = 0
        const cols = root.columns
        for (let i = 0; i < cols.length; ++i) {
            if (cols[i].width > 0)
                total += cols[i].width + root.cellPadding
        }
        return total + root.cellPadding
    }

    function colWidth(col) {
        const cols = root.columns
        // ⚠️ 负数也要挡：`columns` 还没赋值时长度是 0，调用方算「最后一列」会得到 -1，
        // 而 `cols[-1]` 是 undefined —— 接着取 `.width` 就抛
        // 「Value is undefined and could not be converted to an object」。
        // 这条绑定会被反复重算（`columns` 一改就重算），在测试里表现为整档挂住。
        if (!cols || col < 0 || col >= cols.length)
            return 0
        if (cols[col].width > 0)
            return cols[col].width
        // 未指定宽度的列平分剩余空间
        let flexible = 0
        for (let i = 0; i < cols.length; ++i) {
            if (cols[i].width <= 0)
                flexible += 1
        }
        return flexible > 0 ? Math.max(80, (root.width - root.fixedWidth) / flexible) : 80
    }

    // ── 表头 ──
    Rectangle {
        id: header
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        visible: root.headerVisible
        implicitHeight: Math.round(26 * Theme.fontScale)
        color: Theme.bgSurfaceLight

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: Theme.spacingSm
            anchors.rightMargin: Theme.spacingSm
            spacing: 0

            Repeater {
                model: root.columns

                Item {
                    id: headCell
                    required property var modelData
                    required property int index

                    readonly property bool sortable: root.sortableColumns.indexOf(headCell.index) >= 0
                    readonly property bool isSorted: root.sortColumn === headCell.index

                    Layout.preferredWidth: root.colWidth(headCell.index)
                    Layout.fillHeight: true

                    Text {
                        anchors.fill: parent
                        verticalAlignment: Text.AlignVCenter
                        horizontalAlignment: Text.AlignHCenter
                        text: headCell.modelData.title
                              + (headCell.isSorted ? (root.sortAscending ? " ▲" : " ▼") : "")
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: Math.round(12 * Theme.fontScale)
                        elide: Text.ElideRight
                    }

                    MouseArea {
                        anchors.fill: parent
                        enabled: headCell.sortable
                        hoverEnabled: headCell.sortable
                        cursorShape: headCell.sortable ? Qt.PointingHandCursor : Qt.ArrowCursor
                        onClicked: root.sortRequested(headCell.index)
                    }
                }
            }
        }
    }

    // ── 数据行 ──
    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: root.headerVisible ? header.bottom : parent.top
        anchors.bottom: parent.bottom
        color: Theme.bgSurface
        radius: Theme.radius
        border.width: 1
        border.color: Theme.border

        ListView {
            id: rowList
            anchors.fill: parent
            anchors.margins: 1
            clip: true
            model: root.rows
            boundsBehavior: Flickable.StopAtBounds

            ScrollBar.vertical: ScrollBar {
                policy: ScrollBar.AsNeeded
            }

            delegate: Item {
                id: rowItem
                required property var modelData
                required property int index

                width: rowList.width
                implicitHeight: root.rowHeight

                Rectangle {
                    anchors.fill: parent
                    // 多选高亮（`selectedRows`）与单选高亮（`currentRow`，需 `selectable`）并存：
                    // 母项拆解弹窗走前者，其余老使用者走后者，默认空选中集不改变任何旧行为。
                    color: (root.selectable && root.currentRow === rowItem.index)
                           || root.selectedRows.indexOf(rowItem.index) >= 0 ? Theme.primary
                           : (rowItem.index % 2 === 0 ? Theme.bgSurface : Theme.bgDark)
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
                            readonly property bool showAction: root.hasActionColumn
                                                              && index === rowItem.modelData.cells.length - 1

                            Layout.preferredWidth: root.colWidth(index)
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
                                text: root.actionText
                                onClicked: root.actionClicked(rowItem.index)
                            }
                        }
                    }
                }
            }
        }

        /* 行点击命中固定在按下那一刻（见 FTableClickArea 的说明）。
         *
         * 这里是**覆盖式**用法：点击区是 ListView 的兄弟节点（靠声明顺序压在内容之上），
         * 不是它的内联子项 —— 挤进 contentData 会和 delegate 抢层叠顺序，还可能吞掉
         * 行内「操作」按钮的点击。代价是父链里找不到表，所以必须显式把 `owner` 指过去，
         * 否则滚过之后按 y 算出的行号会少算「已经滚过去的行数」。 */
        FTableClickArea {
            id: clickArea
            objectName: "summaryClickArea"
            anchors.fill: parent
            /* ⚠️ 有行内动作列时**必须让出那一列**：本组件锚 `fill` 且是 `rowList` 之后
             * 声明的兄弟节点（靠声明顺序压在内容之上），会吃掉行内动作按钮的全部点击 ——
             * 点击落到 `rowClicked`，而调用方接的是 `actionClicked`，于是「点了没反应」。
             * 实测受害的是母项递归拆解弹窗的「移除」与材料总表的「复制采购」。
             *
             * 同型缺陷与修法见 `LauncherWindow.qml:518-538`（那里让的是 `actionZoneW`）。
             * ⚠️ 不要改用 `z: -1`：`LauncherWindow.qml:526-528` 实测在本仓无效 ——
             * ListView（Flickable）会自己吃掉空白区的点击，整行都点不动。
             *
             * 已知取舍（与 LauncherWindow 一致，有意为之）：动作列那一段不再参与
             * 整行点击 / 双击 / 右键 —— 那里现在是真的按钮，点击该由它接管。 */
            anchors.rightMargin: root.hasActionColumn && root.columns.length > 0
                                 ? root.colWidth(root.columns.length - 1) + root.cellPadding
                                 : 0
            owner: rowList
            rowHeight: root.rowHeight
            columnWidth: root.colWidth

            onRowClicked: function (row, _column) {
                root.handleRowClicked(row)
                root.rowClicked(row)
            }
            onRowDoubleClicked: function (row, column) {
                root.rowDoubleClicked(row, column)
            }
            onRowRightClicked: function (row, _column, _x, _y) {
                root.rowRightClicked(row)
            }
        }

        // 空态
        Text {
            anchors.centerIn: parent
            visible: root.rows.length === 0
            text: root.emptyText
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }
    }
}
