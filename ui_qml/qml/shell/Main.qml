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

    Column {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            width: parent.width
            height: 32
            color: root.chromeColor
            ShellTitleBar {
                anchors.fill: parent
            }
        }

        // ── 工具行（区域 / 更新价格 / 价格年龄 / 自动更新）──
        Rectangle {
            width: parent.width
            height: 36
            color: root.chromeColor

            Item {
                id: toolbar
                anchors.fill: parent

                Row {
                    anchors.left: parent.left
                    anchors.leftMargin: 8
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 6

                    // 区域勾选下拉
                    ShellIconButton {
                        icon: "caret-down"
                        label: shell.regionText
                        tooltip: "选择价格更新区域"
                        tint: Theme.textSecondary
                        onClicked: regionMenu.popup()
                    }

                    ShellIconButton {
                        icon: "refresh"
                        label: "更新价格"
                        tooltip: "立即从 ESI 拉取价格"
                        tint: Theme.textPrimary
                        onClicked: shell.refreshPrice()
                    }
                }

                // 价格年龄（小圆点 + 文案）
                Item {
                    id: priceAge
                    anchors.left: parent.left
                    anchors.leftMargin: 190
                    anchors.verticalCenter: parent.verticalCenter

                    Rectangle {
                        id: ageDot
                        width: 12
                        height: 12
                        radius: 6
                        color: shell.priceAgeColor
                    }
                    Text {
                        anchors.left: ageDot.right
                        anchors.leftMargin: 4
                        anchors.verticalCenter: ageDot.verticalCenter
                        text: shell.priceAgeText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fs(11)
                        color: Theme.textSecondary
                    }
                }

                ShellIconButton {
                    anchors.right: parent.right
                    anchors.rightMargin: 8
                    anchors.verticalCenter: parent.verticalCenter
                    icon: "clock"
                    label: shell.autoUpdateText
                    tooltip: "自动更新价格（点击切换开/关）"
                    checkable: true
                    checked: shell.autoUpdate
                    tint: shell.autoUpdate ? Theme.accentGreen : Theme.textSecondary
                    onClicked: shell.setAutoUpdate(!shell.autoUpdate)
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
            height: parent.height - 32 - 36 - 24

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
            height: 24
            color: Theme.bgSurface
            ShellStatusBar {
                anchors.fill: parent
            }
        }
    }
}
