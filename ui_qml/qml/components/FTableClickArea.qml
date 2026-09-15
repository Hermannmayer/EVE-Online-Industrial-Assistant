import QtQuick
import "tablehit.js" as TableHit

/* 表行点击区 —— 把「点到哪一行」固定在**按下那一刻**。
 *
 * 为什么不能在 delegate 里放 `TapHandler`：表（`TableView` / `ListView`）是 Flickable，
 * 甩动/惯性沉降期间内容会移动，而 `TapHandler`（配 `ReleaseWithinBounds`）是在**释放**
 * 时做命中判定——此时按下时那个 delegate 已经移开，于是该次点击被整个丢掉。
 * 实测：按住不动、让内容移动 1 行再释放，选中集为空；内容不动则正常。
 * 真实使用中「滚一下马上点」必踩，也就是用户说的「单击不到所对应的行上」。
 *
 * 本组件按位置算出 (行, 列) 并记住，释放时按**按下时**算出的值派发，与内容此后
 * 是否移动无关。
 *
 * **本项目只做桌面端（鼠标键盘），不用触摸手势**，所以一律用 `MouseArea` 而不是
 * `TapHandler`：没有手势竞技场（grab / steal）参与，内容移动不会取消点击。
 * 全项目的表行点击都走这一个组件，只有一处实现。
 *
 * **坐标不是「一种」，是两种 —— 取决于宿主是哪种表（踩过坑）**：
 *
 * | 宿主 | 内联子项挂到哪 | 事件坐标 | 要不要加 contentY |
 * |---|---|---|---|
 * | `TableView` | `contentItem`（随内容平移） | **内容坐标** | 不加 |
 * | `ListView` | 表本体（不随内容平移） | **视口坐标** | **要加** |
 *
 * 原先一律按内容坐标算（contentY 传 0）：`TableView` 是对的（早先小位移时看不出问题，
 * 位移一大行号才翻倍——实测 contentY=1000 时第 35 行被算成第 71 行）；
 * 但 `ListView` 上**只要滚过就点错行**（实测 contentY=200 时点视口 y=25 报第 1 行、
 * 应为第 11 行）。判据用「本组件是不是挂在宿主的 contentItem 下」，见 `_contentOffset`。
 *
 * 保持声明在表内还有个好处：滚动条是表自己的子项，仍画在内容之上、
 * 照常可拖，不会被本组件盖住。
 *
 * **行高必须统一**：`TableView` 用 `rowHeightProvider` 返回固定行高；`ListView` 的
 * delegate 高度固定时也适用（行间距另用 `rowSpacing` 传，见下）。
 *
 * 用法（`TableView`）：
 *     TableView {
 *         id: t
 *         rowHeightProvider: function (row) { return page.rowH }
 *
 *         FTableClickArea {
 *             anchors.fill: parent
 *             rowHeight: page.rowH
 *             columnWidth: page.colWidth          // 传 null = 整行一格
 *             onRowClicked: (row, col) => ...
 *             onRowRightClicked: (row, col, x, y) => ...
 *             onRowDoubleClicked: (row, col) => ...
 *         }
 *     }
 *
 * 用法（`ListView` 行卡片，整行一格且有间距）：
 *     ListView {
 *         id: l
 *         spacing: page.gap
 *
 *         FTableClickArea {
 *             anchors.fill: parent
 *             rowHeight: page.cardHeight
 *             rowSpacing: l.spacing
 *             columnWidth: null
 *             onRowClicked: (row, col) => ...
 *         }
 *     }
 */

