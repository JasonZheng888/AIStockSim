"""Trading/data regressions using in-memory stores and stubbed market feeds."""

import copy
import datetime as dt
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from StockTradingSim import MainWindow, PortfolioStore, Quote, QuoteService, today_str


def store_in_memory():
    store = PortfolioStore.__new__(PortfolioStore)
    store.data = store._default()
    store.save = Mock()
    return store


def quote(code="sh600000", price=10.0):
    return Quote(code, "测试证券", price, 0, 0, "10:00:00", "fixture", "HKD" if code.startswith("hk") else "CNY")


def lot(code, qty, date):
    return {"code": code, "name": "测试证券", "qty": qty, "buy_price": 10.0,
            "actual_price": 10.0, "breakeven_price": 10.0, "buy_date": date}


class TradeRuleTests(unittest.TestCase):
    def setUp(self):
        self.store = store_in_memory()

    def test_star_market_accepts_single_share_increments_and_whole_odd_remainder(self):
        self.store.validate_buy_quantity("sh688001", 201)
        self.store.validate_sell_quantity("sh688001", 201, 401)
        self.store.validate_sell_quantity("sh688001", 199, 199)
        with self.assertRaises(ValueError):
            self.store.validate_buy_quantity("sh688001", 199)
        with self.assertRaises(ValueError):
            self.store.validate_sell_quantity("sh688001", 100, 199)

    def test_indices_are_not_securities_and_shenzhen_bank_is_not_an_index(self):
        for code in ("sh000001", "sh000300", "sz399001"):
            with self.subTest(code=code), self.assertRaises(ValueError):
                self.store.buy(quote(code), 100)
        self.store.validate_buy_quantity("sz000001", 100)
        self.assertEqual(self.store.data["trades"], [])

    def test_hong_kong_day_trade_and_mainland_t_plus_one(self):
        self.store.buy(quote("hk01810"), 200)
        self.assertEqual(self.store.positions()["hk01810"]["available"], 200)
        self.store.sell(quote("hk01810", 11.0), 200)
        self.assertNotIn("hk01810", self.store.positions())
        self.store.buy(quote(), 100)
        self.assertEqual(self.store.positions()["sh600000"]["available"], 0)
        with self.assertRaises(ValueError):
            self.store.sell(quote(), 100)

    def test_failed_sale_does_not_partially_consume_available_lots(self):
        yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
        self.store.data["lots"] = [lot("sh600000", 100, yesterday), lot("sh600000", 100, today_str())]
        before = copy.deepcopy(self.store.data)
        with self.assertRaises(ValueError):
            self.store.sell(quote(), 200)
        self.assertEqual(self.store.data, before)
        self.store.save.assert_not_called()

    def test_sale_validates_all_lots_before_mutation(self):
        yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
        damaged = lot("sh600000", 100, yesterday)
        damaged["breakeven_price"] = "invalid"
        self.store.data["lots"] = [lot("sh600000", 100, yesterday), damaged]
        before = copy.deepcopy(self.store.data)
        with self.assertRaises(ValueError):
            self.store.sell(quote(), 200)
        self.assertEqual(self.store.data, before)


