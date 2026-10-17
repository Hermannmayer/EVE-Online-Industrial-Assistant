"""大盘指数计算服务 —— 五个指数（MPI/PPPI/SPPI/CPI/PLEX）的计算与官方篮子映射。

篮子口径来源（官方）
--------------------
五个指数的名字对应 **CCP 官方 Monthly Economic Report（MER）** 的四条价格指数 + PLEX 锚。
MER 新闻页（https://www.eveonline.com/news/view/monthly-economic-report-september-2026）发布的
原始数据包里有 `data/index_baskets.csv` —— **官方逐 type 级成员清单**（列：
`type_id, type_name, category_id, category_name, group_id, group_name, primary_index, sub_index`；
四个指数合计 18,869 个 type），以及 `data/economy_indices_details.csv`（官方 2003-11 起的指数序列）。
本次实现采用的快照：**MER 2026-09 数据包**
（`https://monthly-economic-report.s3.eu-west-1.amazonaws.com/EVEOnline_MER_202609.zip`，
包 Last-Modified 2026-10-12，2026-10-17 下载核对）。官方从 2026-06 起的 MER 数据包包含这份成员
清单（2026-06 / 2026-09 有；2025-12 没有）；更早的官方口径只散见于 2011~2012 年的
「Price Indices」dev blog（四指数定义）与已下线的 Evelopedia「Market Indices」页。

官方清单是 **type 级**的；本地 SDE 只有 `reference.db.item.market_group_id`。两者高度对齐：
1,529 个市场分组一对一映射到某个指数（压缩成 :data:`MER_MARKET_GROUP_RANGES` 连续区间表，
导入时展开为 :data:`MER_MARKET_GROUP_INDEX`）；剩余的对齐差异全部显式列成 type 例外
（:data:`MER_TYPE_OVERRIDES` 补官方成员、:data:`MER_TYPE_EXCLUDED` 去掉规则误收的本地 type）。
用这份映射在真实 SDE 上复算：官方 18,411 个「本地 SDE 里也有的」成员 **0 个判错、0 个漏判**，
规则会多收的 174 个本地 type 已全部显式排除。

五条线
------
==================  ==========================================================================
``mpi``             官方 Mineral Price Index：固定 8 种矿物（:data:`MPI_TYPES`，与 MER 清单逐 type 核对一致）
``pppi``            官方 Primary Producer Price Index 篮子（矿石/月矿/行星产物/发明用品等 19 个 sub_index）
``sppi``            官方 Secondary Producer Price Index 篮子（T2 组件/打捞物/蓝图/增效体等 18 个 sub_index）
``cpi``             官方 Consumer Price Index 篮子（14,483 个 type、38 个 sub_index —— 不再是成交额 top-N 代理）
``plex``            固定 44992（ISK 锚），序列取自官方 Global PLEX Market（region 19000001）
==================  ==========================================================================

算法（不随篮子口径改动）
------------------------
1. **准入**：近 :data:`REBALANCE_DAYS` 个日历天成交额 > :data:`MIN_TURNOVER_ISK`（即 >0）
   **且**覆盖天数 ≥ :data:`MIN_COVERED_DAYS`。不满足的成员当日不参与（权重 0）。
2. **单成分日收益**：`当日成交均价 ÷ 该成员此前最近一次成交均价 − 1`；参考价间隔超过
   :data:`RETURN_GAP_DAYS` 天视为「已不是日收益」→ 当日不参与。再按 :data:`RETURN_CLAMP`
   截断 ±20%（超出按 ±20% 计）。
3. **成分内聚合**：参与成员的**加权中位数**（不是均值 —— 抗单笔异常）。权重见第 4 条。
4. **权重**：该成员**当日**往前 :data:`REBALANCE_DAYS` 个日历天的成交额（`volume × average`），
   经 :data:`WEIGHT_CAP`（25%）单成分上限后按合计归一化 —— 30 天滚动再平衡。
5. **逐日累乘**：基期 = 首个可算日 = :data:`BASE_VALUE`（100），之后
   `I_t = I_{t-1} × (1 + 当日加权中位数收益)`。成分换入换出只改变「当日参与集合与权重」，
   **不重设基期**，所以成分变更日天然不跳变（链式拼接）。

口径备注
--------
- **成员集合 = 官方 MER 篮子**（:func:`official_index_members`）：MPI 固定 8 矿；
  PPPI/SPPI/CPI 由官方 type 清单经 `market_group_id` 映射得到；PLEX 固定。
  异动榜（`services.market_movers_service`）复用同一份集合，两页不会口径分叉。
- **固定指数不因准入阈值掉成员**：MPI/PLEX 的成员表恒为固定集合（不满足准入的权重记 0）；
  PPPI/SPPI/CPI 的成员表只列当日有正权重的成员。
- 价格口径：本模块只用 **成交均价**（`market.db.price_history.average`），**不用挂单价** ——
  一个人挂/撤单就能推动挂单价。
- **`days` 字段** = 该指数已算出的点数（`points` 长度），`base_date` = 首个点日期。
- **数据不足一律 `None`**（不用 0 冒充）：少于 2 个点 → `value`/涨跌全 `None`；
  涨跌窗口没有覆盖到对应日历天 → 该窗口 `None`。

物化缓存
--------
:func:`refresh_index_daily` 把五个指数的逐日点位写进 `market.db.market_index_daily`
（market.db 是可重建缓存，故 DDL 直接建表、不走 `schema_migrations`，同 `price_history` 先例）。
表的 `type_id` 列存的是指数的**保留负数 id**（:data:`INDEX_TYPE_IDS`，真实 EVE type_id 恒为正），
`price` = 指数点位，`volume` = 当日成员成交额；`get_index_cards` / `get_index_series`
优先读这张表，表里没有该指数时退化为实时计算（不写库）。

大盘页要「卡片 + 序列」两样：用 :func:`get_dashboard` 一次算完（成分集 / 观测装载 / 逐日累乘
只跑一遍），不要分别调那两个函数 —— 那会把同一套计算整跑两遍。

进程内缓存
----------
物化表只负责「点位」，成员表/权重/成员价格每次仍要从 `price_history` 装载 ~74 万行重算
（真实库一次约 1.9s）。故三个公开读接口还有一层**进程内短 TTL 缓存**
（:data:`INDEX_MEMO_TTL_S`，键 = 函数名 + 区域 + keys + 锚定日）：命中时返回
`copy.deepcopy`，调用方原地改返回值不会污染缓存；``_db`` 显式注入（测试/特殊调用）不走缓存，
避免同一进程里不同库串数据。:func:`refresh_index_daily` 成功与
:func:`clear_index_memory_cache` 都会清空它。
"""

from __future__ import annotations

import copy
import logging
import threading
import time
from collections.abc import Hashable, Iterable, Mapping, Sequence
from datetime import date, timedelta
from typing import Any, NamedTuple, cast

from services.database_manager import get_db

log = logging.getLogger(__name__)

#: Jita（The Forge）—— 目前唯一历史天数够长的中心（计划 §6 风险表）
JITA_RID = 10000002

#: 进程内短 TTL 缓存（秒）。切页/重开大盘时同一 (区域, keys, 锚定日) 直接返回深拷贝，
#: 不再重算「官方成员表 + 74 万行观测装载 + 逐成员价格/涨幅」；`refresh_index_daily()`
#: 成功后会立即清空，价格导入等其它写路径最迟 TTL 后自然失效。
INDEX_MEMO_TTL_S = 600.0

INDEX_KEYS: tuple[str, ...] = ("mpi", "pppi", "sppi", "cpi", "plex")

INDEX_LABELS: dict[str, str] = {
    "mpi": "矿物指数 (MPI)",
    "pppi": "初级投入品 (PPPI)",
    "sppi": "次级投入品 (SPPI)",
    "cpi": "消费品 (CPI)",
    "plex": "PLEX (全服统一价)",
}

#: 物化表里「指数本身」用的保留 `type_id`。真实 EVE type_id 恒为正数，这里用负数区分合成行。
INDEX_TYPE_IDS: dict[str, int] = {"mpi": -1, "pppi": -2, "sppi": -3, "cpi": -4, "plex": -5}

#: MPI 固定 8 矿（与 CCP MPI 完全一致）
MPI_TYPES: tuple[int, ...] = (34, 35, 36, 37, 38, 39, 40, 11399)

#: PLEX 锚
PLEX_TYPE_ID = 44992

#: PLEX 的官方成交市场：**Global PLEX Market**（region `19000001`，官方名 `GPMR-01`）。
#: 依据 CCP dev blog 2025-07-04（https://developers.eveonline.com/blog/global-plex-market-and-sde-updates）：
#: PLEX 自 2025-07-07 起全服统一交易，`/markets/19000001/history/?type_id=44992` 就是它的权威日线
#: （2026-10-11 实测 200、404 条、2025-09-01 ~ 2026-10-09，**每行带 volume / order_count**）；
#: 4 个贸易中心的同一端点对它恒返回空（实测 `[]`）。
#: 这里**故意重复**定义而不是从 `services.importers.getprices` 导入：那个包的 `__init__.py`
#: 会把全部下载器（SDE / 图标 / 合同…）一并拉进来，而本模块在 UI 启动路径上、只该是轻量读端。
PLEX_REGION_ID = 19000001

#: 篮子来源：CCP 官方 MER 的逐 type 成员清单（见模块 docstring）。
#: 重新生成流程：下载 `EVEOnline_MER_<YYYYMM>.zip` → 取 `data/index_baskets.csv` → 用
#: `type_id ↔ reference.db.item.market_group_id` 做「单指数市场分组 → 连续区间」
#: + 「区间覆盖不到的官方成员 / 区间会误收的本地 type」两份例外清单。
MER_BASKET_SOURCE = "CCP Monthly Economic Report 2026-09 · data/index_baskets.csv"
#: 官方数据包地址（本次快照；换新月份只改月份号即可下载）
MER_BASKET_URL = "https://monthly-economic-report.s3.eu-west-1.amazonaws.com/EVEOnline_MER_202609.zip"
#: 官方数据包下载核对日期
MER_BASKET_CHECKED_AT = "2026-10-17"

