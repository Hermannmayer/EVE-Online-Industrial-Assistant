"""构建**完全合成**的演示数据集 —— 公开 README 截图专用，零账号数据。

用户要求（原话）：「软件的数据最好由你自己生成。不要用我开发环境里的数据，
那是我账号的数据，我怕泄露。」本脚本就是这条要求的实现。

────────────────────────────────────────────────────────────────
数据来源红线（本脚本**只做**这三件事）
────────────────────────────────────────────────────────────────

① 整文件复制**公共 SDE 派生库**：`database/reference.db`、`database/blueprint.db`
   —— 这两份是 CCP 公开 SDE 的导入结果，不含任何用户数据（item/蓝图/星系/空间站…）。

② 从 `sqlite_master` 读**建表 DDL**（`user.db` / `market.db` / `items.db`）——
   只跑 `SELECT ... FROM sqlite_master`，**绝不 SELECT 任何数据行**。
   代码层面有硬闸门：`_schema_only()` 会拒绝执行任何不以 `SELECT` 开头、
   或不含 `sqlite_master` 的语句；`_SOURCE_USER_ROWS_READ` 计数器全程为 0。

③ 复制公共图标缓存 `data/caches/icons/<type_id>.png` 里**被演示数据用到的几十个**
   （不整目录复制 67 MB）。

绝不复制用户真实 `database/`、`data/` 目录；`scripts/shell_snapshot.py --real` 的
`_isolate_app_root()` 会整目录复制它们（那是给开发者本机看界面的），**公开截图不能用**。

演示根里的人物/机库/军团名全部虚构：`演示角色` / `Demo Trader` / `演示总仓` /
`演示物流公司`…；价格用固定随机种子 + BOM 推导生成，**不可能**与真实账号数据重合。

────────────────────────────────────────────────────────────────
用法
────────────────────────────────────────────────────────────────

    .venv/Scripts/python.exe scripts/build_demo_data.py            # 建 → 自检（67 项）
    .venv/Scripts/python.exe scripts/build_demo_data.py --shots    # 再拍 12 张页面图
    .venv/Scripts/python.exe scripts/build_demo_data.py --shell    # 交互式起外壳（打印 7/7）
    .venv/Scripts/python.exe scripts/build_demo_data.py --check-only
    .venv/Scripts/python.exe scripts/build_demo_data.py --root D:\\demo --anchor-date 2026-10-11

演示根默认 `%TEMP%/eve-demo-root/`。数据字典见 `docs/dev/demo-data.md`。

**不要用裸 `Main.py` 起演示根**：`StartupCheckWorker` 的 `icons` 就绪判定要求图标缓存
覆盖全集 80%（18,616 个），而整目录复制 67 MB 图标缓存是本任务明令禁止的 → 启动链会
认为「未初始化」并先弹**联网初始化向导**。`--shell` 直接构造 `ShellWindow`，绕开那条链。
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import sqlite3
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

# ════════════════════════════════════════════════════════════════
#  0. 预解析 --root 并把应用根目录指过去
#     **必须在 import core.paths 之前**：`core.paths` 的 DB/数据目录常量是
#     模块级求值的，晚一步就会指向真实仓库（那正是要避免的事）。
# ════════════════════════════════════════════════════════════════


def _argv_value(flag: str) -> str | None:
    """从 sys.argv 里取 `--flag value` / `--flag=value`（预解析用，早于 argparse）。"""
    argv = sys.argv
    for index, arg in enumerate(argv):
        if arg == flag and index + 1 < len(argv):
            return argv[index + 1]
        if arg.startswith(flag + "="):
            return arg.split("=", 1)[1]
    return None


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEMO_ROOT = Path(
    _argv_value("--root") or os.environ.get("EVE_DEMO_ROOT") or (Path(tempfile.gettempdir()) / "eve-demo-root")
).resolve()
SOURCE_ROOT = Path(_argv_value("--source-root") or _PROJECT_ROOT).resolve()
SOURCE_DB_DIR = SOURCE_ROOT / "database"
SOURCE_DATA_DIR = SOURCE_ROOT / "data"

#: 演示根就是「应用根目录」—— 所有页面/服务读的都必须是它。
os.environ["EVE_ASSISTANT_APP_ROOT"] = str(DEMO_ROOT)

# 自检要 import 本仓库的 services/domain（真实服务共用一份口径），所以源码根必须在 sys.path 上。
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

# 控制台是 GBK：`⚠` 等字符会让 print 抛 UnicodeEncodeError（与 shell_snapshot.py 同一处理）。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


# ════════════════════════════════════════════════════════════════
#  1. 常量：虚构名字 / 固定种子 / 行星级常量
# ════════════════════════════════════════════════════════════════

#: 固定随机种子 —— 同一台机器、同一天重复执行得到逐字节相同的数据。
SEED = 20261011

#: 虚构人物（**不得**使用真实角色名）
CHAR_MAIN = "演示角色"
CHAR_ALT = "Demo Trader"
CHAR_NAMES = (CHAR_MAIN, CHAR_ALT)

#: 虚构机库
HANGAR_MAIN = "演示总仓"
HANGAR_LINE = "演示生产线"
HANGAR_REACTOR = "演示反应堆"
HANGAR_TRADE = "演示贸易仓"

#: 虚构公司/发行方（合同用），名字明显是演示数据
DEMO_ISSUERS = (
    (900000001, "演示物流公司"),
    (900000002, "Demo Freight Co"),
    (900000003, "演示矿业集团"),
)

#: 区域（贸易中心）—— 与 core.constants.TRADE_HUB_IDS 一致
HUB_REGIONS: dict[str, int] = {
    "Jita": 10000002,
    "Amarr": 10000043,
    "Dodixie": 10000032,
    "Rens": 10000030,
    "Hek": 10000028,
}

#: 8 种基础矿物（CCP MPI 口径）+ PLEX —— 价格为**合成值**，不是真实行情
MINERAL_TYPES: tuple[int, ...] = (34, 35, 36, 37, 38, 39, 40, 11399)
PLEX_TYPE_ID = 44992
#: 矿物/PLEX 的合成基准价（ISK）。量级贴近游戏，但数值是编的。
BASE_PRICES: dict[int, float] = {
    34: 4.35,
    35: 5.80,
    36: 9.10,
    37: 12.60,
    38: 71.0,
    39: 545.0,
    40: 1180.0,
    11399: 19_400.0,
    PLEX_TYPE_ID: 4_850_000.0,
}

#: 指数用的保留负数 type_id（与 services.market_index_service.INDEX_TYPE_IDS 同值）
INDEX_KEYS = ("mpi", "pppi", "sppi", "cpi", "plex")
INDEX_TYPE_IDS = {"mpi": -1, "pppi": -2, "sppi": -3, "cpi": -4, "plex": -5}

#: 时间轴长度：资产折线 ≥14 天、指数 ≥30 天、链条的 180 天窗口也要够
ASSET_DAYS = 120
HISTORY_DAYS = 200
SNAPSHOT_DAYS = 60

#: 两行「市价不可信」教材数据的盘口量。
#: 离群行：卖侧只有 3 件（低于 `PRICE_CREDIBLE_MIN_SELL_VOLUME=100`），买侧 200 万件
#: → `domain.market_depth.sell_price_reliable` 判 `False`。
#: 对照行：卖侧 5.2 万件 → 判 `True`。
#: 生成与 `--check-only` 的回捞共用这三个常量，保证两次口径一致。
OUTLIER_SELL_VOLUME = 3
OUTLIER_BUY_VOLUME = 2_000_000
THICK_SELL_VOLUME = 52_000
THICK_BUY_VOLUME = 48_000

#: 演示根自身路径的守卫（绝不写进真实仓库）
_MARKER_FILE = ".eve-demo-root"


# ════════════════════════════════════════════════════════════════
#  2. 安全闸门：只允许 sqlite_master 查询
# ════════════════════════════════════════════════════════════════

#: 针对**真实** user.db 执行过的非 schema 查询次数 —— 全程必须为 0（交付时要报这个数）。
_SOURCE_USER_ROWS_READ = 0


def _schema_only(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list:
    """只允许 `SELECT ... FROM sqlite_master` 这类结构查询，其余一律拒绝。

    这是本脚本对「不读 user.db 数据行」这条红线在**代码层面**的落实：
    就算后面有人手滑写了 `SELECT * FROM inventory_items`，这里会当场抛错，
    而不是悄悄把账号数据读出来。
    """
    global _SOURCE_USER_ROWS_READ
    stripped = " ".join(sql.split()).upper()
    if not stripped.startswith("SELECT") or "SQLITE_MASTER" not in stripped:
        raise RuntimeError(
            f"演示数据脚本只允许查 sqlite_master，已拒绝执行：{sql!r}\n（用户红线：绝不读取 user.db 的任何数据行）"
        )
    return conn.execute(sql, params).fetchall()


def read_source_schema(db_path: Path, skip: tuple[str, ...] = ("sqlite_sequence", "sqlite_stat1")) -> list[str]:
    """从真实库读**建表 DDL** 列表（只查 sqlite_master，不碰数据行）。"""
    if not db_path.exists():
        raise FileNotFoundError(f"缺少 schema 来源库：{db_path}")
    # mode=ro：连写权限都不给，从物理上杜绝误改真实库
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        rows = _schema_only(conn, "SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name")
        ddl: list[str] = []
        for name, sql in rows:
            if name in skip or not sql:
                continue
            ddl.append(str(sql))
        return ddl
    finally:
        conn.close()


def _apply_ddl(db_path: Path, ddl: list[str]) -> None:
    """把 DDL 列表应用到目标库（先删旧文件，保证幂等重建）。"""
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    try:
        for statement in ddl:
            conn.execute(statement)
        conn.commit()
    finally:
        conn.close()


def _set_user_version(db_path: Path, version: int) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(f"PRAGMA user_version = {int(version)}")
        conn.commit()
    finally:
        conn.close()


def _ddl_signature(db_path: Path) -> str:
    """库的「结构指纹」：表名 + 列名，用于自检「演示库 schema 与真实库同形」。"""
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        parts: list[str] = []
        for (name,) in _schema_only(conn, "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
            if name in ("sqlite_sequence", "sqlite_stat1"):
                continue
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({name})")]
            parts.append(f"{name}({','.join(cols)})")
        return "|".join(parts)
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════
#  3. 演示物品选取（全部来自公共 SDE，确定性）
# ════════════════════════════════════════════════════════════════


def _connect_demo_ref() -> sqlite3.Connection:
    conn = sqlite3.connect(DEMO_ROOT / "database" / "reference.db")
    conn.execute(f"ATTACH DATABASE '{DEMO_ROOT / 'database' / 'blueprint.db'}' AS bp")
    return conn


def pick_demo_items(conn: sqlite3.Connection) -> dict:
    """从公共 SDE 里确定性挑出演示用物品种类（可制造品/反应产物/材料/矿石/蓝图）。"""
    # 可制造品：有 manufacturing 蓝图产物、且是已发布的市场物品（有中文名）
    products = conn.execute(
        """
        SELECT bp.product_type_id, bp.blueprint_type_id, i.zh_name
          FROM bp.blueprint_products bp
          JOIN item i ON i.type_id = bp.product_type_id
         WHERE bp.activity = 'manufacturing'
           AND i.market_group_id IS NOT NULL
           AND COALESCE(i.zh_name, '') <> ''
           AND bp.product_type_id > 0
         GROUP BY bp.product_type_id
         ORDER BY bp.product_type_id
         LIMIT 400
        """
    ).fetchall()
    if len(products) < 40:
        raise RuntimeError("reference/blueprint 库里可制造的物品太少，无法构造演示数据")
    # 均匀取样，避免全挤在同一个 type_id 区段（看起来像真市场）
    step = max(1, len(products) // 14)
    picked_products = [products[i] for i in range(0, len(products), step)][:14]

    # 反应产物
    reactions = conn.execute(
        """
        SELECT bp.product_type_id, bp.blueprint_type_id, i.zh_name
          FROM bp.blueprint_products bp
          JOIN item i ON i.type_id = bp.product_type_id
         WHERE bp.activity = 'reaction'
           AND i.market_group_id IS NOT NULL
           AND COALESCE(i.zh_name, '') <> ''
         GROUP BY bp.product_type_id
         ORDER BY bp.product_type_id
         LIMIT 60
        """
    ).fetchall()
    reaction_picked = [reactions[i] for i in range(0, len(reactions), max(1, len(reactions) // 3))][:3]

    # 材料：被这些蓝图真正用到的 type_id（保证 BOM/占用/缺口都能算出来）
    bp_ids = [int(p[1]) for p in picked_products] + [int(r[1]) for r in reaction_picked]
    marks = ",".join("?" * len(bp_ids))
    materials = [
        int(r[0])
        for r in conn.execute(
            f"SELECT DISTINCT material_type_id FROM bp.blueprint_materials "
            f"WHERE blueprint_type_id IN ({marks}) ORDER BY material_type_id",
            bp_ids,
        ).fetchall()
    ]
    # 「计划用到的材料」单独再取一份：演示计划只覆盖前 8 个产品 + 反应，
    # 把这批材料优先放进库存，仓库页的「规划占用 / 缺口」列才会有成片的数字
    # （否则大多数行都是 0，README 截图看不出这两列在干什么）。
    plan_bp_ids = [int(p[1]) for p in picked_products[:8]] + [int(r[1]) for r in reaction_picked]
    marks = ",".join("?" * len(plan_bp_ids))
    plan_materials = [
        int(r[0])
        for r in conn.execute(
            f"SELECT material_type_id FROM bp.blueprint_materials "
            f"WHERE blueprint_type_id IN ({marks}) GROUP BY material_type_id ORDER BY material_type_id",
            plan_bp_ids,
        ).fetchall()
    ]

    # 「生产投入品」（与 market_index_service 同一判据：被 ≥4 张有效配方当材料）
    index_members = [
        int(r[0])
        for r in conn.execute(
            """
            SELECT bm.material_type_id
              FROM bp.blueprint_materials bm
             WHERE bm.activity IN ('manufacturing', 'reaction')
               AND EXISTS (
                     SELECT 1 FROM bp.blueprint_products vp
                     JOIN item vi ON vi.type_id = vp.product_type_id
                    WHERE vp.blueprint_type_id = bm.blueprint_type_id
                      AND vp.activity = bm.activity
                      AND vi.market_group_id IS NOT NULL)
             GROUP BY bm.material_type_id
            HAVING COUNT(DISTINCT bm.blueprint_type_id) >= 4
             ORDER BY bm.material_type_id
            """
        ).fetchall()
    ]
    if len(index_members) < 60:
        raise RuntimeError("reference/blueprint 库里「生产投入品」太少，指数篮子会空")
    index_step = max(1, len(index_members) // 150)
    index_sample = index_members[::index_step][:150]

    # 矿石：category_id=25 且有回收配方（估价页「精炼价值」列要有数）
    ores = [
        int(r[0])
        for r in conn.execute(
            """
            SELECT i.type_id FROM item i
             WHERE i.category_id = 25
               AND EXISTS (SELECT 1 FROM reprocessing_materials rm WHERE rm.type_id = i.type_id)
             ORDER BY i.type_id LIMIT 40
            """
        ).fetchall()
    ]

    # 科研输入蓝图：有 copying 活动的蓝图（拷贝/研究计划要绑 BPO）
    copy_bps = [
        int(r[0])
        for r in conn.execute(
            "SELECT DISTINCT blueprint_type_id FROM bp.blueprint_activities "
            "WHERE activity = 'copying' ORDER BY blueprint_type_id LIMIT 400"
        ).fetchall()
    ]
    invention_bps = [
        int(r[0])
        for r in conn.execute(
            "SELECT DISTINCT blueprint_type_id FROM bp.blueprint_products "
            "WHERE activity = 'invention' ORDER BY blueprint_type_id LIMIT 400"
        ).fetchall()
    ]
    if not copy_bps or not invention_bps:
        raise RuntimeError("蓝图表缺 copying / invention 活动，科研计划无法演示")

    return {
        "products": picked_products,
        "reactions": reaction_picked,
        "materials": materials,
        "plan_materials": plan_materials,
        "index_sample": index_sample,
        "ores": ores,
        "copy_bps": copy_bps,
        "invention_bps": invention_bps,
    }


def pick_stations(conn: sqlite3.Connection) -> dict[str, int]:
    """吉他和阿玛尔各挑一个**真实 SDE 空间站**（合同起止点；跳数要算得出来）。"""
    out: dict[str, int] = {}
    for hub, system_id in (("Jita", 30000142), ("Amarr", 30002187), ("Dodixie", 30002659)):
        row = conn.execute(
            "SELECT station_id FROM station WHERE solar_system_id = ? ORDER BY station_id LIMIT 1",
            (system_id,),
        ).fetchone()
        if not row:
            raise RuntimeError(f"reference.db 里没有星系 {system_id} 的空间站")
        out[hub] = int(row[0])
    return out


# ════════════════════════════════════════════════════════════════
#  4. 合成价格（固定种子 + BOM 推导；数值与真实行情无关）
# ════════════════════════════════════════════════════════════════


class DemoPrices:
    """演示价格表：矿物取基准价，产物按 BOM 材料成本加成，其余按体积量级推导。"""

    def __init__(self, conn: sqlite3.Connection, items: dict, rng: random.Random) -> None:
        self._rng = rng
        self._bp_materials: dict[int, list[tuple[int, int]]] = {}
        self._bp_output_qty: dict[int, int] = {}
        for (bp_id,) in conn.execute(
            "SELECT DISTINCT blueprint_type_id FROM bp.blueprint_materials WHERE activity='manufacturing'"
        ).fetchall():
            self._bp_materials[int(bp_id)] = [
                (int(m), int(q))
                for m, q in conn.execute(
                    "SELECT material_type_id, quantity FROM bp.blueprint_materials "
                    "WHERE blueprint_type_id = ? AND activity = 'manufacturing'",
                    (int(bp_id),),
                ).fetchall()
            ]
        for bp_id, qty in conn.execute(
            "SELECT blueprint_type_id, quantity FROM bp.blueprint_products WHERE activity='manufacturing'"
        ).fetchall():
            self._bp_output_qty[int(bp_id)] = max(int(qty or 1), 1)

        volumes = dict(conn.execute("SELECT type_id, volume FROM item").fetchall())

        self.price: dict[int, float] = dict(BASE_PRICES)

        # 材料：按体积量级 + 抖动推导（量级合理即可，不追求与真实行情一致）
        for type_id in items["materials"] + items["index_sample"] + items["ores"]:
            if type_id in self.price:
                continue
            volume = float(volumes.get(type_id) or 0.0)
            base = 45.0 + max(volume, 0.01) * 2600.0
            self.price[type_id] = _round_price(base * rng.uniform(1.0, 4.2))

        # 产物：材料成本 × 加成 ÷ 每轮产出
        for product_id, bp_id, _name in items["products"]:
            self.price[int(product_id)] = self._product_price(int(bp_id), int(product_id))

        # 反应产物：没有 manufacturing 配方，按材料表 reaction 活动推
        for product_id, bp_id, _name in items["reactions"]:
            price = self._reaction_product_price(int(bp_id))
            self.price[int(product_id)] = price or _round_price(max(200.0, rng.uniform(800.0, 90_000.0)))

        # 蓝图（科研计划的产物是蓝图）：按它造出来的东西定价 × 流程数
        for bp_id in items["copy_bps"][:200] + items["invention_bps"][:200]:
            if int(bp_id) in self.price:
                continue
            output = conn.execute(
                "SELECT product_type_id, quantity FROM bp.blueprint_products "
                "WHERE blueprint_type_id = ? AND activity = 'manufacturing' LIMIT 1",
                (int(bp_id),),
            ).fetchone()
            if output:
                unit = self.price.get(int(output[0])) or 0.0
                self.price[int(bp_id)] = _round_price(max(unit * max(int(output[1] or 1), 1) * 6.0, 25_000.0))
            else:
                self.price[int(bp_id)] = _round_price(rng.uniform(80_000.0, 400_000.0))

    def _materials_of(self, bp_id: int) -> list[tuple[int, int]]:
        return self._bp_materials.get(bp_id) or []

    def _reaction_product_price(self, bp_id: int) -> float | None:
        rows = [
            (int(m), int(q))
            for m, q in _ATTACHED_REF.execute(
                "SELECT material_type_id, quantity FROM bp.blueprint_materials "
                "WHERE blueprint_type_id = ? AND activity = 'reaction'",
                (bp_id,),
            ).fetchall()
        ]
        if not rows:
            return None
        cost = sum(self.price.get(m, 100.0) * q for m, q in rows)
        out_qty = _ATTACHED_REF.execute(
            "SELECT quantity FROM bp.blueprint_products WHERE blueprint_type_id = ? AND activity = 'reaction'",
            (bp_id,),
        ).fetchone()
        per_cycle = max(int((out_qty or [1])[0] or 1), 1)
        return _round_price(cost / per_cycle * self._rng.uniform(1.10, 1.60))

    def _product_price(self, bp_id: int, product_id: int) -> float:
        cost = sum(self.price.get(m, 150.0) * q for m, q in self._materials_of(bp_id))
        per_cycle = self._bp_output_qty.get(bp_id, 1)
        if cost <= 0:
            return _round_price(self._rng.uniform(2_000.0, 900_000.0))
        return _round_price(cost / per_cycle * self._rng.uniform(1.08, 1.85))


def _round_price(value: float) -> float:
    """把价格修成「看起来像挂单」的圆整值（保留 3 位有效数字）。"""
    value = max(float(value), 0.01)
    magnitude = 10 ** max(0, len(str(int(value))) - 3)
    return float(max(magnitude, round(value / magnitude) * magnitude))


#: 供 `DemoPrices` 查 reaction 材料用的模块级连接（建价格表时已 ATTACH 蓝图表）
_ATTACHED_REF: sqlite3.Connection


# ════════════════════════════════════════════════════════════════
#  5. 建 market.db
# ════════════════════════════════════════════════════════════════


def build_market_db(
    conn_ref: sqlite3.Connection, items: dict, prices: DemoPrices, rng: random.Random, anchor: date
) -> dict:
    """建演示 market.db：价格快照 / 逐日成交 / 挂单量快照 / 指数 / 合同。"""
    ddl = read_source_schema(SOURCE_DB_DIR / "market.db")
    target = DEMO_ROOT / "database" / "market.db"
    _apply_ddl(target, ddl)

    hist_types = sorted(
        set(MINERAL_TYPES)
        | {int(p[0]) for p in items["products"]}
        | {int(r[0]) for r in items["reactions"]}
        | {int(t) for t in items["index_sample"]}
        | {int(t) for t in items["ores"]}
        | {int(t) for t in items["materials"]}
    )
    # 薄盘离群价 / 正常厚盘 两个「教材行」：从历史集合里取（必须在 market_prices 里）
    outlier_type = hist_types[7]
    thick_type = hist_types[8]

    conn = sqlite3.connect(target)
    try:
        fetch_time = f"{anchor.isoformat()} 12:00:00"

        # ── market_prices：5 个贸易中心 × 全部演示物品 ──
        price_rows = []
        book: dict[tuple[int, int], tuple[float, float, int, int]] = {}
        for type_id in hist_types:
            base = prices.price.get(type_id) or 1000.0
            for region_id in HUB_REGIONS.values():
                hub_factor = 1.0 + (hash((type_id, region_id)) % 1000) / 1000.0 * 0.14 - 0.07
                sell = _round_price(max(base * hub_factor, 0.01))
                buy = _round_price(max(sell * rng.uniform(0.86, 0.975), 0.01))
                sell_volume = rng.randint(1_200, 90_000)
                buy_volume = rng.randint(1_200, 90_000)
                price_rows.append((type_id, region_id, buy, sell, buy_volume, sell_volume, fetch_time))
                book[(type_id, region_id)] = (buy, sell, buy_volume, sell_volume)

        # 「卖侧极薄 + 买卖价差千倍级」的离群行（展示新版「⚠ 市价不可信」）
        for region_id in HUB_REGIONS.values():
            buy, sell, _bv, _sv = book[(outlier_type, region_id)]
            price_rows = [r for r in price_rows if not (r[0] == outlier_type and r[1] == region_id)]
            price_rows.append(
                (
                    outlier_type,
                    region_id,
                    buy,
                    _round_price(sell * 1500.0),
                    OUTLIER_BUY_VOLUME,
                    OUTLIER_SELL_VOLUME,
                    fetch_time,
                )
            )
        # 对照：正常厚盘
        for region_id in HUB_REGIONS.values():
            buy, sell, _bv, _sv = book[(thick_type, region_id)]
            price_rows = [r for r in price_rows if not (r[0] == thick_type and r[1] == region_id)]
            price_rows.append((thick_type, region_id, buy, sell, THICK_BUY_VOLUME, THICK_SELL_VOLUME, fetch_time))

        conn.executemany(
            "INSERT OR REPLACE INTO market_prices "
            "(type_id, region_id, buy_price, sell_price, adjusted_price, buy_volume, sell_volume, fetch_time) "
            "VALUES (?,?,?,?,?,?,?,?)",
            [(t, r, b, s, (b + s) / 2, bv, sv, ft) for t, r, b, s, bv, sv, ft in price_rows],
        )

        # ── price_history：Jita 逐日成交（每天都有，宽度均匀） ──
        history_rows = []
        for type_id in hist_types:
            if type_id == PLEX_TYPE_ID:
                continue
            base = prices.price.get(type_id) or 1000.0
            drift = rng.uniform(-0.0009, 0.0016)
            level = base * rng.uniform(0.90, 1.10)
            for offset in range(HISTORY_DAYS - 1, -1, -1):
                day = (anchor - timedelta(days=offset)).isoformat()
                level = max(level * (1.0 + drift + rng.uniform(-0.012, 0.012)), 0.02)
                volume = rng.randint(400, 26_000)
                history_rows.append(
                    (
                        type_id,
                        HUB_REGIONS["Jita"],
                        day,
                        _round_price(level),
                        _round_price(level * rng.uniform(1.0, 1.05)),
                        _round_price(level * rng.uniform(0.95, 1.0)),
                        volume,
                        rng.randint(20, 400),
                        fetch_time,
                    )
                )
        conn.executemany(
            "INSERT OR REPLACE INTO price_history "
            "(type_id, region_id, date, average, highest, lowest, volume, order_count, fetched_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            history_rows,
        )

        # ── market_volume_snapshots：5 个中心 × 60 天挂单量快照 ──
        snapshot_rows = []
        for type_id in hist_types:
            base = prices.price.get(type_id) or 1000.0
            for region_id in HUB_REGIONS.values():
                for offset in range(SNAPSHOT_DAYS - 1, -1, -1):
                    day = (anchor - timedelta(days=offset)).isoformat()
                    jitter = 1.0 + rng.uniform(-0.08, 0.08)
                    sell = _round_price(base * jitter)
                    snapshot_rows.append(
                        (
                            type_id,
                            region_id,
                            day,
                            _round_price(sell * rng.uniform(0.88, 0.97)),
                            sell,
                            rng.randint(1_000, 70_000),
                            rng.randint(1_000, 70_000),
                        )
                    )
        conn.executemany(
            "INSERT OR REPLACE INTO market_volume_snapshots "
            "(type_id, region_id, date, buy_price, sell_price, buy_volume, sell_volume) VALUES (?,?,?,?,?,?,?)",
            snapshot_rows,
        )

        # ── global_price_daily：PLEX 全服统一价 ──
        plex_rows = []
        level = BASE_PRICES[PLEX_TYPE_ID]
        for offset in range(HISTORY_DAYS - 1, -1, -1):
            day = (anchor - timedelta(days=offset)).isoformat()
            level = max(level * (1.0 + rng.uniform(-0.006, 0.007)), 1.0)
            plex_rows.append((PLEX_TYPE_ID, day, _round_price(level), _round_price(level * 1.02), fetch_time))
        conn.executemany(
            "INSERT OR REPLACE INTO global_price_daily (type_id, date, average_price, adjusted_price, fetched_at) "
            "VALUES (?,?,?,?,?)",
            plex_rows,
        )

        # ── market_index_daily：5 条指数逐日点位（≥30 天，实际 200 天） ──
        index_rows = []
        for key in INDEX_KEYS:
            level = 100.0
            drift = {"mpi": 0.0006, "pppi": 0.0004, "sppi": 0.0003, "cpi": 0.0002, "plex": 0.0008}[key]
            for offset in range(HISTORY_DAYS - 1, -1, -1):
                day = (anchor - timedelta(days=offset)).isoformat()
                level = max(level * (1.0 + drift + rng.uniform(-0.011, 0.011)), 10.0)
                index_rows.append(
                    (INDEX_TYPE_IDS[key], HUB_REGIONS["Jita"], day, round(level, 4), rng.randint(10**9, 9 * 10**9))
                )
        conn.executemany(
            "INSERT OR REPLACE INTO market_index_daily (type_id, region_id, date, price, volume) VALUES (?,?,?,?,?)",
            index_rows,
        )

        # ── 合同：3 运输 + 4 物品交换 + 2 拍卖（发行人/标题全部虚构） ──
        stations = pick_stations(conn_ref)
        routes = (("Jita", "Amarr"), ("Amarr", "Dodixie"), ("Dodixie", "Jita"))
        contract_rows = []
        item_rows = []
        issuer_rows = [(iid, name, fetch_time) for iid, name in DEMO_ISSUERS]
        item_pool = [int(p[0]) for p in items["products"]] + list(MINERAL_TYPES)

        contract_id = 910000001
        for index, (src, dst) in enumerate(routes):
            reward = 6_500_000.0 + index * 1_750_000.0
            collateral = 120_000_000.0 + index * 35_000_000.0
            contract_rows.append(
                (
                    contract_id,
                    HUB_REGIONS["Jita"],
                    "courier",
                    f"演示运输合同 #{index + 1}（{src} → {dst}）",
                    0.0,
                    0.0,
                    reward,
                    collateral,
                    9_500.0 + index * 4_000.0,
                    3 + index,
                    DEMO_ISSUERS[index % len(DEMO_ISSUERS)][0],
                    1_000_000 + index,
                    f"{anchor.isoformat()}T08:15:00Z",
                    f"{(anchor + timedelta(days=7)).isoformat()}T08:15:00Z",
                    stations[src],
                    stations[dst],
                    0,
                    fetch_time,
                    fetch_time,
                )
            )
            contract_id += 1

        for index in range(4):
            price = 45_000_000.0 + index * 28_000_000.0
            contract_rows.append(
                (
                    contract_id,
                    HUB_REGIONS["Jita"],
                    "item_exchange",
                    f"演示物品交换合同 #{index + 1}",
                    price,
                    price * 1.1,
                    0.0,
                    0.0,
                    12_500.0 + index * 8_000.0,
                    7,
                    DEMO_ISSUERS[(index + 1) % len(DEMO_ISSUERS)][0],
                    1_000_000 + index,
                    f"{anchor.isoformat()}T09:30:00Z",
                    f"{(anchor + timedelta(days=14)).isoformat()}T09:30:00Z",
                    stations["Jita"],
                    stations["Jita"],
                    0,
                    fetch_time,
                    fetch_time,
                )
            )
            for record_id in range(3):
                type_id = item_pool[(index * 3 + record_id) % len(item_pool)]
                item_rows.append(
                    (
                        contract_id,
                        record_id + 1,
                        5_000_000 + index * 100 + record_id,
                        type_id,
                        500 + record_id * 250,
                        0,
                        1,
                        10,
                        20,
                        1,
                    )
                )
            contract_id += 1

        for index in range(2):
            bid = 18_000_000.0 + index * 9_000_000.0
            contract_rows.append(
                (
                    contract_id,
                    HUB_REGIONS["Jita"],
                    "auction",
                    f"演示拍卖合同 #{index + 1}",
                    bid,
                    bid * 1.35,
                    0.0,
                    0.0,
                    4_200.0 + index * 1_500.0,
                    5,
                    DEMO_ISSUERS[(index + 2) % len(DEMO_ISSUERS)][0],
                    1_000_000 + index,
                    f"{anchor.isoformat()}T10:45:00Z",
                    f"{(anchor + timedelta(days=10)).isoformat()}T10:45:00Z",
                    stations["Jita"],
                    stations["Jita"],
                    0,
                    fetch_time,
                    fetch_time,
                )
            )
            for record_id in range(2):
                type_id = item_pool[(index * 5 + record_id + 4) % len(item_pool)]
                item_rows.append(
                    (
                        contract_id,
                        record_id + 1,
                        5_000_000 + index * 200 + record_id,
                        type_id,
                        1_200 + record_id * 400,
                        0,
                        1,
                        0,
                        0,
                        1,
                    )
                )
            contract_id += 1

        conn.executemany(
            "INSERT OR REPLACE INTO public_contracts "
            "(contract_id, region_id, type, title, price, buyout, reward, collateral, volume, days_to_complete, "
            " issuer_id, issuer_corporation_id, date_issued, date_expired, start_location_id, end_location_id, "
            " for_corporation, fetch_time, items_fetched_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            contract_rows,
        )
        conn.executemany(
            "INSERT OR REPLACE INTO contract_items "
            "(contract_id, record_id, item_id, type_id, quantity, is_blueprint_copy, is_included, "
            " material_efficiency, time_efficiency, runs) VALUES (?,?,?,?,?,?,?,?,?,?)",
            item_rows,
        )
        conn.executemany(
            "INSERT OR REPLACE INTO contract_issuers (issuer_id, name, fetched_at) VALUES (?,?,?)",
            issuer_rows,
        )

        conn.execute("ANALYZE market_volume_snapshots")
        conn.commit()
    finally:
        conn.close()

    _set_user_version(target, _expected_version("mkt"))
    return {"outlier_type": outlier_type, "thick_type": thick_type, "history_types": hist_types}


def _expected_version(alias: str) -> int:
    """取代码里声明的 schema 版本（不硬编码，避免与 schema_migrations 漂移）。"""
    from services.schema_migrations import DB_SCHEMA_VERSIONS

    return int(DB_SCHEMA_VERSIONS[alias])


# ════════════════════════════════════════════════════════════════
#  6. 建 user.db（内容全部虚构）
# ════════════════════════════════════════════════════════════════


def build_user_db(
    conn_ref: sqlite3.Connection, items: dict, prices: DemoPrices, market: dict, rng: random.Random, anchor: date
) -> dict:
    """建演示 user.db：机库 / 库存 / 蓝图 / 计划 / 快照 / 挂单 / 关注。"""
    ddl = read_source_schema(SOURCE_DB_DIR / "user.db")
    target = DEMO_ROOT / "database" / "user.db"
    _apply_ddl(target, ddl)

    outlier_type = int(market["outlier_type"])
    thick_type = int(market["thick_type"])
    price_of = lambda tid: float(prices.price.get(int(tid)) or 1000.0)  # noqa: E731

    conn = sqlite3.connect(target)
    try:
        # 旧 items.db 拆分迁移的完成标记（Main.py 见到它就早退；演示根不跑迁移）
        conn.execute(
            "INSERT OR REPLACE INTO _split_migration_complete (id, completed_at) VALUES (1, ?)",
            (f"{anchor.isoformat()} 09:00:00",),
        )

        # ── 机库（名字全部虚构） ──
        hangars = [
            (1, HANGAR_MAIN, "演示用总仓（合成数据）", 30000142, "npc_station", 0.0, None),
            (2, HANGAR_LINE, "演示用生产线（合成数据）", 30000142, "engineering_complex", 0.03, None),
            (3, HANGAR_REACTOR, "演示用反应堆（合成数据）", 30002187, "refinery", 0.05, None),
            (4, HANGAR_TRADE, "演示用贸易仓（合成数据）", 30000142, "npc_station", 0.0, None),
        ]
        conn.executemany(
            "INSERT OR REPLACE INTO hangars (id, name, notes, solar_system_id, facility_type, facility_tax, rigs) "
            "VALUES (?,?,?,?,?,?,?)",
            hangars,
        )

        # ── 库存：≥20 行，含图标、含 1 行薄盘离群 + 1 行正常厚盘 ──
        inventory_ids: list[int] = [outlier_type, thick_type]
        inventory_ids += [int(t) for t in MINERAL_TYPES]
        inventory_ids += [int(t) for t in items["plan_materials"][:30]]
        inventory_ids += [int(t) for t in items["materials"][:12]]
        inventory_ids += [int(t) for t in items["index_sample"][:6]]
        inventory_ids += [int(p[0]) for p in items["products"][:6]]
        seen: set[int] = set()
        ordered_ids = []
        for type_id in inventory_ids:
            if type_id and type_id not in seen and type_id not in (PLEX_TYPE_ID,):
                seen.add(type_id)
                ordered_ids.append(type_id)
        ordered_ids = ordered_ids[:52]

        inventory_rows = []
        for index, type_id in enumerate(ordered_ids):
            # 「市价不可信」的两行必须落在**仓库页默认机库（1 = 演示总仓）**里，
            # 否则底部那句「N 项市价不可信未计入」永远是 0（对照行同理）。
            if type_id in (outlier_type, thick_type):
                hangar_id = 1
            else:
                hangar_id = 1 if index % 3 else 2
            if type_id == outlier_type:
                quantity, cost = 120, price_of(thick_type)
            elif type_id == thick_type:
                quantity, cost = 2_400_000, price_of(type_id) * 0.9
            elif type_id in MINERAL_TYPES:
                quantity, cost = rng.randint(50_000, 4_000_000), price_of(type_id) * rng.uniform(0.85, 1.0)
            else:
                quantity, cost = rng.randint(2_000, 90_000), price_of(type_id) * rng.uniform(0.85, 1.0)
            inventory_rows.append((hangar_id, type_id, quantity, round(cost, 2), f"{anchor.isoformat()} 09:05:00"))
        conn.executemany(
            "INSERT INTO inventory_items (hangar_id, type_id, quantity, cost_price, created_at) VALUES (?,?,?,?,?)",
            inventory_rows,
        )

        # ── 蓝图：原图 + 拷贝混合，≥6 张 ──
        bp_plan_sources: list[int] = [int(p[1]) for p in items["products"][:6]]
        bp_plan_sources += [int(items["copy_bps"][index]) for index in range(3)]
        bp_plan_sources += [int(items["invention_bps"][0]), int(items["reactions"][0][1])]
        bp_rows = []
        for index, bp_type_id in enumerate(dict.fromkeys(bp_plan_sources)):
            is_bpo = 1 if index % 3 else 0
            runs = 0 if is_bpo else rng.randint(8, 40)
            bp_rows.append(
                (
                    index + 1,
                    1 if index % 2 else 2,
                    bp_type_id,
                    is_bpo,
                    rng.choice([0, 6, 8, 10]),
                    rng.choice([0, 12, 16, 20]),
                    runs,
                    1 if is_bpo else rng.randint(1, 4),
                    "演示蓝图（合成数据）",
                    round(price_of(bp_type_id) * 0.02, 2),
                )
            )
        conn.executemany(
            "INSERT OR REPLACE INTO user_blueprints "
            "(id, hangar_id, blueprint_type_id, is_bpo, me_level, te_level, runs, quantity, notes, cost_per_run) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            bp_rows,
        )
        bpo_by_type = {int(row[2]): int(row[0]) for row in bp_rows if row[3] == 1}
        any_bp_by_type: dict[int, int] = {}
        for row in bp_rows:
            any_bp_by_type.setdefault(int(row[2]), int(row[0]))

        # ── 技能（角色设置页 / 精炼产率 / 产线容量都读它） ──
        conn.executemany(
            "INSERT OR REPLACE INTO user_skills (skill_type_id, level) VALUES (?,?)",
            [(skill_id, 5) for skill_id in (3380, 3388, 11450, 24268, 45746, 45748)],
        )

        # ── 生产计划：≥8 条，覆盖三种状态 × 制造/科研/反应，含子项拆解 ──
        plan_rows = _build_plan_rows(items, prices, any_bp_by_type, bpo_by_type, rng, anchor)
        columns = (
            "id, product_type_id, product_name, blueprint_type_id, runs, parallels, me_level, te_level, "
            "mat_hub, sell_hub, facility, char_name, status, profit, margin, score, material_cost, created_at, "
            "started_at, completed_at, iskph, notes, group_number, sub_level, output_location, market_margin, "
            "personal_margin, daily_output, materials_ready, calculated_time, facility_cost_mult, deposit_hangar_id, "
            "deposited, assigned_blueprint_id, mat_hangar_id, material_short, solar_system_id, deducted_materials, "
            "source_mother_ids, component_parent_type_id, demand, material_cost_snapshot, activity, decryptor_type_id, "
            "success_rate, research_target_level, actual_output_runs"
        )
        placeholders = ",".join("?" * len(columns.split(",")))
        conn.executemany(f"INSERT OR REPLACE INTO production_plans ({columns}) VALUES ({placeholders})", plan_rows)

        bindings = []
        for row in plan_rows:
            plan_id = int(row[0])
            assigned = row[columns.split(", ").index("assigned_blueprint_id")]
            if assigned:
                bindings.append((plan_id, int(assigned), int(row[4])))
        conn.executemany(
            "INSERT OR REPLACE INTO plan_blueprint_bindings (plan_id, blueprint_id, runs_used) VALUES (?,?,?)",
            bindings,
        )

        # ── 资产快照：≥14 天（实际 120 天），总资产 = 库存 + 挂单 + 产线 + 钱包 ──
        wallet = 3_184_502_915.44
        inventory_value = 1_842_300_000.0
        line_value = 486_500_000.0
        snapshot_rows = []
        for offset in range(ASSET_DAYS - 1, -1, -1):
            day = (anchor - timedelta(days=offset)).isoformat()
            wobble = 1.0 + rng.uniform(-0.012, 0.016) + (ASSET_DAYS - offset) * 0.0004
            inv = round(inventory_value * wobble, 2)
            orders = round(820_000_000.0 * (1.0 + rng.uniform(-0.06, 0.08)), 2)
            line = round(line_value * (1.0 + rng.uniform(-0.05, 0.06)), 2)
            cash = round(wallet * (1.0 + rng.uniform(-0.02, 0.03)), 2)
            snapshot_rows.append(
                (day, round(inv + orders + line + cash, 2), orders, inv, line, cash, f"{day} 23:50:00")
            )
        conn.executemany(
            "INSERT OR REPLACE INTO asset_snapshots (snap_date, total, orders, inventory, line_value, wallet, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            snapshot_rows,
        )

        # ── 挂单：买单 + 卖单各若干（交易中心价格取自演示 market.db） ──
        order_types = ordered_ids[:12]
        order_rows = []
        for index, type_id in enumerate(order_types):
            is_buy = index % 2
            qty_total = rng.randint(5_000, 60_000)
            remain = int(qty_total * rng.uniform(0.35, 1.0))
            price = price_of(type_id) * (rng.uniform(0.90, 0.985) if is_buy else rng.uniform(1.02, 1.15))
            order_rows.append(
                (
                    880000000 + index,
                    is_buy,
                    round(price, 2),
                    qty_total,
                    remain,
                    60003760,
                    f"演示枢纽空间站 {index % 4 + 1}",
                    type_id,
                    _item_name(conn_ref, type_id),
                    f"{(anchor - timedelta(days=index)).isoformat()}T11:20:00Z",
                    90,
                    900000000 + (index % 2),
                    0,
                    f"{anchor.isoformat()} 12:30:00",
                )
            )
        conn.executemany(
            "INSERT OR REPLACE INTO open_orders "
            "(order_id, is_buy, price, volume_total, volume_remain, location_id, location_name, type_id, type_name, "
            " issued, duration, char_id, is_corp, imported_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            order_rows,
        )

        conn.executemany(
            "INSERT OR REPLACE INTO order_events (order_id, applied_at, outcome, is_buy, price, volume, delta) "
            "VALUES (?,?,?,?,?,?,?)",
            [
                (880000000, f"{anchor.isoformat()} 10:05:00", "filled", 0, 1_250_000.0, 400, 500_000_000.0),
                (880000001, f"{anchor.isoformat()} 10:12:00", "filled", 1, 980_000.0, 250, -245_000_000.0),
                (880000002, f"{anchor.isoformat()} 10:31:00", "cancelled", 0, 640_000.0, 120, 0.0),
            ],
        )

        # ── 关注列表：4 个物品，其中 1 个触发价格阈值 ──
        watch_ids = [int(t) for t in [items["products"][0][0], items["products"][1][0], MINERAL_TYPES[0], outlier_type]]
        watch_rows = []
        for index, type_id in enumerate(watch_ids):
            sell_now = price_of(type_id) * 1.04
            if index == 2:  # 这一行触发：卖价 ≥ 阈值
                threshold_sell = round(sell_now * 0.95, 2)
                note = "演示：已触发卖价提醒（合成数据）"
            else:
                threshold_sell = round(sell_now * 1.35, 2)
                note = "演示关注（合成数据）"
            watch_rows.append(
                (
                    type_id,
                    HUB_REGIONS["Jita"],
                    note,
                    round(price_of(type_id) * 0.95, 2),
                    threshold_sell,
                    round(price_of(type_id) * 1.03, 2),
                    round(sell_now, 2),
                    round(price_of(type_id) * 0.98, 2),
                    f"{(anchor - timedelta(days=index + 2)).isoformat()} 08:00:00",
                    f"{anchor.isoformat()} 08:30:00",
                )
            )
        conn.executemany(
            "INSERT INTO watchlist_items "
            "(type_id, region_id, note, price_threshold_buy, price_threshold_sell, last_buy_price, last_sell_price, "
            " added_price, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            watch_rows,
        )

        # ── 采购清单 / 价格快照（页面次级区块） ──
        conn.executemany(
            "INSERT INTO procurement_items (type_id, item_name, quantity, hub, priority, status, notes, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            [
                (
                    int(items["materials"][index]),
                    _item_name(conn_ref, int(items["materials"][index])),
                    50_000 + index * 8_000,
                    "Jita",
                    "normal",
                    "pending",
                    "演示采购项（合成数据）",
                    f"{anchor.isoformat()} 09:20:00",
                )
                for index in range(6)
            ],
        )
        conn.executemany(
            "INSERT OR REPLACE INTO price_snapshots (type_id, region_id, sell_price, buy_price, snapshot_time) "
            "VALUES (?,?,?,?,?)",
            [
                (
                    int(t),
                    HUB_REGIONS["Jita"],
                    round(price_of(t) * 1.03, 2),
                    round(price_of(t) * 0.97, 2),
                    f"{(anchor - timedelta(days=offset)).isoformat()} 12:00:00",
                )
                for offset in range(5)
                for t in [items["products"][0][0], MINERAL_TYPES[0]]
            ],
        )

        # ── ESI 令牌：**只放明显不可用的演示占位**（不是任何真实凭据） ──
        conn.executemany(
            "INSERT OR REPLACE INTO esi_tokens "
            "(character_id, character_name, refresh_token, access_token, access_expires_at, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            [
                (
                    900000001,
                    CHAR_MAIN,
                    "DEMO-PLACEHOLDER-TOKEN-NOT-A-REAL-CREDENTIAL",
                    None,
                    None,
                    f"{anchor.isoformat()} 08:00:00",
                ),
                (
                    900000002,
                    CHAR_ALT,
                    "DEMO-PLACEHOLDER-TOKEN-NOT-A-REAL-CREDENTIAL",
                    None,
                    None,
                    f"{anchor.isoformat()} 08:00:00",
                ),
            ],
        )

        conn.commit()
        stats = {
            "hangars": _count(conn, "hangars"),
            "inventory_items": _count(conn, "inventory_items"),
            "user_blueprints": _count(conn, "user_blueprints"),
            "production_plans": _count(conn, "production_plans"),
            "asset_snapshots": _count(conn, "asset_snapshots"),
            "open_orders": _count(conn, "open_orders"),
            "watchlist_items": _count(conn, "watchlist_items"),
            "plan_blueprint_bindings": _count(conn, "plan_blueprint_bindings"),
            "procurement_items": _count(conn, "procurement_items"),
            "price_snapshots": _count(conn, "price_snapshots"),
            "order_events": _count(conn, "order_events"),
            "esi_tokens": _count(conn, "esi_tokens"),
        }
    finally:
        conn.close()

    _set_user_version(target, _expected_version("user"))
    return stats


def _count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _item_name(conn_ref: sqlite3.Connection, type_id: int) -> str:
    row = conn_ref.execute("SELECT zh_name, en_name FROM item WHERE type_id = ?", (int(type_id),)).fetchone()
    if not row:
        return f"演示物品 #{type_id}"
    return str(row[0] or row[1] or f"演示物品 #{type_id}")


def _build_plan_rows(
    items: dict,
    prices: DemoPrices,
    any_bp: dict[int, int],
    bpo_by_type: dict[int, int],
    rng: random.Random,
    anchor: date,
) -> list[tuple]:
    """构造 ≥8 条演示计划：覆盖 pending/in_progress/ready、制造+科研+反应、含子项拆解。"""
    created = f"{anchor.isoformat()} 09:30:00"
    started = f"{anchor.isoformat()} 10:05:00"
    main_char, alt_char = CHAR_NAMES

    products = items["products"]
    reactions = items["reactions"]

    def product_plan(product_type_id: int, bp_type_id: int, _name: str = "") -> dict:
        bp_row_id = any_bp.get(int(bp_type_id))
        bound_id = bpo_by_type.get(int(bp_type_id))
        cost = float(prices.price.get(int(product_type_id)) or 1000.0) * 120
        return {
            "blueprint_type_id": int(bp_type_id),
            "assigned_blueprint_id": bound_id,
            "profit": round(cost * 0.22, 2),
            "margin": 22.0,
            "score": round(rng.uniform(60.0, 95.0), 1),
            "material_cost": round(cost, 2),
            "bound_id": bp_row_id,
        }

    # 计划 1（母项，pending，待启动 → 展示材料缺口）
    mother = product_plan(*products[0])
    row1 = _spec(
        id=1,
        product_type_id=int(products[0][0]),
        product_name=products[0][2],
        status="pending",
        char_name=main_char,
        runs=12,
        parallels=2,
        me_level=10,
        te_level=20,
        group_number=1,
        sub_level=0,
        mat_hangar_id=2,
        deposit_hangar_id=1,
        solar_system_id=30000142,
        demand=int(products[0][0]),
        source_mother_ids="",
        component_parent_type_id=None,
        output_location=HANGAR_MAIN,
        materials_ready=0,
        material_short="",
        notes="演示：待启动，材料缺口由小助手显示",
        activity="manufacturing",
        **mother,
    )
    # 计划 2 / 3（子项，pending，引用母项 1）
    child_a = product_plan(*products[1])
    row2 = _spec(
        id=2,
        product_type_id=int(products[1][0]),
        product_name=products[1][2],
        status="pending",
        char_name=main_char,
        runs=6,
        parallels=1,
        me_level=8,
        te_level=16,
        group_number=1,
        sub_level=1,
        mat_hangar_id=2,
        deposit_hangar_id=1,
        solar_system_id=30000142,
        demand=48,
        source_mother_ids="1",
        component_parent_type_id=int(products[0][0]),
        output_location=HANGAR_MAIN,
        materials_ready=1,
        notes="演示：母项 1 的自制件",
        activity="manufacturing",
        **child_a,
    )
    child_b = product_plan(*products[2])
    row3 = _spec(
        id=3,
        product_type_id=int(products[2][0]),
        product_name=products[2][2],
        status="pending",
        char_name=alt_char,
        runs=4,
        parallels=1,
        me_level=6,
        te_level=12,
        group_number=1,
        sub_level=1,
        mat_hangar_id=3,
        deposit_hangar_id=1,
        solar_system_id=30002187,
        demand=24,
        source_mother_ids="1",
        component_parent_type_id=int(products[0][0]),
        output_location=HANGAR_MAIN,
        materials_ready=1,
        notes="演示：母项 1 的自制件（第二张）",
        activity="manufacturing",
        **child_b,
    )
    # 计划 4（in_progress 制造）
    prod4 = product_plan(*products[3])
    row4 = _spec(
        id=4,
        product_type_id=int(products[3][0]),
        product_name=products[3][2],
        status="in_progress",
        char_name=main_char,
        runs=20,
        parallels=3,
        me_level=10,
        te_level=18,
        mat_hangar_id=2,
        deposit_hangar_id=1,
        solar_system_id=30000142,
        demand=0,
        output_location=HANGAR_MAIN,
        materials_ready=1,
        deducted_materials=json.dumps({str(int(products[4][0])): 1200}, ensure_ascii=False),
        material_cost_snapshot=json.dumps(
            {
                "total": 812_500_000.0,
                "unit": {str(int(products[4][0])): round(float(prices.price.get(int(products[4][0])) or 100.0), 2)},
            },
            ensure_ascii=False,
        ),
        notes="演示：生产中",
        activity="manufacturing",
        **prod4,
    )
    # 计划 5（in_progress 反应）
    reaction_product = reactions[0]
    reaction_bp_id = int(reaction_product[1])
    row5 = _spec(
        id=5,
        product_type_id=int(reaction_product[0]),
        product_name=reaction_product[2],
        blueprint_type_id=reaction_bp_id,
        assigned_blueprint_id=any_bp.get(reaction_bp_id),
        status="in_progress",
        char_name=alt_char,
        runs=30,
        parallels=2,
        me_level=0,
        te_level=0,
        mat_hangar_id=3,
        deposit_hangar_id=3,
        solar_system_id=30002187,
        demand=0,
        output_location=HANGAR_REACTOR,
        materials_ready=1,
        notes="演示：反应作业进行中",
        activity="reaction",
        profit=round(float(prices.price.get(int(reaction_product[0])) or 1000.0) * 90, 2),
        margin=18.5,
        score=78.0,
        material_cost=round(float(prices.price.get(int(reaction_product[0])) or 1000.0) * 130, 2),
    )
    # 计划 6（ready 制造，待下线）
    prod6 = product_plan(*products[5])
    row6 = _spec(
        id=6,
        product_type_id=int(products[5][0]),
        product_name=products[5][2],
        status="ready",
        char_name=main_char,
        runs=15,
        parallels=2,
        me_level=10,
        te_level=20,
        mat_hangar_id=2,
        deposit_hangar_id=1,
        solar_system_id=30000142,
        demand=0,
        output_location=HANGAR_MAIN,
        materials_ready=1,
        deposited=0,
        notes="演示：成品待下线",
        activity="manufacturing",
        **prod6,
    )
    # 计划 7（拷贝，pending）
    copy_bp = int(items["copy_bps"][0])
    row7 = _spec(
        id=7,
        product_type_id=copy_bp,
        product_name=_bp_display_name(bp_label="演示拷贝"),
        blueprint_type_id=copy_bp,
        assigned_blueprint_id=bpo_by_type.get(copy_bp),
        status="pending",
        char_name=main_char,
        runs=5,
        parallels=1,
        me_level=0,
        te_level=0,
        mat_hangar_id=1,
        solar_system_id=30000142,
        output_location=HANGAR_MAIN,
        materials_ready=1,
        notes="演示：拷贝作业（科研）",
        activity="copying",
        profit=0.0,
        margin=0.0,
        score=0.0,
        material_cost=round(float(prices.price.get(copy_bp) or 1000.0) * 0.5, 2),
    )
    # 计划 8（发明，pending，带解码器）
    invention_bp = int(items["invention_bps"][0])
    row8 = _spec(
        id=8,
        product_type_id=invention_bp,
        product_name=_bp_display_name(bp_label="演示发明"),
        blueprint_type_id=invention_bp,
        assigned_blueprint_id=any_bp.get(invention_bp),
        status="pending",
        char_name=alt_char,
        runs=4,
        parallels=1,
        me_level=0,
        te_level=0,
        mat_hangar_id=1,
        solar_system_id=30000142,
        output_location=HANGAR_MAIN,
        materials_ready=1,
        notes="演示：发明作业（科研）",
        activity="invention",
        decryptor_type_id=34268,
        success_rate=0.52,
        profit=0.0,
        margin=0.0,
        score=0.0,
        material_cost=round(float(prices.price.get(invention_bp) or 1000.0) * 0.35, 2),
    )
    # 计划 9 / 10（ME / TE 研究，pending）
    research_bp = int(items["copy_bps"][1])
    row9 = _spec(
        id=9,
        product_type_id=research_bp,
        product_name=_bp_display_name(bp_label="演示材料效率研究"),
        blueprint_type_id=research_bp,
        assigned_blueprint_id=bpo_by_type.get(research_bp),
        status="pending",
        char_name=main_char,
        runs=1,
        parallels=1,
        me_level=8,
        te_level=0,
        mat_hangar_id=1,
        solar_system_id=30000142,
        output_location=HANGAR_MAIN,
        materials_ready=1,
        notes="演示：材料效率研究（科研）",
        activity="researching_material_efficiency",
        research_target_level=10,
        profit=0.0,
        margin=0.0,
        score=0.0,
        material_cost=round(float(prices.price.get(research_bp) or 1000.0) * 0.12, 2),
    )
    research_bp2 = int(items["copy_bps"][2])
    row10 = _spec(
        id=10,
        product_type_id=research_bp2,
        product_name=_bp_display_name(bp_label="演示生产效率研究"),
        blueprint_type_id=research_bp2,
        assigned_blueprint_id=bpo_by_type.get(research_bp2),
        status="pending",
        char_name=alt_char,
        runs=1,
        parallels=1,
        me_level=0,
        te_level=10,
        mat_hangar_id=1,
        solar_system_id=30000142,
        output_location=HANGAR_MAIN,
        materials_ready=1,
        notes="演示：生产效率研究（科研）",
        activity="researching_time_efficiency",
        research_target_level=10,
        profit=0.0,
        margin=0.0,
        score=0.0,
        material_cost=round(float(prices.price.get(research_bp2) or 1000.0) * 0.12, 2),
    )
    # 计划 11（已完成） + 12（in_progress，第二个人物）
    prod11 = product_plan(*products[6])
    row11 = _spec(
        id=11,
        product_type_id=int(products[6][0]),
        product_name=products[6][2],
        status="completed",
        char_name=main_char,
        runs=8,
        parallels=1,
        me_level=10,
        te_level=20,
        mat_hangar_id=2,
        deposit_hangar_id=1,
        solar_system_id=30000142,
        output_location=HANGAR_MAIN,
        materials_ready=1,
        deposited=1,
        notes="演示：已完成",
        activity="manufacturing",
        **prod11,
    )
    prod12 = product_plan(*products[7])
    row12 = _spec(
        id=12,
        product_type_id=int(products[7][0]),
        product_name=products[7][2],
        status="in_progress",
        char_name=alt_char,
        runs=25,
        parallels=2,
        me_level=8,
        te_level=14,
        mat_hangar_id=3,
        deposit_hangar_id=3,
        solar_system_id=30002187,
        output_location=HANGAR_REACTOR,
        materials_ready=1,
        notes="演示：第二个人物的产线",
        activity="manufacturing",
        **prod12,
    )

    rows = []
    for spec in (row1, row2, row3, row4, row5, row6, row7, row8, row9, row10, row11, row12):
        started_at = started if spec["status"] in ("in_progress", "running", "ready", "completed") else None
        completed_at = f"{anchor.isoformat()} 18:40:00" if spec["status"] == "completed" else None
        calculated_time = float(rng.randint(3_600, 96_000))
        rows.append(
            (
                spec["id"],
                spec["product_type_id"],
                spec["product_name"],
                spec["blueprint_type_id"],
                spec["runs"],
                spec["parallels"],
                spec["me_level"],
                spec["te_level"],
                "Jita",
                "Jita",
                HANGAR_LINE,
                spec["char_name"],
                spec["status"],
                spec["profit"],
                spec["margin"],
                spec["score"],
                spec["material_cost"],
                created,
                started_at,
                completed_at,
                round(spec["profit"] / max(calculated_time / 3600.0, 0.5), 2),
                spec["notes"],
                spec.get("group_number", 0),
                spec.get("sub_level", 0),
                spec["output_location"],
                round(spec["margin"] * 0.6, 2),
                round(spec["margin"] * 0.9, 2),
                round(max(spec["runs"] * spec["parallels"] / 12.0, 1.0), 2),
                spec.get("materials_ready", 1),
                calculated_time,
                1.0,
                spec.get("deposit_hangar_id"),
                spec.get("deposited", 0),
                spec.get("assigned_blueprint_id"),
                spec["mat_hangar_id"],
                spec.get("material_short", ""),
                spec["solar_system_id"],
                spec.get("deducted_materials", ""),
                spec.get("source_mother_ids", ""),
                spec.get("component_parent_type_id"),
                spec.get("demand", 0),
                spec.get("material_cost_snapshot", ""),
                spec["activity"],
                spec.get("decryptor_type_id"),
                spec.get("success_rate"),
                spec.get("research_target_level", 0),
                spec.get("actual_output_runs"),
            )
        )
    return rows


def _spec(**fields) -> dict:
    """把一堆关键字收成计划行的字段字典（便于与 `**base` 合并的 `dict(...)` 同义写法）。"""
    return fields


def _bp_display_name(bp_label: str) -> str:
    """科研计划的 `product_name`（产物是蓝图）—— 名字明显是演示数据。"""
    return f"{bp_label}（演示蓝图）"


# ════════════════════════════════════════════════════════════════
#  7. 建 items.db（旧兼容单库：只要存在、有表、无数据）
# ════════════════════════════════════════════════════════════════


def build_items_db() -> int:
    """旧版 `items.db`：建表但**不写数据**。

    它的唯一作用是让 `core.paths.database_path()` 指得到东西、并让演示根与真实安装
    同形。真正防止 `Main._migrate_split_db()` 动演示库的是 user.db 里那条
    `_split_migration_complete` 标记（见 `build_user_db`）。
    """
    source = SOURCE_DB_DIR / "items.db"
    ddl = read_source_schema(source) if source.exists() else []
    target = DEMO_ROOT / "database" / "items.db"
    _apply_ddl(target, ddl)
    return len(ddl)


# ════════════════════════════════════════════════════════════════
#  8. data/*.json（全部合成）
# ════════════════════════════════════════════════════════════════


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_data_dir(anchor: date, market: dict) -> dict:
    """写演示根的 `data/` 配置：关掉一切需要联网/真实账号的东西。"""
    data_dir = DEMO_ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    # settings.json：**auto_update_enabled=False**（离线演示的关键开关）
    _write_json(
        data_dir / "settings.json",
        {
            "update_regions": list(HUB_REGIONS.keys()),
            "theme": "fluent-dark",
            "settings_version": 1,
            "default_mat_hangar_id": 2,
            "price_settings": {
                "mat_hub": "Jita",
                "mat_price_type": "sell",
                "mat_mult": 1.0,
                "prod_hub": "Jita",
                "prod_price_type": "sell",
                "prod_mult": 1.0,
            },
            "procurement_pin": True,
            "update_interval": 30,
            "auto_update_enabled": False,
            "window_pin": False,
            "font_size": 14,
            "production_launcher_pin": False,
            "default_research_hangar_id": 1,
            "default_deposit_hangar_id": 1,
            "default_trade_hangar_id": 4,
            "wallet_balance": 3_184_502_915.44,
            "esi_include_corp_wallet": False,
            "backup_enabled": False,
            "backup_keep": 5,
            "last_backup_date": "",
        },
    )

    # char_config.json：角色名与技能全部虚构
    _write_json(
        data_dir / "char_config.json",
        {
            "current": CHAR_MAIN,
            "characters": {
                CHAR_MAIN: {
                    "skills": _demo_skills(level=5),
                    "market": {hub.lower(): {"faction_standing": 5.0, "corp_standing": 5.0} for hub in HUB_REGIONS},
                    "implants": [None, None, None],
                },
                CHAR_ALT: {
                    "skills": _demo_skills(level=4),
                    "market": {hub.lower(): {"faction_standing": 4.0, "corp_standing": 4.0} for hub in HUB_REGIONS},
                    "implants": [None, None, None],
                },
            },
        },
    )

    # score_settings.json / 大盘页设置 / 制造浏览器设置
    _write_json(
        data_dir / "score_settings.json",
        {
            "mfg": {"hub": "Jita", "char": CHAR_MAIN, "tax": 0.0},
            "trade": {"bh": "Amarr", "sh": "Jita", "bs": "sell", "ss": "sell", "char": CHAR_ALT},
        },
    )
    _write_json(data_dir / "market_monitor_settings.json", {"guide_dismissed": True, "range_index": 2})
    _write_json(data_dir / "mfg_browser_settings.json", {"hub": "Jita", "category": 0, "search": ""})

    # 搜索历史（虚构关键词，全是演示物品名）
    _write_json(
        data_dir / "search_history.json",
        [
            {"query": estimate_item_name(34), "time": _epoch(anchor, 0)},
            {"query": estimate_item_name(39), "time": _epoch(anchor, 1)},
            {"query": "PLEX", "time": _epoch(anchor, 2)},
        ],
    )
    # 贸易购物车（A→B 价差排行的候选）
    _write_json(
        data_dir / "trade_cart.json",
        {
            "items": [
                {
                    "type_id": int(market["history_types"][3]),
                    "name": "演示候选物品 1",
                    "from_hub": "Jita",
                    "to_hub": "Amarr",
                    "qty": 500,
                },
                {
                    "type_id": int(market["history_types"][9]),
                    "name": "演示候选物品 2",
                    "from_hub": "Amarr",
                    "to_hub": "Dodixie",
                    "qty": 1200,
                },
            ]
        },
    )
    _write_json(data_dir / "window_geometry.json", {"x": 120, "y": 80, "width": 1600, "height": 1000})
    _write_json(data_dir / "update_progress.json", {"stage": "idle", "percent": 100})

    # 公共项目文件：terminology（术语/基础矿物覆盖名）从仓库复制，不是账号数据
    terminology = SOURCE_DATA_DIR / "terminology.json"
    if terminology.exists():
        shutil.copy2(terminology, data_dir / "terminology.json")

    (data_dir / "caches" / "icons").mkdir(parents=True, exist_ok=True)
    return {"data_dir": str(data_dir)}


def _demo_skills(level: int) -> dict:
    """演示角色技能表 —— 覆盖产线容量/精炼/发明/时间与材料效率用到的键。"""
    names = [
        "工业理论",
        "高级工业理论",
        "工业配置学",
        "高级工业配置学",
        "批量生产学",
        "高级量产技术",
        "实验室运作理论",
        "高级实验室运作理论",
        "大规模反应理论",
        "高级大规模反应理论",
        "提炼学概论",
        "提炼效率理论",
        "凡晶石处理技术",
        "科学原理",
        "研究概论",
        "冶金学",
        "高级量产技术",
    ]
    return dict.fromkeys(dict.fromkeys(names), level)


def _epoch(anchor: date, days_ago: int) -> float:
    return datetime(anchor.year, anchor.month, anchor.day, 12, 0, 0).timestamp() - days_ago * 86_400


# ════════════════════════════════════════════════════════════════
#  9. 图标（只复制被演示数据用到的几十个）
# ════════════════════════════════════════════════════════════════


def copy_icons(type_ids: list[int]) -> int:
    """从公共图标缓存里挑对应 type_id 的 PNG 复制（**不整目录复制**）。"""
    src_dir = SOURCE_DATA_DIR / "caches" / "icons"
    dst_dir = DEMO_ROOT / "data" / "caches" / "icons"
    dst_dir.mkdir(parents=True, exist_ok=True)
    if not src_dir.is_dir():
        return 0
    copied = 0
    for type_id in type_ids:
        src = src_dir / f"{int(type_id)}.png"
        if src.is_file():
            shutil.copy2(src, dst_dir / src.name)
            copied += 1
    return copied


# ════════════════════════════════════════════════════════════════
#  10. 自检（逐项 PASS/FAIL；能用真实服务的就用真实服务）
# ════════════════════════════════════════════════════════════════


class Checker:
    def __init__(self) -> None:
        self.rows: list[tuple[bool, str]] = []

    def check(self, ok: bool, label: str, detail: str = "") -> bool:
        self.rows.append((bool(ok), label if not detail else f"{label}  ·  {detail}"))
        return bool(ok)

    def report(self) -> int:
        width = max((len(r[1]) for r in self.rows), default=0)
        for ok, label in self.rows:
            print(f"[自检] {'PASS' if ok else 'FAIL'}  {label.ljust(width)}")
        passed = sum(1 for ok, _ in self.rows if ok)
        print(f"[自检] {passed}/{len(self.rows)} 项通过")
        return 0 if passed == len(self.rows) else 1


def run_self_check(market: dict, stats_meta: dict) -> int:
    """逐项验证「每个页面所需的数据都在」。"""
    import sqlite3 as _sq

    from services import asset_snapshot_service, inventory_manager, plan_service, watchlist_manager
    from services.init_check import (
        check_blueprint_names,
        check_blueprints,
        check_dogma_attrs,
        check_icons,
        check_implants,
        check_industry,
        check_item_names_ratio,
        check_items,
        check_market_tree,
        check_prices,
        check_schema,
        check_stations,
        check_structure_rigs,
        check_type_materials,
        check_universe,
    )
    from services.market_browser_service import fetch_cross_region_spread
    from services.market_index_service import INDEX_KEYS, get_index_cards
    from services.market_movers_service import get_movers
    from services.plan_execution import check_materials
    from services.schema_migrations import DB_SCHEMA_VERSIONS, get_db_version

    c = Checker()
    db_dir = DEMO_ROOT / "database"

    # ── 数据来源：schema 与真实库同形 + 版本号正确 ──
    for alias in ("ref", "mkt", "user", "bp"):
        version = get_db_version(alias)
        c.check(
            version == DB_SCHEMA_VERSIONS[alias],
            f"schema 版本 {alias}",
            f"v{version} / 期望 v{DB_SCHEMA_VERSIONS[alias]}",
        )
    c.check(check_schema(), "init_check.check_schema() 全库版本一致")

    # ── reference.db（整文件复制公共 SDE 派生库） ──
    named = check_items()
    c.check(named >= 50_000, "reference.item 带名行数 ≥50000", f"{named:,} 行")
    c.check(check_item_names_ratio() < 0.05, "reference.item 缺名比例 <5%", f"{check_item_names_ratio():.4f}")
    c.check(check_market_tree() > 500, "reference.market_tree >500", f"{check_market_tree()} 行")
    c.check(check_implants() > 30, "reference.item_dogma >30", f"{check_implants()} 行")
    c.check(check_industry() > 100, "reference.industry_system_costs >100", f"{check_industry()} 行")
    c.check(check_structure_rigs() > 80, "reference.structure_rigs >80", f"{check_structure_rigs()} 行")
    c.check(check_type_materials() > 0, "reference.reprocessing_materials >0", f"{check_type_materials()} 行")
    c.check(check_dogma_attrs() > 0, "reference.dogma_attribute >0", f"{check_dogma_attrs()} 行")
    c.check(check_stations() > 0, "reference.station >0", f"{check_stations()} 行")
    c.check(check_universe() > 0, "reference.solar_system >0", f"{check_universe()} 行")
    c.check(check_blueprint_names() < 100, "蓝图名称缺失 <100", f"{check_blueprint_names()} 行")

    # ── blueprint.db ──
    bp_rows = check_blueprints()
    c.check(bp_rows > 1_000, "blueprint_activities >1000", f"{bp_rows:,} 行")

    # ── market.db ──
    c.check(check_prices() > 0, "market_prices 有行", f"{check_prices():,} 行")
    conn = _sq.connect(f"file:{(db_dir / 'market.db').as_posix()}?mode=ro", uri=True)
    try:
        hub_regions = int(conn.execute("SELECT COUNT(DISTINCT region_id) FROM market_prices").fetchone()[0])
        history_days = int(conn.execute("SELECT COUNT(DISTINCT date) FROM price_history").fetchone()[0])
        history_types = int(conn.execute("SELECT COUNT(DISTINCT type_id) FROM price_history").fetchone()[0])
        index_days = int(conn.execute("SELECT COUNT(DISTINCT date) FROM market_index_daily").fetchone()[0])
        index_keys = int(conn.execute("SELECT COUNT(DISTINCT type_id) FROM market_index_daily").fetchone()[0])
        snap_days = int(conn.execute("SELECT COUNT(DISTINCT date) FROM market_volume_snapshots").fetchone()[0])
        contracts = {
            row[0]: int(row[1])
            for row in conn.execute("SELECT type, COUNT(*) FROM public_contracts GROUP BY type").fetchall()
        }
        contract_items = int(conn.execute("SELECT COUNT(*) FROM contract_items").fetchone()[0])
        issuers = int(conn.execute("SELECT COUNT(*) FROM contract_issuers").fetchone()[0])
        spread_types = int(
            conn.execute(
                "SELECT COUNT(DISTINCT type_id) FROM market_prices WHERE region_id IN (10000002, 10000043)"
            ).fetchone()[0]
        )
    finally:
        conn.close()
    c.check(hub_regions == len(HUB_REGIONS), "物品查询 · 五中心买卖价", f"{hub_regions} 个贸易中心")
    c.check(
        history_days >= 30 and history_types >= 10,
        "市场监控 · 逐日成交历史",
        f"{history_days} 天 / {history_types} 个物品",
    )
    c.check(
        index_days >= 30 and index_keys == len(INDEX_KEYS),
        "市场监控 · 大盘指数序列",
        f"{index_keys} 条 × {index_days} 天",
    )
    c.check(snap_days >= 2, "市场贸易 · 挂单量快照", f"{snap_days} 天")
    c.check(contracts.get("courier", 0) >= 2, "合同市场 · 运输合同", f"{contracts.get('courier', 0)} 条")
    c.check(
        contracts.get("item_exchange", 0) >= 2, "合同市场 · 物品交换合同", f"{contracts.get('item_exchange', 0)} 条"
    )
    c.check(
        contract_items > 0 and issuers > 0,
        "合同市场 · 内容物与发行方",
        f"{contract_items} 行内容物 / {issuers} 个发行方",
    )
    c.check(spread_types > 0, "市场贸易 · A→B 跨区价差候选", f"{spread_types} 个物品有两个中心的价格")

    # 真实服务实测：指数卡 / 异动榜 / 跨区排行
    cards = get_index_cards()
    with_value = [card for card in cards if card.get("value") is not None]
    c.check(
        len(with_value) == len(INDEX_KEYS), "get_index_cards() 五条指数都有点位", f"{len(with_value)}/{len(INDEX_KEYS)}"
    )
    movers = get_movers(days=3, limit=50)
    c.check(len(movers) > 0, "get_movers(days=3) 异动榜有行", f"{len(movers)} 行")
    rank = fetch_cross_region_spread(10000002, 10000043)
    c.check(len(rank) > 0, "fetch_cross_region_spread(Jita→Amarr) 有行", f"{len(rank)} 行")
    rank_filtered = fetch_cross_region_spread(
        10000002, 10000043, group_ids=_first_market_group(int(market["thick_type"]))
    )
    c.check(len(rank_filtered) > 0, "跨区排行 · 按分类筛选可用", f"{len(rank_filtered)} 行")

    # ── 离群价 / 正常厚盘的实测判定（新版「⚠ 市价不可信」） ──
    from domain.market_depth import sell_price_reliable

    outlier_row = _market_row(db_dir / "market.db", int(market["outlier_type"]), 10000002)
    thick_row = _market_row(db_dir / "market.db", int(market["thick_type"]), 10000002)
    outlier_ok = sell_price_reliable(outlier_row) is False
    thick_ok = sell_price_reliable(thick_row) is True
    c.check(
        outlier_ok,
        "domain.market_depth.sell_price_reliable(离群价) is False",
        f"type {market['outlier_type']} 卖价 {outlier_row['sell_price']:,.0f} / 卖量 {outlier_row['sell_volume']:,}",
    )
    c.check(
        thick_ok,
        "domain.market_depth.sell_price_reliable(厚盘) is True",
        f"type {market['thick_type']} 卖量 {thick_row['sell_volume']:,}",
    )

    # ── user.db ──
    conn = _sq.connect(f"file:{(db_dir / 'user.db').as_posix()}?mode=ro", uri=True)
    try:
        counts = {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in (
                "hangars",
                "inventory_items",
                "user_blueprints",
                "production_plans",
                "asset_snapshots",
                "open_orders",
                "watchlist_items",
                "order_events",
            )
        }
        plan_statuses = {str(r[0]) for r in conn.execute("SELECT DISTINCT status FROM production_plans").fetchall()}
    finally:
        conn.close()
    for table, label, minimum in (
        ("hangars", "user.hangars", 4),
        ("inventory_items", "user.inventory_items（仓库行数）", 20),
        ("user_blueprints", "user.user_blueprints（蓝图张数）", 6),
        ("production_plans", "user.production_plans（计划条数）", 8),
        ("asset_snapshots", "user.asset_snapshots（资产折线）", 14),
        ("open_orders", "user.open_orders（挂单列表）", 2),
        ("watchlist_items", "user.watchlist_items（关注列表）", 3),
    ):
        c.check(counts[table] >= minimum, f"{label} ≥{minimum}", f"{counts[table]} 行")
    c.check(
        {"pending", "in_progress", "ready"} <= plan_statuses,
        "工业制造 · 覆盖 pending/in_progress/ready",
        "、".join(sorted(plan_statuses)),
    )

    # 蓝图：原图 + 拷贝并存
    blueprints = inventory_manager.get_blueprints(None)
    c.check(len(blueprints) >= 6, "仓库管理 · 蓝图行数 ≥6", f"{len(blueprints)} 张")
    c.check(
        any(b.get("is_bpo") for b in blueprints) and any(not b.get("is_bpo") for b in blueprints),
        "仓库管理 · 原图与拷贝并存",
    )

    # 库存：图标 / 计划占用 / 缺口 / 占用资金 / 不可信市价
    items_rows = inventory_manager.get_items(1, include_derived=True)
    c.check(len(items_rows) >= 1, "仓库管理 · 机库 1 有库存行", f"{len(items_rows)} 行")
    icons_ok = sum(
        1 for row in items_rows if (DEMO_ROOT / "data" / "caches" / "icons" / f"{row['type_id']}.png").is_file()
    )
    c.check(icons_ok >= 10, "仓库管理 · 库存行有图标", f"{icons_ok}/{len(items_rows)} 行有 PNG")
    c.check(any(int(row.get("plan_usage") or 0) > 0 for row in items_rows), "仓库管理 · 「规划占用」列有数")
    c.check(
        any(int(row.get("plan_usage") or 0) - int(row.get("quantity") or 0) > 0 for row in items_rows),
        "仓库管理 · 「缺口」列有数",
    )
    c.check(
        all(float(row.get("cost_price") or 0) > 0 for row in items_rows),
        "仓库管理 · 「占用资金」列有数（成本价非 0）",
    )
    total_value = inventory_manager.get_total_value(1, price_type="sell")
    c.check(
        int(total_value.get("unreliable_count") or 0) >= 1 and float(total_value.get("unreliable_total") or 0) > 0,
        "仓库管理 · 「N 项市价不可信未计入」有数",
        f"{total_value.get('unreliable_count')} 项 / {float(total_value.get('unreliable_total') or 0):,.0f} ISK",
    )

    # 计划：类别覆盖 + 子项拆解 + 待启动小助手缺口
    plans = plan_service.load_plans("全部")
    wizard_plans = plan_service.load_plans_for_wizard()
    categories = {str(p.get("category") or "") for p in plans}
    c.check(
        {"manufacturing", "research", "reaction"} <= categories,
        "工业制造 · 覆盖制造+科研+反应三类活动",
        "、".join(sorted(c for c in categories if c)),
    )
    c.check(
        any(int(p.get("sub_level") or 0) > 0 for p in plans)
        and any(str(p.get("source_mother_ids") or "").strip() for p in plans),
        "工业制造 · 子项拆解（sub_level + source_mother_ids）",
    )
    c.check(len(wizard_plans) >= 8, "工业制造 · 待启动小助手数据源 ≥8 条", f"{len(wizard_plans)} 条")
    pending = next((p for p in plans if p.get("status") == "pending" and p.get("mat_hangar_id")), None)
    shortfalls = check_materials(pending, pending.get("mat_hangar_id")) if pending else []
    c.check(len(shortfalls) > 0, "工业制造 · 「待启动小助手」材料缺口 >0", f"{len(shortfalls)} 种缺料")

    # 关注列表：阈值触发
    watch = watchlist_manager.get_watchlist()
    conn = _sq.connect(f"file:{(db_dir / 'user.db').as_posix()}?mode=ro", uri=True)
    conn.execute(f"ATTACH DATABASE '{(db_dir / 'market.db').as_posix()}' AS mkt")
    try:
        triggered = int(
            conn.execute(
                "SELECT COUNT(*) FROM watchlist_items wi JOIN mkt.market_prices mp "
                " ON mp.type_id = wi.type_id AND mp.region_id = wi.region_id "
                "WHERE wi.price_threshold_sell IS NOT NULL AND mp.sell_price >= wi.price_threshold_sell"
            ).fetchone()[0]
        )
    finally:
        conn.close()
    c.check(len(watch) >= 3, "市场监控 · 关注列表 3~5 个物品", f"{len(watch)} 个")
    c.check(triggered >= 1, "市场监控 · 有 1 个关注触发价格阈值", f"{triggered} 个触发")

    # 资产折线：≥14 天且五条线都有值
    series = asset_snapshot_service.load_series(ASSET_DAYS)
    non_zero = {
        key: sum(1 for row in series if float(row.get(key) or 0) > 0)
        for key in ("total", "orders", "inventory", "line_value", "wallet")
    }
    c.check(len(series) >= 14, "物品查询 · 资产折线 ≥14 天快照", f"{len(series)} 天")
    c.check(all(count == len(series) for count in non_zero.values()), "物品查询 · 资产折线 5 条线都有值", str(non_zero))

    # 挂单列表：买 + 卖各有行
    conn = _sq.connect(f"file:{(db_dir / 'user.db').as_posix()}?mode=ro", uri=True)
    try:
        buy_orders = int(conn.execute("SELECT COUNT(*) FROM open_orders WHERE is_buy = 1").fetchone()[0])
        sell_orders = int(conn.execute("SELECT COUNT(*) FROM open_orders WHERE is_buy = 0").fetchone()[0])
        type_name_missing = int(
            conn.execute("SELECT COUNT(*) FROM open_orders WHERE COALESCE(type_name, '') = ''").fetchone()[0]
        )
    finally:
        conn.close()
    c.check(
        buy_orders > 0 and sell_orders > 0 and type_name_missing == 0,
        "物品查询 · 挂单列表（买单/卖单分表）",
        f"买 {buy_orders} / 卖 {sell_orders}",
    )

    # 估价页：物品搜索 + 买/卖价 + 体积 + 精炼价值
    from core.container import get_container
    from services.name_resolver import resolve_item_name

    pricing = get_container().pricing_service
    refining = get_container().refining_service
    clipboard_items = _estimate_clipboard_types()
    price_ok = all(pricing.get_price(tid, "sell", "Jita") for tid in clipboard_items)
    buy_ok = all(pricing.get_price(tid, "buy", "Jita") for tid in clipboard_items)
    c.check(price_ok and buy_ok, "估价页 · 剪贴板物品的买/卖单价都有数", f"{len(clipboard_items)} 个物品")
    ore_type = _first_refinable_ore()
    refine = refining.calc_value(ore_type, quantity=1_000, price_hub="Jita")
    c.check(
        len(refine.get("output") or []) > 0 and refine.get("total_value", 0) > 0,
        "估价页 · 精炼价值可算",
        f"矿石 type {ore_type}",
    )
    c.check(all(_item_volume(tid) > 0 for tid in clipboard_items), "估价页 · 体积列有数")
    _ = resolve_item_name

    # 图标缓存与离线开关
    cached, total = check_icons()
    c.check(cached >= 30, "data/caches/icons 至少几十个图标", f"{cached} 个 PNG（全集 {total}）")
    settings = json.loads((DEMO_ROOT / "data" / "settings.json").read_text(encoding="utf-8"))
    c.check(settings.get("auto_update_enabled") is False, "settings.json auto_update_enabled=false（离线演示）")
    c.check((DEMO_ROOT / "data" / "char_config.json").is_file(), "data/char_config.json（虚构角色）")
    c.check((DEMO_ROOT / "data" / "terminology.json").is_file(), "data/terminology.json 已就位")

    # ── 红线证据：从未读过 user.db 的数据行 ──
    c.check(
        _SOURCE_USER_ROWS_READ == 0,
        "红线：未对 user.db 执行任何数据行查询",
        f"非 schema 查询 {_SOURCE_USER_ROWS_READ} 次",
    )
    c.check(
        SOURCE_DB_DIR / "user.db" != db_dir / "user.db" and (db_dir / "user.db").stat().st_size < 5_000_000,
        "红线：演示 user.db 是新建文件（不是真实库的拷贝）",
        f"{(db_dir / 'user.db').stat().st_size:,} 字节",
    )
    c.check((DEMO_ROOT / _MARKER_FILE).is_file(), "演示根标记文件存在（防误用）")
    return c.report()


def _market_row(db_path: Path, type_id: int, region_id: int) -> dict:
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        row = conn.execute(
            "SELECT type_id, region_id, buy_price, sell_price, buy_volume, sell_volume FROM market_prices "
            "WHERE type_id = ? AND region_id = ?",
            (int(type_id), int(region_id)),
        ).fetchone()
    finally:
        conn.close()
    return {
        "type_id": row[0],
        "region_id": row[1],
        "buy_price": row[2],
        "sell_price": row[3],
        "buy_volume": row[4],
        "sell_volume": row[5],
    }


def _demo_product_type_id() -> int:
    """演示用「第一个可制造品」的 type_id（与 `pick_demo_items` 同一排序口径）。"""
    conn = sqlite3.connect(f"file:{(DEMO_ROOT / 'database' / 'reference.db').as_posix()}?mode=ro", uri=True)
    conn.execute(f"ATTACH DATABASE '{(DEMO_ROOT / 'database' / 'blueprint.db').as_posix()}' AS bp")
    try:
        row = conn.execute(
            """
            SELECT bp.product_type_id
              FROM bp.blueprint_products bp
              JOIN item i ON i.type_id = bp.product_type_id
             WHERE bp.activity = 'manufacturing'
               AND i.market_group_id IS NOT NULL
               AND COALESCE(i.zh_name, '') <> ''
               AND bp.product_type_id > 0
             GROUP BY bp.product_type_id
             ORDER BY bp.product_type_id
             LIMIT 1
            """
        ).fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


def _first_market_group(type_id: int) -> list[int]:
    """某个演示物品所属的市场分类 id（「按分类筛选」要能筛出至少一行）。"""
    conn = sqlite3.connect(f"file:{(DEMO_ROOT / 'database' / 'reference.db').as_posix()}?mode=ro", uri=True)
    try:
        row = conn.execute(
            "SELECT market_group_id FROM item WHERE type_id = ? AND market_group_id IS NOT NULL",
            (int(type_id),),
        ).fetchone()
        return [int(row[0])] if row else []
    finally:
        conn.close()


def _estimate_clipboard_types() -> list[int]:
    """估价页剪贴板演示条目对应的 type_id（价格/体积/精炼都得有数）。"""
    return [type_id for type_id, _qty in ESTIMATE_ITEMS]


def _item_volume(type_id: int) -> float:
    conn = sqlite3.connect(f"file:{(DEMO_ROOT / 'database' / 'reference.db').as_posix()}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT COALESCE(volume, 0) FROM item WHERE type_id = ?", (int(type_id),)).fetchone()
        return float(row[0] or 0.0)
    finally:
        conn.close()


def _first_refinable_ore() -> int:
    conn = sqlite3.connect(f"file:{(DEMO_ROOT / 'database' / 'reference.db').as_posix()}?mode=ro", uri=True)
    try:
        row = conn.execute(
            "SELECT i.type_id FROM item i WHERE i.category_id = 25 "
            "AND EXISTS (SELECT 1 FROM reprocessing_materials rm WHERE rm.type_id = i.type_id) "
            "AND COALESCE(i.en_group_name, '') <> '' ORDER BY i.type_id LIMIT 1"
        ).fetchone()
        return int(row[0])
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════
#  11. 逐页截图（可选；README 配图用）
# ════════════════════════════════════════════════════════════════

#: 估价页演示剪贴板条目：`(type_id, 数量)`。名称从演示 reference.db 现查（就是 SDE 中文名）。
ESTIMATE_ITEMS: tuple[tuple[int, int], ...] = ((34, 120_000), (35, 48_000), (36, 12_500), (38, 3_200), (39, 900))


def estimate_item_name(type_id: int) -> str:
    """演示物品的中文名（查演示 reference.db；查不到退回 `演示矿物 #id`）。"""
    conn = sqlite3.connect(f"file:{(DEMO_ROOT / 'database' / 'reference.db').as_posix()}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT zh_name, en_name FROM item WHERE type_id = ?", (int(type_id),)).fetchone()
    finally:
        conn.close()
    if not row:
        return f"演示矿物 #{type_id}"
    return str(row[0] or row[1] or f"演示矿物 #{type_id}")


def build_estimate_clipboard_text() -> str:
    """游戏「物品」窗口 Ctrl+A/C 的制表符格式：名称 / 数量 / 分组 / 体积 / 估价。"""
    return "\n".join(f"{estimate_item_name(type_id)}\t{qty}\t演示分组\t0 m³\t0 ISK" for type_id, qty in ESTIMATE_ITEMS)


def _patch_shell_for_demo() -> None:
    """掐掉外壳里三条会联网/弹窗的路径（截图与 `--shell` 共用）。

    为什么必须这么做：真实 `Main.py` 启动时 `StartupCheckWorker` 会在
    `icons` 这一项判 False（该步骤要求图标缓存覆盖全集 80%，而全量缓存 67 MB，
    本任务明确禁止整目录复制）→ `Main` 会先弹**联网初始化向导**。
    本脚本的 `--shell` / `--shots` 直接构造 `ShellWindow`，绕开那条启动链，
    并把「自动联网」的入口换成空操作：

    - `_init_price_check`：ESI 价格检查；
    - `_check_first_run`：会在状态栏写「⚠ N 项未初始化」（演示根里 icons 必然未满）；
    - `_maybe_daily_backup`：会往 user.db 的 backups/ 写盘；
    - `ContractBridge._start_backfill`：合同页会发起几万次 ESI 请求。
    """
    from ui_qml.bridge.contract_bridge import ContractBridge
    from ui_qml.shell_window import ShellWindow

    ShellWindow._init_price_check = lambda self: None  # type: ignore[method-assign]
    ShellWindow._check_first_run = lambda self: None  # type: ignore[method-assign]
    ShellWindow._maybe_daily_backup = lambda self: None  # type: ignore[method-assign]
    ContractBridge._start_backfill = lambda self, rows: None  # type: ignore[method-assign]

    from ui_qml import shell_window as shell_mod

    geometry = str(Path(tempfile.gettempdir()) / "eve-demo-window_geometry.json")
    shell_mod.window_geometry_file = lambda: geometry  # type: ignore[assignment]


def run_shell(size: str) -> int:
    """用演示根**交互式**起一次外壳（README 配图时人工操作 / 人工核对用）。

    日志里的「QML 外壳已装载 N/7 个页面」是硬指标：少一个就说明对应页面的数据没造全。
    """
    from PySide6.QtWidgets import QApplication

    from ui_qml import shell_window as shell_mod
    from ui_qml.shell_window import ShellWindow

    _patch_shell_for_demo()
    width, _, height = size.partition("x")
    app = QApplication.instance() or QApplication([])
    win = ShellWindow()
    win.resize(int(width), int(height))
    win.show()
    pages = [key for key, *_ in shell_mod.NAV_TREE]
    loaded = sorted(win._pages)
    print(f"[外壳] 已装载 {len(loaded)}/{len(pages)} 个页面：{loaded}")
    if len(loaded) != len(pages):
        missing = [key for key in pages if key not in win._pages]
        print(f"[外壳] 缺页：{missing}（对应表/列没造全，先修数据）")
    return app.exec()


def run_shots(out_dir: Path, size: str, real: bool) -> int:
    """把那 7 个页面各拍一张（离屏 / 真窗口）。

    走 `ShellWindow` 本体；会联网/弹窗的入口由 `_patch_shell_for_demo()` 掐掉，
    本页不隔离、不复制真实数据 —— 应用根目录已经是演示根。
    """
    if not real:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication

    from ui_qml import shell_window as shell_mod
    from ui_qml.shell_window import ShellWindow

    _patch_shell_for_demo()

    def spin(ms: int) -> None:
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    width, _, height = size.partition("x")
    app = QApplication.instance() or QApplication([])
    win = ShellWindow()
    win.resize(int(width), int(height))
    win.show()
    spin(1200)

    # `shell_window._register_pages()` 在**页面构造抛异常**时会静默跳过该页
    # （`log.warning("页面 %s 未迁移到 QML 或加载失败，本页暂缺")`）—— 缺页的截图等于没验到，
    # 所以这里把「装载了几个页面」当成硬验收：必须 7/7。
    pages = [key for key, *_ in shell_mod.NAV_TREE]
    loaded = sorted(win._pages)
    if len(loaded) != len(pages):
        missing = [key for key in pages if key not in win._pages]
        print(f"[截图] 外壳只装载了 {len(loaded)}/{len(pages)} 个页面，缺：{missing}")
        print("[截图] 缺页说明对应页面构造抛异常（多为表/列没造全），先补数据再截图")
        win.close()
        return 2
    print(f"[截图] QML 外壳已装载 {len(loaded)}/{len(pages)} 个页面：{loaded}")

    out_dir.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []

    def shoot(name: str) -> None:
        spin(900)
        image = win.grabWindow()
        path = out_dir / f"{name}.png"
        if image is not None and not image.isNull() and image.save(str(path)):
            saved.append(name)
            print(f"[截图] {name:9s} → {path}")
        else:
            print(f"[截图] {name:9s} 失败（抓到的图是空的）")

    pages = [key for key, *_ in shell_mod.NAV_TREE]
    for key in pages:
        if key == "query":
            # ① 空闲态：资产折线 + 挂单列表；
            # ② 详情态（可制造品）：五中心价 + 制造材料（走真实 BOM）；
            # ③ 详情态（矿石）：五中心价 + 精炼产物 —— 没有一个物品能同时喂满
            #    「制造材料」与「精炼产物」两块面板，所以两个都拍。
            win.navigate_to("query")
            shoot("query-idle")
            bridge = getattr(win._pages["query"], "hooks", None)
            for term, shot_name in (
                (estimate_item_name(_demo_product_type_id()), "query"),
                (estimate_item_name(_first_refinable_ore()), "query-ore"),
            ):
                if bridge is None:
                    break
                bridge.onTextChanged(term)
                for _ in range(60):
                    if bridge.suggestions:
                        break
                    spin(100)
                if bridge.suggestions:
                    bridge.pickSuggestion(bridge.suggestions[0]["text"])
                shoot(shot_name)
            continue
        if key == "estimate":
            win.navigate_to("estimate")
            hooks = getattr(win._pages["estimate"], "hooks", None)
            if hooks is not None:
                clipboard = QApplication.clipboard()
                if clipboard is not None:
                    clipboard.setText(build_estimate_clipboard_text())
                hooks.paste()
                # 剪贴板解析跑在 QThread 上：空转事件循环等它回来
                for _ in range(60):
                    if hooks.model.rowCount() > 0:
                        break
                    spin(100)
            shoot("estimate")
            continue
        if key == "trade":
            win.navigate_to("trade")
            hooks = getattr(win._pages["trade"], "hooks", None)
            if hooks is not None:
                hooks.analyze()
                for _ in range(120):
                    if getattr(hooks, "_rows", None):
                        break
                    spin(100)
            shoot("trade")
            continue
        if key == "watchlist":
            # 监控页有两个页签：大盘（默认）与关注物品。两边都要有图 —— 大盘页才是
            # 指数卡/折线/异动榜所在，关注页才是阈值列表所在。
            win.navigate_to("watchlist")
            shoot("watchlist")
            item = getattr(win._pages["watchlist"], "item", None)
            if item is not None:
                try:
                    item.setProperty("tabIndex", 1)
                    spin(800)
                    hooks = getattr(win._pages["watchlist"], "hooks", None)
                    if hooks is not None and hasattr(hooks, "selectRow"):
                        hooks.selectRow(0)
                    shoot("watchlist-watch")
                except Exception as exc:  # 截图是辅助手段：切页签失败不该让整轮失败
                    print(f"[截图] watchlist 关注页签切换失败：{exc}")
            continue
        if key == "contract":
            from ui_qml.bridge.contract_bridge import _TAB_KEYS

            win.navigate_to("contract")
            hooks = getattr(win._pages["contract"], "hooks", None)
            for index, tab_key in enumerate(_TAB_KEYS):
                if hooks is not None:
                    try:
                        hooks.setTabIndex(index)
                    except Exception as exc:
                        print(f"[截图] contract 切到 {tab_key} 失败：{exc}")
                shoot(f"contract-{tab_key}")
            continue
        if not win.navigate_to(key):
            print(f"[截图] {key} 未装载，跳过")
            continue
        shoot(key)

    print(f"[截图] 共 {len(saved)} 张 → {out_dir}")
    win.close()
    del app
    return 0 if saved else 1


# ════════════════════════════════════════════════════════════════
#  12. main
# ════════════════════════════════════════════════════════════════


def _guard_demo_root() -> None:
    """拒绝把演示数据写进真实仓库 / 真实 database / 真实 data 目录。"""
    root_str = str(DEMO_ROOT)
    if DEMO_ROOT == SOURCE_ROOT or SOURCE_ROOT in DEMO_ROOT.parents:
        raise SystemExit(f"[中止] 演示根不能落在项目仓库内：{root_str}")
    if DEMO_ROOT == SOURCE_DB_DIR or SOURCE_DB_DIR in DEMO_ROOT.parents:
        raise SystemExit(f"[中止] 演示根不能落在真实 database/ 内：{root_str}")
    if DEMO_ROOT == SOURCE_DATA_DIR or SOURCE_DATA_DIR in DEMO_ROOT.parents:
        raise SystemExit(f"[中止] 演示根不能落在真实 data/ 内：{root_str}")
    for name in ("reference.db", "blueprint.db", "user.db", "market.db"):
        if not (SOURCE_DB_DIR / name).exists():
            raise SystemExit(f"[中止] 缺少公共 schema 来源库：{SOURCE_DB_DIR / name}")

    # 应用侧派生路径也必须落在演示根里 —— 外壳/服务会写 settings.json、
    # mfg_browser_settings.json 这类运行时文件；一旦 `EVE_ASSISTANT_APP_ROOT`
    # 没生效（或晚于 `import core.paths` 设置），它们会写进**真实仓库**的 data/，
    # 把那台机器的角色名/筛选条件带进工作区（公开仓库里就是泄露）。
    # 这里做一次硬断言，宁可当场中止也不要写出真实账号数据。
    from core.paths import app_root, data_dir, icon_cache_dir

    for label, got, want in (
        ("app_root", Path(app_root()), DEMO_ROOT),
        ("data_dir", Path(data_dir()), DEMO_ROOT / "data"),
        ("icon_cache_dir", Path(icon_cache_dir()), DEMO_ROOT / "data" / "caches" / "icons"),
    ):
        if got.resolve() != want.resolve():
            raise SystemExit(f"[中止] 应用侧 {label} 指向 {got}，不是演示根 {want}；拒绝继续写盘")


def main() -> int:
    parser = argparse.ArgumentParser(description="构建完全合成的演示数据集（公开 README 截图用，零账号数据）")
    parser.add_argument("--root", default=str(DEMO_ROOT), help="演示根目录（默认 %%TEMP%%/eve-demo-root）")
    parser.add_argument("--source-root", default=str(SOURCE_ROOT), help="公共 schema/SDE 来源（默认本仓库）")
    parser.add_argument("--anchor-date", default="", help="数据锚定日期 YYYY-MM-DD（默认今天）；用于复现同一份数据")
    parser.add_argument("--check-only", action="store_true", help="只跑自检，不重建数据")
    parser.add_argument("--shots", action="store_true", help="建完后逐页截图（README 配图）")
    parser.add_argument("--shell", action="store_true", help="用演示根交互式起一次外壳（含 7/7 页面计数）")
    parser.add_argument("--shots-dir", default="", help="截图输出目录（默认 <演示根>/shots）")
    parser.add_argument("--shots-real", action="store_true", help="用真窗口截图（默认离屏）")
    parser.add_argument("--size", default="1600x1000", help="截图窗口尺寸 WxH")
    args = parser.parse_args()

    if Path(args.root).resolve() != DEMO_ROOT:
        raise SystemExit("[中止] --root 必须与预解析结果一致（脚本在 import 前就要定根目录）")

    _guard_demo_root()
    anchor = date.fromisoformat(args.anchor_date) if args.anchor_date else date.today()
    rng = random.Random(SEED + anchor.toordinal())

    global _ATTACHED_REF
    market: dict = {}
    stats_meta: dict = {}

    if not args.check_only:
        print(f"[演示] 演示根 {DEMO_ROOT}")
        print(f"[演示] 来源   {SOURCE_ROOT}（只用它的公共 SDE 派生库与 sqlite_master DDL）")
        (DEMO_ROOT / "database").mkdir(parents=True, exist_ok=True)
        (DEMO_ROOT / "data" / "caches" / "icons").mkdir(parents=True, exist_ok=True)
        (DEMO_ROOT / _MARKER_FILE).write_text(
            "本目录由 scripts/build_demo_data.py 生成：全部为合成演示数据，"
            "人物/机库/军团名均为虚构，与任何真实 EVE 账号无关。\n",
            encoding="utf-8",
        )

        # ① 公共 SDE 派生库：整文件复制（不含用户数据）
        for name in ("reference.db", "blueprint.db"):
            shutil.copy2(SOURCE_DB_DIR / name, DEMO_ROOT / "database" / name)
        _set_user_version(DEMO_ROOT / "database" / "reference.db", _expected_version("ref"))
        _set_user_version(DEMO_ROOT / "database" / "blueprint.db", _expected_version("bp"))
        print("[演示] 已复制公共 SDE 派生库 reference.db / blueprint.db")

        # ② 旧 items.db：只建表，不写数据
        tables = build_items_db()
        print(f"[演示] items.db 已建 {tables} 张表（无数据行）")

        conn_ref = _connect_demo_ref()
        try:
            _ATTACHED_REF = conn_ref
            items = pick_demo_items(conn_ref)
            print(
                f"[演示] 选取：可制造品 {len(items['products'])} / 反应产物 {len(items['reactions'])} / "
                f"材料 {len(items['materials'])} / 指数篮子样本 {len(items['index_sample'])} / 矿石 {len(items['ores'])}"
            )
            prices = DemoPrices(conn_ref, items, rng)
            market = build_market_db(conn_ref, items, prices, rng, anchor)
            print(
                f"[演示] market.db 完成（离群价 type={market['outlier_type']}，厚盘对照 type={market['thick_type']}）"
            )
            user_stats = build_user_db(conn_ref, items, prices, market, rng, anchor)
            print(f"[演示] user.db 完成：{user_stats}")
        finally:
            conn_ref.close()

        stats_meta = build_data_dir(anchor, market)
        icon_ids = sorted(
            {int(market["outlier_type"]), int(market["thick_type"])}
            | set(MINERAL_TYPES)
            | {int(t) for t in market["history_types"]}
        )
        copied = copy_icons(icon_ids)
        print(f"[演示] 图标复制 {copied} 个（只复制用到的，不整目录拷）")

    if args.check_only:
        market = _recover_market_meta()
    rc = run_self_check(market, stats_meta)
    print(f"[红线] 对真实 user.db 执行的数据行查询：{_SOURCE_USER_ROWS_READ} 次（只查过 sqlite_master 拿 DDL）")

    if args.shots:
        shots_dir = Path(args.shots_dir) if args.shots_dir else DEMO_ROOT / "shots"
        rc |= run_shots(shots_dir, args.size, args.shots_real)

    if args.shell:
        rc |= run_shell(args.size)

    return rc


def _recover_market_meta() -> dict:
    """`--check-only` 时从演示库里把「离群/厚盘 type」找回来（不重跑生成）。

    判据用生成时那三个盘口量常量（`OUTLIER_SELL_VOLUME` / `OUTLIER_BUY_VOLUME` /
    `THICK_SELL_VOLUME`）—— 不能用「卖量最大/最小」这类相对判据：随机生成的正常
    挂单量最大可以到 9 万，会把对照行认错。
    """
    conn = sqlite3.connect(f"file:{(DEMO_ROOT / 'database' / 'market.db').as_posix()}?mode=ro", uri=True)
    try:
        outlier = conn.execute(
            "SELECT type_id FROM market_prices WHERE region_id = 10000002 "
            "AND sell_volume = ? AND buy_volume = ? ORDER BY type_id LIMIT 1",
            (OUTLIER_SELL_VOLUME, OUTLIER_BUY_VOLUME),
        ).fetchone()
        thick = conn.execute(
            "SELECT type_id FROM market_prices WHERE region_id = 10000002 AND sell_volume = ? ORDER BY type_id LIMIT 1",
            (THICK_SELL_VOLUME,),
        ).fetchone()
    finally:
        conn.close()
    return {"outlier_type": int(outlier[0]) if outlier else 0, "thick_type": int(thick[0]) if thick else 0}


if __name__ == "__main__":
    sys.exit(main())
