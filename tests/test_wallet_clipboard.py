"""剪贴板解析测试 — services/wallet_import.py

覆盖（样本取自用户 2026-09-20 真机复制文本）:
  - parse_wallet_journal: 18 行真实流水；表头行 / 空行整行跳过
  - latest_balance: 同分钟取客户端顺序中更晚的那条（卖出后紧跟扣税）
  - parse_purchase_records: 负=买入 正=卖出 分流；单价列缺失时按总额/数量派生；脏行计入 unparsed
"""

import pytest

from services.wallet_import import latest_balance, parse_purchase_records, parse_wallet_journal

pytestmark = pytest.mark.fast

#: 真机「钱包 → 交易记录」样本（新 → 旧）
_JOURNAL = "\n".join(
    [
        "2026.09.20 07:15\t交易税\t-30,692 星币\t674,433,047 星币\t向SCC支付的销售税",
        "2026.09.20 07:15\t市场交易\t909,400 星币\t674,463,739 星币\t市场：Mad Bull从Meyer Hermann那里购买了物品",
        "2026.09.20 07:00\t交易税\t-186,975 星币\t673,554,339 星币\t向SCC支付的销售税",
        "2026.09.20 07:00\t市场交易\t5,540,000 星币\t673,741,314 星币\t市场：IRaidMarkets从Meyer Hermann那里购买了物品",
        "2026.09.20 06:58\t交易税\t-9,348 星币\t668,201,314 星币\t向SCC支付的销售税",
        "2026.09.20 06:58\t市场交易\t277,000 星币\t668,210,663 星币\t市场：Soul Fields从Meyer Hermann那里购买了物品",
        "2026.09.20 06:55\t交易税\t-294,435 星币\t667,933,663 星币\t向SCC支付的销售税",
        "2026.09.20 06:55\t市场交易\t8,724,000 星币\t668,228,098 星币\t市场：xinkebiao6从Meyer Hermann那里购买了物品",
        "2026.09.20 06:54\t交易税\t-588,870 星币\t659,504,098 星币\t向SCC支付的销售税",
        "2026.09.20 06:54\t市场交易\t17,448,000 星币\t660,092,968 星币\t市场：xinkebiao6从Meyer Hermann那里购买了物品",
        "2026.09.20 06:53\t交易税\t-18,697 星币\t642,644,968 星币\t向SCC支付的销售税",
        "2026.09.20 06:53\t市场交易\t554,000 星币\t642,663,665 星币\t市场：Vanessa Red从Meyer Hermann那里购买了物品",
        "2026.09.20 06:53\t交易税\t-9,348 星币\t642,109,665 星币\t向SCC支付的销售税",
        "2026.09.20 06:53\t市场交易\t277,000 星币\t642,119,014 星币\t市场：Toc Battinson从Meyer Hermann那里购买了物品",
        "2026.09.20 06:52\t交易税\t-9,348 星币\t641,842,014 星币\t向SCC支付的销售税",
        "2026.09.20 06:52\t市场交易\t277,000 星币\t641,851,363 星币\t市场：shirogane cinerea从Meyer Hermann那里购买了物品",
        "2026.09.20 06:48\t经纪人中介费\t-386,636 星币\t641,574,363 星币\tMeyer Hermann授权的支付给中介的市场订单佣金",
        "2026.09.20 06:43\t交易税\t-30,692 星币\t641,960,999 星币\t向SCC支付的销售税",
    ]
)

#: 真机「钱包 → 交易记录（交易页）」样本（新 → 旧，正=卖出 / 负=买入）
_PURCHASES = "\n".join(
    [
        "2026.09.19 13:23\t8\t多谱式涂层 II*\t277,800 星币\t2,222,400 星币\tReleks\t吉他 IV - 卫星 4 - 加达里海军 组装车间*\tMeyer Hermann\t主账户",
        "2026.09.19 13:18\t2\t多谱式涂层 II*\t277,800 星币\t555,600 星币\tHPG\t吉他 IV - 卫星 4 - 加达里海军 组装车间*\tMeyer Hermann\t主账户",
        "2026.09.19 13:17\t2\t多谱式涂层 II*\t277,800 星币\t555,600 星币\tJeanne Hurt\t吉他 IV - 卫星 4 - 加达里海军 组装车间*\tMeyer Hermann\t主账户",
        "2026.09.19 13:17\t3\t轻型装甲维护机器人 II*\t448,400 星币\t1,345,200 星币\tJeanne Hurt\t吉他 IV - 卫星 4 - 加达里海军 组装车间*\tMeyer Hermann\t主账户",
        "2026.09.19 07:11\t8\t船体扫描器 II*\t910,700 星币\t7,285,600 星币\tDogsuperhero doghouse\t吉他 IV - 卫星 4 - 加达里海军 组装车间*\tMeyer Hermann\t主账户",
        "2026.09.19 04:22\t1\t重型跃迁扰频器 I*\t41,720,000 星币\t-41,720,000 星币\tDirrty Harry\t吉他 IV - 卫星 4 - 加达里海军 组装车间*\tMeyer Hermann\t主账户",
        "2026.09.19 04:18\t10\t轻型装甲维护机器人 II*\t448,800 星币\t4,488,000 星币\tleekedleek\t吉他 IV - 卫星 4 - 加达里海军 组装车间*\tMeyer Hermann\t主账户",
        "2026.09.19 04:17\t13\t小型等离子立体炸弹 I*\t84,670 星币\t-1,100,710 星币\tFrank Castlemain\t吉他 IV - 卫星 4 - 加达里海军 组装车间*\tMeyer Hermann\t主账户",
        "2026.09.19 04:17\t1\t小型等离子立体炸弹 I*\t84,500 星币\t-84,500 星币\tRael Hanomaa\t吉他 IV - 卫星 4 - 加达里海军 组装车间*\tMeyer Hermann\t主账户",
        "2026.09.19 04:17\t9\t小型等离子立体炸弹 I*\t84,490 星币\t-760,410 星币\tMaxa X\t吉他 IV - 卫星 4 - 加达里海军 组装车间*\tMeyer Hermann\t主账户",
        "2026.09.19 04:17\t53\t小型等离子立体炸弹 I*\t84,480 星币\t-4,477,440 星币\tKrar Wisht\t吉他 IV - 卫星 4 - 加达里海军 组装车间*\tMeyer Hermann\t主账户",
    ]
)


