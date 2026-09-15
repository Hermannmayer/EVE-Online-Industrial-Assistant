import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

/* 数据初始化向导（阶段 4d）。
 *
 * 逐项检查 / 下载 SDE 与 ESI 数据：每步一个状态图标 + 名称 + 消息 + （运行时的）步骤进度条
 * + 失败重试 / 非关键步骤跳过；底部总进度条 + 已用时间 + 向导自己的按钮行。
 *
 * 形状与 `BatchPriceDialog.qml` 一致（进度条照它用 `Rectangle` 画，不用 `Canvas` ——
 * 离屏截图下 Canvas 整块不可见）。
 *
 * 几处刻意的取舍：
 * - 骨架 `FDialogFrame` 的「取消 · 确定」在本对话框没有对应语义（这里是一串
 *   开始/继续/取消/关闭/后台运行），故 `acceptVisible` / `cancelVisible` 都关掉，
 *   按钮行由本文件自己排。
 * - `_StepRow` 不单独建文件：它就是下面 ListView 的 delegate。每行的图标、颜色、
 *   两个按钮与进度条的可见性都由桥的 `step_row()` 算好（与 Widgets 版逐条对齐），
 *   QML 只按字段画。
 * - 步骤间距原版是 6px，主题里没有对应档位，就近取 `spacingXs`(4)。
 */

