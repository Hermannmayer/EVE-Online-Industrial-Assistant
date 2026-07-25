"""
评分服务 — 单数据源：ScoringCache, 定价查询, 评分逻辑

包含:
  - ScoringCache：线程安全、有界 TTL 缓存
  - 模块级便利函数：get_price / get_volume / get_system_cost_index / calc_*_score
  - ScoringService：可注入的评分服务类（同接口 + calc_reaction_score）
"""

import threading
import time
from collections import OrderedDict

from core.eve_formulas import (
    _hub_region_id,
    calc_broker_rate,
    calc_relist_discount,
    calc_sales_tax_rate,
)
from services.database_manager import DatabaseManager, get_db
from services.blueprint_reader import get_blueprint_materials
from services.manufacturing_calculator import (
    calc_job_cost_fees,
    calc_material_for_runs,
    calc_material_per_run,
    calc_production_time,
    SCC_SURCHARGE,
    STRUCTURE_MAT_SAVING,
)
from services.name_resolver import resolve_item_name

db = get_db()


# ════════════════════════════════════════════════════════════════════
#  评分结果缓存 — 30 分钟 TTL，有界 LRU 淘汰（线程安全）
# ════════════════════════════════════════════════════════════════════


class ScoringCache:
    """线程安全的有界评分缓存，过期被动清理 + LRU 淘汰"""

    def __init__(self, max_size: int = 500, ttl: int = 1800):
        self._cache: OrderedDict[str, tuple[float, dict]] = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl
        self._lock = threading.Lock()

    def get(self, key: str) -> dict | None:
        with self._lock:
            self._evict_expired_locked()
            entry = self._cache.get(key)
            if entry is None:
                return None
            timestamp, result = entry
            if time.time() - timestamp >= self._ttl:
                del self._cache[key]
                return None
            self._cache.move_to_end(key)
            return result

    def set(self, key: str, result: dict):
        with self._lock:
            self._evict_expired_locked()
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = (time.time(), result)
            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

    def invalidate(self):
        with self._lock:
            self._cache.clear()

    def _evict_expired_locked(self):
        cutoff = time.time() - self._ttl
        expired = [k for k, (ts, _) in self._cache.items() if ts < cutoff]
        for k in expired:
            del self._cache[k]

    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)


def cache_key(type_id: int, mode: str, hub: str, char_name: str) -> str:
    return f"{type_id}|{mode}|{hub}|{char_name}"


# 模块级缓存函数（委托给默认实例）
_default_cache = ScoringCache()


def get_cache(key: str) -> dict | None:
    return _default_cache.get(key)


def set_cache(key: str, result: dict):
    _default_cache.set(key, result)


def invalidate_cache():
    _default_cache.invalidate()


# 模块级单例 ScoringService（供模块级便利函数复用，避免每次创建新实例）
_scoring_service_instance: ScoringService | None = None


def _get_scoring_service() -> ScoringService:
    global _scoring_service_instance
    if _scoring_service_instance is None:
        _scoring_service_instance = ScoringService(db, _default_cache)
    return _scoring_service_instance


# ════════════════════════════════════════════════════════════════════
#  角色配置统一解析
# ════════════════════════════════════════════════════════════════════

DEFAULT_SKILLS = {"工业理论": 5, "高级工业理论": 5}


def resolve_char_config(
    char_name: str | None = None,
    char_data: dict | None = None,
    skills: dict | None = None,
) -> dict:
    """
    统一解析角色配置，返回 ScoringService 可用的 char_config dict。

    优先级：skills > char_data > char_name → 查 char_config.json → DEFAULT_CHAR_CONFIG
    返回结果保证包含 'skills' 和 'market' 键。
    """
    if skills is not None:
        return {"skills": dict(skills), "market": {}}
    if char_data is not None and char_data:  # 非空 dict 才直接返回
        return dict(char_data) if isinstance(char_data, dict) else {"skills": {}, "market": {}}
    if char_name is not None:
        try:
            from ui_pyside6.views.char_settings_view import get_character

            char = get_character(char_name)
            if char:
                return dict(char)
        except Exception:
            pass
        try:
            from services.char_config_validator import load_char_config
            from ui_pyside6.views.char_settings_view import char_config_path

            data = load_char_config(char_config_path())
            chars = data.get("characters", {})
            if char_name in chars:
                return dict(chars[char_name])
            # fallback: 用 current
            current = data.get("current", "main")
            if current in chars:
                return dict(chars[current])
        except Exception:
            pass
    # 最终 fallback：默认技能
    return {"skills": dict(DEFAULT_SKILLS), "market": {}}


