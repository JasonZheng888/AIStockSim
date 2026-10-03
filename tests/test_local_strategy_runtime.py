"""Local execution regressions. All stores and quotes are isolated fixtures."""
import datetime as dt
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import StockTradingSim as sim
from local_strategy_panel import LocalStrategyPanel, describe_evidence
from local_strategy_runtime import completed_bars, next_session, order_quantity, quote_freshness_error, session_close

CALENDAR = {"markets": {"cn": {"closed_dates": [f"2026-10-{day:02d}" for day in range(1, 8)]},
                         "hk": {"closed_dates": ["2026-10-01"], "half_days": ["2026-02-16"]}}}
NOW = dt.datetime(2026, 10, 8, 10, 0)


class FixedDateTime(dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW if tz is None else NOW.replace(tzinfo=tz)


def bar(day, close=10):
    return {"date": day, "open": close, "high": close + 1, "low": close - 1, "close": close}


def market_quote(code="sh600000", price=10, now=NOW):
    return sim.Quote(code, "测试证券", price, 0, 0, now.strftime("%H:%M:%S"), "fixture", "CNY", now.date().isoformat())


def memory_store():
    store = sim.PortfolioStore.__new__(sim.PortfolioStore)
    store.data = store._default()
    store.save = Mock()
    return store


def local_order(**overrides):
    return {"id": "fixture-order", "code": "sh600000", "action": "BUY", "status": "ACTIVE",
            "qty": 100, "limit_price": 10, "local_signal_id": "fixture-signal", "signal_confirmed_at": "2026-09-30",
            "structure_stop": 9, "valid_session": "2026-10-08", **overrides}


class LocalSessionAndQuoteTests(unittest.TestCase):
    def test_next_session_and_half_day(self):
        self.assertEqual(next_session("2026-09-30", "sh600000", CALENDAR), "2026-10-08")
        self.assertEqual(next_session("2026-09-30", "hk01810", CALENDAR), "2026-10-02")
        self.assertEqual(session_close("2026-02-16", "hk01810", CALENDAR), dt.datetime(2026, 2, 16, 12))

    def test_daily_bar_enters_only_after_close_and_buffer(self):
        bars = [bar("2026-09-29"), bar("2026-09-30"), bar("2026-10-08")]
        before, _ = completed_bars(bars, "sh600000", dt.datetime(2026, 9, 30, 15, 4, 59), CALENDAR)
        after, _ = completed_bars(bars, "sh600000", dt.datetime(2026, 9, 30, 15, 5), CALENDAR)
        self.assertEqual([b["date"] for b in before], ["2026-09-29"])
        self.assertEqual([b["date"] for b in after], ["2026-09-29", "2026-09-30"])
        hk, _ = completed_bars([bar("2026-02-13"), bar("2026-02-16")], "hk01810", dt.datetime(2026, 2, 16, 12, 5), CALENDAR)
        self.assertEqual(len(hk), 2)

    def test_invalid_bar_breaks_history_instead_of_splicing(self):
        bars = [bar("2026-09-25"), {**bar("2026-09-28"), "high": 1}, bar("2026-09-29"), bar("2026-09-30")]
        result, warnings = completed_bars(bars, "sh600000", NOW, CALENDAR)
        self.assertEqual([b["date"] for b in result], ["2026-09-29", "2026-09-30"])
        self.assertTrue(warnings)

    def test_quote_requires_valid_price_date_and_fresh_time(self):
        for price in (0, -1, float("nan"), float("inf")):
            self.assertIsNotNone(quote_freshness_error(market_quote(price=price), NOW))
        self.assertIsNotNone(quote_freshness_error(market_quote(now=NOW-dt.timedelta(days=1)), NOW))
        for seconds, accepted in ((-300, True), (-301, False), (60, True), (61, False)):
            error = quote_freshness_error(market_quote(now=NOW+dt.timedelta(seconds=seconds)), NOW)
            self.assertEqual(error is None, accepted)

    def test_explicit_share_quantity_never_silently_rounds_or_scales(self):
        self.assertEqual(order_quantity({}, "sh688820", 200), 200)
        for value in (201, 20000, "300"):
            self.assertEqual(order_quantity({"local_order_quantities": {"sh688820": value}}, "sh688820", 200), int(value))
        for value in (200.9, True, float("nan"), "bad"):
            self.assertEqual(order_quantity({"local_order_quantities": {"sh688820": value}}, "sh688820", 200), 0)


class LocalOrderLifecycleTests(unittest.TestCase):
    def matching_host(self, order, quote=None):
        store = memory_store()
        store.data["pending_orders"] = [order]
        return SimpleNamespace(store=store, quote_cache={"sh600000": quote} if quote else {},
                               risk_violations_for_order=Mock(return_value=[]))

    def run_matching(self, host):
        with patch.object(sim.dt, "datetime", FixedDateTime), patch.object(sim, "today_str", return_value=NOW.date().isoformat()), \
             patch.object(sim, "load_trading_calendar", return_value=CALENDAR), patch.object(sim, "trading_time_error", return_value=None):
            return sim.MainWindow.try_execute_pending_orders(host)

    def test_old_valid_session_does_not_expire_or_release_order(self):
        host = self.matching_host(local_order(valid_session="2026-09-30"))
        self.assertEqual(self.run_matching(host), 0)
        self.assertEqual(host.store.data["pending_orders"][0]["status"], "ACTIVE")
        self.assertEqual(host.store.reserved_cash(), 1000)

    def test_below_stop_fills_buy_instead_of_cancelling(self):
        host = self.matching_host(local_order(), market_quote(price=8.5))
        self.assertEqual(self.run_matching(host), 1)
        self.assertEqual(host.store.data["pending_orders"][0]["status"], "FILLED")
        self.assertEqual(host.store.data["lots"][0]["structure_stop"], 9)

    def test_stale_quote_and_same_day_signal_wait(self):
        for order, quote in ((local_order(), market_quote(now=NOW-dt.timedelta(days=1))),
                             (local_order(signal_confirmed_at=NOW.date().isoformat()), market_quote())):
            host = self.matching_host(order, quote)
            self.assertEqual(self.run_matching(host), 0)
            self.assertEqual(host.store.data["pending_orders"][0]["status"], "ACTIVE")

    def test_local_exit_only_consumes_local_lots_even_when_manual_older(self):
        host = self.matching_host(local_order(action="SELL", limit_price=9), market_quote())
        host.store.data["lots"] = [
            {"code": "sh600000", "name": "手工仓", "qty": 200, "buy_date": "2026-09-29", "buy_price": 10},
            {"code": "sh600000", "name": "本地仓", "qty": 100, "buy_date": "2026-09-30", "buy_price": 10,
             "local_signal_id": "entry", "structure_stop": 9}]
        self.assertEqual(self.run_matching(host), 1)
        self.assertEqual([(lot["name"], lot["qty"]) for lot in host.store.data["lots"]], [("手工仓", 200)])


class CandidateAndDispatchTests(unittest.TestCase):
    def panel_host(self, now=NOW, lots=None):
        store = memory_store()
        store.data["lots"] = lots or []
        store.is_strategy_enabled = Mock(return_value=True)
        host = SimpleNamespace(store=store, quote_cache={"sh600000": market_quote(now=now)},
                               daily_kline_dicts=Mock(return_value=[bar("2026-09-30")]),
                               risk_violations_for_order=Mock(return_value=[]), strategy_enabled=Mock(return_value=True),
                               try_execute_pending_orders=Mock(), status=SimpleNamespace(setText=Mock()))
        return SimpleNamespace(host=host, mode=SimpleNamespace(currentData=lambda: "first_second_third"), _analysis_cache={})

    def candidate(self, panel, now=NOW, signal=None):
        signal = signal or {"signal": "buy", "status": "confirmed", "pattern": "proxy_3buy", "signal_id": "fixture-signal",
                            "confirmed_date": "2026-09-30", "reference_price": 10, "stop_price": 9}
        with patch("local_strategy_panel.analyze_chan", return_value=signal), patch.object(sim, "trading_time_error", return_value=None), \
             patch.object(sim, "today_str", return_value=now.date().isoformat()):
            return LocalStrategyPanel._candidate(panel, "sh600000", now, CALENDAR)

    def test_confirmation_day_and_future_wait_but_old_signal_remains_eligible(self):
        for stamp in (dt.datetime(2026, 9, 30, 15, 6), dt.datetime(2026, 9, 29, 10)):
            self.assertFalse(self.candidate(self.panel_host(stamp), stamp)["eligible"])
        self.assertTrue(self.candidate(self.panel_host())["eligible"])
        later = dt.datetime(2026, 10, 20, 10)
        self.assertTrue(self.candidate(self.panel_host(later), later)["eligible"])

    def test_existing_holding_and_cancelled_same_signal_allow_manual_repeat(self):
        panel = self.panel_host(lots=[{"code": "sh600000", "qty": 100, "buy_date": "2026-09-30", "buy_price": 10}])
        panel.host.store.data["pending_orders"] = [local_order(status="CANCELLED", local_signal_id="sh600000:fixture-signal")]
        row = self.candidate(panel)
        self.assertTrue(row["eligible"])
        with patch.object(sim, "trading_time_error", return_value=None):
            LocalStrategyPanel._submit(panel, row)
            LocalStrategyPanel._submit(panel, row)
        self.assertEqual(len(panel.host.store.active_pending_orders()), 2)
        self.assertTrue(all(not item.get("local_auto_event_id") for item in panel.host.store.active_pending_orders()))

    def test_exact_quantity_blocks_unaffordable_instead_of_shrinking(self):
        panel = self.panel_host()
        panel.host.store.strategy_config()["local_order_quantities"] = {"sh600000": 60000}
        row = self.candidate(panel)
        self.assertEqual(row["quantity"], 60000)
        self.assertFalse(row["eligible"])
        self.assertIn("可用资金不足", row["reason"])

    def test_sell_candidates_only_include_local_origin_and_respect_t_plus_one(self):
        local = {"code": "sh600000", "name": "本地", "qty": 100, "buy_date": "2026-10-08", "buy_price": 10,
                 "local_signal_id": "entry-today", "structure_stop": 11}
        manual = {"code": "sh600000", "name": "手工", "qty": 900, "buy_date": "2026-09-30", "buy_price": 10}
        panel = self.panel_host(lots=[manual, local])
        row = self.candidate(panel, signal={"signal": "wait"})
        self.assertFalse(row["eligible"])
        self.assertEqual(row["quantity"], 0)
        local["buy_date"] = "2026-09-30"
        row = self.candidate(panel, signal={"signal": "wait"})
        self.assertTrue(row["eligible"])
        self.assertEqual(row["quantity"], 100)

    def test_automatic_dispatch_once_survives_restart_and_cancel_manual_repeat_allowed(self):
        panel = self.panel_host()
        row = self.candidate(panel)
        panel.rows = [row]
        panel.automatic = SimpleNamespace(isChecked=lambda: True)
        panel.refresh_rows = Mock()
        panel._calendar = lambda: CALENDAR
        panel._candidate = Mock(return_value=row)
        panel._submit = lambda item, **kwargs: LocalStrategyPanel._submit(panel, item, **kwargs)
        with patch.object(sim.dt, "datetime", FixedDateTime), patch.object(sim, "trading_time_error", return_value=None):
            LocalStrategyPanel.on_quotes_refreshed(panel)
            LocalStrategyPanel.on_quotes_refreshed(panel)
            self.assertEqual(len(panel.host.store.data["pending_orders"]), 1)
            order = panel.host.store.data["pending_orders"][0]
            self.assertTrue(order.get("local_auto_event_id"))
            order["status"] = "CANCELLED"
            panel.host.store.strategy_config().pop("local_auto_events")
            LocalStrategyPanel.on_quotes_refreshed(panel)
            self.assertEqual(len(panel.host.store.data["pending_orders"]), 1)
            LocalStrategyPanel._submit(panel, row)
        self.assertEqual(len(panel.host.store.data["pending_orders"]), 2)

    def test_automatic_off_does_not_submit_stop_but_retains_trigger_for_later(self):
        panel = self.panel_host(lots=[{"code": "sh600000", "qty": 100, "buy_date": "2026-10-08", "buy_price": 10,
                                     "local_signal_id": "entry", "structure_stop": 11}])
        panel.automatic = SimpleNamespace(isChecked=lambda: False)
        panel.refresh_rows = Mock()
        with patch.object(sim.dt, "datetime", FixedDateTime), patch.object(sim, "trading_time_error", return_value=None):
            LocalStrategyPanel.on_quotes_refreshed(panel)
        self.assertTrue(panel.host.store.data["lots"][0]["stop_triggered"])
        self.assertEqual(panel.host.store.data["pending_orders"], [])

    def test_evidence_is_human_readable(self):
        text = describe_evidence({"classification": "trend", "center_band": [10, 12], "area_ratio": .4,
                                  "entry_dates": ["2026-01-01", "2026-02-01"], "confirmation": "right_bar_closed"})
        self.assertIn("趋势背驰", text)
        self.assertIn("40.0%", text)
        self.assertIn("次级别走势完成尚未验证", text)


if __name__ == "__main__":
    unittest.main()
