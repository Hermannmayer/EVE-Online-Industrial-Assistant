# 测试与规范

## 测试框架

| 工具 | 版本 | 用途 |
|------|------|------|
| pytest | ~9.0 | 测试运行器 |
| pytest-qt | ~4.5 | Qt UI 测试 |
| pytest-cov | ~5.0 | 覆盖率统计 |
| pytest-asyncio | ~1.3 | 异步测试支持 |

## 运行测试

```bash
# 日常快速测试（跳过 Qt 界面测试，~20s）
pytest tests/ -q --quick --maxfail=1

# 全量回归（含 Qt 测试，~1.5min）
pytest tests/

# 覆盖率报告
pytest tests/ --cov=core --cov=services --cov-report=term-missing

# 运行指定文件
pytest tests/test_scoring.py -v

# 运行匹配的测试名
pytest tests/ -k "test_calc" -v
```

## 测试模式

测试文件中使用 `@pytest.mark` 标记：

```python
@pytest.mark.slow
def test_qt_dialog():
    """需要 Qt 显示环境的 UI 测试"""
    ...

def test_scoring_logic():
    """纯逻辑单元测试（默认）"""
    ...
```

| 标记 | 说明 | 运行条件 |
|------|------|----------|
| `slow` | Qt 界面测试，需要显示环境 | 全量测试 / `QT_QPA_PLATFORM=offscreen` |
| `ui` | UI 相关测试 | 同 slow |

`--quick` 模式自动跳过所有 `@pytest.mark.slow` 测试。

## 测试目录结构

```
tests/
├── conftest.py                    # 共享 fixtures（临时数据库、QApplication）
├── test_core.py                   # core/ 核心路径与配置
├── test_logger.py                 # 日志模块
├── test_paths.py                  # 路径管理
├── test_database_manager.py       # 数据库连接管理器
├── test_scoring.py                # 贸易/制造评分计算
├── test_scoring_cache.py          # 评分缓存
├── test_scoring_core.py           # 评分核心逻辑
├── test_personal_margin.py        # 个人利润率
├── test_price_history.py          # 价格走势图数据
├── test_export_helper.py          # 批量导出
├── test_procurement.py            # 代采购管理
├── test_watchlist_manager.py      # 关注列表与价格变化检测
├── test_contract_view.py          # 合同视图
├── test_logistics.py              # 物流距离计算
├── test_logistics_cost.py         # 物流成本计算
├── test_theme_listeners.py        # 主题监听模式
├── test_ui_industry.py            # 工业页面 UI
├── test_ui_inventory.py           # 仓库页面 UI
├── test_ui_main_window.py         # 主窗口 UI
├── test_workers_industry.py       # 制造评分 Worker
└── test_workers_plan_refresh.py   # 计划价格刷新 Worker
```

## 测试 Fixtures

`conftest.py` 提供的关键 fixtures：

```python
def _create_temp_databases(tmpdir: str):
    """创建标准临时数据库套件（ref/mkt/bp/user 四个库）"""
    # 每个测试文件自动获得独立的临时数据库
    # 测试结束后自动清理
```

## 代码质量工具

### ruff — Lint + Format

```bash
ruff check .                # 检查
ruff check . --fix          # 自动修复
ruff format .               # 格式化
ruff format --check .       # 检查格式（CI 用）
```

配置在 `pyproject.toml`：
- `line-length = 120`
- `target-version = "py313"`
- 启用规则：E/W/F/B/I/M/C4/UP

### mypy — 类型检查

```bash
mypy .                       # 检查全部
mypy . --ignore-missing-imports  # 忽略第三方库类型
```

`pyproject.toml` 配置要点：
- `python_version = "3.14"`
- `warn_unused_configs = true`
- `warn_redundant_casts = true`
- PySide6/aiohttp/aiosqlite 等库 `ignore_missing_imports = true`

### 提交前检查清单

```bash
# 标准提交前验证（确保全绿）
ruff check . && ruff format --check . && mypy . && pytest tests/ -q --quick
```

## CI 检查

GitHub Actions CI（`.github/workflows/ci.yml`）在 push main/develop 和 PR 时运行：

1. **ruff** — lint + format 检查
2. **mypy** — 类型检查
3. **pytest** — 全量测试（`QT_QPA_PLATFORM=offscreen` 用于无头 Qt）
4. **版本一致性校验** — `scripts/check_version.py`
5. **Codecov** — 覆盖率上传
