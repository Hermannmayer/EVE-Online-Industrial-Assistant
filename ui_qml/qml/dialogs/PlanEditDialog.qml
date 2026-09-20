import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 编辑生产计划（阶段 4 的第一个 QML 对话框）。
 *
 * 承载在 `ui_qml/dialog_host.QmlDialog` 里 —— 窗口行为（模态/居中/Esc）是 QDialog 的，
 * 这里只画内容。业务与校验都在 `bridge`（`plan_edit_bridge.py`）里，
 * 与 Widgets 版 `PlanEditDialog.get_updated_data()` 同形。
 *
 * 用的是自己的 `bridge` 而不是页面那套（对话框由 Python 侧 `exec()` 调用）。
 *
 * 布局按「一行一组、相关的两组合并」压到 4~5 行：产品名已在标题栏，不重复占一行；
 * 批量同步勾选内联到流程那行。
 *
 * **机库两行的 `currentIndex` 一律写成对桥属性的声明式绑定**（`dlg.matIndex` /
 * `dlg.depositIndex`，两者都带 `notify=fieldsChanged`）。改材料机库时桥会把
 * `_deposit_index` 一起改掉再发信号，输出机库的下拉就自动跟上了 —— 不需要
 * `Connections` 里手写「读差值再赋值」，那种写法会打断绑定，而且会在下拉展开时
 * 反复重设 `currentIndex`。
 */

