# Industry Page Redesign - Complete Implementation Plan

> Reference: EVE Online Industry Planner screenshot (Pyfa/Blueprint calculator style)
> Updated after audit: 2026-07-01

---

## 1. Layout Overview

The page is divided into 5 regions from top to bottom:

```
================================================================
  Title Bar
  "Production Plan" + plan count statistics
----------------------------------------------------------------
  Top Toolbar
  [Blueprint import input][Add] [Pref defaults] |
  [Material Hub][Sell/Buy multiplier][Skill lvl] |
  [Filter: All|Pending|Running|Done] [Refresh]
----------------------------------------------------------------
  Main Table (Production Plan Table)
  20 columns with scrollable/sortable/filterable
  Header right-click -> Show/Hide columns
  Inline editing on editable cells
----------------------------------------------------------------
  Add Row
  [+ Add from blueprint list] button
----------------------------------------------------------------
  Status Bar
  Plan: N | Running: N | Pending: N |
  Purchases: XXX ISK | Vol: XXX m3 | [Save Prices]
----------------------------------------------------------------
  Action Buttons
  [Refresh Materials/Procure] [Blueprints] [Materials] [Output] [Char Usage]
================================================================
```

---

## 2. Top Toolbar

### 2.1 Left: Blueprint Import

| Widget | Type | Description |
|--------|------|-------------|
| Blueprint paste input | QLineEdit | Placeholder: "Paste blueprint data from clipboard" |
| Add button / "+ Add from blueprint" | QPushButton | Open blueprint selection dialog |
| Pref defaults / small helper | QPushButton | Default config dialog (ME/TE/skills), Phase 3 |

### 2.2 Middle: Material/Price Settings

| Widget | Type | Description |
|--------|------|-------------|
| Material Hub dropdown | QComboBox | Purchase hub: Jita/Amarr/Dodixie/Rens/Hek |
| Sell price multiplier | QDoubleSpinBox | Sell price adjustment (default 1.00) |
| Buy price multiplier | QDoubleSpinBox | Buy price adjustment (default 1.00) |
| Order mode | QComboBox | Single/Bulk order (Phase 3) |
| Skill level dropdown | QComboBox | Presets: All 5/All 4/All 3/Custom (from char_config) |

### 2.3 Right: Filter + View + Actions

| Widget | Type | Description |
|--------|------|-------------|
| Status filter | QComboBox | All/Pending/Running/Done |
| Data / Gantt toggle | QRadioButton (Phase 3, Phase 1 = placeholder) | Table view / Gantt chart |
| Auto-adjust sub-items | QCheckBox (Phase 3) | Auto-adjust sub-component flow |
| Refresh button | QPushButton | Refresh all data |
| Help button | QPushButton (Phase 3) | Help documentation |

### 2.4 "Pref defaults" Button Behavior (Phase 3 details)

- Opens a config dialog to set ME/TE defaults, skill level defaults
- Settings saved to `production_settings` table (new)
- Phase 1: button exists but shows "Feature in development" on click

---

## 3. Main Table

### 3.1 Column Definitions

| # | Column | Data Source | Width | Sort | Inline Edit | Description |
|---|--------|-------------|-------|------|-------------|-------------|
| 0 | Icon | `data/caches/icons/{type_id}.png` -> QPixmapCache | 32px | No | No | 32x32 icon, empty if cache miss |
| 1 | Product | product_name | auto | Yes | No | Product name |
| 2 | Runs | runs | 60px | Yes | Yes | Manufacturing runs |
| 3 | Parallel | parallels | 50px | Yes | Yes | Parallel queues |
| 4 | Group | group_number | 50px | Yes | Yes | Group number (for intermediate products) |
| 5 | Depth | sub_level | 50px | Yes | No | BOM depth level |
| 6 | Status | status | 80px | Yes | No | Pending/Running/Done/Unconfirmed |
| 7 | Notes | notes (new field) | 120px | No | Yes | User notes |
| 8 | Character | char_name | 100px | Yes | Yes | Production character |
| 9 | Flow | "runs x parallels" | 60px | No | No | Display format "1 x1" |
| 10 | Blueprint | "me-te[have/no]" | 100px | No | No | e.g. "10-20[have]" |
| 11 | Duration | calculated_time | 80px | Yes | No | Format "HH:MM:SS" |
| 12 | Facility | facility_name | 80px | Yes | Yes | Production facility |
| 13 | Output | output_location | 80px | Yes | Yes | Output location (hangar) |
| 14 | Cost | material_cost | 110px | Yes | No | Total material cost ISK (with separators) |
| 15 | Profit | profit | 110px | Yes | No | Profit ISK (green positive, red negative) |
| 16 | Mkt Margin | market_margin_pct | 80px | Yes | No | Market margin % |
| 17 | Own Margin | personal_margin_pct | 80px | Yes | No | Personal margin % (incl skills/tax) |
| 18 | Score | score | 60px | Yes | No | Score 0-100 |
| 19 | Actions | - | 120px | No | No | Start/Complete/Delete buttons |

