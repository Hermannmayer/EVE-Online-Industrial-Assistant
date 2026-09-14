import QtQuick
import QtQuick.Controls

/* Fluent 菜单项 —— 在官方 MenuItem 上补一个 Qt 的坑。
 *
 * `Menu` 用 ListView 渲染**全部声明项**，`visible: false` 的条目**照样占满一整行高度**：
 * 实测一个 `visible: false` 的 MenuItem 仍是 y 照排、h=30，把后面的项整体推下去，
 * 视觉上就是一串空行（用户反馈的「右键菜单一堆空行」）。
 * 条件显示的菜单项请一律用它 —— 不可见时把高度一并压成 0。
 *
 * 只压高度、不动其他属性：配色/内边距/高亮/子菜单箭头仍由 Qt 样式提供，
 * 表面色由 `FMenu` 的 background 覆盖（Qt 官方样式的菜单底是中性灰图集，不跟主题）。
 */
MenuItem {
    height: visible ? implicitHeight : 0
}