# ════════════════════════════════════════════════════════════════════
#  定价查询（模块级 + ScoringService 实例方法共享）
# ════════════════════════════════════════════════════════════════════


def get_price(
    type_id: int,
    price_type: str,
    hub: str | None = None,
    _db: DatabaseManager | None = None,
) -> float | None:
    """
    从 market_prices 获取指定区域的价格。
    price_type: 'buy' → buy_price, 'sell' → sell_price
    hub: 贸易中心名称, 如 'Jita', 'Amarr'；None 时返回任意区域
    _db: 可选注入的 DatabaseManager；None 时使用模块级单例。
    """
    conn_mgr = _db or db
    _VALID_PRICE_COLS = {"buy": "buy_price", "sell": "sell_price"}
    col = _VALID_PRICE_COLS.get(price_type)
    if col is None:
        return None
    with conn_mgr.connect("mkt") as conn:
        c = conn.cursor()
        if hub:
            rid = _hub_region_id(hub)
            c.execute(
                f"SELECT {col} FROM market_prices WHERE type_id = ? AND region_id = ? LIMIT 1",
                (type_id, rid),
            )
            row = c.fetchone()
            if row and row[0] is not None:
                return float(row[0])
            # 降级：该区域无数据，尝试其他区域
            c.execute(
                f"SELECT {col} FROM market_prices WHERE type_id = ? AND {col} IS NOT NULL LIMIT 1",
                (type_id,),
            )
        else:
            c.execute(
                f"SELECT {col} FROM market_prices WHERE type_id = ? AND {col} IS NOT NULL LIMIT 1",
                (type_id,),
            )
        row = c.fetchone()
        return row[0] if row else None


def get_volume(
    type_id: int,
    vol_type: str = "total",
    hub: str | None = None,
    _db: DatabaseManager | None = None,
) -> int:
    """获取指定区域的成交量。vol_type: 'buy' / 'sell' / 'total'"""
    conn_mgr = _db or db
    with conn_mgr.connect("mkt") as conn:
        c = conn.cursor()
        if hub:
            rid = _hub_region_id(hub)
            c.execute(
                "SELECT buy_volume, sell_volume FROM market_prices WHERE type_id = ? AND region_id = ? LIMIT 1",
                (type_id, rid),
            )
            row = c.fetchone()
            if row and (row[0] or row[1]):
                if vol_type == "total":
                    return int(row[0] + row[1])
                return int(row[0] if vol_type == "buy" else row[1])
            # 降级：该区域无数据，尝试其他区域
            c.execute(
                "SELECT buy_volume, sell_volume FROM market_prices WHERE type_id = ? LIMIT 1",
                (type_id,),
            )
        else:
            c.execute(
                "SELECT buy_volume, sell_volume FROM market_prices WHERE type_id = ? LIMIT 1",
                (type_id,),
            )
        row = c.fetchone()
        if not row:
            return 0
        if vol_type == "buy":
            return row[0] or 0
        elif vol_type == "sell":
            return row[1] or 0
        return (row[0] or 0) + (row[1] or 0)


def get_system_cost_index(
    system_id: int | None,
    activity: str = "manufacturing",
    _db: DatabaseManager | None = None,
) -> float:
    """从数据库获取星系的制造成本指数(SCI)。默认1.0（无加成）。"""
    if system_id is None:
        return 1.0
    conn_mgr = _db or db
    with conn_mgr.connect("ref") as conn:
        c = conn.cursor()
        c.execute(
            "SELECT cost_index FROM industry_system_costs WHERE solar_system_id = ? AND activity = ? LIMIT 1",
            (system_id, activity),
        )
        row = c.fetchone()
        return row[0] if row else 1.0


# ════════════════════════════════════════════════════════════════════
#  精炼价值计算
# ════════════════════════════════════════════════════════════════════


