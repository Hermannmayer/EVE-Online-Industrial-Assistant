import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 蓝图导入预览对话框（阶段 4b）。
 *
 * 对照 Widgets 版 `BlueprintImportReviewDialog`：工具栏（导入模式 + 全选/取消全选）→
 * 逐行勾选表（现有一列与「最终」一列）→ 底部统计行 → 确定导入/取消。
 *
 * 与只读汇总表不同，这里第一列是复选框、最后一列在**全量模式**下可编辑，所以不用
 * `FSummaryTable`，照 `BlueprintPickerDialog` 的做法自绘表头 + ListView。
 *
 * 「最终」列用 `FTextField` + `onEditingFinished`：提交（回车/失焦）才回桥，避免逐字符
 * 回调重建整个 ListView 把焦点弄丢（原版 `itemChanged` 也是提交时才发）。
 *
 * 逐行勾选同理**不重建行模型**（2026-09-27）：勾选只打桥的 `checkRevision` 心跳，QML 的
 * 复选框按心跳回读。原先 `toggleCheck()` 会让桥重建 `rows`，而这里的 `model` 是普通 var
 * 列表 → `ListView` 整体重建 → **滚动位置回顶**：滑到中段取消一行，列表直接跳回最顶端。
 *
 * 颜色 / 增减规则全在桥里算好（token），这里只把 token 翻成主题色。
 */

