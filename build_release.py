"""
build_release.py — EVE 商人助手 发行版打包脚本

用法：
    python build_release.py           # 完整打包（PyInstaller + 整理目录 + ZIP 压缩）
    python build_release.py --skip-zip   # 仅打包 exe，不压缩 ZIP

输出：
    dist/EVE商人助手/          # 目录结构
    dist/EVE商人助手_v{version}.zip   # ZIP 发行包
"""

import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime

from core.logger import log
from core.version import __version__ as VERSION

# ── 路径 ──
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(PROJECT_ROOT, "dist")
BUILD_EXE_DIR = os.path.join(DIST_DIR, "EVE商人助手")  # PyInstaller 默认输出
RELEASE_DIR = os.path.join(DIST_DIR, "EVE商人助手_v" + VERSION)


def step(msg: str):
    """带时间戳的步骤提示"""
    ts = datetime.now().strftime("%H:%M:%S")
    log.info(f"[{ts}] {msg}")


def discover_local_packages() -> list[str]:
    """自动扫描项目根目录下所有含 __init__.py 的 Python 包。

    排除非包目录（tests/dist/build 等）和隐藏目录。
    返回包名列表（如 ['core', 'domain', 'services', 'bootstrap', 'ui_qml']）。
    """
    skip = {".", "..", "tests", "dist", "build", "__pycache__", "docs", "scripts", "tools", "data", "database"}
    packages = []
    for entry in sorted(os.listdir(PROJECT_ROOT)):
        if entry.startswith(".") or entry in skip:
            continue
        pkg_dir = os.path.join(PROJECT_ROOT, entry)
        if os.path.isdir(pkg_dir) and os.path.isfile(os.path.join(pkg_dir, "__init__.py")):
            packages.append(entry)
    return packages


# 第三方 hidden imports（PyInstaller 静态分析可能遗漏）
THIRD_PARTY_HIDDEN_IMPORTS = [
    "aiosqlite",
    "aiosqlite.dump",
    "aiohttp",
    "tenacity",
    "tqdm",
    "yaml",
    "openpyxl",
]

# ── Qt 模块裁剪 ──────────────────────────────────────────────
# 本应用只用 QtWidgets + QtQuick（Fluent WinUI3 样式），下面这些模块一个都没用到。
# 不过滤的话它们会混进产物，最大的一笔是 `Qt6WebEngineCore.dll`（**195 MB**，占
# 整个产物 45%）：PyInstaller 的 `hook-PySide6.QtQml.py` 用 `rglob('**/qmldir')`
# **无条件**收集 `PySide6/qml/` 下全部模块，其中 `qml/QtWebEngine` 的插件二进制
# 依赖那个库 —— 应用一旦开始用 QtQml（QML 迁移），它就第一次被拖了进来。
#
# 实测：不过滤 440 MB（onedir）/ onefile exe 约 190 MB；
#       过滤后 198 MB / 80 MB。环境见 scripts/build_hooks/。
EXCLUDED_QT_MODULES = [
    # WebEngine —— 单这一项就是全部差距的大头
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets",
    # 3D / 图表
    "PySide6.QtQuick3D",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.QtCharts",
    "PySide6.QtGraphs",
    "PySide6.QtDataVisualization",
    # 文档 / 设计器 / 测试
    "PySide6.QtPdf",
    "PySide6.QtDesigner",
    "PySide6.QtTest",
    # 多媒体与网络附属
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtWebSockets",
    "PySide6.QtLocation",
    "PySide6.QtPositioning",
    "PySide6.QtTextToSpeech",
    "PySide6.QtSensors",
    "PySide6.QtWebView",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtSerialPort",
    # 其它用不到的基础模块
    "PySide6.QtSql",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtStateMachine",
    "PySide6.QtHelp",
]

# 裁剪版 QML 钩子所在目录（覆盖上游那个「全收」的 QtQml 钩子，
# 见 scripts/build_hooks/hook-PySide6.QtQml.py）
BUILD_HOOKS_DIR = os.path.join(PROJECT_ROOT, "scripts", "build_hooks")