MouseArea {
    id: root

    //: 单行高度；行起点之间的间距 = `rowHeight` + `rowSpacing`
    required property real rowHeight
    //: 行间距（对齐 `ListView.spacing`；`TableView` 恒为 0）
    property real rowSpacing: 0

    /* 列宽函数 function(col) -> real；返回 0 的列被跳过（隐藏列）。
     * 传 null 表示「整行就是一格」（ListView 行卡片），列号恒为 0。 */
    property var columnWidth: null

    //: 行数上限（超出视为空白区不派发）。默认自动取所属表的行数，一般不必传。
    property int rowCountOverride: -1

    /* 它盖在哪张表上。默认沿父链自己找，**覆盖式用法必须显式传**。
     *
     * 覆盖式（把点击区当兄弟节点盖在表上、靠声明顺序压在内容之上）时父链里没有表 ——
     * `FSummaryTable` 就是这么用的：它要盖住 ListView 但不能挤进 delegate 的层叠顺序里。
     * 不传的话找不到表，行数上限失效、`contentY` 也补不上，滚过就点错行。
     */
    property var owner: null

    //: 单击**立即派发**，不为了等双击而拖延。
    //:
    //: 实测过「按住等双击间隔再派发单击」的版本：主表单击→选中从 25ms 变成 431ms，
    //: 肉眼就是卡。旧实现（`TapHandler` 同时挂单/双击）实测单击也是 25ms ——
    //: Qt 并不为双击延迟 `singleTapped`。所以双击的代价就是单击也会执行一次，
    //: 与旧实现「两个 handler 都声明了」的语义一致。
    signal rowClicked(int row, int column)
    signal rowRightClicked(int row, int column, real x, real y)
    signal rowDoubleClicked(int row, int column)

    acceptedButtons: Qt.LeftButton | Qt.RightButton

    //: 按下时解析出的命中（-1 = 落在空白区）
    property int pressRow: -1
    property int pressColumn: -1
    //: 诊断用：按下时的原始位置（内容坐标）
    property real pressY: -1

    /* 所属的表 —— 显式传了就用它，否则沿父链找。
     * 行数上限直接取它的 `rows`（TableView）/ `count`（ListView），
     * 调用方不必再为了「最后一行以下算空白」多传一个参数。 */
    readonly property var ownerList: {
        if (root.owner !== null)
            return root.owner
        let node = root.parent
        while (node !== null) {
            if (typeof node.rowHeightProvider === "function" || typeof node.count === "number")
                return node
            node = node.parent
        }
        return null
    }

    readonly property int effectiveRowCount: {
        if (root.rowCountOverride >= 0)
            return root.rowCountOverride
        const owner = root.ownerList
        if (owner === null)
            return 0
        if (typeof owner.rows === "number")
            return owner.rows
        return typeof owner.count === "number" ? owner.count : 0
    }

    readonly property real rowStride: root.rowHeight + root.rowSpacing

    //: 本组件是不是挂在宿主的 `contentItem` 底下（`TableView` 是，`ListView` 不是）
    function _underContentItem(item, content) {
        let node = item
        while (node !== null) {
            if (node === content)
                return true
            node = node.parent
        }
        return false
    }

    /* 事件坐标要补的偏移量。
     *
     * 挂在 `contentItem` 下（`TableView`）：坐标已随内容平移过，补 0。
     * 挂在表本体上（`ListView`）：坐标是视口的，要加上当前 contentY / contentX，
     * 否则滚过之后按 y 算出的行号会少算「已经滚过去的行数」。
     */
    readonly property real contentOffsetY: {
        const owner = root.ownerList
        if (owner === null)
            return 0
        const content = owner.contentItem
        return content !== null && root._underContentItem(root.parent, content) ? 0 : owner.contentY
    }

    readonly property real contentOffsetX: {
        const owner = root.ownerList
        if (owner === null)
            return 0
        const content = owner.contentItem
        return content !== null && root._underContentItem(root.parent, content) ? 0 : owner.contentX
    }

    function rowAt(y: real): int {
        return TableHit.rowAt(y, root.contentOffsetY, root.rowStride)
    }

    function columnAt(x: real): int {
        if (root.columnWidth === null)
            return 0
        return TableHit.columnAt(x, root.contentOffsetX, root.columnWidth)
    }

    function _inRange(row: int, column: int): bool {
        if (row < 0 || column < 0)
            return false
        return !(root.effectiveRowCount > 0 && row >= root.effectiveRowCount)
    }

    onPressed: function (mouse) {
        root.pressY = mouse.y
        root.pressRow = root.rowAt(mouse.y)
        root.pressColumn = root.columnAt(mouse.x)
    }

    // 拖动超过阈值时 MouseArea 收到 canceled（Flickable 抢走手势），不会走到这里——
    // 所以「拖 = 滚动」「点 = 选中」两不误。
    onClicked: function (mouse) {
        if (!root._inRange(root.pressRow, root.pressColumn))
            return
        if (mouse.button === Qt.RightButton) {
            root.rowRightClicked(root.pressRow, root.pressColumn, mouse.x, mouse.y)
            return
        }
        root.rowClicked(root.pressRow, root.pressColumn)
    }

    /* 双击：用**按下时**的行列（`mouse` 的位置在内容移动后可能已指向别的行）。
     * Qt 对双击**不发**第一次的 `clicked`，所以双击只跑双击这一次动作。 */
    onDoubleClicked: function (mouse) {
        if (!root._inRange(root.pressRow, root.pressColumn))
            return
        root.rowDoubleClicked(root.pressRow, root.pressColumn)
    }
}
