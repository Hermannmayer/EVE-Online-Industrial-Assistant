import QtQuick
import QtQuick.Controls
import QtQuick.Effects
import QtQuick.Layouts
import "../components"

/* 价格监控页 —— 阶段 3。
 *
 * 对照 Widgets 版 `ui_pyside6/views/watchlist_view.py`：
 *   顶部「搜索物品 + 区域 + 备注 + 添加关注」、中部 10 列关注表、
 *   底部「刷新价格 / 删除选中 / 计数」，行右键菜单与双击设置阈值。
 *
 * **业务动作一律不在这里实现**：每次交互都调 `watch.<方法>`，
 * 由 `ui_qml/bridge/watchlist_bridge.py` 转给 `services.watchlist_manager`。
 *
 * 与 Widgets 版的两处差异（有意）：
 *   1. 阈值设置从内联 `QDialog` 改成这里的小弹层（阶段 4 少一个对话框）；
 *   2. 删除只作用于**当前行** —— 原版的多选只被「删除选中」用到，
 *      而 QML `TableView` 的内建多选在 Qt 6.11 上不工作（见 PlanTableBridge 的说明），
 *      为它单独实现一套选中模型不划算。
 */
Item {
    id: page

    /* 监控桥，由 `PageHost` 以 context property `bridge` 注入。
     * 别名不与 context property 同名（同名声明会遮蔽它，恒为 null 且无报错）。 */
    readonly property var watch: typeof bridge !== "undefined" ? bridge : null

    readonly property int fntBase: Math.round(12 * Theme.fontScale)
    readonly property int fntSmall: Math.round(11 * Theme.fontScale)
    readonly property int rowH: Math.max(26, Math.round(13 * Theme.fontScale) + 13)
    readonly property int headerH: Math.max(26, fntSmall + 15)
    readonly property int pad: Theme.spacingSm

    //: 当前行（右键菜单 / 删除 / 阈值编辑都作用于它）
    property int currentRow: -1
    //: 阈值弹层的目标
    property int thresholdRow: -1
    property string thresholdKind: "buy"

    // 整页不透明底（宿主是透明清屏的 QQuickWidget，见 IndustryPage 的同款说明）
    Rectangle {
        anchors.fill: parent
        color: Theme.bgDark
    }

    /* 列宽：provider 与点击区必须同口径 —— 两处各算一次会错位。 */
    function colWidth(col) {
        const cols = page.watch ? page.watch.columns : []
        if (col >= cols.length)
            return 0
        // 最后一列（备注）吃满剩余空间，对齐原版的 Stretch
        if (col === cols.length - 1) {
            let used = 0
            for (let i = 0; i < cols.length - 1; ++i)
                used += cols[i].width
            return Math.max(80, tableView.width - used)
        }
        return cols[col].width
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
        //  2. 关注列表
        // ═══════════════════════════════════════════════════════

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.leftMargin: 2 * page.pad
            Layout.rightMargin: 2 * page.pad

            Rectangle {
                anchors.fill: parent
                color: Theme.bgSurface
                radius: Theme.radius
                border.width: 1
                border.color: Theme.border
            }

            HorizontalHeaderView {
                id: headerView
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                height: page.headerH
                syncView: tableView
                clip: true
                // 标题由 delegate 自己取；这个角色没人读，但必须真实存在（Qt 默认 "display" 不在模型里）
                textRole: "text"

                delegate: Item {
                    id: hcell
                    required property int index
                    implicitHeight: page.headerH

                    readonly property var meta: (page.watch && page.watch.columns.length > hcell.index)
                                                 ? page.watch.columns[hcell.index] : null

                    Rectangle {
                        anchors.fill: parent
                        color: Theme.bgSurface

                        Rectangle {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            height: 1
                            color: Theme.border
                        }
                        Rectangle {
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.bottom: parent.bottom
                            width: 1
                            color: Theme.border
                        }
                    }

                    Text {
                        anchors.fill: parent
                        anchors.leftMargin: 6
                        anchors.rightMargin: 6
                        verticalAlignment: Text.AlignVCenter
                        horizontalAlignment: hcell.index >= 4 && hcell.index <= 8 ? Text.AlignRight : Text.AlignLeft
                        text: hcell.meta ? hcell.meta.title : ""
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: page.fntSmall
                        elide: Text.ElideRight
                    }
                }
            }

            TableView {
                id: tableView
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: headerView.bottom
                anchors.bottom: parent.bottom

                clip: true
                boundsBehavior: Flickable.StopAtBounds
                model: page.watch ? page.watch.model : null
                // 内建选中在 Qt 6.11 上不工作（详见 PlanTableBridge 的说明），
                // 这里只需要「当前行」，高亮由 delegate 读 page.currentRow 自己画
                selectionBehavior: TableView.SelectionDisabled
                reuseItems: true
                rowHeightProvider: function (row) { return page.rowH }
                columnWidthProvider: function (col) { return page.colWidth(col) }

                ScrollBar.vertical: ScrollBar {
                    policy: ScrollBar.AsNeeded
                }
                ScrollBar.horizontal: ScrollBar {
                    policy: ScrollBar.AsNeeded
                }

                delegate: Item {
                    id: cell

                    required property int row
                    required property int column
                    required property bool selected
                    required property var model

                    readonly property bool isCurrent: page.currentRow === row
                    readonly property var colMeta: (page.watch && page.watch.columns.length > cell.column)
                                                  ? page.watch.columns[cell.column] : null

                    implicitWidth: cell.colMeta ? cell.colMeta.width : 100
                    implicitHeight: page.rowH

                    Rectangle {
                        anchors.fill: parent
                        // 价格变化/阈值触发的底色带 alpha，直接叠在偶数行底色上
                        color: cell.isCurrent ? Theme.primary : (cell.model.bg || Theme.bgSurface)
                    }

                    Rectangle {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        height: 1
                        color: Theme.border
                    }

                    Image {
                        visible: cell.column === 0
                        anchors.centerIn: parent
                        width: Math.round(22 * Theme.fontScale)
                        height: width
                        source: cell.model.iconUrl
                        sourceSize.width: width
                        sourceSize.height: height
                        smooth: true
                        fillMode: Image.PreserveAspectFit
                    }

                    Text {
                        visible: cell.column !== 0
                        anchors.fill: parent
                        anchors.leftMargin: Math.round(6 * Theme.fontScale)
                        anchors.rightMargin: Math.round(6 * Theme.fontScale)
                        verticalAlignment: Text.AlignVCenter
                        horizontalAlignment: cell.model.alignRight ? Text.AlignRight : Text.AlignLeft
                        text: cell.model.text
                        color: cell.isCurrent ? Theme.textOnPrimary : (cell.model.fg || Theme.textPrimary)
                        font.family: cell.model.mono ? "Consolas" : Theme.fontFamily
                        font.pixelSize: page.fntBase
                        elide: Text.ElideRight
                    }

                    HoverHandler {
                        cursorShape: Qt.PointingHandCursor
                    }

                }

                // 行点击命中固定在按下那一刻（见 FTableClickArea 的说明）
                FTableClickArea {
                    objectName: "watchClickArea"
                    anchors.fill: parent
                    rowHeight: page.rowH
                    columnWidth: page.colWidth

                    onRowClicked: function (row, _column) {
                        page.currentRow = row
                    }
                    onRowDoubleClicked: function (row, column) {
                        page.currentRow = row
                        if (column === 7)
                            page.openThreshold(row, "buy")
                        else if (column === 8)
                            page.openThreshold(row, "sell")
                    }
                    onRowRightClicked: function (row, _column, x, y) {
                        page.currentRow = row
                        const p = mapToItem(page, x, y)
                        rowMenu.row = row
                        rowMenu.x = p.x
                        rowMenu.y = p.y
                        rowMenu.openSoon()
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

    //: 顶部提示（添加失败等），短暂显示
    property string hint: ""
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
                    primary: true
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