def calc_refining_value(
    type_id: int,
    quantity: int = 1,
    *,
    skills: dict | None = None,
    is_player_facility: bool = False,
    price_hub: str = "Jita",
    yield_override: float | None = None,
    ore_skill: int = 0,
) -> dict:
    """计算物品的精炼产出及总价值

    Args:
        type_id: 矿石/冰矿/残骸 type_id
        quantity: 数量
        skills: 角色技能字典
        is_player_facility: 是否玩家设施
        price_hub: 贸易中心
        yield_override: 指定产率（覆盖计算）
        ore_skill: 矿石专精技能等级

    Returns:
        {
            "yield_rate": float,        # 精炼产率 0~1
            "output": [                  # 产出物列表
                {"type_id": id, "name": str, "qty": float, "price": float, "total": float}
            ],
            "total_value": float,        # 产物总价值
            "input_value": float,        # 原材料市场价
            "profit": float,             # 精炼后增值（可为负）
            "margin_pct": float,         # 利润率 %
        }
    """
    from core.eve_formulas import calc_refining_yield, resolve_item_name

    yield_rate = (
        yield_override
        if yield_override is not None
        else calc_refining_yield(
            skills,
            is_player_facility=is_player_facility,
        )
    )
    # 加入矿石专精
    yield_rate += ore_skill * 0.02
    yield_rate = min(yield_rate, 0.85)

    # 从数据库查询 reprocessing_materials
    with db.connect("ref") as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT material_type_id, quantity FROM type_materials WHERE type_id = ?",
            (type_id,),
        )
        materials = cur.fetchall()

    if not materials:
        return {"yield_rate": yield_rate, "output": [], "total_value": 0, "input_value": 0, "profit": 0, "margin_pct": 0}

    output = []
    total_value = 0.0
    with db.connect("ref") as rconn:
        cur = rconn.cursor()
        for mat_id, mat_qty in materials:
            qty = mat_qty * yield_rate * quantity
            price = get_price(mat_id, "sell", price_hub) or 0.0
            total = round(qty * price, 2)
            name = resolve_item_name(cur, mat_id)
            output.append({
                "type_id": mat_id,
                "name": name,
                "qty": round(qty, 2),
                "price": price,
                "total": total,
            })
            total_value += total

    input_price = get_price(type_id, "sell", price_hub) or 0.0
    input_value = input_price * quantity
    profit = total_value - input_value
    margin_pct = (profit / input_value * 100) if input_value > 0 else 0.0

    return {
        "yield_rate": round(yield_rate, 4),
        "output": output,
        "total_value": round(total_value, 2),
        "input_value": round(input_value, 2),
        "profit": round(profit, 2),
        "margin_pct": round(margin_pct, 2),
    }


# ════════════════════════════════════════════════════════════════════
#  ScoringService — 可注入的评分服务类
# ════════════════════════════════════════════════════════════════════


