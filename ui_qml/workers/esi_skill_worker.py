"""从 ESI 导入角色技能 —— OAuth PKCE + 回环回调 + 拉取。

**为什么在 `ui_qml/workers/` 而不是 `services/`**：整套流程只有一个调用方
（人物设置对话框的导入按钮），按本仓克制条款第 1 条不足以新开服务模块；而
「UI 异步 = QThread + Signal」的既定位置就是这里，且已有 worker 直连 ESI 的先例
（`ui_qml/workers/order_workers.py`）。

**安全口径**：走 PKCE 公共客户端，**不带 client_secret** —— 官方 PKCE 示例明写
「we do not use the client secret in this flow」。`CLIENT_ID` 按公共客户端设计就是
公开的，可以内置；secret 一律不落代码、不落库。

**一次授权 = 一个角色**：令牌 `sub` 是 `CHARACTER:EVE:<id>`，用户在 CCP 页面上
选角色。多账号 / 一账号多角色 = 每个角色各点一次导入。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import secrets
import time
import webbrowser
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import aiohttp
from PySide6.QtCore import QThread, Signal

from core.logger import log

#: 新建的专用 Native 应用（PKCE 公共客户端，无 secret）
CLIENT_ID = "248d379a8723486bbc2a7d6d0c1718a1"

CALLBACK_PORT = 8721

#: ⚠️ 必须是 `localhost` 字面量。EVE 门户明文规定 `http` 回调只允许 localhost，
#: 填 `127.0.0.1` 会被拒 —— 但**监听**仍然绑回环 IP（见 `_start_callback_server`）。
CALLBACK_URL = f"http://localhost:{CALLBACK_PORT}/callback"

AUTHORIZE_URL = "https://login.eveonline.com/v2/oauth/authorize"
TOKEN_URL = "https://login.eveonline.com/v2/oauth/token"
ESI_BASE = "https://esi.evetech.net/latest"

#: 只请求本功能要用的；应用上另勾的权限是给后续功能预留的，这里不请求也能用
#: （refresh 时只能传原子集的子集，传了没勾的反而会失败）。
#: ⚠️ 加 scope 后**老 token 不会刷新失败**（`_refresh` 不传 scope，拿到的是原子集），
#: 而是打新接口时 403 → 用户要重新授权一次；且**必须先在本应用的开发者门户勾选**，
#: 否则授权直接 `invalid_scope`，代码侧无解。
SCOPES = (
    "esi-skills.read_skills.v1",
    "esi-skills.read_skillqueue.v1",
    "esi-clones.read_implants.v1",
    "esi-wallet.read_character_wallet.v1",
    "esi-markets.read_character_orders.v1",
)

#: access token 官方寿命 1200s（20 分钟）。剩不足这个裕量就提前刷新。
_EXPIRY_MARGIN_S = 60
_DEFAULT_EXPIRES_IN = 1200

#: 等回调的上限。超时后用户得重新点导入（PKCE 的 verifier 与这次 state 一起作废）。
#: 给到 10 分钟：EVE 登录带邮箱验证码，收信 + 输码 + 可能的二次验证很容易超过 3 分钟；
#: 超时太短的后果不是「慢」，而是用户输完码却跳到一个已经关掉的端口。
_AUTH_TIMEOUT_S = 600

#: 单请求超时
_TIMEOUT = aiohttp.ClientTimeout(total=30)


class _Interrupted(Exception):
    """用户关掉了对话框 —— 不是错误，不要发信号。"""


class _TokenError(RuntimeError):
    """token 端点返回非 200。`code` 是 OAuth 的 error 字段（如 invalid_grant）。"""

    def __init__(self, code: str, desc: str, status: int) -> None:
        super().__init__(desc or code or f"token 端点返回 {status}")
        self.code = code


class EsiAuthRevoked(RuntimeError):
    """401：令牌失效或授权已被撤销，需要用户重新授权。"""


class EsiScopeMissing(RuntimeError):
    """403：令牌有效但缺 scope。"""


# ── 时间 ──


def _utc_now() -> str:
    """ESI 同款格式的 UTC 时间串。同格式 ISO8601 按字典序比较即等价于按时间比较。"""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _utc_after(seconds: int) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── 令牌表（user.db，v19 迁移建的）──


def _token_conn():
    """打开 esi_tokens 所在连接。

    这里再执行一次 DDL 兜底：`sqlite3.connect` 会创建空库文件，全新安装时
    user.db 可能晚于启动时的 schema 迁移才出现（`ensure_all_schemas` 对不存在的
    库直接跳过）。DDL 是 `CREATE TABLE IF NOT EXISTS`，幂等。
    """
    from core.container import get_container
    from services.schema_migrations import ESI_TOKENS_SQL

    conn = get_container().db.direct_connect("user")
    conn.executescript(ESI_TOKENS_SQL)
    return conn


#: 绑定行的列（`load_token_row` / `list_token_rows` 共用，避免两处漂移）
_TOKEN_COLUMNS = "character_id, character_name, refresh_token, access_token, access_expires_at"


def load_token_row(character_name: str) -> dict | None:
    """按角色名取绑定行（token 按角色绑定，名字是配置里的匹配键）。"""
    conn = _token_conn()
    try:
        row = conn.execute(
            f"SELECT {_TOKEN_COLUMNS} FROM esi_tokens WHERE character_name = ?",
            (character_name,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_token_rows() -> list[dict]:
    """全部已绑定角色 —— ESI 钱包/挂单同步要遍历每个角色各拉一份。"""
    conn = _token_conn()
    try:
        rows = conn.execute(f"SELECT {_TOKEN_COLUMNS} FROM esi_tokens ORDER BY character_name").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def save_token_row(
    character_id: int,
    character_name: str,
    refresh_token: str,
    access_token: str,
    access_expires_at: str,
) -> None:
    """写入/更新绑定行。

    **每次刷新后都必须原样保存响应里的 refresh_token** —— CCP 文档明说返回的
    可能和提交的不同（会启用轮换），只留第一次那个迟早失效，用户就得重新授权。
    """
    conn = _token_conn()
    try:
        conn.execute(
            "INSERT INTO esi_tokens"
            " (character_id, character_name, refresh_token, access_token, access_expires_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, datetime('now','localtime'))"
            " ON CONFLICT(character_id) DO UPDATE SET"
            "   character_name = excluded.character_name,"
            "   refresh_token = excluded.refresh_token,"
            "   access_token = excluded.access_token,"
            "   access_expires_at = excluded.access_expires_at,"
            "   updated_at = excluded.updated_at",
            (character_id, character_name, refresh_token, access_token, access_expires_at),
        )
        conn.commit()
    finally:
        conn.close()


def delete_token_row(character_id: int) -> None:
    """授权被撤销时清掉这一行（留着只会每次刷新都失败）。"""
    conn = _token_conn()
    try:
        conn.execute("DELETE FROM esi_tokens WHERE character_id = ?", (character_id,))
        conn.commit()
    finally:
        conn.close()


# ── PKCE / JWT ──


def _pkce_pair() -> tuple[str, str]:
    """生成 (code_verifier, code_challenge)，与官方 PKCE 示例一致。"""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def _jwt_claims(access_token: str) -> dict:
    """解出 JWT 载荷，**不验签**。

    不验签是安全的：这个令牌是我们自己刚经 TLS 从 CCP 的 token 端点直接拿到的，
    不存在第三方注入令牌的路径；验签是为了防「别人塞给我一个伪造令牌」，那个场景
    在这里不存在。`sub` 形如 `CHARACTER:EVE:<id>`。
    """
    seg = access_token.split(".")[1]
    seg += "=" * (-len(seg) % 4)
    claims = json.loads(base64.urlsafe_b64decode(seg))
    return claims if isinstance(claims, dict) else {}


def _character_from_claims(claims: dict, fallback_id: int | None, fallback_name: str | None) -> tuple[int, str]:
    sub = str(claims.get("sub") or "")
    char_id = int(sub.rsplit(":", 1)[-1]) if sub.startswith("CHARACTER:EVE:") else fallback_id
    char_name = str(claims.get("name") or fallback_name or "")
    if char_id is None or not char_name:
        raise RuntimeError("无法从令牌里确定角色身份，请重新授权")
    return int(char_id), char_name


# ── 回环回调 ──


class _CallbackServer(HTTPServer):
    """一次性回环回调服务器。

    `timeout` 必须是**亚秒级**：`ui_qml/workers/lifecycle.detach_worker` 只等 500ms，
    超时设大了每次关窗都会把一个阻塞在 `handle_request()` 的线程漏在外面。
    """

    timeout = 0.5
    allow_reuse_address = True
    pending: dict | None = None


class _CallbackHandler(BaseHTTPRequestHandler):
    server: _CallbackServer  # 收窄类型，方便写 pending

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        # 只把**真正的授权回调**当结果。浏览器可能顺手请求 /favicon.ico，用户也可能
        # 手动打开这个地址 —— 那些请求没有 code/error，若也写进 pending，就会把
        # 「回调 state 不匹配」这个吓人的错误甩给用户。
        if parsed.path != "/callback" or not (params.get("code") or params.get("error")):
            self.send_error(404)
            return
        self.server.pending = params
        body = (
            "<!doctype html><html><head><meta charset='utf-8'><title>授权完成</title></head>"
            "<body style='font-family:sans-serif;padding:2rem'>授权完成，可以关闭此窗口并回到助手。</body></html>"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        """默认实现会往 stderr 打日志；本地一次性回调不需要这些噪音。"""


def _start_callback_server() -> _CallbackServer:
    # 绑定回环 IP（不是 0.0.0.0 —— 那会暴露到局域网并触发防火墙弹窗）。
    # URL 里写 localhost、socket 绑 127.0.0.1 是正确组合。
    return _CallbackServer(("127.0.0.1", CALLBACK_PORT), _CallbackHandler)


def _authorize_url(code_challenge: str, state: str, extra_scopes: tuple[str, ...] = ()) -> str:
    """授权页 URL。`extra_scopes` 给「按开关才要的权限」用。

    默认只要 `SCOPES` —— 用不到的可选能力不该逼用户多授权一次，
    更不该让 CCP 门户没勾的 scope 把**整个**授权流程弄成 `invalid_scope`。
    """
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": CALLBACK_URL,
        "scope": " ".join((*SCOPES, *extra_scopes)),
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


# ── HTTP ──


async def _post_token(client, data: dict) -> dict:
    """POST 到 token 端点。

    注意：OAuth 的 token 端点要 **form 编码**，`APIClient.post` 发的是 JSON 体，
    所以这里直接用 session 发，只用它的共享限流器。
    """
    await client.limiter.acquire()
    async with client.session.post(TOKEN_URL, data=data, timeout=_TIMEOUT) as resp:
        text = await resp.text()
        try:
            payload = json.loads(text) if text.strip() else {}
        except json.JSONDecodeError:
            payload = {}
        if resp.status != 200:
            raise _TokenError(str(payload.get("error") or ""), str(payload.get("error_description") or ""), resp.status)
        return payload if isinstance(payload, dict) else {}


async def _get_json(client, url: str, token: str, *, scope_hint: str = "技能/增效体"):
    """带 Bearer 的 GET。自己看状态码 —— `APIClient.fetch` 把 401/403 都吞成 None，
    而我们必须把「授权失效」和「缺 scope」分开告诉用户。

    `scope_hint` 决定 403 的文案。**必须按接口传**：写死「技能/增效体」的话，
    钱包/挂单 403 时会把用户引去勾错的权限，怎么试都不成功。
    """
    headers = {"Authorization": f"Bearer {token}"}
    for attempt in range(2):
        await client.limiter.acquire()
        async with client.session.get(url, headers=headers, timeout=_TIMEOUT) as resp:
            if resp.status == 401:
                raise EsiAuthRevoked("授权已失效，请重新授权")
            if resp.status == 403:
                raise EsiScopeMissing(f"授权缺少{scope_hint}权限，请在开发者应用勾选对应 scope 后重新授权")
            if resp.status == 429 and attempt == 0:
                retry_after = resp.headers.get("Retry-After", "5")
                await asyncio.sleep(min(int(retry_after) if retry_after.isdigit() else 5, 60))
                continue
            resp.raise_for_status()
            text = await resp.text()
            return json.loads(text) if text.strip() else None


# ── 名字解析 ──


def _resolve_skill_names(skill_ids: list[int]) -> dict[int, str]:
    """skill_id → 中文名（ESI 的 skill_id 就是 SDE 的 type_id）。

    复用既有批量解析。**它要的是 reference.db 连接**，传 user 连接会 no such table: item。
    未命中时它回退返回 `str(type_id)`，所以纯数字串就是「没匹配上」。
    """
    if not skill_ids:
        return {}
    from core.container import get_container
    from services.name_resolver import resolve_item_names_batch

    conn = get_container().db.direct_connect("ref")
    try:
        return resolve_item_names_batch(conn, skill_ids)
    finally:
        conn.close()


class EsiSkillImportWorker(QThread):
    """拉取一个角色的技能 / 技能队列 / 植入体。

    产出 `result_signal` 的载荷：`{character_id, character_name, skills: {中文名: 等级}, implants: [type_id]}`。
    **worker 不写 char_config** —— 只回数据，由主线程的桥合并落盘，保证配置只有一个写者。
    """

    finished_signal = Signal(bool, str)  # success, 错误信息
    result_signal = Signal(dict)

    def __init__(self, character_name: str | None = None, *, force_browser: bool = False, parent=None) -> None:
        super().__init__(parent)
        #: 当前选中的配置角色名。有绑定就走静默刷新，没有才开浏览器。
        self._character_name = character_name
        #: 「添加角色」用：**总是**开浏览器让用户选角色。
        #: 少了这个开关，导完 A 之后 current 变成 A，再点就命中 A 的绑定静默刷 A，
        #: 用户永远没机会选 B（一账号多角色的常见场景）。
        self._force_browser = force_browser

    # ── 线程体 ──

    def run(self) -> None:
        loop = None
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            payload = loop.run_until_complete(self._import())
            # 被请求中断时不再发信号：接收方的 C++ 对象可能已析构，emit 会踩空
            if self.isInterruptionRequested():
                return
            self.result_signal.emit(payload)
            self.finished_signal.emit(True, "")
        except _Interrupted:
            return
        except (TimeoutError, aiohttp.ClientError) as e:
            log.warning("ESI 导入网络失败: %s", e)
            if not self.isInterruptionRequested():
                self.finished_signal.emit(False, "网络不可用，请稍后重试")
        except Exception as e:
            log.exception("ESI 技能导入失败")
            if not self.isInterruptionRequested():
                self.finished_signal.emit(False, str(e) or "导入失败")
        finally:
            if loop is not None:
                loop.close()

    async def _import(self) -> dict:
        from services.client import APIClient

        async with APIClient(timeout=30) as client:
            access, char_id, char_name = await self._obtain_token(client)
            if self.isInterruptionRequested():
                raise _Interrupted()
            return await self._pull(client, access, char_id, char_name)

    # ── 令牌 ──

    def _extra_scopes(self) -> tuple[str, ...]:
        """子类可追加「按开关才要」的 scope（默认不加）。

        单独开钩子而不是往 `SCOPES` 里塞：常量是所有用户都要的，而军团钱包这类
        可选能力一旦写进常量，没开开关的人也得重新授权一次；更糟的是仓库若没在
        CCP 门户勾过那个 scope，授权会直接 `invalid_scope`，把**整个** ESI 链路
        （含技能）一起弄挂。
        """
        return ()

    async def _obtain_token(
        self, client, character_name: str | None = None, *, allow_browser: bool = True
    ) -> tuple[str, int, str]:
        """有可用绑定就静默刷新，否则开浏览器授权。`force_browser` 时跳过静默路径。

        `character_name` 省略时用构造期那个（`EsiSkillImportWorker` 的原行为）；
        多角色同步的调用方逐个显式传入 —— 这样不必把这段逻辑复制第二遍。
        `allow_browser=False` 时**不弹浏览器**，直接按授权失效报错：批量同步里
        一个角色掉线不该让用户连着走三次授权流程（每次最长等 10 分钟）。
        """
        name = character_name or self._character_name
        if name and not self._force_browser:
            row = load_token_row(name)
            if row:
                if self._still_valid(row.get("access_expires_at")) and row.get("access_token"):
                    return str(row["access_token"]), int(row["character_id"]), str(row["character_name"])
                try:
                    return await self._refresh(client, row)
                except _TokenError as e:
                    if e.code != "invalid_grant":
                        raise RuntimeError(f"刷新授权失败：{e}") from e
                    # invalid_grant = 用户在 support 站点撤销了（或令牌已作废）。
                    # 删掉死行，然后**直接接着走浏览器授权** —— 用户点的就是「导入」，
                    # 这里报个错让他再点一次没有意义。
                    log.info("ESI 授权已撤销，转入重新授权: %s", row.get("character_name"))
                    delete_token_row(int(row["character_id"]))
        if not allow_browser:
            raise EsiAuthRevoked(f"{name or '该角色'} 的绑定已失效，请重新授权")
        return await self._browser_authorize(client)

    @staticmethod
    def _still_valid(expires_at: str | None) -> bool:
        """同格式 ISO8601 UTC 串，字典序即时间序；留 `_EXPIRY_MARGIN_S` 裕量。"""
        if not expires_at:
            return False
        deadline = datetime.now(UTC) + timedelta(seconds=_EXPIRY_MARGIN_S)
        return expires_at > deadline.strftime("%Y-%m-%dT%H:%M:%SZ")

    async def _refresh(self, client, row: dict) -> tuple[str, int, str]:
        payload = await _post_token(
            client,
            {
                "grant_type": "refresh_token",
                "refresh_token": str(row["refresh_token"]),
                "client_id": CLIENT_ID,
            },
        )
        return self._persist(
            payload,
            previous_refresh=str(row["refresh_token"]),
            fallback_id=int(row["character_id"]),
            fallback_name=str(row["character_name"]),
        )

    async def _browser_authorize(self, client) -> tuple[str, int, str]:
        verifier, challenge = _pkce_pair()
        state = secrets.token_urlsafe(16)
        try:
            server = _start_callback_server()
        except OSError as e:
            raise RuntimeError(f"回调端口 {CALLBACK_PORT} 被占用，请关掉占用它的程序后重试") from e
        try:
            webbrowser.open(_authorize_url(challenge, state, self._extra_scopes()))
            code = self._await_code(server, state)
        finally:
            # 无条件关掉：否则端口 8721 会一直泄漏到进程结束
            server.server_close()
        try:
            payload = await _post_token(
                client,
                {
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": CLIENT_ID,
                    "code_verifier": verifier,
                },
            )
        except _TokenError as e:
            raise RuntimeError(f"换取令牌失败：{e}") from e
        return self._persist(payload)

    def _await_code(self, server: _CallbackServer, state: str) -> str:
        deadline = time.monotonic() + _AUTH_TIMEOUT_S
        while server.pending is None:
            if self.isInterruptionRequested():
                raise _Interrupted()
            if time.monotonic() > deadline:
                raise RuntimeError(f"授权超时（{_AUTH_TIMEOUT_S} 秒内没收到回调），请重试")
            server.handle_request()  # 自带 0.5s 超时，不会长阻塞
        got = server.pending
        if got.get("error"):
            raise RuntimeError(f"授权被拒绝：{got.get('error_description') or got['error']}")
        if got.get("state") != state:
            raise RuntimeError("回调 state 不匹配，已中止（防止 CSRF）")
        code = got.get("code")
        if not code:
            raise RuntimeError("回调里没有授权码")
        return str(code)

    def _persist(
        self,
        payload: dict,
        *,
        previous_refresh: str | None = None,
        fallback_id: int | None = None,
        fallback_name: str | None = None,
    ) -> tuple[str, int, str]:
        access = str(payload.get("access_token") or "")
        if not access:
            raise RuntimeError("token 端点没有返回 access_token")
        # 刷新响应可能不带 refresh_token（官方说「返回的可能与提交的不同」，没说一定返回）
        refresh = str(payload.get("refresh_token") or previous_refresh or "")
        if not refresh:
            raise RuntimeError("token 端点没有返回 refresh_token，无法保存授权")
        expires_at = _utc_after(int(payload.get("expires_in") or _DEFAULT_EXPIRES_IN))
        char_id, char_name = _character_from_claims(_jwt_claims(access), fallback_id, fallback_name)
        save_token_row(char_id, char_name, refresh, access, expires_at)
        return access, char_id, char_name

    # ── 拉数 ──

    async def _pull(self, client, access: str, char_id: int, char_name: str) -> dict:
        from core.char_settings_common import apply_skill_queue_finished

        base = f"{ESI_BASE}/characters/{char_id}"
        skills_raw = await _get_json(client, f"{base}/skills/", access) or {}
        queue_raw = await _get_json(client, f"{base}/skillqueue/", access) or []
        implants_raw = await _get_json(client, f"{base}/implants/", access) or []

        levels: dict[int, int] = {}
        for entry in skills_raw.get("skills", []) if isinstance(skills_raw, dict) else []:
            skill_id = int(entry.get("skill_id") or 0)
            if skill_id:
                # active_skill_level = 当前**生效**等级（制造公式吃的是这个）；
                # trained_skill_level 是已训练等级，两者仅在个别情形下不同。
                levels[skill_id] = int(entry.get("active_skill_level") or entry.get("trained_skill_level") or 0)

        # `/skills` 对角色离线期间练完的技能是过期的，必须叠加队列里已完成的条目
        if isinstance(queue_raw, list):
            levels = apply_skill_queue_finished(levels, queue_raw, _utc_now())

        names = _resolve_skill_names(list(levels))
        esi_skills = {name: levels[sid] for sid, name in names.items() if not name.isdigit()}

        implants = [int(t) for t in implants_raw if isinstance(t, int)] if isinstance(implants_raw, list) else []
        return {
            "character_id": char_id,
            "character_name": char_name,
            "skills": esi_skills,
            "implants": implants,
        }
