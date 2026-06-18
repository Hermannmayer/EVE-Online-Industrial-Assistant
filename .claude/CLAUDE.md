# EVE Online Industrial Assistant

## Build & Run
- **Run:** `python Main.py` (PySide6 desktop app)
- **Dev server:** `python dev.py`

## Test
- **Run tests:** `pytest`
- **Test directory:** `tests/`

## Lint & Format
- **Lint:** `ruff check .`
- **Format:** `ruff format .`
- **Config:** `pyproject.toml` (line-length 120, py314 target)

## Stack
- **Language:** Python 3.14
- **GUI:** PySide6 (Qt6 Widgets)
- **Frameworks:** aiohttp (async HTTP), aiosqlite (async DB), tenacity (retry)
- **Format:** Ruff (lint + format)
- **Test:** pytest

## Project Structure
- `Main.py` — Application entry point
- `core/` — Core logic (paths, logging)
- `services/` — Business logic (scoring, data fetching, workers)
- `ui/` — Legacy UI
- `ui_pyside6/` — PySide6 UI (main window, views, theme)
- `database/` — SQLite database
- `data/` — Caches, search history, window geometry
- `tests/` — pytest test suite
