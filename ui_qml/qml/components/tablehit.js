.pragma library

/* 表格命中数学 —— 点击位置 → (行, 列)。
 *
 * 抽出来是因为有**两种调用机制、两套坐标系**，但算法必须只有一份：
 *
 *   1. `FTableClickArea`（MouseArea，声明在 TableView 的**内联子项**位置）
 *      —— Flickable 的内联子项进 `contentData`，事件位置已是**内容坐标**，
 *         所以传 contentY = 0 / contentX = 0。
 *   2. `TapHandler`（声明在 TableView 上，handler 不是 Item，挂到 TableView 本身）
 *      —— 位置是**视口坐标**，要传真实的 `view.contentY` / `view.contentX`。
 *
 * 前提：行高常量（各表都用 `rowHeightProvider` 返回固定 rowH）。
 */

/** 视口/内容 y → 行号；越界不在这里判（调用方用 rowCount 判空白区）。 */
function rowAt(y, contentY, rowHeight) {
    if (rowHeight <= 0)
        return -1;
    return Math.floor((y + contentY) / rowHeight);
}

/** x → 列号：按列宽累加；返回 0 的列视为隐藏列并跳过；全都不命中返回 -1。 */
function columnAt(x, contentX, columnWidth) {
    let acc = 0;
    const cx = x + contentX;
    for (let col = 0; col < 64; ++col) {
        const w = columnWidth(col);
        if (w <= 0)
            continue;
        if (cx < acc + w)
            return col;
        acc += w;
    }
    return -1;
}
