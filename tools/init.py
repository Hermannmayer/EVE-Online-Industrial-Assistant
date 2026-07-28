"""
数据初始化工具 — CLI 入口

用法:
    python tools/init.py              # 执行全部初始化步骤
    python tools/init.py --step items  # 仅执行指定步骤
    python tools/init.py --help        # 查看帮助

设计目的：将一次性初始化操作从主程序中独立出来，
          主程序通过 subprocess 调用此脚本。
"""

import argparse
import asyncio
import sys
import time
from pathlib import Path

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.logger import log  # noqa: E402

# ── 步骤定义 ──
# (key, name, module_path, needs_network)
# 工具类模块（sde_loader/sde_cache）已移至 tools/downloaders/，
# 运行时模块（getprices/getindustry/getcontracts）保留在 services/workers/。
STEPS = [
    ("items",        "物品数据",       "tools.downloaders.getitems",          True),
    ("prices",       "市场价格",       "services.workers.getprices",          True),
    ("blueprints",   "蓝图数据",       "tools.downloaders.getblueprints",     True),
    ("implants",     "植入体数据",     "tools.downloaders.getimplantdata",    True),
    ("industry",     "工业数据",       "services.workers.getindustry",        True),
    ("icons",        "物品图标",       "tools.downloaders.geticon",           True),
    ("sde_data",     "SDE扩展数据",    "tools.downloaders.sde_loader",        False),
]


def _import_module(module_path: str):
    """动态导入模块"""
    import importlib
    return importlib.import_module(module_path)


async def _run_step(key: str, name: str, module_path: str) -> bool:
    """执行一个初始化步骤，返回是否成功"""
    log.info(f"{'='*48}")
    log.info(f"  [{key}] {name}")
    log.info(f"{'='*48}")
    try:
        mod = _import_module(module_path)

        # 每个模块的入口函数名不同
        entry_map = {
            "getitems": "main",
            "getprices": "run_price_update",
            "getblueprints": "run_blueprint_update",
            "getimplantdata": "main",
            "geticon": "main",
            "getindustry": "run_industry_update",
            "sde_loader": "main",
        }
        # 从模块路径中提取模块名
        mod_name = module_path.rsplit(".", 1)[-1]
        func_name = entry_map.get(mod_name, "main")
        func = getattr(mod, func_name, None)
        if func is None:
            log.error(f"  [FAIL] {name}: 模块中未找到入口函数 {func_name}")
            return False

        if asyncio.iscoroutinefunction(func):
            await func()
        else:
            func()

        log.info(f"  [OK] {name} 完成")
        return True
    except Exception as e:
        log.error(f"  [FAIL] {name}: {e}", exc_info=True)
        return False


async def _run_all(steps: list | None = None):
    """顺序执行所有步骤"""
    steps = steps or STEPS
    total = len(steps)
    passed = 0
    failed = []

    t0 = time.time()
    for idx, (key, name, mod, *_) in enumerate(steps, 1):
        log.info(f"\n步骤 {idx}/{total}")
        ok = await _run_step(key, name, mod)
        if ok:
            passed += 1
        else:
            failed.append(name)

    elapsed = time.time() - t0
    log.info(f"\n{'='*48}")
    log.info(f"  完成: {passed}/{total}  耗时: {elapsed:.0f}s")
    if failed:
        log.info(f"  失败: {', '.join(failed)}")
    log.info(f"{'='*48}")
    return len(failed) == 0


def main():
    parser = argparse.ArgumentParser(description="EVE Assistant — 数据初始化工具")
    parser.add_argument(
        "--step", "-s",
        help="仅执行指定步骤 (items/prices/blueprints/implants/icons/industry/sde_data)",
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="列出所有步骤",
    )
    args = parser.parse_args()

    if args.list:
        print("可用初始化步骤:")
        for key, name, mod, net in STEPS:
            net_str = "需要网络" if net else "无需网络"
            print(f"  {key:12s}  {name:10s}  [{mod}] ({net_str})")
        return

    if args.step:
        steps = [s for s in STEPS if s[0] == args.step]
        if not steps:
            print(f"未知步骤: {args.step}")
            print(f"可用步骤: {', '.join(s[0] for s in STEPS)}")
            sys.exit(1)
    else:
        steps = STEPS

    success = asyncio.run(_run_all(steps))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
