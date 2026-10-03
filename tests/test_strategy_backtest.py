"""Execution invariants using synthetic bars; no user's portfolio is accessed."""
from pathlib import Path
import tempfile
import unittest

from strategy_backtest import run_backtest
from scripts.run_strategy_backtest import render_report


def bar(day, open_=10, close=10, high=11, low=9.5, volume=1000):
    return {"date": f"2026-09-{day:02d}", "open": open_, "close": close,
            "high": high, "low": low, "volume": volume}


def signals(mapping, observed=None):
    def evaluate(prefix, mode="first_second_third"):
        if observed is not None:
            observed.append([row["date"] for row in prefix])
        row = prefix[-1]
        item = mapping.get(row["date"])
        if not item:
            return {"signals": []}
        action, stop = item[:2]
        kind = item[2] if len(item) > 2 else "third_buy" if action == "buy" else "third_sell"
        return {"signals": [{"signal": action, "kind": kind, "signal_id": action + row["date"],
                             "confirmed_date": row["date"], "pivot_date": row["date"],
                             "reference_price": row["close"], "stop_price": stop}]}
    return evaluate


class BacktestTests(unittest.TestCase):
    def run_case(self, rows, mapping, code="sh688820", **kwargs):
        return run_backtest(rows, code, start="2026-09-01", signal_fn=signals(mapping), **kwargs)

    def test_signal_only_receives_prefix_and_fills_next_open(self):
        observed = []
        result = run_backtest([bar(1), bar(2, open_=10.2, close=10.5), bar(3, close=10.8)],
                              "sh688820", start="2026-09-01", signal_fn=signals({"2026-09-01": ("buy", 9)}, observed))
        self.assertEqual([len(items) for items in observed], [1, 2, 3])
        self.assertEqual(result["open_position"]["entry_date"], "2026-09-02")
        self.assertEqual(result["open_position"]["entry_price"], 10.2)
        self.assertEqual(result["orders"][0]["created_date"], "2026-09-01")
        self.assertGreater(result["metrics"]["total_cost"], 0)

    def test_below_stop_and_large_gap_do_not_refuse_entry(self):
        for next_bar in (bar(2, open_=8.5, close=9, high=10, low=8), bar(2, open_=12, close=12, high=13, low=11)):
            result = self.run_case([bar(1), next_bar], {"2026-09-01": ("buy", 9)})
            self.assertEqual(result["counters"]["entries"], 1)
            self.assertEqual(result["blocked_reasons"], {})

    def test_zero_volume_order_waits_at_original_limit_then_fills(self):
        rows = [bar(1), bar(2, volume=0), bar(3, open_=11, close=11, high=12, low=10.5),
                bar(4, open_=10.5, close=10.5, high=11, low=9.8)]
        result = self.run_case(rows, {"2026-09-01": ("buy", 9)})
        order = result["orders"][0]
        self.assertEqual(order["limit_price"], 10)
        self.assertEqual(order["fill_date"], "2026-09-04")
        self.assertEqual(order["fill_price"], 10)
        self.assertEqual([item["reason"] for item in order["wait_history"]], ["no_volume", "limit_not_reached"])

    def test_additions_use_exact_shares_with_no_position_or_risk_budget(self):
        result = self.run_case([bar(1), bar(2), bar(3)], {"2026-09-01": ("buy", 9), "2026-09-02": ("buy", 9)},
                               initial_cash=50000, order_quantity=2000)
        self.assertEqual(result["counters"]["entries"], 2)
        self.assertEqual(result["open_position"]["quantity"], 4000)
        self.assertEqual(result["counters"]["open_positions"], 2)

    def test_cash_shortage_waits_and_never_resizes_quantity(self):
        result = self.run_case([bar(1), bar(2), bar(3, open_=8, close=8, high=9, low=7)],
                               {"2026-09-01": ("buy", 0)}, initial_cash=1900, order_quantity=200)
        order = result["orders"][0]
        self.assertEqual(order["quantity"], 200)
        self.assertEqual(order["fill_date"], "2026-09-03")
        self.assertEqual(order["wait_history"][0]["reason"], "insufficient_cash_for_requested_quantity")

    def test_max_three_active_orders_and_old_orders_match_before_new_signal(self):
        mapping = {f"2026-09-{day:02d}": ("buy", 0) for day in range(1, 6)}
        result = self.run_case([bar(1), bar(2, volume=0), bar(3, volume=0), bar(4, volume=0), bar(5), bar(6)], mapping)
        self.assertEqual(result["blocked_reasons"]["max_active_orders_per_symbol"], 1)
        self.assertEqual(result["counters"]["entries"], 4)
        events = [item["action"] for item in result["events"] if item["date"] == "2026-09-05"]
        self.assertEqual(events, ["buy", "buy", "buy", "entry_order"])

    def test_cn_entry_day_stop_is_deferred_to_next_open(self):
        rows = [bar(1), bar(2, low=8, close=8.5), bar(3, open_=7, close=8, high=9, low=6.5)]
        result = self.run_case(rows, {"2026-09-01": ("buy", 9)})
        trade = result["trades"][0]
        self.assertEqual((trade["exit_date"], trade["exit_price"]), ("2026-09-03", 7))
        self.assertEqual(trade["exit_reason"], "stop_deferred_by_cn_t_plus_1")
        self.assertAlmostEqual(result["metrics"]["final_equity"], 500000 + trade["pnl"])

    def test_hk_can_stop_on_open_entry_day(self):
        result = self.run_case([bar(1), bar(2, low=8, close=8.5)], {"2026-09-01": ("buy", 9)}, code="hk01810")
        trade = result["trades"][0]
        self.assertEqual(trade["entry_date"], trade["exit_date"])
        self.assertEqual(trade["exit_price"], 9)

    def test_intraday_buy_does_not_use_a_low_that_may_predate_entry(self):
        rows = [bar(1), bar(2, volume=0), bar(3, open_=11, high=12, low=8, close=10)]
        result = self.run_case(rows, {"2026-09-01": ("buy", 9)}, code="hk01810")
        self.assertEqual(result["orders"][0]["fill_phase"], "intraday")
        self.assertEqual(result["trades"], [])
        self.assertFalse(result["open_lots"][0]["stop_triggered"])

    def test_waiting_stop_reserves_its_own_lot_across_additions(self):
        rows = [bar(1), bar(2), bar(3, open_=8, close=8, high=8.2, low=7.8, volume=0),
                bar(4, open_=7, close=7, high=7.5, low=6.9), bar(5, open_=7, close=7, high=7.5, low=6.9)]
        result = self.run_case(rows, {"2026-09-01": ("buy", 9), "2026-09-02": ("buy", 0),
                                      "2026-09-04": ("sell", None)})
        stop_orders = [order for order in result["orders"] if order["protective"]]
        self.assertEqual(len(stop_orders), 1)
        self.assertEqual(stop_orders[0]["status"], "ACTIVE")
        self.assertEqual(stop_orders[0]["limit_price"], 8)
        self.assertEqual(result["open_lots"][0]["id"], result["orders"][0]["id"])
        self.assertEqual(result["trades"][0]["entry_order_id"], result["orders"][1]["id"])

    def test_previously_armed_stop_open_proceeds_can_fund_later_intraday_buy(self):
        rows = [bar(1, high=10, low=10), bar(2, high=10, low=8, close=8),
                bar(3, open_=7, close=7, high=8, low=6)]
        result = self.run_case(rows, {"2026-09-01": ("buy", 9), "2026-09-02": ("buy", 0)},
                               code="sh600000", initial_cash=1000, order_quantity=100, cost_bps=0)
        self.assertEqual(result["counters"]["entries"], 2)
        self.assertEqual(result["orders"][1]["fill_date"], "2026-09-03")
        self.assertEqual(result["orders"][1]["fill_price"], 7)
        self.assertEqual(result["open_position"]["quantity"], 100)

    def test_all_sell_signal_types_exit_multiple_lots_next_day(self):
        for kind in ("first_sell", "second_sell", "third_sell", "range_divergence_sell"):
            with self.subTest(kind=kind):
                result = self.run_case([bar(1), bar(2), bar(3), bar(4), bar(5, open_=10.8, close=10.8)],
                    {"2026-09-01": ("buy", 9), "2026-09-02": ("buy", 9), "2026-09-04": ("sell", None, kind)})
                self.assertEqual(len(result["trades"]), 2)
                self.assertEqual(result["trades"][0]["exit_date"], "2026-09-05")
                self.assertEqual(result["open_position"], None)
                self.assertAlmostEqual(result["metrics"]["total_cost"], 400 * (10 + 10.8) * .0015)

    def test_last_bar_signal_remains_active_and_has_diagnostic(self):
        result = run_backtest([bar(1), bar(2)], "sh688820", start="2026-09-02",
                              signal_fn=signals({"2026-09-01": ("buy", 9), "2026-09-02": ("buy", 9)}))
        self.assertEqual(result["counters"]["warmup_bars"], 1)
        self.assertEqual(result["orders"][0]["status"], "ACTIVE")
        self.assertEqual(result["orders"][0]["wait_reason"], "no_next_session_in_dataset")

    def test_backdated_event_rejected_once_not_repeated_daily(self):
        def invalid(prefix, mode):
            return {"signals": [{"signal": "buy", "signal_id": "old", "confirmed_date": "2026-08-30",
                                 "stop_price": 8, "reference_price": 9}]}
        result = run_backtest([bar(1), bar(2)], "sh688820", signal_fn=invalid)
        self.assertEqual(result["counters"]["entries"], 0)
        self.assertEqual(result["blocked_reasons"]["signal_not_confirmed_on_current_bar"], 1)

    def test_reference_must_be_confirmation_close(self):
        def invalid(prefix, mode):
            return {"signals": [{"signal": "buy", "signal_id": "wrong-close", "confirmed_date": prefix[-1]["date"],
                                 "stop_price": 8, "reference_price": 9}]}
        result = run_backtest([bar(1), bar(2)], "sh688820", signal_fn=invalid)
        self.assertEqual(result["blocked_reasons"]["reference_not_confirmation_close"], 1)

    def test_invalid_share_quantity_and_duplicate_dates_are_rejected(self):
        for quantity in (199, 200.5, True, -1):
            with self.subTest(quantity=quantity), self.assertRaises(ValueError):
                self.run_case([bar(1)], {}, order_quantity=quantity)
        with self.assertRaises(ValueError):
            self.run_case([bar(1), bar(1)], {})

    def test_report_contains_persistent_orders_and_all_event_diagnostics(self):
        result = self.run_case([bar(1), bar(2, volume=0), bar(3, volume=0)], {"2026-09-01": ("buy", 9)})
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            report = Path(directory) / "report.html"
            render_report({"symbols": {}}, [result], report, "2026-09-01")
            text = report.read_text(encoding="utf-8")
        self.assertIn("全部委托及未成交原因", text)
        self.assertIn("当日无成交量，委托继续等待", text)
        self.assertIn(result["orders"][0]["id"], text)
        self.assertNotIn("25%", text)


if __name__ == "__main__":
    unittest.main()
