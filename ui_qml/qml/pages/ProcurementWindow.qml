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
     */
    width: 760
    height: 820
    minimumWidth: 620
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
    //: 七列全部可排序（对齐原 `SortPreservingTableView` 的表头）
    readonly property var allColumns: [0, 1, 2, 3, 4, 5, 6]
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

        // ── 工具栏 ──
        RowLayout {
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
                Layout.preferredWidth: Math.round(110 * Theme.fontScale)
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
                Layout.preferredWidth: Math.round(140 * Theme.fontScale)
                textRole: "label"
                model: page.pc ? page.pc.hubOptions : []
                currentIndex: page.pc ? page.pc.hubIndex : 0
                onActivated: if (page.pc)
                    page.pc.setHubIndex(currentIndex)
            }

            Item {
                Layout.fillWidth: true
            }

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
                objectName: "completeAllButton"
                visible: page.pc ? page.pc.completeAllVisible : false
                text: page.pc ? page.pc.completeAllText : ""
                primary: true
                onClicked: if (page.pc)
                    page.pc.completeAll()
            }

            FCheckBox {
                objectName: "pinBox"
                text: qsTr("置顶")
                checked: page.pc ? page.pc.pinned : false
                onToggled: if (page.pc)
                    page.pc.setPinned(checked)
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
