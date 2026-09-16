import QtQuick
import QtQuick.Window
import QtQuick.Shapes

/* 启动画面（阶段 7 批次 7.2）—— 顶替 `ui_pyside6/splash_screen.py`。

   **全应用第一个 QML 面**：它跑在 `QQuickStyle` 之后、`qInstallMessageHandler` 之前。
   因此本文件只 import QtQuick 基础模块 + Window + Shapes，**不 import QtQuick.Controls**
   —— 控件样式一加载就要解析整套 Fluent 组件，会直接堆到「进程启动 → splash 可见」这段
   首帧时间上（判据见计划 7.2：不得比原来的 QWidget 版差）。

   窗口语义逐项对齐原 QWidget（`ui_pyside6/splash_screen.py`）：

     setFixedSize(360,470)              → Window 的 minimum/maximum 宽高
     FramelessWindowHint|StaysOnTopHint → Window 的 flags
     WA_TranslucentBackground + 自绘圆角 → Window 的 `color: "transparent"` 加面板 Rectangle 的
                                          radius（**不是**窗口圆角：QML 没有窗口圆角，
                                          圆角必须靠矩形自己画）
     windowOpacity 淡出                  → 仍由 Python 侧动画 QWindow.opacity（见 splash_window.py）
     30ms 旋转定时器（+5°/拍）           → 本文件的 Timer，数值逐项照搬

   状态全部来自桥 `splash`（`ui_qml.splash_window.SplashBridge`）：步骤列表、阶段文案、
   提示行、进度值。桥缺席时（例如单独加载本文件做体检）全部走空值分支，不会报错。
*/
Window {
    id: root

    width: 360
    height: 470
    minimumWidth: root.width
    maximumWidth: root.width
    minimumHeight: root.height
    maximumHeight: root.height

    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
    // 半透明窗口：圆角之外要能透过去（等价 WA_TranslucentBackground）
    color: "transparent"
    title: qsTr("EVE 商人助手")
    visible: false // 由 Python 侧 show()

    readonly property var b: (typeof splash !== "undefined" && splash) ? splash : null
    readonly property int progressValue: root.b ? root.b.progress : 0

    // 旋转角：30ms 一拍、每拍 +5°（与原 QWidget 的 _rot_timer 完全一致）
    property int angle: 0
    Timer {
        interval: 30
        // 只在窗口可见时转：首启缺数据那条路（splash → InitWizard）不会调 close()，
        // 窗口会一直藏着 —— 不跟着可见性停掉的话，这个 30ms 定时器会空转到进程结束
        running: root.visible
        repeat: true
        onTriggered: root.angle = (root.angle + 5) % 360
    }

    // ── 圆角面板（原 paintEvent 的 drawRoundedRect，含 1px 边框）──
    Rectangle {
        id: panel
        anchors.fill: parent
        anchors.margins: 1
        radius: 14
        color: Theme.bgSurface
        border.width: 1
        border.color: Theme.border
    }

    Column {
        id: content
        anchors.top: panel.top
        anchors.topMargin: 12
        anchors.horizontalCenter: panel.horizontalCenter
        spacing: 6

        // ── 圆形加载指示器：渐变底 + 内圈基准环 + 旋转弧 + 中央百分比 ──
        Item {
            id: loader
            width: 230
            height: 230
            anchors.horizontalCenter: parent.horizontalCenter

            // 半径 = min(w,h)/2 - 4 = 111 → 用 4px 外边距让出这一圈
            readonly property real discRadius: Math.min(width, height) / 2 - 4

            Rectangle {
                id: disc
                anchors.fill: parent
                anchors.margins: 4
                radius: width / 2
                border.width: 1
                border.color: Theme.border
                gradient: RadialGradient {
                    centerX: disc.width / 2
                    centerY: disc.height / 2
                    centerRadius: disc.width / 2
                    focalX: disc.width / 2
                    focalY: disc.height / 2
                    GradientStop {
                        position: 0.0
                        color: Theme.bgSurfaceLight
                    }
                    GradientStop {
                        position: 0.75
                        color: Theme.bgDark
                    }
                    GradientStop {
                        position: 1.0
                        color: Theme.bgSurface
                    }
                }
            }

            // 内圈基准环（0.78R，2px）
            Rectangle {
                anchors.centerIn: parent
                width: loader.discRadius * 2 * 0.78
                height: width
                radius: width / 2
                color: "transparent"
                border.width: 2
                border.color: Theme.bgSurfaceLight
            }

            // 旋转进度弧：90° 高亮弧绕中心旋转（0.78R，6px，圆头）
            Item {
                id: arcHolder
                anchors.centerIn: parent
                width: loader.discRadius * 2
                height: width
                rotation: root.angle

                Shape {
                    anchors.fill: parent
                    ShapePath {
                        strokeColor: Theme.primary
                        strokeWidth: 6
                        fillColor: "transparent"
                        capStyle: ShapePath.RoundCap
                        PathAngleArc {
                            // 与原 drawArc(rect, 0, 90*16) 同起同向（0° 起、逆时针 90°）
                            centerX: arcHolder.width / 2
                            centerY: arcHolder.height / 2
                            radiusX: loader.discRadius * 0.78
                            radiusY: loader.discRadius * 0.78
                            startAngle: 0
                            sweepAngle: -90
                        }
                    }
                }
            }

            // 中央进度百分比（原 30pt 加粗 ≈ 40px）
            Text {
                anchors.centerIn: parent
                text: root.progressValue + "%"
                color: Theme.textBright
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(40 * Theme.fontScale)
                font.bold: true
            }
        }

        Text {
            id: stageText
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.b ? root.b.stage : ""
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(11 * Theme.fontScale)
        }

        Item {
            width: 1
            height: 6 // 原 layout.addSpacing(6)
        }

        // 步骤网格：每行两组「图标 + 中文名」（原 QGridLayout 的 row-major 排布）
        Grid {
            id: stepGrid
            anchors.horizontalCenter: parent.horizontalCenter
            columns: 2
            columnSpacing: 18
            rowSpacing: 3

            Repeater {
                id: stepRepeater
                objectName: "splashStepRepeater"
                model: root.b ? root.b.steps : []

                delegate: Row {
                    required property var modelData
                    spacing: 18

                    Image {
                        width: 14
                        height: 14
                        sourceSize.width: 14
                        sourceSize.height: 14
                        fillMode: Image.PreserveAspectFit
                        source: "image://phosphor/"
                                + (modelData.state === "ready" ? "check"
                                   : modelData.state === "missing" ? "x" : "circle")
                                + "?c="
                                + encodeURIComponent(Theme.hex(
                                      modelData.state === "ready" ? Theme.accentGreen
                                    : modelData.state === "missing" ? Theme.accentRed
                                    : Theme.primary))
                                + "&s=14"
                    }

                    Text {
                        text: modelData.name
                        color: Theme.textPrimary
                        font.family: Theme.fontFamily
                        font.pixelSize: Math.round(11 * Theme.fontScale)
                    }
                }
            }
        }
    }

    // 提示行固定在底部（原布局是 addStretch() 之后的最后一个控件）
    Text {
        id: messageText
        anchors.bottom: panel.bottom
        anchors.bottomMargin: 16
        anchors.horizontalCenter: panel.horizontalCenter
        text: root.b ? root.b.message : ""
        color: Theme.textSecondary
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(10 * Theme.fontScale)
    }
}
