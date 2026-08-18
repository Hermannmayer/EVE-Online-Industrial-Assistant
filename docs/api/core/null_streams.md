# core.null_streams

> 源文件 `core/null_streams.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

无控制台（--windowed）GUI 下的标准流兜底。

## 函数

### `ensure_console_streams`

```python
def ensure_console_streams() -> None
```

把 None 的 sys.stdout / sys.stderr 替换为 NullWriter。

定义行：`31`

## 类

### `class NullWriter`

静默丢弃所有写入的“黑洞”流，提供 write/flush/isatty 以兼容 io 协议。

定义行：`15`

#### 方法

##### `write`

```python
def write(self, s) -> int
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`18`
##### `flush`

```python
def flush(self) -> None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`21`
##### `isatty`

```python
def isatty(self) -> bool
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`24`
##### `writelines`

```python
def writelines(self, lines) -> None
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`27`
