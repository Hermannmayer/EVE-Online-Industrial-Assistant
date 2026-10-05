import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 大盘 Tab —— 规格见 `docs/dev/market-monitor-plan.md` §4.1。
 *
 * 页面分区（区域名照 `docs/dev/ui-blueprint.md`）：
 *   页面工具栏：「7 日均线」开关 + 「刷新指数」（后台重算物化表）
 *   内容区（整页一条 Flickable）：指数卡 ×5 → 主图（五条基期=100 的指数折线）
 *        → 量价/广度 → 篮子成员表 → 异动榜两区（合格成分 / 全市场）→ 数据状态行
 *   右侧抽屉：点异动行弹出的 BOM 传导链（层级缩进 / 用量 / 成本占比 / 30-90-180 涨跌 /
 *        未跟涨高亮 / 口径标签）
 *   页面状态栏：本页本地数据的概况
 *
 * 业务全在 `ui_qml/bridge/market_pulse_bridge.py`，这里只画与转发 ——
 * 格式化（`—`、千分位、百分点、份额）与配色 token 都在桥里算好。
 *
 * ⚠️ 三条硬约束：
 *  1. 颜色一律 `Theme.*`（token 由桥给**名字**，这里翻成色值，见 `tokenColor`）；
 *  2. **不用 `Canvas`** —— 离屏截图路径下 Canvas 整块是空的（见 FLineChart 头部说明），
 *     折线交给共享组件 `FLineChart`（Shape 画线）；
 *  3. 表格**列宽只在函数里算一次**（`*Widths()`），表头与数据行共用同一份 ——
 *     两处各算一遍必然错位（表头对不齐数据是这页最容易出的外观缺陷）。
 */