# fmt: off
#: 官方成员清单 → `market_group_id` 的映射：**单指数市场分组的连续区间**（1,529 个市场分组 / 466 段）。
#: 区间左闭右闭（市场分组 id，不是 type_id）；同一市场分组内官方分属多个指数的情况
#: 不在这里，走 :data:`MER_TYPE_OVERRIDES`。
MER_MARKET_GROUP_RANGES: tuple[tuple[int, int, str], ...] = (
    (22, 22, "sppi"), (61, 61, "cpi"), (64, 64, "cpi"), (72, 85, "cpi"),
    (102, 103, "cpi"), (105, 109, "cpi"), (112, 113, "cpi"), (116, 116, "cpi"),
    (126, 126, "cpi"), (131, 131, "cpi"), (139, 139, "cpi"), (158, 158, "cpi"),
    (261, 261, "sppi"), (264, 264, "sppi"), (272, 285, "sppi"), (289, 293, "sppi"),
    (295, 298, "sppi"), (302, 303, "sppi"), (305, 309, "sppi"), (312, 313, "sppi"),
    (315, 316, "sppi"), (318, 318, "sppi"), (320, 320, "sppi"), (325, 325, "sppi"),
    (331, 332, "sppi"), (335, 335, "sppi"), (338, 341, "sppi"), (343, 343, "sppi"),
    (358, 359, "sppi"), (364, 370, "cpi"), (372, 378, "cpi"), (380, 383, "cpi"),
    (390, 390, "sppi"), (393, 396, "cpi"), (400, 403, "cpi"), (405, 405, "cpi"),
    (407, 407, "sppi"), (410, 413, "sppi"), (415, 418, "sppi"), (421, 424, "cpi"),
    (425, 425, "sppi"), (427, 430, "sppi"), (433, 436, "cpi"), (438, 441, "cpi"),
    (443, 446, "sppi"), (449, 452, "cpi"), (454, 457, "sppi"), (459, 459, "sppi"),
    (461, 463, "sppi"), (465, 468, "cpi"), (470, 473, "cpi"), (478, 479, "cpi"),
    (481, 485, "cpi"), (488, 488, "cpi"), (490, 491, "cpi"), (494, 494, "cpi"),
    (497, 497, "sppi"), (499, 501, "pppi"), (502, 504, "cpi"), (506, 506, "cpi"),
    (512, 512, "pppi"), (514, 519, "pppi"), (521, 523, "pppi"), (525, 530, "pppi"),
    (542, 542, "cpi"), (561, 570, "cpi"), (572, 579, "cpi"), (583, 586, "sppi"),
    (589, 592, "sppi"), (594, 596, "cpi"), (597, 599, "sppi"), (600, 603, "cpi"),
    (605, 606, "cpi"), (608, 615, "cpi"), (617, 617, "sppi"), (618, 622, "cpi"),
    (630, 633, "cpi"), (635, 638, "sppi"), (639, 648, "cpi"), (658, 660, "cpi"),
    (665, 667, "cpi"), (669, 673, "cpi"), (675, 676, "cpi"), (678, 680, "cpi"),
    (683, 683, "cpi"), (687, 708, "cpi"), (711, 719, "cpi"), (730, 737, "cpi"),
    (738, 738, "sppi"), (740, 750, "cpi"), (752, 752, "sppi"), (757, 757, "cpi"),
    (762, 765, "cpi"), (767, 778, "cpi"), (781, 781, "sppi"), (783, 786, "sppi"),
    (788, 794, "sppi"), (796, 796, "pppi"), (799, 799, "sppi"), (801, 801, "cpi"),
    (802, 803, "sppi"), (813, 816, "cpi"), (818, 821, "cpi"), (825, 843, "cpi"),
    (854, 872, "cpi"), (874, 874, "cpi"), (884, 905, "sppi"), (910, 911, "cpi"),
    (913, 913, "sppi"), (914, 914, "cpi"), (917, 933, "cpi"), (935, 935, "cpi"),
    (937, 937, "sppi"), (938, 938, "cpi"), (939, 939, "sppi"), (940, 940, "cpi"),
    (967, 967, "cpi"), (971, 974, "cpi"), (975, 975, "sppi"), (983, 983, "sppi"),
    (987, 989, "cpi"), (991, 993, "cpi"), (995, 1004, "cpi"), (1006, 1007, "cpi"),
    (1008, 1008, "sppi"), (1009, 1015, "cpi"), (1016, 1016, "sppi"), (1019, 1019, "sppi"),
    (1028, 1030, "sppi"), (1033, 1033, "cpi"), (1037, 1040, "cpi"), (1046, 1046, "sppi"),
    (1048, 1063, "cpi"), (1066, 1069, "cpi"), (1071, 1074, "cpi"), (1076, 1079, "cpi"),
    (1081, 1088, "cpi"), (1090, 1094, "cpi"), (1103, 1103, "cpi"), (1105, 1105, "sppi"),
    (1110, 1110, "cpi"), (1122, 1137, "cpi"), (1139, 1142, "cpi"), (1147, 1147, "sppi"),
    (1191, 1191, "pppi"), (1192, 1197, "cpi"), (1198, 1198, "sppi"), (1199, 1201, "cpi"),
    (1202, 1204, "sppi"), (1206, 1208, "cpi"), (1210, 1215, "cpi"), (1219, 1239, "cpi"),
    (1240, 1245, "sppi"), (1249, 1269, "sppi"), (1273, 1273, "cpi"), (1275, 1275, "cpi"),
    (1282, 1284, "cpi"), (1286, 1286, "sppi"), (1287, 1287, "cpi"), (1310, 1310, "cpi"),
    (1313, 1313, "sppi"), (1317, 1317, "cpi"), (1322, 1323, "cpi"), (1333, 1333, "pppi"),
    (1337, 1337, "sppi"), (1339, 1339, "sppi"), (1341, 1341, "sppi"), (1344, 1345, "sppi"),
    (1347, 1350, "sppi"), (1354, 1354, "sppi"), (1356, 1356, "sppi"), (1358, 1358, "sppi"),
    (1365, 1366, "cpi"), (1370, 1371, "cpi"), (1379, 1380, "cpi"), (1389, 1389, "sppi"),
    (1390, 1390, "cpi"), (1392, 1392, "cpi"), (1398, 1401, "cpi"), (1403, 1406, "cpi"),
    (1408, 1408, "cpi"), (1410, 1410, "cpi"), (1416, 1416, "cpi"), (1426, 1426, "cpi"),
    (1480, 1486, "cpi"), (1489, 1502, "cpi"), (1504, 1509, "cpi"), (1512, 1518, "cpi"),
    (1521, 1521, "sppi"), (1525, 1529, "sppi"), (1531, 1533, "sppi"), (1535, 1544, "sppi"),
    (1547, 1565, "sppi"), (1567, 1568, "sppi"), (1570, 1572, "sppi"), (1574, 1574, "sppi"),
    (1576, 1576, "sppi"), (1579, 1582, "sppi"), (1584, 1586, "sppi"), (1587, 1590, "pppi"),
    (1592, 1595, "pppi"), (1614, 1614, "cpi"), (1616, 1616, "cpi"), (1617, 1617, "sppi"),
    (1618, 1621, "cpi"), (1623, 1624, "cpi"), (1631, 1631, "cpi"), (1633, 1633, "cpi"),
    (1640, 1642, "cpi"), (1643, 1643, "sppi"), (1646, 1646, "cpi"), (1650, 1653, "cpi"),
    (1657, 1658, "cpi"), (1662, 1663, "cpi"), (1664, 1664, "sppi"), (1665, 1670, "cpi"),
    (1672, 1676, "cpi"), (1678, 1696, "cpi"), (1698, 1700, "cpi"), (1701, 1701, "sppi"),
    (1702, 1702, "cpi"), (1704, 1704, "cpi"), (1707, 1707, "sppi"), (1709, 1709, "cpi"),
    (1712, 1712, "sppi"), (1715, 1715, "cpi"), (1716, 1716, "sppi"), (1717, 1718, "cpi"),
    (1719, 1721, "sppi"), (1723, 1729, "sppi"), (1730, 1737, "cpi"), (1739, 1740, "cpi"),
    (1745, 1748, "cpi"), (1765, 1777, "cpi"), (1782, 1793, "cpi"), (1797, 1809, "sppi"),
    (1812, 1814, "cpi"), (1816, 1819, "cpi"), (1822, 1824, "cpi"), (1827, 1827, "cpi"),
    (1828, 1830, "sppi"), (1831, 1833, "cpi"), (1835, 1838, "cpi"), (1842, 1843, "sppi"),
    (1844, 1845, "cpi"), (1847, 1847, "cpi"), (1855, 1856, "pppi"), (1858, 1859, "sppi"),
    (1860, 1860, "pppi"), (1870, 1870, "cpi"), (1873, 1873, "pppi"), (1880, 1880, "pppi"),
    (1884, 1889, "sppi"), (1898, 1906, "sppi"), (1907, 1909, "pppi"), (1913, 1913, "pppi"),
    (1918, 1919, "pppi"), (1920, 1920, "sppi"), (1921, 1921, "cpi"), (1924, 1924, "cpi"),
    (1931, 1932, "cpi"), (1935, 1937, "cpi"), (1938, 1940, "sppi"), (1941, 1944, "cpi"),
    (1949, 1949, "sppi"), (1950, 1950, "cpi"), (1952, 1954, "cpi"), (1956, 1959, "cpi"),
    (1963, 1967, "cpi"), (1969, 1969, "cpi"), (1974, 1987, "cpi"), (1990, 1997, "cpi"),
    (2000, 2000, "cpi"), (2002, 2005, "cpi"), (2007, 2010, "cpi"), (2012, 2012, "cpi"),
    (2014, 2014, "sppi"), (2016, 2017, "sppi"), (2018, 2018, "cpi"), (2020, 2020, "sppi"),
    (2021, 2021, "cpi"), (2024, 2027, "cpi"), (2030, 2034, "cpi"), (2038, 2041, "cpi"),
    (2047, 2063, "cpi"), (2069, 2084, "cpi"), (2088, 2093, "cpi"), (2095, 2098, "cpi"),
    (2103, 2108, "cpi"), (2110, 2113, "cpi"), (2115, 2115, "cpi"), (2120, 2120, "cpi"),
    (2126, 2126, "cpi"), (2131, 2133, "cpi"), (2134, 2134, "sppi"), (2135, 2135, "cpi"),
    (2137, 2140, "cpi"), (2142, 2145, "cpi"), (2147, 2152, "cpi"), (2153, 2153, "sppi"),
    (2154, 2154, "cpi"), (2156, 2156, "sppi"), (2159, 2160, "sppi"), (2167, 2177, "sppi"),
    (2180, 2186, "sppi"), (2188, 2193, "sppi"), (2196, 2198, "cpi"), (2200, 2201, "cpi"),
    (2211, 2216, "cpi"), (2218, 2224, "cpi"), (2228, 2235, "cpi"), (2238, 2238, "sppi"),
    (2239, 2247, "cpi"), (2248, 2248, "sppi"), (2249, 2261, "cpi"), (2263, 2266, "sppi"),
    (2267, 2270, "cpi"), (2272, 2276, "cpi"), (2278, 2281, "cpi"), (2285, 2285, "cpi"),
    (2287, 2287, "cpi"), (2291, 2295, "sppi"), (2298, 2302, "cpi"), (2308, 2308, "cpi"),
    (2310, 2310, "cpi"), (2312, 2312, "cpi"), (2314, 2314, "cpi"), (2316, 2316, "cpi"),
    (2318, 2321, "cpi"), (2322, 2323, "sppi"), (2324, 2325, "cpi"), (2327, 2328, "cpi"),
    (2331, 2332, "cpi"), (2334, 2334, "sppi"), (2336, 2336, "cpi"), (2338, 2338, "cpi"),
    (2339, 2339, "sppi"), (2341, 2351, "cpi"), (2353, 2357, "cpi"), (2360, 2362, "cpi"),
    (2370, 2373, "cpi"), (2376, 2376, "cpi"), (2380, 2380, "cpi"), (2383, 2383, "cpi"),
    (2387, 2392, "cpi"), (2393, 2393, "sppi"), (2396, 2398, "pppi"), (2400, 2404, "pppi"),
    (2406, 2406, "cpi"), (2407, 2407, "sppi"), (2408, 2408, "cpi"), (2411, 2414, "cpi"),
    (2415, 2415, "sppi"), (2417, 2417, "cpi"), (2419, 2419, "cpi"), (2421, 2421, "cpi"),
    (2426, 2426, "cpi"), (2428, 2428, "cpi"), (2430, 2430, "cpi"), (2433, 2435, "cpi"),
    (2441, 2455, "sppi"), (2457, 2461, "cpi"), (2465, 2471, "cpi"), (2475, 2478, "cpi"),
    (2480, 2480, "cpi"), (2482, 2482, "cpi"), (2485, 2487, "cpi"), (2491, 2501, "cpi"),
    (2503, 2506, "cpi"), (2508, 2508, "sppi"), (2509, 2509, "cpi"), (2510, 2510, "sppi"),
    (2511, 2511, "cpi"), (2513, 2517, "sppi"), (2519, 2519, "cpi"), (2521, 2521, "cpi"),
    (2523, 2523, "cpi"), (2525, 2526, "cpi"), (2529, 2529, "cpi"), (2531, 2531, "cpi"),
    (2533, 2534, "sppi"), (2535, 2537, "cpi"), (2538, 2540, "pppi"), (2658, 2658, "sppi"),
    (2690, 2692, "cpi"), (2693, 2693, "sppi"), (2701, 2702, "cpi"), (2704, 2704, "cpi"),
    (2706, 2706, "cpi"), (2734, 2740, "cpi"), (2742, 2744, "cpi"), (2749, 2749, "cpi"),
    (2750, 2754, "sppi"), (2756, 2757, "cpi"), (2760, 2761, "cpi"), (2763, 2763, "cpi"),
    (2764, 2764, "sppi"), (2765, 2765, "pppi"), (2766, 2766, "sppi"), (2767, 2767, "pppi"),
    (2768, 2768, "sppi"), (2769, 2770, "pppi"), (2771, 2771, "cpi"), (2772, 2772, "sppi"),
    (2783, 2783, "cpi"), (2795, 2795, "cpi"), (2797, 2797, "sppi"), (2798, 2798, "cpi"),
    (2801, 2801, "cpi"), (2804, 2805, "cpi"), (2806, 2807, "sppi"), (2814, 2814, "pppi"),
    (2815, 2815, "cpi"), (2816, 2816, "pppi"), (2819, 2820, "cpi"), (2821, 2821, "sppi"),
    (3450, 3450, "cpi"), (3453, 3456, "cpi"), (3478, 3478, "cpi"), (3481, 3481, "cpi"),
    (3483, 3484, "cpi"), (3487, 3490, "pppi"), (3495, 3495, "cpi"), (3497, 3497, "cpi"),
    (3512, 3515, "cpi"), (3521, 3521, "cpi"), (3523, 3523, "cpi"), (3531, 3531, "cpi"),
    (3534, 3541, "cpi"), (3542, 3542, "sppi"), (3546, 3546, "cpi"), (3549, 3549, "cpi"),
    (3567, 3568, "cpi"), (3577, 3578, "cpi"), (3579, 3579, "sppi"), (3580, 3580, "cpi"),
    (3591, 3591, "sppi"), (3593, 3593, "pppi"), (3594, 3594, "sppi"), (3596, 3596, "cpi"),
    (3625, 3625, "cpi"), (3627, 3627, "sppi"), (3629, 3629, "sppi"), (3632, 3633, "sppi"),
    (3636, 3640, "pppi"), (3641, 3643, "sppi"), (3651, 3651, "sppi"), (3653, 3655, "sppi"),
    (3656, 3656, "cpi"), (3668, 3670, "sppi"), (3672, 3673, "cpi"), (3680, 3680, "cpi"),
    (3681, 3681, "sppi"), (3696, 3697, "cpi"), (3720, 3724, "sppi"), (3725, 3726, "cpi"),
    (3732, 3732, "cpi"), (3734, 3734, "cpi"), (3736, 3737, "cpi"), (3738, 3738, "sppi"),
    (3739, 3739, "cpi"), (3740, 3740, "sppi"), (3741, 3741, "cpi"), (3742, 3742, "sppi"),
    (3743, 3743, "pppi"), (3744, 3746, "cpi"),
)

