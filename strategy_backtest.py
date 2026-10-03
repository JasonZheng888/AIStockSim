"""Daily-bar research ledger with persistent orders and explicit share quantities.

The signal function receives only the history available at each close. Orders
from that close first become executable on the following bar. This module never
reads or writes a user's portfolio.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date
import math
from typing import Any, Callable


def _row(bar: Any) -> dict:
    if isinstance(bar, dict):
        return dict(bar)
    if is_dataclass(bar):
        return asdict(bar)
    return {key: getattr(bar, key) for key in ("date", "open", "high", "low", "close", "volume")}


def _lot(code: str) -> tuple[int, int]:
    if code.startswith("sh688"):
        return 200, 1
    if code == "hk01810":
        return 200, 200
    if code.startswith("hk"):
        raise ValueError("Unknown HK board lot; provide a verified symbol-specific lot rule first")
    return 100, 100


def run_backtest(bars: list, code: str, mode: str = "first_second_third",
                 start: str = "2024-10-01", initial_cash: float = 500000,
                 cost_bps: float = 15, signal_fn: Callable | None = None,
                 order_quantity: int | None = None,
                 lot_rule: tuple[int, int] | None = None) -> dict:
    if mode not in ("third_buy", "second_third", "first_second_third"):
        raise ValueError("Unknown strategy mode")
    date.fromisoformat(start)
    if not math.isfinite(initial_cash) or initial_cash <= 0 or not math.isfinite(cost_bps) or cost_bps < 0:
        raise ValueError("Cash must be positive and costs nonnegative and finite")
    minimum, step = lot_rule or _lot(code)
    if minimum <= 0 or step <= 0:
        raise ValueError("Invalid minimum lot or quantity increment")
    quantity = minimum if order_quantity is None else order_quantity
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < minimum or quantity % step:
        raise ValueError(f"Order quantity must be at least {minimum}, in increments of {step}; it is never resized")
    rows = [_row(bar) for bar in bars]
    previous = ""
    for row in rows:
        day = str(row["date"])
        if date.fromisoformat(day).isoformat() != day or day <= previous:
            raise ValueError("Bars must have unique increasing ISO dates")
        for field in ("open", "high", "low", "close", "volume"):
            row[field] = float(row.get(field, 0))
            if not math.isfinite(row[field]) or row[field] < 0 or (field != "volume" and row[field] == 0):
                raise ValueError("Bars require finite positive OHLC and nonnegative volume")
        if not row["low"] <= min(row["open"], row["close"]) <= max(row["open"], row["close"]) <= row["high"]:
            raise ValueError("Invalid OHLC range")
        previous = day
    if signal_fn is None:
        from chan_strategy import analyze_chan
        signal_fn = analyze_chan
    fee_rate = cost_bps / 10000
    cash = float(initial_cash)
    lots, orders, signals, trades, events, curve = [], [], [], [], [], []
    seen, blocked, waits, statuses = set(), {}, {}, {}
    total_cost = 0.0
    exposed_days = 0
    peak, max_drawdown = initial_cash, 0.0
    benchmark_cash, benchmark_qty, benchmark_checked = initial_cash, 0, False

    def active():
        return [order for order in orders if order["status"] == "ACTIVE"]

    def held():
        return sum(lot["quantity"] for lot in lots)

    def sellable(day, eligible_ids=None):
        return sum(lot["quantity"] for lot in lots
                   if (code.startswith("hk") or lot["entry_date"] < day)
                   and (eligible_ids is None or lot["id"] in eligible_ids))

    def reserved_sell():
        return sum(order["quantity"] for order in active() if order["action"] == "sell")

    def reserved_lots():
        reserved = {}
        for order in active():
            for identity, shares in order.get("lot_allocations", {}).items():
                reserved[identity] = reserved.get(identity, 0) + shares
        return reserved

    def reject(signal, reason, day):
        signal["disposition"] = reason
        blocked[reason] = blocked.get(reason, 0) + 1
        events.append({"date": day, "action": "blocked", "reason": reason, "signal_id": signal.get("signal_id")})

    def wait(order, reason, day):
        marker = (day, reason)
        if order.get("last_wait_marker") == marker:
            return
        order["last_wait_marker"] = marker
        order["wait_reason"] = reason
        order["wait_history"].append({"date": day, "reason": reason})
        waits[reason] = waits.get(reason, 0) + 1
        events.append({"date": day, "action": "wait", "reason": reason, "order_id": order["id"], "signal_id": order["signal_id"]})

    def enqueue(signal, shares, index, day, *, protective=False, price=None, lot_ids=None):
        if len(active()) >= 3:
            if protective:
                events.append({"date": day, "action": "defer_exit", "reason": "max_active_orders_per_symbol", "signal_id": signal.get("signal_id")})
            else:
                reject(signal, "max_active_orders_per_symbol", day)
            return None
        order = {"id": f"{code}-order-{len(orders) + 1}", "signal_id": signal.get("signal_id"),
                 "action": signal["signal"], "quantity": shares, "status": "ACTIVE",
                 "created_date": day, "ready_index": index if protective else index + 1,
                 "limit_price": price, "confirmed_date": signal.get("confirmed_date", day),
                 "stop_price": float(signal.get("stop_price") or 0),
                 "reason": signal.get("exit_reason") or signal.get("kind") or signal.get("pattern") or signal["signal"],
                 "protective": protective, "lot_ids": lot_ids, "wait_history": [], "wait_reason": ""}
        if order["action"] == "sell":
            reserved, remaining = reserved_lots(), shares
            allocation = {}
            for lot in lots:
                if lot_ids is not None and lot["id"] not in lot_ids:
                    continue
                available = max(0, lot["quantity"] - reserved.get(lot["id"], 0))
                taken = min(remaining, available)
                if taken:
                    allocation[lot["id"]] = taken
                    remaining -= taken
                if remaining == 0:
                    break
            if remaining:
                raise ValueError("Sell order allocation exceeds unreserved strategy lots")
            order["lot_allocations"] = allocation
        orders.append(order)
        if not protective:
            signal.update(order_id=order["id"], disposition="order_submitted")
        events.append({"date": day, "action": "entry_order" if order["action"] == "buy" else "exit_order",
                       "order_id": order["id"], "signal_id": order["signal_id"], "quantity": shares,
                       "reason": order["reason"]})
        return order

    def fill(order, row, price, index, phase, buying_power=None):
        nonlocal cash, total_cost
        shares, day = order["quantity"], row["date"]
        value, cost = shares * price, shares * price * fee_rate
        if order["action"] == "buy":
            if value + cost > min(cash, cash if buying_power is None else buying_power) + 1e-8:
                wait(order, "insufficient_cash_for_requested_quantity", day)
                return False
            cash -= value + cost
            lots.append({"id": order["id"], "signal_id": order["signal_id"], "entry_date": day,
                         "entry_index": index, "entry_phase": phase, "entry_price": price,
                         "quantity": shares, "entry_value": value, "entry_cost": cost,
                         "stop_price": order["stop_price"], "stop_triggered": False})
        else:
            allocation = order["lot_allocations"]
            available = sum(min(lot["quantity"], allocation.get(lot["id"], 0)) for lot in lots
                            if code.startswith("hk") or lot["entry_date"] < day)
            if shares > available:
                wait(order, "insufficient_sellable_quantity_t_plus_1", day)
                return False
            remaining = shares
            for lot in list(lots):
                if remaining <= 0:
                    break
                if (not code.startswith("hk") and lot["entry_date"] >= day) or lot["id"] not in allocation:
                    continue
                taken = allocation[lot["id"]]
                fraction = taken / lot["quantity"]
                entry_value, entry_cost = lot["entry_value"] * fraction, lot["entry_cost"] * fraction
                exit_cost = taken * price * fee_rate
                pnl = taken * price - exit_cost - entry_value - entry_cost
                trades.append({"entry_date": lot["entry_date"], "exit_date": day, "quantity": taken,
                               "entry_price": lot["entry_price"], "exit_price": price,
                               "stop_price": lot["stop_price"], "entry_cost": entry_cost, "exit_cost": exit_cost,
                               "pnl": pnl, "return_pct": pnl / (entry_value + entry_cost) * 100,
                               "exit_reason": order["reason"], "entry_order_id": lot["id"], "exit_order_id": order["id"]})
                lot["quantity"] -= taken
                lot["entry_value"] -= entry_value
                lot["entry_cost"] -= entry_cost
                remaining -= taken
                if lot["quantity"] == 0:
                    lots.remove(lot)
            cash += value - cost
        total_cost += cost
        order.update(status="FILLED", fill_date=day, fill_price=price, fill_phase=phase, wait_reason="")
        for signal in signals:
            if signal.get("order_id") == order["id"]:
                signal["disposition"] = "filled"
        events.append({"date": day, "action": order["action"], "order_id": order["id"],
                       "signal_id": order["signal_id"], "quantity": shares, "price": price, "reason": order["reason"]})
        return True

    def protective_exit(group, row, index, price, reason):
        if not group:
            return
        for lot in group:
            lot["stop_triggered"] = True
        lot_ids = [lot["id"] for lot in group]
        reserved = reserved_lots()
        shares = sum(max(0, lot["quantity"] - reserved.get(lot["id"], 0)) for lot in group
                     if code.startswith("hk") or lot["entry_date"] < row["date"])
        if shares:
            stop_signal = {"signal": "sell", "signal_id": "stop:" + ":".join(lot_ids), "exit_reason": reason}
            order = enqueue(stop_signal, shares, index, row["date"], protective=True, price=price, lot_ids=lot_ids)
            if order:
                if row["volume"] > 0:
                    fill(order, row, price, index, "stop")
                else:
                    wait(order, "no_volume", row["date"])
        elif any(lot["entry_date"] == row["date"] for lot in group) and not code.startswith("hk"):
            events.append({"date": row["date"], "action": "defer_exit", "reason": "stop_deferred_by_cn_t_plus_1"})

    for index, row in enumerate(rows):
        day = row["date"]
        if day < start:
            continue
        exposed = bool(lots)
        if not benchmark_checked and row["volume"] > 0:
            benchmark_checked = True
            value = quantity * row["open"] * (1 + fee_rate)
            if value <= benchmark_cash:
                benchmark_qty, benchmark_cash = quantity, benchmark_cash - value
        # Orders present before this bar are matched before evaluating its close.
        executable = [order for order in active() if order["ready_index"] <= index]
        for order in executable:
            if order["limit_price"] is None:
                order["limit_price"] = row["open"]
                order["priced_date"] = day
            if row["volume"] <= 0:
                wait(order, "no_volume", day)
                continue
            marketable = row["open"] <= order["limit_price"] if order["action"] == "buy" else row["open"] >= order["limit_price"]
            if marketable:
                fill(order, row, row["open"], index, "open")
        # These stop instructions were already known before this open. Process
        # their now-sellable lots before fixing the intraday cash budget, so
        # opening sale proceeds are usable without borrowing future proceeds.
        carry = [lot for lot in lots if lot["stop_triggered"] and lot["entry_date"] < day]
        protective_exit(carry, row, index, row["open"], "stop_deferred_by_cn_t_plus_1")
        opening_ids = {lot["id"] for lot in lots}
        # OHLC does not establish the order of intraday highs/lows. Proceeds of
        # an intraday sale cannot finance another intraday purchase on this bar.
        intraday_budget = cash
        for order in executable:
            if order["status"] != "ACTIVE" or row["volume"] <= 0:
                continue
            touched = row["low"] <= order["limit_price"] if order["action"] == "buy" else row["high"] >= order["limit_price"]
            if touched:
                before_cash = cash
                if fill(order, row, order["limit_price"], index, "intraday", intraday_budget) and order["action"] == "buy":
                    intraday_budget -= before_cash - cash
            else:
                wait(order, "limit_not_reached", day)
        exposed = exposed or bool(lots)
        # A stop already observed on an earlier bar remains armed after a
        # rebound. A newly intraday-filled lot only uses this bar's CLOSE to
        # test a stop, because its earlier low may predate the purchase.
        opening = [lot for lot in lots if lot["id"] in opening_ids and not lot["stop_triggered"]]
        stop = max((lot["stop_price"] for lot in opening), default=0)
        if stop > 0 and row["low"] <= stop:
            protective_exit(opening, row, index, min(row["open"], stop), "structure_stop")
        intraday = [lot for lot in lots if lot["entry_index"] == index and lot["entry_phase"] == "intraday" and not lot["stop_triggered"]]
        stop = max((lot["stop_price"] for lot in intraday), default=0)
        if stop > 0 and row["close"] <= stop:
            protective_exit(intraday, row, index, row["close"], "structure_stop_at_close")
        response = signal_fn(rows[:index + 1], mode=mode)
        status = str(response.get("status") or "unspecified")
        statuses[status] = statuses.get(status, 0) + 1
        for raw in response.get("signals", []):
            signal = dict(raw)
            identity = str(signal.get("signal_id") or "")
            if not identity or identity in seen:
                continue
            seen.add(identity)
            signal.setdefault("confirmed_date", day)
            signal.setdefault("signal", "buy" if "buy" in str(signal.get("kind")) else "sell")
            signals.append(signal)
            if signal["confirmed_date"] != day:
                reject(signal, "signal_not_confirmed_on_current_bar", day)
                continue
            if signal["signal"] not in ("buy", "sell"):
                reject(signal, "invalid_signal", day)
                continue
            try:
                reference = float(signal.get("reference_price"))
            except (ValueError, TypeError):
                reference = 0
            if not math.isfinite(reference) or not math.isclose(reference, row["close"], rel_tol=1e-8):
                reject(signal, "reference_not_confirmation_close", day)
                continue
            shares = quantity if signal["signal"] == "buy" else max(0, held() - reserved_sell())
            if shares <= 0:
                reject(signal, "no_unreserved_position_to_exit", day)
                continue
            enqueue(signal, shares, index, day)
        if exposed:
            exposed_days += 1
        equity = cash + held() * row["close"]
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak * 100)
        curve.append({"date": day, "equity": equity, "cash": cash, "quantity": held(),
                      "benchmark_equity": benchmark_cash + benchmark_qty * row["close"]})
    last_day = curve[-1]["date"] if curve else None
    for order in active():
        if order["limit_price"] is None:
            wait(order, "no_next_session_in_dataset", last_day or order["created_date"])
        for signal in signals:
            if signal.get("order_id") == order["id"]:
                signal["disposition"] = "active_waiting: " + (order["wait_reason"] or "next_session")
    for order in orders:
        order.pop("last_wait_marker", None)
        order.pop("ready_index", None)
    last_close = rows[-1]["close"] if curve else 0
    open_lots = [{**lot, "last_close": last_close,
                  "unrealized_pnl": lot["quantity"] * last_close - lot["entry_value"] - lot["entry_cost"]} for lot in lots]
    position = None
    if lots:
        position = {"entry_date": min(lot["entry_date"] for lot in lots), "quantity": held(),
                    "entry_price": sum(lot["entry_value"] for lot in lots) / held(),
                    "entry_value": sum(lot["entry_value"] for lot in lots), "entry_cost": sum(lot["entry_cost"] for lot in lots),
                    "stop_price": max(lot["stop_price"] for lot in lots), "last_close": last_close,
                    "unrealized_pnl": sum(lot["unrealized_pnl"] for lot in open_lots)}
    final_equity = curve[-1]["equity"] if curve else initial_cash
    benchmark_equity = curve[-1]["benchmark_equity"] if curve else initial_cash
    return {"schema_version": 2, "code": code, "mode": mode, "requested_start": start,
            "first_test_date": curve[0]["date"] if curve else None, "last_test_date": last_day,
            "assumptions": {"initial_cash": initial_cash, "one_way_cost_bps": cost_bps,
                            "order_quantity": quantity, "minimum_quantity": minimum, "quantity_step": step,
                            "max_active_orders_per_symbol": 3, "order_expiry": None,
                            "entry_limit": "first executable bar open, then unchanged",
                            "intraday_path": "no intraday sale proceeds reused; new intraday lots use closing stop only"},
            "counters": {"warmup_bars": sum(row["date"] < start for row in rows), "test_bars": len(curve),
                         "buy_signals": sum(item["signal"] == "buy" for item in signals),
                         "sell_signals": sum(item["signal"] == "sell" for item in signals),
                         "entries": sum(item["action"] == "buy" for item in events),
                         "closed_trades": len(trades), "open_positions": len(lots), "active_orders": len(active())},
            "metrics": {"final_equity": final_equity, "return_pct": (final_equity / initial_cash - 1) * 100,
                        "max_drawdown_pct": max_drawdown, "total_cost": total_cost,
                        "closed_trade_win_rate_pct": sum(trade["pnl"] > 0 for trade in trades) / len(trades) * 100 if trades else None,
                        "exposure_pct": exposed_days / len(curve) * 100 if curve else 0},
            "benchmark": {"description": "one purchase of the same configured share quantity; remaining cash retained",
                          "quantity": benchmark_qty, "final_equity": benchmark_equity,
                          "return_pct": (benchmark_equity / initial_cash - 1) * 100},
            "blocked_reasons": blocked, "waiting_reasons": waits, "analysis_status_counts": statuses,
            "trades": trades, "open_position": position, "open_lots": open_lots,
            "signals": signals, "orders": orders, "events": events, "equity_curve": curve}
