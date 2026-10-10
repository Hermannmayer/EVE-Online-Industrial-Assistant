import QtQuick
import QtQuick.Controls
import QtQuick.Effects
import QtQuick.Layouts
import "../components"
import "watchlist"

/* 关注 Tab（原「价格监控」页）—— 阶段 3 建的页，WP5 重构成**两栏**：
 *
 *   ┌ 顶部：搜索物品 + 区域 + 备注 + 添加关注（原样保留） ─────────────┐
 *   ├ 左（220–260px，可拖拽）：关注列表 + 排序 ─┬ 右：选中物品详情 ────┤
 *   │  阈值触发/价格变化的行底色、右键菜单照旧   │  `WatchlistDetailPane` │
 *   ├ 底部：刷新价格 / 删除选中 / 计数（原样保留）─────────────────────┤
 *
 * **业务动作一律不在这里实现**：每次交互都调 `watch.<方法>`，
 * 由 `ui_qml/bridge/watchlist_bridge.py` 转给 `services.watchlist_manager`。
 *
 * 左侧列表从 10 列 `TableView` 改成**行卡片 `ListView`**（窄栏放不下 10 列）：
 *   - 行内两段文字：物品名 / 「买 x 卖 y 涨幅」；
 *   - 行点击仍走 `FTableClickArea`（`objectName: "watchClickArea"`，命中固定在按下那一刻）；
 *   - **阈值能力没有丢**：右键菜单（设置买价/卖价阈值）与右详情面板的两个按钮都在，
 *     外加**双击行 = 设置买价阈值**（原版双击第 7 列做的事，窄列表里没有那一列了）。
 *
 * 参考：`docs/dev/market-monitor-plan.md` 4.2（关注 Tab 的目标结构）。
 */