#: 展开后的 `{market_group_id: 指数 key}`（导入时由 :data:`MER_MARKET_GROUP_RANGES` 生成）。
#: 分类热路径只查它（O(1)），不扫区间。
MER_MARKET_GROUP_INDEX: dict[int, str] = {
    mg: index for start, end, index in MER_MARKET_GROUP_RANGES for mg in range(start, end + 1)
}

#: 官方成员清单里、但「单指数市场分组区间」命不中的 type（多指数共用的市场分组 / 无市场分类）。
#: 直接按官方清单给指数，不靠猜。
MER_TYPE_OVERRIDES: dict[int, str] = {
    34: "mpi", 35: "mpi", 36: "mpi", 37: "mpi", 38: "mpi",
    39: "mpi", 40: "mpi", 41: "sppi", 42: "sppi", 43: "sppi",
    44: "sppi", 45: "sppi", 2312: "pppi", 2317: "pppi", 2319: "pppi",
    2321: "pppi", 2327: "pppi", 2328: "pppi", 2329: "pppi", 2344: "pppi",
    2345: "pppi", 2346: "pppi", 2348: "sppi", 2349: "pppi", 2351: "pppi",
    2352: "pppi", 2354: "pppi", 2358: "pppi", 2360: "pppi", 2361: "pppi",
    2366: "pppi", 2367: "pppi", 2368: "sppi", 2369: "sppi", 2371: "sppi",
    2373: "sppi", 2374: "sppi", 2375: "sppi", 2376: "sppi", 2377: "sppi",
    2389: "pppi", 2390: "pppi", 2392: "pppi", 2393: "pppi", 2395: "pppi",
    2396: "pppi", 2397: "pppi", 2398: "pppi", 2399: "pppi", 2400: "pppi",
    2401: "pppi", 2463: "sppi", 3643: "sppi", 3645: "sppi", 3647: "sppi",
    3673: "sppi", 3683: "sppi", 3685: "sppi", 3687: "sppi", 3689: "sppi",
    3691: "pppi", 3693: "pppi", 3695: "pppi", 3697: "pppi", 3699: "sppi",
    3715: "sppi", 3717: "sppi", 3719: "sppi", 3721: "sppi", 3723: "sppi",
    3725: "pppi", 3771: "sppi", 3773: "sppi", 3775: "pppi", 3777: "sppi",
    3779: "pppi", 3806: "sppi", 3810: "sppi", 3812: "sppi", 3814: "sppi",
    3828: "sppi", 4358: "sppi", 9826: "sppi", 9828: "pppi", 9830: "sppi",
    9832: "sppi", 9834: "sppi", 9836: "sppi", 9838: "sppi", 9840: "sppi",
    9842: "sppi", 9844: "sppi", 9846: "pppi", 9848: "sppi", 9850: "sppi",
    9852: "sppi", 11069: "sppi", 11399: "mpi", 11585: "sppi", 11588: "sppi",
    11855: "sppi", 11944: "sppi", 12049: "sppi", 12110: "sppi", 12243: "sppi",
    12302: "sppi", 12478: "sppi", 12836: "pppi", 12865: "sppi", 12994: "sppi",
    12995: "sppi", 13267: "sppi", 14358: "sppi", 15316: "sppi", 15317: "pppi",
    15331: "pppi", 15353: "sppi", 15410: "sppi", 16686: "sppi", 16712: "sppi",
    16713: "sppi", 16714: "sppi", 17136: "sppi", 17143: "sppi", 17392: "sppi",
    17423: "sppi", 17424: "sppi", 17754: "sppi", 17755: "sppi", 17756: "sppi",
    17765: "sppi", 17767: "sppi", 17791: "sppi", 17796: "sppi", 17893: "sppi",
    17894: "sppi", 17895: "sppi", 17897: "sppi", 17898: "pppi", 18029: "sppi",
    19461: "sppi", 19462: "sppi", 19463: "sppi", 21947: "sppi", 21949: "sppi",
    21951: "sppi", 21953: "sppi", 21955: "sppi", 21957: "sppi", 21959: "sppi",
    21961: "sppi", 21963: "sppi", 21965: "sppi", 21967: "sppi", 21969: "sppi",
    25588: "sppi", 25589: "sppi", 25590: "sppi", 25591: "sppi", 25592: "sppi",
    25593: "sppi", 25594: "sppi", 25595: "sppi", 25596: "sppi", 25597: "sppi",
    25598: "sppi", 25599: "sppi", 25600: "sppi", 25601: "sppi", 25602: "sppi",
    25603: "sppi", 25604: "sppi", 25605: "sppi", 25606: "sppi", 25607: "sppi",
    25608: "sppi", 25609: "sppi", 25610: "sppi", 25611: "sppi", 25612: "sppi",
    25613: "sppi", 25614: "sppi", 25615: "sppi", 25616: "sppi", 25617: "sppi",
    25618: "sppi", 25619: "sppi", 25620: "sppi", 25621: "sppi", 25622: "sppi",
    25623: "sppi", 25624: "sppi", 25625: "sppi", 26902: "cpi", 27204: "cpi",
    27205: "cpi", 27206: "cpi", 28840: "cpi", 28974: "pppi", 30018: "sppi",
    30019: "sppi", 30021: "sppi", 30022: "sppi", 30024: "sppi", 30248: "sppi",
    30251: "sppi", 30252: "sppi", 30254: "sppi", 30258: "sppi", 30259: "sppi",
    30268: "sppi", 30269: "sppi", 30270: "sppi", 30271: "sppi", 30497: "pppi",
    32099: "sppi", 33015: "cpi", 33016: "cpi", 33017: "cpi", 33018: "cpi",
    33019: "cpi", 33020: "cpi", 33021: "cpi", 33022: "cpi", 33023: "cpi",
    33024: "cpi", 33025: "cpi", 33026: "cpi", 33027: "cpi", 33028: "cpi",
    33029: "cpi", 33030: "cpi", 33058: "cpi", 33059: "cpi", 33060: "cpi",
    33061: "cpi", 33065: "cpi", 33066: "cpi", 33213: "cpi", 33214: "cpi",
    33215: "cpi", 33217: "cpi", 33218: "cpi", 33219: "cpi", 33220: "cpi",
    33221: "cpi", 33539: "sppi", 33575: "cpi", 33577: "sppi", 33809: "cpi",
    33988: "cpi", 34005: "cpi", 34016: "cpi", 34417: "cpi", 34418: "cpi",
    34419: "cpi", 34420: "cpi", 34421: "cpi", 34422: "cpi", 34423: "cpi",
    34424: "cpi", 34425: "cpi", 34426: "cpi", 34427: "cpi", 34428: "cpi",
    34429: "cpi", 34430: "cpi", 34431: "cpi", 34432: "cpi", 34433: "cpi",
    34434: "cpi", 34435: "cpi", 34436: "cpi", 34540: "cpi", 34541: "cpi",
    34542: "cpi", 34543: "cpi", 34544: "cpi", 34545: "cpi", 34546: "cpi",
    34547: "cpi", 34548: "cpi", 34549: "cpi", 34551: "cpi", 34552: "cpi",
    34553: "cpi", 34554: "cpi", 34555: "cpi", 34556: "cpi", 34557: "cpi",
    34558: "cpi", 34559: "cpi", 34560: "cpi", 34575: "cpi", 34769: "cpi",
    34770: "cpi", 34771: "cpi", 34772: "cpi", 34773: "cpi", 34774: "cpi",
    34775: "cpi", 34776: "cpi", 34777: "cpi", 34778: "cpi", 34816: "cpi",
    36902: "cpi", 36949: "sppi", 36956: "sppi", 36957: "sppi", 36958: "sppi",
    37874: "cpi", 37875: "cpi", 37877: "cpi", 37878: "cpi", 37879: "cpi",
    37880: "cpi", 37881: "cpi", 37882: "cpi", 37883: "cpi", 37884: "cpi",
    37885: "cpi", 37886: "cpi", 37887: "cpi", 37888: "cpi", 37889: "cpi",
    37892: "cpi", 37893: "cpi", 37894: "cpi", 37895: "cpi", 37896: "cpi",
    40456: "sppi", 40519: "sppi", 40520: "cpi", 40548: "sppi", 40549: "sppi",
    40656: "cpi", 40701: "cpi", 41263: "sppi", 41264: "sppi", 41265: "sppi",
    41266: "sppi", 41267: "sppi", 41268: "sppi", 41269: "sppi", 41302: "sppi",
    41303: "sppi", 41304: "sppi", 41305: "sppi", 41306: "sppi", 41307: "sppi",
    41308: "sppi", 41309: "sppi", 41310: "sppi", 41311: "sppi", 41312: "sppi",
    42229: "cpi", 42230: "cpi", 42231: "cpi", 43640: "cpi", 43678: "cpi",
    43679: "cpi", 43682: "cpi", 43683: "cpi", 43684: "cpi", 43685: "cpi",
    43686: "cpi", 43687: "cpi", 43688: "cpi", 43689: "cpi", 43690: "cpi",
    43691: "cpi", 43692: "cpi", 43693: "cpi", 43695: "cpi", 43696: "cpi",
    43697: "cpi", 43698: "cpi", 43930: "cpi", 43931: "cpi", 43932: "cpi",
    43933: "cpi", 44205: "cpi", 44206: "cpi", 44207: "cpi", 44208: "cpi",
    44209: "cpi", 44210: "cpi", 44211: "cpi", 44212: "cpi", 44213: "cpi",
    44214: "cpi", 44215: "cpi", 44216: "cpi", 45060: "cpi", 45061: "cpi",
    45062: "cpi", 45584: "pppi", 45585: "pppi", 45635: "cpi", 45660: "pppi",
    45661: "pppi", 45662: "pppi", 45663: "pppi", 45677: "cpi", 45678: "cpi",
    45679: "cpi", 45996: "cpi", 46050: "cpi", 46151: "cpi", 46375: "cpi",
    46381: "cpi", 46579: "cpi", 46580: "cpi", 46601: "cpi", 46602: "cpi",
    46603: "cpi", 46756: "cpi", 46766: "cpi", 46771: "cpi", 46772: "cpi",
    46825: "cpi", 47042: "cpi", 47043: "cpi", 47044: "cpi", 47045: "cpi",
    47046: "cpi", 47047: "cpi", 47048: "cpi", 47053: "cpi", 47054: "cpi",
    47055: "cpi", 47056: "cpi", 47057: "cpi", 47058: "cpi", 47059: "cpi",
    47060: "cpi", 47062: "cpi", 47063: "cpi", 47064: "cpi", 47154: "cpi",
    47253: "cpi", 47482: "cpi", 47961: "cpi", 47962: "cpi", 47963: "cpi",
    47975: "sppi", 48112: "sppi", 48135: "cpi", 48136: "cpi", 48137: "cpi",
    48138: "cpi", 48139: "cpi", 48140: "cpi", 48141: "cpi", 48142: "cpi",
    48143: "cpi", 48144: "cpi", 48374: "cpi", 48375: "cpi", 48376: "cpi",
    48377: "cpi", 48378: "cpi", 48379: "cpi", 48531: "cpi", 48532: "cpi",
    48533: "cpi", 48534: "cpi", 48535: "cpi", 48536: "cpi", 48584: "cpi",
    48585: "cpi", 48586: "cpi", 48587: "cpi", 48588: "cpi", 48589: "cpi",
    48590: "cpi", 48591: "cpi", 48592: "cpi", 48593: "cpi", 48642: "cpi",
    48748: "cpi", 48749: "cpi", 48750: "cpi", 48751: "cpi", 48752: "cpi",
    48753: "cpi", 48754: "cpi", 48755: "cpi", 48756: "cpi", 48757: "cpi",
    48758: "cpi", 48759: "cpi", 48760: "cpi", 48927: "pppi", 48928: "cpi",
    48950: "cpi", 48951: "cpi", 48952: "cpi", 48953: "cpi", 48954: "cpi",
    49333: "cpi", 49619: "cpi", 49620: "cpi", 49621: "cpi", 49634: "cpi",
    49641: "cpi", 49644: "cpi", 49645: "cpi", 49646: "cpi", 49647: "cpi",
    49648: "cpi", 49649: "cpi", 49650: "cpi", 49651: "cpi", 49652: "cpi",
    49653: "cpi", 49705: "cpi", 49707: "cpi", 49708: "cpi", 49709: "cpi",
    49719: "cpi", 49720: "sppi", 49746: "cpi", 49748: "cpi", 49802: "cpi",
    49803: "cpi", 49804: "cpi", 49805: "cpi", 49974: "sppi", 49975: "sppi",
    49981: "sppi", 50029: "sppi", 50030: "sppi", 50039: "cpi", 50040: "cpi",
    50041: "cpi", 50042: "cpi", 50045: "cpi", 50046: "cpi", 50047: "cpi",
    50048: "cpi", 52273: "cpi", 52274: "cpi", 52275: "cpi", 52276: "cpi",
    52277: "cpi", 52290: "cpi", 52291: "cpi", 52292: "cpi", 52293: "cpi",
    52294: "cpi", 52295: "cpi", 52296: "cpi", 52297: "cpi", 52298: "cpi",
    52299: "cpi", 52300: "cpi", 52301: "cpi", 52783: "cpi", 53053: "cpi",
    53055: "cpi", 53056: "cpi", 53057: "cpi", 53058: "cpi", 53059: "cpi",
    53060: "cpi", 53291: "cpi", 53299: "cpi", 53341: "cpi", 53476: "cpi",
    53486: "cpi", 53488: "cpi", 53490: "cpi", 53491: "cpi", 53493: "cpi",
    53494: "cpi", 53496: "cpi", 53498: "cpi", 53508: "cpi", 53509: "cpi",
    53512: "cpi", 53513: "cpi", 53514: "cpi", 53846: "cpi", 53851: "cpi",
    54160: "cpi", 54161: "cpi", 54162: "cpi", 54163: "cpi", 54164: "cpi",
    54165: "cpi", 54166: "cpi", 54225: "cpi", 54226: "cpi", 54227: "cpi",
    54228: "cpi", 54562: "cpi", 54808: "cpi", 54809: "cpi", 54810: "cpi",
    54811: "cpi", 54968: "cpi", 54970: "sppi", 54971: "sppi", 54972: "sppi",
    55029: "cpi", 55358: "cpi", 55359: "cpi", 55746: "cpi", 55827: "cpi",
    56365: "cpi", 56708: "cpi", 56709: "cpi", 56710: "cpi", 56711: "cpi",
    56712: "cpi", 56713: "cpi", 56714: "cpi", 56715: "cpi", 56716: "cpi",
    56788: "cpi", 56971: "cpi", 56972: "cpi", 56973: "cpi", 56974: "cpi",
    56975: "cpi", 56976: "cpi", 56977: "cpi", 56978: "cpi", 56979: "cpi",
    56980: "cpi", 56981: "cpi", 56982: "cpi", 56983: "cpi", 57166: "cpi",
    57168: "cpi", 57170: "cpi", 57414: "cpi", 57416: "cpi", 57422: "cpi",
    57592: "cpi", 57593: "cpi", 59752: "cpi", 60577: "cpi", 60578: "cpi",
    60579: "cpi", 62028: "cpi", 62031: "sppi", 62032: "sppi", 62033: "sppi",
    62034: "sppi", 62035: "sppi", 62036: "sppi", 62037: "sppi", 62038: "sppi",
    62039: "sppi", 62040: "sppi", 62041: "sppi", 62042: "sppi", 62043: "sppi",
    62044: "sppi", 62045: "sppi", 62046: "cpi", 62047: "cpi", 62048: "cpi",
    62049: "cpi", 62050: "cpi", 62051: "cpi", 62052: "cpi", 62053: "cpi",
    62054: "cpi", 62651: "cpi", 62709: "cpi", 62710: "sppi", 63174: "cpi",
    63175: "cpi", 63638: "cpi", 63698: "sppi", 63699: "cpi", 63704: "cpi",
    63705: "cpi", 63706: "cpi", 63707: "cpi", 63708: "cpi", 63709: "cpi",
    63710: "cpi", 63711: "cpi", 63712: "cpi", 63713: "cpi", 63770: "cpi",
    63771: "cpi", 63772: "cpi", 63773: "cpi", 63774: "cpi", 63775: "cpi",
    63776: "cpi", 63777: "cpi", 63778: "cpi", 63779: "cpi", 63780: "cpi",
    63781: "cpi", 63782: "cpi", 63783: "cpi", 63784: "cpi", 63785: "cpi",
    63786: "cpi", 63787: "cpi", 64033: "cpi", 72258: "cpi", 73248: "cpi",
    73249: "cpi", 73250: "cpi", 73251: "cpi", 74001: "cpi", 76150: "cpi",
    76151: "cpi", 76152: "cpi", 76153: "cpi", 76155: "cpi", 76156: "cpi",
    76157: "cpi", 76158: "cpi", 76159: "cpi", 76160: "cpi", 76163: "cpi",
    76164: "cpi", 76165: "cpi", 76166: "cpi", 76167: "cpi", 76169: "cpi",
    76170: "cpi", 76171: "cpi", 76173: "cpi", 76174: "cpi", 76175: "cpi",
    76176: "cpi", 76177: "cpi", 76178: "cpi", 76203: "cpi", 76204: "cpi",
    76207: "cpi", 76208: "cpi", 76209: "cpi", 76210: "cpi", 76211: "cpi",
    76212: "cpi", 76235: "cpi", 76236: "cpi", 76237: "cpi", 76238: "cpi",
    76239: "cpi", 76240: "cpi", 76241: "cpi", 76242: "cpi", 76243: "cpi",
    76244: "cpi", 76245: "cpi", 76246: "cpi", 76247: "cpi", 76248: "cpi",
    76249: "cpi", 76250: "cpi", 76374: "pppi", 76375: "cpi", 77118: "pppi",
    77418: "pppi", 77419: "pppi", 77420: "pppi", 77421: "pppi", 77524: "pppi",
    77707: "cpi", 77708: "cpi", 77946: "cpi", 77947: "cpi", 77948: "cpi",
    77949: "cpi", 78886: "cpi", 78887: "cpi", 78889: "cpi", 78906: "cpi",
    79186: "cpi", 79192: "cpi", 79785: "cpi", 80010: "sppi", 80011: "sppi",
    80012: "sppi", 80013: "sppi", 80014: "sppi", 80015: "sppi", 80016: "sppi",
    80017: "sppi", 80018: "sppi", 80019: "sppi", 80022: "sppi", 80023: "sppi",
    80024: "sppi", 80025: "sppi", 80382: "cpi", 81352: "cpi", 81383: "cpi",
    81603: "cpi", 81920: "cpi", 81953: "cpi", 82432: "cpi", 83709: "cpi",
    83832: "cpi", 84333: "cpi", 84334: "cpi", 84335: "cpi", 84336: "cpi",
    84337: "cpi", 84338: "cpi", 84339: "cpi", 84340: "cpi", 84341: "cpi",
    84342: "cpi", 84344: "cpi", 84345: "cpi", 84346: "cpi", 84347: "cpi",
    84348: "cpi", 84349: "cpi", 84350: "cpi", 84519: "cpi", 84520: "cpi",
    84521: "cpi", 85178: "cpi", 85179: "cpi", 85242: "cpi", 85390: "sppi",
    85391: "sppi", 85392: "sppi", 85393: "sppi", 85394: "sppi", 85395: "sppi",
    85396: "sppi", 85397: "sppi", 85398: "sppi", 85399: "sppi", 85400: "sppi",
    85401: "sppi", 85402: "sppi", 85712: "cpi", 85713: "cpi", 85714: "cpi",
    85715: "cpi", 85716: "cpi", 85717: "cpi", 85718: "cpi", 85719: "cpi",
    85720: "cpi", 85721: "cpi", 85722: "cpi", 85723: "cpi", 85724: "cpi",
    85725: "cpi", 85726: "cpi", 85727: "cpi", 85728: "cpi", 85729: "cpi",
    85730: "cpi", 85731: "cpi", 85757: "cpi", 85758: "cpi", 85759: "cpi",
    85849: "cpi", 86110: "cpi", 86111: "cpi", 86112: "cpi", 86114: "cpi",
    86115: "cpi", 86116: "cpi", 86118: "cpi", 86119: "cpi", 86120: "cpi",
    86121: "cpi", 86122: "cpi", 86270: "sppi", 86271: "sppi", 86272: "sppi",
    86273: "sppi", 86274: "sppi", 86275: "sppi", 86276: "sppi", 86413: "cpi",
    87207: "cpi", 87208: "cpi", 87217: "cpi", 87222: "cpi", 87226: "cpi",
    87258: "cpi", 87263: "cpi", 87264: "cpi", 87265: "cpi", 87266: "cpi",
    87267: "cpi", 87268: "cpi", 87269: "cpi", 87273: "cpi", 87354: "cpi",
    87360: "cpi", 87374: "cpi", 87389: "cpi", 87390: "cpi", 87391: "cpi",
    87392: "cpi", 87393: "cpi", 87601: "cpi", 87602: "cpi", 87603: "cpi",
    87604: "cpi", 87605: "cpi", 87606: "cpi", 87607: "cpi", 87608: "cpi",
    87618: "cpi", 87853: "cpi", 87982: "cpi", 88087: "sppi", 88172: "cpi",
    88173: "cpi", 88174: "cpi", 88175: "cpi", 88176: "cpi", 88177: "cpi",
    88178: "cpi", 88179: "cpi", 88568: "cpi", 88571: "cpi", 88852: "cpi",
    88853: "cpi",
}