class ScoringService:
    def __init__(self, db: DatabaseManager, cache: ScoringCache, char_config: dict | None = None):
        self._db = db
        self._cache = cache
        self._char_config = char_config or {}

    # ── 经纪人费率计算（去重：制造/贸易共用） ──

    def _calc_broker_rate(self, skills: dict, market_data: dict) -> float:
        return calc_broker_rate(skills, market_data)

    def _calc_relist_discount(self, skills: dict) -> float:
        return calc_relist_discount(skills)

    def _calc_sales_tax_rate(self, skills: dict) -> float:
        return calc_sales_tax_rate(skills)

    # ── 制造评分 ──

    def calc_manufacturing_score(
        self,
        type_id: int,
        char_config: dict,
        mat_source_hub: str = "Jita",
        sell_hub: str = "Jita",
        facility_tax_pct: float = 0.0,
        price_type_mat: str = "sell",
        price_type_prod: str = "sell",
        bp_me: int = 0,
        bp_te: int = 0,
        system_id: int | None = None,
        structure_bonus: float = 0.0,
        structure_time_mod: float = 1.0,
        is_alpha: bool = False,
    ) -> dict:
        """计算制造评分。

        重构后使用 manufacturing_calculator 中的公式：
        - 材料浪费: calc_material_per_run / calc_material_for_runs
        - 安装费: calc_job_cost_fees（加法结构）
        - 时间: calc_production_time
        """
        result = {
            "score": 0.0,
            "profit_per_run": 0.0,
            "margin_pct": 0.0,
            "isk_per_hour": 0.0,
            "cost_per_unit": 0.0,
            "revenue_per_unit": 0.0,
            "hours_per_run": 0.0,
            "status": "",
            "breakdown": {},
        }

        with self._db.connect("ref", "mkt", "bp") as conn:
            c = conn.cursor()

            c.execute(
                """
                SELECT bp.blueprint_type_id, bp.quantity, ba.time
                FROM blueprint_products bp
                JOIN blueprint_activities ba ON ba.blueprint_type_id = bp.blueprint_type_id
                    AND ba.activity = bp.activity
                WHERE bp.product_type_id = ? AND bp.activity = 'manufacturing'
                LIMIT 1
            """,
                (type_id,),
            )
            bp_row = c.fetchone()
            if not bp_row:
                result["status"] = "no_blueprint"
                return result

            bp_id, prod_qty, base_time = bp_row
            prod_qty = prod_qty or 1

            prod_price = get_price(type_id, price_type_prod, sell_hub, _db=self._db)
            if not prod_price:
                result["status"] = "no_price"
                return result

            # 用 blueprint_reader 获取材料（含 wastefactor）
            mat_rows = get_blueprint_materials(c, bp_id)
            if not mat_rows:
                result["status"] = "no_materials"
                return result

            # 材料成本计算（使用正确的浪费公式 + ceil 取整）
            total_mat_cost = 0.0
            mat_detail = []
            eiv_materials: list[tuple[int, float]] = []
            for mat_id, mat_qty, wastefactor in mat_rows:
                wastefactor = wastefactor or 10  # 兜底 T1
                mat_price = get_price(mat_id, price_type_mat, mat_source_hub, _db=self._db)
                # 正确公式：ceil(base_qty × waste_factor) 每轮次
                per_run_qty = calc_material_per_run(mat_qty, wastefactor, bp_me, STRUCTURE_MAT_SAVING)
                waste_qty = per_run_qty * prod_qty  # 多轮次
                if mat_price:
                    total_mat_cost += waste_qty * mat_price
                mat_name = resolve_item_name(c, mat_id)
                # EIV 基础材料量（ME0 无浪费）
                base_qty_no_waste = mat_qty
                eiv_materials.append((base_qty_no_waste, mat_price or 0.0))
                mat_detail.append(
                    {
                        "name": mat_name,
                        "base_qty": mat_qty,
                        "qty": waste_qty,
                        "wastefactor": wastefactor,
                        "waste_factor": round(per_run_qty / mat_qty, 4) if mat_qty > 0 else 1.0,
                        "unit_price": mat_price or 0.0,
                        "subtotal": round((mat_price or 0.0) * waste_qty, 2),
                    }
                )
            result["materials"] = mat_detail

            skills = char_config.get("skills", {}) if char_config else {}
            market_data = char_config.get("market", {}).get(sell_hub.lower(), {}) if char_config else {}

            broker_rate = self._calc_broker_rate(skills, market_data)
            relist_discount = self._calc_relist_discount(skills)
            sales_tax_rate = self._calc_sales_tax_rate(skills)

            revenue = prod_price * prod_qty
            total_cost = total_mat_cost
            sci = get_system_cost_index(system_id, "manufacturing", _db=self._db)

            # EIV 计算 & 安装费（加法结构）
            eiv = sum(qty * price for qty, price in eiv_materials)
            # structure_bonus: 传入的 0.0 表示 NPC 无加成 → 乘数 1.0
            # 传入的负值表示折扣（如 -0.1 → 乘数 0.9）
            sb_mult = 1.0 + structure_bonus
            alpha_tax = 0.0025 if is_alpha else 0.0
            fee_detail = calc_job_cost_fees(
                eiv=eiv,
                sci=sci,
                structure_mult=sb_mult,
                facility_tax=facility_tax_pct / 100,
                alpha_tax=alpha_tax,
            )
            facility_fee = fee_detail["total_fee"]
            total_cost += facility_fee

            broker_init = revenue * (broker_rate / 100)
            broker_relist = revenue * (broker_rate / 100) * (1 - relist_discount / 100)
            sales_tax = revenue * (sales_tax_rate / 100)
            total_cost += broker_init + broker_relist + sales_tax

            profit = revenue - total_cost

            # 时间计算（使用 calc_production_time）
            ind_lvl = skills.get("工业理论", 5)
            adv_lvl = skills.get("高级工业理论", 5)
            actual_time = calc_production_time(
                base_time=base_time,
                industry_skill=ind_lvl,
                adv_industry_skill=adv_lvl,
                te_level=bp_te,
                structure_time_mod=structure_time_mod,
            )
            hours_per_run = actual_time / 3600
            margin_pct = profit / total_cost * 100 if total_cost > 0 else 0

            # 费用明细字典
            breakdown = {
                "bp_me": bp_me,
                "bp_te": bp_te,
                "isk_per_hour": 0.0,
                "revenue": round(revenue, 2),
                "material_cost": round(total_mat_cost, 2),
                "broker_init": round(broker_init, 2),
                "broker_relist": round(broker_relist, 2),
                "sales_tax": round(sales_tax, 2),
                "facility_fee": round(facility_fee, 2),
                "eiv": round(eiv, 2),
                "sci": round(sci, 4),
                "structure_bonus": round(structure_bonus, 4),
                "structure_time_mod": round(structure_time_mod, 4),
                "facility_tax_pct": round(facility_tax_pct, 2),
                "scc_surcharge": round(fee_detail["scc"], 2),
                "broker_rate": round(broker_rate, 3),
                "sales_tax_rate": round(sales_tax_rate, 3),
                "relist_discount": round(relist_discount, 1),
            }

            if profit <= 0:
                result.update(
                    {
                        "margin_pct": round(margin_pct, 2),
                        "profit_per_run": round(profit, 2),
                        "cost_per_unit": round(total_cost / prod_qty, 2),
                        "hours_per_run": round(hours_per_run, 2),
                        "revenue_per_unit": round(prod_price, 2),
                        "breakdown": breakdown,
                    }
                )
                return result

            volume = get_volume(type_id, "total", sell_hub, _db=self._db)
            if volume == 0:
                return result

            profit_score = min(margin_pct * 4, 40)
            volume_factor = min(volume / 5_000_000, 1.0)
            volume_score = volume_factor * 30
            isk_per_hour = profit / hours_per_run if hours_per_run > 0 else 0
            efficiency_score = min(isk_per_hour / 50_000_000 * 30, 30)
            total_score = profit_score + volume_score + efficiency_score

            breakdown.update(
                {
                    "profit_score": round(profit_score, 1),
                    "volume_score": round(volume_score, 1),
                    "efficiency_score": round(efficiency_score, 1),
                    "isk_per_hour": round(isk_per_hour, 2),
                }
            )

            result.update(
                {
                    "score": round(total_score, 1),
                    "profit_per_run": round(profit, 2),
                    "margin_pct": round(margin_pct, 2),
                    "isk_per_hour": round(isk_per_hour, 2),
                    "cost_per_unit": round(total_cost / prod_qty, 2),
                    "revenue_per_unit": round(prod_price, 2),
                    "hours_per_run": round(hours_per_run, 2),
                    "status": "",
                    "breakdown": breakdown,
                }
            )

        return result

    # ── 贸易评分 ──

    def calc_trade_score(
        self,
        type_id: int,
        buy_hub: str = "Jita",
        sell_hub: str = "Jita",
        buy_price_type: str = "buy",
        sell_price_type: str = "sell",
        char_config: dict | None = None,
        quantity: int = 1,
    ) -> dict:
        """计算贸易评分。"""
        result = {
            "score": 0.0,
            "buy_cost": 0.0,
            "sell_revenue": 0.0,
            "gross_profit": 0.0,
            "margin_pct": 0.0,
            "profit_per_m3": 0.0,
            "status": "",
        }

        buy_price = get_price(type_id, buy_price_type, buy_hub, _db=self._db)
        sell_price = get_price(type_id, sell_price_type, sell_hub, _db=self._db)
        if not buy_price or not sell_price:
            result["status"] = "no_price"
            return result

        with self._db.connect("ref") as conn:
            c = conn.cursor()
            c.execute("SELECT volume FROM item WHERE type_id = ?", (type_id,))
            row = c.fetchone()
            volume_m3 = row[0] or 1.0 if row else 1.0

        skills = char_config.get("skills", {}) if char_config else {}
        market_data_buy = char_config.get("market", {}).get(buy_hub.lower(), {}) if char_config else {}
        market_data_sell = char_config.get("market", {}).get(sell_hub.lower(), {}) if char_config else {}

        broker_rate = self._calc_broker_rate(skills, market_data_buy)
        relist_discount = self._calc_relist_discount(skills)
        sales_tax_rate = self._calc_sales_tax_rate(skills)

        buy_fee_total = broker_rate + broker_rate * (1 - relist_discount / 100)

        sell_rate = self._calc_broker_rate(skills, market_data_sell)
        sell_fee_total = sell_rate + sell_rate * (1 - relist_discount / 100) + sales_tax_rate

        buy_cost = buy_price * quantity + buy_price * quantity * (buy_fee_total / 100)
        sell_revenue = sell_price * quantity - sell_price * quantity * (sell_fee_total / 100)
        gross_profit = sell_revenue - buy_cost
        margin_pct = gross_profit / buy_cost * 100 if buy_cost > 0 else 0

        if gross_profit <= 0:
            result["margin_pct"] = round(margin_pct, 2)
            result["buy_cost"] = round(buy_cost, 2)
            result["sell_revenue"] = round(sell_revenue, 2)
            result["gross_profit"] = round(gross_profit, 2)
            return result

        volume = get_volume(type_id, "total", sell_hub, _db=self._db)
        if volume == 0:
            return result

        margin_pct = gross_profit / buy_cost * 100 if buy_cost > 0 else 0
        profit_per_m3 = gross_profit / volume_m3 if volume_m3 > 0 else gross_profit

        margin_score = min(margin_pct * 5, 50)
        volume_factor = min(volume / 5_000_000, 1.0)
        vol_score = volume_factor * 50
        total_score = margin_score + vol_score

        result.update(
            {
                "score": round(total_score, 1),
                "buy_cost": round(buy_cost, 2),
                "sell_revenue": round(sell_revenue, 2),
                "gross_profit": round(gross_profit, 2),
                "margin_pct": round(margin_pct, 2),
                "profit_per_m3": round(profit_per_m3, 2),
            }
        )

        return result

    # ── 反应评分 ──

    def calc_reaction_score(
        self,
        type_id: int,
        char_config: dict,
        mat_source_hub: str = "Jita",
        sell_hub: str = "Jita",
        facility_tax_pct: float = 0.0,
        price_type_mat: str = "sell",
        price_type_prod: str = "sell",
        system_id: int | None = None,
        structure_bonus: float = 0.0,
    ) -> dict:
        """
        计算反应（Reaction）利润评分。

        与 calc_manufacturing_score 的差异:
          - 查 activity='reaction' 的蓝图数据
          - 无 ME/TE 概念：waste_factor=1.0, 无 TE 修正
          - 时间仅受 Advanced Industry 技能影响（-3%/级）
          - 安装费使用反应专用 SCI
        """
        result = {
            "score": 0.0,
            "profit_per_run": 0.0,
            "margin_pct": 0.0,
            "isk_per_hour": 0.0,
            "cost_per_unit": 0.0,
            "revenue_per_unit": 0.0,
            "hours_per_run": 0.0,
            "status": "",
            "breakdown": {},
        }

        with self._db.connect("ref", "mkt", "bp") as conn:
            c = conn.cursor()

            # 1. 查找反应蓝图
            c.execute(
                """
                SELECT bp.blueprint_type_id, bp.quantity, ba.time
                FROM blueprint_products bp
                JOIN blueprint_activities ba ON ba.blueprint_type_id = bp.blueprint_type_id
                    AND ba.activity = bp.activity
                WHERE bp.product_type_id = ? AND bp.activity = 'reaction'
                LIMIT 1
                """,
                (type_id,),
            )
            bp_row = c.fetchone()
            if not bp_row:
                result["status"] = "no_blueprint"
                return result

            bp_id, prod_qty, base_time = bp_row
            prod_qty = prod_qty or 1

            # 2. 成品价格
            prod_price = get_price(type_id, price_type_prod, sell_hub, _db=self._db)
            if not prod_price:
                result["status"] = "no_price"
                return result

            # 3. 查反应材料
            c.execute(
                """
                SELECT bm.material_type_id, bm.quantity
                FROM blueprint_materials bm
                WHERE bm.blueprint_type_id = ? AND bm.activity = 'reaction'
                """,
                (bp_id,),
            )
            mat_rows = c.fetchall()

            if not mat_rows:
                result["status"] = "no_materials"
                return result

            # 4. 计算材料成本（反应无 ME 浪费，waste_factor=1.0）
            waste_factor = 1.0
            total_mat_cost = 0.0
            mat_detail = []
            for mat_id, mat_qty in mat_rows:
                mat_price = get_price(mat_id, price_type_mat, mat_source_hub, _db=self._db)
                waste_qty = mat_qty * waste_factor
                if mat_price:
                    total_mat_cost += waste_qty * mat_price
                mat_name = _mat_name(mat_id, c)
                mat_detail.append(
                    {
                        "name": mat_name,
                        "base_qty": mat_qty,
                        "qty": round(waste_qty, 2),
                        "waste_factor": round(waste_factor, 2),
                        "unit_price": mat_price or 0.0,
                        "subtotal": round((mat_price or 0.0) * waste_qty, 2),
                    }
                )
            result["materials"] = mat_detail

            # 5. 从人物配置读取费率
            skills = char_config.get("skills", {}) if char_config else {}
            market_data = char_config.get("market", {}).get(sell_hub.lower(), {}) if char_config else {}

            broker_rate = calc_broker_rate(skills, market_data)
            relist_discount = calc_relist_discount(skills)
            sales_tax_rate_val = calc_sales_tax_rate(skills)

            # 6. 安装费
            revenue = prod_price * prod_qty
            total_cost = total_mat_cost
            sci = get_system_cost_index(system_id, "reaction", _db=self._db)
            install_base = REACTION_INSTALL_FEE_RATE * revenue
            facility_fee = install_base * sci * (1 - structure_bonus) * (1 + facility_tax_pct / 100)
            total_cost += facility_fee
            broker_init = revenue * (broker_rate / 100)
            broker_relist = revenue * (broker_rate / 100) * (1 - relist_discount / 100)
            sales_tax = revenue * (sales_tax_rate_val / 100)
            total_cost += broker_init + broker_relist + sales_tax

            profit = revenue - total_cost
            margin_pct = profit / total_cost * 100 if total_cost > 0 else 0

            # 7. 反应时间
            adv_lvl = skills.get("高级工业理论", 5)
            skill_mod = 1 - ADV_INDUSTRY_SKILL_MULT * adv_lvl
            actual_time = base_time * skill_mod
            hours_per_run = actual_time / 3600

            # 8. 负利润时提前返回
            if profit <= 0:
                result["margin_pct"] = round(margin_pct, 2)
                result["profit_per_run"] = round(profit, 2)
                result["cost_per_unit"] = round(total_cost / prod_qty, 2)
                result["hours_per_run"] = round(hours_per_run, 2)
                result["revenue_per_unit"] = round(prod_price, 2)
                return result

            # 9. 评分
            margin_pct = profit / total_cost * 100 if total_cost > 0 else 0
            volume = get_volume(type_id, "total", sell_hub, _db=self._db)
            if volume == 0:
                return result

            profit_score = min(margin_pct * 4, 40)  # 10% = 40分
            volume_factor = min(volume / 5_000_000, 1.0)
            volume_score = volume_factor * 30  # 500万 = 30分
            isk_per_hour = profit / hours_per_run if hours_per_run > 0 else 0
            efficiency_score = min(isk_per_hour / 50_000_000 * 30, 30)  # 5000万/h = 30分

            total_score = profit_score + volume_score + efficiency_score

            result.update(
                {
                    "score": round(total_score, 1),
                    "profit_per_run": round(profit, 2),
                    "margin_pct": round(margin_pct, 2),
                    "isk_per_hour": round(isk_per_hour, 2),
                    "cost_per_unit": round(total_cost / prod_qty, 2),
                    "revenue_per_unit": round(prod_price, 2),
                    "hours_per_run": round(hours_per_run, 2),
                    "status": "",
                    "breakdown": {
                        "waste_factor": round(waste_factor, 2),
                        "profit_score": round(profit_score, 1),
                        "volume_score": round(volume_score, 1),
                        "efficiency_score": round(efficiency_score, 1),
                        "isk_per_hour": round(isk_per_hour, 2),
                        "revenue": round(revenue, 2),
                        "material_cost": round(total_mat_cost, 2),
                        "broker_init": round(broker_init, 2),
                        "broker_relist": round(broker_relist, 2),
                        "sales_tax": round(sales_tax, 2),
                        "facility_fee": round(facility_fee, 2),
                        "install_base": round(install_base, 2),
                        "sci": round(sci, 4),
                        "structure_bonus": round(structure_bonus, 4),
                        "facility_tax_pct": round(facility_tax_pct, 2),
                        "broker_rate": round(broker_rate, 3),
                        "sales_tax_rate": round(sales_tax_rate_val, 3),
                        "relist_discount": round(relist_discount, 1),
                    },
                }
            )

        return result


