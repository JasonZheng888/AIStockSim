"""Execution helpers shared by the local signal panel and order matching.

The signal model consumes completed daily bars. Quotes and the order book are
separate inputs: a historical signal never grants permission to fill an order.
"""
from __future__ import annotations

import datetime as dt
import math


def next_session(day: str, code: str, calendar: dict) -> str:
    market = calendar.get("markets", {}).get("hk" if code.startswith("hk") else "cn", {})
    closed = set(market.get("closed_dates", []))
    date = dt.date.fromisoformat(day)
    for _ in range(60):
        date += dt.timedelta(days=1)
        if date.weekday() < 5 and date.isoformat() not in closed:
            return date.isoformat()
    raise ValueError("交易日历无法确定下一交易日")


def session_close(day: str, code: str, calendar: dict) -> dt.datetime:
    market = calendar.get("markets", {}).get("hk" if code.startswith("hk") else "cn", {})
    hour = 16 if code.startswith("hk") else 15
    if code.startswith("hk") and day in market.get("half_days", []):
        hour = 12
    return dt.datetime.combine(dt.date.fromisoformat(day), dt.time(hour))


def completed_bars(rows: list[dict], code: str, now: dt.datetime, calendar: dict) -> tuple[list[dict], list[str]]:
    """Keep a continuous valid suffix; never splice around an invalid OHLC bar."""
    result, warnings = [], []
    last_date = ""
    for row in rows:
        day = str(row.get("date", ""))[:10]
        if day > now.date().isoformat():
            continue
        try:
            close_time = session_close(day, code, calendar)
            if now < close_time + dt.timedelta(minutes=5):
                continue
            values = [float(row[k]) for k in ("open", "high", "low", "close")]
            op, hi, lo, cl = values
            valid = (all(math.isfinite(v) and v > 0 for v in values)
                     and lo <= min(op, cl) <= max(op, cl) <= hi
                     and day > last_date)
        except (ValueError, TypeError, KeyError):
            valid = False
        if not valid:
            result = []
            warnings = ["历史含无效或乱序价格，仅使用最后异常之后的连续日K"]
            last_date = day
            continue
        last_date = day
        result.append(row)
    return result, warnings


def quote_freshness_error(quote, now: dt.datetime) -> str | None:
    try:
        price = float(quote.price)
        if not math.isfinite(price) or price <= 0:
            return "报价价格无效，等待刷新"
    except (AttributeError, TypeError, ValueError, OverflowError):
        return "报价价格无效，等待刷新"
    day = str(getattr(quote, "asof_date", "") or "").replace("/", "-")
    try:
        stamp = dt.datetime.fromisoformat(day + " " + str(quote.time_label))
        age = (now - stamp).total_seconds()
    except (ValueError, AttributeError):
        return "报价缺少可核验的日期或时间，等待刷新"
    if age < -60 or age > 300:
        return "报价非当前5分钟内，等待新行情"
    return None


def order_quantity(settings: dict, code: str, minimum: int) -> int:
    """Explicit shares per order; the initial lot is a visible, editable default."""
    quantities = settings.get("local_order_quantities", {})
    value = quantities.get(code, minimum) if isinstance(quantities, dict) else minimum
    try:
        quantity = int(value)
        if isinstance(value, bool) or float(value) != quantity:
            return 0
        return quantity
    except (TypeError, ValueError, OverflowError):
        return 0
