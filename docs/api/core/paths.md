# core.paths

> 源文件 `core/paths.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

集中式路径管理 —— 兼容开发环境和 PyInstaller 打包环境

开发环境：
    eve/
        Main.py
        database/
            reference.db   ← 静态参考数据（item, industry_*, market_tree, item_dogma）
            blueprint.db   ← 蓝图数据（blueprint_activities, _materials, _products, _skills）
            market.db      ← 市场价格数据（market_prices, market_volume_snapshots）
            user.db        ← 用户自有数据（hangars, inventory_items, production_plans, user_skills）
        data/caches/icons/
        services/workers/getprices.py

PyInstaller 打包后：
    dist/EVE商人助手/
        EVE商人助手.exe
        database/
            reference.db
            market.db
            user.db
        data/caches/icons/
        data/update_progress.json
        data/search_history.json
        data/window_geometry.json

## 函数

### `is_frozen`

```python
def is_frozen() -> bool
```

判断是否运行在 PyInstaller 打包后的环境中

定义行：`32`

### `app_root`

```python
def app_root() -> str
```

返回应用根目录（优先级：环境变量覆盖 > 打包环境 > 开发环境）

定义行：`37`

### `database_dir`

```python
def database_dir() -> str
```

数据库目录

定义行：`56`

### `database_path`

```python
def database_path() -> str
```

旧单库文件路径（迁移后保持兼容）

定义行：`61`

### `reference_db_path`

```python
def reference_db_path() -> str
```

参考数据库路径（item, industry_*, market_tree, item_dogma）

定义行：`66`

### `market_db_path`

```python
def market_db_path() -> str
```

市场价格数据库路径（market_prices, market_volume_snapshots）

定义行：`71`

### `user_db_path`

```python
def user_db_path() -> str
```

用户数据数据库路径（hangars, inventory_items, production_plans, user_skills）

定义行：`76`

### `blueprint_db_path`

```python
def blueprint_db_path() -> str
```

蓝图数据库路径（blueprint_activities, blueprint_materials, blueprint_products, blueprint_skills）

定义行：`81`

### `data_dir`

```python
def data_dir() -> str
```

数据目录（图标缓存、搜索历史等）

定义行：`86`

### `icon_cache_dir`

```python
def icon_cache_dir() -> str
```

图标缓存目录

定义行：`91`

### `progress_file`

```python
def progress_file() -> str
```

更新进度文件路径

定义行：`96`

### `search_history_file`

```python
def search_history_file() -> str
```

搜索历史文件路径

定义行：`101`

### `window_geometry_file`

```python
def window_geometry_file() -> str
```

窗口位置文件路径

定义行：`106`

### `ensure_dirs_exist`

```python
def ensure_dirs_exist()
```

确保所有必要目录存在（打包后首次运行时创建）

定义行：`111`
