import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 工业制造页 —— 阶段 2b：整页骨架（5 区）。
 *
 * 对照 Widgets 版 `ui_pyside6/views/industry_view.py` 的分区：
 *   1 页面标题栏   2 顶部工具栏   3 主工作区（表格 / 甘特图）   4 状态栏   5 功能按钮
 *
 * **业务动作一律不在这里实现**：每次交互都调 `industry.<方法>`，
 * 由 `ui_qml/bridge/industry_bridge.py` 转给 `IndustryPage`，
 * 保证迁移期只有一份业务实现。
 *
 * 计划表本体是 `PlanTablePane`，它的桥 `planTableBridge` 由同一层宿主注入，
 * 全树同名（见该文件头部的命名说明）。
 */
Item {
    id: page

    /* 工业页桥。别名不与 context property 同名 —— 同名声明会**遮蔽** context
     * property，恒为 null 且无任何报错（QML 查找顺序是「自身属性 → context」）。 */
    readonly property var industry: typeof bridge !== "undefined" ? bridge : null

    readonly property int fntBase: Math.round(12 * Theme.fontScale)
    readonly property int fntTitle: Math.round(16 * Theme.fontScale)

    /* 整页不透明底 —— 与 `EstimatePage` 同款，**必须有**。
     *
     * 宿主 `PageHost` 是 `QQuickWidget`，且为了让窗口级 Mica 透出来而设了
     * `setClearColor(transparent)`。于是**本页没画到的每一处都会透出窗口背后的东西**
     * （Widgets 窗口的 palette 底色，暗色下近似纯黑）。表格本体由 `PlanTablePane`
     * 自己铺了 surface 底色，但标题栏/工具栏/状态栏之间的空隙、行区以外的留白
     * 全在页面这一层 —— 少这一块，整页就是一块块黑洞（用户反馈「黑色背景」）。
     * 页级底色到手后，任何一区漏画都不会再漏到窗口外面去。 */
    Rectangle {
        anchors.fill: parent
        color: Theme.bgDark
    }

    // ═══════════════════════════════════════════════════════════
    //  1. 页面标题栏
    // ═══════════════════════════════════════════════════════════

    Item {
        id: titleBar
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: Math.max(30, page.fntTitle + 14)

        Text {
            anchors.left: parent.left
            anchors.leftMargin: 12
            anchors.verticalCenter: parent.verticalCenter
            text: page.industry ? page.industry.titleText : ""
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: page.fntTitle
            font.bold: true
        }

        Text {
            anchors.left: parent.left
            anchors.leftMargin: 12 + 96
            anchors.verticalCenter: parent.verticalCenter
            text: page.industry ? page.industry.planCountText : ""
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(13 * Theme.fontScale)
        }
    }

    // ═══════════════════════════════════════════════════════════
    //  2. 顶部工具栏（可换行）
    // ═══════════════════════════════════════════════════════════

    Flow {
        id: toolbar
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: titleBar.bottom
        anchors.margins: 6
        spacing: Theme.spacingSm
        // 组内不换行、只在组边界换行，与旧 FlowLayout 的分组策略一致

        RowLayout {
            spacing: Theme.spacingSm

            FButton {
                text: qsTr("从全物品添加")
                onClicked: page.industry.openManufacturableBrowser()
            }

            Text {
                text: "│"
                color: Theme.textSecondary
                font.pixelSize: page.fntBase
            }

            Text {
                text: qsTr("蓝图")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntBase
            }

            // 蓝图输入 + 搜索候选
            Item {
                Layout.preferredWidth: 240
                Layout.preferredHeight: 32

                FTextField {
                    id: blueprintInput
                    anchors.fill: parent
                    placeholderText: qsTr("粘贴蓝图名或剪贴板内容")
                    onTextChanged: page.industry.requestSuggestions(text)
                    onAccepted: page.submitBlueprint()
                }
            }

            FButton {
                text: qsTr("添加")
                onClicked: page.submitBlueprint()
            }
        }

        RowLayout {
            spacing: Theme.spacingSm

            Text {
                text: "│"
                color: Theme.textSecondary
                font.pixelSize: page.fntBase
            }

            FPriceSourceRow {
                id: matRow
                label: qsTr("材料")
                hubs: page.industry ? page.industry.hubs : []
                priceTypes: page.industry ? page.industry.priceTypes : []
                onHubEdited: value => page.industry.setPriceSetting("mat_hub", value)
                onPriceTypeEdited: value => page.industry.setPriceSetting("mat_price_type", value)
                onMultEdited: value => page.industry.setPriceSetting("mat_mult", value)
            }

            Text {
                text: "|"
                color: Theme.textSecondary
                font.pixelSize: page.fntBase
            }

            FPriceSourceRow {
                id: prodRow
                label: qsTr("成品")
                hubs: page.industry ? page.industry.hubs : []
                priceTypes: page.industry ? page.industry.priceTypes : []
                onHubEdited: value => page.industry.setPriceSetting("prod_hub", value)
                onPriceTypeEdited: value => page.industry.setPriceSetting("prod_price_type", value)
                onMultEdited: value => page.industry.setPriceSetting("prod_mult", value)
            }
        }

        RowLayout {
            spacing: Theme.spacingSm

            Text {
                text: "│"
                color: Theme.textSecondary
                font.pixelSize: page.fntBase
            }

            Text {
                text: qsTr("视图:")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntBase
            }

            // 分段切换：当前视图用主色实心，另一个描边
            FButton {
                text: qsTr("数据视图")
                primary: page.industry ? page.industry.viewMode === "data" : true
                onClicked: page.industry.setViewMode("data")
            }
            FButton {
                text: qsTr("甘特图")
                primary: page.industry ? page.industry.viewMode === "gantt" : false
                onClicked: page.industry.setViewMode("gantt")
            }

            FComboBox {
                id: filterCombo
                model: page.industry ? page.industry.filterOptions : []
                implicitWidth: 96
                onActivated: page.industry.setFilterIndex(currentIndex)
            }

            FButton {
                text: qsTr("刷新")
                onClicked: page.industry.refreshPrices()
            }
        }
    }

    // ═══════════════════════════════════════════════════════════
    //  3. 主工作区（数据视图 / 甘特图）
    // ═══════════════════════════════════════════════════════════

    Item {
        id: workspace
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: toolbar.bottom
        anchors.bottom: statusBar.top
        /* 与「价格监控」页同款：主工作区被外框裹住，从页边内缩一档 */
        anchors.leftMargin: Theme.spacingSm
        anchors.rightMargin: Theme.spacingSm
        anchors.bottomMargin: Theme.spacingSm

        /* 外框。单独一层、`z` 高于两个视图 —— 它们的底色是 `anchors.fill: parent`
         * 且声明在后，把边框加在底色矩形上会被整个盖掉（见 `QueryPage` 同款说明）。
         * 纯 `Rectangle` 不含 MouseArea，不吞鼠标事件，压在上层不影响点表。 */
        Rectangle {
            anchors.fill: parent
            z: 1
            color: "transparent"
            radius: Theme.radius
            border.width: 1
            border.color: Theme.border
        }

        PlanTablePane {
            id: dataView
            anchors.fill: parent
            visible: page.industry ? page.industry.viewMode === "data" : true
        }

        FGanttChart {
            id: ganttView
            anchors.fill: parent
            visible: page.industry ? page.industry.viewMode === "gantt" : false
            rows: page.industry ? page.industry.ganttRows : []
            maxHours: page.industry ? page.industry.ganttMaxHours : 48
        }
    }

    // ═══════════════════════════════════════════════════════════
    //  4. 状态栏（甘特图模式下隐藏，与旧行为一致）
    // ═══════════════════════════════════════════════════════════

    Item {
        id: statusBar
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: actionBar.top
        height: visible ? Math.max(32, page.fntBase + 20) : 0
        visible: page.industry ? page.industry.statusVisible : true
        clip: true

        // 左侧：统计文案 + 全部下线
        RowLayout {
            anchors.left: parent.left
            anchors.leftMargin: 10
            anchors.verticalCenter: parent.verticalCenter
            spacing: Theme.spacingMd

            Text {
                text: page.industry ? page.industry.statusText : ""
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntBase
                elide: Text.ElideRight
            }

            FButton {
                visible: page.industry ? page.industry.completeAllVisible : false
                text: page.industry ? page.industry.completeAllText : ""
                onClicked: page.industry.completeAll()
            }
        }

        // 右侧：采购汇总 + 保存价格
        RowLayout {
            anchors.right: parent.right
            anchors.rightMargin: 10
            anchors.verticalCenter: parent.verticalCenter
            spacing: Theme.spacingMd

            Text {
                text: page.industry ? page.industry.materialText : ""
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntBase
            }

            FButton {
                text: qsTr("保存价格")
                onClicked: page.industry.savePrices()
            }
        }
    }

    // ═══════════════════════════════════════════════════════════
    //  5. 底部功能按钮
    // ═══════════════════════════════════════════════════════════

    RowLayout {
        id: actionBar
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 6
        visible: page.industry ? page.industry.statusVisible : true
        height: visible ? 40 : 0
        spacing: Theme.spacingMd

        FButton {
            text: qsTr("产线启动小助手")
            onClicked: page.industry.launchWizard()
        }
        FButton {
            text: qsTr("采购小助手")
            onClicked: page.industry.openProcurement()
        }
        FButton {
            text: qsTr("所需蓝图表")
            onClicked: page.industry.openBlueprintList()
        }
        FButton {
            text: qsTr("填料总表")
            onClicked: page.industry.openMaterialsSummary()
        }
        FButton {
            text: qsTr("产出总表")
            onClicked: page.industry.openOutputSummary()
        }
        FButton {
            text: qsTr("人物占用")
            onClicked: page.industry.openCharUsage()
        }
        Item {
            Layout.fillWidth: true
        }
    }

    // ═══════════════════════════════════════════════════════════
    //  蓝图搜索候选
    // ═══════════════════════════════════════════════════════════

    Popup {
        id: suggestionPopup
        objectName: "suggestionPopup"
        /* 位置：以输入框为父项，交给 Qt 的弹出物定位（在 open 时按当时的几何换算）。
         *
         * **不要写成 `x: input.mapToItem(page, 0, 0).x`** —— `mapToItem` 是函数调用，
         * 它内部读的 x/y/width/height **不会被 QML 的绑定依赖追踪记下**，于是这条绑定
         * 只在创建时求值一次。那一刻输入框还没布局完（坐标是 0,0），此后布局再变也不会
         * 重算 —— 表现就是候选框永远贴在页面左上角（用户反馈实测踩过）。
         * 与 `Theme.fs()` 不被追踪是同一类问题。
         *
         * `parent: 输入框` 之后 x/y 是**相对输入框**的偏移，Qt 自己负责换算与跟手；
         * `blueprintInput.height` 是普通属性读取，会被正常追踪。 */
        parent: blueprintInput
        x: 0
        y: blueprintInput.height + 2
        width: Math.max(blueprintInput.width, 300)
        padding: 2
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        visible: page.industry !== null && page.industry.suggestions.length > 0

        background: Rectangle {
            color: Theme.bgElevated
            border.color: Theme.border
            border.width: 1
            radius: Theme.radius
        }

        contentItem: ListView {
            clip: true
            implicitHeight: Math.min(280, contentHeight)
            model: page.industry ? page.industry.suggestions : []
            ScrollIndicator.vertical: ScrollIndicator {}

            delegate: ItemDelegate {
                id: suggestionItem

                required property int index
                required property var modelData

                width: ListView.view ? ListView.view.width : 0
                implicitHeight: 30
                leftPadding: Theme.spacingSm
                rightPadding: Theme.spacingSm

                contentItem: Text {
                    text: suggestionItem.modelData
                    elide: Text.ElideRight
                    verticalAlignment: Text.AlignVCenter
                    color: Theme.textPrimary
                    font.family: Theme.fontFamily
                    font.pixelSize: page.fntBase
                }

                background: Rectangle {
                    radius: Theme.radiusSmall
                    color: suggestionItem.hovered ? Theme.bgHover : "transparent"
                }

                onClicked: page.acceptSuggestion(suggestionItem.modelData)
            }
        }
    }

    // ═══════════════════════════════════════════════════════════
    //  逻辑
    // ═══════════════════════════════════════════════════════════

    function submitBlueprint(): void {
        var text = blueprintInput.text.trim()
        if (!text || !page.industry)
            return
        blueprintInput.text = ""
        page.industry.addPlan(text)
    }

    function acceptSuggestion(text: string): void {
        // "中文名 (EnglishName)" → 取中文名；仅有英文名则直接取
        var name = text
        if (name.indexOf(" (") >= 0)
            name = name.split(" (")[0]
        else if (name.indexOf("（") >= 0)
            name = name.split("（")[0]
        name = name.trim()
        page.industry.clearSuggestions()
        if (name) {
            blueprintInput.text = ""
            page.industry.addPlan(name)
        }
    }

    function syncPriceSettings(): void {
        if (!page.industry)
            return
        var s = page.industry.priceSettings
        matRow.applySettings(s.mat_hub || "", s.mat_price_type || "sell", s.mat_mult || 1.0)
        prodRow.applySettings(s.prod_hub || "", s.prod_price_type || "sell", s.prod_mult || 1.0)
    }

    Component.onCompleted: syncPriceSettings()

    Connections {
        target: page.industry
        function onPriceSettingsChanged() {
            page.syncPriceSettings()
        }
        function onFilterChanged() {
            if (filterCombo.currentIndex !== page.industry.filterIndex)
                filterCombo.currentIndex = page.industry.filterIndex
        }
    }
}
