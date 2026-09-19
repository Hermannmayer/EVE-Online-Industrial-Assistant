import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 机库设置对话框（阶段 4b 收尾）。
 *
 * 两个 Tab 与 Widgets 版一一对应：
 *   1) 机库配置 —— 左边机库增删改 + 列表，右边当前机库的编辑区（星系 / 设施类型 / 设施税 /
 *      结构改装件 / 加成汇总）。编辑区放在 `Flickable` 里：改件按制造类别分组，索迪约那一档
 *      有十几组，不滚动会把窗口撑破。
 *   2) 默认机库 —— 科研 / 制造材料 / 制造产出 / 商业四个默认机库下拉。
 *
 * **编辑区为什么包在 `Repeater` 里**：QML 里 `FSpinBox.value` / `FComboBox.currentIndex` 是
 * 声明式绑定，用户手动改一次就会打断它；换机库时不重建控件，微调框会留着上一个机库的数值。
 * 桥给的 `editorKey` 在换机库 / 重载列表时递增，`[editorKey]` 一换 `Repeater` 就重建整块
 * 编辑区，绑定随之重建。（`TransferDialog` 靠 ListView 重建规避同一问题，这里没有列表可用。）
 *
 * 删除走**两步确认条**（`requestDelete` → `confirmDelete`），不再弹原生 `QMessageBox`，
 * 也不再弹第二个对话框 —— 这个页面本身已经是 QML 了。
 */

