import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 合同市场页 —— 阶段 3。
 *
 * 对照 Widgets 版 `ui_pyside6/views/contract_view.py`：
 *   工具栏（区域 / 类型 / 刷新 / 计数）+ 过滤栏（物品名 / 价格区间 / 买卖）
 *   + 上下分栏（上：合同列表 10 列；下：选中合同的物品 8 列）。
 *
 * **业务动作一律不在这里实现**：每次交互都调 `contract.<方法>`，
 * 由 `ui_qml/bridge/contract_bridge.py` 转给既有的 worker / 模型。
 *
 * 过滤走 `ContractFilterProxy`（`QSortFilterProxyModel` 会转发源模型的 `roleNames()`，
 * 所以这里直接把**代理**当 model 用），过滤规则一份都没重写。
 */

Item {
    id: page

    /* 合同桥，由 `PageHost` 以 context property `bridge` 注入。
     * 别名不与 context property 同名（同名声明会遮蔽它，恒为 null 且无报错）。 */
    readonly property var contract: typeof bridge !== "undefined" ? bridge : null

    readonly property int fntBase: Math.round(12 * Theme.fontScale)
    readonly property int fntSmall: Math.round(11 * Theme.fontScale)
    readonly property int rowH: Math.max(24, Math.round(13 * Theme.fontScale) + 11)
    readonly property int headerH: Math.max(24, fntSmall + 13)
    readonly property int gap: Theme.spacingSm

    //: 当前合同行（代理行号；右键菜单与物品详情都作用于它）
    property int currentRow: -1

    // 整页不透明底（宿主是透明清屏的 QQuickWidget，见 IndustryPage 的同款说明）
    Rectangle {
        anchors.fill: parent
        color: Theme.bgDark
    }

    /* 两张表共用同一个 delegate 形状：文本 + 可选取色 + 斑马纹 + 单击/右键。
     * `model` 由 TableView 按行给下来。 */
    component TableCell: Item {
        id: tcell
        required property int row
        required property int column
        required property var model

        implicitHeight: page.rowH

        readonly property bool isCurrent: page.currentRow === row && tcell.isContractRow
        //: 只有上表参与「当前行」高亮与右键菜单
        property bool isContractRow: false

        Rectangle {
            anchors.fill: parent
            color: tcell.isCurrent
                   ? Theme.primary
                   : (tcell.model.bg !== undefined && tcell.model.bg ? tcell.model.bg : Theme.bgSurface)
        }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 1
            color: Theme.border
        }

        Text {
            anchors.fill: parent
            anchors.leftMargin: Math.round(6 * Theme.fontScale)
            anchors.rightMargin: Math.round(6 * Theme.fontScale)
            verticalAlignment: Text.AlignVCenter
            horizontalAlignment: tcell.model.alignRight ? Text.AlignRight : Text.AlignLeft
            text: tcell.model.text !== undefined ? tcell.model.text : ""
            color: tcell.isCurrent ? Theme.textOnPrimary : (tcell.model.fg ? tcell.model.fg : Theme.textPrimary)
            font.family: (tcell.model.mono === true) ? "Consolas" : Theme.fontFamily
            font.pixelSize: page.fntBase
            elide: Text.ElideRight
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // ═══════════════════════════════════════════════════════
        //  1. 工具栏
        // ═══════════════════════════════════════════════════════

        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 2 * page.gap
            Layout.rightMargin: 2 * page.gap
            Layout.topMargin: page.gap
            Layout.bottomMargin: page.gap
            spacing: page.gap

            Text {
                text: qsTr("区域:")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntBase
            }
            FComboBox {
                implicitWidth: 110
                model: page.contract ? page.contract.regions : []
                currentIndex: page.contract ? page.contract.regionIndex : 0
                onActivated: if (page.contract)
                    page.contract.setRegionIndex(currentIndex)
            }

            Text {
                text: qsTr("类型:")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntBase
            }
            FComboBox {
                implicitWidth: 110
                model: page.contract ? page.contract.types : []
                currentIndex: page.contract ? page.contract.typeIndex : 0
                onActivated: if (page.contract)
                    page.contract.setTypeIndex(currentIndex)
            }

            Item {
                Layout.fillWidth: true
            }

            FButton {
                text: qsTr("刷新合同数据")
                onClicked: if (page.contract)
                    page.contract.refresh()
            }

            Text {
                text: page.contract ? page.contract.countText : ""
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntBase
            }
        }

        // ═══════════════════════════════════════════════════════
        //  2. 过滤栏
        // ═══════════════════════════════════════════════════════

        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 2 * page.gap
            Layout.rightMargin: 2 * page.gap
            Layout.bottomMargin: page.gap
            spacing: page.gap

            FTextField {
                id: searchInput
                Layout.preferredWidth: 220
                placeholderText: qsTr("物品名搜索…")
                onTextChanged: if (page.contract)
                    page.contract.setSearchText(text)
            }

            Text {
                text: qsTr("价格:")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntBase
            }
            FDoubleSpinBox {
                implicitWidth: 140
                from: 0
                to: 1e12
                decimals: 0
                value: page.contract ? page.contract.priceMin : 0
                onValueModified: if (page.contract)
                    page.contract.setPriceMin(value)
            }
            Text {
                text: "~"
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntBase
            }
            FDoubleSpinBox {
                implicitWidth: 140
                from: 0
                to: 1e12
                decimals: 0
                value: page.contract ? page.contract.priceMax : 0
                onValueModified: if (page.contract)
                    page.contract.setPriceMax(value)
            }

            Text {
                text: qsTr("买卖:")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntBase
            }
            FComboBox {
                implicitWidth: 100
                model: page.contract ? page.contract.buySellOptions : []
                currentIndex: page.contract ? page.contract.buySellIndex : 0
                onActivated: if (page.contract)
                    page.contract.setBuySellIndex(currentIndex)
            }

            Item {
                Layout.fillWidth: true
            }
        }

        // ═══════════════════════════════════════════════════════
        //  3. 进度条
        // ═══════════════════════════════════════════════════════

        Rectangle {
            Layout.fillWidth: true
            height: 3
            visible: page.contract ? page.contract.busy : false
            color: Theme.bgSurfaceLight

            Rectangle {
                id: progressBlob
                width: Math.max(40, parent.width * 0.3)
                height: parent.height
                color: Theme.primary

                NumberAnimation on x {
                    from: -progressBlob.width
                    to: progressBlob.parent.width
                    duration: 900
                    loops: Animation.Infinite
                    running: progressBlob.parent.visible
                }
            }
        }

        // ═══════════════════════════════════════════════════════
        //  4. 上下分栏
        // ═══════════════════════════════════════════════════════

        SplitView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: Qt.Vertical

            handle: Rectangle {
                implicitHeight: 4
                color: SplitHandle.pressed || SplitHandle.hovered ? Theme.primary : Theme.border
            }

            // ── 上：合同列表 ──
            Item {
                SplitView.preferredHeight: Math.round(page.height * 0.6)
                SplitView.minimumHeight: 120

                Rectangle {
                    anchors.fill: parent
                    color: Theme.bgSurface
                }

                HorizontalHeaderView {
                    id: contractHeader
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    height: page.headerH
                    syncView: contractTable
                    clip: true
                    textRole: "text"

                    delegate: Item {
                        id: chead
                        required property int index
                        implicitHeight: page.headerH

                        readonly property var meta: (page.contract && page.contract.contractColumns.length > chead.index)
                                                     ? page.contract.contractColumns[chead.index] : null

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
                            horizontalAlignment: [0, 3, 4, 5, 6].indexOf(chead.index) >= 0 ? Text.AlignRight : Text.AlignLeft
                            text: chead.meta ? chead.meta.title : ""
                            color: Theme.textPrimary
                            font.family: Theme.fontFamily
                            font.pixelSize: page.fntSmall
                            elide: Text.ElideRight
                        }
                    }
                }

                TableView {
                    id: contractTable
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: contractHeader.bottom
                    anchors.bottom: parent.bottom

                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    model: page.contract ? page.contract.model : null
                    selectionBehavior: TableView.SelectionDisabled
                    reuseItems: true
                    rowHeightProvider: function (row) { return page.rowH }
                    columnWidthProvider: function (col) {
                        const cols = page.contract ? page.contract.contractColumns : []
                        return col < cols.length ? cols[col].width : 100
                    }

                    ScrollBar.vertical: ScrollBar {
                        policy: ScrollBar.AsNeeded
                    }
                    ScrollBar.horizontal: ScrollBar {
                        policy: ScrollBar.AsNeeded
                    }

                    delegate: TableCell {
                        isContractRow: true
                        implicitWidth: {
                            const cols = page.contract ? page.contract.contractColumns : []
                            return column < cols.length ? cols[column].width : 100
                        }

                        TapHandler {
                            acceptedButtons: Qt.LeftButton
                            gesturePolicy: TapHandler.ReleaseWithinBounds
                            onSingleTapped: {
                                page.currentRow = row
                                if (page.contract)
                                    page.contract.selectContract(row)
                            }
                            onDoubleTapped: {
                                page.currentRow = row
                                if (page.contract)
                                    page.contract.showDetail(row)
                            }
                        }

                        TapHandler {
                            acceptedButtons: Qt.RightButton
                            gesturePolicy: TapHandler.ReleaseWithinBounds
                            onSingleTapped: function (eventPoint) {
                                page.currentRow = row
                                const p = parent.mapToItem(page, eventPoint.position.x, eventPoint.position.y)
                                rowMenu.row = row
                                rowMenu.x = p.x
                                rowMenu.y = p.y
                                rowMenu.open()
                            }
                        }
                    }
                }
            }

            // ── 下：合同物品 ──
            Item {
                SplitView.minimumHeight: 100

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: page.headerH
                        color: Theme.bgSurface

                        Text {
                            anchors.left: parent.left
                            anchors.leftMargin: page.gap
                            anchors.verticalCenter: parent.verticalCenter
                            text: qsTr("合同物品（点击上方合同查看）")
                            color: Theme.textSecondary
                            font.family: Theme.fontFamily
                            font.pixelSize: page.fntBase
                            font.bold: true
                        }
                    }

                    Item {
                        Layout.fillWidth: true
                        Layout.fillHeight: true

                        HorizontalHeaderView {
                            id: itemHeader
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            height: page.headerH
                            syncView: itemTable
                            clip: true
                            textRole: "text"

                            delegate: Item {
                                id: ihead
                                required property int index
                                implicitHeight: page.headerH

                                readonly property var meta: (page.contract && page.contract.itemColumns.length > ihead.index)
                                                             ? page.contract.itemColumns[ihead.index] : null

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
                                }

                                Text {
                                    anchors.fill: parent
                                    anchors.leftMargin: 6
                                    anchors.rightMargin: 6
                                    verticalAlignment: Text.AlignVCenter
                                    horizontalAlignment: ([0, 3, 6, 7].indexOf(ihead.index) >= 0)
                                                         ? Text.AlignRight : Text.AlignLeft
                                    text: ihead.meta ? ihead.meta.title : ""
                                    color: Theme.textPrimary
                                    font.family: Theme.fontFamily
                                    font.pixelSize: page.fntSmall
                                    elide: Text.ElideRight
                                }
                            }
                        }

                        TableView {
                            id: itemTable
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: itemHeader.bottom
                            anchors.bottom: parent.bottom

                            clip: true
                            boundsBehavior: Flickable.StopAtBounds
                            model: page.contract ? page.contract.itemModel : null
                            selectionBehavior: TableView.SelectionDisabled
                            reuseItems: true
                            rowHeightProvider: function (row) { return page.rowH }
                            columnWidthProvider: function (col) {
                                const cols = page.contract ? page.contract.itemColumns : []
                                return col < cols.length ? cols[col].width : 100
                            }

                            ScrollBar.vertical: ScrollBar {
                                policy: ScrollBar.AsNeeded
                            }

                            delegate: TableCell {
                                implicitWidth: {
                                    const cols = page.contract ? page.contract.itemColumns : []
                                    return column < cols.length ? cols[column].width : 100
                                }
                            }
                        }
                    }
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
            text: qsTr("复制合同 ID")
            onTriggered: page.contract.copyContractId(rowMenu.row)
        }
        FMenuItem {
            text: qsTr("复制物品列表")
            onTriggered: page.contract.copyItems()
        }
        FMenuSeparator {}
        FMenuItem {
            text: qsTr("在新窗口查看")
            onTriggered: page.contract.showDetail(rowMenu.row)
        }
        FMenuSeparator {}
        FMenuItem {
            text: qsTr("加入关注列表")
            onTriggered: page.contract.addItemsToWatchlist()
        }
        FMenuItem {
            text: qsTr("查看物品详情")
            onTriggered: {
                const summary = page.contract.itemSummary()
                if (summary === "")
                    page.contract.copyItems()  // 没物品时走同一提示路径（「请先点击合同加载物品列表」）
                itemDetailPopup.text = summary
                itemDetailPopup.open()
            }
        }
    }

    //: 「查看物品详情」的展示（替代 Widgets 版的 QMessageBox.information）
    Popup {
        id: itemDetailPopup
        objectName: "itemDetailPopup"
        anchors.centerIn: Overlay.overlay
        width: 420
        height: Math.min(420, contentItem.implicitHeight + 2 * 12)
        padding: 12
        modal: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        property string text: ""

        background: Rectangle {
            color: Theme.bgElevated
            border.color: Theme.border
            border.width: 1
            radius: Theme.radius
        }

        contentItem: ColumnLayout {
            spacing: 8

            Text {
                Layout.fillWidth: true
                text: qsTr("合同物品详情")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(14 * Theme.fontScale)
                font.bold: true
            }

            Flickable {
                Layout.fillWidth: true
                Layout.fillHeight: true
                contentHeight: detailText.implicitHeight
                clip: true

                Text {
                    id: detailText
                    width: parent.width
                    text: itemDetailPopup.text
                    color: Theme.textPrimary
                    font.family: Theme.fontFamily
                    font.pixelSize: page.fntBase
                    wrapMode: Text.WordWrap
                }
            }

            FButton {
                Layout.alignment: Qt.AlignRight
                text: qsTr("关闭")
                primary: true
                onClicked: itemDetailPopup.close()
            }
        }
    }
}
