import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 粘贴导入预览对话框（阶段 4b-3）。
 *
 * 对照 Widgets 版 `ui_pyside6/views/inventory/review_dialog.py::ImportReviewDialog`：
 * 工具栏（导入模式 / 贸易中心 / 全选 / 材料倍率）+ 预览表 + 统计行 + 确定导入。
 *
 * 表格是**自绘**的（`FSummaryTable` 只能只读渲染，这里每行带复选框、可编辑数量、
 * 成本价控件），列标题与列宽都取自桥的 `columns`（width=0 的列吃满剩余），
 * 表头与行用同一组宽度，改列宽只需改桥里那一处。
 *
 * **行区用 Flickable + Column + Repeater，不用 ListView**：`FTableClickArea` 要求
 * 声明成 Flickable 的内联子项（Flickable 的 componentComplete 会把声明子项塞进
 * contentData，事件坐标才是内容坐标）。ListView 不这么做 —— 实测内联子项的 parent
 * 是 ListView 本体、尺寸按视口算，滚动后按 y 算出的行号全错。顺带：原版 QTableWidget
 * 也是「每行都建控件、不做虚拟化」，行数与开销与这里同量级。
 *
 * **行点击一律走 `FTableClickArea`**（不用 TapHandler，理由见该组件头部）；它声明在行
 * 之前并置 `z: -1`，行里除复选框与两个微调框外的区域都点得到它。Ctrl 多选：修饰键在
 * Python 侧读（`FTableClickArea` 只发行列号），QML 只维护 `selRows` 这个 UI 状态。
 *
 * 与原版的差异见 `ui_qml/bridge/review_bridge.py` 的文件头。
 */