Item {
    id: root

    readonly property var dlg: typeof bridge !== "undefined" ? bridge : null

    readonly property int fntBase: Math.round(12 * Theme.fontScale)
    readonly property int gap: Theme.spacingSm
    readonly property int labelWidth: Math.round(68 * Theme.fontScale)
    readonly property int fieldW: Math.round(140 * Theme.fontScale)

    /* 对话框底色。**必须自己铺**：宿主 `PageHost` 透明清屏 + `WA_TranslucentBackground`，
     * 没画到的地方直接透出窗口背后，真窗口抓屏是纯黑（离屏快照反而看不出来，会被补成
     * 调色板底色）。本对话框比 `FDialogFrame` 早，没走那个骨架，所以在这儿自己补一块。*/
    Rectangle {
        anchors.fill: parent
        color: Theme.bgDark
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.spacingMd
        spacing: root.gap

        // ── 行1：流程数 × 并行数（+ 批量同步 + 发明的总尝试）──
        RowLayout {
            Layout.fillWidth: true
            spacing: root.gap

            Text {
                Layout.preferredWidth: root.labelWidth
                horizontalAlignment: Text.AlignRight
                text: root.dlg ? root.dlg.runsLabel : qsTr("流程数")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: root.fntBase
            }
            FSpinBox {
                objectName: "runsBox"
                Layout.preferredWidth: Math.round(88 * Theme.fontScale)
                from: 1
                // 研究行的 runs 就是目标等级，上限走游戏规则（ME 10 / TE 20，见桥的 runsMax）
                to: root.dlg ? root.dlg.runsMax : 99999
                value: root.dlg ? root.dlg.runs : 1
                onValueModified: if (root.dlg)
                    root.dlg.setRuns(value)

                HoverHandler {
                    id: runsHover
                }
                ToolTip.visible: runsHover.hovered && text !== ""
                ToolTip.text: root.dlg ? root.dlg.runsTip : ""
            }
            Text {
                visible: root.dlg ? root.dlg.showParallel : true
                text: qsTr("×")
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: root.fntBase
            }
            FSpinBox {
                objectName: "parBox"
                Layout.preferredWidth: Math.round(88 * Theme.fontScale)
                visible: root.dlg ? root.dlg.showParallel : true
                from: 1
                to: 100
                value: root.dlg ? root.dlg.parallels : 1
                onValueModified: if (root.dlg)
                    root.dlg.setParallels(value)

                HoverHandler {
                    id: parHover
                }
                ToolTip.visible: parHover.hovered && (root.dlg ? root.dlg.parallelTip !== "" : false)
                ToolTip.text: root.dlg ? root.dlg.parallelTip : ""
            }
            Text {
                visible: root.dlg ? root.dlg.showParallel : true
                text: root.dlg ? root.dlg.parallelLabel : qsTr("并行数")
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: root.fntBase
            }
            Text {
                visible: (root.dlg ? root.dlg.totalAttempts : "") !== ""
                text: root.dlg ? root.dlg.totalAttempts : ""
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: root.fntBase
            }
            Item {
                Layout.fillWidth: true
            }
            FCheckBox {
                visible: root.dlg ? root.dlg.batchMode : false
                text: qsTr("同步到所有选中行")
                checked: root.dlg ? root.dlg.syncRuns : false
                onToggled: if (root.dlg)
                    root.dlg.setSyncRuns(checked)
            }
        }

        // ── 行2：ME / TE（只有制造行有意义）──
        RowLayout {
            Layout.fillWidth: true
            visible: root.dlg ? root.dlg.showMeTe : false
            spacing: root.gap

            Text {
                Layout.preferredWidth: root.labelWidth
                horizontalAlignment: Text.AlignRight
                text: qsTr("ME / TE")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: root.fntBase
            }
            FSpinBox {
                objectName: "meBox"
                Layout.preferredWidth: Math.round(88 * Theme.fontScale)
                from: 0
                to: 10
                value: root.dlg ? root.dlg.me : 0
                onValueModified: if (root.dlg)
                    root.dlg.setMe(value)
            }
            FSpinBox {
                objectName: "teBox"
                Layout.preferredWidth: Math.round(88 * Theme.fontScale)
                from: 0
                to: 20
                value: root.dlg ? root.dlg.te : 0
                onValueModified: if (root.dlg)
                    root.dlg.setTe(value)
            }
            Item {
                Layout.fillWidth: true
            }
        }

        // ── 行3：解码器（只有发明行有意义，它同时改产出流程数与成功率）──
        RowLayout {
            Layout.fillWidth: true
            visible: root.dlg ? root.dlg.showDecryptor : false
            spacing: root.gap

            Text {
                Layout.preferredWidth: root.labelWidth
                horizontalAlignment: Text.AlignRight
                text: qsTr("解码器")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: root.fntBase
            }
            FComboBox {
                objectName: "decryptorBox"
                Layout.fillWidth: true
                model: root.dlg ? root.dlg.decryptorLabels : []
                currentIndex: root.dlg ? root.dlg.decryptorIndex : 0
                onActivated: if (root.dlg)
                    root.dlg.setDecryptorIndex(currentIndex)
            }
        }

        // ── 行4：人物 + 备注 ──
        RowLayout {
            Layout.fillWidth: true
            spacing: root.gap

            Text {
                Layout.preferredWidth: root.labelWidth
                horizontalAlignment: Text.AlignRight
                text: qsTr("人物")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: root.fntBase
            }
            FComboBox {
                objectName: "charBox"
                Layout.preferredWidth: root.fieldW
                model: root.dlg ? root.dlg.chars : []
                currentIndex: root.dlg ? root.dlg.charIndex : 0
                onActivated: if (root.dlg)
                    root.dlg.setCharIndex(currentIndex)
            }
            Text {
                Layout.leftMargin: root.gap
                text: qsTr("备注")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: root.fntBase
            }
            FTextField {
                objectName: "notesField"
                Layout.fillWidth: true
                placeholderText: qsTr("备注信息…")
                text: root.dlg ? root.dlg.notes : ""
                onTextChanged: if (root.dlg)
                    root.dlg.setNotes(text)
            }
        }

        // ── 行5：材料机库 / 产出机库（产出默认跟随材料）──
        RowLayout {
            Layout.fillWidth: true
            spacing: root.gap

            Text {
                Layout.preferredWidth: root.labelWidth
                horizontalAlignment: Text.AlignRight
                text: qsTr("材料机库")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: root.fntBase
            }
            FComboBox {
                objectName: "matHangarBox"
                Layout.preferredWidth: root.fieldW
                model: root.dlg ? root.dlg.hangars : []
                currentIndex: root.dlg ? root.dlg.matIndex : 0
                onActivated: if (root.dlg)
                    root.dlg.setMatIndex(currentIndex)
            }
            Text {
                Layout.leftMargin: root.gap
                text: qsTr("产出机库")
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: root.fntBase
            }
            FComboBox {
                objectName: "depositHangarBox"
                Layout.fillWidth: true
                model: root.dlg ? root.dlg.hangars : []
                currentIndex: root.dlg ? root.dlg.depositIndex : 0
                onActivated: if (root.dlg)
                    root.dlg.setDepositIndex(currentIndex)
            }
        }

        /* ── 发明预期结果（只有发明行有）──
         *
         * 数字全部来自桥（`domain.research` 的纯函数），改流程/并行/解码器会实时变。
         * 口径是**期望值**：预期张数 = 总尝试 × 成功率（每次成功产 1 张 BPC）；
         * 与表格「输出」列的「全成功上限」不是一回事，所以文案一律带「预期」二字。
         *
         * 画法抄 `FSlider` 的轨道（Theme.border 轨 + Theme.primary 填充），不引入新组件。
         * 高度刻意压到 ~60px：只留一根 6px 细条 + 一行三格，不加分组标题行。
         */
        Rectangle {
            objectName: "expectPanel"
            Layout.fillWidth: true
            visible: root.dlg ? root.dlg.expectVisible : false
            implicitHeight: expectCol.implicitHeight + 2 * Theme.spacingSm
            radius: Theme.radius
            color: Theme.bgSurface
            border.width: 1
            border.color: Theme.border

            ColumnLayout {
                id: expectCol
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: Theme.spacingSm
                spacing: Math.round(4 * Theme.fontScale)

                // ── 行1：标签 + 成功率条 + 百分比 + 合计流程 ──
                RowLayout {
                    Layout.fillWidth: true
                    spacing: root.gap

                    Text {
                        text: qsTr("发明预期")
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: root.fntBase
                    }
                    Text {
                        Layout.leftMargin: root.gap
                        text: qsTr("成功率")
                        color: Theme.textSecondary
                        font.family: Theme.fontFamily
                        font.pixelSize: root.fntBase - 1
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 6
                        Layout.minimumWidth: Math.round(60 * Theme.fontScale)
                        radius: height / 2
                        color: Theme.border

                        Rectangle {
                            width: Math.max(0, Math.min(1, root.dlg ? root.dlg.expectRate : 0)) * parent.width
                            height: parent.height
                            radius: height / 2
                            color: Theme.primary
                        }
                    }
                    Text {
                        text: root.dlg ? root.dlg.expectRateText : ""
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: root.fntBase
                        font.bold: true
                    }
                    Text {
                        Layout.leftMargin: root.gap
                        text: root.dlg ? root.dlg.expectTotalRunsText : ""
                        color: Theme.textSecondary
                        font.family: Theme.fontFamily
                        font.pixelSize: root.fntBase - 1
                    }
                }

                // ── 行2：三格（每张流程 / 蓝图等级 / 预期张数）──
                RowLayout {
                    Layout.fillWidth: true
                    spacing: root.gap

                    Rectangle {
                        objectName: "expectRunsCell"
                        Layout.fillWidth: true
                        implicitHeight: runsCellCol.implicitHeight + 4
                        radius: Theme.radiusSmall
                        color: Theme.bgSurfaceLight

                        ColumnLayout {
                            id: runsCellCol
                            anchors.fill: parent
                            anchors.margins: 2
                            spacing: 0

                            Text {
                                Layout.alignment: Qt.AlignHCenter
                                text: qsTr("每张")
                                color: Theme.textSecondary
                                font.family: Theme.fontFamily
                                font.pixelSize: root.fntBase - 1
                            }
                            Text {
                                Layout.alignment: Qt.AlignHCenter
                                text: root.dlg ? root.dlg.expectRunsPerBpcText : ""
                                color: Theme.textPrimary
                                font.family: Theme.fontFamily
                                font.pixelSize: root.fntBase
                                font.bold: true
                            }
                        }
                    }

                    Rectangle {
                        objectName: "expectLevelCell"
                        Layout.fillWidth: true
                        implicitHeight: lvlCellCol.implicitHeight + 4
                        radius: Theme.radiusSmall
                        color: Theme.bgSurfaceLight

                        ColumnLayout {
                            id: lvlCellCol
                            anchors.fill: parent
                            anchors.margins: 2
                            spacing: 0

                            Text {
                                Layout.alignment: Qt.AlignHCenter
                                text: qsTr("蓝图等级")
                                color: Theme.textSecondary
                                font.family: Theme.fontFamily
                                font.pixelSize: root.fntBase - 1
                            }
                            Text {
                                Layout.alignment: Qt.AlignHCenter
                                text: root.dlg ? root.dlg.expectMeTeText : ""
                                color: Theme.textPrimary
                                font.family: Theme.fontFamily
                                font.pixelSize: root.fntBase
                                font.bold: true
                            }
                        }
                    }

                    Rectangle {
                        objectName: "expectBpcCell"
                        Layout.fillWidth: true
                        implicitHeight: bpcCellCol.implicitHeight + 4
                        radius: Theme.radiusSmall
                        color: Theme.bgSurfaceLight

                        ColumnLayout {
                            id: bpcCellCol
                            anchors.fill: parent
                            anchors.margins: 2
                            spacing: 0

                            Text {
                                Layout.alignment: Qt.AlignHCenter
                                text: qsTr("预期产出")
                                color: Theme.textSecondary
                                font.family: Theme.fontFamily
                                font.pixelSize: root.fntBase - 1
                            }
                            Text {
                                Layout.alignment: Qt.AlignHCenter
                                text: root.dlg ? root.dlg.expectBpcText : ""
                                color: Theme.textPrimary
                                font.family: Theme.fontFamily
                                font.pixelSize: root.fntBase
                                font.bold: true
                            }
                        }
                    }
                }
            }
        }

        // ── 校验提示 ──
        Text {
            Layout.fillWidth: true
            visible: (root.dlg ? root.dlg.error : "") !== ""
            text: root.dlg ? root.dlg.error : ""
            color: Theme.accentRed
            font.family: Theme.fontFamily
            font.pixelSize: root.fntBase
            horizontalAlignment: Text.AlignRight
        }

        Item {
            Layout.fillHeight: true
        }

        // ── 按钮 ──
        RowLayout {
            Layout.fillWidth: true
            spacing: root.gap

            Item {
                Layout.fillWidth: true
            }
            FButton {
                objectName: "cancelButton"
                text: qsTr("取消")
                onClicked: if (root.dlg)
                    root.dlg.reject()
            }
            FButton {
                objectName: "okButton"
                text: qsTr("确定")
                primary: true
                onClicked: if (root.dlg)
                    root.dlg.accept()
            }
        }
    }
}