# ════════════════════════════════════════════════════════════════════
#  反应安装费常数（模块级导出供外部使用）
# ════════════════════════════════════════════════════════════════════

REACTION_INSTALL_FEE_RATE = 0.05


# ════════════════════════════════════════════════════════════════════
#  模块级评分便利函数（使用默认 db 单例 + 默认缓存）
#  向后兼容：保持与旧 services.scoring 相同的接口签名
# ════════════════════════════════════════════════════════════════════


def calc_manufacturing_score(
    type_id: int,
    char_config: dict,
    mat_source_hub: str = "Jita",
    sell_hub: str = "Jita",
    facility_tax_pct: float = 0.0,
    price_type_mat: str = "sell",
    price_type_prod: str = "sell",
    bp_me: int = 0,
    bp_te: int = 0,
    system_id: int | None = None,
    structure_bonus: float = 0.0,
    structure_time_mod: float = 1.0,
    is_alpha: bool = False,
) -> dict:
    """模块级便利函数：复用模块级单例 ScoringService。"""
    return _get_scoring_service().calc_manufacturing_score(
        type_id=type_id,
        char_config=char_config,
        mat_source_hub=mat_source_hub,
        sell_hub=sell_hub,
        facility_tax_pct=facility_tax_pct,
        price_type_mat=price_type_mat,
        price_type_prod=price_type_prod,
        bp_me=bp_me,
        bp_te=bp_te,
        system_id=system_id,
        structure_bonus=structure_bonus,
        structure_time_mod=structure_time_mod,
        is_alpha=is_alpha,
    )


