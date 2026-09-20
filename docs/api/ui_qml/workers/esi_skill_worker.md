# ui_qml.workers.esi_skill_worker

> 源文件 `ui_qml/workers/esi_skill_worker.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

从 ESI 导入角色技能 —— OAuth PKCE + 回环回调 + 拉取。

**为什么在 `ui_qml/workers/` 而不是 `services/`**：整套流程只有一个调用方
（人物设置对话框的导入按钮），按本仓克制条款第 1 条不足以新开服务模块；而
「UI 异步 = QThread + Signal」的既定位置就是这里，且已有 worker 直连 ESI 的先例
（`ui_qml/workers/order_workers.py`）。

**安全口径**：走 PKCE 公共客户端，**不带 client_secret** —— 官方 PKCE 示例明写
「we do not use the client secret in this flow」。`CLIENT_ID` 按公共客户端设计就是
公开的，可以内置；secret 一律不落代码、不落库。

**一次授权 = 一个角色**：令牌 `sub` 是 `CHARACTER:EVE:<id>`，用户在 CCP 页面上
选角色。多账号 / 一账号多角色 = 每个角色各点一次导入。

## 函数

### `_utc_now`

```python
def _utc_now() -> str
```

ESI 同款格式的 UTC 时间串。同格式 ISO8601 按字典序比较即等价于按时间比较。

定义行：`91`

### `_utc_after`

```python
def _utc_after(seconds: int) -> str
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`96`

### `_token_conn`

```python
def _token_conn()
```

打开 esi_tokens 所在连接。

定义行：`103`

### `load_token_row`

```python
def load_token_row(character_name: str) -> dict | None
```

按角色名取绑定行（token 按角色绑定，名字是配置里的匹配键）。

定义行：`118`

### `save_token_row`

```python
def save_token_row(character_id: int, character_name: str, refresh_token: str, access_token: str, access_expires_at: str) -> None
```

写入/更新绑定行。

定义行：`132`

### `delete_token_row`

```python
def delete_token_row(character_id: int) -> None
```

授权被撤销时清掉这一行（留着只会每次刷新都失败）。

定义行：`163`

### `_pkce_pair`

```python
def _pkce_pair() -> tuple[str, str]
```

生成 (code_verifier, code_challenge)，与官方 PKCE 示例一致。

定义行：`176`

### `_jwt_claims`

```python
def _jwt_claims(access_token: str) -> dict
```

解出 JWT 载荷，**不验签**。

定义行：`183`

### `_character_from_claims`

```python
def _character_from_claims(claims: dict, fallback_id: int | None, fallback_name: str | None) -> tuple[int, str]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`196`

### `_start_callback_server`

```python
def _start_callback_server() -> _CallbackServer
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`247`

### `_authorize_url`

```python
def _authorize_url(code_challenge: str, state: str) -> str
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`253`

### `_post_token`

```python
async def _post_token(client, data: dict) -> dict
```

POST 到 token 端点。

定义行：`269`

### `_get_json`

```python
async def _get_json(client, url: str, token: str)
```

带 Bearer 的 GET。自己看状态码 —— `APIClient.fetch` 把 401/403 都吞成 None，
而我们必须把「授权失效」和「缺 scope」分开告诉用户。

定义行：`287`

### `_resolve_skill_names`

```python
def _resolve_skill_names(skill_ids: list[int]) -> dict[int, str]
```

skill_id → 中文名（ESI 的 skill_id 就是 SDE 的 type_id）。

定义行：`310`

## 类

### `class _Interrupted`（继承 `Exception`）

用户关掉了对话框 —— 不是错误，不要发信号。

定义行：`68`

### `class _TokenError`（继承 `RuntimeError`）

token 端点返回非 200。`code` 是 OAuth 的 error 字段（如 invalid_grant）。

定义行：`72`

#### 方法

##### `__init__`

```python
def __init__(self, code: str, desc: str, status: int) -> None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`75`

### `class EsiAuthRevoked`（继承 `RuntimeError`）

401：令牌失效或授权已被撤销，需要用户重新授权。

定义行：`80`

### `class EsiScopeMissing`（继承 `RuntimeError`）

403：令牌有效但缺 scope。

定义行：`84`

### `class _CallbackServer`（继承 `HTTPServer`）

一次性回环回调服务器。

`timeout` 必须是**亚秒级**：`ui_qml/workers/lifecycle.detach_worker` 只等 500ms，
超时设大了每次关窗都会把一个阻塞在 `handle_request()` 的线程漏在外面。

定义行：`208`

### `class _CallbackHandler`（继承 `BaseHTTPRequestHandler`）

::: warning ⚠️ 待补 docstring
此类暂无 docstring，欢迎补充。
:::

定义行：`220`

#### 方法

##### `do_GET`

```python
def do_GET(self) -> None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`223`
##### `log_message`

```python
def log_message(self, *args: object) -> None
```

默认实现会往 stderr 打日志；本地一次性回调不需要这些噪音。

定义行：`243`

### `class EsiSkillImportWorker`（继承 `QThread`）

拉取一个角色的技能 / 技能队列 / 植入体。

产出 `result_signal` 的载荷：`&#123;character_id, character_name, skills: &#123;中文名: 等级&#125;, implants: [type_id]&#125;`。
**worker 不写 char_config** —— 只回数据，由主线程的桥合并落盘，保证配置只有一个写者。

定义行：`328`

#### 方法

##### `__init__`

```python
def __init__(self, character_name: str | None=None, *, force_browser: bool=False, parent=None) -> None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`338`
##### `run`

```python
def run(self) -> None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`349`
##### `_import`

```python
async def _import(self) -> dict
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`374`
##### `_obtain_token`

```python
async def _obtain_token(self, client) -> tuple[str, int, str]
```

有可用绑定就静默刷新，否则开浏览器授权。`force_browser` 时跳过静默路径。

定义行：`385`
##### `_still_valid`

```python
def _still_valid(expires_at: str | None) -> bool
```

同格式 ISO8601 UTC 串，字典序即时间序；留 `_EXPIRY_MARGIN_S` 裕量。

定义行：`405`
##### `_refresh`

```python
async def _refresh(self, client, row: dict) -> tuple[str, int, str]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`412`
##### `_browser_authorize`

```python
async def _browser_authorize(self, client) -> tuple[str, int, str]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`428`
##### `_await_code`

```python
def _await_code(self, server: _CallbackServer, state: str) -> str
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`455`
##### `_persist`

```python
def _persist(self, payload: dict, *, previous_refresh: str | None=None, fallback_id: int | None=None, fallback_name: str | None=None) -> tuple[str, int, str]
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`473`
##### `_pull`

```python
async def _pull(self, client, access: str, char_id: int, char_name: str) -> dict
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`495`