class TestParseWalletJournal:
    def test_real_sample_rows(self):
        """18 行流水全部解析，金额/余额去千分位与「星币」后缀。"""
        rows = parse_wallet_journal(_JOURNAL)
        assert len(rows) == 18
        assert rows[0] == {
            "time": "2026.09.20 07:15",
            "kind": "交易税",
            "amount": -30692.0,
            "balance": 674433047.0,
            "note": "向SCC支付的销售税",
        }
        assert rows[-1]["kind"] == "交易税"

    @pytest.mark.parametrize(
        ("label", "raw"),
        [
            ("空文本", ""),
            ("只有表头", "日期\t类型\t金额\t余额\t说明"),
            ("列数不足", "2026.09.20 07:15\t交易税\t-30,692 星币"),
            ("余额不是数字", "2026.09.20 07:15\t交易税\t-30,692 星币\t若干 星币\t备注"),
            ("缺少时间列", "交易税\t-30,692 星币\t674,433,047 星币\t向SCC支付的销售税"),
        ],
    )
    def test_unrecognized_lines_dropped(self, label, raw):
        assert parse_wallet_journal(raw) == [], label


class TestLatestBalance:
    def test_same_minute_takes_later_row(self):
        """07:15 有两条：先卖出（674,463,739）后扣税（674,433,047）—— 客户端复制里税那条在前。"""
        assert latest_balance(parse_wallet_journal(_JOURNAL)) == (674433047.0, "2026.09.20 07:15")

    @pytest.mark.parametrize("rows", [[], parse_wallet_journal(""), parse_wallet_journal("日期\t类型\t金额\t余额")])
    def test_no_rows_gives_none(self, rows):
        assert latest_balance(rows) is None


class TestParsePurchaseRecords:
    def test_real_sample_splits_buy_and_sell(self):
        """11 行里 5 行买入（负数）入库、6 行卖出（正数）跳过，物品名去尾 `*`。"""
        rows, stats = parse_purchase_records(_PURCHASES)
        assert stats == {"sales": 6, "unparsed": 0}
        assert [r["raw_name"] for r in rows] == [
            "重型跃迁扰频器 I",
            "小型等离子立体炸弹 I",
            "小型等离子立体炸弹 I",
            "小型等离子立体炸弹 I",
            "小型等离子立体炸弹 I",
        ]
        assert rows[0] == {
            "time": "2026.09.19 04:22",
            "raw_name": "重型跃迁扰频器 I",
            "qty": 1,
            "unit_price": 41720000.0,
            "seller": "Dirrty Harry",
        }
        assert rows[1]["qty"] == 13 and rows[1]["unit_price"] == 84670.0
        assert rows[-1]["seller"] == "Krar Wisht"

    def test_unit_price_derived_when_column_missing(self):
        """单价列空时按 |总额| / 数量 派生（游戏偶尔把单价列留空）。"""
        raw = "2026.09.19 04:22\t10\t凡晶石*\t\t-1,000 星币\t某某"
        rows, stats = parse_purchase_records(raw)
        assert stats == {"sales": 0, "unparsed": 0}
        assert rows[0]["unit_price"] == 100.0

    @pytest.mark.parametrize(
        ("label", "raw", "unparsed"),
        [
            ("空文本", "", 0),
            ("只有表头", "日期\t数量\t物品\t单价\t总额", 1),
            ("列数不足", "2026.09.19 04:22\t10\t凡晶石*", 1),
            ("数量非正整数", "2026.09.19 04:22\t0\t凡晶石*\t100 星币\t-1,000 星币", 1),
            ("总额不是数字", "2026.09.19 04:22\t10\t凡晶石*\t100 星币\t若干", 1),
            ("缺物品名", "2026.09.19 04:22\t10\t\t100 星币\t-1,000 星币", 1),
        ],
    )
    def test_dirty_lines_counted(self, label, raw, unparsed):
        rows, stats = parse_purchase_records(raw)
        assert rows == [], label
        assert stats["unparsed"] == unparsed, label

    def test_all_sales_gives_no_rows(self):
        raw = "\n".join(
            [
                "2026.09.19 13:23\t8\t多谱式涂层 II*\t277,800 星币\t2,222,400 星币\tReleks",
                "2026.09.19 13:18\t2\t多谱式涂层 II*\t277,800 星币\t555,600 星币\tHPG",
            ]
        )
        rows, stats = parse_purchase_records(raw)
        assert rows == []
        assert stats == {"sales": 2, "unparsed": 0}
