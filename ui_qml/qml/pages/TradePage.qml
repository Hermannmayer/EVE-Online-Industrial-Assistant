import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 贸易页 —— A 贸易中心 → B 贸易中心的全品类价差排行。

 * 工具栏：从 [中心][买/卖] 到 [中心][买/卖] [⇄] [分类] [开始计算]
 * 主工作区：排行表（默认按每方利润倒序，点表头换列）
 * 页面状态栏：行数 + 两个中心的价格时间 + 购物车汇总
 * 页面功能按钮：「购物车」（打开置顶独立窗口）

 * **页面加载不查库、不拉取** —— 只有点「开始计算」才动作（用户明确要求）。
 * 业务全在 `ui_qml/bridge/trade_bridge.py`，这里只画与转发。
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

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // ═══════════════════════════════════════════════════
        //  页面工具栏
        // ═══════════════════════════════════════════════════
        // 外层 RowLayout 只为把「开始计算」顶到最右；筛选那一组用 **Flow** 承载，
        // 窗口收窄时它会自己折行、永不裁切（单行 RowLayout 会把最右边的控件切掉，
        // 采购窗那边踩过）。
        RowLayout {
            objectName: "tradeToolbar"
            Layout.fillWidth: true
            Layout.margins: page.pad
            spacing: page.pad

            Flow {
                objectName: "tradeFromTo"
                Layout.fillWidth: true
                spacing: page.pad

                Text {
                    text: qsTr("从")
                    color: Theme.textPrimary
                    font.family: Theme.fontFamily
                    font.pixelSize: page.fntBase
                    height: 32
                    verticalAlignment: Text.AlignVCenter
                }

                FComboBox {
                    objectName: "fromHubBox"
                    implicitWidth: 120
                    model: page.trade ? page.trade.hubs : []
                    currentIndex: page.trade ? page.trade.fromIndex : 0
                    onActivated: if (page.trade)
                        page.trade.setFromIndex(currentIndex)
                }

                FComboBox {
                    objectName: "fromSideBox"
                    implicitWidth: 90
                    model: page.trade ? page.trade.sideLabels : []
                    currentIndex: page.trade ? page.trade.fromSideIndex : 0
                    onActivated: if (page.trade)
                        page.trade.setFromSideIndex(currentIndex)
                }

                Text {
                    text: qsTr("到")
                    color: Theme.textPrimary
                    font.family: Theme.fontFamily
                    font.pixelSize: page.fntBase
                    height: 32
                    verticalAlignment: Text.AlignVCenter
                }

                FComboBox {
                    objectName: "toHubBox"
                    implicitWidth: 120
                    model: page.trade ? page.trade.hubs : []
                    currentIndex: page.trade ? page.trade.toIndex : 0
                    onActivated: if (page.trade)
                        page.trade.setToIndex(currentIndex)
                }

                FComboBox {
                    objectName: "toSideBox"
                    implicitWidth: 90
                    model: page.trade ? page.trade.sideLabels : []
                    currentIndex: page.trade ? page.trade.toSideIndex : 0
                    onActivated: if (page.trade)
                        page.trade.setToSideIndex(currentIndex)
                }

                FButton {
                    objectName: "swapButton"
                    compact: true
                    text: qsTr("⇄ 切换方向")
                    onClicked: if (page.trade)
                        page.trade.swapDirection()
                }
            }

            FButton {
                objectName: "analyzeButton"
                primary: true
                text: (page.trade && page.trade.busy) ? qsTr("计算中…") : qsTr("开始计算")
                enabled: page.trade ? !page.trade.busy : false
                onClicked: if (page.trade)
                    page.trade.analyze()
            }
        }

        // ── 筛选项（独立一行，对齐标注里的「筛选项：」）─────────
        // 用 Flow：窄窗口下自动折行，不会把最右边的控件切掉
        Flow {
            objectName: "tradeFilters"
            Layout.fillWidth: true
            Layout.leftMargin: page.pad
            Layout.rightMargin: page.pad
            spacing: page.pad

            Text {
                text: qsTr("筛选项：")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntBase
                height: 28
                verticalAlignment: Text.AlignVCenter
            }

            FComboBox {
                objectName: "categoryBox"
                implicitWidth: 160
                model: page.trade ? page.trade.categories.map(function (c) {
                    return c.name;
                }) : []
                currentIndex: page.trade ? page.trade.categoryIndex : 0
                onActivated: if (page.trade)
                    page.trade.setCategoryIndex(currentIndex)
            }

            FCheckBox {
                objectName: "profitableBox"
                text: qsTr("只看赚钱的")
                checked: page.trade ? page.trade.hideUnprofitable : false
                onToggled: if (page.trade)
                    page.trade.setHideUnprofitable(checked)
            }

            FComboBox {
                objectName: "liquidityBox"
                implicitWidth: 150
                model: page.trade ? page.trade.liquidityOptions : []
                currentIndex: page.trade ? page.trade.liquidityIndex : 0
                onActivated: if (page.trade)
                    page.trade.setLiquidityIndex(currentIndex)
            }

            Text {
                text: qsTr("（对手盘：两侧在所选价位的挂单量）")
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntSmall
                height: 28
                verticalAlignment: Text.AlignVCenter
            }
        }

        Text {
            objectName: "hintText"
            Layout.fillWidth: true
            Layout.leftMargin: 2 * page.pad
            Layout.rightMargin: 2 * page.pad
            text: page.trade ? page.trade.hintText : ""
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: page.fntSmall
            elide: Text.ElideRight
        }

        // ═══════════════════════════════════════════════════
        //  主工作区：排行表
        // ═══════════════════════════════════════════════════
        Item {
            objectName: "rankArea"
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.margins: page.pad

            HorizontalHeaderView {
                id: rankHeader
                objectName: "rankHeader"
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                height: Math.max(24, page.fntSmall + 12)
                syncView: rankTable
                clip: true
                /* ⚠️ `textRole` 必须是模型 `roleNames()` 里**真有**的角色。
                 * 写 Qt 保留的 `"display"` 会每帧刷一条
                 * 「The 'textRole' property contains a role that doesn't exist in the model」——
                 * `TradeRankQmlModel` 只登记了 `text` / `fg` / `iconUrl` … 那几个命名角色。 */
                textRole: "text"
                /* ⚠️ **不要给这里加 `model:`**。写上 `model: page.trade.columns` 会让本页
                 * 在装配期必崩（access violation，崩点落在 `registry.build_qml_page` 的
                 * `component.create`）：那份列表每次求值都是**新建**的 JS 数组+对象，
                 * 与 `syncView` 的同步机制撞在一起。
                 * 表头本来就从 `syncView` 取模型（列名走 `TradeRankQmlModel.headerData`），
                 * 宽度也由同步给出 —— 委托里只按 index 读一次列元数据。 */

                delegate: Item {
                    id: headCell
                    required property int index

                    readonly property var meta: (page.trade && page.trade.columns.length > headCell.index)
                                                ? page.trade.columns[headCell.index] : null
                    readonly property bool isSorted: page.trade ? page.trade.sortColumn === headCell.index : false

                    implicitHeight: rankHeader.height

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
                        horizontalAlignment: (headCell.index === 0 || headCell.index === 1 || headCell.index === 2)
                                             ? Text.AlignLeft : Text.AlignRight
                        text: {
                            var title = headCell.meta ? headCell.meta.title : "";
                            /* ⚠️ 这里**必须**同时挡住 `page.trade`，不能只信 `headCell.isSorted`。
                             *
                             * `isSorted` 是**派生**属性（`page.trade ? … : false`），自己带缓存。
                             * 只要它在某一轮算过 `true`，而此后 `page.trade` 变成 null 时绑定没
                             * 能及时重算（退出期拆场景就是这个窗口），下面那行就会对着 null 取
                             * `sortAscending`，日志刷
                             * `TradePage.qml:259: Cannot read property 'sortAscending' of null`
                             * —— 实测出现在关窗那一刻（其后紧跟 killTimer / QThread 告警）。
                             *
                             * 判断条件要**自足**：同一个绑定里直接验源头，不依赖另一个派生
                             * 属性的新鲜度。`page.trade` 为 null 时本就只该返回纯标题 —— 与
                             * `headCell.meta`（上一行，也是直接验 `page.trade`）同一个口径，
                             * 行为不变、箭头照常。 */
                            if (!page.trade || !headCell.isSorted)
                                return title;
                            return title + (page.trade.sortAscending ? " ▲" : " ▼");
                        }
                        color: headCell.isSorted ? Theme.textPrimary : Theme.textSecondary
                        font.family: Theme.fontFamily
                        font.pixelSize: page.fntSmall
                        elide: Text.ElideRight
                    }

                    MouseArea {
                        anchors.fill: parent
                        onClicked: if (page.trade)
                            page.trade.sortBy(headCell.index)
                    }
                }
            }

            TableView {
                id: rankTable
                objectName: "rankTable"
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: rankHeader.bottom
                anchors.bottom: parent.bottom

                clip: true
                boundsBehavior: Flickable.StopAtBounds
                model: page.trade ? page.trade.model : null
                selectionBehavior: TableView.SelectionDisabled
                // 1.2 万行量级，必须复用 delegate，否则光建项就卡死
                reuseItems: true
                rowHeightProvider: function (row) { return 26 }
                columnWidthProvider: function (col) {
                    const cols = page.trade ? page.trade.columns : [];
                    return col < cols.length ? cols[col].width : 100;
                }

                delegate: Item {
                    id: rankRow
                    required property int row
                    required property int column
                    required property var model

                    implicitWidth: 100
                    implicitHeight: 26

                    Rectangle {
                        anchors.fill: parent
                        color: rankRow.row % 2 === 1 ? Theme.bgDark : Theme.bgSurface
                    }

                    Image {
                        visible: rankRow.column === 0
                        anchors.left: parent.left
                        anchors.leftMargin: 4
                        anchors.verticalCenter: parent.verticalCenter
                        width: 20
                        height: 20
                        source: rankRow.model.iconUrl
                        sourceSize.width: width
                        sourceSize.height: height
                        smooth: true
                        fillMode: Image.PreserveAspectFit
                    }

                    Text {
                        anchors.fill: parent
                        anchors.leftMargin: rankRow.column === 0 ? 28 : 6
                        anchors.rightMargin: 6
                        verticalAlignment: Text.AlignVCenter
                        horizontalAlignment: rankRow.model.alignRight ? Text.AlignRight : Text.AlignLeft
                        text: rankRow.model.text
                        color: rankRow.model.fg || Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: page.fntBase
                        elide: Text.ElideRight
                    }

                    // 每行一个「加入购物车」。用 Loader 只在操作列建按钮 ——
                    // 直接摆 FButton 的话，视口里每一格都会实例化一个按钮。
                    Loader {
                        anchors.centerIn: parent
                        active: rankRow.model ? rankRow.model.isAction : false
                        visible: active
                        sourceComponent: Component {
                            FButton {
                                compact: true
                                text: qsTr("加入购物车")
                                onClicked: if (page.trade)
                                    page.trade.addToCart(rankRow.row)
                            }
                        }
                    }
                }
            }

            Text {
                objectName: "rankEmpty"
                anchors.centerIn: parent
                visible: page.trade ? page.trade.isEmpty : true
                text: page.trade ? page.trade.emptyHint : ""
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntBase
            }
        }

        // ═══════════════════════════════════════════════════
        //  页面状态栏
        // ═══════════════════════════════════════════════════
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: Math.max(28, page.fntSmall + 14)
            color: Theme.bgSurface

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 2 * page.pad
                anchors.rightMargin: 2 * page.pad
                spacing: page.pad

                Text {
                    objectName: "statusText"
                    Layout.fillWidth: true
                    text: page.trade ? page.trade.statusText : ""
                    color: Theme.textSecondary
                    font.family: Theme.fontFamily
                    font.pixelSize: page.fntSmall
                    elide: Text.ElideRight
                    verticalAlignment: Text.AlignVCenter
                }

                Text {
                    objectName: "cartSummary"
                    text: page.trade ? page.trade.cartSummary : ""
                    color: Theme.textPrimary
                    font.family: Theme.fontFamily
                    font.pixelSize: page.fntSmall
                    verticalAlignment: Text.AlignVCenter
                }
            }
        }

        // ═══════════════════════════════════════════════════
        //  页面功能按钮
        // ═══════════════════════════════════════════════════
        RowLayout {
            objectName: "actionButtons"
            Layout.fillWidth: true
            Layout.margins: page.pad
            spacing: page.pad

            Item {
                Layout.fillWidth: true
            }

            FButton {
                objectName: "cartButton"
                text: qsTr("购物车")
                onClicked: if (page.trade)
                    page.trade.openCart()
            }
        }
    }
}
