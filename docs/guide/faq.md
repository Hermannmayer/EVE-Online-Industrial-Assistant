# 常见问题

## 数据相关

### Q：首次启动后价格显示为空？

首次启动会自动从 ESI 拉取市场价格，通常需要 3-5 秒。如果网络不稳定：
1. 检查底部状态栏的更新状态
2. 点击状态栏的 🔄 更新按钮手动刷新
3. 通过 **设置 → 数据初始化** 重新拉取

### Q：蓝图数据从哪里来？

蓝图数据来自 CCP 官方 SDE（Static Data Export），首次启动时自动从 `https://sde.jita.space/latest` 下载并解析到 `blueprint.db`。

### Q：4 个数据库文件可以删除吗？

删除后应用会在下次启动时重新初始化：
- `reference.db` — 从 SDE 重建（物品、分类、成本指数）
- `market.db` — 从 ESI 重建（市场价格）
- `blueprint.db` — 从 SDE 重建（蓝图数据）
- `user.db` — **会丢失你的所有用户数据**（机库、库存、蓝图记录、生产计划）

> 建议只删除 `database/` 目录以完全重置，或只删除特定库文件。

## 制造相关

### Q：安装费（Installation Fee）如何计算？

安装费基于 ESI 的 **adjusted_price**（7 日均价）计算 EIV（Estimated Item Value），再乘以系统成本指数（SCI）：

- 系统成本指数（SCI）来自 ESI `industry/systems` 接口
- 当选定的 Hub 没有直接 SCI 数据时，自动从 Hub 名称查找对应太阳系 ID 作为降级
- 安装费按游戏类目拆分为：`system_cost` / `facility_tax` / `scc_surcharge` / `installation_fee`

### Q：材料损耗率怎么算？

公式考虑了蓝图 ME 级别和废品率（Waste Factor）：

```
实际用量 = ceil(数据库数量 × (1 + 废品率/100/(1+ME)) / (1 + 废品率/100) × 结构减免)
```

::: warning
SDE 中 `blueprint_materials.quantity` 存储的是 ME 0 时的实际用量（已含基础浪费），旧代码曾将其当作「真实基础量」又加了一层浪费，已在 v1.4.0 修复。
:::

### Q：个人利润率和普通利润率有什么区别？

- **普通利润率**：基于市场卖出价和材料市场买入价计算
- **个人利润率**：综合考虑库存成本（加权平均）和市场价，更准确反映你的实际收益

母项拆解子项后，子项自制件按**制造价**（材料 + 制造作业费）计入母项成本，而非市场买入价，
因此拆解后个人利润率通常显著高于普通（市场）利润率。

## 技术相关

### Q：支持哪些操作系统？

主开发平台为 Windows（打包为 EXE）。macOS 和 Linux 需从源码运行（需要 PySide6 及系统 Qt 库）。

### Q：如何更新到最新版本？

```bash
git pull origin main
uv sync --dev    # 更新依赖
python Main.py   # 重新启动
```

如果数据库 schema 有变更，应用会自动执行迁移。