FDialogFrame {
    id: frame

    readonly property var rv: typeof bridge !== "undefined" ? bridge : null

    dlg: frame.rv
    acceptText: qsTr("确定导入")

    //: 右键菜单作用的行号（Ctrl+左键多选）—— 纯 UI 状态
    property var selRows: []
    //: 行高（Widgets 版 `verticalHeader().setDefaultSectionSize(32)`）
    readonly property int rowH: Math.round(32 * Theme.fontScale)

    function tokenColor(token) {
        switch (token) {
        case "ACCENT_GREEN":
            return Theme.accentGreen;
        case "ACCENT_RED":
            return Theme.accentRed;
        case "TEXT_SECONDARY":
            return Theme.textSecondary;
        default:
            return Theme.textPrimary;
        }
    }

    //: 第 col 列的固定宽；0 = 吃满剩余（与桥的 `columns` 同口径）
    function colW(col) {
        if (!frame.rv || col >= frame.rv.columns.length)
            return 0;
        return frame.rv.columns[col].width;
    }

    // ── 工具栏 ──
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
            onActivated: {
                if (!frame.rv)
                    return;
                frame.selRows = [];  // 整表重算，旧行号作废
                frame.rv.setModeIndex(currentIndex);
            }
        }

        Text {
            text: qsTr("贸易中心:")
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }

        FComboBox {
            objectName: "hubBox"
            Layout.preferredWidth: Math.round(160 * Theme.fontScale)
            textRole: "label"
            model: frame.rv ? frame.rv.hubs : []
            currentIndex: frame.rv ? frame.rv.hubIndex : 0
            onActivated: if (frame.rv)
                frame.rv.setHubIndex(currentIndex)
        }

        Item {
            Layout.fillWidth: true
        }

        FButton {
            text: qsTr("全选")
            onClicked: if (frame.rv)
                frame.rv.setAllChecked(true)
        }

        FButton {
            text: qsTr("取消全选")
            onClicked: if (frame.rv)
                frame.rv.setAllChecked(false)
        }

        Item {
            Layout.fillWidth: true
        }

        Text {
            text: qsTr("材料倍率:")
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }

        FDoubleSpinBox {
            objectName: "multBox"
            Layout.preferredWidth: Math.round(120 * Theme.fontScale)
            from: frame.rv ? frame.rv.discountMin : 0.1
            to: frame.rv ? frame.rv.discountMax : 10.0
            decimals: 2
            stepSize: 0.05
            value: frame.rv ? frame.rv.discount : 1.0
            onValueModified: if (frame.rv)
                frame.rv.setDiscount(value)
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
            spacing: 0

            Repeater {
                model: frame.rv ? frame.rv.columns : []

                Text {
                    required property var modelData

                    Layout.preferredWidth: modelData.width
                    Layout.fillWidth: modelData.width <= 0
                    Layout.fillHeight: true
                    verticalAlignment: Text.AlignVCenter
                    horizontalAlignment: Text.AlignHCenter
                    text: modelData.title
                    color: Theme.textPrimary
                    font.family: Theme.fontFamily
                    font.pixelSize: Math.round(12 * Theme.fontScale)
                    elide: Text.ElideRight
                }
            }
        }
    }

    // ── 预览表 ──
    Rectangle {
        Layout.fillWidth: true
        Layout.fillHeight: true
        color: Theme.bgSurface
        radius: Theme.radius
        border.width: 1
        border.color: Theme.border

        Flickable {
            id: rowFlick
            objectName: "reviewRowFlick"
            anchors.fill: parent
            anchors.margins: 1
            clip: true
            contentHeight: rowColumn.implicitHeight
            boundsBehavior: Flickable.StopAtBounds

            ScrollBar.vertical: ScrollBar {
                policy: ScrollBar.AsNeeded
            }

            /* 行命中固定在按下那一刻（见 FTableClickArea 头部）。声明在行之前、且 z 压在下层：
             * 行里除复选框与两个微调框外都点得到它，那几个控件自己吃事件、照常可用。 */
            FTableClickArea {
                objectName: "reviewClickArea"
                anchors.fill: parent
                z: -1
                rowHeight: frame.rowH
                columnWidth: null  // 整行一格：本表的操作都以行为单位
                // Flickable 自身不是「表」，命中区推不出行数上限，得显式给（空区不派发）
                rowCountOverride: frame.rv ? frame.rv.rows.length : 0

                onRowClicked: function (row, _column) {
                    if (!frame.rv)
                        return;
                    if (frame.rv.ctrlHeld()) {
                        const next = frame.selRows.slice();
                        const at = next.indexOf(row);
                        if (at >= 0)
                            next.splice(at, 1);
                        else
                            next.push(row);
                        frame.selRows = next;
                    } else {
                        frame.selRows = [row];
                    }
                }
                onRowRightClicked: function (row, _column, x, y) {
                    if (!frame.rv)
                        return;
                    // 右键到未选中行时只操作该行（原版 `_on_context_menu` 的判据）
                    if (frame.selRows.indexOf(row) < 0)
                        frame.selRows = [row];
                    frame.rv.openMenu(frame.selRows);
                    rowMenu.state = frame.rv.menuState(frame.selRows);
                    const p = mapToItem(frame, x, y);
                    rowMenu.x = p.x;
                    rowMenu.y = p.y;
                    rowMenu.open();
                }
            }

            ColumnLayout {
                id: rowColumn
                width: parent.width
                spacing: 0

                Repeater {
                    model: frame.rv ? frame.rv.rows : []

                    Rectangle {
                        id: rowItem
                        required property var modelData
                        required property int index

                        Layout.fillWidth: true
                        implicitHeight: frame.rowH

                        readonly property bool rowSelected: frame.selRows.indexOf(rowItem.index) >= 0

                        color: rowItem.rowSelected
                               ? Theme.bgHover
                               : (rowItem.index % 2 === 0 ? Theme.bgSurface : Theme.bgDark)

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: Theme.spacingSm
                            anchors.rightMargin: Theme.spacingSm
                            spacing: 0

                            // 勾选
                            Item {
                                Layout.preferredWidth: frame.colW(0)
                                Layout.fillHeight: true

                                FCheckBox {
                                    objectName: "rowCheck"
                                    // 复选框的 implicitWidth 是「指示器 + 空文本内边距」算出来的（实测 73px），
                                    // 直接居中会往左溢出 30px 的格子、勾选框贴着表边。收窄到指示器宽度即可。
                                    width: Math.round(20 * Theme.fontScale)
                                    leftPadding: 0
                                    anchors.centerIn: parent
                                    enabled: rowItem.modelData.checkable
                                    checked: rowItem.modelData.checked
                                    onToggled: if (frame.rv)
                                        frame.rv.setChecked(rowItem.index, checked)
                                }
                            }

                            // 图标
                            Item {
                                Layout.preferredWidth: frame.colW(1)
                                Layout.fillHeight: true

                                Image {
                                    anchors.centerIn: parent
                                    width: Math.round(24 * Theme.fontScale)
                                    height: width
                                    visible: source !== ""
                                    source: rowItem.modelData.iconUrl
                                    sourceSize.width: width
                                    sourceSize.height: height
                                    smooth: true
                                    fillMode: Image.PreserveAspectFit
                                }
                            }

                            // 名称（吃满剩余）
                            Text {
                                Layout.fillWidth: true
                                Layout.preferredWidth: 0
                                Layout.leftMargin: Math.round(6 * Theme.fontScale)
                                Layout.fillHeight: true
                                verticalAlignment: Text.AlignVCenter
                                horizontalAlignment: Text.AlignLeft
                                text: rowItem.modelData.name
                                color: rowItem.modelData.unmatched ? Theme.textSecondary : Theme.textPrimary
                                font.family: Theme.fontFamily
                                font.pixelSize: Math.round(12 * Theme.fontScale)
                                elide: Text.ElideRight
                            }

                            // 数量（机库现有）
                            Text {
                                Layout.preferredWidth: frame.colW(3)
                                Layout.rightMargin: Math.round(6 * Theme.fontScale)
                                Layout.fillHeight: true
                                verticalAlignment: Text.AlignVCenter
                                horizontalAlignment: Text.AlignRight
                                text: rowItem.modelData.currentText
                                color: rowItem.modelData.unmatched ? Theme.textSecondary : Theme.textPrimary
                                font.family: Theme.fontFamily
                                font.pixelSize: Math.round(12 * Theme.fontScale)
                            }

                            // 比原纪录（本次增减）
                            Text {
                                Layout.preferredWidth: frame.colW(4)
                                Layout.rightMargin: Math.round(6 * Theme.fontScale)
                                Layout.fillHeight: true
                                verticalAlignment: Text.AlignVCenter
                                horizontalAlignment: Text.AlignRight
                                text: rowItem.modelData.deltaText
                                color: frame.tokenColor(rowItem.modelData.deltaToken)
                                font.family: Theme.fontFamily
                                font.pixelSize: Math.round(12 * Theme.fontScale)
                            }

                            // 变化（最终数量）—— 可编辑，供库存修正逐行修正数量
                            Item {
                                Layout.preferredWidth: frame.colW(5)
                                Layout.fillHeight: true

                                Text {
                                    anchors.fill: parent
                                    visible: rowItem.modelData.unmatched
                                    verticalAlignment: Text.AlignVCenter
                                    horizontalAlignment: Text.AlignRight
                                    text: "0"
                                    color: Theme.textSecondary
                                    font.family: Theme.fontFamily
                                    font.pixelSize: Math.round(12 * Theme.fontScale)
                                }

                                FSpinBox {
                                    objectName: "rowFinal"
                                    anchors.fill: parent
                                    visible: !rowItem.modelData.unmatched
                                    from: 0
                                    to: frame.rv ? frame.rv.maxQty : 2000000000
                                    value: rowItem.modelData.final
                                    onValueModified: if (frame.rv)
                                        frame.rv.setFinal(rowItem.index, value)
                                }
                            }

                            // 成本价
                            FDoubleSpinBox {
                                objectName: "rowPrice"
                                Layout.preferredWidth: frame.colW(6)
                                from: 0
                                to: frame.rv ? frame.rv.maxPrice : 1e12
                                decimals: 2
                                stepSize: 1000
                                enabled: rowItem.modelData.checkable
                                value: rowItem.modelData.price
                                onValueModified: if (frame.rv)
                                    frame.rv.setPrice(rowItem.index, value)
                            }
                        }
                    }
                }
            }
        }

        // 空态
        Text {
            anchors.centerIn: parent
            visible: frame.rv ? frame.rv.rows.length === 0 : true
            text: qsTr("没有可导入的物品")
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(12 * Theme.fontScale)
        }
    }

    // ── 统计栏 ──
    Text {
        Layout.fillWidth: true
        text: frame.rv ? frame.rv.summaryText : ""
        color: Theme.textSecondary
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(11 * Theme.fontScale)
        elide: Text.ElideRight
    }

    // ── 行右键菜单 ──
    FMenu {
        id: rowMenu
        objectName: "reviewMenu"
        property var state: ({})

        FMenuItem {
            text: qsTr("设置为卖单价")
            onTriggered: if (frame.rv)
                frame.rv.setPriceFromMarket("sell")
        }
        FMenuItem {
            text: qsTr("设置为买单价")
            onTriggered: if (frame.rv)
                frame.rv.setPriceFromMarket("buy")
        }
        FMenuItem {
            text: qsTr("设置为均价")
            onTriggered: if (frame.rv)
                frame.rv.setPriceFromMarket("avg")
        }
        FMenuSeparator {}

        FMenuItem {
            text: rowMenu.state.count > 1 ? qsTr("删除选中行 (%1)").arg(rowMenu.state.count) : qsTr("删除该行")
            onTriggered: {
                if (!frame.rv)
                    return;
                frame.rv.deleteRows();
                frame.selRows = [];
            }
        }
        FMenuSeparator {}

        FMenuItem {
            text: qsTr("卖价 × %1").arg(rowMenu.state.discountText || "")
            onTriggered: if (frame.rv)
                frame.rv.applyDiscount("sell")
        }
        FMenuItem {
            text: qsTr("买价 × %1").arg(rowMenu.state.discountText || "")
            onTriggered: if (frame.rv)
                frame.rv.applyDiscount("buy")
        }
        FMenuSeparator {}

        // 来自其他机库（原版无其他机库时整块不出现；FMenu 没有「不可见即压高度」的
        // 兄弟组件，空列表时这里是一个空子菜单）
        FMenu {
            title: qsTr("来自其他机库")
            Repeater {
                model: rowMenu.state.hangars || []

                FMenuItem {
                    required property var modelData
                    text: modelData.name
                    onTriggered: if (frame.rv)
                        frame.rv.addFromHangar(modelData.id)
                }
            }
        }
        FMenuSeparator {}

        FMenuItem {
            text: qsTr("过滤无变化项")
            onTriggered: if (frame.rv)
                frame.rv.filterNoChange()
        }

        // 未匹配行：提供手动搜索匹配（原版只在「选中恰好一行且未匹配」时出现）
        FMenuItem {
            text: qsTr("搜索匹配物品…")
            visible: rowMenu.state.canSearchMatch === true
            onTriggered: {
                if (!frame.rv)
                    return;
                frame.rv.searchMatch();
                frame.selRows = [];
            }
        }
    }
}