Item {
    id: page

    /* 大盘桥。常规挂页（注册表按 `bridge` 注入）与「两个 Tab 共用一个页面」的容器
     * （那时 `bridge` 被关注页占着，大盘桥按 `pulseBridge` 注入）都认。
     * 别名**不与 context property 同名** —— 同名声明会遮蔽它，恒为 null 且不报错
     * （见 TradePage 顶部的同款说明）。 */
    readonly property var pulse: typeof pulseBridge !== "undefined" ? pulseBridge
                               : (typeof bridge !== "undefined" ? bridge : null)

    readonly property int fntBase: Math.round(12 * Theme.fontScale)
    readonly property int fntSmall: Math.round(11 * Theme.fontScale)
    readonly property int pad: Theme.spacingSm
    readonly property int rowH: Math.max(22, Math.round(12 * Theme.fontScale) + 10)
    readonly property int cardW: Math.round(226 * Theme.fontScale)
    readonly property int cardH: Math.round(130 * Theme.fontScale)  // 含副标题（构成/口径）一行
    readonly property int chgColW: Math.round(38 * Theme.fontScale)
    readonly property int drawerW: Math.round(560 * Theme.fontScale)
    readonly property int indentW: Math.round(12 * Theme.fontScale)

    /* 桥给的 token 名 → 主题色：颜色只在这里取，切主题自动跟着变
     * （同 `dialogs/ImportReviewDialog.qml` 的 `tokenColor`）。 */
    function tokenColor(token) {
        switch (token) {
        case "PRIMARY":
            return Theme.primary;
        case "ACCENT_GREEN":
            return Theme.accentGreen;
        case "ACCENT_RED":
            return Theme.accentRed;
        case "ACCENT_YELLOW":
            return Theme.accentYellow;
        case "ACCENT_ORANGE":
            return Theme.accentOrange;
        case "ACCENT_PURPLE":
            return Theme.accentPurple;
        case "ACCENT_CYAN":
            return Theme.accentCyan;
        case "TEXT_BRIGHT":
            return Theme.textBright;
        default:
            return Theme.textSecondary;
        }
    }

    /* FLineChart 要的是 `{label,color,points}`；桥给的是 token 名，这里翻成色值。
     * `series` 不是 `model`，每次求值新建数组不会碰到「新数组喂 syncView 会崩」那个坑
     * （见 TradePage 表头那段）。 */
    function chartSeries(rows) {
        const out = [];
        for (let i = 0; rows && i < rows.length; ++i) {
            const row = rows[i];
            out.push({
                "label": row.label,
                "color": page.tokenColor(row.token),
                "points": row.points,
                // 图例带上「现值 · 30 日涨跌」（FLineChart 的 note）——漏了这个字段，
                // 五条线在图上就只剩名字，看不出各自什么水平
                "note": row.note || ""
            });
        }
        return out;
    }

    // ── 三张表的列宽（单位 px，已按全局字号缩放）────────────────
    //: 第 0 列（名称）吃剩余宽度，所以数组第 0 项是占位 0。
    //: 「贡献」= 权重 × 30 日涨跌（百分点）——指数跌 8% 时一眼看出是谁在拖；
    //: 只按权重排序看不出这件事（最大成分未必是最大拖累）。
    function memberWidths() {
        return [0, Math.round(84 * Theme.fontScale), Math.round(104 * Theme.fontScale),
                Math.round(78 * Theme.fontScale), Math.round(74 * Theme.fontScale),
                Math.round(52 * Theme.fontScale)];
    }

    function moverWidths() {
        return [0, Math.round(104 * Theme.fontScale), Math.round(72 * Theme.fontScale),
                Math.round(96 * Theme.fontScale), Math.round(64 * Theme.fontScale),
                Math.round(46 * Theme.fontScale), Math.round(110 * Theme.fontScale)];
    }

    function chainWidths() {
        return [0, Math.round(64 * Theme.fontScale), Math.round(64 * Theme.fontScale),
                Math.round(58 * Theme.fontScale), Math.round(58 * Theme.fontScale),
                Math.round(58 * Theme.fontScale), Math.round(62 * Theme.fontScale)];
    }

    //: 名称列 = 总宽 − 其余固定列（下限 90，窄窗口下宁可截断也不要负宽度）
    function nameWidth(widths, total) {
        let fixed = 0;
        for (let i = 1; i < widths.length; ++i)
            fixed += widths[i];
        return Math.max(90, total - fixed);
    }

    //: 表头单元：与数据行同一个形状（列宽来自同一个 `widths`，不会错位）
    function headCells(labels, widths, total) {
        const out = [];
        const nameW = page.nameWidth(widths, total);
        for (let i = 0; i < labels.length; ++i) {
            out.push({
                "text": labels[i],
                "w": i === 0 ? nameW : widths[i],
                "indent": 0,
                "color": Theme.textSecondary,
                "right": i > 0,
                "bold": false,
                "size": page.fntSmall
            });
        }
        return out;
    }

    function memberHead(total) {
        return page.headCells([qsTr("成分"), qsTr("权重"), qsTr("现价"), qsTr("30 日涨跌"),
                               qsTr("贡献"), qsTr("触顶")],
                              page.memberWidths(), total);
    }

    function memberRow(row, total) {
        const widths = page.memberWidths();
        return [
            { "text": row.name, "w": page.nameWidth(widths, total), "indent": 0,
              "color": Theme.textPrimary, "right": false, "bold": false, "size": page.fntBase },
            { "text": row.weightText, "w": widths[1], "indent": 0,
              "color": Theme.textPrimary, "right": true, "bold": false, "size": page.fntBase },
            { "text": row.priceText, "w": widths[2], "indent": 0,
              "color": Theme.textPrimary, "right": true, "bold": false, "size": page.fntBase },
            { "text": row.chg30Text, "w": widths[3], "indent": 0,
              "color": page.tokenColor(row.chg30Token), "right": true, "bold": false, "size": page.fntBase },
            { "text": row.contribText, "w": widths[4], "indent": 0,
              "color": page.tokenColor(row.contribToken), "right": true, "bold": false, "size": page.fntBase },
            { "text": row.capped ? qsTr("已触顶") : "", "w": widths[5], "indent": 0,
              "color": Theme.accentYellow, "right": false, "bold": false, "size": page.fntSmall }
        ];
    }

    function moverHead(total) {
        return page.headCells([qsTr("物品"), qsTr("现价"), qsTr("涨跌"), qsTr("日成交量"),
                               qsTr("量比"), qsTr("流动性"), qsTr("命中指数")],
                              page.moverWidths(), total);
    }

    function moverRow(row, total) {
        const widths = page.moverWidths();
        return [
            { "text": row.name, "w": page.nameWidth(widths, total), "indent": 0,
              "color": Theme.textPrimary, "right": false, "bold": false, "size": page.fntBase },
            { "text": row.priceText, "w": widths[1], "indent": 0,
              "color": Theme.textPrimary, "right": true, "bold": false, "size": page.fntBase },
            { "text": row.chgText, "w": widths[2], "indent": 0,
              "color": page.tokenColor(row.chgToken), "right": true, "bold": true, "size": page.fntBase },
            { "text": row.volumeText, "w": widths[3], "indent": 0,
              "color": Theme.textSecondary, "right": true, "bold": false, "size": page.fntSmall },
            { "text": row.ratioText, "w": widths[4], "indent": 0,
              "color": Theme.textSecondary, "right": true, "bold": false, "size": page.fntSmall },
            // 「薄」= 近 N 日日均成交量太低，百分比很可能只是一笔成交推出来的
            { "text": row.thin ? qsTr("薄") : "", "w": widths[5], "indent": 0,
              "color": Theme.accentYellow, "right": false, "bold": false, "size": page.fntSmall },
            { "text": row.indexText, "w": widths[6], "indent": 0,
              "color": Theme.textSecondary, "right": true, "bold": false, "size": page.fntSmall }
        ];
    }

    function chainHead(total) {
        return page.headCells([qsTr("传导层级（点异动行 → 它的上游材料）"), qsTr("用量"), qsTr("成本占比"),
                               qsTr("30日"), qsTr("90日"), qsTr("180日"), qsTr("口径")],
                              page.chainWidths(), total);
    }

    function chainRow(row, total) {
        const widths = page.chainWidths();
        const level = Math.max(0, row.level - 1);
        return [
            // 层级用左内边距缩进（不是改 x：Row 会覆盖子项 x，改 x 会触发绑定冲突）
            { "text": (row.notCaughtUp ? "⚠ " : "") + (row.level > 1 ? "└ " : "") + row.name,
              "w": page.nameWidth(widths, total), "indent": level * page.indentW,
              "color": row.notCaughtUp ? Theme.accentYellow : Theme.textPrimary,
              "right": false, "bold": row.notCaughtUp, "size": page.fntBase },
            { "text": row.qtyText, "w": widths[1], "indent": 0,
              "color": Theme.textPrimary, "right": true, "bold": false, "size": page.fntBase },
            { "text": row.costShareText, "w": widths[2], "indent": 0,
              "color": Theme.textPrimary, "right": true, "bold": false, "size": page.fntBase },
            { "text": row.chg30Text, "w": widths[3], "indent": 0,
              "color": page.tokenColor(row.chg30Token), "right": true, "bold": false, "size": page.fntSmall },
            { "text": row.chg90Text, "w": widths[4], "indent": 0,
              "color": page.tokenColor(row.chg90Token), "right": true, "bold": false, "size": page.fntSmall },
            { "text": row.chg180Text, "w": widths[5], "indent": 0,
              "color": page.tokenColor(row.chg180Token), "right": true, "bold": false, "size": page.fntSmall },
            { "text": row.sourceText, "w": widths[6], "indent": 0,
              "color": Theme.textSecondary, "right": true, "bold": false, "size": page.fntSmall }
        ];
    }

    //: 挂载即拉一次本地数据（全是本地库的读，不碰网络；失败的那块由桥退化成空）
    Component.onCompleted: if (page.pulse)
        page.pulse.refresh()

    // 整页不透明底（宿主是透明清屏的 QQuickWidget，见 TradePage 的同款说明）
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
        RowLayout {
            objectName: "pulseToolbar"
            Layout.fillWidth: true
            Layout.margins: page.pad
            spacing: page.pad

            Text {
                text: qsTr("市场大盘")
                color: Theme.textBright
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(15 * Theme.fontScale)
                font.bold: true
                verticalAlignment: Text.AlignVCenter
            }

            Text {
                text: qsTr("（基期=100 · 只用 Jita 成交均价）")
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntSmall
                verticalAlignment: Text.AlignVCenter
            }

            Item {
                Layout.fillWidth: true
            }

            FCheckBox {
                objectName: "ma7Box"
                text: qsTr("7 日均线")
                checked: page.pulse ? page.pulse.showMa7 : false
                onToggled: if (page.pulse)
                    page.pulse.setShowMa7(checked)
            }

            FButton {
                objectName: "refreshIndexButton"
                primary: true
                text: (page.pulse && page.pulse.busy) ? qsTr("重算中…") : qsTr("刷新指数")
                enabled: page.pulse ? !page.pulse.busy : false
                onClicked: if (page.pulse)
                    page.pulse.refreshIndex()
            }
        }

        // ═══════════════════════════════════════════════════
        //  内容区（整页一条 Flickable：内部各表不再各自滚动，
        //  否则窄窗口里会变成「滚动条套滚动条」）
        // ═══════════════════════════════════════════════════
        Flickable {
            id: pulseScroll
            objectName: "pulseScroll"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            contentWidth: width
            contentHeight: body.y + body.implicitHeight + page.pad

            ScrollBar.vertical: ScrollBar {
                policy: ScrollBar.AsNeeded
            }

            /* 内容是一整条 ColumnLayout（不是 Column）：分区容器 `FSection` / `FPanel`
             * 的 `implicitHeight` 要靠布局系统抬成实际高度 —— 放在朴素 `Column` 里
             * 位置器**不会**改子项高度，它们会塌成 0 高（整块看不见，且不报错）。
             * 同 `components/FMarketTab.qml` 的 Flickable + ColumnLayout 写法。 */
            ColumnLayout {
                id: body
                x: page.pad
                y: page.pad
                width: pulseScroll.width - 2 * page.pad
                spacing: page.pad

                // ── 0. 首次使用引导（可关，关掉只影响本次会话）────────
                FPanel {
                    objectName: "guidePanel"
                    Layout.fillWidth: true
                    visible: page.pulse ? page.pulse.guideVisible : false
                    implicitHeight: guideCol.implicitHeight + 2 * page.pad

                    ColumnLayout {
                        id: guideCol
                        anchors.fill: parent
                        anchors.margins: page.pad
                        spacing: 4

                        RowLayout {
                            Layout.fillWidth: true

                            Text {
                                Layout.fillWidth: true
                                text: qsTr("这一页怎么用")
                                color: Theme.textPrimary
                                font.family: Theme.fontFamily
                                font.pixelSize: page.fntBase
                                font.bold: true
                            }

                            FButton {
                                objectName: "dismissGuideButton"
                                text: qsTr("知道了")
                                onClicked: if (page.pulse)
                                    page.pulse.dismissGuide()
                            }
                        }

                        Text {
                            Layout.fillWidth: true
                            text: page.pulse ? page.pulse.guideText : ""
                            color: Theme.textSecondary
                            font.family: Theme.fontFamily
                            font.pixelSize: page.fntSmall
                            wrapMode: Text.WordWrap
                            lineHeight: 1.25
                        }
                    }
                }

                // ── 0b. 市场诊断：把指数/广度翻译成「那我该干什么」──
                FPanel {
                    objectName: "diagnosisPanel"
                    Layout.fillWidth: true
                    implicitHeight: diagCol.implicitHeight + 2 * page.pad

                    ColumnLayout {
                        id: diagCol
                        anchors.fill: parent
                        anchors.margins: page.pad
                        spacing: 4

                        RowLayout {
                            Layout.fillWidth: true

                            Text {
                                text: qsTr("市场诊断")
                                color: Theme.textPrimary
                                font.family: Theme.fontFamily
                                font.pixelSize: page.fntBase
                                font.bold: true
                            }

                            Text {
                                Layout.fillWidth: true
                                /* 明说这是规则推导：不写这句，用户会当成预测/投资建议 */
                                text: qsTr("（按指数与广度规则推导，不是预测、也不是投资建议）")
                                color: Theme.textSecondary
                                font.family: Theme.fontFamily
                                font.pixelSize: page.fntSmall
                                elide: Text.ElideRight
                            }
                        }

                        Repeater {
                            model: page.pulse ? page.pulse.diagnosis : []

                            Text {
                                required property var modelData

                                Layout.fillWidth: true
                                text: "· " + modelData.text
                                color: page.tokenColor(modelData.token)
                                font.family: Theme.fontFamily
                                font.pixelSize: page.fntSmall
                                wrapMode: Text.WordWrap
                                lineHeight: 1.25
                            }
                        }
                    }
                }

                // ── 1. 指数卡 ×5 ────────────────────────────────
                Flow {
                    objectName: "indexCards"
                    Layout.fillWidth: true
                    spacing: page.pad

                    Repeater {
                        model: page.pulse ? page.pulse.cards : []

                        Rectangle {
                            id: indexCard

                            required property var modelData

                            readonly property bool picked: modelData.selected === true

                            width: page.cardW
                            height: page.cardH
                            radius: Theme.radius
                            color: indexCard.picked ? Theme.bgSurfaceLight : Theme.bgSurface
                            border.width: indexCard.picked ? 2 : 1
                            border.color: indexCard.picked ? Theme.primary : Theme.border

                            Column {
                                anchors.fill: parent
                                anchors.margins: page.pad
                                spacing: 2

                                Text {
                                    width: parent.width
                                    text: indexCard.modelData.label
                                    color: Theme.textPrimary
                                    font.family: Theme.fontFamily
                                    font.pixelSize: page.fntBase
                                    font.bold: true
                                    elide: Text.ElideRight
                                }

                                /* 「这个指数由什么构成、怎么加权」——用户不知道 MPI/PPPI 是什么，
                                 * 没有这一行就得靠记忆。文案在桥里（`_CARD_META`）。 */
                                Text {
                                    objectName: "indexCardSubtitle"
                                    width: parent.width
                                    text: indexCard.modelData.subtitle || ""
                                    color: Theme.textSecondary
                                    font.family: Theme.fontFamily
                                    font.pixelSize: page.fntSmall
                                    elide: Text.ElideRight
                                }

                                Text {
                                    text: indexCard.modelData.valueText
                                    color: Theme.textBright
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Math.round(19 * Theme.fontScale)
                                    font.bold: true
                                }

                                Text {
                                    width: parent.width
                                    text: indexCard.modelData.baseDate + " · " + indexCard.modelData.days + qsTr(" 天")
                                    color: Theme.textSecondary
                                    font.family: Theme.fontFamily
                                    font.pixelSize: page.fntSmall
                                    elide: Text.ElideRight
                                }

                                Row {
                                    spacing: 2

                                    Repeater {
                                        model: indexCard.modelData.chgs

                                        Column {
                                            id: chgCol

                                            required property var modelData

                                            width: page.chgColW

                                            Text {
                                                width: parent.width
                                                text: chgCol.modelData.label
                                                color: Theme.textSecondary
                                                font.family: Theme.fontFamily
                                                font.pixelSize: page.fntSmall
                                                horizontalAlignment: Text.AlignRight
                                            }

                                            Text {
                                                width: parent.width
                                                text: chgCol.modelData.text
                                                color: page.tokenColor(chgCol.modelData.token)
                                                font.family: Theme.fontFamily
                                                font.pixelSize: page.fntSmall
                                                font.bold: true
                                                horizontalAlignment: Text.AlignRight
                                            }
                                        }
                                    }
                                }

                                Text {
                                    objectName: "indexCardHint"
                                    width: parent.width
                                    visible: indexCard.modelData.hint !== ""
                                    /* 文案由桥给（口径/基期提示），因为这三种情况要说的话不一样：
                                     * 「基期短，长窗口不全」是数据不足；PLEX 是**全服统一价**、
                                     * 口径与另外四条不同 —— 写死在这里必然有一边是误导。 */
                                    text: indexCard.modelData.hint
                                    color: Theme.accentYellow
                                    font.family: Theme.fontFamily
                                    font.pixelSize: page.fntSmall
                                    elide: Text.ElideRight
                                }
                            }

                            // 点卡切换选中：再点一次取消（成员表跟着切）；悬停看「怎么看」
                            MouseArea {
                                objectName: "indexCardHover"
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: if (page.pulse)
                                    page.pulse.selectIndex(indexCard.modelData.key)

                                ToolTip.visible: containsMouse && !!indexCard.modelData.toolTipText
                                ToolTip.text: indexCard.modelData.toolTipText || ""
                                ToolTip.delay: 400
                            }
                        }
                    }
                }

                Text {
                    objectName: "cardsEmpty"
                    Layout.fillWidth: true
                    visible: page.pulse ? page.pulse.cards.length === 0 : true
                    text: qsTr("还没有指数数据 —— 先在顶栏点「更新价格」补成交均价历史，再点右上「刷新指数」")
                    color: Theme.textSecondary
                    font.family: Theme.fontFamily
                    font.pixelSize: page.fntBase
                    wrapMode: Text.WordWrap
                }

                // ── 2. 主图（五条指数折线）───────────────────────
                FPanel {
                    objectName: "chartPanel"
                    Layout.fillWidth: true
                    Layout.preferredHeight: Math.round(268 * Theme.fontScale)
                    title: page.pulse && page.pulse.showMa7
                           ? qsTr("五大指数 · 7 日均线（基期=100）")
                           : qsTr("五大指数（基期=100）")

                    FLineChart {
                        objectName: "pulseChart"
                        anchors.fill: parent
                        series: page.chartSeries(page.pulse ? page.pulse.displaySeries : [])
                        xLabels: page.pulse ? page.pulse.xLabels : []
                        normalize: true
                        emptyText: qsTr("暂无指数序列 —— 先在顶栏「更新价格」补历史，再点「刷新指数」")
                    }
                }

                // ── 3. 量价 / 广度 ──────────────────────────────
                FSection {
                    objectName: "breadthSection"
                    title: qsTr("量价 / 广度")

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 2 * page.pad

                        Text {
                            objectName: "turnoverText"
                            text: page.pulse ? page.pulse.turnoverText : ""
                            color: Theme.textPrimary
                            font.family: Theme.fontFamily
                            font.pixelSize: page.fntBase
                        }

                        Text {
                            objectName: "advDeclText"
                            text: page.pulse ? page.pulse.advDeclText : ""
                            color: Theme.textPrimary
                            font.family: Theme.fontFamily
                            font.pixelSize: page.fntBase
                        }

                        Item {
                            Layout.fillWidth: true
                        }
                    }

                    Text {
                        objectName: "divergenceText"
                        Layout.fillWidth: true
                        visible: text !== ""
                        text: page.pulse ? page.pulse.divergenceText : ""
                        color: page.tokenColor(page.pulse ? page.pulse.divergenceToken : "")
                        font.family: Theme.fontFamily
                        font.pixelSize: page.fntBase
                        wrapMode: Text.WordWrap
                    }
                }

                // ── 4. 篮子成员表 ───────────────────────────────
                FSection {
                    objectName: "memberSection"
                    title: qsTr("篮子成员 · ") + (page.pulse ? page.pulse.membersNote : "")

                    Column {
                        id: memberTable

                        Layout.fillWidth: true
                        spacing: 0

                        Row {
                            width: memberTable.width
                            height: page.rowH

                            Repeater {
                                model: page.memberHead(memberTable.width)

                                Text {
                                    required property var modelData

                                    width: modelData.w
                                    height: parent.height
                                    leftPadding: modelData.indent
                                    text: modelData.text
                                    color: modelData.color
                                    font.family: Theme.fontFamily
                                    font.pixelSize: modelData.size
                                    font.bold: modelData.bold
                                    horizontalAlignment: modelData.right ? Text.AlignRight : Text.AlignLeft
                                    verticalAlignment: Text.AlignVCenter
                                    elide: Text.ElideRight
                                }
                            }
                        }

                        Repeater {
                            model: page.pulse ? page.pulse.members : []

                            Rectangle {
                                id: memberRow

                                required property var modelData
                                required property int index

                                width: memberTable.width
                                height: page.rowH
                                color: index % 2 === 1 ? Theme.bgDark : Theme.bgSurface

                                Row {
                                    anchors.fill: parent

                                    Repeater {
                                        model: page.memberRow(memberRow.modelData, memberTable.width)

                                        Text {
                                            required property var modelData

                                            width: modelData.w
                                            height: parent.height
                                            leftPadding: modelData.indent
                                            text: modelData.text
                                            color: modelData.color
                                            font.family: Theme.fontFamily
                                            font.pixelSize: modelData.size
                                            font.bold: modelData.bold
                                            horizontalAlignment: modelData.right ? Text.AlignRight : Text.AlignLeft
                                            verticalAlignment: Text.AlignVCenter
                                            elide: Text.ElideRight
                                        }
                                    }
                                }
                            }
                        }

                        Text {
                            objectName: "membersEmpty"
                            width: memberTable.width
                            height: page.rowH
                            visible: page.pulse ? page.pulse.members.length === 0 : true
                            text: qsTr("（没有成分行）")
                            color: Theme.textSecondary
                            font.family: Theme.fontFamily
                            font.pixelSize: page.fntSmall
                            verticalAlignment: Text.AlignVCenter
                        }
                    }
                }

                // ── 5. 异动榜：①合格成分（可信）②全市场（含噪音）──
                FSection {
                    objectName: "qualifiedSection"
                    title: qsTr("异动榜 ① 合格成分（过准入 + 流动性门槛，可信） · ")
                           + (page.pulse ? page.pulse.moversNote : "")

                    Column {
                        id: qualifiedTable

                        Layout.fillWidth: true
                        spacing: 0

                        Row {
                            width: qualifiedTable.width
                            height: page.rowH

                            Repeater {
                                model: page.moverHead(qualifiedTable.width)

                                Text {
                                    required property var modelData

                                    width: modelData.w
                                    height: parent.height
                                    leftPadding: modelData.indent
                                    text: modelData.text
                                    color: modelData.color
                                    font.family: Theme.fontFamily
                                    font.pixelSize: modelData.size
                                    font.bold: modelData.bold
                                    horizontalAlignment: modelData.right ? Text.AlignRight : Text.AlignLeft
                                    verticalAlignment: Text.AlignVCenter
                                    elide: Text.ElideRight
                                }
                            }
                        }

                        Repeater {
                            model: page.pulse ? page.pulse.qualifiedMovers : []

                            Rectangle {
                                id: qualifiedRow

                                required property var modelData
                                required property int index

                                width: qualifiedTable.width
                                height: page.rowH
                                color: index % 2 === 1 ? Theme.bgDark : Theme.bgSurface

                                Row {
                                    anchors.fill: parent

                                    Repeater {
                                        model: page.moverRow(qualifiedRow.modelData, qualifiedTable.width)

                                        Text {
                                            required property var modelData

                                            width: modelData.w
                                            height: parent.height
                                            leftPadding: modelData.indent
                                            text: modelData.text
                                            color: modelData.color
                                            font.family: Theme.fontFamily
                                            font.pixelSize: modelData.size
                                            font.bold: modelData.bold
                                            horizontalAlignment: modelData.right ? Text.AlignRight : Text.AlignLeft
                                            verticalAlignment: Text.AlignVCenter
                                            elide: Text.ElideRight
                                        }
                                    }
                                }

                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: if (page.pulse)
                                        page.pulse.openMover("qualified", qualifiedRow.index)
                                }
                            }
                        }

                        Text {
                            objectName: "qualifiedEmpty"
                            width: qualifiedTable.width
                            height: page.rowH
                            visible: page.pulse ? page.pulse.qualifiedMovers.length === 0 : true
                            text: qsTr("（没有合格成分异动 —— 样本不足或都在阈值内）")
                            color: Theme.textSecondary
                            font.family: Theme.fontFamily
                            font.pixelSize: page.fntSmall
                            verticalAlignment: Text.AlignVCenter
                        }
                    }
                }

                FSection {
                    objectName: "marketSection"
                    title: qsTr("异动榜 ② 全市场（可能是个别玩家操作，只作线索；涨幅极大值多来自单笔成交，见「薄」标记）")

                    Column {
                        id: marketTable

                        Layout.fillWidth: true
                        spacing: 0

                        Row {
                            width: marketTable.width
                            height: page.rowH

                            Repeater {
                                model: page.moverHead(marketTable.width)

                                Text {
                                    required property var modelData

                                    width: modelData.w
                                    height: parent.height
                                    leftPadding: modelData.indent
                                    text: modelData.text
                                    color: modelData.color
                                    font.family: Theme.fontFamily
                                    font.pixelSize: modelData.size
                                    font.bold: modelData.bold
                                    horizontalAlignment: modelData.right ? Text.AlignRight : Text.AlignLeft
                                    verticalAlignment: Text.AlignVCenter
                                    elide: Text.ElideRight
                                }
                            }
                        }

                        Repeater {
                            model: page.pulse ? page.pulse.marketMovers : []

                            Rectangle {
                                id: marketRow

                                required property var modelData
                                required property int index

                                width: marketTable.width
                                height: page.rowH
                                color: index % 2 === 1 ? Theme.bgDark : Theme.bgSurface

                                Row {
                                    anchors.fill: parent

                                    Repeater {
                                        model: page.moverRow(marketRow.modelData, marketTable.width)

                                        Text {
                                            required property var modelData

                                            width: modelData.w
                                            height: parent.height
                                            leftPadding: modelData.indent
                                            text: modelData.text
                                            color: modelData.color
                                            font.family: Theme.fontFamily
                                            font.pixelSize: modelData.size
                                            font.bold: modelData.bold
                                            horizontalAlignment: modelData.right ? Text.AlignRight : Text.AlignLeft
                                            verticalAlignment: Text.AlignVCenter
                                            elide: Text.ElideRight
                                        }
                                    }
                                }

                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: if (page.pulse)
                                        page.pulse.openMover("market", marketRow.index)
                                }
                            }
                        }

                        Text {
                            objectName: "marketEmpty"
                            width: marketTable.width
                            height: page.rowH
                            visible: page.pulse ? page.pulse.marketMovers.length === 0 : true
                            text: qsTr("（全市场区没有异动数据）")
                            color: Theme.textSecondary
                            font.family: Theme.fontFamily
                            font.pixelSize: page.fntSmall
                            verticalAlignment: Text.AlignVCenter
                        }
                    }
                }

                // ── 6. 数据状态行（各中心快照天数与最后日期）──────
                FSection {
                    objectName: "dataStatusSection"
                    title: qsTr("数据状态（各中心快照天数与最后日期）")

                    Flow {
                        Layout.fillWidth: true
                        spacing: page.pad

                        Repeater {
                            model: page.pulse ? page.pulse.statusRows : []

                            Text {
                                required property var modelData

                                text: modelData.text
                                color: page.tokenColor(modelData.token)
                                font.family: Theme.fontFamily
                                font.pixelSize: page.fntSmall
                            }
                        }
                    }

                    Text {
                        objectName: "statusHint"
                        Layout.fillWidth: true
                        visible: text !== ""
                        text: page.pulse ? page.pulse.statusHint : ""
                        color: Theme.accentYellow
                        font.family: Theme.fontFamily
                        font.pixelSize: page.fntSmall
                        wrapMode: Text.WordWrap
                    }
                }
            }
        }

        // ═══════════════════════════════════════════════════
        //  页面状态栏
        // ═══════════════════════════════════════════════════
        Rectangle {
            objectName: "pulseStatusBar"
            Layout.fillWidth: true
            implicitHeight: Math.max(28, page.fntSmall + 14)
            color: Theme.bgSurface

            Text {
                objectName: "statusText"
                anchors.fill: parent
                anchors.leftMargin: 2 * page.pad
                anchors.rightMargin: 2 * page.pad
                text: page.pulse ? page.pulse.statusText : ""
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntSmall
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideRight
            }
        }
    }

    /* ── 右侧抽屉：BOM 传导链 ────────────────────────────────
     * 宽度 0↔drawerW 做展开动画；内容用固定宽度并右对齐，动画期间文字不会回流。 */
    Rectangle {
        id: scrim

        anchors.fill: parent
        z: 4
        visible: page.pulse ? page.pulse.detailOpen : false
        color: Theme.bgDark
        opacity: 0.45

        MouseArea {
            anchors.fill: parent
            onClicked: if (page.pulse)
                page.pulse.closeDetail()
        }
    }

    Rectangle {
        id: drawer

        objectName: "detailDrawer"
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.right: parent.right
        z: 5
        width: (page.pulse && page.pulse.detailOpen) ? page.drawerW : 0
        visible: width > 0
        clip: true
        color: Theme.bgSurface
        border.width: 1
        border.color: Theme.border

        Behavior on width {
            NumberAnimation {
                duration: Theme.reducedMotion ? 0 : Theme.durationFast
                easing.type: Easing.OutCubic
            }
        }

        ColumnLayout {
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.right: parent.right
            width: page.drawerW
            spacing: 0

            // 抽屉标题栏
            RowLayout {
                Layout.fillWidth: true
                Layout.margins: page.pad
                spacing: page.pad

                Text {
                    objectName: "detailTitle"
                    Layout.fillWidth: true
                    text: page.pulse ? page.pulse.detailTitle : ""
                    color: Theme.textBright
                    font.family: Theme.fontFamily
                    font.pixelSize: Math.round(14 * Theme.fontScale)
                    font.bold: true
                    elide: Text.ElideRight
                    verticalAlignment: Text.AlignVCenter
                }

                FButton {
                    objectName: "detailCloseButton"
                    compact: true
                    text: qsTr("关闭")
                    onClicked: if (page.pulse)
                        page.pulse.closeDetail()
                }
            }

            Text {
                objectName: "detailStatus"
                Layout.fillWidth: true
                Layout.leftMargin: page.pad
                Layout.rightMargin: page.pad
                text: page.pulse ? page.pulse.detailStatus : ""
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntSmall
                wrapMode: Text.WordWrap
            }

            /* ── 交易建议（挂单/卖单该怎么做）───────────────────────
             * 用户口径：「真给我来点挂单、卖单之类的建议」。这里给的是**规则推导**：
             * verdict + 两条具体建议价 + 关键数字（价差/来回费用/日均成交/队列天数）+ 依据，
             * 并明确写「不构成投资建议」——数字口径都在 `market_advice_service` 里。 */
            FPanel {
                objectName: "advicePanel"
                Layout.fillWidth: true
                Layout.leftMargin: page.pad
                Layout.rightMargin: page.pad
                Layout.topMargin: page.pad
                visible: page.pulse ? page.pulse.advice.verdict !== undefined
                                      && page.pulse.advice.verdict !== "" : false
                implicitHeight: adviceCol.implicitHeight + 2 * page.pad

                ColumnLayout {
                    id: adviceCol
                    anchors.fill: parent
                    anchors.margins: page.pad
                    spacing: 3

                    RowLayout {
                        Layout.fillWidth: true

                        Text {
                            objectName: "adviceTitle"
                            text: page.pulse ? page.pulse.advice.title : ""
                            color: page.pulse ? page.tokenColor(page.pulse.advice.token) : Theme.textPrimary
                            font.family: Theme.fontFamily
                            font.pixelSize: page.fntBase
                            font.bold: true
                            elide: Text.ElideRight
                        }

                        Item {
                            Layout.fillWidth: true
                        }

                        Text {
                            text: qsTr("挂单建议")
                            color: Theme.textSecondary
                            font.family: Theme.fontFamily
                            font.pixelSize: page.fntSmall
                        }
                    }

                    // 关键数字：为什么这么建议，摊开给用户看
                    Repeater {
                        model: page.pulse ? page.pulse.advice.metrics : []

                        RowLayout {
                            required property var modelData

                            Layout.fillWidth: true
                            spacing: page.pad

                            Text {
                                Layout.preferredWidth: Math.round(150 * Theme.fontScale)
                                text: modelData.label
                                color: Theme.textSecondary
                                font.family: Theme.fontFamily
                                font.pixelSize: page.fntSmall
                                elide: Text.ElideRight
                            }

                            Text {
                                Layout.fillWidth: true
                                text: modelData.value
                                color: Theme.textPrimary
                                font.family: Theme.fontFamily
                                font.pixelSize: page.fntSmall
                                elide: Text.ElideRight
                            }
                        }
                    }

                    Text {
                        objectName: "adviceBuy"
                        Layout.fillWidth: true
                        text: page.pulse ? page.pulse.advice.buyAdvice : ""
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: page.fntSmall
                        wrapMode: Text.WordWrap
                        lineHeight: 1.2
                    }

                    Text {
                        objectName: "adviceSell"
                        Layout.fillWidth: true
                        text: page.pulse ? page.pulse.advice.sellAdvice : ""
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: page.fntSmall
                        wrapMode: Text.WordWrap
                        lineHeight: 1.2
                    }

                    Repeater {
                        model: page.pulse ? page.pulse.advice.reasons : []

                        Text {
                            required property var modelData

                            Layout.fillWidth: true
                            text: "· " + modelData
                            color: Theme.textSecondary
                            font.family: Theme.fontFamily
                            font.pixelSize: page.fntSmall
                            wrapMode: Text.WordWrap
                            lineHeight: 1.2
                        }
                    }

                    Text {
                        Layout.fillWidth: true
                        text: (page.pulse ? page.pulse.advice.caliber : "") + qsTr("　· 规则推导，不构成投资建议")
                        color: Theme.textSecondary
                        font.family: Theme.fontFamily
                        font.pixelSize: page.fntSmall
                        wrapMode: Text.WordWrap
                    }
                }
            }

            // 传导链表
            Column {
                id: chainTable

                objectName: "chainTable"
                Layout.fillWidth: true
                Layout.topMargin: page.pad
                Layout.leftMargin: page.pad
                Layout.rightMargin: page.pad
                spacing: 0

                Row {
                    width: chainTable.width
                    height: page.rowH

                    Repeater {
                        model: page.chainHead(chainTable.width)

                        Text {
                            required property var modelData

                            width: modelData.w
                            height: parent.height
                            leftPadding: modelData.indent
                            text: modelData.text
                            color: modelData.color
                            font.family: Theme.fontFamily
                            font.pixelSize: modelData.size
                            font.bold: modelData.bold
                            horizontalAlignment: modelData.right ? Text.AlignRight : Text.AlignLeft
                            verticalAlignment: Text.AlignVCenter
                            elide: Text.ElideRight
                        }
                    }
                }

                Repeater {
                    model: page.pulse ? page.pulse.detailRows : []

                    Rectangle {
                        id: chainRow

                        required property var modelData
                        required property int index

                        width: chainTable.width
                        height: page.rowH
                        color: index % 2 === 1 ? Theme.bgDark : Theme.bgSurface

                        // 「未跟涨」高亮：上游涨了、这一环没跟上 —— 计划 §4.1 的重点信号
                        Rectangle {
                            anchors.fill: parent
                            visible: chainRow.modelData.notCaughtUp
                            color: Theme.accentYellow
                            opacity: 0.18
                        }

                        Row {
                            anchors.fill: parent

                            Repeater {
                                model: page.chainRow(chainRow.modelData, chainTable.width)

                                Text {
                                    required property var modelData

                                    width: modelData.w
                                    height: parent.height
                                    leftPadding: modelData.indent
                                    text: modelData.text
                                    color: modelData.color
                                    font.family: Theme.fontFamily
                                    font.pixelSize: modelData.size
                                    font.bold: modelData.bold
                                    horizontalAlignment: modelData.right ? Text.AlignRight : Text.AlignLeft
                                    verticalAlignment: Text.AlignVCenter
                                    elide: Text.ElideRight
                                }
                            }
                        }
                    }
                }
            }

            Text {
                objectName: "chainEmpty"
                Layout.fillWidth: true
                Layout.margins: page.pad
                visible: page.pulse ? page.pulse.detailRows.length === 0 : true
                text: qsTr("（没有可展开的制造链）")
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: page.fntSmall
                wrapMode: Text.WordWrap
            }

            Item {
                Layout.fillHeight: true
            }
        }
    }
}
