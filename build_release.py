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
import sys
import shutil
import subprocess
import zipfile
from datetime import datetime

# ── 版本号 ──
VERSION = "1.0.0"

# ── 路径 ──
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(PROJECT_ROOT, "dist")
BUILD_EXE_DIR = os.path.join(DIST_DIR, "EVE商人助手")  # PyInstaller 默认输出
RELEASE_DIR = os.path.join(DIST_DIR, "EVE商人助手_v" + VERSION)


def step(msg: str):
    """带时间戳的步骤提示"""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def run_pyinstaller():
    """步骤 1：运行 PyInstaller 打包 exe"""
    step("🔄 运行 PyInstaller 打包...")
    spec_path = os.path.join(PROJECT_ROOT, "EVE商人助手.spec")
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", spec_path, "--distpath", DIST_DIR, "--noconfirm"],
        cwd=PROJECT_ROOT,
        capture_output=False,
    )
    if result.returncode != 0:
        print("❌ PyInstaller 打包失败！")
        sys.exit(1)
    step("✅ PyInstaller 打包完成")


def organize_release():
    """
    步骤 2：整理发行版目录

    最终结构：
        dist/EVE商人助手_v1.0.0/
            EVE商人助手.exe
            database/
                items.db
            data/
                caches/icons/   (由用户运行时自动创建)
                search_history.json
                window_geometry.json
                update_progress.json
            README.md
    """
    step("🔄 整理发行版目录...")

    # 如果 Release 目录已存在，清空重建
    if os.path.exists(RELEASE_DIR):
        shutil.rmtree(RELEASE_DIR)
    os.makedirs(RELEASE_DIR, exist_ok=True)

    # 1. 复制 exe（PyInstaller 无 COLLECT 时直接输出到 dist/ 目录）
    exe_src_candidates = [
        os.path.join(BUILD_EXE_DIR, "EVE商人助手.exe"),   # 有 COLLECT 时
        os.path.join(DIST_DIR, "EVE商人助手.exe"),        # 无 COLLECT 时
    ]
    exe_src = None
    for candidate in exe_src_candidates:
        if os.path.exists(candidate):
            exe_src = candidate
            break
    if not exe_src:
        print(f"❌ exe 文件未找到（查找路径: {exe_src_candidates}）")
        sys.exit(1)
    exe_dst = os.path.join(RELEASE_DIR, "EVE商人助手.exe")
    shutil.copy2(exe_src, exe_dst)
    step(f"   ✓ 复制 {exe_src} → {exe_dst}")

    # 2. 复制 database/ 目录（用户离线数据）
    db_src = os.path.join(PROJECT_ROOT, "database")
    db_dst = os.path.join(RELEASE_DIR, "database")
    if os.path.exists(db_src):
        shutil.copytree(db_src, db_dst, ignore=shutil.ignore_patterns("__pycache__"))
        step(f"   ✓ 复制 database/")

    # 3. 复制 data/ 目录（运行期缓存和配置）
    data_src = os.path.join(PROJECT_ROOT, "data")
    data_dst = os.path.join(RELEASE_DIR, "data")
    if os.path.exists(data_src):
        # 只保留 json 文件，图标缓存由用户运行时自动生成
        shutil.copytree(
            data_src,
            data_dst,
            ignore=shutil.ignore_patterns("__pycache__", "caches"),
        )
        step(f"   ✓ 复制 data/（不含图标缓存）")
    else:
        os.makedirs(data_dst, exist_ok=True)
        step(f"   ✓ 创建空的 data/")

    # 4. 复制 README.md
    readme_src = os.path.join(PROJECT_ROOT, "README.md")
    readme_dst = os.path.join(RELEASE_DIR, "README.md")
    if os.path.exists(readme_src):
        shutil.copy2(readme_src, readme_dst)
        step(f"   ✓ 复制 README.md")

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
        for root, dirs, files in os.walk(RELEASE_DIR):
            for file in files:
                file_path = os.path.join(root, file)
                # 在 zip 中的路径：相对于 RELEASE_DIR 的路径
                arcname = os.path.relpath(file_path, RELEASE_DIR)
                # 保持 EVE商人助手_v1.0.0/xxx 的目录结构
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


def main():
    print("=" * 50)
    print(f"  EVE 商人助手 v{VERSION} 发行版打包")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    # 检查是否为开发环境
    skip_zip = "--skip-zip" in sys.argv

    # 1. PyInstaller 打包
    run_pyinstaller()

    # 2. 整理发行版目录
    organize_release()

    # 3. 清理构建中间产物
    clean_build_artifacts()

    # 4. 创建 ZIP
    if not skip_zip:
        create_zip()
    else:
        step("⏭ 跳过 ZIP 压缩（--skip-zip）")

    print("\n" + "=" * 50)
    print(f"  🎉 打包完成！")
    if not skip_zip:
        zip_path = os.path.join(DIST_DIR, f"EVE商人助手_v{VERSION}.zip")
        print(f"  发行包: {zip_path}")
    print(f"  目录:   {RELEASE_DIR}/")
    print("=" * 50)


if __name__ == "__main__":
    main()