#: `market_group_id` 区间会命中、但**不在**官方成员清单里的本地 type（2026-10 真实 SDE 复算 174 个）。
#: 显式排除，保证篮子成员与官方清单一致（这 174 个当前都没有成交历史）。
MER_TYPE_EXCLUDED: frozenset[int] = frozenset({
    4005, 4386, 9373, 11292, 12180, 12181, 12182, 12183, 12184, 12185, 12186, 12187,
    12188, 12190, 12191, 12192, 12193, 12194, 12195, 15431, 15433, 16140, 19658, 19660,
    30222, 33677, 34133, 37280, 37281, 37282, 37283, 37284, 37285, 37386, 37388, 37415,
    37433, 37845, 37854, 40512, 40513, 40516, 40517, 40535, 40536, 40537, 40538, 40700,
    41350, 41389, 41395, 41402, 41422, 41423, 41424, 41425, 41426, 41427, 41428, 41429,
    42132, 42133, 43533, 43534, 43535, 45650, 45669, 45670, 45671, 45672, 45673, 45674,
    45675, 45676, 46010, 46011, 46012, 46013, 48121, 48648, 49787, 52265, 52267, 54361,
    54362, 54366, 54367, 54368, 54372, 54373, 54374, 54379, 54380, 54790, 54793, 54824,
    54825, 54839, 54976, 55700, 55747, 55803, 55804, 55805, 55806, 55830, 55831, 55832,
    56569, 56631, 56632, 56633, 57433, 57434, 57435, 63633, 63634, 63635, 63645, 63646,
    63647, 63648, 63649, 63650, 63651, 63652, 74426, 74427, 74428, 74429, 74430, 74431,
    74432, 74433, 74434, 80873, 81035, 83647, 84008, 84010, 84011, 84013, 84088, 84089,
    84090, 84091, 84092, 84093, 84094, 84095, 84096, 84097, 84807, 84808, 85281, 85282,
    85283, 85284, 85285, 85286, 85287, 85288, 85289, 85881, 85882, 85883, 85884, 85885,
    85886, 85887, 87444, 88186, 88187, 88763,
})
# fmt: on

#: 成员来源（`get_index_series` 的 `members[].source`）：
#: ``fixed`` 固定篮子 / ``official`` 官方 MER 成员清单（经 market_group 映射）。
MEMBER_SOURCES: dict[str, str] = {
    "mpi": "fixed",
    "pppi": "official",
    "sppi": "official",
    "cpi": "official",
    "plex": "fixed",
}

#: 基期点位（首个可算日 = 100）
BASE_VALUE = 100.0

#: 权重/准入的滚动窗口（日历天）—— 30 天滚动再平衡
REBALANCE_DAYS = 30

#: 准入阈值 ①：近 REBALANCE_DAYS 天成交额必须 **大于** 该值（0 = 有成交额即可）
MIN_TURNOVER_ISK = 0.0

#: 准入阈值 ②：近 REBALANCE_DAYS 天必须有成交的天数下限（薄市场抗噪，计划 §2.2.1）
MIN_COVERED_DAYS = 5

#: 单成分权重上限（超过则按上限计，再按合计归一化）—— 计划 §2.2.4
WEIGHT_CAP = 0.25

#: 单成分日收益截断（去极值）—— 计划 §2.2.7
RETURN_CLAMP = 0.20

#: 参考价间隔上限：超过这么多天没成交，价格变化不再是「日收益」（当日不参与）
RETURN_GAP_DAYS = 30

#: 装载窗口：最长卡片窗口 180 天 + 权重窗口 30 天 + 余量，用于控制内存与 SQL 规模
LOAD_WINDOW_DAYS = 220

#: 一次 SQL 里 `IN (...)` 的参数个数上限（SQLite 变量上限的保守取值，与 blueprint_repository 同口径）
_SQL_CHUNK = 900

#: 卡片涨跌窗口：`chg1` 用「上一个点」，其余按日历天回看
CHG_WINDOWS: tuple[tuple[str, int], ...] = (
    ("chg1", 1),
    ("chg7", 7),
    ("chg30", 30),
    ("chg90", 90),
    ("chg180", 180),
)

#: `market_index_daily` 建表语句（market.db 是可重建缓存，不走 schema_migrations）
MARKET_INDEX_DDL = """
    CREATE TABLE IF NOT EXISTS market_index_daily (
        type_id INTEGER NOT NULL,
        region_id INTEGER NOT NULL,
        date TEXT NOT NULL,
        price REAL NOT NULL,
        volume INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (type_id, region_id, date)
    )
"""


class _IndexPoints(NamedTuple):
    """一条指数的计算结果：逐日点位 + 最后一个指数日的成分权重。"""

    points: list[dict]
    weights: dict[int, tuple[float, bool]]


# ════════════════════════════════════════════════════════════════
#  纯计算（可单独测）
# ════════════════════════════════════════════════════════════════


def clamp_return(value: float | None) -> float | None:
    """单成分日收益去极值：超过 :data:`RETURN_CLAMP`（±20%）按 ±20% 计。"""
    if value is None:
        return None
    if value > RETURN_CLAMP:
        return RETURN_CLAMP
    if value < -RETURN_CLAMP:
        return -RETURN_CLAMP
    return value


