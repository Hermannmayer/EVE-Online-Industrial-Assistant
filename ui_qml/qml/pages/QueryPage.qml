import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
// 两态面板都在 pages/query/ 下 —— QML 只按**同目录**解析本地类型，
// 不写这一行会报「QueryDetailPane is not a type」而整页加载失败。
import "query"

/* 物品查询页 —— 阶段 3。
 *
 * 对照 Widgets 版 `ui_pyside6/views/query/query_page.py`：
 *   工具栏（全物品 / 搜索框+候选 / 清空 / 批量查价 / 区域）
 *   + 进度条 + 状态行 + 下方面板。
 *
 * **候选弹窗就是匹配清单**（用户明确要求）：输入即列全部前缀匹配，点一条直接出详情，
 * 不再有结果表格 —— 所以这里没有列定义、排序、右键菜单与当前行。
 *
 * **业务动作一律不在这里实现**：每次交互都调 `query.<方法>`，
 * 由 `ui_qml/bridge/query_bridge.py` 转给既有的 worker / service。
 *
 * 两态的判据是 `detail.typeId > 0`（详情桥有没有拿到物品），不是「有没有查询结果」。
 */
Item {
    id: page

    /* 查询桥，由 `PageHost` 以 context property `bridge` 注入。
     * 别名不与 context property 同名（同名声明会遮蔽它，恒为 null 且无报错）。 */
    readonly property var query: typeof bridge !== "undefined" ? bridge : null

    readonly property int fntBase: Math.round(12 * Theme.fontScale)
    readonly property int fntSmall: Math.round(11 * Theme.fontScale)

    /* 页面被销毁（切页 / 关窗 / 退出）时停掉在途取数线程。
     *
     * 详情面板选中一行就会起 ESI 订单线程（超时 30 秒）。不停的话，Qt 会在进程退出时
     * 去析构一个**还在跑**的 QThread —— 那是直接崩、且输出里连 traceback 都没有
     * （见 `QueryDetailBridge.shutdown` 的说明）。同一条也对仪表盘的定时器生效。 */
    Component.onDestruction: if (page.query)
        page.query.shutdown()

    // 整页不透明底（宿主是透明清屏的 QQuickWidget，见 IndustryPage 的同款说明）
    Rectangle {
        anchors.fill: parent
        color: Theme.bgDark
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // ═══════════════════════════════════════════════════════
        //  1. 工具栏
        // ═══════════════════════════════════════════════════════

        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.spacingSm
            Layout.rightMargin: Theme.spacingSm
            Layout.topMargin: Theme.spacingSm
            Layout.bottomMargin: Theme.spacingSm
            spacing: Theme.spacingSm

            FButton {
                id: allItemsButton
                text: qsTr("全物品")
                onClicked: if (page.query)
                    page.query.openAllItems()

                HoverHandler {
                    id: allItemsHover
                }
                ToolTip.visible: allItemsHover.hovered
                ToolTip.text: qsTr("打开全物品浏览器")
            }

            FTextField {
                id: searchInput
                objectName: "searchInput"
                Layout.fillWidth: true
                placeholderText: qsTr("输入物品名称或 ID...")
                onTextChanged: if (page.query)
                    page.query.onTextChanged(text)

                /* 回车 = 选第一条候选。页面已经没有「搜索」这一步 —— 候选就是匹配清单，
                 * 选中即出详情。取的是**桥**里那份候选（与弹窗显示的是同一份），
                 * 不被弹窗的 items 分支（候选/历史）影响。 */
                onAccepted: if (page.query && page.query.suggestions.length > 0)
                    page.query.pickSuggestion(page.query.suggestions[0].text)

                /* 空输入框被**按下**时让桥把历史读出来。弹窗的开/关由 `suggestPopup`
                 * 里的 `onSuggestionsChanged` 统一处理，这里只管「要数据」。
                 *
                 * 触发点必须挂在 `onPressed` 而不是 `onActiveFocusChanged`：
                 * 用户实测「点输入框之后再去点界面其他地方，输入框**并不丢焦点**」，
                 * 所以第二次点击根本没有 activeFocusChanged 事件 —— 这正是
                 * 「只有第一次点击会出现历史」的原因。
                 *
                 * 顺带解决「刚进页面输入框本来就是空的、没有文本变化」：`_history` 原先
                 * 只在文本**变成空**时才读，点「清空」反而会触发（把 text 置空）。
                 */
                onPressed: if (page.query && text.length === 0)
                    page.query.showHistory()
                Keys.onEscapePressed: suggestPopup.close()
            }

            FButton {
                text: qsTr("清空")
                onClicked: {
                    searchInput.text = ""
                    if (page.query)
                        page.query.clear()
                }
            }

            Item {
                Layout.fillWidth: true
            }

            Text {
                text: qsTr("区域:")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntBase
            }

            FComboBox {
                id: regionCombo
                implicitWidth: 96
                model: page.query ? page.query.regions : []
                currentIndex: page.query ? page.query.regionIndex : 0
                onActivated: if (page.query)
                    page.query.setRegionIndex(currentIndex)
            }
        }

        // ═══════════════════════════════════════════════════════
        //  2. 进度条（查询中显示，3px 不确定态）
        // ═══════════════════════════════════════════════════════

        Rectangle {
            id: progressTrack
            Layout.fillWidth: true
            height: 3
            visible: page.query ? page.query.busy : false
            color: Theme.bgSurfaceLight

            Rectangle {
                id: progressBlob
                width: Math.max(40, progressTrack.width * 0.3)
                height: parent.height
                color: Theme.primary

                NumberAnimation on x {
                    from: -progressBlob.width
                    to: progressTrack.width
                    duration: 900
                    loops: Animation.Infinite
                    running: progressTrack.visible
                }
            }
        }

        // ═══════════════════════════════════════════════════════
        //  3. 状态行
        // ═══════════════════════════════════════════════════════

        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.spacingSm
            Layout.rightMargin: Theme.spacingSm
            Layout.topMargin: 2
            Layout.bottomMargin: 2
            spacing: Theme.spacingSm

            Text {
                text: page.query ? page.query.statusText : ""
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntSmall
                elide: Text.ElideRight
                horizontalAlignment: Text.AlignRight
            }
        }

        // ═══════════════════════════════════════════════════════
        //  4. 主工作区：**两态**
        //     未选物品 = 仪表盘（产线详情 / 资产折线 / 挂单列表）
        //     已选物品 = 详情面板（5 中心价格 / 订单 / 精炼 / 材料）
        // ═══════════════════════════════════════════════════════

        Item {
            id: workArea
            Layout.fillWidth: true
            Layout.fillHeight: true
            /* 外框内缩：与「价格监控」页同款观感（表格区被一块带描边的面裹住，
             * 而不是通铺到页边）。内缩量取本页工具栏用的同一个 spacingSm。 */
            Layout.leftMargin: Theme.spacingSm
            Layout.rightMargin: Theme.spacingSm
            Layout.bottomMargin: Theme.spacingSm

            /* 两态切换的唯一判据：详情桥**有没有拿到物品**（`detail.typeId > 0`）。
             *
             * 原先判据是「有没有查询结果」，那是因为页面上有张结果表；表已按用户要求删掉，
             * 于是「显示仪表盘还是详情面板」只能看有没有选中物品。
             * `typeId` 是详情桥自己的 Property（`notify=changed`），换物品与清空都会发通知，
             * 绑定会跟着刷新 —— 不像 Slot 调用那样追不到。
             *
             * 判据里**不能带 `busy`**：它只是「按候选查明细」的中间态，掺进来会让界面
             * 在仪表盘与详情之间来回翻两次（本仓既有教训）。 */
            readonly property bool idle: !(page.query && page.query.detail && page.query.detail.typeId > 0)

            QueryDashboard {
                objectName: "queryDashboard"
                anchors.fill: parent
                visible: workArea.idle
                dashboard: page.query ? page.query.dashboard : null
            }

            /* 详情面板：四块（5 个贸易中心价格 / 订单列表 / 精炼产物 / 制造材料）。
             * 没有结果表之后它**铺满整个工作区** —— 四块是 2×2 网格，
             * 挤进窄列会让「空间站」这种长列被截断。 */
            QueryDetailPane {
                objectName: "queryDetailPane"
                anchors.fill: parent
                visible: !workArea.idle
                detail: page.query ? page.query.detail : null
            }
        }
    }

    // ═══════════════════════════════════════════════════════════
    //  搜索候选 / 历史（贴在输入框下方）
    // ═══════════════════════════════════════════════════════════

    Popup {
        id: suggestPopup
        objectName: "suggestPopup"
        // 以输入框为父项：位置由 Qt 在 open 时换算，**不要**用 mapToItem 手算坐标
        // （函数调用不被绑定依赖追踪，只在创建时求值一次，会永远贴在左上角）
        parent: searchInput
        x: 0
        y: searchInput.height + 2
        width: Math.max(searchInput.width, 260)
        padding: 2
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        readonly property var items: page.query && page.query.suggestions.length > 0
                                     ? page.query.suggestions
                                     : (page.query && searchInput.text.length === 0 ? page.query.history : [])
        readonly property bool showingHistory: !(page.query && page.query.suggestions.length > 0)

        /* 开/关只由**桥的显式信号**驱动，不写 `visible: items.length > 0`，也不监听 `items`。
         *
         * 两种写法都错在同一个地方 —— `items` 是每次重算都会产生**新数组**的派生值：
         *  - `visible: items.length > 0`：关掉（点外面 / Esc）之后历史内容没变 → 长度也不变
         *    → 绑定不重算 → 再也打不开。用户实测就是「只有第一次点击会出现历史」。
         *  - `onItemsChanged: open()`：反过来又太灵 —— 任何依赖变化都会让 `items` 换个新数组
         *    从而触发它，实测连 `close()` 都会被立刻顶回来（Esc 关不掉）。
         *
         * 于是：桥在「候选/历史有内容了」时发 `suggestionsChanged`（用户动作才会发），
         * QML 收到后**显式**开关。`close()` 之后没有信号进来，就稳定关着。
         * `Qt.callLater` 是必须的：`items` 是派生绑定，同一轮里读到的还是旧值。
         */
        Connections {
            target: page.query
            function onSuggestionsChanged() {
                // 里面的 `items` 必须限定成 `suggestPopup.items`：嵌套 `function()` 有独立
                // 作用域，不带限定符时解析不到 Popup 的属性（实测报 ReferenceError）。
                Qt.callLater(function () {
                    if (suggestPopup.items.length > 0)
                        suggestPopup.open()
                    else
                        suggestPopup.close()
                })
            }
        }

        background: Rectangle {
            color: Theme.bgElevated
            border.color: Theme.border
            border.width: 1
            radius: Theme.radius
        }

        contentItem: ListView {
            clip: true
            implicitHeight: Math.min(280, contentHeight)
            model: suggestPopup.items
            ScrollIndicator.vertical: ScrollIndicator {}

            delegate: ItemDelegate {
                id: suggestItem
                required property var modelData
                width: ListView.view.width
                implicitHeight: 28

                /* 候选带物品图标（历史项是**裸查询词**，没有物品、也就没有图标）。
                 * 图标 PNG 没下载到本地时桥给的是空串，`visible` 跟着 false ——
                 * 空串喂给 `Image.source` 不会刷警告（见 `icon_cache.icon_url`）。 */
                readonly property string iconSource: !suggestPopup.showingHistory
                                                     && suggestItem.modelData
                                                     && suggestItem.modelData.icon
                                                     ? String(suggestItem.modelData.icon) : ""

                Image {
                    visible: suggestItem.iconSource !== ""
                    anchors.left: parent.left
                    anchors.leftMargin: Theme.spacingSm
                    anchors.verticalCenter: parent.verticalCenter
                    width: Math.round(16 * Theme.fontScale)
                    height: width
                    source: suggestItem.iconSource
                    sourceSize.width: width
                    sourceSize.height: height
                    smooth: true
                    fillMode: Image.PreserveAspectFit
                }

                contentItem: Text {
                    // 有图标时把文字右移，免得压在图标上
                    leftPadding: suggestItem.iconSource !== ""
                                 ? Theme.spacingSm + Math.round(22 * Theme.fontScale)
                                 : Theme.spacingSm
                    rightPadding: Theme.spacingSm
                    verticalAlignment: Text.AlignVCenter
                    /* 候选与历史都**只显示物品名**，历史项不再加「历史:」前缀。
                     * 分支保留是因为两者形状不同：候选项是 `{id, text, query, icon}` 字典，
                     * 历史项是字符串（桥里已从历史文件取出 `query` 字段）。 */
                    text: suggestPopup.showingHistory
                          ? String(suggestItem.modelData)
                          : String(suggestItem.modelData.text)
                    color: Theme.textPrimary
                    font.family: Theme.fontFamily
                    font.pixelSize: page.fntBase
                    elide: Text.ElideRight
                }

                background: Rectangle {
                    radius: Theme.radiusSmall
                    color: suggestItem.highlighted ? Theme.bgHover : "transparent"
                }

                onClicked: {
                    if (page.query)
                        page.query.pickSuggestion(suggestPopup.showingHistory
                                                  ? String(suggestItem.modelData)
                                                  : String(suggestItem.modelData.text))
                    searchInput.forceActiveFocus()
                }
            }
        }
    }

    // ═══════════════════════════════════════════════════════════
    //  右键菜单已随结果表一起删除（复制类快捷方式用户明确不要了）。
    //  「查看制造配方」是那里唯一非复制类的功能，改挂工具栏按钮（见上面的 recipeButton）。
    // ═══════════════════════════════════════════════════════════
}
