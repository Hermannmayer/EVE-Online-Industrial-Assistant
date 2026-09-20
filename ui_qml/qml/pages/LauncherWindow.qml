import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import "../components"

/* 产线启动小助手 —— 阶段 2c：整窗由 QML 渲染（L1–L4 四区）。
 *
 * 对照 Widgets 版 `ui_pyside6/views/industry/production_launcher.py`：
 *   L1 工具条（线型/人物筛选 + 筛选摘要 + 置顶）
 *   L2 占用面板（可折叠，逐角色一行容量方块）
 *   L3 产线列表（行卡片，图标 + 标题/徽章/副标题 + 时长 + 动作槽）
 *   L4 详情执行面板（未选中紧凑单行；选中后参数摘要 + 执行人物 + 主按钮）
 *
 * **业务动作一律不在这里实现**：每次交互都调 `launcher.<方法>`，
 * 由 `ui_qml/bridge/launcher_bridge.py` 转给 `ProductionLauncher`。
 * 行卡片的五态动作槽（折叠/可下线/启动/强制启动/阻塞）也由 Python 判好后
 * 以 `actionKind` 传达，QML 只负责画。
 *
 * 批次 7.4：根元素从 `Item` 换成 **`Window`** —— 控制器退成 `QObject`，不再有
 * `QWidget` 外壳，窗口语义（标题 / 尺寸 / 顶层 / 关闭 / 显示事件）由这里自持。
 * 命令式的那几项（show / raise / activate / resize）仍由控制器转发，见该文件
 * `# ── 窗口命令` 一节。
 */