def weighted_median(values: Sequence[float], weights: Sequence[float]) -> float | None:
    """成交量加权中位数（权重非正的样本不参与）。

    - 升序累加权重，取首个「累计权重 ≥ 合计一半」的样本值（统计上的加权中位数）；
    - 累计权重**恰好**落在两样本交界处（偶数个等权时必然如此）→ 取两者算术平均，
      于是等权退化为标准中位数（`[1, 2, 3, 4]` → `2.5`）；
    - 没有正权重样本 → `None`（**不用 0 冒充**）。
    """
    pairs = sorted((float(v), float(w)) for v, w in zip(values, weights, strict=True) if w > 0)
    if not pairs:
        return None
    total = sum(w for _v, w in pairs)
    if total <= 0:  # pragma: no cover - pairs 里 w>0 时不可能为真，留作除零护栏
        return None
    half = total / 2.0
    tolerance = 1e-12 * max(1.0, total)
    cum = 0.0
    for i, (value, weight) in enumerate(pairs):
        cum += weight
        if cum > half + tolerance:
            return value
        if abs(cum - half) <= tolerance:
            nxt = pairs[i + 1][0] if i + 1 < len(pairs) else value
            return (value + nxt) / 2.0
    return pairs[-1][0]


def cap_weights[K: Hashable](raw: Mapping[K, float]) -> dict[K, tuple[float, bool]]:
    """成交额权重：单成分上限 :data:`WEIGHT_CAP`（25%）后按合计归一化。

    返回 `{key: (归一化权重, 是否触顶)}`；上限 = `WEIGHT_CAP × 原始合计`，原始值超过即
    `capped=True`。权重合计 ≤ 0（或没有正权重）→ `{}`（调用方按「当日无可算收益」处理）。

    ⚠️ 触顶成员归一化后可能**再次**超过 25%（上限是「先夹后归一」的一次性口径，不是迭代上限）：
    多成员同时触顶时各自按夹后的合计分摊。只有一个成员时它也必然记为 `capped=True`（原始值
    100% > 25% 的上限），这是该口径的字面结果。
    """
    positive = {key: float(weight) for key, weight in raw.items() if weight > 0}
    total = sum(positive.values())
    if total <= 0:
        return {}
    cap = WEIGHT_CAP * total
    clipped = {key: min(weight, cap) for key, weight in positive.items()}
    clipped_total = sum(clipped.values())
    if clipped_total <= 0:  # pragma: no cover - 正权重夹后不可能为 0，除零护栏
        return {}
    return {key: (weight / clipped_total, positive[key] > cap) for key, weight in clipped.items()}


def classify_official_basket(type_id: int, market_group_id: int | None) -> str | None:
    """官方 MER 篮子分类（纯函数，不查库）：`type_id` + SDE `market_group_id` → 指数 key 或 `None`。

    判定顺序：

    1. :data:`MER_TYPE_EXCLUDED`（规则会误收的本地 type）→ `None`；
    2. :data:`MER_TYPE_OVERRIDES`（官方成员里规则覆盖不到的 type）→ 其官方指数；
    3. :data:`MER_MARKET_GROUP_INDEX`（单指数市场分组）→ 其官方指数；
    4. 其余 → `None`（不在官方篮子 / SDE 里没有市场分类）。

    返回 `"mpi"` / `"pppi"` / `"sppi"` / `"cpi"` / `None`。PLEX 是独立锚、不在 MER 四指数里。
    """
    tid = int(type_id)
    if tid in MER_TYPE_EXCLUDED:
        return None
    override = MER_TYPE_OVERRIDES.get(tid)
    if override is not None:
        return override
    if market_group_id is None:
        return None
    return MER_MARKET_GROUP_INDEX.get(int(market_group_id))


def _build_index(obs: Mapping[int, Sequence[tuple[str, float, int]]], members: Iterable[int]) -> _IndexPoints:
    """把「成员 → 逐日 `(date, average, volume)`」链式累乘成指数。

    `obs` 的每个成员序列必须按日期升序。算法见模块 docstring 第 1~5 条；
    只有「当日有成交均价 + 参考价可用 + 通过准入」的成员参与当日加权中位数。
    """
    member_ids = sorted({int(m) for m in members})
    #: 日期串 → ordinal 缓存：一轮里同一日期被 N 个成员重复解析（14,218 个 CPI 成员 × ~150 行），
    #: 而不同日期串只有 ~220 个；实测 `date.fromisoformat` 调用从 ~2M 次降到 ~220 次。
    ordinal_cache: dict[str, int] = {}
    day_rows: dict[str, list[tuple[int, int]]] = {}
    turnovers: dict[int, list[float]] = {}
    returns: dict[int, list[float | None]] = {}
    windows: dict[int, tuple[list[float], list[int]]] = {}
    #: 该成员**完全没有成交量**（全服统一价品种）→ 只按覆盖天数准入、权重等权
    price_only: dict[int, bool] = {}

    for tid in member_ids:
        rows = list(obs.get(tid) or [])
        if len(rows) < 2:
            continue  # 单点算不出收益，也无法构成指数
        ords: list[int] = []
        for row in rows:
            ordinal = ordinal_cache.get(row[0])
            if ordinal is None:
                ordinal = date.fromisoformat(row[0]).toordinal()
                ordinal_cache[row[0]] = ordinal
            ords.append(ordinal)
        avgs = [float(row[1]) for row in rows]
        turns = [float(row[1]) * float(row[2]) for row in rows]

        member_returns: list[float | None] = [None]
        for i in range(1, len(rows)):
            gap_ok = ords[i] - ords[i - 1] <= RETURN_GAP_DAYS
            base = avgs[i - 1]
            member_returns.append(clamp_return(avgs[i] / base - 1.0) if gap_ok and base > 0 else None)

        # 每行的「往前 REBALANCE_DAYS 个日历天（含当日）」成交额与覆盖天数：双指针 + 前缀和
        prefix = [0.0]
        for turn in turns:
            prefix.append(prefix[-1] + turn)
        win_turn = [0.0] * len(rows)
        win_cov = [0] * len(rows)
        left = 0
        for i in range(len(rows)):
            while ords[i] - ords[left] >= REBALANCE_DAYS:
                left += 1
            win_turn[i] = prefix[i + 1] - prefix[left]
            win_cov[i] = i + 1 - left

        turnovers[tid] = turns
        returns[tid] = member_returns
        windows[tid] = (win_turn, win_cov)
        # 整条序列**没有任何成交量**的品种（当前只有 PLEX 走 `global_price_daily` 兜底时会这样：
        # 那张表只有价、没有成交）→ 成交额权重恒为 0，会被下面的「成交额门槛」整条筛掉。
        # 它本身就是**固定锚**，不是「按交易活跃度加权」的对象：只按覆盖天数准入、权重按等权给。
        # PLEX 的正常路径（`PLEX_REGION_ID` 的成交历史）是带 `volume` 的，不走这一支。
        price_only[tid] = not any(turns)
        for i, row in enumerate(rows):
            day_rows.setdefault(row[0], []).append((tid, i))

    points: list[dict] = []
    level: float | None = None
    last_weights: dict[int, tuple[float, bool]] = {}

    for day in sorted(day_rows):
        day_turnover = 0.0
        day_returns: dict[int, float] = {}
        raw_weights: dict[int, float] = {}
        for tid, i in day_rows[day]:
            day_turnover += turnovers[tid][i]
            ret = returns[tid][i]
            if ret is None:
                continue
            win_turn, win_cov = windows[tid]
            if price_only.get(tid):
                if win_cov[i] < MIN_COVERED_DAYS:
                    continue
                day_returns[tid] = ret
                raw_weights[tid] = 1.0
                continue
            if win_turn[i] <= MIN_TURNOVER_ISK or win_cov[i] < MIN_COVERED_DAYS:
                continue
            day_returns[tid] = ret
            raw_weights[tid] = win_turn[i]

        weights = cap_weights(raw_weights)
        if not weights:
            continue
        aggregate = weighted_median(
            [day_returns[tid] for tid in weights],
            [weight for weight, _capped in weights.values()],
        )
        if aggregate is None:
            continue

        # 首个可算日就是基期（100），当日收益从**下一个**指数日开始计入
        level = BASE_VALUE if level is None else level * (1.0 + aggregate)
        points.append({"date": day, "value": level, "volume": int(round(day_turnover))})
        # `weights` 每天都是新 dict、之后不再修改 → 直接留引用，避免再拷贝一份（214 天 × ~4k 项）。
        last_weights = weights

    return _IndexPoints(points=points, weights=last_weights)


def _price_change(rows: Sequence[tuple[str, float, int]], days: int) -> float | None:
    """成员自身近 `days` 个日历天的成交均价涨幅（%）—— 数据不足 → `None`。

    日期是 `YYYY-MM-DD` 的 ISO 串，**字典序即时间序**，直接比字符串（不逐行 `fromisoformat`）。
    """
    if len(rows) < 2:
        return None
    cutoff = (date.fromisoformat(rows[-1][0]) - timedelta(days=days)).isoformat()
    base: float | None = None
    for item in rows:
        if item[0] > cutoff:
            break
        base = float(item[1])
    if base is None or base <= 0:
        return None
    return (float(rows[-1][1]) / base - 1.0) * 100.0


def _last_price(rows: Sequence[tuple[str, float, int]], anchor: date | None) -> float | None:
    """成员在 `anchor` 日（含）之前**最近一次**成交均价；没有可用观测 → `None`（不用 0 冒充）。

    `rows` 按日期升序，日期是 ISO 串 → 直接比字符串（不逐行解析）。
    """
    if anchor is None:
        return None
    limit = anchor.isoformat()
    last: float | None = None
    for day, average, _volume in rows:
        if day > limit:
            break
        last = float(average)
    return last


def _weights_at(
    obs: Mapping[int, Sequence[tuple[str, float, int]]],
    members: Iterable[int],
    anchor: date,
) -> dict[int, tuple[float, bool]]:
    """以 `anchor` 为最后一天，算成员表用的 30 天成交额权重（准入 + 25% 上限 + 归一化）。

    `rows` 按日期升序、日期是 ISO 串 → 用字符串边界比较并提前 `break`（不逐行解析）。
    """
    last = anchor.isoformat()
    first = (anchor - timedelta(days=REBALANCE_DAYS - 1)).isoformat()
    raw: dict[int, float] = {}
    for tid in members:
        covered = 0
        turnover = 0.0
        for day, average, volume in obs.get(tid) or []:
            if day < first:
                continue
            if day > last:
                break
            covered += 1
            turnover += float(average) * float(volume)
        if turnover > MIN_TURNOVER_ISK and covered >= MIN_COVERED_DAYS:
            raw[tid] = turnover
    return cap_weights(raw)


def _append_missing_days(
    points: list[dict],
    obs: Mapping[int, Sequence[tuple[str, float, int]]],
    members: Iterable[int],
    anchor: date,
) -> list[dict]:
    """在已物化点位后**只补缺失的指数日**（通常今天 1 个点），历史点位一棵不动。

    口径逐点对齐 :func:`_build_index`：成员日收益用「当日均价 ÷ 上一有效均价」（间隔
    > :data:`RETURN_GAP_DAYS` → 当日不参与）、权重用当日往前 :data:`REBALANCE_DAYS`
    天成交额（准入 + :data:`WEIGHT_CAP` 上限 + 归一化）、聚合用加权中位数、点位从
    `points[-1].value` 续乘。**不重跑 220 天窗口**：每成员只扫「最后点位日之前
    :data:`REBALANCE_DAYS` 天」起的行。

    `obs` 由调用方按需装载（必须覆盖到缺口的窗口，见 :func:`_resolve_points`）。
    """
    if not points:
        return list(points)
    last_date = str(points[-1]["date"])
    level = float(points[-1]["value"])
    window_start = (date.fromisoformat(last_date) - timedelta(days=REBALANCE_DAYS - 1)).isoformat()
    #: 缺失日 → [(tid, turn, ret, win_turn, win_cov, price_only)]
    day_rows: dict[str, list[tuple[int, float, float | None, float, int, bool]]] = {}
    ordinal_cache: dict[str, int] = {}
    for raw_tid in members:
        tid = int(raw_tid)
        rows = list(obs.get(tid) or [])
        if len(rows) < 2:
            continue
        turns = [float(row[1]) * float(row[2]) for row in rows]
        price_only = not any(turns)
        # 窗口起点所在行（再往前留一行做「上一观测」基数）
        start = len(rows)
        for idx, row in enumerate(rows):
            if row[0] >= window_start:
                start = idx
                break
        start = max(start - 1, 0)
        if start >= len(rows) - 1:
            continue
        window_rows = rows[start:]
        ords: list[int] = []
        for row in window_rows:
            ordinal = ordinal_cache.get(row[0])
            if ordinal is None:
                ordinal = date.fromisoformat(row[0]).toordinal()
                ordinal_cache[row[0]] = ordinal
            ords.append(ordinal)
        avgs = [float(row[1]) for row in window_rows]
        turns_w = turns[start:]
        prefix = [0.0]
        for turn in turns_w:
            prefix.append(prefix[-1] + turn)
        left = 0
        for i, row in enumerate(window_rows):
            while ords[i] - ords[left] >= REBALANCE_DAYS:
                left += 1
            if row[0] <= last_date:
                continue
            ret: float | None = None
            if i > 0 and ords[i] - ords[i - 1] <= RETURN_GAP_DAYS and avgs[i - 1] > 0:
                ret = clamp_return(avgs[i] / avgs[i - 1] - 1.0)
            day_rows.setdefault(row[0], []).append(
                (tid, turns_w[i], ret, prefix[i + 1] - prefix[left], i + 1 - left, price_only)
            )

    appended: list[dict] = []
    for day in sorted(day_rows):
        day_turnover = 0.0
        day_returns: dict[int, float] = {}
        raw_weights: dict[int, float] = {}
        for tid, turn, ret, win_turn, win_cov, price_only in day_rows[day]:
            day_turnover += turn
            if ret is None:
                continue
            if price_only:
                if win_cov >= MIN_COVERED_DAYS:
                    day_returns[tid] = ret
                    raw_weights[tid] = 1.0
                continue
            if win_turn > MIN_TURNOVER_ISK and win_cov >= MIN_COVERED_DAYS:
                day_returns[tid] = ret
                raw_weights[tid] = win_turn
        weights = cap_weights(raw_weights)
        if not weights:
            continue
        aggregate = weighted_median(
            [day_returns[tid] for tid in weights],
            [weight for weight, _capped in weights.values()],
        )
        if aggregate is None:
            continue
        level = level * (1.0 + aggregate)
        appended.append({"date": day, "value": level, "volume": int(round(day_turnover))})
    return [*points, *appended]


