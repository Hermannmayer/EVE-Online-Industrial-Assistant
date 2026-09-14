import QtQuick

/* 表格点击区 —— 把「点到了哪一行」固定在**按下那一刻**。
 *
 * 为什么不能在 delegate 里放 TapHandler：`TableView` 是 Flickable，甩动/惯性沉降
 * 期间内容会移动，而 `TapHandler`（配 `ReleaseWithinBounds`）是在**释放**时做命中
 * 判定——此时按下时那个 delegate 已经移开，于是该次点击被整个丢掉。
 * 实测：按住不动、让内容移动 1 行再释放，选中集为空；内容不动则正常。
 * 真实使用中「滚一下马上点」必踩。
 *
 * 这里改为：按下时按位置算出 (row, column) 并记住，释放时用**按下时**算出的行列
 * 派发，与内容此后是否移动无关。
 *
 * **坐标约定（踩过坑）**：本组件必须声明在 `TableView` 的**内联子项**位置——
 * Flickable 的内联子项进的是它的 `contentData`，于是事件位置是**内容坐标**
 * （= 视口坐标 + contentY），不是视口坐标。所以这里**不再叠加 contentY**：
 * 早先按视口坐标算（又加了一次 contentY），在小位移时看不出问题，
 * 位移一大行号就翻倍（实测 contentY=1000 时第 35 行被算成第 71 行）。
 * 保持声明在 TableView 内还有个好处：滚动条是 TableView 自己的子项，
 * 仍画在内容之上、照常可拖，不会被本组件盖住。
 *
 * 前提：行高必须是常量（各表都用 `rowHeightProvider` 返回固定 rowH）；列宽由
 * 调用方给函数（各表的列宽算法不同，隐藏列返回 0 即跳过）。
 *
 * 用法：
 *     TableView {
 *         id: t
 *         rowHeightProvider: function (row) { return page.rowH }
 *
 *         FTableClickArea {
 *             anchors.fill: parent
 *             rowHeight: page.rowH
 *             columnWidth: page.itemColWidth
 *             rowCount: page.inv.itemCount
 *             onRowClicked: (row, col) => ...
 *             onRowRightClicked: (row, col, x, y) => ...
 *         }
 *     }
 */

MouseArea {
    id: root

    //: 列宽函数 function(col) -> real；返回 0 的列被跳过（隐藏列）
    required property var columnWidth
    required property int rowHeight

    //: 行数上限（超出视为空白区不派发）；≤0 表示不限制
    property int rowCount: 0

    signal rowClicked(int row, int column)
    signal rowRightClicked(int row, int column, real x, real y)

    acceptedButtons: Qt.LeftButton | Qt.RightButton

    //: 按下时解析出的命中（-1 = 落在空白区）
    property int pressRow: -1
    property int pressColumn: -1
    //: 诊断用：按下时的原始位置（内容坐标）
    property real pressY: -1

    readonly property int _maxColumns: 64

    function rowAt(y: real): int {
        if (root.rowHeight <= 0)
            return -1
        return Math.floor(y / root.rowHeight)
    }

    function columnAt(x: real): int {
        let acc = 0
        for (let col = 0; col < root._maxColumns; ++col) {
            const w = root.columnWidth(col)
            if (w <= 0)
                continue
            if (x < acc + w)
                return col
            acc += w
        }
        return -1
    }

    onPressed: function (mouse) {
        root.pressY = mouse.y
        root.pressRow = root.rowAt(mouse.y)
        root.pressColumn = root.columnAt(mouse.x)
    }

    // 拖动超过阈值时 MouseArea 收到 canceled（Flickable 抢走手势），不会走到这里——
    // 所以「拖 = 滚动」「点 = 选中」两不误。
    onClicked: function (mouse) {
        if (root.pressRow < 0 || root.pressColumn < 0)
            return
        if (root.rowCount > 0 && root.pressRow >= root.rowCount)
            return
        if (mouse.button === Qt.RightButton)
            root.rowRightClicked(root.pressRow, root.pressColumn, mouse.x, mouse.y)
        else
            root.rowClicked(root.pressRow, root.pressColumn)
    }
}
