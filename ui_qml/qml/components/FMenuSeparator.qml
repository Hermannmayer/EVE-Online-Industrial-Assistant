import QtQuick.Controls

/* Fluent 菜单分隔线 —— 与 `FMenuItem` 同一个坑：`Menu` 的 ListView 会为**声明过但不可见**
 * 的条目照样留位（实测分隔线 h=5），条件显示的场合必须把高度一并压掉，
 * 否则菜单里仍会剩下一串细空条。
 */
MenuSeparator {
    height: visible ? implicitHeight : 0
}
