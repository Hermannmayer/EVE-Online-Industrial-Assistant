import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

import "tabfit.js" as TabFit

/* 等宽标签栏 —— `TabBar` 的替身，解决了「最长的标签被截成省略号」。
 *
 * 为什么不能直接用 `TabBar`：它把可用宽度**等分**给每个按钮，不看各自的
 * `implicitWidth`；而它自己的 `implicitWidth` 又是从这些被挤窄的按钮反推的，两者互相
 * 锁死在一个放不下最长标签的宽度上。窄容器（`RowLayout` + 占位 `Item` 那套「标签栏靠左
 * 收窄」的写法）里必然截断：实测 `CharSettingsDialog` 的「市场费率」每格只拿到 48px
 * （它需要 60），`SettingsDialog` 的「ESI 与数据」是 55px（需要 69）。
 *
 * 用法与 `TabBar` 一致：把标签栏从 `TabBar` 换成 `FTabBar` 即可，容器照旧。
 *     RowLayout { FTabBar { TabButton { text: … } } ; Item { Layout.fillWidth: true } }
 * 标签栏被 `Layout.fillWidth: true` 拉满时（贸易页那种）本组件也无害：
 * 布局忽略 preferredWidth，宽度照旧由容器决定。
 */

TabBar {
    id: root

    /* 总宽用**绑定**算，而不是「函数量一次 + 存进属性」。
     *
     * 量的是各按钮的 `implicitWidth`，它只随文字与字号变，与标签栏自己的宽度无关 ——
     * 所以这里**没有** `FComboBox.maxItemWidth` 那种「读自己宽度 → 又写自己宽度」的绑定
     * 循环。字号一变（换主题 / 调全局字号）按钮的 `implicitWidth` 就变，绑定自动重算，
     * 不需要任何监听。
     *
     * 也**别**换成 `Connections { target: Theme }`：`Theme` 是进程级单例，而每个
     * `PageHost` 各持一个 QML 引擎（见 `host.py` 头部注释），跨引擎连信号在拆宿主时的
     * 析构顺序上很脆；本仓其余主题监听一律走 Python 侧 `theme.add_theme_listener`。
     */
    Layout.preferredWidth: TabFit.requiredWidth(root)

    /* 容器不够宽时也别挤我：只写 `preferredWidth` 的话，窄容器里每个按钮仍会被压到
     * `width / n`，照样截标签（实测：被测标签栏宽度被压到 0）。*/
    Layout.minimumWidth: TabFit.requiredWidth(root)
}