FDialogFrame {
    id: frame

    readonly property var bp: typeof bridge !== "undefined" ? bridge : null
    readonly property int fntBase: Math.round(12 * Theme.fontScale)
    readonly property int fntSmall: Math.round(11 * Theme.fontScale)
    readonly property int labelWidth: Math.round(72 * Theme.fontScale)
    readonly property int gap: Theme.spacingSm

    dlg: frame.bp
    acceptText: qsTr("保存")

    // ══════════════════════════════════════════════════════════
    //  标签栏
    // ══════════════════════════════════════════════════════════

    RowLayout {
        Layout.fillWidth: true
        spacing: frame.gap

        /* 收窄的标签栏要用 `FTabBar`：普通 `TabBar` 把宽度等分给按钮而不看各自的
         * `implicitWidth`，两个标签不等宽时长的那个会被截成省略号。*/
        FTabBar {
            id: tabBar

            TabButton {
                text: qsTr("机库配置")
            }
            TabButton {
                text: qsTr("默认机库")
            }
        }
        Item {
            Layout.fillWidth: true
        }
    }

    StackLayout {
        Layout.fillWidth: true
        Layout.fillHeight: true
        currentIndex: tabBar.currentIndex

        // ══════════════════════════════════════════════════════
        //  Tab 1：机库配置
        // ══════════════════════════════════════════════════════

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: frame.gap

            // ── 左：增删改 + 机库列表 ──
            ColumnLayout {
                /* 宽度**三个都要钉死**（只给 preferredWidth 会被 RowLayout 撑开，
                 * 右侧编辑区就被挤成 3px 宽、看起来像整块没了）。
                 * 同一条教训 `LauncherWindow.qml` 的动作槽已经写过一次。 */
                readonly property int paneWidth: Math.round(240 * Theme.fontScale)
                Layout.preferredWidth: paneWidth
                Layout.minimumWidth: paneWidth
                Layout.maximumWidth: paneWidth
                Layout.fillWidth: false
                Layout.fillHeight: true
                spacing: frame.gap

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.spacingXs

                    FButton {
                        text: qsTr("新建机库")
                        onClicked: if (frame.bp)
                            frame.bp.newHangar()
                    }
                    FButton {
                        text: qsTr("重命名")
                        onClicked: if (frame.bp)
                            frame.bp.renameHangar()
                    }
                    FButton {
                        objectName: "deleteHangarBtn"
                        text: qsTr("删除")
                        onClicked: if (frame.bp)
                            frame.bp.requestDelete()
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    color: Theme.bgSurface
                    radius: Theme.radius
                    border.width: 1
                    border.color: Theme.border

                    ListView {
                        id: hangarList
                        anchors.fill: parent
                        anchors.margins: 1
                        clip: true
                        //: 选中行只由桥决定（行内高亮比较 currentRow）—— 不绑 currentIndex，
                        //: 否则用户按方向键会让 ListView 自己改 currentIndex 并打断绑定
                        keyNavigationEnabled: false
                        activeFocusOnTab: false
                        model: frame.bp ? frame.bp.hangarLabels : []
                        boundsBehavior: Flickable.StopAtBounds

                        ScrollBar.vertical: ScrollBar {
                            policy: ScrollBar.AsNeeded
                        }

                        delegate: Item {
                            id: hangarRow
                            required property var modelData
                            required property int index

                            width: hangarList.width
                            implicitHeight: Math.round(30 * Theme.fontScale)

                            readonly property bool selected: frame.bp ? frame.bp.currentRow === hangarRow.index : false

                            Rectangle {
                                anchors.fill: parent
                                color: hangarRow.selected ? Theme.bgSurfaceLight : "transparent"
                            }

                            Text {
                                anchors.fill: parent
                                anchors.leftMargin: Theme.spacingSm
                                anchors.rightMargin: Theme.spacingSm
                                verticalAlignment: Text.AlignVCenter
                                text: hangarRow.modelData
                                color: hangarRow.selected ? Theme.textBright : Theme.textPrimary
                                font.family: Theme.fontFamily
                                font.pixelSize: Math.round(13 * Theme.fontScale)
                                elide: Text.ElideRight
                            }

                            MouseArea {
                                anchors.fill: parent
                                onClicked: if (frame.bp)
                                    frame.bp.selectHangar(hangarRow.index)
                            }
                        }
                    }
                }
            }

            /* ── 右：当前机库编辑区 ──
               `Repeater` 用来在 `editorKey` 变化时**重建**编辑区（切换机库要清掉内部状态），
               但 **Repeater 的代理项不被 Layout 布局** —— 直接把 Repeater 当 RowLayout 的子项，
               面板会以 0×0 落在布局原点、从左侧列表底下铺开（实测：右侧面板压住列表右缘）。
               所以外面套一层被布局的 Item，面板改锚定它。 */
            Item {
                Layout.fillWidth: true
                Layout.fillHeight: true

                Repeater {
                    model: frame.bp ? [frame.bp.editorKey] : []

                    Flickable {
                        id: editorPane
                        anchors.fill: parent
                        visible: frame.bp ? frame.bp.hasHangars : false
                        clip: true
                        contentWidth: width
                        contentHeight: editorCol.implicitHeight
                        boundsBehavior: Flickable.StopAtBounds

                        ScrollBar.vertical: ScrollBar {
                            policy: ScrollBar.AsNeeded
                        }

                        ColumnLayout {
                            id: editorCol
                            width: editorPane.width
                            spacing: frame.gap

                            // ── 所在星系 ──
                            FSection {
                                title: qsTr("所在星系（成本指数）")

                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: frame.gap

                                    Text {
                                        Layout.fillWidth: true
                                        text: frame.bp ? frame.bp.systemText : qsTr("未设置")
                                        color: Theme.textPrimary
                                        font.family: Theme.fontFamily
                                        font.pixelSize: frame.fntBase
                                        elide: Text.ElideRight
                                    }
                                    FButton {
                                        text: qsTr("选择星系…")
                                        onClicked: if (frame.bp)
                                            frame.bp.pickSystem()
                                    }
                                    FButton {
                                        text: qsTr("清除")
                                        onClicked: if (frame.bp)
                                            frame.bp.clearSystem()
                                    }
                                }
                            }

                            // ── 设施类型 ──
                            FSection {
                                title: qsTr("设施类型（结构本体加成）")

                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: frame.gap

                                    Text {
                                        Layout.preferredWidth: frame.labelWidth
                                        horizontalAlignment: Text.AlignRight
                                        text: qsTr("设施类型:")
                                        color: Theme.textPrimary
                                        font.family: Theme.fontFamily
                                        font.pixelSize: frame.fntBase
                                    }
                                    FComboBox {
                                        objectName: "facilityBox"
                                        Layout.preferredWidth: Math.round(220 * Theme.fontScale)
                                        textRole: "label"
                                        model: frame.bp ? frame.bp.facilityOptions : []
                                        currentIndex: frame.bp ? frame.bp.facilityIndex : 0
                                        onActivated: if (frame.bp)
                                            frame.bp.setFacilityIndex(currentIndex)
                                    }
                                    Item {
                                        Layout.fillWidth: true
                                    }
                                }

                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: frame.gap

                                    Text {
                                        Layout.preferredWidth: frame.labelWidth
                                        horizontalAlignment: Text.AlignRight
                                        text: qsTr("本体加成:")
                                        color: Theme.textPrimary
                                        font.family: Theme.fontFamily
                                        font.pixelSize: frame.fntBase
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: frame.bp ? frame.bp.baseBonusText : ""
                                        color: Theme.textSecondary
                                        font.family: Theme.fontFamily
                                        font.pixelSize: frame.fntBase
                                        wrapMode: Text.WordWrap
                                    }
                                }
                            }

                            // ── 设施税 ──
                            FSection {
                                title: qsTr("设施税")

                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: frame.gap

                                    FDoubleSpinBox {
                                        objectName: "taxBox"
                                        Layout.preferredWidth: Math.round(140 * Theme.fontScale)
                                        from: 0
                                        to: 100
                                        decimals: 3
                                        value: frame.bp ? frame.bp.taxValue : 0.25
                                        enabled: frame.bp ? !frame.bp.taxFollowDefault : true
                                        onValueModified: if (frame.bp)
                                            frame.bp.setTaxValue(value)
                                    }
                                    // QML 的微调框没有 `suffix`（写了会连输入解析一起坏掉），
                                    // 单位单独一个 Text，避免动 `valueFromText` 那套。
                                    Text {
                                        text: qsTr("%")
                                        color: Theme.textSecondary
                                        font.family: Theme.fontFamily
                                        font.pixelSize: frame.fntBase
                                    }
                                    FCheckBox {
                                        objectName: "taxDefaultBox"
                                        text: qsTr("跟随默认（不单独设置）")
                                        checked: frame.bp ? frame.bp.taxFollowDefault : true
                                        onToggled: if (frame.bp)
                                            frame.bp.setTaxFollowDefault(checked)
                                    }
                                    Item {
                                        Layout.fillWidth: true
                                    }
                                }
                            }

                            // ── 结构改装件 ──
                            FSection {
                                title: qsTr("结构改装件（每制造类别最多 1 个）")

                                Repeater {
                                    model: frame.bp ? frame.bp.rigGroups : []

                                    FSection {
                                        id: rigGroup
                                        required property var modelData
                                        required property int index

                                        title: rigGroup.modelData.label

                                        Repeater {
                                            model: rigGroup.modelData.items

                                            FCheckBox {
                                                required property var modelData
                                                Layout.fillWidth: true
                                                text: modelData.text
                                                checked: modelData.checked
                                                onToggled: if (frame.bp)
                                                    frame.bp.setRigChecked(modelData.typeId, checked)
                                            }
                                        }
                                    }
                                }
                            }

                            // ── 加成汇总 ──
                            Text {
                                Layout.fillWidth: true
                                text: frame.bp ? frame.bp.summaryText : ""
                                color: Theme.textSecondary
                                font.family: Theme.fontFamily
                                font.pixelSize: frame.fntSmall
                                wrapMode: Text.WordWrap
                            }
                        }
                    }
                }

                // 没有机库时的空态（编辑区整块隐藏，这里给一句可执行的提示）
                Text {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    visible: frame.bp ? !frame.bp.hasHangars : true
                    text: qsTr("还没有机库，点左上角「新建机库」开始")
                    color: Theme.textSecondary
                    font.family: Theme.fontFamily
                    font.pixelSize: frame.fntBase
                    wrapMode: Text.WordWrap
                }
            }

            // ══════════════════════════════════════════════════════
            //  Tab 2：默认机库
            // ══════════════════════════════════════════════════════

            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: frame.gap

                FSection {
                    title: qsTr("默认机库（决定材料来源 / 产品去向）")

                    Repeater {
                        model: frame.bp ? frame.bp.defaultRows : []

                        RowLayout {
                            required property var modelData

                            Layout.fillWidth: true
                            spacing: frame.gap

                            Text {
                                Layout.preferredWidth: Math.round(150 * Theme.fontScale)
                                horizontalAlignment: Text.AlignRight
                                text: modelData.label + ":"
                                color: Theme.textPrimary
                                font.family: Theme.fontFamily
                                font.pixelSize: frame.fntBase
                            }
                            FComboBox {
                                Layout.preferredWidth: Math.round(240 * Theme.fontScale)
                                textRole: "label"
                                model: modelData.options
                                currentIndex: modelData.index
                                onActivated: if (frame.bp)
                                    frame.bp.setDefaultIndex(modelData.key, currentIndex)
                            }
                            Item {
                                Layout.fillWidth: true
                            }
                        }
                    }
                }

                Item {
                    Layout.fillHeight: true
                }
            }
        }

        // ══════════════════════════════════════════════════════════
        //  删除确认条（两步确认的第二步）
        // ══════════════════════════════════════════════════════════

        Rectangle {
            objectName: "deleteConfirmBar"
            Layout.fillWidth: true
            visible: frame.bp ? frame.bp.confirmVisible : false
            implicitHeight: confirmCol.implicitHeight + 2 * Theme.spacingSm
            color: Theme.bgSurface
            radius: Theme.radius
            border.width: 1
            border.color: Theme.accentOrange

            ColumnLayout {
                id: confirmCol
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: Theme.spacingSm
                spacing: Theme.spacingXs

                Text {
                    Layout.fillWidth: true
                    text: frame.bp ? frame.bp.confirmTitle : ""
                    color: Theme.accentOrange
                    font.family: Theme.fontFamily
                    font.pixelSize: frame.fntBase
                    font.bold: true
                    wrapMode: Text.WordWrap
                }

                Repeater {
                    model: frame.bp ? frame.bp.confirmReferences : []

                    Text {
                        required property var modelData

                        Layout.fillWidth: true
                        text: "    • " + modelData
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: frame.fntBase
                        elide: Text.ElideRight
                    }
                }

                Text {
                    Layout.fillWidth: true
                    visible: text !== ""
                    text: frame.bp ? frame.bp.confirmNote : ""
                    color: Theme.textSecondary
                    font.family: Theme.fontFamily
                    font.pixelSize: frame.fntSmall
                    wrapMode: Text.WordWrap
                }

                RowLayout {
                    Layout.fillWidth: true
                    visible: frame.bp ? frame.bp.showRepoint : false
                    spacing: frame.gap

                    Text {
                        text: qsTr("将上述引用改为：")
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: frame.fntBase
                    }
                    FComboBox {
                        objectName: "repointBox"
                        Layout.fillWidth: true
                        textRole: "label"
                        model: frame.bp ? frame.bp.repointOptions : []
                        currentIndex: frame.bp ? frame.bp.repointIndex : 0
                        onActivated: if (frame.bp)
                            frame.bp.setRepointIndex(currentIndex)
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: frame.gap

                    Item {
                        Layout.fillWidth: true
                    }
                    FButton {
                        objectName: "confirmDeleteBtn"
                        text: qsTr("删除")
                        onClicked: if (frame.bp)
                            frame.bp.confirmDelete()
                    }
                    FButton {
                        text: qsTr("取消删除")
                        onClicked: if (frame.bp)
                            frame.bp.cancelDelete()
                    }
                }
            }
        }
    }
}
