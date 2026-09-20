import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import "../components"

/* 采购小助手窗口（阶段 4b）—— 非模态工具窗，渲染整体在 QML。
 *
 * 两个分区（需采购 / 库存已备足）放在可拖动的 `SplitView` 里，各自带可排序表头
 * —— 与 Widgets 版的 `QSplitter` + 两个 `SortPreservingTableView` 对齐。
 *
 * 业务全在 `ProcurementDialog`（控制器）里，这里只画与转发。
 *
 * 批次 7.4：根元素从 `Item` 换成 **`Window`** —— 控制器退成 `QObject`，不再有
 * `QDialog` 外壳，窗口语义（标题 / 尺寸 / 顶层 / 关闭 / Esc / 显示隐藏事件）由这里自持；
 * 命令式的那几项（show / raise / activate / resize）仍由控制器转发。
 */
Window {
    id: page

    /* ── 窗口语义（逐项对齐原 QDialog 版 `ProcurementDialog`）──
     *
     *   setWindowTitle(f"待采购 - 材料需求 ({机库})") → title 绑定桥的 titleText
     *   setWindowFlag(Qt.Window, True)               → 顶层 Window 默认即带 Qt.Window；
     *                                                  构造时不给 transientParent，所以仍
     *                                                  然「不随主窗最小化」（原 parent=None）
     *   setMinimumSize(620, 400)                     → minimumWidth / minimumHeight
     *   resize(760, 820)                             → width / height（窄高，一眼看全）
     *   show() / raise_() / activateWindow() / done()/Esc → 控制器转发 + 下面的 Shortcut
     *
     * ⚠️ **这个窗口是置顶用的**（往游戏里照着录单），所以宽度按「内容真正需要的
     * 最小宽」定，不按好看的宽定：`minimumWidth` = 内容最小宽，`width` 开局就等于
     * `minimumWidth`。窗口比内容窄就会把最右边的控件切掉（用户报过两次
     * 「首次打开显示不全」）。
     *
     * 宽度预算（改动下面任何一行都要重量）：
     *   - 工具栏第一行（两个下拉 + 置顶）≈ 367px，**比表格窄**，所以它不再是下限
     *   - 工具栏第二行是 `Flow`，**会自动折行** —— 加按钮只多占一行高度，不会顶宽
     *   - **下限由表格定**：4 个固定列的像素宽之和（416，与 `procurement_bridge._COLUMNS`
     *     同源）+ 每列 `FSummaryTable.cellPadding`（随字体缩放）+ 名称列下限 80 + 左右边距 16
     *
     * 所以最小值写成**算式**而不是一个数：固定列宽是绝对像素，cellPadding 却随
     * `Theme.fontScale` 变 —— 写死数字的话，用户把字体调大后右侧列又会被裁掉。
     * `tests/test_procurement_tab.py::test_narrowest_window_clips_nothing` 按渲染结果
     * 兜这条（改了列宽/边距忘了改这里就会红）。
     */
    readonly property int contentMinWidth: 416 + Math.round(12 * Theme.fontScale) * 5 + 80 + 16
    width: page.contentMinWidth
    height: 820
    minimumWidth: page.contentMinWidth
    minimumHeight: 400
    title: page.pc ? page.pc.titleText : ""
    // 窗口清屏色 = 页面底色：首帧之前也不会闪一下白底
    color: Theme.bgDark
    visible: false // 由 Python 侧的 `show()` 打开（构造完不该自己冒出来）

    /* 显示 / 隐藏 —— 等价于原 `showEvent` / `hideEvent`。
     * ⚠️ 原 `showEvent` 里除了起轮询表，还有一次 `_reload_plans()`（不复用就会看到
     * 过期数据）—— 两条都搬到了控制器同名方法里，这里只负责把可见性转过去。 */
    onVisibleChanged: if (page.pc)
        page.pc.windowVisibilityChanged(page.visible)

    /* ⚠️ QML 的 `Window.onClosing` 是**可取消**的：一旦挂上处理函数，
     * 就必须显式 `close.accepted = true`，否则关闭事件被静默吃掉、窗口关不掉。 */
    onClosing: function (close) {
        if (page.pc)
            page.pc.windowClosing()
        close.accepted = true
    }

    /* Esc —— 原 `QDialog` 的内置行为（`reject()`，不经 `closeEvent`）。
     * QML 的 `Window` 没有内置 Esc 语义，这里补一条。
     * ⚠️ 用字面量 `"Escape"` 而不是 `StandardKey.Cancel`：后者是**多绑定**的标准键，
     * `sequence:` 只绑其中一条，Qt 会在每次加载时刷一行告警（测试的「零告警」护栏会红）。 */
    Shortcut {
        sequence: "Escape"
        onActivated: if (page.pc)
            page.pc.escapePressed()
    }

    readonly property var pc: typeof bridge !== "undefined" ? bridge : null
    //: 全部列都可排序（对齐原 `SortPreservingTableView` 的表头）。
    //: **从 `columns` 长度推，不要写死下标数组** —— 写死的话加列时新列的表头点不动，
    //: 而且不会报错（只是点了没反应）。
    readonly property var allColumns: page.pc ? page.pc.columns.map(function (c, i) { return i; }) : []
    //: 两分区的取数口径一致，只有数据源与排序列不同 —— 抽成内联组件，避免抄两遍
    readonly property bool anyVisible: page.pc ? (page.pc.buyVisible || page.pc.stockVisible) : false

    component SectionPane: ColumnLayout {
        id: pane

        //: "buy" | "stock"
        required property string sectionKey
        required property string title
        required property var rows
        required property bool shown
        required property int sortCol
        required property bool sortAsc

        SplitView.fillHeight: true
        SplitView.minimumHeight: Math.round(90 * Theme.fontScale)
        visible: pane.shown
        spacing: Theme.spacingXs

        Text {
            Layout.fillWidth: true
            text: pane.title
            color: pane.sectionKey === "buy" ? Theme.accentRed : Theme.accentGreen
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
            font.weight: Font.DemiBold
        }

        FSummaryTable {
            objectName: "table_" + pane.sectionKey
            Layout.fillWidth: true
            Layout.fillHeight: true
            columns: page.pc ? page.pc.columns : []
            rows: pane.rows
            sortableColumns: page.allColumns
            sortColumn: pane.sortCol
            sortAscending: pane.sortAsc
            onSortRequested: function (column) {
                if (page.pc)
                    page.pc.sortSection(pane.sectionKey, column);
            }
            onRowDoubleClicked: function (row, column) {
                if (page.pc)
                    page.pc.copyCell(pane.sectionKey, row, column);
            }
            onRowRightClicked: function (row) {
                rowMenu.sectionKey = pane.sectionKey;
                rowMenu.row = row;
                rowMenu.popupSoon();
            }
        }
    }

    Rectangle {
        anchors.fill: parent
        color: Theme.bgDark
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.spacingSm
        spacing: Theme.spacingSm

        // ── 工具栏 · 第一行：两个下拉 + 置顶（这一行定窗口最小宽）──
        RowLayout {
            objectName: "toolbar"
            Layout.fillWidth: true
            spacing: Theme.spacingSm

            Text {
                text: qsTr("价格类型:")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(12 * Theme.fontScale)
            }

            FComboBox {
                objectName: "priceTypeBox"
                Layout.preferredWidth: Math.round(84 * Theme.fontScale)
                textRole: "label"
                model: page.pc ? page.pc.priceTypeOptions : []
                currentIndex: page.pc ? page.pc.priceTypeIndex : 0
                onActivated: if (page.pc)
                    page.pc.setPriceTypeIndex(currentIndex)
            }

            Text {
                text: qsTr("来源:")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(12 * Theme.fontScale)
            }

            FComboBox {
                objectName: "hubBox"
                Layout.preferredWidth: Math.round(92 * Theme.fontScale)
                textRole: "label"
                model: page.pc ? page.pc.hubOptions : []
                currentIndex: page.pc ? page.pc.hubIndex : 0
                onActivated: if (page.pc)
                    page.pc.setHubIndex(currentIndex)
            }

            Item {
                Layout.fillWidth: true
            }

            FCheckBox {
                objectName: "pinBox"
                text: qsTr("置顶")
                checked: page.pc ? page.pc.pinned : false
                onToggled: if (page.pc)
                    page.pc.setPinned(checked)
            }
        }

        // ── 工具栏 · 第二行：动作按钮（`Flow` 自动折行）──
        // ⚠️ **不要换回 RowLayout**：单行 RowLayout 的内容宽度会顶到窗口上（加一个
        // 按钮就把最右边的切掉，用户报过），Flow 则会换行，永不裁切。
        Flow {
            objectName: "actionBar"
            Layout.fillWidth: true
            spacing: Theme.spacingSm

            FButton {
                objectName: "refreshButton"
                text: qsTr("刷新计算")
                onClicked: if (page.pc)
                    page.pc.refresh()
            }

            FButton {
                text: qsTr("复制到剪贴板")
                onClicked: if (page.pc)
                    page.pc.copyAll()
            }

            FButton {
                text: qsTr("增量添加到仓库")
                onClicked: if (page.pc)
                    page.pc.addToHangar()
            }

            FButton {
                objectName: "importPurchasesButton"
                text: qsTr("从剪贴板导入")
                onClicked: if (page.pc)
                    page.pc.importPurchases()

                HoverHandler {
                    id: buyImportHover
                }
                ToolTip.visible: buyImportHover.hovered
                ToolTip.text: qsTr("在游戏「钱包 → 交易记录」里 Ctrl+A/C 复制后点这里：把负 ISK 的买入行按单价（成本）入到指定机库")
            }

            FButton {
                objectName: "completeAllButton"
                visible: page.pc ? page.pc.completeAllVisible : false
                text: page.pc ? page.pc.completeAllText : ""
                primary: true
                onClicked: if (page.pc)
                    page.pc.completeAll()
            }
        }

        // ── 两个分区（可拖动分隔）──
        SplitView {
            id: split
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: Qt.Vertical
            visible: page.anyVisible

            SectionPane {
                sectionKey: "buy"
                title: page.pc ? page.pc.buyLabel : ""
                rows: page.pc ? page.pc.buyRows : []
                shown: page.pc ? page.pc.buyVisible : false
                sortCol: page.pc ? page.pc.buySortColumn : -1
                sortAsc: page.pc ? page.pc.buySortAscending : true
            }

            SectionPane {
                sectionKey: "stock"
                title: page.pc ? page.pc.stockLabel : ""
                rows: page.pc ? page.pc.stockRows : []
                shown: page.pc ? page.pc.stockVisible : false
                sortCol: page.pc ? page.pc.stockSortColumn : -1
                sortAsc: page.pc ? page.pc.stockSortAscending : true
            }
        }

        // ── 空态 ──
        Text {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: !page.anyVisible
            text: page.pc ? page.pc.emptyText : ""
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(13 * Theme.fontScale)
        }

        // ── 底部：汇总 + 复制提示（复制后 5s 内显示）──
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingSm

            Text {
                Layout.fillWidth: true
                text: page.pc ? page.pc.summaryText : ""
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(12 * Theme.fontScale)
                elide: Text.ElideRight
            }

            Text {
                objectName: "copyHint"
                visible: page.pc ? page.pc.copyHint !== "" : false
                text: page.pc ? page.pc.copyHint : ""
                color: Theme.accentGreen
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(12 * Theme.fontScale)
                elide: Text.ElideRight
            }
        }
    }

    // ── 行右键菜单 ──
    FMenu {
        id: rowMenu
        objectName: "rowMenu"
        property string sectionKey: "buy"
        property int row: -1

        FMenuItem {
            text: qsTr("删除此行")
            onTriggered: if (page.pc)
                page.pc.deleteRow(rowMenu.sectionKey, rowMenu.row)
        }
        FMenuItem {
            text: qsTr("修改数量")
            onTriggered: if (page.pc)
                page.pc.editQty(rowMenu.sectionKey, rowMenu.row)
        }
        FMenuItem {
            text: qsTr("复制数量")
            onTriggered: if (page.pc)
                page.pc.copyQty(rowMenu.sectionKey, rowMenu.row)
        }
        FMenuSeparator {}

        FMenuItem {
            text: qsTr("复制此行")
            onTriggered: if (page.pc)
                page.pc.copyLine(rowMenu.sectionKey, rowMenu.row)
        }
    }
}
