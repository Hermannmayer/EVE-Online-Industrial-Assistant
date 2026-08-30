# core.diagnostics

> 源文件 `core/diagnostics.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

崩溃记录与环境信息采集 — 开发环境与发行版通用。

只依赖标准库，不依赖 Qt：弹窗等 UI 行为由 Main.py 持有；
本模块负责崩溃文件的落盘、后台线程异常兜底与 faulthandler 原生崩溃捕获。

## 函数

### `collect_env_info`

```python
def collect_env_info() -> dict[str, str]
```

采集运行环境信息，供崩溃转储表头与排障使用。

定义行：`19`

### `_exception_value`

```python
def _exception_value(exc_info) -> BaseException | None
```

兼容 (type, value, tb) 元组与裸异常对象两种入参。

定义行：`44`

### `write_crash_dump`

```python
def write_crash_dump(exc_info, crash_dir: Path | None=None) -> Path | None
```

写崩溃转储文件（环境信息表头 + traceback），返回文件路径；失败返回 None。

定义行：`56`

### `_thread_excepthook`

```python
def _thread_excepthook(args: threading.ExceptHookArgs) -> None
```

后台线程未捕获异常兜底：只记录落盘，不弹窗（避免阻塞 UI / 跨线程建窗）。

定义行：`84`

### `install_background_hooks`

```python
def install_background_hooks() -> None
```

安装后台诊断钩子：threading.excepthook + faulthandler。

定义行：`90`
