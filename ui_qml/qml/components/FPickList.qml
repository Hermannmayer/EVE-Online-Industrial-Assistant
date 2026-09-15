import QtQuick
import QtQuick.Layouts

/* 搜索选择列表 —— 「输入过滤 → 选一行 → 确定」的共用中段。
 *
 * 星系搜索与物品搜索的对话框形状完全一致（各自还被两处打开），
 * 所以过滤框 + 可选中表格 + 状态行只留这一份；各自的对话框只管标题与按钮。
 *
 * **`source`（桥）的契约**：
 *   rows        当前结果行（`[{cells:[{text,color}]}]`）
 *   currentRow  当前选中行；-1 = 无
 *   statusText  底部状态文案（「共 N 个星系」/「请先选择」之类）
 *   setQuery(text)   过滤词变化
 *   selectRow(row)   选中
 *   activateRow(row) 双击 = 选中并确定
 *
 * 调用方通常还要读 `source.hasSelection` 决定「确定」是否可点。
 */

ColumnLayout {
    id: root

    //: 数据来源（桥）
    property var source: null
    //: 列定义（交给 `FSummaryTable`）
    property var columns: []
    //: 过滤框占位文案
    property string placeholder: ""
    //: 过滤框是否可用（例如星系数据没加载时禁用）
    property bool filterEnabled: true
    //: 空表提示（空串 = 不显示）
    property string emptyText: ""

    signal rowPicked(int row)
    signal rowActivated(int row)

    spacing: Theme.spacingSm

    FTextField {
        objectName: "pickFilter"
        Layout.fillWidth: true
        placeholderText: root.placeholder
        enabled: root.filterEnabled
        onTextChanged: if (root.source)
            root.source.setQuery(text)
    }

    FSummaryTable {
        objectName: "pickTable"
        Layout.fillWidth: true
        Layout.fillHeight: true
        columns: root.columns
        rows: root.source ? root.source.rows : []
        selectable: true
        currentRow: root.source ? root.source.currentRow : -1
        emptyText: root.emptyText
        onRowClicked: function (row) {
            if (root.source)
                root.source.selectRow(row);
            root.rowPicked(row);
        }
        onRowDoubleClicked: function (row) {
            if (root.source)
                root.source.activateRow(row);
            root.rowActivated(row);
        }
    }

    Text {
        Layout.fillWidth: true
        text: root.source ? root.source.statusText : ""
        color: Theme.textSecondary
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(11 * Theme.fontScale)
        wrapMode: Text.WordWrap
    }
}
