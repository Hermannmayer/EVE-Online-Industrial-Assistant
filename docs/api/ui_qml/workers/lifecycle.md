# ui_qml.workers.lifecycle

> 源文件 `ui_qml/workers/lifecycle.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

后台线程收尾 —— 「QThread 在运行中被析构会让 Qt 直接 abort()」的统一兜底。

本仓真实崩过（退出码 127，`ui_snapshot.py --dialog contract_detail` 可复现）。
各桥原先各自内联实现这段收尾逻辑（5 处逐字重复的 `_DETACHED` + 3 个 `stop()`），
这里汇总成一份。

两种语义，按**等不等得到**选：

- `drop_worker(worker)` —— 等满 `wait_ms` 仍没结束才摘出去保活。用于 `run()` 会查
  中断标志、正常远小于超时的 worker（如评分线程）。
- `detach_worker(worker)` —— 超时短、`cancel()` 对阻塞式 ESI 请求无效时用，语义是
  「中断不了就别让它随对话框一起销毁」。

`_DETACHED` 必须是模块级强引用：线程被摘出对话树后若没人持有，`QThread` 的析构
就会在中止进程。线程自己 `finished` 后从集合里放掉。

## 函数

### `_detach`

```python
def _detach(worker: Any) -> None
```

把 worker 摘出对话树并挂到模块级集合上保活。

定义行：`33`

### `drop_worker`

```python
def drop_worker(worker: Any, *, cancel: bool=False, wait_ms: int=DEFAULT_WAIT_MS) -> None
```

停掉后台线程；超时就摘出对话树保活。

定义行：`40`

### `detach_worker`

```python
def detach_worker(worker: Any) -> None
```

中断不了就直接保活（阻塞式请求专用）。

定义行：`58`
