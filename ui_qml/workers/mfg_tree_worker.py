"""可制造物品的分类树加载线程。"""

from PySide6.QtCore import QThread, Signal

from core.container import get_container


class MfgTreeW(QThread):
    """加载可制造物品市场分类树

    `done` 载 `(树 items, {product_type_id: market_group_id})`：分类树与
    「产物 → 分类」映射一次取回，调用方据此判断每个树节点在当前「类别」下
    有没有物品（没有就置灰）。

    ⚠️ 第二参的签名**必须是 `object`**：`Signal(list, dict)` / `Signal(list,
    "QVariantMap")` 都会经 Qt 的 `QVariantMap` 转换，而 **QVariantMap 的键只能是
    字符串** —— type_id 是 int，于是到达槽里时整个映射变成**空 dict**（实测：
    994 个树节点全部被误判成「空」而置灰，且 Qt 只在 stderr 打一行
    `Cannot copy-convert (dict) to C++`，不报错）。`object` 走 Python 对象，
    原样送达。
    """

    done = Signal(list, object)

    def run(self):
        repo = get_container().blueprint_repo
        items = repo.get_manufacturable_market_tree()
        ids = set(repo.get_all_product_ids("manufacturing")) | set(repo.get_all_product_ids("reaction"))
        self.done.emit(items, repo.get_product_market_groups(ids))
