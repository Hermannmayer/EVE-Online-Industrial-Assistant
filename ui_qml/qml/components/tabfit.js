/* TabBar 的宽度陷阱 —— 唯一推荐用法见 `components/FTabBar.qml`。
 *
 * Qt 的 `TabBar` **把可用宽度等分给每个按钮**，不看各自的 `implicitWidth`：
 * 实测给三个按钮分别写 110 / 70 / 95，实得 92 / 92 / 92。
 * 更麻烦的是 `TabBar.implicitWidth` 又是由这些**已经被挤窄**的按钮反推的，
 * 于是「父布局取它的 implicitWidth → 它再等分 → 反推更小的 implicitWidth」会锁死在
 * 一个放不下最长标签的宽度上（`SettingsDialog` 实测：总宽 167，而三个按钮各需 69/36/60，
 * 等分只有 55 —— 最长的标签必然变成「ESI 与…」）。
 *
 * 所以总宽只能自己算。每个按钮要多少，直接问按钮自己：`implicitWidth` 已经含了它的
 * 左右内边距，而且**不受被挤窄影响**（挤的是 `width`，不是 `implicitWidth`）。
 *
 * 别改成「用 `TextMetrics` 量文字 + 补一个猜的内边距」：那要在这里复述一遍委托的
 * 字号与内边距，委托一改就悄悄失准（字号还随 `Theme.fontScale` 变）。`implicitWidth`
 * 是委托自己算出来的，天然跟着走。
 *
 * 本函数是**纯函数**（只读入参、不写 `bar` 的任何属性），所以可以直接写在绑定里：
 *     Layout.preferredWidth: TabFit.requiredWidth(root)
 * 它依赖的是各按钮的 `implicitWidth`，与 `bar` 自己的宽度无关，因此不存在绑定循环。
 */

/** 装下 `bar` 里最长标签所需的总宽；`bar` 为空时返回 0。 */
function requiredWidth(bar) {
    if (!bar || !bar.count)
        return 0;
    var widest = 0;
    for (var i = 0; i < bar.count; ++i) {
        var item = bar.itemAt(i);
        if (item)
            widest = Math.max(widest, item.implicitWidth);
    }
    /* 等分意味着每格都要容得下最宽的那个；再补上标签栏自身的左右内边距。
     *
     * 每格额外 +1px 不是随手加的余量：等分按整像素落地时**每格会少 1px**——
     * 实测 `CharSettingsDialog` 给足 180（正好 3×60）时每格只拿到 59，
     * 而按钮需要 60，于是「市场费率」照样被省略号截掉。+1 正好补掉这个取整损失。*/
    return (Math.ceil(widest) + 1) * bar.count + bar.leftPadding + bar.rightPadding;
}