class MarketDataRegressionTests(unittest.TestCase):
    def test_manual_refresh_covers_all_requested_symbols_in_one_action(self):
        codes = [f"sh60{index:04d}" for index in range(21)]
        service = Mock()
        service.fetch_daily_klines.return_value = {}
        service.fetch_intraday_points.return_value = {}
        win = SimpleNamespace(_daily_kline_last_fetch=dt.datetime.now(), _intraday_last_fetch=dt.datetime.now(),
                              quotes=service, daily_kline_cache={}, intraday_cache={},
                              store=SimpleNamespace(refresh_seconds=3), write_codex_kline_history=Mock())
        MainWindow.refresh_daily_klines(win, codes, force=True)
        MainWindow.refresh_intraday_points(win, codes, force=True)
        self.assertEqual(set(service.fetch_daily_klines.call_args.args[0]), set(codes))
        self.assertEqual(set(service.fetch_intraday_points.call_args.args[0]), set(codes))

    def test_daily_batches_reach_beyond_sixteen_even_when_first_requests_fail(self):
        codes = [f"sh60{index:04d}" for index in range(21)]
        service = Mock()
        service.fetch_daily_klines.return_value = {}
        win = SimpleNamespace(_daily_kline_last_fetch=None, quotes=service, daily_kline_cache={},
                              write_codex_kline_history=Mock())
        for _ in range(6):
            win._daily_kline_last_fetch = None
            MainWindow.refresh_daily_klines(win, codes)
        calls = [call.args[0] for call in service.fetch_daily_klines.call_args_list]
        self.assertEqual(set(code for batch in calls for code in batch), set(codes))
        self.assertTrue(all(len(batch) <= 4 for batch in calls))

    def test_current_day_bar_refreshes_after_cooldown(self):
        code = "sh600000"
        old_bar, new_bar = SimpleNamespace(date=today_str(), close=10), SimpleNamespace(date=today_str(), close=12)
        service = Mock()
        service.fetch_daily_klines.return_value = {code: [new_bar]}
        win = SimpleNamespace(_daily_kline_last_fetch=None, quotes=service, daily_kline_cache={code: [old_bar]},
                              write_codex_kline_history=Mock())
        MainWindow.refresh_daily_klines(win, [code])
        self.assertEqual(win.daily_kline_cache[code][-1].close, 12)
        win._daily_kline_last_fetch = None
        MainWindow.refresh_daily_klines(win, [code])
        self.assertEqual(service.fetch_daily_klines.call_count, 1)
        win._daily_kline_fetched_at[code] -= dt.timedelta(minutes=31)
        win._daily_kline_attempted_at[code] -= dt.timedelta(minutes=31)
        MainWindow.refresh_daily_klines(win, [code])
        self.assertEqual(service.fetch_daily_klines.call_count, 2)

    def test_intraday_batches_rotate_over_entire_watchlist(self):
        codes = [f"sh60{index:04d}" for index in range(21)]
        service = Mock()
        service.fetch_intraday_points.return_value = {}
        win = SimpleNamespace(_intraday_last_fetch=None, quotes=service, intraday_cache={},
                              store=SimpleNamespace(refresh_seconds=3))
        for _ in range(6):
            win._intraday_last_fetch = None
            MainWindow.refresh_intraday_points(win, codes)
        calls = [call.args[0] for call in service.fetch_intraday_points.call_args_list]
        self.assertEqual(set(code for batch in calls for code in batch), set(codes))
        self.assertTrue(all(len(batch) <= 4 for batch in calls))

    def test_breakout_reference_excludes_current_day_high(self):
        yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
        bars = [SimpleNamespace(date=yesterday, close=100, high=101, low=99, volume=100),
                SimpleNamespace(date=today_str(), close=109, high=110, low=100, volume=200)]
        win = SimpleNamespace(daily_kline_cache={"sh600000": bars}, avg=MainWindow.avg,
                              daily_rsi_value=Mock(return_value=None), macd_profile=Mock(return_value={}),
                              kdj_profile=Mock(return_value={}))
        profile = MainWindow.technical_profile(win, "sh600000")
        self.assertEqual(profile["high_60"], 110)
        self.assertEqual(profile["prior_high_60"], 101)


class QuoteEncodingAndTimestampTests(unittest.TestCase):
    def setUp(self):
        self.service = QuoteService.__new__(QuoteService)
        self.service.session = Mock()

    def test_sina_decodes_utf8_and_gb18030_without_replacement_characters(self):
        cn = ["0"] * 34
        cn[0], cn[2], cn[3], cn[30], cn[31] = "ST 测试𠀀", "10", "11", "2026-09-30", "15:00:00"
        hk = ["0"] * 25
        hk[0], hk[1], hk[3], hk[6], hk[17], hk[18] = "XIAOMI-W", "小米集团－Ｗ", "10", "11", "2026/10/02", "16:08:15"
        response = f'var hq_str_sh600000="{",".join(cn)}";\nvar hq_str_rt_hk01810="{",".join(hk)}";'
        for encoding in ("utf-8", "utf-8-sig", "gb18030"):
            with self.subTest(encoding=encoding):
                self.service.session.get.return_value = SimpleNamespace(content=response.encode(encoding))
                quotes = {}
                self.service._fetch_sina(["sh600000", "hk01810"], quotes)
                self.assertEqual(quotes["sh600000"].name, "ST 测试𠀀")
                self.assertEqual(quotes["sh600000"].asof_date, "2026-09-30")
                self.assertEqual(quotes["sh600000"].time_label, "15:00:00")
                self.assertEqual(quotes["hk01810"].name, "小米集团－Ｗ")
                self.assertEqual(quotes["hk01810"].asof_date, "2026-10-02")

    def test_eastmoney_epoch_is_retained_as_exchange_date_and_time(self):
        timestamp = int(dt.datetime(2026, 9, 30, 7, 8, 9, tzinfo=dt.timezone.utc).timestamp())
        payload = {"data": {"diff": [{"f12": "01810", "f14": "小米集团－Ｗ", "f2": 40,
                                       "f3": 1, "f4": 0.4, "f124": timestamp}]}}
        self.service.session.get.return_value.json.return_value = payload
        quotes = {}
        self.service._fetch_hk_eastmoney(["hk01810"], quotes)
        self.assertEqual(quotes["hk01810"].asof_date, "2026-09-30")
        self.assertEqual(quotes["hk01810"].time_label, "15:08:09")

    def test_missing_or_invalid_dates_are_not_replaced_with_today(self):
        self.assertEqual(quote().asof_date, "")
        for invalid in (None, "", "-", "2026-02-30"):
            self.assertEqual(self.service._normalize_quote_date(invalid), "")


