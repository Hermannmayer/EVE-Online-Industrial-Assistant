# ui_qml.workers.mfg_tree_worker

> 源文件 `ui_qml/workers/mfg_tree_worker.py` · 由 `scripts/gen_api_docs.py` 自动生成，请勿手改

> 模块说明：

可制造物品的分类树加载线程（原先在 `ui_pyside6/views/manufacturable_items_dialog.py`）。

## 类

### `class MfgTreeW`（继承 `QThread`）

加载可制造物品市场分类树

`done` 载 `(树 items, &#123;product_type_id: market_group_id&#125;)`：分类树与
「产物 → 分类」映射一次取回，调用方据此判断每个树节点在当前「类别」下
有没有物品（没有就置灰）。

⚠️ 第二参的签名**必须是 `object`**：`Signal(list, dict)` / `Signal(list,
"QVariantMap")` 都会经 Qt 的 `QVariantMap` 转换，而 **QVariantMap 的键只能是
字符串** —— type_id 是 int，于是到达槽里时整个映射变成**空 dict**（实测：
994 个树节点全部被误判成「空」而置灰，且 Qt 只在 stderr 打一行
`Cannot copy-convert (dict) to C++`，不报错）。`object` 走 Python 对象，
原样送达。

定义行：`8`

#### 方法

##### `run`

```python
def run(self)
```

::: warning ⚠️ 待补 docstring
此函数暂无 docstring，欢迎补充。
:::

定义行：`25`