def run_pyinstaller():
    """步骤 1：运行 PyInstaller 打包 exe"""
    step("🔄 运行 PyInstaller 打包...")
    entry_path = os.path.join(PROJECT_ROOT, "Main.py")  # PySide6 入口
    packages = discover_local_packages()
    step(f"   📦 发现本地包: {', '.join(packages)}")

    args = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--windowed",
    ]

    # 动态生成 --add-data 和 --hidden-import（每个本地包）
    for pkg in packages:
        args.extend(["--add-data", f"{pkg}{os.pathsep}{pkg}"])
        args.extend(["--hidden-import", pkg])

    # 第三方 hidden imports
    for hi in THIRD_PARTY_HIDDEN_IMPORTS:
        args.extend(["--hidden-import", hi])

    # Qt 模块裁剪 —— 不带这两项的话产物会大出一倍多，见 EXCLUDED_QT_MODULES 注释
    for mod in EXCLUDED_QT_MODULES:
        args.extend(["--exclude-module", mod])
    args.extend(["--additional-hooks-dir", BUILD_HOOKS_DIR])

    args.extend(
        [
            # 程序图标（多尺寸 .ico，由 scripts/make_app_icon.py 从设计稿生成）。
            # ⚠️ 必须在这里传：`.spec` 是 PyInstaller 每次构建自动生成的副产物（且被
            # .gitignore 忽略），往 spec 里写 icon= 下次构建就被覆盖。
            # 资源本身随 --add-data ui_qml 打进包，供运行时 setWindowIcon 读取。
            "--icon",
            os.path.join(PROJECT_ROOT, "ui_qml", "assets", "app.ico"),
            "--name",
            "EVE商人助手",
            entry_path,
            "--distpath",
            DIST_DIR,
            "--noconfirm",
        ]
    )

    result = subprocess.run(args, cwd=PROJECT_ROOT, capture_output=False)
    if result.returncode != 0:
        log.error("❌ PyInstaller 打包失败！")
        sys.exit(1)
    step("✅ PyInstaller 打包完成")
    return packages


# 发行包内置的 data/ 白名单：只带「缺失会影响功能」的静态文件，
# 运行期缓存/用户数据（sde.zip、*.yaml、caches/、search_history.json 等）一律不入包。
# 实测：全量复制会把构建机上恰好存在的 380MB SDE 原料一起打进去。
RELEASE_DATA_FILES = ("terminology.json", "mfg_browser_settings.json")


def organize_release():
    """
    步骤 2：整理发行版目录

    最终结构：
        dist/EVE商人助手_v{version}/
            EVE商人助手.exe
            database/
                reference.db    ← 无头初始化预生成：python Main.py --init-only
                blueprint.db
            data/
                terminology.json
                mfg_browser_settings.json
            README.md

    模板库缺失直接失败：README 向用户承诺「发行包已内置静态数据、首启走本地快路径」，
    静默跳过会让每个用户首启重跑一遍 SDE 下载与解析。
    """
    step("🔄 整理发行版目录...")

    # 如果 Release 目录已存在，清空重建
    if os.path.exists(RELEASE_DIR):
        shutil.rmtree(RELEASE_DIR)
    os.makedirs(RELEASE_DIR, exist_ok=True)

    # 1. 复制 exe（PyInstaller 无 COLLECT 时直接输出到 dist/ 目录）
    exe_src_candidates = [
        os.path.join(BUILD_EXE_DIR, "EVE商人助手.exe"),  # 有 COLLECT 时
        os.path.join(DIST_DIR, "EVE商人助手.exe"),  # 无 COLLECT 时
    ]
    exe_src = None
    for candidate in exe_src_candidates:
        if os.path.exists(candidate):
            exe_src = candidate
            break
    if not exe_src:
        log.error(f"❌ exe 文件未找到（查找路径: {exe_src_candidates}）")
        sys.exit(1)
    exe_dst = os.path.join(RELEASE_DIR, "EVE商人助手.exe")
    shutil.copy2(exe_src, exe_dst)
    step(f"   ✓ 复制 {exe_src} → {exe_dst}")

    # 2. 复制 database/ 模板库（只读；user/market 运行数据不入包）
    db_src = os.path.join(PROJECT_ROOT, "database")
    db_dst = os.path.join(RELEASE_DIR, "database")
    os.makedirs(db_dst, exist_ok=True)
    missing_db = [n for n in ("reference.db", "blueprint.db") if not os.path.exists(os.path.join(db_src, n))]
    if missing_db:
        log.error(f"❌ 缺少模板库: {', '.join(missing_db)}（{db_src}）")
        log.error("   先在干净环境跑一次无头初始化：python Main.py --init-only")
        sys.exit(1)
    for template_name in ("reference.db", "blueprint.db"):
        shutil.copy2(os.path.join(db_src, template_name), os.path.join(db_dst, template_name))
    step("   ✓ 复制 database/（reference.db + blueprint.db 只读模板）")

    # 3. 复制 data/ 白名单（不再整目录复制：缓存与用户配置不入包）
    data_src = os.path.join(PROJECT_ROOT, "data")
    data_dst = os.path.join(RELEASE_DIR, "data")
    os.makedirs(data_dst, exist_ok=True)
    for name in RELEASE_DATA_FILES:
        src_file = os.path.join(data_src, name)
        if not os.path.exists(src_file):
            log.error(f"❌ 缺少 data/{name}（{data_src}）")
            sys.exit(1)
        shutil.copy2(src_file, os.path.join(data_dst, name))
    step(f"   ✓ 复制 data/（{', '.join(RELEASE_DATA_FILES)}）")

    # 4. 复制 README.md
    readme_src = os.path.join(PROJECT_ROOT, "README.md")
    readme_dst = os.path.join(RELEASE_DIR, "README.md")
    if os.path.exists(readme_src):
        shutil.copy2(readme_src, readme_dst)
        step("   ✓ 复制 README.md")

    step(f"✅ 发行版目录已整理到: {RELEASE_DIR}")