FDialogFrame {
    id: frame

    readonly property var rv: typeof bridge !== "undefined" ? bridge : null

    dlg: frame.rv
    acceptText: qsTr("确定导入")

    //: 各列宽度；「蓝图」列吃满剩余宽度
    readonly property int colCheck: Math.round(40 * Theme.fontScale)
    readonly property int colAttr: Math.round(180 * Theme.fontScale)
    readonly property int colQty: Math.round(68 * Theme.fontScale)
    readonly property int colFinal: Math.round(94 * Theme.fontScale)

    function tokenColor(token) {
        switch (token) {
        case "ACCENT_GREEN":
            return Theme.accentGreen;
        case "ACCENT_RED":
            return Theme.accentRed;
        case "ACCENT_ORANGE":
            return Theme.accentOrange;
        case "TEXT_SECONDARY":
            return Theme.textSecondary;
        default:
            return Theme.textPrimary;
        }
    }

    // ── 工具栏：导入模式 + 全选/取消全选 ──
    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.spacingSm

        Text {
            text: qsTr("导入模式:")
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }

        FComboBox {
            objectName: "modeBox"
            Layout.preferredWidth: Math.round(140 * Theme.fontScale)
            textRole: "label"
            model: frame.rv ? frame.rv.modes : []
            currentIndex: frame.rv ? frame.rv.modeIndex : 0
            onActivated: if (frame.rv)
                frame.rv.setModeIndex(currentIndex)
        }

        Item {
            Layout.fillWidth: true
        }

        FButton {
            objectName: "selectAllBtn"
            text: qsTr("全选")
            onClicked: if (frame.rv)
                frame.rv.selectAll()
        }

        FButton {
            objectName: "deselectAllBtn"
            text: qsTr("取消全选")
            onClicked: if (frame.rv)
                frame.rv.deselectAll()
        }
    }

    // ── 表头 ──
    Rectangle {
        Layout.fillWidth: true
        implicitHeight: Math.round(26 * Theme.fontScale)
        color: Theme.bgSurfaceLight

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: Theme.spacingSm
            anchors.rightMargin: Theme.spacingSm
            spacing: Theme.spacingSm

            Text {
                Layout.preferredWidth: frame.colCheck
                horizontalAlignment: Text.AlignHCenter
                text: qsTr("勾选")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(12 * Theme.fontScale)
                elide: Text.ElideRight
            }
            Text {
                Layout.fillWidth: true
                text: qsTr("蓝图")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(12 * Theme.fontScale)
                elide: Text.ElideRight
            }
            Text {
                Layout.preferredWidth: frame.colAttr
                text: qsTr("属性")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(12 * Theme.fontScale)
                elide: Text.ElideRight
            }
            Text {
                Layout.preferredWidth: frame.colQty
                horizontalAlignment: Text.AlignHCenter
                text: qsTr("现有")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(12 * Theme.fontScale)
            }
            Text {
                Layout.preferredWidth: frame.colQty
                horizontalAlignment: Text.AlignHCenter
                text: qsTr("剪贴板")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(12 * Theme.fontScale)
            }
            Text {
                Layout.preferredWidth: frame.colQty
                horizontalAlignment: Text.AlignHCenter
                text: qsTr("增减")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(12 * Theme.fontScale)
            }
            Text {
                Layout.preferredWidth: frame.colFinal
                horizontalAlignment: Text.AlignHCenter
                text: qsTr("最终")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(12 * Theme.fontScale)
            }
        }
    }

    // ── 数据行 ──
    Rectangle {
        Layout.fillWidth: true
        Layout.fillHeight: true
        color: Theme.bgSurface
        radius: Theme.radius
        border.width: 1
        border.color: Theme.border

        ListView {
            id: rowList
            anchors.fill: parent
            anchors.margins: 1
            clip: true
            model: frame.rv ? frame.rv.rows : []
            boundsBehavior: Flickable.StopAtBounds

            ScrollBar.vertical: ScrollBar {
                policy: ScrollBar.AsNeeded
            }

            delegate: Item {
                id: rowItem
                required property var modelData
                required property int index

                width: rowList.width
                implicitHeight: Math.round(28 * Theme.fontScale)

                Rectangle {
                    anchors.fill: parent
                    color: rowItem.index % 2 === 0 ? Theme.bgSurface : Theme.bgDark
                }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: Theme.spacingSm
                    anchors.rightMargin: Theme.spacingSm
                    spacing: Theme.spacingSm

                    // 列0：勾选（新增/更新默认勾选；纯删除默认不勾选 —— 策略在桥里）
                    Item {
                        Layout.preferredWidth: frame.colCheck
                        Layout.fillHeight: true

                        /* 勾选态由桥持有（全选 / 取消全选也要能同步回来），QML 只负责画：
                         * 初值取模型里的 `checked`（= 打开那一刻的取舍）；用户点一下 → 交给桥
                         * → 再把桥的回读值写回自己（`checked` 一旦被赋值就与初值绑定脱钩，
                         * 这是 QML 的正常语义）。`Connections` 那条心跳负责批量变化。
                         *
                         * `Component.onCompleted` 的回读是必需的：行被 ListView 回收后重建时，
                         * `modelData.checked` 还是打开那一刻的旧值（勾选不重建 rows），不回读
                         * 就会出现「明明取消了、滑走再滑回来又变回勾上」。 */
                        FCheckBox {
                            id: checkBox
                            anchors.centerIn: parent
                            checked: rowItem.modelData.checked
                            onToggled: {
                                if (!frame.rv)
                                    return
                                frame.rv.toggleCheck(rowItem.index, checked)
                                checkBox.checked = frame.rv.isChecked(rowItem.index)
                            }

                            Component.onCompleted: if (frame.rv)
                                checkBox.checked = frame.rv.isChecked(rowItem.index)

                            Connections {
                                target: frame.rv
                                function onCheckRevisionChanged() {
                                    checkBox.checked = frame.rv ? frame.rv.isChecked(rowItem.index) : false
                                }
                            }
                        }
                    }

                    // 列1：蓝图名
                    Text {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        verticalAlignment: Text.AlignVCenter
                        text: rowItem.modelData.name
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: Math.round(12 * Theme.fontScale)
                        elide: Text.ElideRight
                    }

                    // 列2：属性
                    Text {
                        Layout.preferredWidth: frame.colAttr
                        Layout.fillHeight: true
                        verticalAlignment: Text.AlignVCenter
                        text: rowItem.modelData.attr
                        color: Theme.textSecondary
                        font.family: Theme.fontFamily
                        font.pixelSize: Math.round(12 * Theme.fontScale)
                        elide: Text.ElideRight
                    }

                    // 列3/4/5：现有 / 剪贴板 / 增减
                    Text {
                        Layout.preferredWidth: frame.colQty
                        Layout.fillHeight: true
                        horizontalAlignment: Text.AlignRight
                        verticalAlignment: Text.AlignVCenter
                        text: rowItem.modelData.current
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: Math.round(12 * Theme.fontScale)
                    }
                    Text {
                        Layout.preferredWidth: frame.colQty
                        Layout.fillHeight: true
                        horizontalAlignment: Text.AlignRight
                        verticalAlignment: Text.AlignVCenter
                        text: rowItem.modelData.clip
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: Math.round(12 * Theme.fontScale)
                    }
                    Text {
                        Layout.preferredWidth: frame.colQty
                        Layout.fillHeight: true
                        horizontalAlignment: Text.AlignRight
                        verticalAlignment: Text.AlignVCenter
                        text: rowItem.modelData.delta
                        color: frame.tokenColor(rowItem.modelData.deltaToken)
                        font.family: Theme.fontFamily
                        font.pixelSize: Math.round(12 * Theme.fontScale)
                    }

                    // 列6：最终数量（仅全量模式可编辑；非法值由桥标红）
                    Item {
                        Layout.preferredWidth: frame.colFinal
                        Layout.fillHeight: true

                        Text {
                            anchors.fill: parent
                            visible: !rowItem.modelData.editable
                            horizontalAlignment: Text.AlignRight
                            verticalAlignment: Text.AlignVCenter
                            text: rowItem.modelData.finalText
                            color: frame.tokenColor(rowItem.modelData.finalToken)
                            font.family: Theme.fontFamily
                            font.pixelSize: Math.round(12 * Theme.fontScale)
                        }

                        FTextField {
                            objectName: "finalField"
                            anchors.fill: parent
                            visible: rowItem.modelData.editable
                            horizontalAlignment: Text.AlignRight
                            text: rowItem.modelData.finalText
                            color: frame.tokenColor(rowItem.modelData.finalToken)
                            onEditingFinished: if (frame.rv)
                                frame.rv.setFinal(rowItem.index, text)
                        }
                    }
                }
            }
        }
    }

    // ── 统计栏 ──
    Text {
        Layout.fillWidth: true
        text: frame.rv ? frame.rv.summaryText : ""
        color: Theme.textSecondary
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(11 * Theme.fontScale)
        wrapMode: Text.WordWrap
    }
}