FDialogFrame {
    id: frame

    readonly property var bp: typeof bridge !== "undefined" ? bridge : null
    readonly property int fntBase: Math.round(12 * Theme.fontScale)
    readonly property int fntSmall: Math.round(11 * Theme.fontScale)
    readonly property int gap: Theme.spacingSm

    dlg: frame.bp
    acceptVisible: false
    cancelVisible: false

    // ══════════════════════════════════════════════════════════
    //  标题区 + 网络状态
    // ══════════════════════════════════════════════════════════

    RowLayout {
        Layout.fillWidth: true
        spacing: frame.gap

        Text {
            text: qsTr("数据初始化")
            color: Theme.primary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(18 * Theme.fontScale)
            font.bold: true
        }

        Item {
            Layout.fillWidth: true
        }

        Text {
            objectName: "netLabel"
            text: frame.bp ? frame.bp.netText : ""
            color: frame.bp && frame.bp.netColor !== "" ? frame.bp.netColor : Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: frame.fntSmall
        }
    }

    Text {
        Layout.fillWidth: true
        text: qsTr("正在下载游戏数据以启用全部功能。已就绪的步骤将自动跳过。")
        color: Theme.textSecondary
        font.family: Theme.fontFamily
        font.pixelSize: frame.fntBase
        wrapMode: Text.WordWrap
    }

    Rectangle {
        Layout.fillWidth: true
        Layout.preferredHeight: 1
        color: Theme.border
    }

    // ══════════════════════════════════════════════════════════
    //  步骤列表（原 `_StepRow`）
    // ══════════════════════════════════════════════════════════

    ListView {
        id: stepList
        objectName: "stepList"
        Layout.fillWidth: true
        Layout.fillHeight: true
        clip: true
        spacing: Theme.spacingXs
        model: frame.bp ? frame.bp.steps : []
        boundsBehavior: Flickable.StopAtBounds

        ScrollBar.vertical: ScrollBar {
            policy: ScrollBar.AsNeeded
        }

        delegate: Rectangle {
            id: stepRow
            required property var modelData
            required property int index

            width: stepList.width
            implicitHeight: rowLayout.implicitHeight + 2 * Theme.spacingSm
            color: Theme.bgSurface
            radius: Theme.radius
            border.width: 1
            border.color: Theme.border

            RowLayout {
                id: rowLayout
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: Theme.spacingSm
                anchors.rightMargin: Theme.spacingSm
                spacing: frame.gap

                // 状态图标（emoji 由桥按状态给出，颜色同理）
                Text {
                    objectName: "stepIcon"
                    Layout.preferredWidth: Math.round(24 * Theme.fontScale)
                    text: stepRow.modelData.icon
                    color: stepRow.modelData.color !== "" ? stepRow.modelData.color : Theme.textSecondary
                    font.pixelSize: Math.round(14 * Theme.fontScale)
                    horizontalAlignment: Text.AlignHCenter
                }

                // 名称 + 消息
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2

                    Text {
                        Layout.fillWidth: true
                        text: stepRow.modelData.name
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: Math.round(13 * Theme.fontScale)
                        font.bold: true
                        elide: Text.ElideRight
                    }

                    Text {
                        Layout.fillWidth: true
                        text: stepRow.modelData.message
                        color: Theme.textSecondary
                        font.family: Theme.fontFamily
                        font.pixelSize: frame.fntSmall
                        elide: Text.ElideRight
                    }
                }

                // 步骤级进度条（只在下载中显示；原版是 140×16 的细进度条）
                Rectangle {
                    objectName: "stepProgress"
                    visible: stepRow.modelData.running
                    Layout.preferredWidth: Math.round(140 * Theme.fontScale)
                    Layout.preferredHeight: Math.round(16 * Theme.fontScale)
                    color: Theme.bgSurfaceLight
                    border.width: 1
                    border.color: Theme.border
                    radius: 3

                    Rectangle {
                        anchors.left: parent.left
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        anchors.margins: 1
                        radius: 2
                        color: Theme.primary
                        width: Math.max(
                                   0,
                                   (parent.width - 2)
                                   * Math.min(100, Math.max(0, stepRow.modelData.percent)) / 100)
                    }

                    Text {
                        anchors.centerIn: parent
                        text: stepRow.modelData.percent + "%"
                        color: Theme.textSecondary
                        font.family: Theme.fontFamily
                        font.pixelSize: Math.round(10 * Theme.fontScale)
                    }
                }

                FButton {
                    objectName: "retryButton"
                    visible: stepRow.modelData.retryVisible
                    text: qsTr("重试")
                    implicitWidth: Math.round(58 * Theme.fontScale)
                    implicitHeight: Math.round(24 * Theme.fontScale)
                    onClicked: if (frame.bp)
                        frame.bp.retryStep(stepRow.modelData.key)
                }

                FButton {
                    objectName: "skipButton"
                    visible: stepRow.modelData.skipVisible
                    text: qsTr("跳过")
                    implicitWidth: Math.round(58 * Theme.fontScale)
                    implicitHeight: Math.round(24 * Theme.fontScale)
                    onClicked: if (frame.bp)
                        frame.bp.skipStep(stepRow.modelData.key)
                }
            }
        }
    }

    Rectangle {
        Layout.fillWidth: true
        Layout.preferredHeight: 1
        color: Theme.border
    }

    // ══════════════════════════════════════════════════════════
    //  总进度条 + 已用时间
    // ══════════════════════════════════════════════════════════

    Rectangle {
        objectName: "totalBar"
        Layout.fillWidth: true
        Layout.preferredHeight: Math.round(22 * Theme.fontScale)
        color: Theme.bgSurface
        border.width: 1
        border.color: Theme.border
        radius: Theme.radiusSmall

        Rectangle {
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.margins: 1
            radius: Theme.radiusSmall - 1
            color: Theme.primary
            width: frame.bp && frame.bp.totalMaximum > 0
                   ? Math.max(0, (parent.width - 2)
                              * Math.min(1, frame.bp.totalCurrent / frame.bp.totalMaximum))
                   : 0
        }

        Text {
            objectName: "totalLabel"
            anchors.centerIn: parent
            text: frame.bp ? frame.bp.totalText : ""
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: frame.fntBase
        }
    }

    Text {
        objectName: "etaLabel"
        Layout.fillWidth: true
        text: frame.bp ? frame.bp.etaText : ""
        color: Theme.textSecondary
        font.family: Theme.fontFamily
        font.pixelSize: frame.fntSmall
        elide: Text.ElideRight
    }

    // ══════════════════════════════════════════════════════════
    //  按钮行（原 `_build_ui` 底部那一排）
    // ══════════════════════════════════════════════════════════

    RowLayout {
        Layout.fillWidth: true
        spacing: frame.gap

        FButton {
            objectName: "continueButton"
            visible: frame.bp ? frame.bp.continueVisible : false
            text: qsTr("继续（重试未完成）")
            onClicked: if (frame.bp)
                frame.bp.continueInit()
        }

        Item {
            Layout.fillWidth: true
        }

        // auto_mode（启动场景）下的逃生口：跳过 → 直接进主界面
        FButton {
            objectName: "skipEnterButton"
            visible: frame.bp ? frame.bp.autoMode : false
            text: qsTr("跳过，进入主界面")
            onClicked: if (frame.bp)
                frame.bp.skipEnter()
        }

        FButton {
            objectName: "startButton"
            visible: frame.bp ? frame.bp.startVisible : false
            enabled: frame.bp ? frame.bp.startEnabled : false
            primary: true
            text: frame.bp ? frame.bp.startText : qsTr("开始初始化")
            onClicked: if (frame.bp)
                frame.bp.startInit()
        }

        FButton {
            objectName: "cancelButton"
            visible: frame.bp ? frame.bp.cancelVisible : false
            text: qsTr("取消")
            onClicked: if (frame.bp)
                frame.bp.cancelInit()
        }

        FButton {
            objectName: "closeButton"
            visible: frame.bp ? frame.bp.closeVisible : false
            text: qsTr("关闭")
            onClicked: if (frame.bp)
                frame.bp.requestClose()
        }

        FButton {
            objectName: "bgButton"
            enabled: frame.bp ? frame.bp.bgEnabled : true
            text: frame.bp ? frame.bp.bgText : qsTr("最小化")
            onClicked: if (frame.bp)
                frame.bp.hideWizard()
        }
    }
}