def create_zip():
    """步骤 3：创建 ZIP 压缩包"""
    step("🔄 创建 ZIP 压缩包...")

    zip_name = f"EVE商人助手_v{VERSION}.zip"
    zip_path = os.path.join(DIST_DIR, zip_name)

    # 如果存在则删除旧 ZIP
    if os.path.exists(zip_path):
        os.remove(zip_path)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(RELEASE_DIR):
            for file in files:
                file_path = os.path.join(root, file)
                # 在 zip 中的路径：相对于 RELEASE_DIR 的路径
                arcname = os.path.relpath(file_path, RELEASE_DIR)
                # 保持 EVE商人助手_v{version}/xxx 的目录结构
                arcname = os.path.join(os.path.basename(RELEASE_DIR), arcname)
                zf.write(file_path, arcname)

    # 计算文件大小
    size_mb = os.path.getsize(zip_path) / (1024 * 1024)
    step(f"✅ ZIP 包已创建: {zip_path} ({size_mb:.1f} MB)")


def clean_build_artifacts():
    """删除 PyInstaller 的临时构建产物"""
    step("🔄 清理构建中间产物...")
    build_dir = os.path.join(PROJECT_ROOT, "build")
    if os.path.exists(build_dir):
        shutil.rmtree(build_dir)
        step("   ✓ 删除 build/ 目录")
    # PyInstaller 生成的 dist/EVE商人助手/（非 Release 目录）
    if os.path.exists(BUILD_EXE_DIR):
        shutil.rmtree(BUILD_EXE_DIR)
        step(f"   ✓ 删除 {BUILD_EXE_DIR}")


def verify_packages_in_build(packages: list[str]):
    """构建后验证：检查 PyInstaller build 目录中是否收集了所有本地包的 .pyc"""
    step("🔍 验证构建完整性...")
    build_dir = os.path.join(PROJECT_ROOT, "build")
    pyc_dir = os.path.join(build_dir, "EVE商人助手", "localpycs")
    if not os.path.isdir(pyc_dir):
        # onefile 模式可能没有 localpycs 目录，跳过验证
        step("   ⏭ onefile 模式跳过 .pyc 目录验证")
        return

    missing = []
    for pkg in packages:
        pkg_pyc = os.path.join(pyc_dir, pkg)
        if not os.path.isdir(pkg_pyc):
            missing.append(pkg)
    if missing:
        step(f"   ⚠️ 以下包未在构建中找到: {', '.join(missing)}")
    else:
        step(f"   ✓ 所有 {len(packages)} 个本地包已正确收集")


def main():
    log.info("=" * 50)
    log.info(f"  EVE 商人助手 v{VERSION} 发行版打包")
    log.info(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 50)

    # 检查是否为开发环境
    skip_zip = "--skip-zip" in sys.argv

    # 1. PyInstaller 打包
    packages = run_pyinstaller()

    # 2. 构建后验证
    verify_packages_in_build(packages)

    # 3. 整理发行版目录
    organize_release()

    # 4. 清理构建中间产物
    clean_build_artifacts()

    # 5. 创建 ZIP
    if not skip_zip:
        create_zip()
    else:
        step("⏭ 跳过 ZIP 压缩（--skip-zip）")

    log.info("\n" + "=" * 50)
    log.info("  🎉 打包完成！")
    if not skip_zip:
        zip_path = os.path.join(DIST_DIR, f"EVE商人助手_v{VERSION}.zip")
        log.info(f"  发行包: {zip_path}")
    log.info(f"  目录:   {RELEASE_DIR}/")
    log.info("=" * 50)


if __name__ == "__main__":
    main()