def calc_trade_score(
    type_id: int,
    buy_hub: str = "Jita",
    sell_hub: str = "Jita",
    buy_price_type: str = "buy",
    sell_price_type: str = "sell",
    char_config: dict | None = None,
    quantity: int = 1,
) -> dict:
    """模块级便利函数：复用模块级单例 ScoringService。"""
    return _get_scoring_service().calc_trade_score(
        type_id=type_id,
        buy_hub=buy_hub,
        sell_hub=sell_hub,
        buy_price_type=buy_price_type,
        sell_price_type=sell_price_type,
        char_config=char_config,
        quantity=quantity,
    )


def calc_reaction_score(
    type_id: int,
    char_config: dict,
    mat_source_hub: str = "Jita",
    sell_hub: str = "Jita",
    facility_tax_pct: float = 0.0,
    price_type_mat: str = "sell",
    price_type_prod: str = "sell",
    system_id: int | None = None,
    structure_bonus: float = 0.0,
) -> dict:
    """模块级便利函数：复用模块级单例 ScoringService。"""
    return _get_scoring_service().calc_reaction_score(
        type_id=type_id,
        char_config=char_config,
        mat_source_hub=mat_source_hub,
        sell_hub=sell_hub,
        facility_tax_pct=facility_tax_pct,
        price_type_mat=price_type_mat,
        price_type_prod=price_type_prod,
        system_id=system_id,
        structure_bonus=structure_bonus,
    )
