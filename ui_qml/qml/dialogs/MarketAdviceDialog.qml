import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 挂单建议（「可制造物品」窗口右键 → 挂单建议）。
 *
 * 与大盘页 `MarketPulsePane.advicePanel` 同一份服务、同一套措辞：
 * 物品名 → verdict 标题 → 关键数字（价差 / 来回费用 / 近 7 天日均成交 / 卖单队列）
 * → 买 / 卖建议 → 依据 → 口径 +「规则推导，不构成投资建议」。
 *
 * 三条纪律（用户报过「文字超出面板」，这里逐条守住）：
 *   1. **配色一律 `Theme.*`**：桥只给 token 名（`ACCENT_GREEN` / …），`tokenColor()` 翻；
 *      本文件里不准出现 hex / rgb / 颜色名。
 *   2. **不用 `Canvas`**（Qt 的 Canvas 画进离屏纹理，本仓离屏截图路径下整块是空的，
 *      见 `PriceChartDialog.qml` 那段记录）——这里全是场景图元素。
 *   3. **每一条 `Text` 都有边界**：单行用 `elide` + `Layout.fillWidth`（或固定
 *      `Layout.preferredWidth`），长句用 `wrapMode: Text.WordWrap` + `Layout.fillWidth`；
 *      没有宽度的 `elide` 是无效的，等于让文字溢出。内容整体放进 `Flickable`，
 *      字号放大 / 依据条数多也只会滚动，不会把按钮行挤出去。
 *
 * 取数在桥的构造函数里同步做完（只读本地 `market.db`，无网络），所以这里没有「加载中」态：
 * 要么有建议，要么是空态 / 失败说明行。
 */

