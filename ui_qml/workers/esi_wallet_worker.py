"""ESI 钱包余额 + 未结挂单：一次拉**全部已绑定角色**。

继承 `esi_skill_worker.EsiSkillImportWorker`，**只重写 `_import()`** —— 令牌获取 /
静默刷新 / 过期与撤销处理全部复用基类。为什么不把那段抽成模块级函数：基类的
`_browser_authorize` / `_refresh` 被 `tests/test_qml_char_settings.py` 按**类属性**
打桩，抽出去会让那些桩失效（测试会真去开浏览器）。

**为什么这条路径不做「订单变动」推断**：ESI 给的钱包余额是**绝对值**、挂单是
「该角色当前未结」的**完整集**（官方 OpenAPI spec 里该接口没有 `page` 参数，
一次调用即全量）。所以落库是**快照替换**：钱包绝对覆盖、订单按
`(char_id, is_corp)` 组整体替换。接 `adjust_wallet_balance` 那种差额逻辑会把钱算两遍。

载荷（`result_signal`）：

- `orders`：字段与 `query_dashboard_bridge._normalize_order` 同口径，桥直接收。
- `wallet_total`：**全部角色（含军团钱包，若开启）都成功才有值**，否则 `None` ——
  合计少算了某一块会把余额写小，比不写更糟，所以由桥据此决定要不要覆盖。
- `corp_total` / `include_corp`：军团钱包合计与开关状态（未开启或失败时为 `None`）。
  桥据此把「角色钱包 + 军团钱包」的构成写进状态栏 —— 看不出钱在哪正是要解决的问题。
- `groups`：本次成功同步到的归属组 `[[char_id, is_corp], ...]`，**含当前无挂单的空组**
  （桥按组整体替换，少了空组就删不掉已成交的幽灵行）。
- `errors`：单角色 / 军团钱包失败的说明。有它也不影响其余角色落库。
- `chars`：成功同步的角色数。

**军团钱包是可选口径**（开关在 `settings.json` 的 `esi_include_corp_wallet`）：
它是共享账户、不是个人净资产，读它还要角色有军团会计类角色，所以默认不拉。
"""

from __future__ import annotations

from core.logger import log
from services.user_settings import get_include_corp_wallet
from ui_qml.workers.esi_skill_worker import (
    ESI_BASE,
    EsiAuthRevoked,
    EsiScopeMissing,
    EsiSkillImportWorker,
    _get_json,
    _Interrupted,
    list_token_rows,
)

#: 两条接口要的 scope 不同，403 文案得分开说 —— 写死一处会把用户引去勾错的权限
_WALLET_SCOPE_HINT = "钱包"
_ORDERS_SCOPE_HINT = "挂单"


def _map_order(raw: dict, char_id: int) -> dict:
    """ESI 订单 → `open_orders` 记录口径。

    ⚠️ ESI 给的是 ``is_buy_order``（不是 ``is_buy``），值是**真 bool** ——
    直接透传的话 `_as_buy` 认不出来，**所有挂单都会变成卖单**。
    """
    return {
        "order_id": int(raw.get("order_id") or 0),
        "is_buy": 1 if raw.get("is_buy_order") else 0,
        "price": float(raw.get("price") or 0.0),
        "volume_total": int(raw.get("volume_total") or 0),
        "volume_remain": int(raw.get("volume_remain") or 0),
        "location_id": int(raw.get("location_id") or 0),
        "location_name": "",
        "type_id": int(raw.get("type_id") or 0),
        "type_name": "",
        "issued": str(raw.get("issued") or ""),
        "duration": int(raw.get("duration") or 0),
        "char_id": int(char_id),
        "is_corp": 1 if raw.get("is_corporation") else 0,
    }