### 3.2 Table Interactions

- **Single click**: Select and highlight row
- **Double click**: Open plan detail edit dialog (Phase 3)
- **Right click menu**: Delete / Copy / Export row
- **Column header click**: Sort (asc/desc/reset)
- **Column header right-click**: Show/Hide column toggle menu (Phase 1)
  - Implementation: QMenu with QCheckBox per column, calls `tableView.setColumnHidden()`
- **Inline editing**: Double-click cells on editable columns (Phase 1)
  - `flags()` returns `Qt.ItemIsEditable` for columns: 2,3,4,7,8,12,13
  - `setData()` updates internal model + writes to user.db

### 3.3 Icon Column Rendering (FIXED after audit)

**Important**: Do NOT do file I/O in `DecorationRole`. Use `QPixmapCache`:

```python
from PySide6.QtGui import QPixmapCache, QPixmap

# In PlanTableModel.data() for DecorationRole:
pixmap = QPixmapCache.find(f"icon_{type_id}")
if not pixmap:
    icon_path = f"data/caches/icons/{type_id}.png"
    if os.path.exists(icon_path):
        pixmap = QPixmap(icon_path).scaled(32, 32, Qt.AspectRatioMode.KeepAspectRatio, ...)
        QPixmapCache.insert(f"icon_{type_id}", pixmap)
    else:
        return None  # Return empty, no icon
return pixmap
```

The `geticon.py` worker is for pre-downloading icons. It is NOT called at runtime during table rendering.
If icons are not pre-downloaded, the column just shows empty for those rows.

### 3.4 Filter Functionality (RESTORED after audit)

The filter combo in the toolbar applies `WHERE status = ?` to `load_plans()`.

| Filter | SQL Condition |
|--------|---------------|
| All | (no filter) |
| Pending | `WHERE status IN ('pending')` |
| Running | `WHERE status IN ('running', 'in_progress')` |
| Done | `WHERE status IN ('completed', 'done')` |

### 3.5 Plan Creation Entry (ADDED after audit)

- Below the table: "+ Add from blueprint list" button
- Click opens blueprint selection dialog
- Input: type_id + runs + parallels + ME + TE + character
- INSERT into production_plans, then call `load_plans()` to refresh

---

## 4. Status Bar

```
Plan total: N | Running: N | Pending: N |
Purchase list: XXX,XXX.XX ISK | Volume(m3): XXX | [Save Prices]
```

| Field | Calculation | Update Timing |
|-------|-------------|---------------|
| Plan total / Running / Pending | Computed from PlanTableModel._plans in memory (NOT from DB) | After load_plans() |
| Purchase list total | Sum of material costs for all active plans | After material refresh |
| Volume(m3) | Sum of volume for all pending purchase materials | After material refresh |
| [Save Prices] button | Saves current prices to `price_snapshots` table | On click |

**Note**: Status bar stats are computed from the in-memory model data, not from a separate DB query.

---

## 5. Bottom Action Buttons & Sub-Panels

### 5.1 Refresh Materials / Procurement Assistant
- **Existing**: `procurement_tab.py` -> `ProcurementDialog`
- **Changes**: Integrate into bottom button click, show summary total in dialog title

### 5.2 Required Blueprint Table
- **New**: `BlueprintRequirementsDialog`
- **Data source (FIXED after audit)**:
  1. Get all active plans (status IN ('pending','running'))
  2. For each plan's `product_type_id`, call `bom_expander.expand_bom()` recursively
  3. Collect all intermediate products' `blueprint_type_id`
  4. Aggregate and compare against `user_blueprints` table
  5. Display: blueprint name / BPO or BPC / ME/TE owned / quantity needed / quantity owned / status

| Column | Description |
|--------|-------------|
| Blueprint Name | Blueprint item name |
| Type | BPO / BPC |
| ME | Owned ME level |
| TE | Owned TE level |
| Needed | How many blueprints needed |
| Owned | Owned count from user_blueprints |
| Status | Sufficient / Missing |

### 5.3 Materials Summary (BOM Total)
- **New**: `MaterialsSummaryDialog`
- **Data source**: `bom_expander.expand_bom()` recursive BOM expansion + inventory comparison

