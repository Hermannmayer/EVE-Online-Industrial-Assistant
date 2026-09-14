import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 贸易页 —— 阶段 3。
 *
 * 对照 Widgets 版 `ui_pyside6/views/trade_view.py`：两个 Tab
 *   1) 跨区域价差：搜索 → 四大贸易中心价格对比表 → 贸易评分 + 最优路线
 *   2) 运输利润：搜索 → 目的地/数量/运输模式/跳跃数 → 运费后净利润
 *
 * **业务动作一律不在这里实现**：每次交互都调 `trade.<方法>`，
 * 由 `ui_qml/bridge/trade_bridge.py` 转给既有的 worker。
 *
 * 结果卡片用 `FFieldList` 画 —— 桥给出的就是 `{label, value, color, strong}` 列表，
 * 「哪一项标红加粗」这类规则留在 Python 侧（与 Widgets 版逐项对齐）。
 */
Item {
    id: page

    /* 贸易桥，由 `PageHost` 以 context property `bridge` 注入。
     * 别名不与 context property 同名（同名声明会遮蔽它，恒为 null 且无报错）。 */
    readonly property var trade: typeof bridge !== "undefined" ? bridge : null

    readonly property int fntBase: Math.round(12 * Theme.fontScale)
    readonly property int fntSmall: Math.round(11 * Theme.fontScale)
    readonly property int pad: Theme.spacingSm

    // 整页不透明底（宿主是透明清屏的 QQuickWidget，见 IndustryPage 的同款说明）
    Rectangle {
        anchors.fill: parent
        color: Theme.bgDark
    }

    /* 候选列表：两个 Tab 各一个输入框，共用同一个内联组件定义。
     * 位置以输入框为父项（**不用 mapToItem**：函数调用不被绑定依赖追踪）。 */
    component SuggestPopup: Popup {
        id: suggest
        objectName: "suggestPopup"
        property var items: []
        property var pickHandler: null

        x: 0
        y: 0
        width: 320
        padding: 2
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        visible: items.length > 0

        background: Rectangle {
            color: Theme.bgElevated
            border.color: Theme.border
            border.width: 1
            radius: Theme.radius
        }

        contentItem: ListView {
            clip: true
            implicitHeight: Math.min(220, contentHeight)
            model: suggest.items
            ScrollIndicator.vertical: ScrollIndicator {}

            delegate: ItemDelegate {
                id: row
                required property int index
                required property var modelData
                width: ListView.view.width
                implicitHeight: 28

                contentItem: Text {
                    leftPadding: Theme.spacingSm
                    rightPadding: Theme.spacingSm
                    verticalAlignment: Text.AlignVCenter
                    text: String(row.modelData.text)
                    color: Theme.textPrimary
                    font.family: Theme.fontFamily
                    font.pixelSize: page.fntBase
                    elide: Text.ElideRight
                }

                background: Rectangle {
                    radius: Theme.radiusSmall
                    color: row.highlighted ? Theme.bgHover : "transparent"
                }

                onClicked: if (suggest.pickHandler)
                    suggest.pickHandler(row.index)
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        TabBar {
            id: tabBar
            Layout.fillWidth: true

            TabButton {
                text: qsTr("跨区域价差")
            }
            TabButton {
                text: qsTr("运输利润")
            }
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: tabBar.currentIndex

            // ═══════════════════════════════════════════════════
            //  Tab 1：跨区域价差
            // ═══════════════════════════════════════════════════

            ColumnLayout {
                spacing: page.pad
                Layout.margins: page.pad

                RowLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: page.pad
                    Layout.rightMargin: page.pad
                    Layout.topMargin: page.pad
                    spacing: page.pad

                    FTextField {
                        id: searchInput
                        Layout.fillWidth: true
                        placeholderText: qsTr("搜索物品名称（如 渡鸦级）→ 查看跨区域价差 → 贸易评分")
                        onTextChanged: if (page.trade)
                            page.trade.onSearchChanged(text)
                        Keys.onEscapePressed: searchSuggest.close()
                    }

                    FButton {
                        text: qsTr("分析")
                        primary: true
                        onClicked: if (page.trade)
                            page.trade.analyze()
                    }
                }

                Text {
                    Layout.fillWidth: true
                    Layout.leftMargin: 2 * page.pad
                    Layout.rightMargin: 2 * page.pad
                    text: page.trade ? page.trade.previewText : ""
                    color: page.trade ? page.trade.previewColor : Theme.textSecondary
                    font.family: Theme.fontFamily
                    font.pixelSize: page.fntBase
                    wrapMode: Text.WordWrap
                }

                FSection {
                    Layout.leftMargin: page.pad
                    Layout.rightMargin: page.pad
                    title: qsTr("跨区域价格对比")

                    Item {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 150

                        HorizontalHeaderView {
                            id: hubHeader
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            height: Math.max(22, page.fntSmall + 10)
                            syncView: hubTable
                            clip: true
                            textRole: "text"

                            delegate: Item {
                                id: hubCell
                                required property int index
                                implicitHeight: hubHeader.height

                                readonly property var meta: (page.trade && page.trade.hubColumns.length > hubCell.index)
                                                             ? page.trade.hubColumns[hubCell.index] : null

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
                                    horizontalAlignment: hubCell.index === 0 ? Text.AlignLeft : Text.AlignRight
                                    text: hubCell.meta ? hubCell.meta.title : ""
                                    color: Theme.textSecondary
                                    font.family: Theme.fontFamily
                                    font.pixelSize: page.fntSmall
                                    elide: Text.ElideRight
                                }
                            }
                        }

                        TableView {
                            id: hubTable
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: hubHeader.bottom
                            anchors.bottom: parent.bottom

                            clip: true
                            boundsBehavior: Flickable.StopAtBounds
                            model: page.trade ? page.trade.hubModel : null
                            selectionBehavior: TableView.SelectionDisabled
                            reuseItems: true
                            rowHeightProvider: function (row) { return 24 }
                            columnWidthProvider: function (col) {
                                const cols = page.trade ? page.trade.hubColumns : []
                                return col < cols.length ? cols[col].width : 100
                            }

                            delegate: Item {
                                id: hubRow
                                required property int row
                                required property int column
                                required property var model

                                readonly property var colMeta: (page.trade && page.trade.hubColumns.length > hubRow.column)
                                                               ? page.trade.hubColumns[hubRow.column] : null

                                implicitWidth: hubRow.colMeta ? hubRow.colMeta.width : 100
                                implicitHeight: 24

                                Rectangle {
                                    anchors.fill: parent
                                    color: hubRow.row % 2 === 1 ? Theme.bgDark : Theme.bgSurface
                                }

                                Image {
                                    visible: hubRow.column === 0
                                    anchors.left: parent.left
                                    anchors.leftMargin: 4
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: 18
                                    height: 18
                                    source: hubRow.model.iconUrl
                                    sourceSize.width: width
                                    sourceSize.height: height
                                    smooth: true
                                    fillMode: Image.PreserveAspectFit
                                }

                                Text {
                                    anchors.fill: parent
                                    anchors.leftMargin: hubRow.column === 0 ? 26 : 6
                                    anchors.rightMargin: 6
                                    verticalAlignment: Text.AlignVCenter
                                    horizontalAlignment: hubRow.model.alignRight ? Text.AlignRight : Text.AlignLeft
                                    text: hubRow.model.text
                                    color: hubRow.model.fg || Theme.textPrimary
                                    font.family: Theme.fontFamily
                                    font.pixelSize: page.fntBase
                                    elide: Text.ElideRight
                                }
                            }
                        }
                    }

                    Text {
                        Layout.fillWidth: true
                        text: page.trade ? page.trade.hubStatus : ""
                        color: Theme.textSecondary
                        font.family: Theme.fontFamily
                        font.pixelSize: page.fntSmall
                    }
                }

                FSection {
                    Layout.leftMargin: page.pad
                    Layout.rightMargin: page.pad
                    visible: page.trade ? page.trade.scoreVisible : false
                    title: qsTr("贸易评分")

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: page.pad

                        Text {
                            text: qsTr("买入区域:")
                            color: Theme.textPrimary
                            font.family: Theme.fontFamily
                            font.pixelSize: page.fntBase
                        }
                        FComboBox {
                            implicitWidth: 110
                            model: page.trade ? page.trade.hubs : []
                            currentIndex: page.trade ? page.trade.buyHubIndex : 0
                            onActivated: if (page.trade)
                                page.trade.setBuyHubIndex(currentIndex)
                        }

                        Text {
                            text: qsTr("卖出区域:")
                            color: Theme.textPrimary
                            font.family: Theme.fontFamily
                            font.pixelSize: page.fntBase
                        }
                        FComboBox {
                            implicitWidth: 110
                            model: page.trade ? page.trade.hubs : []
                            currentIndex: page.trade ? page.trade.sellHubIndex : 0
                            onActivated: if (page.trade)
                                page.trade.setSellHubIndex(currentIndex)
                        }

                        Text {
                            text: qsTr("数量:")
                            color: Theme.textPrimary
                            font.family: Theme.fontFamily
                            font.pixelSize: page.fntBase
                        }
                        FSpinBox {
                            implicitWidth: 120
                            from: 1
                            to: 1000000
                            value: page.trade ? page.trade.quantity : 1
                            onValueModified: if (page.trade)
                                page.trade.setQuantity(value)
                        }

                        FButton {
                            text: qsTr("计算贸易评分")
                            onClicked: if (page.trade)
                                page.trade.computeScore()
                        }

                        Item {
                            Layout.fillWidth: true
                        }
                    }

                    FFieldList {
                        Layout.fillWidth: true
                        fields: page.trade ? page.trade.scoreFields : []
                    }
                }

                FSection {
                    Layout.leftMargin: page.pad
                    Layout.rightMargin: page.pad
                    Layout.bottomMargin: page.pad
                    visible: page.trade ? page.trade.pairVisible : false
                    title: qsTr("最优路线")

                    Text {
                        Layout.fillWidth: true
                        text: page.trade ? page.trade.pairText : ""
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: page.fntBase
                        wrapMode: Text.WordWrap
                    }
                }

                Item {
                    Layout.fillHeight: true
                }
            }

            // ═══════════════════════════════════════════════════
            //  Tab 2：运输利润
            // ═══════════════════════════════════════════════════

            ColumnLayout {
                spacing: page.pad
                Layout.margins: page.pad

                RowLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: page.pad
                    Layout.rightMargin: page.pad
                    Layout.topMargin: page.pad
                    spacing: page.pad

                    FTextField {
                        id: transportInput
                        Layout.fillWidth: true
                        placeholderText: qsTr("搜索物品名称 → 计算运费后净利润")
                        onTextChanged: if (page.trade)
                            page.trade.onTransportSearchChanged(text)
                        Keys.onEscapePressed: transportSuggest.close()
                    }

                    FButton {
                        text: qsTr("分析运输")
                        primary: true
                        onClicked: if (page.trade)
                            page.trade.analyzeTransport()
                    }
                }

                Text {
                    Layout.fillWidth: true
                    Layout.leftMargin: 2 * page.pad
                    Layout.rightMargin: 2 * page.pad
                    text: page.trade ? page.trade.transportPreview : ""
                    color: page.trade ? page.trade.transportPreviewColor : Theme.textSecondary
                    font.family: Theme.fontFamily
                    font.pixelSize: page.fntBase
                    wrapMode: Text.WordWrap
                }

                FSection {
                    Layout.leftMargin: page.pad
                    Layout.rightMargin: page.pad
                    title: qsTr("运输配置")

                    GridLayout {
                        Layout.fillWidth: true
                        columns: 6
                        columnSpacing: page.pad
                        rowSpacing: Theme.spacingXs

                        Text {
                            text: qsTr("买入区域:")
                            color: Theme.textPrimary
                            font.family: Theme.fontFamily
                            font.pixelSize: page.fntBase
                        }
                        FComboBox {
                            implicitWidth: 110
                            model: page.trade ? page.trade.hubs : []
                            currentIndex: page.trade ? page.trade.transportBuyHubIndex : 0
                            onActivated: if (page.trade)
                                page.trade.setTransportBuyHubIndex(currentIndex)
                        }

                        Text {
                            text: qsTr("卖出区域:")
                            color: Theme.textPrimary
                            font.family: Theme.fontFamily
                            font.pixelSize: page.fntBase
                        }
                        FComboBox {
                            implicitWidth: 110
                            model: page.trade ? page.trade.hubs : []
                            currentIndex: page.trade ? page.trade.transportSellHubIndex : 0
                            onActivated: if (page.trade)
                                page.trade.setTransportSellHubIndex(currentIndex)
                        }

                        Text {
                            text: qsTr("数量:")
                            color: Theme.textPrimary
                            font.family: Theme.fontFamily
                            font.pixelSize: page.fntBase
                        }
                        FSpinBox {
                            implicitWidth: 120
                            from: 1
                            to: 1000000
                            value: page.trade ? page.trade.transportQuantity : 100
                            onValueModified: if (page.trade)
                                page.trade.setTransportQuantity(value)
                        }

                        Text {
                            text: qsTr("运输模式:")
                            color: Theme.textPrimary
                            font.family: Theme.fontFamily
                            font.pixelSize: page.fntBase
                        }
                        FComboBox {
                            implicitWidth: 110
                            model: page.trade ? page.trade.modes : []
                            currentIndex: page.trade ? page.trade.transportModeIndex : 0
                            onActivated: if (page.trade)
                                page.trade.setTransportModeIndex(currentIndex)
                        }

                        Text {
                            text: (page.trade && page.trade.transportJumpsAuto)
                                  ? qsTr("跳跃数 (自动):") : qsTr("跳跃数:")
                            color: Theme.textPrimary
                            font.family: Theme.fontFamily
                            font.pixelSize: page.fntBase
                        }
                        FSpinBox {
                            implicitWidth: 120
                            from: 1
                            to: 500
                            value: page.trade ? page.trade.transportJumps : 72
                            onValueModified: if (page.trade)
                                page.trade.setTransportJumps(value)
                        }
                    }
                }

                FSection {
                    Layout.leftMargin: page.pad
                    Layout.rightMargin: page.pad
                    Layout.bottomMargin: page.pad
                    visible: page.trade ? page.trade.transportResultVisible : false
                    title: qsTr("运输利润分析")

                    FFieldList {
                        Layout.fillWidth: true
                        fields: page.trade ? page.trade.transportFields : []
                    }
                }

                Item {
                    Layout.fillHeight: true
                }
            }
        }
    }

    // 两个 Tab 的候选弹窗（挂在各自的输入框下面）
    SuggestPopup {
        id: searchSuggest
        parent: searchInput
        y: searchInput.height + 2
        width: Math.max(searchInput.width, 320)
        items: page.trade ? page.trade.results : []
        pickHandler: function (index) {
            page.trade.pickResult(index)
            searchInput.forceActiveFocus()
        }
    }

    SuggestPopup {
        id: transportSuggest
        parent: transportInput
        y: transportInput.height + 2
        width: Math.max(transportInput.width, 320)
        items: page.trade ? page.trade.transportResults : []
        pickHandler: function (index) {
            page.trade.pickTransportResult(index)
            transportInput.forceActiveFocus()
        }
    }
}
