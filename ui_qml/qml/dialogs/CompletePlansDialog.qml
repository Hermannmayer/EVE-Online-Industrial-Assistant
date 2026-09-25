import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 下线确认（阶段 4）。
 *
 * 清单行由桥算好（产出量 = 流程 × 并行 × 每次产出，口径与 Widgets 版一致），这里只画；
 * 「确认下线」把**每行各自选的**产出机库交回桥。
 *
 * 第 4 列是**逐行下拉**（默认 = 该计划自己配的机库，见桥的 `_initial_index`）；
 * 底部那一个是「统一设为」，一次覆盖全部行。
 */

FDialogFrame {
    id: frame

    readonly property var cp: typeof bridge !== "undefined" ? bridge : null

    dlg: frame.cp
    acceptText: qsTr("确认下线")

    readonly property int colWidthName: Math.round(200 * Theme.fontScale)
    readonly property int colWidthRuns: Math.round(90 * Theme.fontScale)
    readonly property int colWidthQty: Math.round(100 * Theme.fontScale)

    /* 行高必须容得下行内的 `FComboBox`，否则被 `Flickable.clip` **静默裁掉**。
     *
     * 实测（offscreen + FluentWinUI3）：`FComboBox` 覆写了 `background`（普通 Rectangle，
     * 没有 Fluent 图集的 `implicitBackgroundHeight`），所以它的 `implicitHeight` 只有
     * 26（无自定义 app 字体）~ 29（生产字体 Microsoft YaHei UI 10pt），**不是裸
     * `ComboBox` 的 32** —— 那个 32 来自图集的 StyleImage，与本控件无关。
     * 行高按 `Math.round(26 * fontScale)` 时，fontScale ≤ 1.0 就会裁掉 2~3px。
     * 取 32 是覆盖全部实测配置（含 fontScale=0.5）的无风险下界。 */
    readonly property int rowH: Math.max(32, Math.round(32 * Theme.fontScale))

    Text {
        Layout.fillWidth: true
        text: frame.cp ? frame.cp.tipText : ""
        color: Theme.textSecondary
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(12 * Theme.fontScale)
        wrapMode: Text.WordWrap
    }

    // ── 清单 ──
    Rectangle {
        Layout.fillWidth: true
        Layout.fillHeight: true
        color: Theme.bgSurface
        radius: Theme.radius
        border.width: 1
        border.color: Theme.border

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 1
            spacing: 0

            // 表头
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: Math.round(26 * Theme.fontScale)
                color: Theme.bgSurfaceLight

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 8
                    anchors.rightMargin: 8
                    spacing: Theme.spacingSm

                    Repeater {
                        model: [
                            {
                                "text": frame.cp ? frame.cp.headers[0] : "",
                                "width": frame.colWidthName,
                                "align": Text.AlignLeft,
                                "fill": false
                            },
                            {
                                "text": frame.cp ? frame.cp.headers[1] : "",
                                "width": frame.colWidthRuns,
                                "align": Text.AlignRight,
                                "fill": false
                            },
                            {
                                "text": frame.cp ? frame.cp.headers[2] : "",
                                "width": frame.colWidthQty,
                                "align": Text.AlignRight,
                                "fill": false
                            },
                            {
                                "text": frame.cp ? frame.cp.headers[3] : "",
                                "width": 0,
                                "align": Text.AlignLeft,
                                "fill": true
                            }
                        ]

                        Text {
                            required property var modelData
                            Layout.preferredWidth: modelData.fill ? 0 : modelData.width
                            Layout.fillWidth: modelData.fill
                            verticalAlignment: Text.AlignVCenter
                            horizontalAlignment: modelData.align
                            text: modelData.text
                            color: Theme.textPrimary
                            font.family: Theme.fontFamily
                            font.pixelSize: Math.round(12 * Theme.fontScale)
                            elide: Text.ElideRight
                        }
                    }
                }
            }

            Flickable {
                Layout.fillWidth: true
                Layout.fillHeight: true
                contentHeight: rowColumn.implicitHeight
                clip: true

                ColumnLayout {
                    id: rowColumn
                    width: parent.width
                    spacing: 0

                    Repeater {
                        model: frame.cp ? frame.cp.rows : []

                        Rectangle {
                            required property var modelData
                            required property int index

                            Layout.fillWidth: true
                            implicitHeight: frame.rowH
                            color: index % 2 === 0 ? Theme.bgSurface : Theme.bgDark

                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 8
                                anchors.rightMargin: 8
                                spacing: Theme.spacingSm

                                Text {
                                    Layout.preferredWidth: frame.colWidthName
                                    text: modelData.name
                                    color: Theme.textPrimary
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Math.round(12 * Theme.fontScale)
                                    elide: Text.ElideRight
                                }
                                Text {
                                    Layout.preferredWidth: frame.colWidthRuns
                                    horizontalAlignment: Text.AlignRight
                                    text: modelData.runs
                                    color: Theme.textPrimary
                                    font.family: "Consolas"
                                    font.pixelSize: Math.round(12 * Theme.fontScale)
                                }
                                Text {
                                    Layout.preferredWidth: frame.colWidthQty
                                    horizontalAlignment: Text.AlignRight
                                    text: modelData.qty
                                    color: Theme.textPrimary
                                    font.family: "Consolas"
                                    font.pixelSize: Math.round(12 * Theme.fontScale)
                                }
                                /* 第 4 列：**本行自己的**产出机库下拉。
                                 *
                                 * 初值取 `cp.hangarIndexAt(index)`（= 该计划自己存的
                                 * `deposit_hangar_id`，取不到才退化默认值），**不是**底部
                                 * 那个统一值 —— 这正是 d2ac6a2 退化掉的东西。
                                 *
                                 * 绑定里显式读 `hangarRevision` 心跳（先例
                                 * `LauncherWindow.qml:409` 的 `tickRevision` 注释）：`rows`
                                 * 是普通 dict 列表，改它不通知；不过桥同时让 `rows` 带
                                 * notify，委托会整体重建、绑定随之重建 —— 心跳是第二道保险
                                 * （若将来把 rows 改回 constant，这条绑定仍然成立）。 */
                                FComboBox {
                                    Layout.fillWidth: true
                                    model: frame.cp ? frame.cp.hangarNames : []
                                    currentIndex: {
                                        if (!frame.cp)
                                            return 0
                                        frame.cp.hangarRevision
                                        return frame.cp.hangarIndexAt(index)
                                    }
                                    onActivated: if (frame.cp)
                                        frame.cp.setHangarIndexAt(index, currentIndex)
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    // ── 统一设为（批量覆盖）──
    //
    // 它**不再是**「产出机库」的唯一来源：每行有自己的下拉（见上）。这里只在用户主动选
    // 一项时把**所有行**（含已单独改过的行）改成同一个值，见桥的 `setAllHangars`。
    //
    // `currentIndex: -1` = 还没用过 → 显示为空（`FComboBox` 没有 placeholderText 属性，
    // 实测赋值会报 "Cannot assign to non-existent property"，故用 -1 留白，
    // 左边的标签「统一设为:」已经说明它是干什么的）。
    // 用户点过一次之后，Qt 样式的委托会自己把 `currentIndex` 设成所选项（JS 赋值摘掉绑定），
    // 于是这里显示「上次统一设成的值」——那正是它此刻的语义，符合预期。
    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spacingSm

        Text {
            text: qsTr("统一设为:")
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }
        FComboBox {
            Layout.fillWidth: true
            model: frame.cp ? frame.cp.hangarNames : []
            currentIndex: -1
            onActivated: if (frame.cp)
                frame.cp.setAllHangars(currentIndex)
        }
    }

    Text {
        Layout.fillWidth: true
        text: frame.cp ? frame.cp.summaryText : ""
        color: Theme.textSecondary
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(11 * Theme.fontScale)
    }
}
