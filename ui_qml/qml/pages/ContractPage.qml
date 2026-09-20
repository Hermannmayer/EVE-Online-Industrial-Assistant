import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 合同市场页 —— 三个子页签（拍卖 / 物品交换 / 运输）。
 *
 * 对照旧版单页（工具栏 + 过滤栏 + 上下两表的 SplitView）：类型从「下拉筛选」升级成
 * **页签**，因为三类合同的判定口径完全不同 —— 拍卖比一口价、物品交换比内容物市价
 * （含蓝图时还要算制造利润）、运输比每方每跳 ISK。混在一张表里列不出各自要的列。
 *
 * **进页面只查库、不联网**：拉取只在点「拉取合同」之后发生（用户明确要求）。
 * 物品详情是「价差」的前提，但一个星域三万多份合同、一份一个请求，所以它走
 * 「后台补齐 + 可停 + 进度可见」，而不是拉合同时一起拉。
 *
 * 业务动作一律不在这里实现：每次交互都调 `contract.<方法>`。
 */

Item {
    id: page

    /* 合同桥，由 `PageHost` 以 context property `bridge` 注入。
     * 别名不与 context property 同名（同名声明会遮蔽它，恒为 null 且无报错）。 */
    readonly property var contract: typeof bridge !== "undefined" ? bridge : null

    readonly property int fntBase: Math.round(12 * Theme.fontScale)
    readonly property int gap: Theme.spacingSm

    /* 进页面就查库（不联网）—— 旧版没有任何「初次加载」入口，只有切区域/切类型/点刷新
     * 才会加载，于是第一次打开合同页永远是空表、也不报错。 */
    Component.onCompleted: {
        if (page.contract) {
            page.contract.refreshRegionLabel()
            page.contract.loadTab()
        }
    }

    /* 销毁前先让在跑的 worker 收尾。
     * 本页是唯一「进门就起 QThread」的页面；线程生命周期本已由 `contract_workers._LIVE_WORKERS`
     * 兜住（不随宿主析构），这里再等一次是让关窗时不留悬空线程。取数是本地查询，等几百毫秒无感。 */
    Component.onDestruction: if (page.contract) page.contract.shutdown()

    // 整页不透明底（宿主是透明清屏的 QQuickWidget）
    Rectangle {
        anchors.fill: parent
        color: Theme.bgDark
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // ═══════════════════════════════════════════════════════
        //  页面工具栏：星域 / 拉取 / 补齐 / 状态
        // ═══════════════════════════════════════════════════════

        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 2 * page.gap
            Layout.rightMargin: 2 * page.gap
            Layout.topMargin: page.gap
            spacing: page.gap

            Text {
                text: qsTr("星域:")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntBase
            }
            FComboBox {
                objectName: "hubCombo"
                implicitWidth: 140
                model: page.contract ? page.contract.regionOptions : []
                onActivated: if (page.contract) page.contract.setHubIndex(currentIndex)
            }

            /* 按**名字**挑星域 —— 用户不该被要求背星域 id，而官方中文名又和口语名
             * 对不上（口语「寂静谷」，官方「静谧谷」），所以打几个字就出候选。 */
            FTextField {
                id: regionInput
                objectName: "regionInput"
                implicitWidth: 200
                placeholderText: qsTr("或输入星域名（如 静谧谷 / Domain）")
                onTextChanged: if (page.contract) page.contract.setRegionQuery(text)
                Keys.onEscapePressed: regionSuggest.close()
            }

            Text {
                text: page.contract ? ("当前: " + page.contract.regionLabel) : ""
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntBase
            }

            /* 按发布者反查 —— 游戏内搜合同只能按发布者搜，所以「双击复制发布者」之后
             * 得能拿这个名字回来查他的全部合同。筛选状态在桥上，**三个页签共用**。 */
            Text {
                text: qsTr("发布者:")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntBase
                Layout.leftMargin: page.gap
            }
            FTextField {
                objectName: "issuerInput"
                implicitWidth: 170
                placeholderText: qsTr("发布者名字，回车查询")
                // 只记下输入，不每敲一个字就查库（最重一档 49 ms）—— 回车/应用筛选才查
                onTextChanged: if (page.contract) page.contract.setIssuerQuery(text)
                onAccepted: if (page.contract) page.contract.applyFilters()
            }

            Item {
                Layout.fillWidth: true
            }

            FButton {
                objectName: "fetchButton"
                text: qsTr("拉取合同")
                primary: true
                enabled: page.contract ? !page.contract.busy : false
                onClicked: if (page.contract) page.contract.refresh()
            }
            FButton {
                objectName: "fillButton"
                text: qsTr("补齐全部物品")
                enabled: page.contract ? !page.contract.busy : false
                onClicked: if (page.contract) page.contract.startFill()
            }
            FButton {
                objectName: "stopButton"
                text: qsTr("停止")
                visible: page.contract ? page.contract.busy : false
                onClicked: if (page.contract) page.contract.stopFill()
            }
        }

        // ── 状态条（拉取/补齐的进度与结果都走这里，不再有静默失败）──
        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 2 * page.gap
            Layout.rightMargin: 2 * page.gap
            Layout.bottomMargin: page.gap
            spacing: page.gap

            Text {
                objectName: "statusText"
                Layout.fillWidth: true
                text: page.contract ? page.contract.statusText : ""
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntBase
                elide: Text.ElideRight
            }
        }

        /* 不确定进度条：光带从左侧滑出、滑到右侧消失。
         * **必须 clip**：外框不裁的话，光带滑到 `parent.width` 时整个露在页面外面
         * （用户看到的就是「进度条超出了页面」）。 */
        Rectangle {
            Layout.fillWidth: true
            height: 3
            visible: page.contract ? page.contract.busy : false
            color: Theme.bgSurfaceLight
            clip: true

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
        //  三个子页签 —— 分段控件
        // ═══════════════════════════════════════════════════════

        /* 为什么不是 `FTabBar`：它在 `Layout.fillWidth: true` 下把三个标签**等分撑到整行**
         * （实测 1920 宽的窗口里「拍卖」在 x≈320、「运输」在 x≈1650），选中态只有一条
         * 1px 细线 —— 用户反馈「一眼看不到分页在哪里调」。改成左对齐的紧凑分段控件：
         * 选中段整块填主色 + 反白，未选中是次级文字、悬停变亮，段内带条数徽标。
         *
         * 用 `Repeater` 而不是手写三个：分隔线要判断「右边那段是不是选中的」，
         * 按下标取邻段只有 Repeater 能给。 */
        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 2 * page.gap
            Layout.rightMargin: 2 * page.gap
            Layout.topMargin: page.gap
            spacing: page.gap

            Rectangle {
                objectName: "contractTabStrip"
                implicitWidth: tabRow.implicitWidth + 4
                implicitHeight: tabRow.implicitHeight + 4
                radius: Theme.radius
                color: Theme.bgSurface
                border.width: 1
                border.color: Theme.border

                component SegTab: Rectangle {
                    id: seg
                    required property int index
                    required property string label

                    readonly property int activeIndex: page.contract ? page.contract.tabIndex : 0
                    readonly property bool active: seg.activeIndex === seg.index
                    readonly property var counts: page.contract ? page.contract.tabCounts : []
                    readonly property int count: seg.index < seg.counts.length ? seg.counts[seg.index] : 0

                    implicitWidth: segContent.implicitWidth + 2 * Math.round(16 * Theme.fontScale)
                    implicitHeight: Math.round(32 * Theme.fontScale)
                    radius: Theme.radiusSmall
                    color: seg.active ? Theme.primary : (segMouse.containsMouse ? Theme.bgHover : "transparent")

                    Row {
                        id: segContent
                        anchors.centerIn: parent
                        spacing: Math.round(8 * Theme.fontScale)

                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: seg.label
                            color: seg.active ? Theme.textOnPrimary : Theme.textSecondary
                            font.family: Theme.fontFamily
                            font.pixelSize: page.fntBase
                            font.bold: seg.active
                        }
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            visible: seg.count > 0
                            text: seg.count.toLocaleString(Qt.locale(), "f", 0)
                            color: seg.active ? Theme.textOnPrimary : Theme.textSecondary
                            opacity: seg.active ? 0.75 : 0.7
                            font.family: Theme.fontFamily
                            font.pixelSize: Math.round(page.fntBase * 0.9)
                        }
                    }

                    /* 段间分隔线：两段都没选中时才画（选中的那段整块是主色，画线只会脏） */
                    Rectangle {
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        width: 1
                        height: Math.round(seg.height * 0.45)
                        color: Theme.border
                        visible: seg.index < 2 && !seg.active && seg.activeIndex !== seg.index + 1
                    }

                    MouseArea {
                        id: segMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        onClicked: if (page.contract) page.contract.setTabIndex(seg.index)
                    }
                }

                Row {
                    id: tabRow
                    anchors.centerIn: parent
                    spacing: 0

                    /* 用下标取标签，**不走 `modelData`**：delegate 声明了 required 属性时
                     * Qt 不再把模型数据放进上下文，`label: modelData` 会静默绑成空串
                     * （实测页签只剩条数、中文标签全不见）。 */
                    Repeater {
                        model: 3

                        delegate: SegTab {
                            label: page.contract && page.contract.tabs.length > index
                                   ? page.contract.tabs[index] : ""
                        }
                    }
                }
            }

            Item {
                Layout.fillWidth: true
            }
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: page.contract ? page.contract.tabIndex : 0

            ContractTabPane {
                tabKey: "auction"
                c: page.contract
                columns: page.contract ? page.contract.auctionColumns : []
                model: page.contract ? page.contract.auctionModel : null
            }
            ContractTabPane {
                tabKey: "exchange"
                c: page.contract
                columns: page.contract ? page.contract.exchangeColumns : []
                model: page.contract ? page.contract.exchangeModel : null
            }
            ContractTabPane {
                tabKey: "courier"
                c: page.contract
                columns: page.contract ? page.contract.courierColumns : []
                model: page.contract ? page.contract.courierModel : null
            }
        }
    }

    // ── 星域候选：打几个字就出，点一条即选中 ──
    Popup {
        id: regionSuggest
        objectName: "regionSuggest"
        // 以输入框为父项：位置由 Qt 在 open 时换算；**不要**用 mapToItem 手算坐标
        // （函数调用不被绑定依赖追踪，只在创建时求值一次，会永远贴在左上角）
        parent: regionInput
        x: 0
        y: regionInput.height + 2
        width: Math.max(280, regionInput.width)
        padding: 4
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        /* 开/关只由**桥的显式信号**驱动，不写 `visible: suggestions.length > 0`。
         * `suggestions` 每次都是新数组：绑 visible 的话，关掉（点外面/Esc）之后
         * 内容没变 → 长度没变 → 绑定不重算 → 再也打不开（`#suggestPopup` 踩过这个坑）。
         * `Qt.callLater` 是必须的：同一轮里读到的还是旧值。 */
        Connections {
            target: page.contract
            function onSuggestChanged() {
                Qt.callLater(function () {
                    if (page.contract && page.contract.suggestions.length > 0)
                        regionSuggest.open()
                    else
                        regionSuggest.close()
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
            implicitHeight: Math.min(300, contentHeight)
            clip: true
            model: page.contract ? page.contract.suggestions : []
            ScrollIndicator.vertical: ScrollIndicator {}

            delegate: Item {
                id: srow
                required property int index
                required property var modelData
                width: ListView.view.width
                implicitHeight: Math.max(24, page.fntBase + 12)

                Rectangle {
                    anchors.fill: parent
                    color: sMouse.containsMouse ? Theme.bgSurfaceLight : "transparent"
                }
                Text {
                    anchors.fill: parent
                    anchors.leftMargin: 6
                    verticalAlignment: Text.AlignVCenter
                    text: srow.modelData.name + "  (" + srow.modelData.en_name + ")"
                    color: Theme.textPrimary
                    font.family: Theme.fontFamily
                    font.pixelSize: page.fntBase
                    elide: Text.ElideRight
                }
                MouseArea {
                    id: sMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    onClicked: {
                        // 选中后桥会清空候选并发信号 —— 弹窗由上面的 Connections 关掉
                        if (page.contract) page.contract.pickRegion(srow.index)
                        regionInput.text = ""
                    }
                }
            }
        }
    }
}
