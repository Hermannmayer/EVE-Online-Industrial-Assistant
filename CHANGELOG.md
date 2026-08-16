# 更新日志

本项目的版本遵循[语义化版本 2.0.0](https://semver.org/lang/zh-CN/)。`feat` 递增 MINOR（0.7.0 → 0.8.0），`fix`/`perf` 递增 PATCH（0.7.0 → 0.7.1），其余提交不触发发版；大版本（1.0.0 及以后）由发布者手动决定。

本文件是唯一更新日志源：发版时由 python-semantic-release 自动在版本列表标记处插入新版本段，无需手动维护。

<!-- version list -->

## v0.16.1 (2026-08-16)

### Bug Fixes

- Clear pre-commit debt left by refactor (format, mypy, docs)
  ([`3819680`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/38196803a9f8f4e13d7d98c8837a0550f5b14fee))


## v0.16.0 (2026-08-16)

### Bug Fixes

- Repair 16 tests and cancel semantics broken by recent refactor
  ([`1b95a62`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/1b95a628db179248b13aa037437125dec1585302))

### Chores

- Remove compat shims query_view/compare_dialog/inventory_view and update test imports
  ([`a29a57b`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/a29a57b9ec75380712e9a086776b8e348fd23255))

### Features

- Auto-backup user data before schema migration and version settings.json
  ([`5ef6e2b`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/5ef6e2b67cef634760cbdef6be637c057f5e4bf1))

### Refactoring

- Add APIClient.post and route remaining ESI calls through shared client
  ([`e9a7836`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/e9a783607402020a6326939737721d9e8ede7c7a))

- Converge all UI direct SQL into services/repositories and sync uv.lock version
  ([`8bb9f5f`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/8bb9f5f68753427b909192b78f3e3bb65670f7a1))

- Extract all-items market browser queries to services/market_browser_service.py
  ([`d3ce6d8`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/d3ce6d8a759da7ddeac94058e14af253848eecaa))

- Extract contract database queries to services/contract_service.py
  ([`8b69ca2`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/8b69ca2c47093c4e25b6e7eaa46be7536590d9c6))

- Extract implant data loading to services/implant_loader.py
  ([`17cb358`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/17cb358999f813e0d7aedac6f40aef6a32a0b380))

- Extract industry page workers to ui_pyside6/workers/industry_page_workers.py
  ([`ac50ec6`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/ac50ec68aa960371ef003fd761a2c034ab646d4c))

- Extract inventory clipboard parsing and market price batch to services
  ([`f4863bd`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/f4863bded4e4a9e57b9588ce2b58881737e1ca33))

- Extract main window navigation/page registration into MainWindowNavMixin
  ([`0f7c575`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/0f7c5754cd0811bc2659ac7f3003e4503e65894a))

- Extract main window price workers to ui_pyside6/workers/main_window_workers.py
  ([`8409324`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/840932473a8bc1871283a764e6344336421b6178))

- Extract procurement calculation to services/procurement_service.py
  ([`5f5f26c`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/5f5f26c25e792e87c19c8d733accaba1bbada936))

- Fix data integrity, concurrency, layering and tech debt from audit
  ([`812fade`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/812fade2cbd5085bd65c3109554a8dd5a2d7a48b))

- Further audit fixes for caches, packaging, hot reload, research cost, icons
  ([`2823b7e`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/2823b7ed312023b2c9727f446f6435b97ef5edf3))

- Improve QThread parent/strong references and use requestInterruption instead of quit
  ([`36ef5fb`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/36ef5fb0dc7cd71dd9252784766c93feb1b1b96b))

- Make core.container services imports lazy to reduce import-time coupling
  ([`ea0f5b5`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/ea0f5b5fe1962f3261c98312fc7856c687bc02b6))

- Migrate contract fetcher to shared APIClient with global rate limiting
  ([`b81626c`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/b81626ca6d6935770e57c91626bed594a355186e))

- Move DI container to bootstrap/ and keep core/container as compatibility shim
  ([`323925e`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/323925ea5a4c3750839e14bebf53f332e8d8b047))

- Move industry refresh type-id collection into plan_service
  ([`9ba1ee1`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/9ba1ee160c3fc0abb0c86c714e1eab2f73e3bad8))

- Move plan category colors from services to UI theme layer
  ([`f5b2c8a`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/f5b2c8a2c95bbab382ca6cf0add2f554cdac7caa))

- Move procurement loading and price snapshot saving into plan_service
  ([`f1eb530`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/f1eb530b196462201f87de593d8f1ef97e342f09))

- Move production plan loading into plan_service.load_plans
  ([`435bb7d`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/435bb7d2113cf1846c96f4cf96653aaaf28c07e7))

- Move refinable filtering into RefiningService
  ([`c8d1499`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/c8d1499ef4cf7ec3de6072224d6dc3e587420d95))

- Move scoring facade to services and eliminate services->application dependency
  ([`afd7a9b`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/afd7a9b94cb72cfd368fa1c46d42baef852252a2))

- Move system name lookup to name_resolver service for hangar settings
  ([`34a7247`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/34a7247f2e910493af885aa552a1b8c959b7fc00))

- Move targeted price refresh cache/save into services/price_refresh_service.py
  ([`6e0eca4`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/6e0eca4bfc4506f1d3282b3d95763a63dbc065e3))

- Point internal imports to new UI subpackages, reducing compat shim usage
  ([`140d5db`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/140d5db94ff0471ce7ddd7cb96685fca422f648d))

- Register price_snapshots DDL in schema_migrations user v10→v11 and remove UI DDL
  ([`5f07486`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/5f0748699a0d3d567804a1fb5daa8cb5546cd264))

- Remove dead application layer and align architecture docs
  ([`51618cf`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/51618cf68d825d5e1e749c6f1a310fa875895a58))

- Replace hardcoded UI colors with theme constants
  ([`56a79f7`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/56a79f7828278a9abe008af0a00bd77dbfed3c13))

- Replace industry page item search/blueprint check with repositories
  ([`0119f47`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/0119f47a4c3f7fd77671233f38b5c11255f9c7ce))

- Route child parallel and parent decompose updates through PlanRepository
  ([`288967c`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/288967c4723ce268b653d96b2ee213889a728e02))

- Split CharSettingsDialog pages/formulas into char_settings_common and char_settings_pages
  ([`fc8e1a3`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/fc8e1a332b1271c5318089cf26795d680c5ecd2c))

- Split PlanTable delegate and column constants into separate modules
  ([`fdb422b`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/fdb422b137f898316edb92119f81a601488a8250))

- Unify remaining production plan insert paths and add ESI limiter to contract/name calls
  ([`2c041d1`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/2c041d1135b1a24bab36e5dc79d547709145800e))

- Use blueprint repository in query search add-to-plan path
  ([`2e6a5e7`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/2e6a5e7739a08a2e564089f486385d86be6e898f))

- Use item repository for market tree queries in blueprint tab
  ([`683f8db`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/683f8db102ae22c4cf463e24577245c2eca3fdd2))

- Use item repository for score dialog titles
  ([`ce3036e`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/ce3036e883accc9e9e29d4174d45b2fe7c49d703))

- Use item repository in compare chart search/name helpers
  ([`6b3ac24`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/6b3ac249112a704364329f7376ec0241176b250e))

- Use item repository in inventory item search dialog
  ([`24f3592`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/24f359275e6e5ce6f417ca1485e0ae324b262911))

- Use item repository in watchlist suggestion worker
  ([`3b42486`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/3b424865a8f685f100f560c9d32439898056fd2d))

- Use market repository batch price query in blueprint tab
  ([`a3198e6`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/a3198e6fdf5fe585d56ded9cd7cbd1c411552cbd))

- Use market repository for main window price age query
  ([`92a8d3d`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/92a8d3da748a85d6fc9ea2e4f8d20fb51d2aae58))

- Use market repository in inventory review dialog price operations
  ([`560ecf2`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/560ecf275b37d0d0456783f75f4027bfd9f1128b))

- Use name resolver service in inventory page system name lookup
  ([`08fe92c`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/08fe92c40c5a5a8ac5230ddf6d658d52405225cd))

- Use repositories in batch price dialog queries
  ([`bf2b192`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/bf2b192e51fd74f8969ce487b40d82ef35995a36))

- Use repositories in hangar paste import dialog
  ([`a2b4243`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/a2b4243d681af0fbb04b32c4af87520549f4e0b1))


## v0.15.4 (2026-08-15)

### Performance Improvements

- 初始化全面提速 + 单实例锁健壮化 + dev.py 全新开箱模式
  ([`813b513`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/813b5133b351ebda80c1aaf5b8ef71f95c4a3c2e))


## v0.15.3 (2026-08-13)

### Bug Fixes

- Watchlist_manager _db 函数内 import get_container，避免 mock 污染测试
  ([`45450c5`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/45450c5f13df66da92dae5c28943f68d9dbc785d))

### Documentation

- 架构重构遗留项清单（4 项高风险/纯风格工作）
  ([`1f7a763`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/1f7a7638559a67ccc78ebfdace46851dc29e87f1))

### Refactoring

- 4a 拆 estimate_view + all_items_view — model/worker 抽到独立模块
  ([`9e69032`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/9e690323a6dd855aef4f3b3a6f4941396e2605f9))

- 4a 拆 hangar_tab — 4 个 dialog + 搜索 model 抽到 dialogs/hangar_dialogs
  ([`d282c4e`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/d282c4e746c82266a356b300ab5c0a5f125050ad))

- 4a 收尾 contract_view — workers + dialog 抽到独立模块
  ([`749cca6`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/749cca6abed334ecf847e4fa618cf249ab431189))

- 4a 第一步 — contract_view 的 3 个 model 抽到 contract_models
  ([`da516dd`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/da516dd2e9bfd6dae8beb6f283bbdb2831fc1798))

- 4b 下载器统一到 services/importers
  ([`5ccfbf9`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/5ccfbf9b788f6c5d28f64be39d15b97c2a959987))

- 4c 收尾 — 删除 4 个死代码 model（Rank/Material/Procurement/Production）
  ([`14e31ec`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/14e31ec330983c61390ca82f173ba3436d19ef3e))

- BOM 展开收敛 — 删死代码 + 抽 domain/bom.py walk_bom
  ([`a108851`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/a108851891a022764d0a25c83b172b16e2caffe3))

- Bom_expander/logistics DI 收敛到容器，修复 TransportWorker 坏调用
  ([`8b6b1ca`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/8b6b1ca15a05c8704b125086c5366fbb97cb3c77))

- 初始化提速与图标修复 + 文档站更新
  ([`fe0c2d6`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/fe0c2d66c815d7f02d74e7d0adc173cf6b5c9826))

- 架构审计修复与分层收敛
  ([`fc1eaa5`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/fc1eaa5bb2a36c3df59ac8236858ed2ddab74d3b))

- 模型/delegate 分层 — PlanTableModel 展示职责抽到 PlanTableDelegate（4c 第一步）
  ([`0ef9e4e`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/0ef9e4e9f0a45d06608ddc4863406d48c24467f8))

- 评分算法纯度化 — calc_manufacturing_score 抽到 domain/application 层
  ([`dc4d014`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/dc4d014a642a7a8022a9ee5402c9f766e6290b79))

- 评分算法纯度化 — 抽 calc_trade_score / calc_reaction_score 到 domain/application
  ([`1ab5f15`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/1ab5f156376818a42b52e48c18d01dc2b116264f))

### Testing

- 修复 ProductionWizard 测试访问真实库（worktree/CI 无 schema）
  ([`d9d0c4e`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/d9d0c4e7817a422db7f4db999b38101acb77c095))

- 精简测试 — 合并重复/删低价值构造测试 + fixture 优化省时
  ([`85e60ad`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/85e60ad8f17e2d40406974e359adb196f86b7a59))


## v0.15.2 (2026-08-06)

### Bug Fixes

- 生产计划 int 列排序崩溃（.lower() on int）
  ([`bba5ccb`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/bba5ccb55c23640ad75f55efa39f7b58f21c5eac))


## v0.15.1 (2026-08-05)

### Bug Fixes

- 批量重算 worker 单条计划计算失败容错，不再崩线程
  ([`01a814f`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/01a814fe636531d0e3068a7a5577232c20fdb679))

- 生产规划设施/输出列显示机库名 + SCI 过期自动刷新
  ([`8278cc7`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/8278cc7030c4dbe70d581e54ce7f9c88df283b57))

### Testing

- 阻止 UI 测试真实价格下载 + 自动清理 MainWindow 残留
  ([`f1b2047`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/f1b2047f7e89089a0d34eef98e4c75bfe4422321))


## v0.15.0 (2026-08-05)

### Bug Fixes

- Dev.py 热重载防连环重启 + 蓝图表连接修正 + schema 检查容错
  ([`6d7b3ea`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/6d7b3ea90e9acb5f6cd905ebcce6eea56194115a))

- 图标下载 — 400/404 确定性失败写 noicon，移除限流恢复 100 并发
  ([`ba2daa3`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/ba2daa3a9de054b1b3f50750fab309f80cecd614))

- 拆解母项子项按制造价计入成本 + 市场/个人利润率口径分离
  ([`1e2a413`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/1e2a413bb118bb529d1dc7318bf52842b4214a36))

- 母项拆解重跑整体刷新 runs/parallels + 预览加需求列
  ([`b5d6f95`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/b5d6f95be27d75ad96ec2da63a7feca3d245b327))

### Features

- 新增 setup_worktree.sh 快速初始化 worktree
  ([`af8c85b`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/af8c85b82d993f31e35cf16e635c0d2930ad8cd0))

### Performance Improvements

- 数据初始化下载加速 — 步骤并行调度 + reference.db 并发写锁 + 下载器优化
  ([`a190c2d`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/a190c2dae5a5c61bd52dfd3e1ea4964648d0121b))


## v0.14.2 (2026-08-04)

### Bug Fixes

- Dev.py 热重载链路修复 + 单实例锁防多开
  ([#6](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/pull/6),
  [`430673b`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/430673bb2a390890d28ef8d688d1b0011ef125e6))


## v0.14.1 (2026-08-04)

### Bug Fixes

- 修复 production_plans 缺 v2 扩展列 — 倒计时补算/建计划/完成入库 no such column
  ([`415398d`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/415398d10a2eaeda6155886af7e015136e8a790c))


## v0.14.0 (2026-08-03)

### Features

- 生产规划增强 — 智能调整多行、统计行新统计、流程列改序、自动勾选备料、删除级联子项并释放蓝图、待采购排除子项自制件、母项成本按子项制造价计个人利润、子项并行流程自动生成
  ([`b72c11c`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/b72c11c1d13b5422e0c2b44b89210232ab752030))


## v0.13.1 (2026-08-03)

### Bug Fixes

- 制造成本 SCI 按材料机库星系核算，修复空星系回退吉他
  ([`decba62`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/decba62c59568df3b69c86564b6722aa900992b6))


## v0.13.0 (2026-08-02)

### Features

- 蓝图批量加入制造规划 + 生产追踪增强 + 库存导入重构
  ([`3658494`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/3658494d7ea7b6a60487b109797c9f4c73682e2e))


## v0.11.0 (2026-08-01)

### Chores

- **docs**: 同步 API 文档 + README 测试数
  ([`273719c`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/273719c71c580bef35f8dfc3ae067c1475ac1e52))

### Features

- 生产计划执行服务层 — schema v3→v4、材料校验/扣减/返还、蓝图占用/消耗、启动/完成/撤销
  ([`af7f607`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/af7f6078ebc3a37160310053d2aedf9cc859a94e))

- 生产追踪 UI — 材料机库设置、倒计时、蓝图绑定弹窗、完成入库收敛、撤销启动、编辑机库去重
  ([`a344bc0`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/a344bc02526e9458cdd391045485984adef1dfe8))

### Testing

- 生产追踪测试 — 执行/倒计时/迁移/蓝图占用用例
  ([`d629aa6`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/d629aa6465033a1ec9fb3b5ca128735e405e9892))


## v0.10.0 (2026-08-01)

### Bug Fixes

- Schema 迁移加固 — 缺失表守卫跳过 + v0 库显式落盘版本号
  ([`df8d538`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/df8d538b8b990288ad2fa31efe63719566e7969c))

- UI 稳定性 — 主题 lambda 监听器强引用、非模态对话框 GC 引用、showEvent 异常兜底、子对话框传 parent
  ([`866c122`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/866c122e6adf5419308ba7852e9054c629a23531))

- 初始化流程优化 — check_all 单次轮询、网络检查缓存、inspect 签名检测 progress_cb、结束释放 YAML 缓存、schema 检查跳过不存在库
  ([`94fac59`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/94fac59348d43939c302b25a6d7ed0aef63a2fe6))

### Chores

- **docs**: 同步 API 文档 + README 测试数（663）
  ([`2c02420`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/2c02420b964478bbe34a4809f826f96ce4d86dbf))

### Features

- 下载器重构 — 植入体 dogma 改走 ESI 并发拉取、复用共享 SDE zip、ESI 名称并发补拉、进度回调上报
  ([`7cd5b17`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/7cd5b1727e5330ed9debe8414aeca0aad6f67619))

### Performance Improvements

- SDE 解析并行化 + YAML 进程内缓存 — universe to_thread 多线程解析、load_yaml 二次解析缓存、clear_yaml_cache 释放大文件内存
  ([`38af496`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/38af496d1684da2d98baf3071ccc65a087358b1c))


## v0.9.0 (2026-07-31)

### Features

- 顶栏/状态栏精简重构 — 价格年龄定时刷新、更新按钮拆分+区域持久化、去重状态栏、分档测试脚本
  ([`7c24921`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/7c249214657770fe9dd1231b262dfb1e1274dcad))


## v0.8.0 (2026-07-31)

### Bug Fixes

- 审计 P0 — 精炼查错表、迁移原子性、char_config 反依赖下沉
  ([`79e9128`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/79e9128c546580351d8c4c83702c9b6b5ae16505))

- 审计 P1 — 评分缓存接线、ESI 限流、费用差额计费、busy_timeout 等 10 项
  ([`71006bf`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/71006bf6d7c9b0d2b0df4f3b4a7b41ff84fe1565))

- 审计 P1 尾 — theme 监听器弱引用、fetch_time 索引、schema 迁移收敛、删 scheduler
  ([`79b93d2`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/79b93d254206dec892d7223cebc2f8220f2d8ed3))

### Chores

- Ruff 格式化存量文件（21 个历史未格式化文件清零）
  ([`2452e0a`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/2452e0a98731173845f249de5b6986d5daa210f3))

- 清理过期文档与残留文件（-1022 行）+ 修正引用
  ([`bb4909d`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/bb4909d7b81f1cd035b33382acce28605eff2246))

### Documentation

- 新增 2026-07-31 审计报告 — 4 P0 + 20 P1 问题清单与修复状态
  ([`49f7a1c`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/49f7a1c92059591d3011ce04c29b677e290dc6d3))

- 澄清材料浪费公式误报 + 防错机制落地（字段契约 + 金标准测试）
  ([`d410f58`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/d410f58220539d4b07c1a8f8f0b8c236965b087d))

### Features

- 文档联动机制 — 提交时自动生成 API 文档 + README/链接校验 + 变更提醒
  ([`e3015db`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/e3015dbf04e51f414a769df5fd7f99989599dd14))


## v0.7.0 (2026-07-31)

### Bug Fixes

- 补 blueprint_tab 蓝图函数 patch，修复 CI 主题监听测试
  ([`4cd4f7b`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/4cd4f7be9a1a2fb971140f3b3bebd3c5f527ca60))


## v0.6.0 (2026-07-31)

### Bug Fixes

- 补 hangar_tab 模块 patch，修复 CI 上 inventory 主题监听测试
  ([`452d74b`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/452d74b313a72d29b35489fddff8224b77962f1c))


## v0.5.0 (2026-07-31)

### Bug Fixes

- 修复 UI 测试依赖真实数据库目录导致 CI(Linux) 失败（patch blueprint_tab get_container）
  ([`d5e76f2`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/d5e76f210e4c4280743ce61683429e57f27dac92))


## v0.4.0 (2026-07-31)

### Bug Fixes

- 修复 test_init_check 依赖真实数据库路径导致 CI(Linux) 失败
  ([`4ad8c53`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/4ad8c53cace2241303dfc55e347253898252f1f0))

### Chores

- 修复 CHANGELOG 头部被 semantic-release 拆断的结构
  ([`a375571`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/a37557106c58c43ee95c58f8ad9c5efef9a052db))

### Continuous Integration

- 添加 libEGL/libGL 系统库解决 Linux 上 PySide6 导入失败
  ([`0655c94`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/0655c946e648914bc70b4e6d25f07921a18521f5))


## v0.3.0 (2026-07-31)

### Bug Fixes

- CI mypy 平台配置 + PyInstaller 依赖（解决 Linux CI 上 windll 报错与 release 打包缺依赖）
  ([`d61349a`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/d61349aab6eb61008f0f33b9384d240ad3d57bba))

### Chores

- 触发文档站部署（GitHub Pages 已启用）
  ([`c84a9eb`](https://github.com/Hermannmayer/EVE-Online-Industrial-Assistant/commit/c84a9eb46727943b30eeb34d564126c09240b230))

## v0.2.0 (2026-07-31)

### Added

- 语义化版本管理：新增 `core/version.py` 单一版本源；接入 python-semantic-release，push main 自动发版（解析 Conventional Commits → bump 版本 → 更新 CHANGELOG → 打 tag → 建 GitHub Release → 打包上传安装包）
- CI 版本一致性校验（`scripts/check_version.py`）：`core/version.py` / CHANGELOG 最新版本段 / git tag 三者不一致即阻断合并
- VitePress 中文文档站（`docs/`），函数级 API 参考自动生成（`scripts/gen_api_docs.py`），GitHub Actions 自动部署到 GitHub Pages

### Changed

- 依赖管理统一迁移到 uv：`uv sync --dev` 安装依赖；移除 `requirements.txt` 与全部 pip 安装路径
- `build_release.py` 版本号改为从 `core/version.py` 读取，不再硬编码
- 历史 1.x 版本段降级为归档记录（见下文「历史遗留」）

### Removed

- 移除 `build_release.py` 中已废弃的 pyperclip hidden-import（代码已改用 Qt `QApplication.clipboard()`）

## 历史遗留（v0.2.0 之前）

> 产品现处于 0.x 开发阶段。以下 1.x 版本段仅作归档，不代表当前版本状态。

### v1.4.0 (2026-07-27)

#### 架构重构

- IOC 容器化：`AppContainer` 统一管理 15+ 服务生命周期，消除模块级全局 DB 单例
- 新增 `core/cache.py`：`TtlLRUCache` 线程安全 LRU+TTL 缓存，替代旧 `ScoringCache`
- 新增 `services/repositories/`：4 个数据仓库（Item/Market/Blueprint/PlanRepository），封装跨库查询
- 新增 `services/pricing_service.py`：`PricingService` 统一定价 + 成交量 + 系统成本指数查询
- 新增 `services/char_config_resolver.py`：角色配置四源合并解析器
- 新增 `services/refining_service.py`：精炼价值计算独立服务
- 新增 `services/bom_expander.py BomExpander` / `services/logistics.py LogisticsService` 等 6 个可注入服务类
- `services/scoring_service.py` 瘦身：972 行 → 536 行，移除 437 行死代码（ScoringCache、模块级缓存函数、resolve_char_config、get_price 等迁移到新模块）

#### 安装费修复

- 安装费改为读取 ESI **adjusted_price**（7 日均价）计算 EIV，而非市场实时卖出价
- 系统成本指数（SCI）降级：`system_id=None` 时自动从 `sell_hub` 名称（Jita/Amarr等）查找对应太阳系 ID，使用真实 SCI 值
- 安装费 breakdown 按游戏类目拆分：`system_cost` / `facility_tax` / `scc_surcharge` / `installation_fee`

#### 材料损耗公式修正

- **关键修复**：SDE `blueprint_materials.quantity` 存储的是 **ME 0 实际用量**（已含基础浪费），旧代码当作「真实基础量」又加了一层浪费
- 新公式：`actual = ceil(db_qty × (1 + wf/100/(1+ME)) / (1 + wf/100) × 结构减免)`
- ME 0 时用量与游戏完全一致，ME 上升时逐步减少

#### 消费者迁移

- 4 个 UI Worker → 通过容器注入服务，不再模块级引用
- 8 个 UI View → 改用容器 + `TtlLRUCache`
- 2 个 Service 文件 → `PricingService` 替代模块级 `get_price`
- 6 个测试文件 → 更新 mock 路径与断言

#### 测试

- 653 测试全部通过，0 失败 0 错误
- 测试基础设施改进：`conftest.py` 修复 18 个 UI 测试 RuntimeError

#### 新功能

- 生产计划管理：计划表编辑、甘特图视图、多计划切换（Phase 3）
- 精炼计算：矿物精炼产出与效率计算（Phase 3）
- 设置对话框：应用设置集中管理界面（Phase 3）
- Universe 数据缓存：SDE 星系/空间站数据缓存加速（Phase 3）
- 甘特图主题：生产进度可视化与双主题适配（Phase 3）

#### Bug 修复

- 修复工业界面 5 个问题：SpinBox 重叠、ComboBox 主题/Hub 中文名、蓝图等级参与计算、角色技能读取、制造时长未生效
- 修复待采购弹窗图标/矿物名/窄高尺寸/InputDialog 关键字
- BSD YAML 列表格式 station 数据写入
- 状态栏显示具体哪项数据未初始化便于诊断
- 移除 universe 检查避免每次提示初始化
- SDE zip 文件名映射 + universe 路径解析 + operationServices 不存在修复

#### 性能优化

- SDE zip 共享缓存加速多 Worker 并行导入
- 全量 SDE 数据集成（三人团队并行实施）

#### 代码质量

- mypy 类型警告修复、测试基础设施改进
- 过滤 Qt 字体大小警告

### v1.2.0 (2026-07-01)

#### 新功能

- 价格走势图：订单弹窗→走势图按钮，历史价格趋势可视化（Wave 2）
- 批量导出 CSV/Excel：查询页、全物品浏览页均支持导出（Wave 0-1）
- 代采购管理：IndustryPage 新增第4Tab，管理代采购订单与供应商（Wave 3-4）
- 价格变化自动检测：关注列表 60s 定时器，自动检测价格变动并通知（Wave 3-4）
- 合同视图：查看和管理游戏内合同（Wave 6-7）
- 物流距离计算：自动计算并补全物流距离数据（Wave 6）
- 系统通知：集成系统桌面通知（Wave 7）

#### Bug 修复

- 修复启动时忽略自动更新设置的 bug
- 修复主题架构 — 从 `from import VAR` 改为 `import theme as module`
- 修复多项 UI 颜色与样式问题
- 数据库初始化流程修复

#### 代码质量

- 安全修复 + 依赖注入 + 测试基础设施重构（第一阶段）
- UI 拆分 + 依赖注入消除 + DB 清理（第二、三阶段）
- 配色规范化，双主题支持全面强化
- 项目结构清理：移除废弃文档、.vscode/、.github/、缓存文件
- 引入 ruff 作为统一 lint/format 工具（pyproject.toml 配置）
- 所有视图添加 `add_theme_listener` + `_on_theme_changed` 模式
- AGENTS.md 替代废弃的 PROMPT.md
- 设计文档精简为 4 篇核心文档

#### 测试

- 测试总数从约 50 增加到 204 个
- 新增测试文件：
  - `test_contract_view.py` — 492 行，合同视图功能测试
  - `test_logistics.py` — 537 行，物流距离计算测试
  - `test_watchlist_manager.py` — 285 行，关注列表与价格变化检测测试
  - `test_procurement.py` — 182 行，代采购管理测试
  - `test_price_history.py` — 180 行，价格走势图数据测试
  - `test_export_helper.py` — 104 行，批量导出测试
  - `test_scoring_core.py` — 评分核心逻辑测试
  - `test_theme_listeners.py` — 主题监听模式测试
  - `test_database_manager.py` — 数据库连接管理器测试
  - `test_paths.py` — 路径管理测试
- 新增 `conftest.py` 共享测试 fixtures