class DailyKlineContinuityTests(unittest.TestCase):
    def parse(self, payload):
        service = QuoteService.__new__(QuoteService)
        service.session = Mock()
        service.session.get.return_value.json.return_value = payload
        return service._fetch_daily_kline("sz300308")

    def test_invalid_ohlc_and_truncated_rows_break_history(self):
        first = "2026-09-28,10,10,11,9,100,1000,0,0,0,1"
        last = "2026-09-30,12,12,13,11,100,1200,0,0,0,1"
        invalid_rows = [
            "2026-09-29,-1,10,11,9,100,1000,0,0,0,1",
            "2026-09-29,10,0,11,9,100,1000,0,0,0,1",
            "2026-09-29,10,10,nan,9,100,1000,0,0,0,1",
            "2026-09-29,10,10,inf,9,100,1000,0,0,0,1",
            "2026-09-29,10,12,11,9,100,1000,0,0,0,1",
            "2026-09-29,10,10,11,12,100,1000,0,0,0,1",
            "2026-09-29,10,10",
        ]
        for invalid in invalid_rows:
            with self.subTest(invalid=invalid):
                rows = self.parse({"data": {"klines": [first, invalid, last]}})
                self.assertEqual([row.date for row in rows], ["2026-09-30"])
                self.assertIn("前史已截断", rows[0].source)
        untouched = self.parse({"data": {"klines": [first, last]}})
        self.assertEqual(len(untouched), 2)
        self.assertEqual(untouched[0].source, "东方财富日K")

    def test_last_invalid_row_returns_no_spliced_earlier_history(self):
        rows = self.parse({"data": {"klines": ["2026-09-28,10,10,11,9,100,1000,0,0,0,1", "2026-09-29"]}})
        self.assertEqual(rows, [])

    def test_recorded_eastmoney_payload_matches_research_continuous_suffix(self):
        directory = Path(__file__).resolve().parents[1] / "build" / "backtest-data"
        raw_path = directory / "raw" / "sz300308-eastmoney.json"
        normalized_path = directory / "sz300308.json"
        if not raw_path.is_file() or not normalized_path.is_file():
            self.skipTest("Optional recorded market fixtures are not installed")
        payload = json.loads(raw_path.read_text(encoding="utf-8"))
        research = json.loads(normalized_path.read_text(encoding="utf-8"))["klines"]
        rows = self.parse(payload)
        self.assertEqual(len(payload["data"]["klines"]), 3351)
        self.assertEqual(len(rows), 2969)
        self.assertEqual(rows[0].date, "2013-11-08")
        self.assertTrue(all("前史已截断" in row.source for row in rows))
        self.assertEqual([(row.date, row.open, row.high, row.low, row.close) for row in rows],
                         [(row["date"], row["open"], row["high"], row["low"], row["close"]) for row in research])


class StrategyScoringRegressionTests(unittest.TestCase):
    def scoring_window(self):
        win = SimpleNamespace(store=store_in_memory(), money_flow_cache={}, quote_cache={},
                              strategy_enabled=Mock(return_value=True),
                              relative_strength_percentile=Mock(return_value=90),
                              clamp_score=MainWindow.clamp_score, intraday_profile=Mock(return_value={"above_vwap": True}),
                              technical_profile=Mock(return_value={"status": "ok", "ma_status": "多头排列",
                                                                  "high_60": 112, "prior_high_60": 100,
                                                                  "ma": {"ma20": 98, "ma60": 95}, "volume_ratio_5_20": 1.5}))
        win.market_gate_profile = lambda code=None: MainWindow.market_gate_profile(win, code)
        return win

    def test_overextended_price_is_not_scored_as_near_buy_point(self):
        win = self.scoring_window()
        profile = MainWindow.canslim_profile_for_code(win, "sh600000", quote(price=110),
                                                      {"gate": "green", "label": "绿灯"})
        self.assertEqual(profile["components"]["setup"], 35)
        self.assertIn("偏远", profile["setup"])

    def test_hong_kong_does_not_inherit_mainland_red_gate(self):
        win = self.scoring_window()
        profile = MainWindow.canslim_profile_for_code(win, "hk01810", quote("hk01810", 100),
                                                      {"gate": "red", "label": "红灯"})
        self.assertEqual(profile["market_gate"], "港股数据缺失")
        self.assertTrue(any("港股基准" in item for item in profile["missing"]))
        win.account_equity_estimate = Mock(return_value=500000)
        win.store.data["risk"]["block_new_position_near_close"] = False
        violations = MainWindow.risk_violations_for_order(win, "buy", quote("hk01810", 100), 200, 100)
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
