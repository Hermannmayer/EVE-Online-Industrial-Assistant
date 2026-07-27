# EVE-Online-Industrial-Assistant

PySide6 + SQLite 桌面应用。

## 代码约束

- **Python 3.14+** / **PySide6 6.8+** / ruff 格式化 + linting
- ❌ Python 2 语法、裸 `except: pass`、SQL F-string 拼接、模块级 DB 单例
- ✅ 参数化查询、`logger.exception(...)`、`async with`、类型注解、新功能加测试
- ✅ 终止表示论从 `ui_pyside6.theme` 导入，禁止 hex/rgb/颜色名
- ✅ **术语铁律**：EVE 术语（技能名/蓝图活动/UI 标签）通过 `services.terminology` 获取，技能 key 需在 `data/terminology.json` 注册
- ✅ 安全：参数化查询防注入、`yaml.safe_load()`、不硬编码密钥
- 三层分离：`core/` → `services/` → `ui_pyside6/`，依赖注入用 `core/container.py`

## 测试

```bash
pytest tests/ -q --quick --maxfail=1   # 日常（~20s，跳过 Qt）
pytest tests/                           # 全量回归（含 Qt，~1.5min）
```

提交前：`ruff check .` + `mypy .` + `pytest` 均通过，无新增 `except: pass`。

## 常用命令

```bash
python dev.py            # 热重载
python Main.py           # 生产启动
ruff check . --fix       # 修复风格
```

## EVE 术语来源（按优先级）

1. **SDE 数据库** `database/reference.db` → `item` 表（CCP 官方翻译）
   - `SELECT zh_name FROM item WHERE category_id=16 AND en_name='Reprocessing'`
2. **`data/terminology.json`** — 项目中水线，`services.terminology.py` 统一查询
3. 公式中的技能 key → 先在 `terminology.json` 的 `skill_names` 注册