| Column | Description |
|--------|-------------|
| Material Name | Item name |
| Depth | 0=raw material, 1=sub-component, ... |
| Needed | Total quantity required (incl ME waste) |
| Stock | Quantity in inventory |
| Shortfall | Needed - Stock |
| Unit Price | Current market price |
| Total Price | Shortfall x unit price |
| Volume | Shortfall x unit volume |

### 5.4 Output Summary
- **New**: `OutputSummaryDialog`
- **Data source**: `production_plans` + `scoring.calc_manufacturing_score()`

| Column | Description |
|--------|-------------|
| Product Name | Item name |
| Quantity | Total output quantity |
| Cost | Total material cost |
| Sell Price | Current market sell price |
| Profit | Revenue - Cost |
| Margin | Profit / Cost % |
| Status | Pending/Running/Done |

### 5.5 Character Usage
- **New**: `CharacterUsageDialog`
- **Data source**: `production_plans` GROUP BY char_name + `char_config.json`

| Column | Description |
|--------|-------------|
| Character Name | Production character name |
| Active Plans | Number of running plans |
| Queue Duration | Total plan duration (calc from base_time * skill_mod * te_mod) |
| Skill Levels | Industry / Advanced Industry etc from char_config |
| Usage Details | Expand to show specific plans |

### 5.6 "Save Prices" Button (CLARIFIED after audit)

- Creates/uses `price_snapshots` table (see Section 6)
- On click: snapshots sell_price / buy_price for all items involved in active plans
- Shows confirmation: "Saved {N} price snapshots at {time}"

---

## 6. Database Changes

### 6.1 production_plans - New Columns

```sql
ALTER TABLE production_plans ADD COLUMN notes TEXT DEFAULT '';
ALTER TABLE production_plans ADD COLUMN group_number INTEGER DEFAULT 0;
ALTER TABLE production_plans ADD COLUMN sub_level INTEGER DEFAULT 0;
ALTER TABLE production_plans ADD COLUMN facility TEXT DEFAULT '';
ALTER TABLE production_plans ADD COLUMN output_location TEXT DEFAULT '';
ALTER TABLE production_plans ADD COLUMN sell_hub TEXT DEFAULT 'Jita';
ALTER TABLE production_plans ADD COLUMN market_margin REAL DEFAULT 0;
ALTER TABLE production_plans ADD COLUMN personal_margin REAL DEFAULT 0;
```

### 6.2 New Tables

```sql
CREATE TABLE IF NOT EXISTS price_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type_id INTEGER NOT NULL,
    region_id INTEGER NOT NULL,
    sell_price REAL,
    buy_price REAL,
    snapshot_time TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(type_id, region_id, snapshot_time)
);

CREATE TABLE IF NOT EXISTS production_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    value TEXT NOT NULL
);
```

---

## 7. File Change List

### 7.1 Modified Files

| File | Change | Description |
|------|--------|-------------|
| `ui_pyside6/views/industry_view.py` | Rewrite | Page layout, orchestrates all components |
| `ui_pyside6/models/industry_models.py` | Extend | PlanTableModel to 20 cols + QPixmapCache icons + inline edit |
| `services/production_scheduler.py` | Extend | Add time/profit calculation, save_prices(), get_price_snapshot() |

### 7.2 New Files

| File | Description |
|------|-------------|
| `ui_pyside6/views/industry/__init__.py` | Exports: TopToolbar, PlanTable, StatusBar, ActionButtons, BlueprintRequirementsDialog, MaterialsSummaryDialog, OutputSummaryDialog, CharacterUsageDialog |
| `ui_pyside6/views/industry/top_toolbar.py` | Top toolbar with all inputs |
| `ui_pyside6/views/industry/plan_table.py` | Main table with column defs, rendering, interactions |
| `ui_pyside6/views/industry/status_bar.py` | Status bar with real-time stats |
| `ui_pyside6/views/industry/action_buttons.py` | Bottom action button group |
| `ui_pyside6/views/industry/blueprint_dialog.py` | Blueprint requirements dialog |
| `ui_pyside6/views/industry/materials_dialog.py` | Materials summary dialog (BOM-based) |
| `ui_pyside6/views/industry/output_dialog.py` | Output summary dialog |
| `ui_pyside6/views/industry/char_usage_dialog.py` | Character usage dialog |

---

## 8. Implementation Phases

### Phase 1: Core Framework + Table (1200-1500 lines)

1. Rewrite `industry_view.py` page layout (5 regions: title / toolbar / table / status bar / buttons)
2. Extend `PlanTableModel` to full 20 columns with icon rendering via QPixmapCache
3. Add inline editing for editable columns (runs, parallels, group_number, notes, char_name, facility, output_location)
4. Add column visibility control (header right-click -> checkbox toggle menu)
5. Bottom status bar real-time calculation
6. Top toolbar: Hub selection / Skill selection / Filter / Refresh
7. Plan creation: "+ Add from blueprint list" button with selection dialog
8. All toolbar features NOT in scope show "Feature in development" on click