Item {
    id: page

    /* 监控桥，由 `PageHost` 以 context property `bridge` 注入。
     * 别名不与 context property 同名（同名声明会遮蔽它，恒为 null 且无报错）。 */
    readonly property var watch: typeof bridge !== "undefined" ? bridge : null

    readonly property int fntBase: Math.round(12 * Theme.fontScale)
    readonly property int fntSmall: Math.round(11 * Theme.fontScale)
    //: 左列表的行高（两行文字）；`FTableClickArea` 的命中口径依赖它恒定
    readonly property int listRowH: Math.max(42, Math.round(26 * Theme.fontScale))
    readonly property int pad: Theme.spacingSm

    //: 当前行（右键菜单 / 删除 / 阈值编辑都作用于它）
    property int currentRow: -1
    //: 阈值弹层的目标
    property int thresholdRow: -1
    property string thresholdKind: "buy"
    //: 顶部提示（添加失败等），短暂显示
    property string hint: ""

    // 整页不透明底（宿主是透明清屏的 QQuickWidget，见 IndustryPage 的同款说明）
    Rectangle {
        anchors.fill: parent
        color: Theme.bgDark
    }

    function openThreshold(row, kind) {
        const info = page.watch ? page.watch.rowInfo(row) : ({})
        if (!info.valid)
            return
        page.thresholdRow = row
        page.thresholdKind = kind
        thresholdPopup.title = (kind === "buy" ? qsTr("设置买价阈值") : qsTr("设置卖价阈值"))
        thresholdPopup.hint = (kind === "buy"
                               ? qsTr("当买价 ≤ 此值时提醒")
                               : qsTr("当卖价 ≥ 此值时提醒")) + "\n" + info.name
        thresholdInput.value = kind === "buy" ? info.buyThreshold : info.sellThreshold
        thresholdPopup.open()
    }

    /* 列表刷新（60 秒轮询 / 增删 / 排序后）行号会变，当前行以桥里的选中行为准 —— 桥按
     * `watchlist_items.id` 重新定位，这里只把结果同步到高亮用的 `currentRow`。 */
    Connections {
        target: page.watch

        function onRowsChanged() {
            if (page.watch)
                page.currentRow = page.watch.selectedRow
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: page.pad

        // ═══════════════════════════════════════════════════════
        //  1. 顶部：添加关注
        // ═══════════════════════════════════════════════════════

        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 2 * page.pad
            Layout.rightMargin: 2 * page.pad
            Layout.topMargin: 2 * page.pad
            spacing: page.pad

            Text {
                text: qsTr("搜索物品:")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntBase
            }

            FTextField {
                id: searchInput
                Layout.preferredWidth: 280
                placeholderText: qsTr("输入物品名称或 Type ID...")
                onTextChanged: if (page.watch)
                    page.watch.onSearchChanged(text)
                onAccepted: if (page.watch)
                    page.watch.add()
                Keys.onEscapePressed: suggestPopup.close()
            }

            Text {
                Layout.minimumWidth: 120
                text: page.watch ? page.watch.selectedName : ""
                color: Theme.primary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntBase
                font.bold: true
                elide: Text.ElideRight
            }

            Text {
                text: qsTr("区域:")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntBase
            }
            FComboBox {
                implicitWidth: 100
                model: page.watch ? page.watch.regions : []
                currentIndex: page.watch ? page.watch.regionIndex : 0
                onActivated: if (page.watch)
                    page.watch.setRegionIndex(currentIndex)
            }

            Text {
                text: qsTr("备注:")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntBase
            }
            FTextField {
                id: noteInput
                Layout.preferredWidth: 150
                placeholderText: qsTr("可选")
                onTextChanged: if (page.watch)
                    page.watch.setNote(text)
            }

            FButton {
                text: qsTr("添加关注")
                primary: true
                onClicked: {
                    if (page.watch && !page.watch.add())
                        page.hint = qsTr("请先搜索并选择一个物品")
                }
            }

            Item {
                Layout.fillWidth: true
            }
        }

        Text {
            Layout.fillWidth: true
            Layout.leftMargin: 2 * page.pad
            Layout.rightMargin: 2 * page.pad
            text: page.hint
            visible: page.hint !== ""
            color: Theme.accentOrange
            font.family: Theme.fontFamily
            font.pixelSize: page.fntSmall
        }

        // ═══════════════════════════════════════════════════════
        //  2. 左列表 + 右详情（窄栏可拖拽）
        // ═══════════════════════════════════════════════════════

        SplitView {
            id: split
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.leftMargin: 2 * page.pad
            Layout.rightMargin: 2 * page.pad
            orientation: Qt.Horizontal

            // 3px 分隔条（Controls 2 的 SplitView 没有 handleWidth 属性，只能这样给 handle 定宽）
            handle: Rectangle {
                implicitWidth: 3
                implicitHeight: 3
                color: Theme.border
            }

            // ── 左：关注列表 ────────────────────────────────────
            Rectangle {
                objectName: "watchListPane"
                SplitView.preferredWidth: 240
                SplitView.minimumWidth: 220
                SplitView.maximumWidth: 260
                color: Theme.bgSurface
                radius: Theme.radius
                border.width: 1
                border.color: Theme.border

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 2
                    spacing: Theme.spacingXs

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.spacingXs

                        Text {
                            text: qsTr("排序:")
                            color: Theme.textSecondary
                            font.family: Theme.fontFamily
                            font.pixelSize: page.fntSmall
                        }
                        FComboBox {
                            Layout.fillWidth: true
                            model: page.watch ? page.watch.sortOptions : []
                            currentIndex: page.watch ? page.watch.sortIndex : 0
                            onActivated: if (page.watch)
                                page.watch.setSortIndex(currentIndex)
                        }
                    }

                    ListView {
                        id: watchList
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        // 行卡片由桥算好（`list_rows`），这里用 JS 数组模型 —— 与仓里其它
                        // ListView 同款（`modelData`），不走 QAbstractItemModel 的角色查找
                        model: page.watch ? page.watch.listRows : []
                        boundsBehavior: Flickable.StopAtBounds
                        reuseItems: true
                        spacing: 0

                        ScrollBar.vertical: ScrollBar {
                            policy: ScrollBar.AsNeeded
                        }

                        delegate: Item {
                            id: rowCard

                            required property int index
                            required property var modelData

                            readonly property bool isCurrent: page.currentRow === rowCard.index

                            width: ListView.view ? ListView.view.width : 0
                            height: page.listRowH

                            Rectangle {
                                anchors.fill: parent
                                // 价格变化/阈值触发是行底色（模型给的是带 alpha 的 #aarrggbb）
                                color: rowCard.isCurrent ? Theme.primary
                                                         : (rowCard.modelData.bg ? rowCard.modelData.bg : Theme.bgSurface)
                            }

                            Rectangle {
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.bottom: parent.bottom
                                height: 1
                                color: Theme.border
                            }

                            Image {
                                id: rowIcon
                                anchors.left: parent.left
                                anchors.leftMargin: 4
                                anchors.verticalCenter: parent.verticalCenter
                                width: Math.round(22 * Theme.fontScale)
                                height: width
                                source: rowCard.modelData.iconUrl
                                sourceSize.width: width
                                sourceSize.height: height
                                smooth: true
                                fillMode: Image.PreserveAspectFit
                            }

                            Text {
                                id: rowNameText
                                anchors.left: rowIcon.right
                                anchors.leftMargin: 6
                                anchors.right: parent.right
                                anchors.rightMargin: 6
                                anchors.top: parent.top
                                anchors.topMargin: Math.round(3 * Theme.fontScale)
                                text: rowCard.modelData.name
                                color: rowCard.isCurrent ? Theme.textOnPrimary : Theme.textPrimary
                                font.family: Theme.fontFamily
                                font.pixelSize: page.fntBase
                                elide: Text.ElideRight
                            }

                            Text {
                                anchors.left: rowNameText.left
                                anchors.right: parent.right
                                anchors.rightMargin: 6
                                anchors.top: rowNameText.bottom
                                text: qsTr("买 %1  卖 %2  %3").arg(rowCard.modelData.buyText).arg(rowCard.modelData.sellText).arg(rowCard.modelData.riseText)
                                color: rowCard.isCurrent ? Theme.textOnPrimary : Theme.textSecondary
                                font.family: "Consolas"
                                font.pixelSize: page.fntSmall
                                elide: Text.ElideRight
                            }
                        }

                        /* 行点击命中固定在按下那一刻（见 FTableClickArea 的说明）。
                         * `columnWidth` 不传 = 整行一格（窄列表只有一列）。 */
                        FTableClickArea {
                            objectName: "watchClickArea"
                            anchors.fill: parent
                            rowHeight: page.listRowH
                            rowSpacing: watchList.spacing

                            onRowClicked: function (row, _column) {
                                page.currentRow = row
                                if (page.watch)
                                    page.watch.selectRow(row)
                            }
                            onRowDoubleClicked: function (row, _column) {
                                // 窄列表里没有独立的买/卖阈值列，双击沿用原「第 7 列」的买价阈值；
                                // 卖价阈值走右键菜单或右侧详情面板的按钮（能力没丢）
                                page.currentRow = row
                                if (page.watch)
                                    page.watch.selectRow(row)
                                page.openThreshold(row, "buy")
                            }
                            onRowRightClicked: function (row, _column, x, y) {
                                page.currentRow = row
                                if (page.watch)
                                    page.watch.selectRow(row)
                                const p = mapToItem(page, x, y)
                                rowMenu.row = row
                                rowMenu.x = p.x
                                rowMenu.y = p.y
                                rowMenu.openSoon()
                            }
                        }
                    }
                }
            }

            // ── 右：选中物品详情 ────────────────────────────────
            Rectangle {
                objectName: "watchDetailFrame"
                SplitView.fillWidth: true
                SplitView.minimumWidth: 320
                color: Theme.bgSurface
                radius: Theme.radius
                border.width: 1
                border.color: Theme.border

                WatchlistDetailPane {
                    id: detailPane
                    anchors.fill: parent
                    anchors.margins: 2
                    watch: page.watch

                    onThresholdRequested: function (kind) {
                        page.openThreshold(page.currentRow, kind)
                    }
                }
            }
        }

        // ═══════════════════════════════════════════════════════
        //  3. 底部操作栏
        // ═══════════════════════════════════════════════════════

        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 2 * page.pad
            Layout.rightMargin: 2 * page.pad
            Layout.bottomMargin: 2 * page.pad
            spacing: page.pad

            FButton {
                text: qsTr("刷新价格")
                onClicked: if (page.watch)
                    page.watch.checkPriceChanges()
            }

            FButton {
                text: qsTr("删除选中")
                enabled: page.currentRow >= 0
                onClicked: confirmPopup.open()
            }

            Item {
                Layout.fillWidth: true
            }

            Text {
                text: page.watch ? page.watch.countText : ""
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntBase
            }
        }
    }

    Timer {
        interval: 2500
        running: page.hint !== ""
        onTriggered: page.hint = ""
    }

    // ═══════════════════════════════════════════════════════════
    //  候选列表（贴在搜索框下方）
    // ═══════════════════════════════════════════════════════════

    Popup {
        id: suggestPopup
        objectName: "suggestPopup"
        // 以输入框为父项：位置由 Qt 在 open 时换算（不用 mapToItem，见阶段 2 的同类修复）
        parent: searchInput
        x: 0
        y: searchInput.height + 2
        width: Math.max(searchInput.width, 320)
        padding: 2
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        visible: page.watch && page.watch.suggestions.length > 0

        background: Rectangle {
            color: Theme.bgElevated
            border.color: Theme.border
            border.width: 1
            radius: Theme.radius
        }

        contentItem: ListView {
            clip: true
            implicitHeight: Math.min(220, contentHeight)
            model: page.watch ? page.watch.suggestions : []
            ScrollIndicator.vertical: ScrollIndicator {}

            delegate: ItemDelegate {
                id: suggestRow
                required property int index
                required property var modelData
                width: ListView.view.width
                implicitHeight: 28

                contentItem: Text {
                    leftPadding: Theme.spacingSm
                    rightPadding: Theme.spacingSm
                    verticalAlignment: Text.AlignVCenter
                    text: String(suggestRow.modelData.text)
                    color: Theme.textPrimary
                    font.family: Theme.fontFamily
                    font.pixelSize: page.fntBase
                    elide: Text.ElideRight
                }

                background: Rectangle {
                    radius: Theme.radiusSmall
                    color: suggestRow.highlighted ? Theme.bgHover : "transparent"
                }

                onClicked: {
                    if (page.watch)
                        page.watch.pickSuggestion(suggestRow.index)
                    searchInput.forceActiveFocus()
                }
            }
        }
    }

    // ═══════════════════════════════════════════════════════════
    //  行右键菜单
    // ═══════════════════════════════════════════════════════════

    FMenu {
        id: rowMenu
        objectName: "rowMenu"
        property int row: -1

        FMenuItem {
            text: qsTr("设置买价阈值")
            onTriggered: page.openThreshold(rowMenu.row, "buy")
        }
        FMenuItem {
            text: qsTr("设置卖价阈值")
            onTriggered: page.openThreshold(rowMenu.row, "sell")
        }
        FMenuSeparator {}
        FMenuItem {
            text: qsTr("删除")
            onTriggered: {
                page.currentRow = rowMenu.row
                confirmPopup.open()
            }
        }
    }

    // ═══════════════════════════════════════════════════════════
    //  阈值设置（替代原版内联 QDialog）
    // ═══════════════════════════════════════════════════════════

    Popup {
        id: thresholdPopup
        objectName: "thresholdPopup"
        anchors.centerIn: Overlay.overlay
        width: 320
        padding: page.pad
        modal: true
        closePolicy: Popup.CloseOnEscape
        property string title: ""
        property string hint: ""

        background: Rectangle {
            color: Theme.bgElevated
            border.color: Theme.border
            border.width: 1
            radius: Theme.radius
            // 与 FCard 同款：MultiEffect 的阴影（shadowBlur 是 0..1 归一化值，不是像素）
            layer.enabled: true
            layer.effect: MultiEffect {
                shadowEnabled: true
                shadowBlur: Theme.controlBlur(2)
                shadowVerticalOffset: Theme.controlOffset(2)
                shadowColor: Qt.rgba(0, 0, 0, Theme.controlAlpha(2))
                autoPaddingEnabled: true
            }
        }

        contentItem: ColumnLayout {
            spacing: page.pad

            Text {
                Layout.fillWidth: true
                text: thresholdPopup.title
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(14 * Theme.fontScale)
                font.bold: true
            }

            Text {
                Layout.fillWidth: true
                text: thresholdPopup.hint
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntSmall
                wrapMode: Text.WordWrap
            }

            FDoubleSpinBox {
                id: thresholdInput
                Layout.fillWidth: true
                from: 0
                to: 999999999
                decimals: 2
                value: 0
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: page.pad

                Item {
                    Layout.fillWidth: true
                }
                FButton {
                    text: qsTr("取消")
                    onClicked: thresholdPopup.close()
                }
                FButton {
                    text: qsTr("确定")
                    primary: true
                    onClicked: {
                        if (page.watch)
                            page.watch.setThreshold(page.thresholdRow, page.thresholdKind, thresholdInput.value)
                        thresholdPopup.close()
                    }
                }
            }
        }
    }

    // ═══════════════════════════════════════════════════════════
    //  删除确认
    // ═══════════════════════════════════════════════════════════

    Popup {
        id: confirmPopup
        objectName: "confirmPopup"
        anchors.centerIn: Overlay.overlay
        width: 300
        padding: page.pad
        modal: true
        closePolicy: Popup.CloseOnEscape

        background: Rectangle {
            color: Theme.bgElevated
            border.color: Theme.border
            border.width: 1
            radius: Theme.radius
        }

        contentItem: ColumnLayout {
            spacing: page.pad

            Text {
                Layout.fillWidth: true
                text: qsTr("确定删除这一项关注?")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(14 * Theme.fontScale)
                wrapMode: Text.WordWrap
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: page.pad

                Item {
                    Layout.fillWidth: true
                }
                FButton {
                    text: qsTr("取消")
                    onClicked: confirmPopup.close()
                }
                FButton {
                    text: qsTr("删除")
                    /* **不**用 `primary`：`primary` 在本项目里是「推荐执行的动作」，
                       破坏性动作标成主色会误导。全仓唯一的成体系危险确认
                       （`HangarSettingsDialog` 的删除确认条）就是普通按钮 + 橙色警示。 */
                    onClicked: {
                        if (page.watch && page.currentRow >= 0)
                            page.watch.removeRow(page.currentRow)
                        page.currentRow = -1
                        confirmPopup.close()
                    }
                }
            }
        }
    }
}