class EsiWalletOrdersWorker(EsiSkillImportWorker):
    """一次性线程：逐角色拉钱包余额与未结挂单。

    构造只传 `parent`（不传 `character_name`）—— 角色列表由 `esi_tokens` 决定。
    """

    async def _import(self) -> dict:
        from services.client import APIClient

        rows = list_token_rows()
        if not rows:
            raise RuntimeError("还没有绑定任何角色 —— 请先在人物设置里「从 ESI 添加角色」")

        #: 军团钱包是可选口径（共享账户 + 需要军团会计角色），默认不拉
        include_corp = get_include_corp_wallet()
        corp_seen: set[int] = set()  # 多角色同军团只算一次，否则重复计入
        corp_total = 0.0

        orders: list[dict] = []
        groups: list[list[int]] = []
        errors: list[str] = []
        wallet_total = 0.0
        ok_chars = 0

        async with APIClient(timeout=30) as client:
            for row in rows:
                name = str(row.get("character_name") or "")
                try:
                    # allow_browser=False：批量同步里一个角色掉线，不该让用户连着走
                    # 三次浏览器授权（每次最长等 10 分钟），报出来让他单独去重授权。
                    access, char_id, _char_name = await self._obtain_token(client, name, allow_browser=False)
                    if self.isInterruptionRequested():
                        raise _Interrupted()
                    wallet, char_orders = await self._pull_one(client, access, int(char_id))
                except _Interrupted:
                    raise
                except (EsiAuthRevoked, EsiScopeMissing) as e:
                    errors.append(f"{name}：{e}")
                    continue
                except Exception as e:
                    # 吞的是「这一个角色拉取失败」（网络超时、单条接口 5xx 等）：
                    # 其余角色的挂单照常落库，失败的写进 errors 由 UI 原样展示。
                    log.exception("ESI 同步角色失败 name=%s", name)
                    errors.append(f"{name}：{e}")
                    continue

                ok_chars += 1
                wallet_total += wallet
                orders.extend(_map_order(o, int(char_id)) for o in char_orders)
                # 个人单 / 军团单各算一组，都要声明「本次已覆盖」——
                # 空组也要，否则桥按组替换时删不掉已经成交掉的旧行。
                groups.extend(([int(char_id), 0], [int(char_id), 1]))

                if not include_corp:
                    continue
                # 军团钱包单独兜异常：拉不到只影响钱包合计（整块跳过），
                # **已经拿到的挂单照常落库** —— 不该因为读不到钱就把挂单也丢了。
                try:
                    corp_id = await self._character_corp(client, access, int(char_id))
                    if corp_id not in corp_seen:
                        corp_total += await self._pull_corp_wallet(client, access, corp_id)
                        corp_seen.add(corp_id)
                except EsiScopeMissing:
                    # 403 有两种可能：token 里没这个 scope（要重新授权一次），或角色没有
                    # 军团会计权限。ESI 不区分这两种，所以提示里都得说 —— 只报「缺权限」
                    # 会让没会计角色的人反复重新授权却永远失败。
                    errors.append(
                        f"{name} 的军团钱包：读不到（缺授权，或该角色没有军团会计权限）——"
                        f"先在人物设置里点「+ 从 ESI」重新授权一次；仍失败就是角色权限不够"
                    )
                except EsiAuthRevoked as e:
                    errors.append(f"{name} 的军团钱包：{e}")
                except Exception as e:
                    log.exception("ESI 军团钱包拉取失败 name=%s", name)
                    errors.append(f"{name} 的军团钱包：{e}")

        if not ok_chars:
            raise RuntimeError("；".join(errors) or "没有可同步的角色")

        return {
            "orders": orders,
            # 任一角色/军团失败 → 整块 None：合计缺人要写小，比不写更糟
            "wallet_total": wallet_total + corp_total if not errors else None,
            "corp_total": corp_total if (include_corp and not errors) else None,
            "include_corp": include_corp,
            "groups": groups,
            "chars": ok_chars,
            "errors": errors,
        }

    async def _character_corp(self, client, access: str, char_id: int) -> int:
        """角色所属军团 id。`/characters/{id}/` 是**公开**接口，不需要任何 scope。"""
        detail = await _get_json(client, f"{ESI_BASE}/characters/{char_id}/", access)
        return int((detail or {}).get("corporation_id") or 0)

    async def _pull_corp_wallet(self, client, access: str, corp_id: int) -> float:
        """军团钱包合计（各分部余额相加）。

        只有军团会计类角色读得到；没有该角色、或 token 里没这个 scope，都会 403。
        由调用方转成「军团钱包未纳入」，不当作整体失败之外的额外惩罚。
        """
        if not corp_id:
            return 0.0
        rows = await _get_json(
            client,
            f"{ESI_BASE}/corporations/{corp_id}/wallets/",
            access,
            scope_hint="军团钱包",
        )
        return float(sum(float(d.get("balance") or 0.0) for d in rows or []))

    async def _pull_one(self, client, access: str, char_id: int) -> tuple[float, list]:
        """一个角色的 (钱包余额, 未结挂单)。"""
        wallet = await _get_json(
            client,
            f"{ESI_BASE}/characters/{char_id}/wallet/",
            access,
            scope_hint=_WALLET_SCOPE_HINT,
        )
        orders = await _get_json(
            client,
            f"{ESI_BASE}/characters/{char_id}/orders/",
            access,
            scope_hint=_ORDERS_SCOPE_HINT,
        )
        return float(wallet or 0.0), list(orders or [])
