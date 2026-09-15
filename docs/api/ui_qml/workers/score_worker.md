# ui_qml.workers.score_worker

> 源文件 `ui_qml/workers/score_worker.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

评分线程 `ScoreW`（原先在 `ui_pyside6/views/score_dialogs.py`）。

QML 侧（全物品页 / 可制造页）与 Widgets 对话框共用这一份。

## 类

### `class ScoreW`（继承 `BaseBatchScoreWorker`）

::: warning ⚠️ 待补 docstring
此类暂无 docstring，欢迎补充。
:::

定义行：`19`

#### 方法

##### `__init__`

```python
def __init__(self, items, is_mfg, cfg, parent=None)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`23`
##### `run`

```python
def run(self)
```

ScoreW 自定义 run：预加载市场数据，迭代 _calc_item 并 emit done(list)

定义行：`30`
##### `_calc_item`

```python
def _calc_item(self, row) -> dict
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`60`
