import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 估价页 —— 阶段 1 试点页。

   对照 Widgets 版 ui_pyside6/views/estimate_view.py，四个区块逐项对齐：
   导入栏 / 精炼栏 / 主工作区（表格）/ 底部汇总栏。
   所有颜色与尺寸取自 Theme，禁止字面量。
*/
Item {
    id: page

    // 与 Widgets 版 _COLUMNS 的宽度逐列对齐
    readonly property var columnWidths: [50, 160, 70, 110, 120, 120, 80]
    readonly property var columnTitles: ["图标", "名字", "数量", "单价", "卖价合计", "买价合计", "体积 m³"]
    // 可排序列 → 模型字段（与 _SORT_KEYS 对齐；图标列不可排）
    readonly property var sortKeys: [null, "name", "qty", "unit_price", "sell_total", "buy_total", "volume"]

    property int selectedRow: -1
    property int sortColumn: -1
    property bool sortDescending: false

    Rectangle {
        anchors.fill: parent
        color: Theme.bgDark
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // ── 导入栏 ──
        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.spacingSm
            Layout.rightMargin: Theme.spacingSm
            Layout.topMargin: 6
            spacing: Theme.spacingSm

            Text {
                text: qsTr("价格取自")
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fs(12)
            }
            ComboBox {
                id: priceSource
                implicitWidth: 92
                model: bridge ? bridge.priceTypes : []
                currentIndex: 0
                onActivated: bridge.priceType = ["sell", "buy", "avg"][currentIndex]
            }

            FButton {
                text: qsTr("粘贴剪贴板")
                enabled: bridge && !bridge.busy
                onClicked: bridge.paste()
            }

            Text {
                text: qsTr("怎么用")
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fs(12)
                HoverHandler { id: helpHover }
                ToolTip.visible: helpHover.hovered
                ToolTip.text: qsTr("从游戏内复制物品列表（Ctrl+C）\n然后点击「粘贴剪贴板」即可自动估价")
            }

            Item { Layout.fillWidth: true }

            Text {
                text: qsTr("折扣")
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fs(12)
            }
            DoubleSpinBox {
                id: discountBox
                implicitWidth: 96
                from: 0.01
                to: 10.0
                stepSize: 0.01
                decimals: 2
                value: bridge ? bridge.discount : 1.0
                onValueModified: bridge.discount = value
            }
        }

        // ── 精炼栏 ──
        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.spacingSm
            Layout.rightMargin: Theme.spacingSm
            Layout.topMargin: 2
            Layout.bottomMargin: 2
            spacing: Theme.spacingSm

            FButton {
                text: qsTr("一键精炼")
                enabled: bridge && !bridge.busy && bridge.summary.rowCount > 0
                onClicked: bridge.refine(refineMode.currentText, skillPreset.currentText,
                                         Number(gasRate.text || 0), residualCheck.checked)
            }

            Text {
                text: qsTr("模式")
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fs(12)
            }
            ComboBox {
                id: refineMode
                implicitWidth: 80
                model: bridge ? bridge.refineModes : []
                currentIndex: 0
            }

            Text {
                text: qsTr("技能")
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fs(12)
            }
            ComboBox {
                id: skillPreset
                implicitWidth: 104
                model: bridge ? bridge.skillPresets : []
                currentIndex: 0
            }

            Text {
                text: qsTr("气云解压率(%)")
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fs(12)
            }
            TextField {
                id: gasRate
                implicitWidth: 72
                text: "0"
                horizontalAlignment: TextInput.AlignRight
            }

            FButton {
                text: qsTr("刷新")
                enabled: bridge && !bridge.busy
                onClicked: bridge.refreshPrices()
            }

            CheckBox {
                id: residualCheck
                text: qsTr("残余也精炼掉")
            }

            Item { Layout.fillWidth: true }
        }

        // ── 主工作区：表格 ──
        FCard {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.margins: Theme.spacingSm
            interactive: false

            ColumnLayout {
                anchors.fill: parent
                spacing: 0

                // 表头（可点击排序）
                Row {
                    id: headerRow
                    Layout.fillWidth: true
                    height: 30

                    Repeater {
                        model: page.columnTitles.length
                        delegate: Item {
                            required property int index
                            width: page.columnWidths[index]
                            height: headerRow.height

                            Rectangle {
                                anchors.fill: parent
                                color: headerHover.hovered && page.sortKeys[index] !== null
                                       ? Theme.bgHover : "transparent"
                            }
                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                anchors.left: parent.left
                                anchors.leftMargin: Theme.spacingSm
                                text: page.columnTitles[index] + (page.sortColumn === index
                                      ? (page.sortDescending ? " ↓" : " ↑") : "")
                                color: page.sortColumn === index ? Theme.primary : Theme.textSecondary
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fs(11)
                                font.weight: Font.DemiBold
                            }
                            HoverHandler { id: headerHover }
                            TapHandler {
                                onTapped: {
                                    if (page.sortKeys[index] === null)
                                        return
                                    if (page.sortColumn === index)
                                        page.sortDescending = !page.sortDescending
                                    else {
                                        page.sortColumn = index
                                        page.sortDescending = false
                                    }
                                    bridge.model.sort(index, page.sortDescending
                                                      ? Qt.DescendingOrder : Qt.AscendingOrder)
                                }
                            }
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    height: 1
                    color: Theme.border
                }

                TableView {
                    id: table
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true

                    model: bridge ? bridge.model : null
                    columnWidthProvider: function (column) { return page.columnWidths[column] }
                    rowHeightProvider: function () { return 36 }
                    boundsBehavior: Flickable.StopAtBounds

                    ScrollBar.vertical: ScrollBar {}

                    delegate: Rectangle {
                        required property int row
                        required property int column
                        required property var model

                        color: row === page.selectedRow
                               ? Theme.bgSurfaceLight
                               : (row % 2 === 1 ? Qt.rgba(1, 1, 1, 0.02) : "transparent")

                        // 图标列
                        Image {
                            visible: column === 0
                            anchors.centerIn: parent
                            source: visible ? (model.iconUrl || "") : ""
                            sourceSize.width: 32
                            sourceSize.height: 32
                            asynchronous: true
                        }

                        Text {
                            visible: column !== 0
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.leftMargin: Theme.spacingSm
                            anchors.rightMargin: Theme.spacingSm
                            text: {
                                if (column === 1) return model.name
                                if (column === 2) return model.qtyText
                                if (column === 3) return model.unitPriceText
                                if (column === 4) return model.sellTotalText
                                if (column === 5) return model.buyTotalText
                                if (column === 6) return model.volumeText
                                return ""
                            }
                            color: column === 4 ? Theme.accentGreen
                                 : column === 5 ? Theme.accentRed
                                 : column === 3 ? Theme.accentGreen
                                 : Theme.textPrimary
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fs(12)
                            elide: Text.ElideRight
                            horizontalAlignment: column >= 2 ? Text.AlignRight : Text.AlignLeft
                        }

                        TapHandler {
                            acceptedButtons: Qt.LeftButton
                            onTapped: page.selectedRow = row
                        }
                        TapHandler {
                            acceptedButtons: Qt.RightButton
                            onTapped: {
                                page.selectedRow = row
                                rowMenu.popup()
                            }
                        }
                        // 数量列双击内联编辑（对齐 Widgets 版的 setData/EditRole）
                        TapHandler {
                            acceptedButtons: Qt.LeftButton
                            onDoubleTapped: {
                                if (column !== 2)
                                    return
                                page.selectedRow = row
                                qtyEditor.targetRow = row
                                qtyEditor.text = model.qtyText
                                qtyEditor.open()
                            }
                        }
                    }
                }

                Item {
                    visible: !bridge || bridge.summary.rowCount === 0
                    Layout.fillWidth: true
                    Layout.fillHeight: true

                    Text {
                        anchors.centerIn: parent
                        text: qsTr("从游戏内复制物品列表后点击「粘贴剪贴板」，或搜索添加物品")
                        color: Theme.textSecondary
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fs(12)
                    }
                }
            }
        }

        // ── 底部汇总栏 ──
        FCard {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.spacingSm
            Layout.rightMargin: Theme.spacingSm
            Layout.bottomMargin: Theme.spacingSm
            implicitHeight: 96
            interactive: false

            RowLayout {
                anchors.fill: parent
                spacing: Theme.spacingLg

                ColumnLayout {
                    spacing: 2
                    Text {
                        text: qsTr("体积（精炼前）")
                        color: Theme.textSecondary
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fs(11)
                    }
                    Text {
                        text: bridge ? bridge.summary.volume : "—"
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fs(18)
                        font.weight: Font.DemiBold
                    }
                }

                Item { Layout.fillWidth: true }

                GridLayout {
                    columns: 2
                    rowSpacing: 1
                    columnSpacing: Theme.spacingMd

                    Text {
                        text: qsTr("卖价合计")
                        color: Theme.textSecondary; font.family: Theme.fontFamily; font.pixelSize: Theme.fs(11)
                    }
                    Text {
                        text: bridge ? bridge.summary.sell : "—"
                        color: Theme.accentGreen; font.family: Theme.fontFamily
                        font.pixelSize: Theme.fs(16); font.weight: Font.DemiBold
                    }
                    Text {
                        text: qsTr("买价合计")
                        color: Theme.textSecondary; font.family: Theme.fontFamily; font.pixelSize: Theme.fs(11)
                    }
                    Text {
                        text: bridge ? bridge.summary.buy : "—"
                        color: Theme.accentRed; font.family: Theme.fontFamily
                        font.pixelSize: Theme.fs(16); font.weight: Font.DemiBold
                    }
                    Text {
                        text: qsTr("买卖均价")
                        color: Theme.textSecondary; font.family: Theme.fontFamily; font.pixelSize: Theme.fs(11)
                    }
                    Text {
                        text: bridge ? bridge.summary.avg : "—"
                        color: Theme.textPrimary; font.family: Theme.fontFamily
                        font.pixelSize: Theme.fs(16); font.weight: Font.DemiBold
                    }
                }

                Item { Layout.fillWidth: true }

                GridLayout {
                    columns: 2
                    columnSpacing: Theme.spacingSm
                    rowSpacing: Theme.spacingXs

                    FButton {
                        text: qsTr("卖价到剪贴板")
                        onClicked: bridge.copyTotals("sell")
                    }
                    FButton {
                        text: qsTr("买价到剪贴板")
                        onClicked: bridge.copyTotals("buy")
                    }

                    RowLayout {
                        spacing: Theme.spacingXs
                        Text {
                            text: qsTr("机库")
                            color: Theme.textSecondary; font.family: Theme.fontFamily; font.pixelSize: Theme.fs(11)
                        }
                        ComboBox {
                            id: hangarCombo
                            implicitWidth: 120
                            textRole: "name"
                            valueRole: "id"
                            model: hangarModel
                        }
                    }
                    FButton {
                        text: qsTr("添加到机库")
                        onClicked: bridge.addToHangar(hangarCombo.currentValue)
                    }

                    Item { width: 1; height: 1 }
                    FButton {
                        text: qsTr("更新价格")
                        onClicked: bridge.refreshPrices()
                    }
                }
            }
        }
    }

    ListModel { id: hangarModel }

    function _reloadHangars() {
        hangarModel.clear()
        if (!bridge)
            return
        const list = bridge.hangars()
        for (let i = 0; i < list.length; ++i)
            hangarModel.append(list[i])
    }

    Component.onCompleted: _reloadHangars()

    // ── 右键菜单 ──
    Menu {
        id: rowMenu
        property var rowData: bridge ? bridge.rowAt(page.selectedRow) : ({})

        MenuItem {
            text: qsTr("复制名称")
            enabled: page.selectedRow >= 0
            onTriggered: bridge.copyText(rowMenu.rowData.name || "")
        }
        MenuItem {
            text: qsTr("复制 Type ID")
            visible: (rowMenu.rowData.typeId || 0) > 0
            onTriggered: bridge.copyText(String(rowMenu.rowData.typeId))
        }
        MenuSeparator {}
        MenuItem {
            text: qsTr("修改数量")
            enabled: page.selectedRow >= 0
            onTriggered: {
                qtyEditor.targetRow = page.selectedRow
                qtyEditor.text = String(rowMenu.rowData.qty || 1)
                qtyEditor.open()
            }
        }
        MenuItem {
            text: qsTr("数量翻倍")
            enabled: page.selectedRow >= 0
            onTriggered: bridge.multiplyQty(page.selectedRow, 2)
        }
        MenuItem {
            text: qsTr("修改蓝图")
            enabled: page.selectedRow >= 0
            onTriggered: {
                const bp = bridge.blueprintOf(page.selectedRow)
                bpEditor.targetRow = page.selectedRow
                bpEditor.title = qsTr("蓝图属性 — %1").arg(bp.name)
                meBox.value = bp.me
                teBox.value = bp.te
                bpEditor.open()
            }
        }
        MenuSeparator {}
        MenuItem {
            text: qsTr("删除条目")
            enabled: page.selectedRow >= 0
            onTriggered: {
                bridge.removeRow(page.selectedRow)
                page.selectedRow = -1
            }
        }
        MenuItem {
            text: qsTr("清空表格")
            onTriggered: {
                bridge.clearAll()
                page.selectedRow = -1
            }
        }
    }

    // ── 数量编辑 ──
    Dialog {
        id: qtyEditor
        property int targetRow: -1
        title: qsTr("修改数量")
        modal: true
        anchors.centerIn: parent
        standardButtons: Dialog.Ok | Dialog.Cancel
        implicitWidth: 260

        onAccepted: bridge.setQty(targetRow, Number(qtyField.text))

        TextField {
            id: qtyField
            anchors.fill: parent
            text: qtyEditor.text
            validator: IntValidator { bottom: 1; top: 999999999 }
        }
    }

    // ── 蓝图编辑 ──
    Dialog {
        id: bpEditor
        property int targetRow: -1
        modal: true
        anchors.centerIn: parent
        standardButtons: Dialog.Ok | Dialog.Cancel
        implicitWidth: 300

        onAccepted: bridge.setBlueprint(targetRow, meBox.value, teBox.value)

        GridLayout {
            anchors.fill: parent
            columns: 2
            columnSpacing: Theme.spacingSm

            Text {
                text: qsTr("材料效率 (ME):")
                color: Theme.textPrimary; font.family: Theme.fontFamily; font.pixelSize: Theme.fs(12)
            }
            SpinBox { id: meBox; from: 0; to: 10 }

            Text {
                text: qsTr("时间效率 (TE):")
                color: Theme.textPrimary; font.family: Theme.fontFamily; font.pixelSize: Theme.fs(12)
            }
            SpinBox { id: teBox; from: 0; to: 20 }
        }
    }

    // ── 精炼结果 ──
    Dialog {
        id: refineDialog
        title: qsTr("精炼产出估算")
        modal: true
        anchors.centerIn: parent
        standardButtons: Dialog.Close
        implicitWidth: 640
        implicitHeight: 460

        // 不能叫 result —— Dialog 自带 FINAL 的 result（done() 的结果码）
        property var refineData: ({})

        ColumnLayout {
            anchors.fill: parent
            spacing: Theme.spacingSm

            Text {
                Layout.fillWidth: true
                text: {
                    const r = refineDialog.refineData
                    if (!r || r.total_input_value === undefined)
                        return ""
                    return qsTr("原材料价值: %1 ISK　|　精炼产物价值: %2 ISK　|　利润: %3 ISK")
                        .arg(Math.round(r.total_input_value).toLocaleString(Qt.locale(), 'f', 0))
                        .arg(Math.round(r.total_output_value).toLocaleString(Qt.locale(), 'f', 0))
                        .arg(Math.round(r.total_profit).toLocaleString(Qt.locale(), 'f', 0))
                }
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fs(13)
                wrapMode: Text.WordWrap
            }

            ListView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                model: refineDialog.refineData.items || []
                spacing: Theme.spacingSm

                delegate: ColumnLayout {
                    required property var modelData
                    width: ListView.view.width
                    spacing: 2

                    Text {
                        text: qsTr("%1 ×%2　产率 %3%　精炼前 %4　精炼后 %5")
                            .arg(modelData.input_name)
                            .arg(modelData.input_qty)
                            .arg((modelData.yield_rate * 100).toFixed(1))
                            .arg(Math.round(modelData.input_value).toLocaleString(Qt.locale(), 'f', 0))
                            .arg(Math.round(modelData.output_value).toLocaleString(Qt.locale(), 'f', 0))
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fs(12)
                    }
                    Repeater {
                        model: modelData.output || []
                        delegate: Text {
                            required property var modelData
                            text: qsTr("　• %1　%2　@ %3")
                                .arg(modelData.name)
                                .arg(modelData.qty.toFixed(1))
                                .arg(modelData.price.toLocaleString(Qt.locale(), 'f', 2))
                            color: Theme.textSecondary
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fs(11)
                        }
                    }
                }
            }

            Text {
                Layout.fillWidth: true
                visible: (refineDialog.refineData.errors || []).length > 0
                text: qsTr("警告: %1 项计算失败").arg((refineDialog.refineData.errors || []).length)
                color: Theme.accentRed
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fs(11)
            }
        }
    }

    Connections {
        target: bridge
        function onRefineResult(result) {
            refineDialog.refineData = result
            refineDialog.open()
        }
        function onStatusChanged(message) {
            if (shell)
                shell.setStatus(message)
        }
    }
}
