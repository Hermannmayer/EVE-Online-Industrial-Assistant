import QtQuick
import QtQuick.Controls

/* 整页外壳（阶段 5 批次 6.1）—— 顶替 Widgets 版 `ui_pyside6/main_window.py` 的外框。

   由 `ui_qml/shell_window.ShellWindow`（`QQuickView` 子类）加载；根元素是 `Item`
   不是 `Window`，因为窗口本身要在 Python 里继承（`nativeEvent` 要处理
   `WM_NCCALCSIZE` 等无边框窗口消息）。

   页面由 Python 挂进 `contentArea`（`registry` 造的是 QML Item，不再是 QQuickWidget
   —— QQuickWidget 是 QWidget，装不进 QQuickWindow）。尺寸同步在 Python 侧连信号做，
   这里不写回调。
*/
Item {
    id: root

    // 页面容器：Python 通过 `rootObject().property("contentArea")` 取到它
    property Item contentArea: contentArea

    /* 外壳各行的底色。**照搬原 QSS 的取值**（`ui_qml/theme/registry.py`）：
       标题行与导航是 `BG_SURFACE` 约 90% 不透明（留住一点 DWM 毛玻璃），
       状态栏不透明；**只有内容区透明**——页面自己铺底，Mica 从页面边缘透出来。
       不这么做的话顶栏会直接透到桌面，看起来像没画完。 */
    readonly property color chromeColor: Qt.rgba(
        Theme.bgSurface.r, Theme.bgSurface.g, Theme.bgSurface.b, 0.9)

    /* 标题行 / 工具行 / 状态栏的高度，以及各行的左内边距。
       以前这三行的高度是散在布局里和 body 的算式里各写一遍的字面量，
       改一处忘一处就会让内容区少算一截。 */
    readonly property int titleRowH: 32
    readonly property int toolRowH: 36
    readonly property int statusRowH: 24
    /* 标题文字、工具行左侧控件组、导航行图标列共用这一条竖线 ——
       批注「此处没有上下对齐（和旁边的字）」要的就是它。
       （侧栏 logo 不在这条线上：它按用户要求水平居中。） */
    readonly property int chromeInset: Theme.spacingMd

    Column {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            width: parent.width
            height: root.titleRowH
            color: root.chromeColor
            ShellTitleBar {
                anchors.fill: parent
                leftInset: root.chromeInset
            }
        }

        /* ── 工具行 ──
           左侧一律是「状态与上下文」（区域 / 价格年龄 / 自动更新），连成一组；
           右侧只留一个动作（更新价格）。改版前自动更新被甩在最右边，
           和它讲的是同一件事的价格年龄隔了半个屏幕。 */
        Rectangle {
            width: parent.width
            height: root.toolRowH
            color: root.chromeColor

            Item {
                id: toolbar
                anchors.fill: parent

                Row {
                    anchors.left: parent.left
                    anchors.leftMargin: root.chromeInset
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: Theme.spacingSm

                    // 区域勾选下拉
                    ShellIconButton {
                        icon: shell.iconFile("caret-down")
                        label: shell.regionText
                        tooltip: "选择价格更新区域"
                        tint: Theme.textSecondary
                        onClicked: regionMenu.popup()
                    }

                    // 分隔：区域是「查询范围」，后面三项是「价格是否新鲜」
                    Rectangle {
                        anchors.verticalCenter: parent.verticalCenter
                        width: 1
                        height: 16
                        color: Theme.border
                    }

                    // 价格年龄（小圆点 + 文案）
                    Item {
                        id: priceAge
                        anchors.verticalCenter: parent.verticalCenter
                        width: ageDot.width + 4 + ageText.width
                        height: ageText.height

                        Rectangle {
                            id: ageDot
                            width: 12
                            height: 12
                            radius: 6
                            color: shell.priceAgeColor
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Text {
                            id: ageText
                            anchors.left: ageDot.right
                            anchors.leftMargin: 4
                            anchors.verticalCenter: parent.verticalCenter
                            text: shell.priceAgeText
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fs(11)
                            color: Theme.textSecondary
                        }
                    }

                    // 自动更新（紧跟价格年龄 —— 两者说的是同一件事）
                    ShellIconButton {
                        icon: shell.iconFile("clock")
                        label: shell.autoUpdateText
                        tooltip: "自动更新价格（点击切换开/关）"
                        checkable: true
                        checked: shell.autoUpdate
                        tint: shell.autoUpdate ? Theme.accentGreen : Theme.textSecondary
                        onClicked: shell.setAutoUpdate(!shell.autoUpdate)
                    }
                }

                ShellIconButton {
                    anchors.right: parent.right
                    anchors.rightMargin: root.chromeInset
                    anchors.verticalCenter: parent.verticalCenter
                    icon: shell.iconFile("refresh")
                    label: "更新价格"
                    tooltip: "立即从 ESI 拉取价格"
                    tint: Theme.textPrimary
                    onClicked: shell.refreshPrice()
                }

                Menu {
                    id: regionMenu
                    Repeater {
                        model: shell.regions
                        MenuItem {
                            required property var modelData
                            text: modelData.name
                            checkable: true
                            checked: modelData.checked
                            onTriggered: shell.setRegion(modelData.name, !modelData.checked)
                        }
                    }
                }
            }
        }

        // ── 主体：导航 + 页面 ──
        Item {
            id: body
            width: parent.width
            height: parent.height - root.titleRowH - root.toolRowH - root.statusRowH

            Rectangle {
                id: navBackground
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                width: 160
                color: root.chromeColor
            }

            ShellNavPanel {
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                width: 160
            }

            // 内容区**不铺底**：页面自己画背景，Mica 从页面边缘透出来
            Item {
                id: contentArea
                anchors.left: navBackground.right
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.bottom: parent.bottom
            }
        }

        Rectangle {
            width: parent.width
            height: root.statusRowH
            color: Theme.bgSurface
            ShellStatusBar {
                anchors.fill: parent
            }
        }
    }
}
