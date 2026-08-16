# ui_pyside6.workers.startup_worker

> 源文件 `ui_pyside6/workers/startup_worker.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

启动后台检查 Worker — 迁移 + schema + 数据就绪，信号上报 SplashScreen。

## 类

### `class StartupCheckWorker`（继承 `QThread`）

后台顺序执行迁移与数据检查，逐步上报进度。

定义行：`12`

#### 方法

##### `run`

```python
def run(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`19`
##### `_run_migrations`

```python
def _run_migrations(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`33`
##### `_check_data`

```python
def _check_data(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`44`
