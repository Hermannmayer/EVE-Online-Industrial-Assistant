# EVE Online Industrial Assistant

## Build & Run
- **Run:** `python Main.py` (PySide6 desktop app)
- **Dev reload:** `python dev.py` (auto-restart on file changes)
- **Build release:** `python build_release.py` (PyInstaller 打包)

## Test
- **Run tests:** `pytest`
- **Failing collection fix:** `pip install -e .` 或确保 `__init__.py` 正确

## Test
- **Run tests:** `pytest`
- **Test directory:** `tests/`

## Lint & Format
- **Lint:** `ruff check .`
- **Format:** `ruff format .`
- **Config:** `pyproject.toml` (line-length 120, py314 target)
- **Type check:** mypy . --ignore-missing-imports
- **Pre-commit:** pre-commit run --all-files

## Stack
- **Language:** Python 3.14
- **GUI:** PySide6 (Qt6 Widgets)
- **Frameworks:** aiohttp (async HTTP), aiosqlite (async DB), tenacity (retry)
- **Format:** Ruff (lint + format, line-length=120)
- **Test:** pytest + pytest-qt + pytest-cov
- **Type check:** mypy
- **Pre-commit:** pre-commit (ruff + mypy + 通用检查)

## Project Structure
- `Main.py` — Application entry point
- `dev.py` — Hot-reload development mode
- `build_release.py` — PyInstaller packaging
- `core/` — Core logic (paths, logging, constants, container, formulas)
- `services/` — Business logic (scoring, SDE, logistics, BOM, workers)
- `ui_pyside6/` — PySide6 UI (main window, views, dialogs, theme, models)
- `database/` — SQLite databases (reference / market / user / blueprint)
- `data/` — Caches, settings, YAML data
- `scripts/` — Maintenance scripts (migration)
- `specs/` — Implementation specs
- `tests/` — pytest test suite (50 test files, 620+ tests)

## 自主运行规则
- 技术方案不明确 → 选最简方案，改动最小
- 两种可行实现 → 选更简单的
- 连续 3 次修复失败 → 写入 blocked.md，切换任务
- 上下文紧张时 → 把进度写入 tasks/mission.md（已完成/下一步/阻塞）
- 永远不要用 AskUserQuestion，做出最佳判断继续
- 需求模糊 → 应用最合理理解，记录假设
- 每完成一个功能点 → git commit（中文信息）
- 提交前确保 `ruff check .` 通过

## 配色铁律（违反将导致亮/暗模式失效）
- 所有颜色从 `ui_pyside6.theme` 导入，禁止 hex(#xxx)/rgb()/颜色名(white/black等)
- 按钮/选中菜单文字用 TEXT_ON_PRIMARY，禁止 `white`/`#fff`
- 新页面/弹窗必须 `add_theme_listener` + 实现 `_on_theme_changed` 重建 inline stylesheet
- 右键菜单禁止 inline setStyleSheet，依赖全局 QSS（已覆盖 QMenu/QMenu::item/QMenu::item:selected）
- QColor 只接受 theme 模块级变量，不传字符串
- 提交前自查: `grep -nE '#[0-9a-fA-F]{3,6}|color:\s*white|QColor\("' ui_pyside6/views/*.py ui_pyside6/main_window.py`