### Phase 2: Sub-Panels (800-1000 lines)

1. Procurement assistant (reuse ProcurementDialog with minor adaptation)
2. Blueprint requirements dialog (BlueprintRequirementsDialog)
3. Materials summary (MaterialsSummaryDialog, based on bom_expander)
4. Output summary (OutputSummaryDialog)
5. Character usage (CharacterUsageDialog)

### Phase 3: Advanced Features (500-700 lines)

1. Blueprint paste-from-clipboard parser
2. Default config dialog (Pref defaults)
3. Plan detail edit dialog (double-click row)
4. Gantt chart view (timeline visualization)

---

## 9. Data Flow

```
User action -> toolbar widget change
    |
load_plans() loads plans from user.db
    |
For each plan:
  +-- Query blueprint_products -> blueprint info
  +-- Query blueprint_materials -> material list
  +-- Query market_prices -> cost/sell price
  +-- Query user_blueprints -> blueprint inventory match
  +-- Query inventory_items -> material inventory match
  +-- calc_manufacturing_score() -> time/profit/score
    |
Fill PlanTableModel -> table render
    |
Update status bar statistics
```

---

## 10. Key Dependencies

| Component | Exists? | Needs New? |
|-----------|---------|------------|
| BOM expander | YES (bom_expander.py) | - |
| Scoring | YES (scoring.py) | - |
| Procurement dialog | YES (procurement_tab.py) | Adapt to new layout |
| Production scheduler | YES (production_scheduler.py) | Extend time/profit calculation |
| Blueprint management | YES (inventory_manager.py) | - |
| Character config | YES (char_config_validator.py) | - |
| Icon download | YES (workers/geticon.py) | - |
| 20-col table render | - | YES (new) |
| Icon column render (QPixmapCache) | - | YES (new) |
| Price snapshot | - | YES (new: save_prices()) |
| Blueprint requirements panel | - | YES (new) |
| Materials summary panel | - | YES (new) |
| Output summary panel | - | YES (new) |
| Character usage panel | - | YES (new) |
| Toolbar component | - | YES (new) |
| Status bar component | - | YES (new) |

### 10.1 Icon Rendering (FIXED)

- Use QPixmapCache (Qt built-in) for in-memory caching
- Load flow: QPixmapCache.find(key) -> if not found: QPixmap(icon_path) -> QPixmapCache.insert(key, pixmap)
- icon_path = f"data/caches/icons/{type_id}.png"; if file doesn't exist, return None (empty cell)
- geticon.py is a pre-download tool, NOT called during table rendering

---

## 11. Risks & Notes

1. **Icon performance**: QPixmapCache handles this; no async needed for simple file loading
2. **BOM recursion**: Materials dialog needs recursive expansion; bom_expander already handles cycle detection
3. **Large datasets**: If dozens of plans exist, table may lag; consider pagination only if needed
4. **Theme compliance**: All colors MUST import from `ui_pyside6.theme`; NO hardcoded hex
5. **Dark/Light mode**: Every sub-panel implements `add_theme_listener` + `_on_theme_changed`
6. **Encoding**: All files UTF-8, Chinese comments
7. **Ruff lint**: `ruff check .` must pass before each commit

---

## 12. Line Count Estimate (UPDATED)

| Phase | Estimated Lines |
|-------|-----------------|
| Phase 1 (Core + Table + UI) | 1200-1500 |
| Phase 2 (Sub-panels) | 800-1000 |
| Phase 3 (Advanced) | 500-700 |
| **Total** | **2500-3200** |

---

## 13. Summary of Audit Fixes

| Issue | Original | Fixed |
|-------|----------|-------|
| Icon rendering | DecorationRole + file I/O | QPixmapCache + empty fallback |
| Plan creation | Phase 3 only (blueprint import) | Phase 1 "+ Add from blueprint list" button |
| Filter functionality | Missing | Restored to toolbar |
| Column visibility | Missing | Header right-click show/hide menu |
| Inline editing | Phase 3 only | Phase 1 basic fields (runs/parallels/notes etc) |
| "Save Prices" button | Undefined semantics | Defined price_snapshots table + behavior |
| Page title | Missing | Added title bar section |
| Status bar stats | Unclear update strategy | Clarified: compute from memory, not DB |
| Blueprint dialog data | Vague "user_blueprints + blueprint_materials" | Full BOM recursive approach documented |
| Transport reminder | Mentioned in Phase 3 scope check | Confirmed removed per user request |