FDialogFrame {
    id: frame

    readonly property var ma: typeof bridge !== "undefined" ? bridge : null

    dlg: frame.ma
    //: 只读查看器：没有「确定」，只有「关闭」
    acceptVisible: false
    cancelText: qsTr("关闭")

    //: 有建议才排内容；否则给一行空态说明（不是「一片空白」）
    readonly property bool hasAdvice: frame.ma ? frame.ma.verdict !== "" : false

    readonly property int fntTitle: Math.round(15 * Theme.fontScale)
    readonly property int fntBase: Math.round(12 * Theme.fontScale)
    readonly property int fntSmall: Math.round(11 * Theme.fontScale)
    //: 关键数字的标签列宽（值列吃满剩余宽度，两者都 elide）
    readonly property int metricLabelW: Math.round(150 * Theme.fontScale)

    //: 颜色 token → 主题色。**不认得的 token 走次要色**，不猜颜色。
    function tokenColor(token) {
        switch (token) {
        case "ACCENT_GREEN":
            return Theme.accentGreen;
        case "ACCENT_YELLOW":
            return Theme.accentYellow;
        case "ACCENT_RED":
            return Theme.accentRed;
        case "PRIMARY":
            return Theme.primary;
        case "TEXT_SECONDARY":
            return Theme.textSecondary;
        default:
            return Theme.textPrimary;
        }
    }

    // ── 物品名 + Type ID ──
    Text {
        objectName: "adviceHeader"
        Layout.fillWidth: true
        text: frame.ma ? frame.ma.headerText : ""
        color: Theme.textPrimary
        font.family: Theme.fontFamily
        font.pixelSize: frame.fntTitle
        font.bold: true
        elide: Text.ElideRight
    }

    // ── 取数失败说明行（成功时为空串，不占高度）──
    Text {
        objectName: "adviceStatus"
        Layout.fillWidth: true
        visible: text !== ""
        text: frame.ma ? frame.ma.statusText : ""
        color: Theme.accentYellow
        font.family: Theme.fontFamily
        font.pixelSize: frame.fntSmall
        wrapMode: Text.WordWrap
    }

    // ── 空态：说清「没数据」而不是画一屏空的 ──
    Text {
        objectName: "adviceEmpty"
        Layout.fillWidth: true
        visible: !frame.hasAdvice
        text: qsTr("没有取到这只物品的挂单/成交数据 —— 先在主界面「更新价格」补齐本地行情")
        color: Theme.textSecondary
        font.family: Theme.fontFamily
        font.pixelSize: frame.fntBase
        wrapMode: Text.WordWrap
    }

    // ── 建议正文（可滚动：依据多、字号放大都不会把面板撑破）──
    Flickable {
        id: scroll
        Layout.fillWidth: true
        Layout.fillHeight: true
        visible: frame.hasAdvice
        clip: true
        contentHeight: body.implicitHeight
        boundsBehavior: Flickable.StopAtBounds

        ScrollBar.vertical: ScrollBar {
            policy: ScrollBar.AsNeeded
        }

        ColumnLayout {
            id: body
            width: scroll.width
            spacing: Theme.spacingSm

            // ── verdict 标题（颜色按判定档位）──
            Text {
                objectName: "adviceTitle"
                Layout.fillWidth: true
                text: frame.ma ? frame.ma.title : ""
                color: frame.ma ? frame.tokenColor(frame.ma.token) : Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: frame.fntBase
                font.bold: true
                wrapMode: Text.WordWrap
            }

            // ── 关键数字：为什么这么建议，摊开给用户看 ──
            FSection {
                objectName: "adviceMetrics"
                title: qsTr("关键数字")

                Repeater {
                    model: frame.ma ? frame.ma.metrics : []

                    RowLayout {
                        required property var modelData

                        Layout.fillWidth: true
                        spacing: Theme.spacingSm

                        Text {
                            Layout.preferredWidth: frame.metricLabelW
                            text: modelData.label
                            color: Theme.textSecondary
                            font.family: Theme.fontFamily
                            font.pixelSize: frame.fntSmall
                            elide: Text.ElideRight
                        }

                        Text {
                            Layout.fillWidth: true
                            text: modelData.value
                            color: Theme.textPrimary
                            font.family: Theme.fontFamily
                            font.pixelSize: frame.fntSmall
                            elide: Text.ElideRight
                        }
                    }
                }
            }

            // ── 买 / 卖建议 ──
            FSection {
                objectName: "adviceAdvice"
                title: qsTr("买 / 卖建议")

                Text {
                    objectName: "adviceBuy"
                    Layout.fillWidth: true
                    text: frame.ma ? frame.ma.buyAdvice : ""
                    color: Theme.textPrimary
                    font.family: Theme.fontFamily
                    font.pixelSize: frame.fntBase
                    wrapMode: Text.WordWrap
                    lineHeight: 1.2
                }

                Text {
                    objectName: "adviceSell"
                    Layout.fillWidth: true
                    text: frame.ma ? frame.ma.sellAdvice : ""
                    color: Theme.textPrimary
                    font.family: Theme.fontFamily
                    font.pixelSize: frame.fntBase
                    wrapMode: Text.WordWrap
                    lineHeight: 1.2
                }
            }

            // ── 依据（一条一行）──
            FSection {
                objectName: "adviceReasons"
                title: qsTr("依据")
                visible: frame.ma ? frame.ma.reasons.length > 0 : false

                Repeater {
                    model: frame.ma ? frame.ma.reasons : []

                    Text {
                        required property var modelData

                        Layout.fillWidth: true
                        text: "· " + modelData
                        color: Theme.textSecondary
                        font.family: Theme.fontFamily
                        font.pixelSize: frame.fntSmall
                        wrapMode: Text.WordWrap
                        lineHeight: 1.2
                    }
                }
            }

            // ── 口径 + 免责 ──
            Text {
                objectName: "adviceCaliber"
                Layout.fillWidth: true
                text: (frame.ma ? frame.ma.caliber : "") + qsTr("　· 规则推导，不构成投资建议")
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: frame.fntSmall
                wrapMode: Text.WordWrap
                lineHeight: 1.2
            }
        }
    }
}