Window {
    id: win

    /* ── 窗口语义（逐项对齐原 QWidget 版 `ProductionLauncher`）──
     *
     *   setWindowTitle("产线启动小助手")  → title 绑定到桥的 titleText
     *   setWindowFlag(Qt.Window, True)   → 顶层 Window 默认就带 Qt.Window；构造时
     *                                      也不给 transientParent，所以仍然「不随主窗
     *                                      最小化」，与原来 parent=None 的语义一致
     *   resize(880, 760)                 → width / height
     *   setMinimumSize(560, 480)         → minimumWidth / minimumHeight
     *   show() / raise_() / activateWindow() → 由控制器转发（QML 里没有对等写法：
     *                                        `Window.raise()` / `requestActivate()`）
     *
     * ⚠️ 宽度按**实测的内容最小宽**定，不按「好看」定：这个窗口也常与游戏同屏
     * （工具条上有「置顶」），宽了就挡游戏。量出来的两处下限（字体缩放 1.0）：
     *   - L2 占用面板的容量方块行（`FCapacityRow`）≈ 420 ← 由它定 `minimumWidth`
     *   - L1 工具条（两个下拉 + 置顶）≈ 350
     * `minimumWidth` 取 420 + 10 余量：离屏量的是方框字，真字体的字宽可能略胖。
     * 默认宽度取 520：行卡片的「名称 / 副标题」还读得全，再窄就只剩省略号。
     * 两个值都乘 `Theme.fontScale`：方块与文字随字体放大，写死数字的话放大字体后又会被裁。
     * 护栏：`tests/test_production_launcher.py::test_narrowest_window_clips_nothing`。
     */
    readonly property int contentMinWidth: Math.round(430 * Theme.fontScale)
    readonly property int defaultWidth: Math.round(520 * Theme.fontScale)
    width: win.defaultWidth
    height: 760
    minimumWidth: win.contentMinWidth
    minimumHeight: 480
    title: win.launcher ? win.launcher.titleText : ""
    // 窗口清屏色 = 页面底色：首帧之前也不会闪一下白底
    color: Theme.bgDark
    visible: false // 由 Python 侧的 `show()` 打开（构造完不该自己冒出来）

    /* 显示 / 关闭 —— 等价于原 `showEvent` / `closeEvent`。
     *
     * 关闭时停表、再次显示时重启（单实例复用后不会变成不刷新的死窗口）；
     * 控制器侧的方法名与时序见 `ProductionLauncher.window_visibility_changed` /
     * `window_closing`。 */
    onVisibleChanged: if (win.launcher)
        win.launcher.windowVisibilityChanged(win.visible)

    /* ⚠️ QML 的 `Window.onClosing` 是**可取消**的：一旦挂上处理函数，
     * 就必须显式 `close.accepted = true`，否则关闭事件被静默吃掉、窗口关不掉。 */
    onClosing: function (close) {
        if (win.launcher)
            win.launcher.windowClosing()
        close.accepted = true
    }

    /* 别名不与 context property 同名 —— 同名声明会**遮蔽** context property，
     * 恒为 null 且无任何报错（QML 查找顺序是「自身属性 → context」）。 */
    readonly property var launcher: typeof bridge !== "undefined" ? bridge : null

    readonly property int fntCaption: Math.round(13 * Theme.fontScale)
    readonly property int fntBody: Math.round(14 * Theme.fontScale)
    readonly property int padXs: Theme.spacingXs
    readonly property int padSm: Theme.spacingSm
    readonly property int padMd: Theme.spacingMd

    /* 整窗不透明底。
     *
     * 原来这里是给 `PageHost(QQuickWidget)` 的透明清屏色兜底（宿主设了
     * `setClearColor(transparent)`，页面没画到的地方会透出窗口背后的东西）。
     * 现在宿主就是本 `Window`，`color` 已经负责首帧清屏，这个矩形继续兜住
     * 「内容区之下的整块表面」，与 `EstimatePage` / `DemoPage` 同款。 */
    Rectangle {
        anchors.fill: parent
        color: Theme.bgDark
    }

    // ═══════════════════════════════════════════════════════════
    //  L1 工具条（固定单行）
    // ═══════════════════════════════════════════════════════════

    Item {
        id: toolbar
        objectName: "toolbar"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: win.padXs
        height: Math.max(30, win.fntCaption + 18)

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 1
            color: Theme.border
        }

        RowLayout {
            anchors.fill: parent
            spacing: win.padSm

            FComboBox {
                id: lineFilter
                model: win.launcher ? win.launcher.lineFilters : []
                textRole: "label"
                Layout.preferredWidth: 130
                Layout.maximumWidth: 160
                onActivated: win.launcher.setLineFilterIndex(currentIndex)
            }

            FComboBox {
                id: charFilter
                model: win.launcher ? win.launcher.charFilters : []
                textRole: "label"
                Layout.preferredWidth: 180
                Layout.maximumWidth: 260
                onActivated: win.launcher.setCharFilterIndex(currentIndex)
            }

            Text {
                text: win.launcher ? win.launcher.filterSummary : ""
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: win.fntCaption
                elide: Text.ElideRight
                Layout.fillWidth: true
            }

            FButton {
                text: qsTr("置顶")
                primary: win.launcher ? win.launcher.pinned : false
                onClicked: win.launcher.setPinned(!win.launcher.pinned)
            }
        }
    }

    // ═══════════════════════════════════════════════════════════
    //  L2 占用面板（可折叠，≤4 行不滚动）
    // ═══════════════════════════════════════════════════════════

    Item {
        id: occHeader
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: toolbar.bottom
        anchors.leftMargin: win.padXs
        anchors.rightMargin: win.padXs
        height: Math.max(22, win.fntCaption + 8)

        RowLayout {
            anchors.fill: parent
            spacing: win.padSm

            FButton {
                text: (win.launcher && win.launcher.occupancyCollapsed) ? "+" : "−"
                implicitWidth: 28
                onClicked: win.launcher.toggleOccupancy()
                ToolTip.visible: hovered
                ToolTip.text: qsTr("折叠/展开产线占用")
            }

            Text {
                text: qsTr("产线占用")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: win.fntCaption
            }

            Text {
                text: win.launcher ? win.launcher.occupancySummary : ""
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: win.fntCaption
                elide: Text.ElideRight
            }

            Item {
                Layout.fillWidth: true
            }
        }
    }

    Item {
        id: occPanel
        objectName: "occPanel"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: occHeader.bottom
        anchors.leftMargin: win.padXs
        anchors.rightMargin: win.padXs

        readonly property bool collapsed: win.launcher ? win.launcher.occupancyCollapsed : false
        readonly property int rowH: Math.max(26, Math.round(Math.max(14, win.fntBody + 1)) + 10)
        readonly property int maxRows: 4
        readonly property int rowCount: win.launcher ? win.launcher.occupancyRows.length : 0
        height: collapsed ? 0 : Math.min(rowCount, maxRows) * (rowH + 1) + 2
        visible: !collapsed
        clip: true

        ListView {
            id: occList
            anchors.fill: parent
            model: win.launcher ? win.launcher.occupancyRows : []
            spacing: 1
            clip: true
            interactive: contentHeight > height
            boundsBehavior: Flickable.StopAtBounds

            delegate: FCapacityRow {
                required property var modelData
                width: occList.width
                charName: modelData.name
                nameWidth: modelData.nameWidth
                lines: modelData.lines
                statusText: modelData.statusText
                statusColor: modelData.statusColor
                slotTotal: modelData.slotTotal
            }
        }

        Text {
            anchors.centerIn: parent
            visible: occList.count === 0
            text: win.launcher ? win.launcher.occupancySummary : ""
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: win.fntCaption
        }
    }

    // ═══════════════════════════════════════════════════════════
    //  L3 产线列表（主工作区）
    // ═══════════════════════════════════════════════════════════

    Item {
        id: listArea
        // 供测试当「可 `findChild` 又可可 `mapToItem` 的根」用（见 `tests/qml_click.py`）：
        // 根元素是 `Window` 时，声明出来的顶层 Item 的 QObject 父是**窗口本身**，
        // `parentItem` 才是窗口的 `contentItem` —— 于是从 `contentItem()` 往下
        // `findChild` 什么都找不到，必须落到某个真正的 Item 上。
        objectName: "listArea"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: occPanel.bottom
        anchors.bottom: bottomPanel.top
        anchors.margins: win.padXs

        ListView {
            id: planList
            anchors.fill: parent
            clip: true
            spacing: win.padXs
            model: win.launcher ? win.launcher.rows : []
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar {
                policy: ScrollBar.AsNeeded
            }

            delegate: Rectangle {
                id: rowCard
                required property int index
                required property var modelData

                readonly property bool selected: win.launcher && win.launcher.selectedId === modelData.id

                width: planList.width
                height: win.launcher ? win.launcher.rowHeight : 68
                color: mouse.containsMouse || selected ? Theme.bgSurfaceLight : Theme.bgDark
                border.width: 1
                border.color: Theme.border
                radius: Theme.radius

                HoverHandler {
                    id: mouse
                    cursorShape: Qt.PointingHandCursor
                }

                RowLayout {
                    objectName: "rowCardRow"
                    anchors.fill: parent
                    anchors.leftMargin: win.padMd + modelData.indent
                    anchors.rightMargin: win.padMd
                    // 上下内边距取 XS：行高由 `launcher.rowHeight` 钉死，这里多留的每一像素
                    // 都是在挤内容区（真正的高度下限是右侧「时长 + 26px 按钮」那一列）。
                    anchors.topMargin: win.padXs
                    anchors.bottomMargin: win.padXs
                    spacing: win.padMd

                    // 子级缩进引导线
                    Rectangle {
                        visible: modelData.indent > 0
                        Layout.preferredWidth: 2
                        Layout.fillHeight: true
                        color: Theme.border
                    }

                    // 图标（无图标文件时退回类别首字）
                    Item {
                        Layout.preferredWidth: 32
                        Layout.preferredHeight: 32

                        Image {
                            anchors.fill: parent
                            visible: rowCard.modelData.iconUrl !== ""
                            source: rowCard.modelData.iconUrl
                            sourceSize.width: 32
                            sourceSize.height: 32
                            fillMode: Image.PreserveAspectFit
                        }

                        Text {
                            anchors.centerIn: parent
                            visible: rowCard.modelData.iconUrl === ""
                            text: rowCard.modelData.iconFallback
                            color: Theme.textPrimary
                            font.family: Theme.fontFamily
                            font.pixelSize: win.fntBody
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: win.padXs

                        RowLayout {
                            spacing: win.padSm

                            Text {
                                Layout.fillWidth: true
                                text: rowCard.modelData.name
                                elide: Text.ElideRight
                                color: Theme.textBright
                                font.family: Theme.fontFamily
                                font.pixelSize: win.fntBody
                            }

                            // 状态徽章
                            Rectangle {
                                Layout.preferredWidth: statusText.implicitWidth + 2 * win.padSm
                                Layout.preferredHeight: 20
                                radius: Theme.radiusSmall
                                color: Theme.bgSurfaceLight

                                Text {
                                    id: statusText
                                    anchors.centerIn: parent
                                    text: rowCard.modelData.statusText
                                    color: Theme.textPrimary
                                    font.family: Theme.fontFamily
                                    font.pixelSize: win.fntCaption
                                }

                                ToolTip.visible: statusHover.hovered
                                ToolTip.text: rowCard.modelData.statusTip
                                HoverHandler {
                                    id: statusHover
                                }
                            }

                            Item {
                                Layout.fillWidth: true
                            }
                        }

                        Text {
                            Layout.fillWidth: true
                            text: rowCard.modelData.metaText
                            elide: Text.ElideRight
                            color: Theme.textPrimary
                            font.family: Theme.fontFamily
                            font.pixelSize: win.fntCaption
                        }
                    }

                    ColumnLayout {
                        spacing: win.padXs
                        // 动作槽固定宽度：**三个都要钉死**。只给 preferredWidth 时
                        // RowLayout 仍可能把它撑开（槽内按钮会跟着变宽），
                        // 而这一段的全部意义就是「五个按钮切换时占位不变、动作区不左右跳」。
                        readonly property int slotW: Math.max(win.launcher ? win.launcher.actionSlotWidth : 88, 88)
                        Layout.preferredWidth: slotW
                        Layout.minimumWidth: slotW
                        Layout.maximumWidth: slotW

                        Text {
                            Layout.fillWidth: true
                            horizontalAlignment: Text.AlignRight
                            // 显式读一下心跳计数：model 是普通 var 列表，改字典里的值
                            // 不会触发重绘，绑定必须依赖一个会通知的属性才会重新求值
                            text: {
                                if (win.launcher)
                                    win.launcher.tickRevision
                                return rowCard.modelData.durationText
                            }
                            color: Theme.textPrimary
                            font.family: Theme.fontFamily
                            font.pixelSize: win.fntCaption
                            elide: Text.ElideRight
                        }

                        // 动作槽：恒占位，槽内五态互斥（排版不跳动）
                        Item {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 26

                            FButton {
                                anchors.right: parent.right
                                width: parent.width
                                implicitHeight: 26
                                visible: rowCard.modelData.actionKind === "start"
                                primary: true
                                text: rowCard.modelData.actionText
                                onClicked: win.launcher.rowStart(rowCard.modelData.id)
                            }

                            FButton {
                                anchors.right: parent.right
                                width: parent.width
                                implicitHeight: 26
                                visible: rowCard.modelData.actionKind === "toggle"
                                text: rowCard.modelData.actionText
                                onClicked: win.launcher.rowToggle(rowCard.modelData.groupId)
                            }

                            FButton {
                                anchors.right: parent.right
                                width: parent.width
                                implicitHeight: 26
                                visible: rowCard.modelData.actionKind === "complete"
                                primary: true
                                text: rowCard.modelData.actionText
                                onClicked: win.launcher.rowComplete(rowCard.modelData.id)
                            }

                            FButton {
                                anchors.right: parent.right
                                width: parent.width
                                implicitHeight: 26
                                visible: rowCard.modelData.actionKind === "blocked"
                                text: rowCard.modelData.actionText
                                onClicked: win.launcher.rowBlocked(rowCard.modelData.id)
                            }
                        }
                    }
                }

            }

            /* 行点击命中固定在按下那一刻（见 FTableClickArea 的说明）。
             * 这是 ListView 行卡片：整行一格（`columnWidth: null`），行距 = 卡片高 + spacing。 */
            FTableClickArea {
                objectName: "launcherClickArea"
                anchors.fill: parent
                rowHeight: win.launcher ? win.launcher.rowHeight : 68
                rowSpacing: planList.spacing
                columnWidth: null

                function _idAt(row) {
                    const rows = win.launcher ? win.launcher.rows : []
                    return row >= 0 && row < rows.length ? rows[row].id : null
                }

                onRowClicked: function (row, _column) {
                    const id = _idAt(row)
                    if (id === null)
                        return
                    win.launcher.selectRow(id)
                    win.launcher.rowClicked(id)
                }
                onRowRightClicked: function (row, _column, _x, _y) {
                    const id = _idAt(row)
                    if (id !== null)
                        win.launcher.rowContextMenu(id)
                }
            }
        }

        Text {
            anchors.centerIn: parent
            visible: win.launcher && win.launcher.isEmpty
            text: qsTr("该角色无产线计划")
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: win.fntBody
        }
    }

    // ═══════════════════════════════════════════════════════════
    //  L4 详情 / 执行面板
    // ═══════════════════════════════════════════════════════════

    Rectangle {
        id: bottomPanel
        objectName: "bottomPanel"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: win.padXs
        color: Theme.bgSurface
        border.width: 1
        border.color: Theme.border
        radius: Theme.radius
        height: content.implicitHeight + 2 * win.padSm

        ColumnLayout {
            id: content
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: win.padSm
            spacing: win.padSm

            // 紧凑态
            Text {
                Layout.fillWidth: true
                visible: win.launcher && !win.launcher.bottomExpanded
                text: win.launcher ? win.launcher.bottomHint : ""
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: win.fntCaption
                elide: Text.ElideRight
            }

            // 展开态
            ColumnLayout {
                Layout.fillWidth: true
                visible: win.launcher && win.launcher.bottomExpanded
                spacing: win.padSm

                Text {
                    Layout.fillWidth: true
                    text: win.launcher ? win.launcher.paramsText : ""
                    color: Theme.textPrimary
                    font.family: Theme.fontFamily
                    font.pixelSize: win.fntCaption
                    wrapMode: Text.WordWrap
                }

                RowLayout {
                    spacing: win.padMd

                    FComboBox {
                        id: executorCombo
                        model: win.launcher ? win.launcher.executors : []
                        textRole: "label"
                        Layout.preferredWidth: 220
                        Layout.maximumWidth: 300
                        onActivated: win.launcher.setExecutorIndex(currentIndex)
                    }

                    Item {
                        Layout.fillWidth: true
                    }

                    FButton {
                        visible: win.launcher ? win.launcher.mainButtonVisible : false
                        primary: true
                        text: win.launcher ? win.launcher.mainButtonText : ""
                        onClicked: win.launcher.mainAction()

                        ToolTip.visible: mainHover.hovered
                        ToolTip.text: win.launcher ? win.launcher.mainButtonTip : ""
                        HoverHandler {
                            id: mainHover
                        }
                    }
                }

                Text {
                    Layout.fillWidth: true
                    visible: text !== ""
                    text: win.launcher ? win.launcher.feedback : ""
                    color: Theme.textSecondary
                    font.family: Theme.fontFamily
                    font.pixelSize: win.fntCaption
                    wrapMode: Text.WordWrap
                }
            }
        }
    }

    // 选中行变化时把列表滚到该行（行内启动 / 阻塞提示共用）
    Connections {
        target: win.launcher
        function onSelectionRequested(planId) {
            for (let i = 0; i < planList.count; ++i) {
                if (planList.itemAtIndex(i) && planList.itemAtIndex(i).modelData.id === planId) {
                    planList.positionViewAtIndex(i, ListView.Contain)
                    return
                }
            }
        }
        function onToolbarChanged() {
            if (lineFilter.currentIndex !== win.launcher.lineFilterIndex)
                lineFilter.currentIndex = win.launcher.lineFilterIndex
            if (charFilter.currentIndex !== win.launcher.charFilterIndex)
                charFilter.currentIndex = win.launcher.charFilterIndex
        }
        function onBottomChanged() {
            if (executorCombo.currentIndex !== win.launcher.executorIndex)
                executorCombo.currentIndex = win.launcher.executorIndex
        }
        // 行右键：条目与可见性由 Python 判定（`_can_partial_start` 要读计划状态）
        function onContextMenuRequested(planId, canPartial) {
            rowMenu.planId = planId
            rowMenu.canPartial = canPartial
            rowMenu.popupSoon()
        }
    }

    /* 行右键菜单 —— 取代原先 Python 侧自建的 `QMenu` + `menu.exec(QCursor.pos())`。
     *
     * 条目用 `FMenuItem` 而不是裸 `MenuItem`：后者在 `visible: false` 时**照样占满
     * 一整行高度**（Menu 用 ListView 渲染全部声明项），会留出一行空行；`FMenuItem`
     * 不可见时把高度一并压成 0。
     * 用 `popupSoon()` 而非 `popup()`：见 `FMenu.qml` 里「延迟一拍」那段 —— 直接弹会被
     * 那次右键的按下/释放当成对条目的点击。
     */
    FMenu {
        id: rowMenu
        objectName: "rowMenu"
        property int planId: -1
        property bool canPartial: false

        FMenuItem {
            text: qsTr("添加备注…")
            onTriggered: if (win.launcher)
                win.launcher.rowNotes(rowMenu.planId)
        }

        FMenuItem {
            text: qsTr("部分启动…")
            visible: rowMenu.canPartial
            onTriggered: if (win.launcher)
                win.launcher.rowPartialStart(rowMenu.planId)
        }
    }

    Component.onCompleted: {
        if (!win.launcher)
            return
        lineFilter.currentIndex = win.launcher.lineFilterIndex
        charFilter.currentIndex = win.launcher.charFilterIndex
        executorCombo.currentIndex = win.launcher.executorIndex
    }
}
