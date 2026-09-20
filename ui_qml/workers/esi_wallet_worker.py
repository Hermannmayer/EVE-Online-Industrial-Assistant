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
- `wallet_total`：**全部角色都成功才有值**，否则 `None` —— 合计少算了某个角色会把
  余额写小，比不写更糟，所以由桥据此决定要不要覆盖。
- `groups`：本次成功同步到的归属组 `[[char_id, is_corp], ...]`，**含当前无挂单的空组**
  （桥按组整体替换，少了空组就删不掉已成交的幽灵行）。
- `errors`：单角色失败的说明。有它也不影响其余角色落库。
- `chars`：成功同步的角色数。
"""

from __future__ import annotations

from core.logger import log
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

        if not ok_chars:
            raise RuntimeError("；".join(errors) or "没有可同步的角色")

        return {
            "orders": orders,
            "wallet_total": wallet_total if not errors else None,
            "groups": groups,
            "chars": ok_chars,
            "errors": errors,
        }

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
