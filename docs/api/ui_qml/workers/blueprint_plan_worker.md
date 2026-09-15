# ui_qml.workers.blueprint_plan_worker

> 源文件 `ui_qml/workers/blueprint_plan_worker.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

蓝图批量加入规划时的派生指标计算线程。

原先在 `ui_pyside6/views/inventory/blueprint_tab.py`。

## 类

### `class _BulkPlanMetricsWorker`（继承 `QThread`）

后台批量计算各组合并后的派生指标（评分较重，避免卡死 UI）。

定义行：`9`

#### 方法

##### `__init__`

```python
def __init__(self, group_items: list[list[dict]], product_name: str, char_name: str, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`14`
##### `run`

```python
def run(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`20`
