# core.logger

> 源文件 `core/logger.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

结构化日志模块 — 统一日志输出

用法:
    from core.logger import log
    log.info("消息")
    log.warning("警告")
    log.error("错误")
    log.debug("调试")

## 函数

### `set_debug`

```python
def set_debug(enabled: bool=True)
```

切换 debug 模式

定义行：`79`

### `prune_logs`

```python
def prune_logs(logs_dir: Path, crashes_dir: Path, retention_days: int=14) -> int
```

删除超过 retention_days 天的日志与崩溃转储文件，返回删除数量。

定义行：`87`

## 类

### `class _Logger`

轻量日志封装 — 控制台输出 + 文件日志

定义行：`25`

#### 方法

##### `__init__`

```python
def __init__(self, name: str='eve-assistant')
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`28`
##### `info`

```python
def info(self, msg: str, *args, **kwargs)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`57`
##### `warning`

```python
def warning(self, msg: str, *args, **kwargs)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`60`
##### `error`

```python
def error(self, msg: str, *args, **kwargs)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`63`
##### `debug`

```python
def debug(self, msg: str, *args, **kwargs)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`66`
##### `critical`

```python
def critical(self, msg: str, *args, **kwargs)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`69`
##### `exception`

```python
def exception(self, msg: str, *args, **kwargs)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`72`