# ════════════════════════════════════════════════════════════════
#  数据读取
# ════════════════════════════════════════════════════════════════


def _table_has_column(conn, table: str, column: str) -> bool:
    """`table` 是否存在且含 `column`（表不存在 → False）。

    `table` / `column` 只接受模块内常量，不做外部输入拼接。
    """
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    if row is None:
        return False
    return column in {info[1] for info in conn.execute(f"PRAGMA table_info({table})")}


def _table_exists(conn, name: str) -> bool:
    """表是否存在。`name` 可以带库前缀（如 `ref.item`）—— 带前缀时查那张库的 `sqlite_master`。

    ⚠️ 不带前缀的查询只看**主库**：`db.connect("bp", "ref")` 之后
    `SELECT ... FROM sqlite_master WHERE name='item'` 是查不到 `ref.item` 的（ATTACH 进来的库
    有自己的 `sqlite_master`），照那样判会把「有效配方过滤」整条静默跳过。
    """
    if "." in name:
        schema, _, table = name.partition(".")
        row = conn.execute(f"SELECT 1 FROM {schema}.sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    else:
        row = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
    return row is not None


#: 尾部「还没补齐的一天」的判定阈值：当天覆盖的 type 数低于窗口常态的这个比例时不算数据日。
#: ESI 的市场历史**按天逐步出**，最新一两天往往只有几百个 type（实测 2026-10-04 只有 434 个，
#: 前一天 2,926 个）—— 把它当锚点，广度与指数会落在残缺的一天上（涨跌家数从 2,300+ 掉到 399）。
COVERAGE_RATIO = 0.5


def _last_history_day(conn_mgr, region_id: int) -> date | None:
    """最新**已补齐**的**成交**数据日（只看 `price_history`，覆盖数达标的那天）。

    广度/成交额这类「当日成交」统计必须用它：全服价表里的日子没有成交量，
    拿来当统计日会得到 0 家涨跌（见 `get_breadth`）。
    """
    best: str | None = None
    with conn_mgr.connect("mkt") as conn:
        if _table_exists(conn, "price_history"):
            rows = conn.execute(
                "SELECT date, COUNT(*) FROM price_history WHERE region_id = ? GROUP BY date ORDER BY date",
                (region_id,),
            ).fetchall()
            if rows:
                typical = max(int(r[1] or 0) for r in rows)
                threshold = typical * COVERAGE_RATIO
                # 从最后往前找第一个「覆盖数达标」的日子（通常就是倒数第二天）
                for day, count in reversed(rows):
                    if int(count or 0) >= threshold:
                        best = str(day)
                        break
    return date.fromisoformat(best) if best else None


def latest_price_day(region_id: int = JITA_RID, _db=None) -> str | None:
    """`price_history` / 全服价的最新日期（**不做覆盖度校验**，~ms）。

    仅供桥层判断「磁盘缓存是否已经跨了交易日」：同一天重复打开可继续用 payload 文件；
    出现新日期（哪怕尾部残缺日）就认为需要增量刷新一次。口径与 :func:`_last_day` 不同：
    这里要的是「有没有新行」而不是「指数锚定日」，所以故意取裸 MAX(date)。
    """
    conn_mgr = _db or get_db()
    with conn_mgr.connect("mkt") as conn:
        best: str | None = None
        if _table_exists(conn, "price_history"):
            row = conn.execute(
                "SELECT MAX(date) FROM price_history WHERE region_id IN (?, ?)",
                (region_id, PLEX_REGION_ID),
            ).fetchone()
            if row and row[0]:
                best = str(row[0])
        if _table_exists(conn, "global_price_daily"):
            row = conn.execute("SELECT MAX(date) FROM global_price_daily").fetchone()
            if row and row[0]:
                best = max(best or "", str(row[0])) or None
    return best


def _last_day(conn_mgr, region_id: int) -> date | None:
    """指数计算用的最新数据日：**成交**的已补齐日 与 **全服价**的最新日取较晚者。

    - 只看「MAX(date)」会被 ESI 的尾部残缺日骗到（见 `COVERAGE_RATIO`）；
    - 只看 `price_history` 又会让「只装了全服价」的库算不出 PLEX（它的序列在
      `global_price_daily` 里）；
    - PLEX 的成交历史写在**全域市场 region**（`PLEX_REGION_ID`）而指数区域是 Jita：
      它的数据日也要算进来，否则「只拉到 PLEX 全域历史」的库会把 PLEX 整条线算空
      （`_load_observations` 的装载窗口以本函数返回的日期为右端）。
      实测/推算：正常库里 `global_price_daily` 的当日快照日 ≥ PLEX 的历史最末日
      （ESI 在 D+1 的 11:05 才放出 D 的日线，而快照是每次「更新价格」当天写的），
      所以这一支平时不动锚定日，只在「没有成交历史也没有全服快照」时才把 PLEX 救回来。
    """
    best = _last_history_day(conn_mgr, region_id)
    plex_day = _last_history_day(conn_mgr, PLEX_REGION_ID)
    if plex_day and (best is None or plex_day > best):
        best = plex_day
    with conn_mgr.connect("mkt") as conn:
        if _table_exists(conn, "global_price_daily"):
            row = conn.execute("SELECT MAX(date) FROM global_price_daily").fetchone()
            if row and row[0]:
                global_day = date.fromisoformat(str(row[0]))
                if best is None or global_day > best:
                    best = global_day
    return best


#: `price_history` 的主键索引名（SQLite 为 `PRIMARY KEY (type_id, region_id, date)` 自动生成）。
#: 取「有数据的成员集合」时**强制走它**：这是覆盖索引，只读索引页不回表，
#: 实测 139 万行 ~0.3s；不强制时优化器会走 `idx_price_history_region_date` + 回表 +
#: TEMP B-TREE 去重（同一查询实测 ~6s）。
_HISTORY_PK_INDEX = "sqlite_autoindex_price_history_1"


def _active_history_ids(conn, region_id: int) -> set[int]:
    """该区域 `price_history` 里**有任意历史行**的 type_id 集合（覆盖索引扫描，不读表）。"""
    return {
        int(row[0])
        for row in conn.execute(
            f"SELECT DISTINCT type_id FROM price_history INDEXED BY {_HISTORY_PK_INDEX} WHERE region_id = ?",
            (region_id,),
        )
    }


def _global_price_type_ids(conn) -> set[int]:
    """`global_price_daily` 里有行的 type_id（只有 PLEX 这类全服统一价品种，表很小）。"""
    if not _table_exists(conn, "global_price_daily"):
        return set()
    return {int(row[0]) for row in conn.execute("SELECT DISTINCT type_id FROM global_price_daily")}


def _read_region_history(
    conn,
    out: dict[int, list[tuple[str, float, int]]],
    region_id: int,
    ids: Sequence[int],
    start: date,
    end: date,
) -> None:
    """把 `price_history` 里 `region_id` 的 `ids` 行追加进 `out`（按 `_SQL_CHUNK` 分批）。"""
    for offset in range(0, len(ids), _SQL_CHUNK):
        chunk = ids[offset : offset + _SQL_CHUNK]
        placeholders = ",".join("?" * len(chunk))
        # 流式迭代（不先 fetchall 出 70 万行列表）+ 不再逐值 str()/float()/int() 转换：
        # price_history 的列亲和性保证返回已是 str/float/int，转换只是白花 ~3×70 万次调用。
        for tid, day, average, volume in conn.execute(
            f"SELECT type_id, date, average, volume FROM price_history "
            f"WHERE region_id = ? AND date >= ? AND date <= ? AND type_id IN ({placeholders}) "
            f"ORDER BY type_id, date",
            (region_id, start.isoformat(), end.isoformat(), *chunk),
        ):
            out.setdefault(tid, []).append((day, average, volume))


def _load_observations(
    conn_mgr,
    region_id: int,
    type_ids: Iterable[int],
    start: date,
    end: date,
) -> dict[int, list[tuple[str, float, int]]]:
    """读 `price_history` → `{type_id: [(date, average, volume), ...]}`（按日期升序）。

    **PLEX 的序列改读全局市场 region**：它的价格全服统一、没有本地市场划分，
    成交历史在官方 Global PLEX Market（`PLEX_REGION_ID`）里，贸易中心的区块历史对它
    恒返回空（实测 `/markets/10000002/history/?type_id=44992` → `[]`）。所以命中 PLEX 时
    改读 `region_id = PLEX_REGION_ID` 的行 —— **连 `volume` / `order_count` 一起拿到的真值**，
    不再像以前那样只能拿全服价、成交量填 0。

    两个兜底都在，且**不混进同一条序列**（命中就整段替换）：
    PLEX 的全域历史还没拉过时退回 `global_price_daily`；其余品种照旧退回它。
    """
    ids = sorted({int(t) for t in type_ids})
    out: dict[int, list[tuple[str, float, int]]] = {}
    if not ids:
        return out
    with conn_mgr.connect("mkt") as conn:
        # 两张表各自判断存在性：只装了 `global_price_daily`（还没跑过历史拉取）时，
        # PLEX 也应该有数 —— 早退会让它整条线空掉
        if _table_exists(conn, "price_history"):
            # **只装载真的有历史行的成员**：官方 CPI 篮子本地有 14,218 个成员，但 Jita 的
            # price_history 只有 ~4,700 个 type 有成交行；其余成员本来就不参与任何一天的
            # 收益/权重（`_build_index` 对空序列直接跳过），逐个探测只是白跑索引查找与
            # SQL 分块（21 块 → 6 块）。篮子集合本身**不变**，只是取数前先取交集。
            active = _active_history_ids(conn, region_id)
            active |= _global_price_type_ids(conn)
            if PLEX_TYPE_ID in ids:
                # PLEX 的成交历史在官方全域市场 region（PLEX_REGION_ID），不在贸易中心里
                active.add(PLEX_TYPE_ID)
            ids = [tid for tid in ids if tid in active]
            plex_ids = [PLEX_TYPE_ID] if PLEX_TYPE_ID in ids else []
            other_ids = [tid for tid in ids if tid != PLEX_TYPE_ID]
            if other_ids:
                _read_region_history(conn, out, region_id, other_ids, start, end)
            if plex_ids:
                _read_region_history(conn, out, PLEX_REGION_ID, plex_ids, start, end)
        for tid, rows in _load_global_observations(conn, ids, start, end).items():
            # 全服价是**退路，不是覆盖**：只有该品种在窗口里完全没有成交序列时才用它。
            # （曾经写成无条件覆盖 —— 那时把 8 种矿物也放进了全服快照表，结果矿物的
            #  398 天成交序列被换成 1 行当日价，MPI 直接整条空掉。）
            if not out.get(tid):
                out[tid] = rows
    return out


def _load_global_observations(
    conn,
    type_ids: Iterable[int],
    start: date,
    end: date,
) -> dict[int, list[tuple[str, float, int]]]:
    """读 `global_price_daily`（全服统一价）→ 与 `price_history` 同形的序列。

    成交量给 0：这张表只有价格，没有成交（它是 `/markets/prices/` 的每日快照，
    不含成交量）。PLEX 的**权威序列已经换成** `PLEX_REGION_ID` 的成交历史
    （那份**带**真实 `volume`），这里只剩「那个 region 还没拉过」时的兜底。
    """
    ids = sorted({int(t) for t in type_ids})
    out: dict[int, list[tuple[str, float, int]]] = {}
    if not ids or not _table_exists(conn, "global_price_daily"):
        return out
    for offset in range(0, len(ids), _SQL_CHUNK):
        chunk = ids[offset : offset + _SQL_CHUNK]
        placeholders = ",".join("?" * len(chunk))
        rows = conn.execute(
            f"SELECT type_id, date, average_price FROM global_price_daily "
            f"WHERE date >= ? AND date <= ? AND type_id IN ({placeholders}) ORDER BY type_id, date",
            (start.isoformat(), end.isoformat(), *chunk),
        ).fetchall()
        for tid, day, average in rows:
            out.setdefault(int(tid), []).append((str(day), float(average or 0.0), 0))
    return out


def _load_names(conn_mgr, type_ids: Iterable[int]) -> dict[int, str]:
    """`{type_id: 中文名（退回英文名，再退回 #id）}`；reference.db 没表 → `{}`。"""
    ids = sorted({int(t) for t in type_ids})
    out: dict[int, str] = {}
    if not ids:
        return out
    with conn_mgr.connect("ref") as conn:
        if not _table_exists(conn, "item"):
            return out
        for offset in range(0, len(ids), _SQL_CHUNK):
            chunk = ids[offset : offset + _SQL_CHUNK]
            placeholders = ",".join("?" * len(chunk))
            rows = conn.execute(
                f"SELECT type_id, zh_name, en_name FROM item WHERE type_id IN ({placeholders})", chunk
            ).fetchall()
            for tid, zh, en in rows:
                out[int(tid)] = str(zh or en or f"#{int(tid)}")
    return out


def official_index_members(conn_mgr=None) -> dict[str, set[int]]:
    """官方 MER 四指数篮子（`{mpi, pppi, sppi, cpi}` → type_id 集合）—— 指数与异动榜的唯一口径。

    读 `reference.db.item(type_id, market_group_id)`，逐个套 :func:`classify_official_basket`。
    篮子成员来自**官方逐 type 清单**；`market_group_id` 只是把清单压缩到本地 SDE 的映射方式
    （覆盖率见模块 docstring）。

    `reference.db` 缺 `item` 表或 `market_group_id` 列时，只返回固定 MPI、其余为空集并 warning
    —— 数据没导好时不拿旧启发式猜。
    """
    conn_mgr = conn_mgr or get_db()
    out: dict[str, set[int]] = {"mpi": set(MPI_TYPES), "pppi": set(), "sppi": set(), "cpi": set()}
    with conn_mgr.connect("ref") as conn:
        if not _table_exists(conn, "item"):
            log.warning("reference.db 缺 item 表，指数篮子退化为只剩固定篮子（MPI/PLEX）")
            return out
        if not _table_has_column(conn, "item", "market_group_id"):
            log.warning("reference.db.item 缺 market_group_id 列，官方篮子无法映射（只剩固定 MPI/PLEX）")
            return out
        for tid, mg in conn.execute("SELECT type_id, market_group_id FROM item"):
            index = classify_official_basket(int(tid), mg)
            if index is not None:
                out[index].add(int(tid))
    return out


def _official_classes(conn_mgr) -> tuple[set[int], set[int]]:
    """官方 MER 篮子的 PPPI / SPPI 成员集合（= :func:`official_index_members` 的对应两项）。"""
    sets = official_index_members(conn_mgr)
    return sets["pppi"], sets["sppi"]


def production_input_classes(db=None) -> tuple[set[int], set[int]]:
    """**生产投入品**的 PPPI / SPPI 划分 —— 指数篮子与异动榜共用的唯一口径。

    成员 = 官方 MER 的 Primary / Secondary Producer Price Index 篮子（官方逐 type 清单，
    映射见 :func:`official_index_members`）。`db` 传 `services.database_manager` 的 manager
    （含临时库 fixture），不传则用 `get_db()`。

    异动榜（`services.market_movers_service`）复用本函数、不自己抄一份：
    两份口径一旦分叉，用户就会看到「同一件东西在指数篮子里、却在异动榜里标成另一个指数」。
    """
    return _official_classes(db or get_db())


def production_inputs(db=None) -> set[int]:
    """生产投入品 = PPPI ∪ SPPI（见 :func:`production_input_classes`）。"""
    pppi, sppi = production_input_classes(db)
    return pppi | sppi


def _member_sets(conn_mgr, keys: Sequence[str]) -> dict[str, set[int]]:
    """`{key: 候选成分}`：**官方 MER 篮子**的成员集合（指数与异动榜同一口径）。

    成员来自 :func:`official_index_members`：MPI 固定 8 矿、PLEX 固定 44992、
    PPPI/SPPI/CPI 取官方清单映射结果。候选成分**未**做准入过滤（准入在逐日权重里做）。
    """
    official = official_index_members(conn_mgr)
    out: dict[str, set[int]] = {}
    for key in keys:
        if key == "mpi":
            out[key] = set(MPI_TYPES)
        elif key == "plex":
            out[key] = {PLEX_TYPE_ID}
        elif key in official:
            out[key] = set(official[key])
    return out


def _build_for(
    conn_mgr,
    region_id: int,
    keys: Sequence[str],
    anchor: date | None = None,
    sets: Mapping[str, set[int]] | None = None,
    obs: Mapping[int, Sequence[tuple[str, float, int]]] | None = None,
) -> dict[str, _IndexPoints]:
    """实时计算若干指数的点位（不写库）。

    `anchor`（最新数据日）与 `sets`（成分集）可传入调用方已算好的结果 —— 见
    :func:`get_dashboard`：它把成分集算一遍后同时喂给卡片与序列两条路。`sets` 里
    多出来的 key 不参与观测装载（只装 `keys` 要用的那部分）。
    """
    empty = {key: _IndexPoints(points=[], weights={}) for key in keys}
    if anchor is None:
        anchor = _last_day(conn_mgr, region_id)
    if anchor is None:
        return empty
    if sets is None:
        sets = _member_sets(conn_mgr, keys)
    if obs is None:
        union: set[int] = set()
        for key in keys:
            union |= sets[key]
        obs = _load_observations(conn_mgr, region_id, union, anchor - timedelta(days=LOAD_WINDOW_DAYS - 1), anchor)
    return {key: _build_index(obs, sets[key]) for key in keys}


def _read_materialized(conn_mgr, region_id: int, key: str) -> list[dict]:
    """读物化表里某指数的点位；没有表/没有行 → `[]`。"""
    tid = INDEX_TYPE_IDS.get(key)
    if tid is None:
        return []
    with conn_mgr.connect("mkt") as conn:
        if not _table_exists(conn, "market_index_daily"):
            return []
        rows = conn.execute(
            "SELECT date, price, volume FROM market_index_daily WHERE type_id = ? AND region_id = ? ORDER BY date",
            (tid, region_id),
        ).fetchall()
    return [{"date": str(day), "value": float(price), "volume": int(volume or 0)} for day, price, volume in rows]


def _persist_points(
    conn_mgr,
    region_id: int,
    key: str,
    points: Sequence[dict],
    *,
    replace: bool = False,
) -> None:
    """把点位写回 `market_index_daily` —— 读路径算出的增量结果也必须落库，否则下次打开又重算。

    `replace=True` 用于「整条指数重建」（初始化 / 缺口超出装载窗口的安全兜底）：先删本区域
    本指数的旧行再写；`replace=False` 只写增量日期（`INSERT OR REPLACE` 幂等）。
    """
    tid = INDEX_TYPE_IDS.get(key)
    if tid is None:
        return
    rows = [(tid, region_id, str(p["date"]), float(p["value"]), int(p.get("volume") or 0)) for p in points]
    with conn_mgr.connect("mkt") as conn:
        conn.execute(MARKET_INDEX_DDL)
        if replace:
            conn.execute("DELETE FROM market_index_daily WHERE type_id = ? AND region_id = ?", (tid, region_id))
        if rows:
            conn.executemany(
                "INSERT OR REPLACE INTO market_index_daily (type_id, region_id, date, price, volume) "
                "VALUES (?, ?, ?, ?, ?)",
                rows,
            )


def _resolve_points(
    conn_mgr,
    region_id: int,
    keys: Sequence[str],
    anchor: date | None = None,
    sets: Mapping[str, set[int]] | None = None,
    obs: Mapping[int, Sequence[tuple[str, float, int]]] | None = None,
) -> dict[str, list[dict]]:
    """点位：**历史一律读已物化缓存、不重算**；只对「最后点位日 → 锚定日」的缺口做增量续算。

    - 缓存为空 → 全量算一次（初始化，:func:`_build_for`）；
    - 缓存停在今天/更早、缺口在全量装载窗口内 → :func:`_append_missing_days` 只补缺失日期；
    - 缺口超过 :data:`LOAD_WINDOW_DAYS`（观测已无法覆盖）→ 退回全量（安全兜底）。

    `anchor` / `sets` / `obs` 透传（:func:`get_dashboard` 一次算完时用）；没传时这里按需装载。
    增量续算与全量重算逐点一致（口径同 :func:`_build_index`，见副本库等价验证用例）。
    """
    out: dict[str, list[dict]] = {}
    rebuild: list[str] = []
    rebuild_replace: set[str] = set()  # 旧点位存在但不连续（缺口超窗口）→ 重建时整条替换
    to_append: list[tuple[str, list[dict]]] = []
    horizon = anchor - timedelta(days=LOAD_WINDOW_DAYS - 1) if anchor is not None else None
    for key in keys:
        cached = _read_materialized(conn_mgr, region_id, key)
        out[key] = cached
        if not cached:
            rebuild.append(key)
        elif anchor is not None:
            last = date.fromisoformat(str(cached[-1]["date"]))
            if last < anchor:
                if horizon is not None and last >= horizon:
                    to_append.append((key, cached))
                else:
                    rebuild.append(key)  # 缺口超出装载窗口：续算不可靠，退回全量
                    rebuild_replace.add(key)
    if rebuild:
        for key, built in _build_for(conn_mgr, region_id, rebuild, anchor, sets, obs).items():
            out[key] = built.points
            # 初始化/兜底重建也落库：下次打开直接读表，不再全量算。
            _persist_points(conn_mgr, region_id, key, built.points, replace=key in rebuild_replace)
    if to_append:
        if anchor is None:
            anchor = _last_day(conn_mgr, region_id)
        if anchor is not None:
            append_keys = [key for key, _cached in to_append]
            if sets is None:
                sets = _member_sets(conn_mgr, append_keys)
            if obs is None:
                union: set[int] = set()
                for key in append_keys:
                    union |= sets[key]
                obs = _load_observations(
                    conn_mgr, region_id, union, anchor - timedelta(days=LOAD_WINDOW_DAYS - 1), anchor
                )
            for key, cached in to_append:
                out[key] = _append_missing_days(cached, obs, sets[key], anchor)
                # 只把**新增日期**写回表（历史点位不动）——「除初始化外只算今天」的落点。
                _persist_points(conn_mgr, region_id, key, out[key][len(cached) :])
    return out


# ════════════════════════════════════════════════════════════════
#  公开接口
# ════════════════════════════════════════════════════════════════

#: 进程内缓存：key → (过期 monotonic 时间, 值)。值只存**规范副本**，读出一律深拷贝。
_INDEX_MEMO: dict[tuple[Any, ...], tuple[float, Any]] = {}
_INDEX_MEMO_LOCK = threading.Lock()
_MEMO_MISS = object()


def _anchor_key(anchor: date | None) -> str | None:
    """锚定日 → 缓存 key 片段（`None` 表无数据）。"""
    return anchor.isoformat() if anchor is not None else None


def _cached_anchor(conn_mgr, region_id: int) -> date | None:
    """锚定日（`_last_day`）随指数结果一起缓存：该查询在真实库上实测 ~170ms，是缓存命中路径的
    主要残费；TTL 内复用同一锚定日即可（`refresh_index_daily` 清缓存后重新查）。
    """
    key = ("anchor", region_id)
    cached = _memo_lookup(key)
    if cached is not _MEMO_MISS:
        return cast("date | None", cached)
    anchor = _last_day(conn_mgr, region_id)
    _memo_store(key, anchor)
    return anchor


def _memo_lookup(key: tuple[Any, ...]) -> Any:
    """命中且未过期 → 返回深拷贝；未命中/已过期 → `_MEMO_MISS`。"""
    now = time.monotonic()
    with _INDEX_MEMO_LOCK:
        entry = _INDEX_MEMO.get(key)
        if entry is None:
            return _MEMO_MISS
        expires_at, value = entry
        if expires_at <= now:
            _INDEX_MEMO.pop(key, None)
            return _MEMO_MISS
    log.debug("大盘指数进程内缓存命中：%s", key)
    # 深拷贝：调用方（桥/测试）可能原地改返回的 list/dict，不能让它污染缓存规范值。
    return copy.deepcopy(value)


def _memo_store(key: tuple[Any, ...], value: Any) -> None:
    """写入缓存（值应视为不可变规范副本）；顺带清掉过期项，键数量有界。"""
    now = time.monotonic()
    with _INDEX_MEMO_LOCK:
        if len(_INDEX_MEMO) > 64:
            for stale in [k for k, (expires_at, _v) in _INDEX_MEMO.items() if expires_at <= now]:
                _INDEX_MEMO.pop(stale, None)
        _INDEX_MEMO[key] = (now + INDEX_MEMO_TTL_S, value)


def clear_index_memory_cache() -> None:
    """清空进程内指数缓存（`refresh_index_daily` 成功后自动调用；测试/价格刷新可显式调）。"""
    with _INDEX_MEMO_LOCK:
        _INDEX_MEMO.clear()


def refresh_index_daily(region_id: int = JITA_RID) -> int:
    """重建 `market.db.market_index_daily`（五个指数逐日点位），返回写入行数。

    成功重建后清空进程内指数缓存：物化点位已换新，旧缓存必须立即失效（不能等 TTL）。
    """
    conn_mgr = get_db()
    with conn_mgr.connect("mkt") as conn:
        conn.execute(MARKET_INDEX_DDL)

    built = _build_for(conn_mgr, region_id, INDEX_KEYS)
    rows: list[tuple[int, int, str, float, int]] = []
    for key in INDEX_KEYS:
        tid = INDEX_TYPE_IDS[key]
        for point in built[key].points:
            rows.append((tid, region_id, str(point["date"]), float(point["value"]), int(point["volume"])))

    with conn_mgr.connect("mkt") as conn:
        conn.execute("DELETE FROM market_index_daily WHERE region_id = ?", (region_id,))
        if rows:
            conn.executemany(
                "INSERT OR REPLACE INTO market_index_daily (type_id, region_id, date, price, volume) "
                "VALUES (?, ?, ?, ?, ?)",
                rows,
            )
    clear_index_memory_cache()
    return len(rows)


def _pct(value: float | None, base: float | None) -> float | None:
    """百分比涨幅；基数缺失/为 0 → `None`（不用 0 冒充）。"""
    if value is None or base is None or base <= 0:
        return None
    return (value / base - 1.0) * 100.0


def _value_before(points: Sequence[dict], days: int) -> float | None:
    """最后一个点往前 `days` 个日历天（含）之前最近一个点的点位；不够长 → `None`。"""
    if not points:
        return None
    cutoff = date.fromisoformat(str(points[-1]["date"])).toordinal() - days
    found: float | None = None
    for point in points:
        if date.fromisoformat(str(point["date"])).toordinal() <= cutoff:
            found = float(point["value"])
        else:
            break
    return found


def _cards_from_points(points_map: Mapping[str, Sequence[dict]]) -> list[dict]:
    """点位表 → 五张指数卡（`get_index_cards` / `get_dashboard` 共用这一份口径）。"""
    cards: list[dict] = []
    for key in INDEX_KEYS:
        points = points_map.get(key) or []
        card: dict = {
            "key": key,
            "label": INDEX_LABELS[key],
            "value": None,
            "chg1": None,
            "chg7": None,
            "chg30": None,
            "chg90": None,
            "chg180": None,
            "days": len(points),
            "base_date": str(points[0]["date"]) if points else None,
        }
        if len(points) >= 2:
            last = float(points[-1]["value"])
            card["value"] = last
            card["chg1"] = _pct(last, float(points[-2]["value"]))
            for name, days in CHG_WINDOWS[1:]:
                card[name] = _pct(last, _value_before(points, days))
        cards.append(card)
    return cards


def _series_from_points(
    conn_mgr,
    region_id: int,
    keys: Sequence[str],
    points_map: Mapping[str, Sequence[dict]],
    member_sets: Mapping[str, set[int]],
    obs: Mapping[int, Sequence[tuple[str, float, int]]] | None = None,
) -> list[dict]:
    """点位表 + 成分集 → 折线 + 篮子成员表（`get_index_series` / `get_dashboard` 共用）。

    成员字段与口径见 :func:`get_index_series` 的 docstring；`member_sets` 由调用方传入，
    于是成分集只算一遍。
    """
    anchors: dict[str, date] = {}
    for key in keys:
        points = points_map.get(key) or []
        if points:
            anchors[key] = date.fromisoformat(str(points[-1]["date"]))

    union: set[int] = set()
    for members in member_sets.values():
        union |= members
    if obs is None:
        loaded: dict[int, list[tuple[str, float, int]]] = {}
        if anchors and union:
            end = max(anchors.values())
            loaded = _load_observations(conn_mgr, region_id, union, end - timedelta(days=LOAD_WINDOW_DAYS - 1), end)
        obs = loaded
    names = _load_names(conn_mgr, union)

    out: list[dict] = []
    for key in keys:
        members_out: list[dict] = []
        anchor = anchors.get(key)
        weights = _weights_at(obs, member_sets[key], anchor) if anchor is not None else {}
        for tid, (weight, capped) in sorted(weights.items(), key=lambda item: -item[1][0]):
            members_out.append(_member_row(tid, weight, capped, names, obs, key, anchor))
        if MEMBER_SOURCES[key] == "fixed":
            listed = {row["typeId"] for row in members_out}
            for tid in sorted(member_sets[key] - listed):
                members_out.append(_member_row(tid, 0.0, False, names, obs, key, anchor))
        out.append(
            {
                "key": key,
                "label": INDEX_LABELS[key],
                "points": [{"date": str(p["date"]), "value": float(p["value"])} for p in (points_map.get(key) or [])],
                "members": members_out,
            }
        )
    return out


def get_index_cards(region_id: int = JITA_RID, _db=None) -> list[dict]:
    """五张指数卡：`[{key,label,value,chg1,chg7,chg30,chg90,chg180,days,base_date}]`。

    涨跌是百分比（`float`）；数据不足的窗口给 `None`（不用 0 冒充）。
    走进程内 TTL 缓存（`_db` 显式注入时不缓存，见模块 docstring「进程内缓存」）。
    """
    conn_mgr = _db or get_db()
    key: tuple[Any, ...] | None = None
    if _db is None:
        anchor = _cached_anchor(conn_mgr, region_id)
        key = ("cards", region_id, _anchor_key(anchor))
        cached = _memo_lookup(key)
        if cached is not _MEMO_MISS:
            return cast("list[dict[Any, Any]]", cached)
    result = _cards_from_points(_resolve_points(conn_mgr, region_id, INDEX_KEYS))
    if key is not None:
        _memo_store(key, result)
        return copy.deepcopy(result)
    return result


def get_index_series(keys: Sequence[str] | None = None, region_id: int = JITA_RID, _db=None) -> list[dict]:
    """指数折线 + 篮子成员表：`[{key,label,points:[{date,value}],members:[...]}]`。

    成员字段：`{typeId,name,weight,capped,price,chg30,source}`；`weight` 是该指数**最后一个指数日**
    的近 30 天成交额权重（准入 + 25% 上限后归一化），`price` = 该成员在同一锚定日（含）之前最近一次
    成交均价（当日没成交则取此前最近一次；完全没有 → `None`）。固定篮子（MPI/PLEX）恒列出全部固定成员
    （不满足准入的权重 0），其余篮子只列当日有正权重的成员。未知 key 直接忽略。
    走进程内 TTL 缓存（`_db` 显式注入时不缓存，见模块 docstring「进程内缓存」）。
    """
    conn_mgr = _db or get_db()
    wanted = [key for key in (keys if keys is not None else INDEX_KEYS) if key in INDEX_LABELS]
    if not wanted:
        return []
    # anchor / 成分集 / 观测各只算一次：优化前 `_resolve_points`（缺物化行时）与
    # `_series_from_points` 会各装一遍观测（736k 行 ~1.3s/遍）、`_member_sets` 跑两遍。
    anchor = _cached_anchor(conn_mgr, region_id)
    key: tuple[Any, ...] | None = None
    if _db is None:
        key = ("series", region_id, tuple(wanted), _anchor_key(anchor))
        cached = _memo_lookup(key)
        if cached is not _MEMO_MISS:
            return cast("list[dict[Any, Any]]", cached)
    member_sets = _member_sets(conn_mgr, wanted)
    union: set[int] = set()
    for members in member_sets.values():
        union |= members
    obs: Mapping[int, Sequence[tuple[str, float, int]]] | None = None
    if anchor is not None and union:
        obs = _load_observations(conn_mgr, region_id, union, anchor - timedelta(days=LOAD_WINDOW_DAYS - 1), anchor)
    points_map = _resolve_points(conn_mgr, region_id, wanted, anchor, member_sets, obs)
    result = _series_from_points(conn_mgr, region_id, wanted, points_map, member_sets, obs)
    if key is not None:
        _memo_store(key, result)
        return copy.deepcopy(result)
    return result


def get_dashboard(region_id: int = JITA_RID, _db=None) -> dict:
    """卡片 + 序列**一次算完** → `{"cards": [...], "series": [...]}`。

    形状与值同分别调 :func:`get_index_cards` / :func:`get_index_series` **逐字段一致**，
    区别只在「只算一遍」：成分集（官方 MER 篮子）、观测装载、逐日累乘都只跑一次，
    两个返回值从同一份中间结果派生。大盘页原先分别调那两个函数 —— 同一套计算整跑两遍
    （真实库实测合计约 13s，虽在后台线程不卡 UI，但没必要）。
    结果进进程内 TTL 缓存（切页/重开大盘命中 ~ms；`refresh_index_daily` 成功后清空）。
    """
    conn_mgr = _db or get_db()
    anchor = _cached_anchor(conn_mgr, region_id)
    key: tuple[Any, ...] | None = None
    if _db is None:
        key = ("dashboard", region_id, _anchor_key(anchor))
        cached = _memo_lookup(key)
        if cached is not _MEMO_MISS:
            return cast("dict[Any, Any]", cached)
    member_sets = _member_sets(conn_mgr, INDEX_KEYS)
    union: set[int] = set()
    for members in member_sets.values():
        union |= members
    obs: Mapping[int, Sequence[tuple[str, float, int]]] | None = None
    if anchor is not None and union:
        obs = _load_observations(conn_mgr, region_id, union, anchor - timedelta(days=LOAD_WINDOW_DAYS - 1), anchor)
    points_map = _resolve_points(conn_mgr, region_id, INDEX_KEYS, anchor, member_sets, obs)
    result = {
        "cards": _cards_from_points(points_map),
        "series": _series_from_points(conn_mgr, region_id, INDEX_KEYS, points_map, member_sets, obs),
    }
    if key is not None:
        _memo_store(key, result)
        return copy.deepcopy(result)
    return result


def _member_row(
    tid: int,
    weight: float,
    capped: bool,
    names: Mapping[int, str],
    obs: Mapping[int, Sequence[tuple[str, float, int]]],
    key: str,
    anchor: date | None,
) -> dict:
    rows = obs.get(tid) or []
    return {
        "typeId": tid,
        "name": names.get(tid, f"#{tid}"),
        "weight": weight,
        "capped": capped,
        "price": _last_price(rows, anchor),
        "chg30": _price_change(rows, REBALANCE_DAYS),
        "source": MEMBER_SOURCES[key],
    }


def get_breadth(region_id: int = JITA_RID, _db=None) -> dict:
    """最新交易日的市场广度：`{date,advancers,decliners,unchanged,turnover}`。

    统计口径：当日有成交均价、且此前有过成交的 type；`turnover` = 当日 Σ(volume × average)。
    没有数据 → 所有字段 `None`（不用 0 冒充）。
    """
    empty = {"date": None, "advancers": None, "decliners": None, "unchanged": None, "turnover": None}
    conn_mgr = _db or get_db()
    # 用**已补齐的成交锚点日**（不是各 type 自己最新的那天）：ESI 的尾部残缺日只有几百个
    # type 有数据，按它统计会把涨跌家数从 2,300+ 掉到 399，量价背离也跟着假报
    # （见 `COVERAGE_RATIO`）。
    anchor = _last_history_day(conn_mgr, region_id)
    if anchor is None:
        return empty
    latest = anchor.isoformat()

    with conn_mgr.connect("mkt") as conn:
        if not _table_exists(conn, "price_history"):
            return empty
        # ⚠️ 三个坑都踩过（实测真实库 116 万行）：
        # 1. `ROW_NUMBER() OVER (PARTITION BY type_id ...)`：加了 `(region_id, date)` 索引后改走
        #    「扫索引 + 临时 B 树排序」，`get_breadth` 从 2.04s 恶化到 10.16s；
        # 2. 「前一次观测」写成不限期窗口的 `GROUP BY type_id` 子查询：11.8s；
        # 3. 写成 `prev_days ⋈ cur ⋈ prev` 的 join：优化器会拿 `prev` 当驱动表并丢掉日期约束
        #    （`SEARCH prev ... (region_id=?)` = 扫该区域全部 110 万行 + 逐行主键探测），17.4~28.4s，
        #    连 `MATERIALIZED` 也治不住。
        # 正解 = **相关标量子查询**：`cur` 走 (region_id, date) 索引（当日 2,926 行），
        # 每个 type 再用主键 `(type_id, region_id, date)` 做一次倒序范围扫取前一次观测，
        # 并限制在 `RETURN_GAP_DAYS` 天内（日度广度不该拿一个月前的价格比）。实测 **0.05s**。
        rows = conn.execute(
            """SELECT cur.type_id, cur.average, cur.volume,
                      (SELECT p.average FROM price_history p
                        WHERE p.type_id = cur.type_id AND p.region_id = cur.region_id
                          AND p.date < cur.date AND p.date >= date(cur.date, ?)
                        ORDER BY p.date DESC LIMIT 1) AS prev
               FROM price_history cur
               WHERE cur.region_id = ? AND cur.date = ?""",
            (f"-{RETURN_GAP_DAYS} days", region_id, latest),
        ).fetchall()
    if not rows:
        return empty

    advancers = decliners = unchanged = 0
    turnover = 0.0
    for _tid, average, volume, prior in rows:  # 列序与 SELECT 一致：type_id, average, volume, prev
        now = float(average or 0.0)
        turnover += now * float(volume or 0)
        if prior is None:
            continue  # 30 天内没有前一次观测 → 算不出涨跌方向，只计成交额
        before = float(prior or 0.0)
        if now > before:
            advancers += 1
        elif now < before:
            decliners += 1
        else:
            unchanged += 1

    return {
        "date": latest,
        "advancers": advancers,
        "decliners": decliners,
        "unchanged": unchanged,
        "turnover": turnover,
    }
