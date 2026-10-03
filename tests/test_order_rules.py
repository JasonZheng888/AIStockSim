"""Order lifecycle regression tests; no market requests or real account writes."""
import copy
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication, QCheckBox, QDialog, QSpinBox, QTabWidget
import StockTradingSim as sim


def memory_store():
    store = sim.PortfolioStore.__new__(sim.PortfolioStore)
    store.data = store._default()
    store.save = Mock()
    return store


def fresh_quote(code="sh600000", price=10.0):
    now = dt.datetime.now()
    return sim.Quote(code, "ST测试证券", price, 9.0, 9.9, now.strftime("%H:%M:%S"), "fixture", "CNY",
                     asof_date=now.date().isoformat())


def historical_lot(qty=1000):
    return {"code": "sh600000", "qty": qty, "buy_price": 20.0, "breakeven_price": 20.0,
            "buy_date": (dt.date.today() - dt.timedelta(days=3)).isoformat(), "currency": "CNY"}


def matching_window(store, quote):
    win = SimpleNamespace(store=store, quote_cache={quote.code: quote}, render_all=Mock())
    win.risk_violations_for_order = lambda *a, **kw: sim.MainWindow.risk_violations_for_order(win, *a, **kw)
    return win


class OrderRuleTests(unittest.TestCase):
    def test_fixed_cap_counts_both_sides_and_cannot_be_disabled(self):
        store = memory_store()
        store.data["lots"] = [historical_lot()]
        store.data["risk"] = {"enabled": False, "max_pending_per_code": 999}
        q = fresh_quote()
        for action in ("BUY", "SELL", "BUY"):
            store.add_pending_order(action, q, 100, 10, "fixture")
        before = copy.deepcopy(store.data)
        with self.assertRaisesRegex(ValueError, "最多 3"):
            store.add_pending_order("SELL", q, 100, 10, "fixture")
        self.assertEqual(store.data, before)
        store.add_pending_order("BUY", fresh_quote("sz000001"), 100, 10, "fixture")
        win = matching_window(store, q)
        self.assertTrue(sim.MainWindow.risk_violations_for_order(win, "BUY", q, 100, 10))

    def test_cancel_and_fill_release_slot_and_amend_does_not_add_slot(self):
        store = memory_store()
        q = fresh_quote()
        orders = [store.add_pending_order("BUY", q, 100, 10, "fixture") for _ in range(3)]
        win = matching_window(store, q)
        self.assertEqual(sim.MainWindow.risk_violations_for_order(win, "BUY", q, 200, 10, orders[0]), [])
        store.update_pending_order(order_id=orders[0]["id"], qty=200)
        self.assertEqual(len(store.active_pending_orders()), 3)
        store.cancel_pending_order(orders[1]["id"])
        store.add_pending_order("BUY", q, 100, 10, "fixture")
        store.buy(q, 200, pending_order_id=orders[0]["id"])
        store.add_pending_order("BUY", q, 100, 10, "fixture")
        self.assertEqual(len(store.active_pending_orders()), 3)

    def test_st_existing_loss_high_change_and_full_cash_are_allowed(self):
        store = memory_store()
        store.data["cash"] = 2000.0
        store.data["lots"] = [historical_lot(10000)]
        q = fresh_quote()
        win = matching_window(store, q)
        win.market_gate_profile = Mock(side_effect=AssertionError("risk must not consult market gate"))
        win.strategy_enabled = Mock(return_value=True)
        self.assertEqual(sim.MainWindow.risk_violations_for_order(win, "BUY", q, 200, 10), [])
        order = store.add_pending_order("BUY", q, 200, 10, "fixture")
        self.assertEqual(order["qty"], 200)
        self.assertEqual(store.available_cash(), 0)
        store.buy(q, 200, pending_order_id=order["id"])
        self.assertEqual(store.cash, 0)
        self.assertEqual(store.positions()[q.code]["qty"], 10200)

    def test_insufficient_cash_does_not_shrink_or_partially_create_order(self):
        store = memory_store()
        store.data["cash"] = 1999.99
        before = copy.deepcopy(store.data)
        with self.assertRaisesRegex(ValueError, "可用资金不足"):
            store.add_pending_order("BUY", fresh_quote(), 200, 10, "fixture")
        self.assertEqual(store.data, before)
        for quantity in (100.5, True, float("nan")):
            with self.subTest(quantity=quantity), self.assertRaises(ValueError):
                store.add_pending_order("BUY", fresh_quote(), quantity, 10, "fixture")

    def test_direct_buy_cannot_spend_other_order_reserved_cash(self):
        store = memory_store()
        store.data["cash"] = 2000
        order = store.add_pending_order("BUY", fresh_quote(), 200, 10, "fixture")
        before = copy.deepcopy(store.data)
        with self.assertRaises(ValueError):
            store.buy(fresh_quote("sz000001"), 100)
        self.assertEqual(store.data, before)
        store.buy(fresh_quote(price=9), 200, pending_order_id=order["id"])
        self.assertEqual(store.cash, 200)
        self.assertEqual(store.reserved_cash(), 0)

    def test_direct_sale_cannot_consume_reserved_shares_and_own_fill_can(self):
        store = memory_store()
        store.data["lots"] = [historical_lot(300)]
        q = fresh_quote()
        order = store.add_pending_order("SELL", q, 200, 10, "fixture")
        before = copy.deepcopy(store.data)
        with self.assertRaises(ValueError):
            store.sell(q, 200)
        self.assertEqual(store.data, before)
        store.sell(q, 100)
        store.sell(q, 200, pending_order_id=order["id"])
        self.assertEqual(store.positions(), {})
        self.assertEqual(store.reserved_sell_qty(q.code), 0)

    def test_metadata_is_saved_with_order_and_cannot_override_order_fields(self):
        store = memory_store()
        saved = []
        store.save.side_effect = lambda: saved.append(copy.deepcopy(store.data))
        order = store.add_pending_order("BUY", fresh_quote(), 100, 10, "fixture",
                                        metadata={"local_signal_id": "signal-1", "local_auto_event_id": "event-1",
                                                  "structure_stop": 8, "qty": 1, "status": "FILLED"})
        self.assertEqual(saved[0]["pending_orders"][0]["local_auto_event_id"], "event-1")
        self.assertEqual((order["qty"], order["status"]), (100, "ACTIVE"))
        store.buy(fresh_quote(), 100, pending_order_id=order["id"])
        self.assertEqual(saved[-1]["pending_orders"][0]["status"], "FILLED")
        self.assertEqual(saved[-1]["lots"][0]["local_signal_id"], "signal-1")
        self.assertEqual(saved[-1]["lots"][0]["structure_stop"], 8)

    def test_manual_sale_preserves_lots_frozen_by_local_exit(self):
        store = memory_store()
        local = historical_lot(100)
        local["local_signal_id"] = "structure-1"
        store.data["lots"] = [local, historical_lot(100)]
        q = fresh_quote()
        order = store.add_pending_order("SELL", q, 100, 10, "fixture",
                                        metadata={"local_signal_id": "structure-exit"})
        store.sell(q, 100)
        self.assertEqual(store.data["lots"], [local])
        self.assertEqual(local["qty"], 100)
        store.sell(q, 100, local_only=True, pending_order_id=order["id"])
        self.assertEqual(store.data["lots"], [])
        self.assertEqual(order["status"], "FILLED")

    def test_local_exit_cannot_freeze_or_amend_into_manual_holdings(self):
        store = memory_store()
        local = historical_lot(100)
        local["local_signal_id"] = "structure-1"
        store.data["lots"] = [local, historical_lot(1000)]
        q = fresh_quote()
        with self.assertRaises(ValueError):
            store.add_pending_order("SELL", q, 200, 10, "fixture", metadata={"local_signal_id": "exit"})
        order = store.add_pending_order("SELL", q, 100, 10, "fixture", metadata={"local_signal_id": "exit"})
        with self.assertRaises(ValueError):
            store.update_pending_order(order_id=order["id"], qty=200)
        self.assertEqual(order["qty"], 100)

    def test_amend_uses_net_reservations_and_rejects_nan_atomically(self):
        store = memory_store()
        store.data["cash"] = 3000
        q = fresh_quote()
        order = store.add_pending_order("BUY", q, 100, 10, "fixture")
        store.add_pending_order("BUY", q, 100, 10, "fixture")
        store.update_pending_order(order_id=order["id"], qty=200)
        self.assertEqual(store.available_cash(), 0)
        before = copy.deepcopy(store.data)
        for price in (float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                store.update_pending_order(order_id=order["id"], limit_price=price)
        with self.assertRaises(ValueError):
            store.update_pending_order(order_id=order["id"], qty=300)
        self.assertEqual(store.data, before)

    def test_expired_future_session_and_below_structure_stop_do_not_cancel_buy(self):
        for old_session in ("2020-01-01", "2099-01-01"):
            with self.subTest(old_session=old_session):
                store = memory_store()
                q = fresh_quote(price=5)
                order = store.add_pending_order("BUY", q, 100, 10, "fixture",
                                                 metadata={"local_signal_id": "old", "structure_stop": 8,
                                                           "signal_confirmed_at": (dt.date.today() - dt.timedelta(days=3)).isoformat()})
                order["valid_session"] = old_session
                with patch.object(sim, "trading_time_error", return_value=None):
                    self.assertEqual(sim.MainWindow.try_execute_pending_orders(matching_window(store, q)), 1)
                self.assertEqual(order["status"], "FILLED")
                self.assertEqual(order["qty"], 100)
                self.assertEqual(store.data["lots"][0]["structure_stop"], 8)

    def test_local_confirmation_today_future_or_unknown_waits_without_cancellation(self):
        for day in (dt.date.today().isoformat(), "2099-01-01", "", "bad-date"):
            with self.subTest(day=day):
                store = memory_store()
                q = fresh_quote()
                order = store.add_pending_order("BUY", q, 100, 10, "fixture",
                                                metadata={"local_signal_id": "signal-1", "signal_confirmed_at": day})
                with patch.object(sim, "trading_time_error", return_value=None):
                    self.assertEqual(sim.MainWindow.try_execute_pending_orders(matching_window(store, q)), 0)
                self.assertEqual(order["status"], "ACTIVE")
                self.assertIn("确认", order["wait_reason"])
                self.assertEqual(store.data["trades"], [])

    def test_old_signal_date_alias_fills_and_structure_stop_can_fill_today(self):
        store = memory_store()
        q = fresh_quote()
        buy = store.add_pending_order("BUY", q, 100, 10, "fixture",
                                      metadata={"local_signal_id": "signal-1",
                                                "signal_date": (dt.date.today() - dt.timedelta(days=3)).isoformat()})
        with patch.object(sim, "trading_time_error", return_value=None):
            self.assertEqual(sim.MainWindow.try_execute_pending_orders(matching_window(store, q)), 1)
        self.assertEqual(buy["status"], "FILLED")
        store.data["lots"][0]["buy_date"] = (dt.date.today() - dt.timedelta(days=1)).isoformat()
        sell = store.add_pending_order("SELL", q, 100, 10, "fixture",
                                       metadata={"local_signal_id": q.code + ":stop:signal-1",
                                                 "signal_confirmed_at": dt.date.today().isoformat()})
        with patch.object(sim, "trading_time_error", return_value=None):
            self.assertEqual(sim.MainWindow.try_execute_pending_orders(matching_window(store, q)), 1)
        self.assertEqual(sell["status"], "FILLED")

    def test_stale_price_closed_market_or_untriggered_limit_keep_orders_active(self):
        store = memory_store()
        q = fresh_quote()
        order = store.add_pending_order("BUY", q, 100, 10, "fixture")
        win = matching_window(store, q)
        q.asof_date = "2000-01-01"
        with patch.object(sim, "trading_time_error", return_value=None):
            self.assertEqual(sim.MainWindow.try_execute_pending_orders(win), 0)
        self.assertEqual(order["status"], "ACTIVE")
        win.quote_cache[q.code] = fresh_quote()
        with patch.object(sim, "trading_time_error", return_value="休市"):
            self.assertEqual(sim.MainWindow.try_execute_pending_orders(win), 0)
        self.assertEqual(order["wait_reason"], "休市")
        win.quote_cache[q.code] = fresh_quote(price=11)
        with patch.object(sim, "trading_time_error", return_value=None):
            self.assertEqual(sim.MainWindow.try_execute_pending_orders(win), 0)
        self.assertEqual(order["status"], "ACTIVE")
        self.assertEqual(store.data["trades"], [])

    def test_temporary_cash_shortage_waits_and_fills_later_without_resizing(self):
        store = memory_store()
        q = fresh_quote()
        order = store.add_pending_order("BUY", q, 200, 10, "fixture")
        store.data["cash"] = 1999
        win = matching_window(store, q)
        with patch.object(sim, "trading_time_error", return_value=None):
            self.assertEqual(sim.MainWindow.try_execute_pending_orders(win), 0)
            self.assertEqual((order["status"], order["qty"]), ("ACTIVE", 200))
            store.data["cash"] = 2000
            self.assertEqual(sim.MainWindow.try_execute_pending_orders(win), 1)
        self.assertEqual(store.data["trades"][0]["qty"], 200)

    def test_disabled_canslim_returns_no_advice_or_score(self):
        win = SimpleNamespace(strategy_enabled=Mock(return_value=False))
        profile = sim.MainWindow.canslim_profile_for_code(win, "sh600000", fresh_quote())
        self.assertFalse(profile["enabled"])
        self.assertIsNone(profile["score"])
        self.assertEqual(profile["components"], {})

    def test_json_orders_allow_repeats_until_three_then_enforce_same_cap(self):
        store = memory_store()
        q = fresh_quote()
        win = matching_window(store, q)
        win.try_execute_pending_orders = lambda: sim.MainWindow.try_execute_pending_orders(win)
        win.account_snapshot = Mock(return_value={})
        win.render_ai_logs = Mock()
        commands = [{"action": "buy", "code": q.code, "qty": 100, "limit_price": 9,
                     "reason": "same confirmed signal"} for _ in range(4)]
        with patch.object(sim, "trading_time_error", return_value=None):
            result = sim.MainWindow.execute_ai_orders(win, json.dumps(commands), "Codex", False)
        self.assertEqual((result["submitted"], result["filled"]), (3, 0))
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual([o["qty"] for o in store.active_pending_orders()], [100] * 3)

    def test_json_and_direct_execution_reject_stale_quote_and_fractional_shares(self):
        store = memory_store()
        q = fresh_quote()
        win = matching_window(store, q)
        win.try_execute_pending_orders = lambda: sim.MainWindow.try_execute_pending_orders(win)
        win.account_snapshot = Mock(return_value={})
        win.render_ai_logs = Mock()
        commands = [{"action": "buy", "code": q.code, "qty": 100.5, "limit_price": 10}]
        result = sim.MainWindow.execute_ai_orders(win, json.dumps(commands), "fixture", False)
        self.assertEqual(result["submitted"], 0)
        q.asof_date = "2000-01-01"
        commands[0]["qty"] = 100
        result = sim.MainWindow.execute_ai_orders(win, json.dumps(commands), "fixture", False)
        self.assertEqual(result["submitted"], 0)
        with patch.object(sim, "trading_time_error", return_value=None):
            error = sim.MainWindow.execute_order(win, "buy", q.code, 100)
        self.assertIn("报价", error)
        self.assertEqual(store.data["trades"], [])

    def test_red_and_missing_market_gate_do_not_deny_new_orders(self):
        win = SimpleNamespace(strategy_enabled=Mock(return_value=True), quote_cache={},
                              technical_profile=Mock(return_value={"status": "missing"}))
        self.assertTrue(sim.MainWindow.market_gate_profile(win)["new_long_allowed"])
        win.quote_cache = {code: fresh_quote(code) for code in sim.MARKET_GATE_CODES}
        for quote in win.quote_cache.values():
            quote.change_pct = -3
        profile = sim.MainWindow.market_gate_profile(win)
        self.assertEqual(profile["gate"], "red")
        self.assertTrue(profile["new_long_allowed"])


class RuleSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["order-settings-tests"])

    def test_settings_expose_only_fixed_three_order_rule(self):
        dialog = QDialog()
        dialog.owner = SimpleNamespace(store=memory_store())
        dialog.tabs = QTabWidget(dialog)
        sim.MainSettingsDialog._insert_risk_tab(dialog)
        self.assertEqual(dialog.findChildren(QCheckBox), [])
        self.assertEqual(len(dialog.findChildren(QSpinBox)), 1)
        self.assertEqual(dialog.risk_max_pending.value(), 3)
        self.assertFalse(dialog.risk_max_pending.isEnabled())
        dialog.deleteLater()

    def test_data_directory_override_isolated_for_main_and_compact_apps(self):
        root = Path(__file__).resolve().parents[1]
        fixtures = root / "build" / "test-state"
        fixtures.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=fixtures) as directory:
            env = dict(os.environ, AISTOCKSIM_DATA_DIR=directory, PYTHONIOENCODING="utf-8")
            code = "import json, StockTradingSim as s, StockWidget as w; print(json.dumps([s.CONFIG_DIR,w.CONFIG_DIR,s.APP_VERSION]))"
            result = subprocess.run([sys.executable, "-X", "utf8", "-c", code], cwd=root,
                                    env=env, capture_output=True, text=True, encoding="utf-8", check=True)
            main, compact, version = json.loads(result.stdout)
            self.assertEqual(Path(main), Path(directory))
            self.assertEqual(Path(compact), Path(directory) / "StockWidget")
            self.assertEqual(version, "3.3.0")


if __name__ == "__main__":
    unittest.main()
