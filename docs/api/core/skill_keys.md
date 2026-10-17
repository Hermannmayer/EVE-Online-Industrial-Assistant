# core.skill_keys

> 源文件 `core/skill_keys.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

技能键（中文名）常量 —— `core/` 与 `domain/` 层技能名的**唯一来源**。

为什么放在 `core/` 而不是 `services/terminology.py`：
    - `domain/` 是纯函数层，禁止 import `services/`（分层铁律）；
    - 但制造/科研/贸易/精炼公式都要按**中文技能名**从 `char_config.json` 的
      `skills` 字典取值（例如 `skills.get("工业理论")`）。这些中文名原本散落在
      domain/core 各处硬编码，改名/新增技能时容易漏改一处就静默取到 0 级。

分层口径（不要反过来）：
    - `core/` / `domain/`：本模块的中文常量，只做「取值键」；不查 DB、不查术语服务。
    - `services/terminology.py` + `data/terminology.json`：UI/查询层的术语来源
      （英文名 ↔ 中文名映射）。本模块的每个中文名都必须在 `terminology.json` 的
      `skill_names` 里注册 —— 由 `tests/test_skill_keys.py` 护栏保证。
    - UI 层仍然走 `services.terminology`，**不要**从 QML/桥里 import 本模块。

取值契约：常量值就是 `char_config.json` 里 `skills` 字典的键，必须与 SDE
`item.zh_name`（CCP 官方中文名）一致；`tests/test_skill_keys.py` 同时校验
「在 terminology.json 注册」与「取值为非空、互不重复」。

_（此模块无可公开的类或函数）_
