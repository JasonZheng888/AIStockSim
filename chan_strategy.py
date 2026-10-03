"""Causal daily-bar Chan-inspired *stroke proxy* research strategy.

This is deliberately NOT the book's recursive segment / central-zone theory.
The contract is: completed daily OHLC bars, ascending unique ISO dates; no Qt,
network, orders, or account state. Only a newly confirmed event on the final
input date can produce ``signal != 'wait'``. ``signal_history`` is an immutable
as-observed event journal reconstructed by chronological replay, not a plot of
retrospectively revised swing endpoints. Trade at the next available session,
never at ``pivot_date`` or its extreme price.

Definitions used here:
* Sequential directional inclusion reduction (lessons 62 / 65).
* Three standard-bar high AND low fractals; a right bar must have closed.
* Early strict strokes: fractal centres at least four standard bars apart,
  leaving a separate bar between their three-bar ranges. Same-kind extremes
  extend the current stroke; the last stroke remains provisional.
* Three strokes whose endpoints are already locked by the next opposite
  fractal supply a fixed overlap interval, labelled a ``stroke_proxy`` zone.
  A later independent three-stroke overlap wholly outside the active zone
  replaces it even when the initial departure was not observable at creation.
* The first valid return stroke after an upward/downward departure can create
  a proxy third buy/sell. A completed signal is never erased on later extension;
  subsequent price failure belongs to execution / stop handling.
* Optional proxy second buy: a lower-high/lower-low pair, a rebound above that
  lower high, then its first return holding above the preceding low. No same-
  level first buy is required (lesson 53). This is a conservative subset.
* MACD alone remains observation only. Two independent non-overlapping full
  centre ranges plus weaker same-direction entry/exit stroke areas can emit a
  trend-divergence first-buy proxy in the explicit all-buy mode. One-centre
  divergence never becomes a first buy. Upward divergence can emit an exit.
* First-buy/sell anchors can confirm a second buy/sell on the first holding
  return; structural reversal second buys still need no same-level first buy.

All strokes also require both the top range's high and low to exceed the
bottom range's, an explicit conservative rule for excluding contained ranges.
"""

from __future__ import annotations

from datetime import date as Date
import math
from typing import Any

from chan_divergence import divergence_context, macd_evidence
from chan_segments import analyze_segments


STRATEGY_NAME = "缠论日线笔结构实验版"
MODES = ("third_buy", "second_third", "first_second_third")
_WARNINGS = [
    "实验规则：中枢与买卖点仍为日线笔级代理；特征序列线段只作独立诊断，未实现递归级别及完整缠论三类买卖点。",
    "趋势背驰需两个独立中枢的完整波动区间分离；MACD面积仅作同向笔力度代理，未验证次级别走势完成。",
    "分型极值日不是可交易确认日；末端笔可继续延伸，已发信号保持当时记录，失效须执行止损。",
    "仅使用已收盘日K；有限历史起点影响结构划分，实盘与回测应采用相同历史起点。",
]


def _validated(bars: list[dict]) -> list[dict]:
    result = []
    previous = ""
    for index, bar in enumerate(bars):
        day = str(bar.get("date", ""))
        try:
            parsed = Date.fromisoformat(day)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"第 {index + 1} 根K线日期必须为 YYYY-MM-DD") from exc
        if parsed.isoformat() != day or day <= previous:
            raise ValueError("K线日期必须唯一且按时间递增，不能排序后偷偷改写输入")
        values = {}
        for field in ("open", "high", "low", "close"):
            try:
                value = float(bar[field])
            except (KeyError, ValueError, TypeError) as exc:
                raise ValueError(f"{day} 缺少有效 {field}") from exc
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{day} 的 {field} 必须为有限正数")
            values[field] = value
        if not values["low"] <= min(values["open"], values["close"]) <= max(values["open"], values["close"]) <= values["high"]:
            raise ValueError(f"{day} 的 OHLC 高低范围不一致")
        result.append({"date": day, "raw_index": index, **values})
        previous = day
    return result


def _new_standard(bar: dict, *, bootstrap: bool = False) -> dict:
    return {
        "high": bar["high"], "low": bar["low"],
        "high_date": bar["date"], "low_date": bar["date"],
        "high_index": bar["raw_index"], "low_index": bar["raw_index"],
        "start_date": bar["date"], "end_date": bar["date"],
        "bootstrap": bootstrap,
    }


def _contains(a: dict, b: dict) -> bool:
    return (a["high"] >= b["high"] and a["low"] <= b["low"]) or (b["high"] >= a["high"] and b["low"] <= a["low"])


def _append_standard(standard: list[dict], bar: dict) -> bool:
    """Return True for a new standard bar, False for inclusion into its tail."""
    if not standard:
        standard.append(_new_standard(bar, bootstrap=True))
        return True
    tail = standard[-1]
    if not _contains(tail, bar):
        standard.append(_new_standard(bar))
        return True
    if len(standard) == 1:
        # No preceding direction exists. Keep this envelope only as warm-up;
        # it cannot be one of the three bars forming a tradable fractal.
        use_high = bar["high"] > tail["high"]
        use_low = bar["low"] < tail["low"]
    else:
        rising = tail["high"] > standard[-2]["high"]
        use_high = bar["high"] > tail["high"] if rising else bar["high"] < tail["high"]
        use_low = bar["low"] > tail["low"] if rising else bar["low"] < tail["low"]
    if use_high:
        tail.update(high=bar["high"], high_date=bar["date"], high_index=bar["raw_index"])
    if use_low:
        tail.update(low=bar["low"], low_date=bar["date"], low_index=bar["raw_index"])
    tail["end_date"] = bar["date"]
    return False


def _fractal(standard: list[dict], bar: dict) -> dict | None:
    if len(standard) < 3:
        return None
    left, mid, right = standard[-3:]
    if left["bootstrap"] or mid["bootstrap"] or right["bootstrap"]:
        return None
    top = mid["high"] > max(left["high"], right["high"]) and mid["low"] > max(left["low"], right["low"])
    bottom = mid["low"] < min(left["low"], right["low"]) and mid["high"] < min(left["high"], right["high"])
    if not (top or bottom):
        return None
    extreme = "high" if top else "low"
    return {
        "kind": "top" if top else "bottom",
        "price": mid[extreme], "high": mid["high"], "low": mid["low"],
        "standard_index": len(standard) - 2,
        "raw_index": mid[f"{extreme}_index"],
        "pivot_date": mid[f"{extreme}_date"],
        "confirmed_date": bar["date"], "confirmed_at_index": bar["raw_index"],
    }


def _accept_fractal(pivots: list[dict], candidate: dict) -> bool:
    if not pivots:
        pivots.append({**candidate, "sequence_confirmed_date": candidate["confirmed_date"]})
        return True
    last = pivots[-1]
    if candidate["kind"] == last["kind"]:
        extreme = candidate["price"] > last["price"] if last["kind"] == "top" else candidate["price"] < last["price"]
        if extreme:
            if len(pivots) > 1:
                other = pivots[-2]
                top, bottom = (candidate, other) if candidate["kind"] == "top" else (other, candidate)
                if top["high"] <= bottom["high"] or top["low"] <= bottom["low"]:
                    # A later wide-range fractal may swallow the opposite
                    # endpoint. A more extreme price alone cannot turn that
                    # invalid pair into a strict stroke.
                    return False
            pivots[-1] = {**candidate, "sequence_confirmed_date": last["sequence_confirmed_date"]}
            return True
        return False
    if candidate["standard_index"] - last["standard_index"] < 4:
        return False
    top, bottom = (candidate, last) if candidate["kind"] == "top" else (last, candidate)
    if top["high"] <= bottom["high"] or top["low"] <= bottom["low"]:
        return False
    pivots.append({**candidate, "sequence_confirmed_date": candidate["confirmed_date"]})
    return True


def _stroke(start: dict, end: dict, index: int, *, provisional: bool) -> dict:
    return {
        "index": index, "direction": "up" if end["kind"] == "top" else "down",
        "start_date": start["pivot_date"], "end_date": end["pivot_date"],
        "start_price": start["price"], "end_price": end["price"],
        "low": min(start["price"], end["price"]), "high": max(start["price"], end["price"]),
        "confirmed_date": end["confirmed_date"], "provisional": provisional,
    }


def _new_center(pivots: list[dict], centers: list[dict], bar: dict) -> dict | None:
    # The newest stroke is still extendable, so only its three predecessors
    # may define a fixed centre. Their four endpoints are now immutable.
    if len(pivots) < 5:
        return None
    first = len(pivots) - 5
    points = pivots[-5:-1]
    lower = max(min(a["price"], b["price"]) for a, b in zip(points, points[1:]))
    upper = min(max(a["price"], b["price"]) for a, b in zip(points, points[1:]))
    if lower >= upper:
        return None
    if centers:
        prior = centers[-1]
        if prior["state"].startswith("broken_"):
            if first < prior["break_pivot_sequence"]:
                return None
        else:
            # Locking the third stroke can be later than price's departure.
            # An old zone must not remain the active reference forever when
            # three subsequent locked strokes already overlap wholly outside
            # it. This is a newly formed proxy zone, not an invented trade at
            # an earlier missed breakout. Shared constituent strokes cannot
            # manufacture a second centre.
            if first <= prior["source_strokes"][-1]:
                return None
            if lower > prior["high"]:
                prior["state"] = "superseded_up"
            elif upper < prior["low"]:
                prior["state"] = "superseded_down"
            else:
                return None
            prior["superseded_confirmed_date"] = bar["date"]
    return {
        "id": f"stroke_proxy:{points[0]['pivot_date']}:{points[-1]['pivot_date']}",
        "kind": "stroke_proxy", "low": lower, "high": upper,
        "start_date": points[0]["pivot_date"], "end_date": points[-1]["pivot_date"],
        "confirmed_date": bar["date"], "source_strokes": list(range(first, first + 3)),
        "state": "seeking_departure", "failed_retests": 0,
        "range_low": min(point["price"] for point in points),
        "range_high": max(point["price"] for point in points),
        "extension_strokes": [],
    }


def _extend_center(center: dict, pivots: list[dict], bar: dict) -> None:
    """Extend only an unresolved zone, never absorb its successful departure."""
    if center["state"] != "seeking_departure" or len(pivots) < 3:
        return
    index = len(pivots) - 3  # previous stroke is now locked
    if index <= center["source_strokes"][-1] or index in center["extension_strokes"]:
        return
    a, b = pivots[index:index + 2]
    low, high = sorted((a["price"], b["price"]))
    if low <= center["high"] and high >= center["low"]:
        center["range_low"] = min(center["range_low"], low)
        center["range_high"] = max(center["range_high"], high)
        center["extension_strokes"].append(index)
        center["last_extended_date"] = bar["date"]


def _event(kind: str, pivot: dict, bar: dict, *, stop: float | None, reason: str) -> dict:
    pattern = {"first_buy": "proxy_1buy", "second_buy": "proxy_2buy", "third_buy": "proxy_3buy", "first_sell": "proxy_1sell", "second_sell": "proxy_2sell", "third_sell": "proxy_3sell", "range_divergence_sell": "proxy_range_sell"}[kind]
    return {
        "status": "confirmed", "signal": "sell" if kind.endswith("sell") else "buy",
        "signal_id": f"{pattern}:{bar['date']}:{pivot['pivot_date']}",
        "pattern": pattern, "kind": kind,
        "confirmed_date": bar["date"], "pivot_date": pivot["pivot_date"],
        "stop_price": stop, "reference_price": bar["close"], "reason": reason,
    }


def _center_event(center: dict, pivots: list[dict], bar: dict) -> dict | None:
    if center["state"].startswith(("broken_", "superseded_")) or len(pivots) < 2:
        return None
    pivot = pivots[-1]
    sequence = len(pivots) - 1
    state = center["state"]
    if state.startswith("awaiting_"):
        if sequence == center["departure_pivot_sequence"]:
            center["departure_price"] = pivot["price"]
            return None
        if sequence == center["departure_pivot_sequence"] + 1:
            upward = state == "awaiting_pullback_up"
            qualifies = pivot["kind"] == "bottom" and pivot["price"] >= center["high"] if upward else pivot["kind"] == "top" and pivot["price"] <= center["low"]
            if qualifies:
                center["state"] = "broken_up" if upward else "broken_down"
                center["break_pivot_sequence"] = sequence
                center["break_confirmed_date"] = bar["date"]
                if upward:
                    return _event("third_buy", pivot, bar, stop=pivot["price"], reason=f"笔中枢代理 [{center['low']:.3f}, {center['high']:.3f}] 上方第一次回试成笔；底分型右侧日K已收盘确认（实验三买代理）。")
                return _event("third_sell", pivot, bar, stop=None, reason=f"向下离开笔中枢代理后，第一次回抽高点未升破下沿 {center['low']:.3f}，顶分型已确认（实验三卖代理）。")
            center["failed_retests"] += 1
            center["state"] = "seeking_departure"
            # This return might simultaneously depart on the opposite side.
        else:
            center["state"] = "seeking_departure"
    if pivot["kind"] == "top" and pivot["price"] > center["high"] and pivots[-2]["price"] <= center["high"]:
        center.update(state="awaiting_pullback_up", departure_pivot_sequence=sequence, departure_price=pivot["price"], departure_date=pivot["pivot_date"])
    elif pivot["kind"] == "bottom" and pivot["price"] < center["low"] and pivots[-2]["price"] >= center["low"]:
        center.update(state="awaiting_pullback_down", departure_pivot_sequence=sequence, departure_price=pivot["price"], departure_date=pivot["pivot_date"])
    return None


def _second_event(pivots: list[dict], bar: dict, consumed: set[tuple]) -> dict | None:
    if len(pivots) < 6:
        return None
    first, second, prior_turn, base, rebound, retest = pivots[-6:]
    buying = retest["kind"] == "bottom"
    key = ("reversal", base["pivot_date"], rebound["pivot_date"])
    if key in consumed:
        return None
    # Mirror the downward reversal without a global MA / position prerequisite.
    sign = 1 if buying else -1
    a, b, c, d, e, f = [point["price"] * sign for point in (first, second, prior_turn, base, rebound, retest)]
    if c < a and d < b and e > c and f > d:
        consumed.add(key)
        event = _event("second_buy" if buying else "second_sell", retest, bar, stop=retest["price"] if buying else None, reason="下降结构被反弹突破，首次回试成笔且未破转折低点；底分型已确认（转强首回试二买代理）。" if buying else "上升结构被回落破坏，首次反抽成笔且未越转折高点；顶分型已确认（转弱首反抽二卖代理）。")
        event["evidence"] = {"subtype": "structural_reversal", "base_date": base["pivot_date"], "base_price": base["price"], "rebound_date": rebound["pivot_date"]}
        return event
    return None


def _anchored_second(pivots: list[dict], bar: dict, anchors: dict) -> dict | None:
    """First *opposite stroke then return*, never a later arbitrary pullback."""
    sequence = len(pivots) - 1
    pivot = pivots[-1]
    result = None
    for side, anchor in list(anchors.items()):
        buying = side == "buy"
        breaks = pivot["price"] < anchor["price"] if buying else pivot["price"] > anchor["price"]
        if sequence < anchor["sequence"] + 2:
            if pivot["kind"] == ("bottom" if buying else "top") and breaks:
                del anchors[side]
            continue
        del anchors[side]  # the first return consumes the setup, also on failure
        holds = pivot["price"] > anchor["price"] if buying else pivot["price"] < anchor["price"]
        if sequence == anchor["sequence"] + 2 and holds:
            result = _event("second_buy" if buying else "second_sell", pivot, bar, stop=pivot["price"] if buying else None, reason="趋势背驰一买代理后首次反弹、回试成笔，低点高于原转折低点（二买代理）。" if buying else "趋势背驰一卖代理后首次回落、反抽成笔，高点低于原转折高点（二卖代理）。")
            result["evidence"] = {"subtype": "after_first_divergence", "anchor_date": anchor["pivot_date"], "anchor_confirmed_date": anchor["confirmed_date"], "anchor_price": anchor["price"]}
    return result


def _macd_areas(bars: list[dict]) -> list[float]:
    """Cumulative negative histogram area; strictly forward EMAs."""
    return macd_evidence(bars)["negative"]


def _divergence_observation(pivots: list[dict], bar: dict, area: list[float]) -> dict | None:
    if bar["raw_index"] < 34 or len(pivots) < 4 or pivots[-1]["kind"] != "bottom":
        return None
    a, b, c, d = pivots[-4:]
    prior = area[b["raw_index"] + 1] - area[a["raw_index"]]
    current = area[d["raw_index"] + 1] - area[c["raw_index"]]
    if d["price"] < b["price"] and 0 < current < prior:
        return {"kind": "divergence_watch", "confirmed_date": bar["date"], "pivot_date": d["pivot_date"], "reason": "下降笔创新低但负MACD柱面积缩小；此现象单独不足以构成一买，需另行验证中枢和可比同向段。"}
    return None


def analyze_chan(bars: list[dict], mode: str = "third_buy") -> dict[str, Any]:
    """Replay completed bars and return today's event plus explicit diagnostics.

    ``third_buy`` enables third-buy entries; ``second_third`` also enables
    second-buy proxies; ``first_second_third`` additionally enables structural
    trend-divergence first buys. Structural / divergence exits exist in all.
    Invalid data returns ``status='data_error'`` and never yields an order.
    ``signals`` contains only final-date events; ``signal_history`` preserves
    past observations even if future prices extend the last stroke.
    """
    result: dict[str, Any] = {
        "strategy": STRATEGY_NAME, "mode": mode, "status": "insufficient_data",
        "signal": "wait", "signal_id": "", "pattern": "none",
        "confirmed_date": None, "pivot_date": None, "stop_price": None,
        "reference_price": None, "reason": "至少需要3根已收盘日K，随后等待严格笔结构形成。",
        "structures": {"fractals": [], "strokes": [], "centers": [], "segments": [], "segment_pending": {"status": "forming"}},
        "warnings": list(_WARNINGS), "signals": [], "signal_history": [], "observations": [],
        "divergence_history": [], "center_history": [],
        "bar_count": 0, "standard_bar_count": 0,
    }
    if mode not in MODES:
        result.update(status="data_error", reason=f"未知模式 {mode!r}；允许 {', '.join(MODES)}。")
        return result
    try:
        raw = _validated(bars)
    except (ValueError, TypeError, AttributeError) as exc:
        result.update(status="data_error", reason=str(exc))
        return result
    if not raw:
        return result
    result["reference_price"] = raw[-1]["close"]
    standard: list[dict] = []
    fractals: list[dict] = []
    pivots: list[dict] = []
    centers: list[dict] = []
    events: list[dict] = []
    observations: list[dict] = []
    divergences: list[dict] = []
    center_history: list[dict] = []
    consumed_seconds: set[tuple] = set()
    consumed_divergences: set[tuple] = set()
    anchors: dict[str, dict] = {}
    macd = macd_evidence(raw)
    areas = macd["negative"]
    for bar in raw:
        if not _append_standard(standard, bar):
            continue
        candidate = _fractal(standard, bar)
        if candidate is None:
            continue
        fractals.append(candidate.copy())
        old_count = len(pivots)
        if not _accept_fractal(pivots, candidate):
            continue
        old_state = (centers[-1]["id"], centers[-1]["state"], len(centers[-1]["extension_strokes"])) if centers else None
        # First allow an existing zone's current return to confirm an event;
        # only then consider a new independent zone on the same observation.
        third = _center_event(centers[-1], pivots, bar) if centers else None
        if len(pivots) > old_count:
            if centers:
                _extend_center(centers[-1], pivots, bar)
            new_center = _new_center(pivots, centers, bar)
            if new_center is not None:
                centers.append(new_center)
                third = third or _center_event(new_center, pivots, bar)
        if centers:
            new_state = (centers[-1]["id"], centers[-1]["state"], len(centers[-1]["extension_strokes"]))
            if new_state != old_state:
                center_history.append({"confirmed_date": bar["date"], "center_id": centers[-1]["id"], "state": centers[-1]["state"], "previous_center_id": old_state[0] if old_state else None, "previous_state": old_state[1] if old_state else None, "extension_count": new_state[2]})
        anchored = _anchored_second(pivots, bar, anchors)
        second = anchored or _second_event(pivots, bar, consumed_seconds)
        if second and second["signal"] == "buy" and mode == "third_buy":
            second = None
        divergence = divergence_context(pivots, centers, macd)
        divergence_event = None
        if divergence is not None:
            key = (divergence["classification"], divergence["direction"], divergence["center_id"], divergence["exit_stroke"])
            if key not in consumed_divergences:
                consumed_divergences.add(key)
                downward = divergence["direction"] == "down"
                trend = divergence["classification"] == "trend"
                reason = ("两个独立笔中枢的完整波动区间依次下移" if downward else "两个独立笔中枢的完整波动区间依次上移") if trend else "同一笔中枢两侧的同向进出笔比较"
                reason += "，离开笔创新极值但MACD同向柱面积缩小；分型右侧日K已确认（笔级背驰代理，未验证次级别完成）。"
                observation = {"kind": "trend_divergence" if trend else "range_divergence", "confirmed_date": bar["date"], "pivot_date": pivots[-1]["pivot_date"], "reason": reason, "evidence": divergence}
                divergences.append(observation)
                observations.append(observation)
                if trend:
                    side = "buy" if downward else "sell"
                    anchors[side] = {"sequence": len(pivots) - 1, "price": pivots[-1]["price"], "pivot_date": pivots[-1]["pivot_date"], "confirmed_date": bar["date"]}
                if not downward or (trend and mode == "first_second_third"):
                    kind = ("first_buy" if downward else "first_sell") if trend else "range_divergence_sell"
                    divergence_event = _event(kind, pivots[-1], bar, stop=pivots[-1]["price"] if downward else None, reason=reason)
                    divergence_event["evidence"] = divergence
        # Resolve coincident structural descriptions into one research event.
        # This is signal identity, not a restriction on user order quantities.
        chosen = third or divergence_event or second
        if chosen is not None:
            events.append(chosen)
        watch = _divergence_observation(pivots, bar, areas)
        if watch is not None:
            observations.append(watch)
    strokes = [_stroke(a, b, i, provisional=i == len(pivots) - 2) for i, (a, b) in enumerate(zip(pivots, pivots[1:]))]
    for index, stroke in enumerate(strokes):
        stroke["locked_date"] = pivots[index + 2]["sequence_confirmed_date"] if index + 2 < len(pivots) else None
    segment_result = analyze_segments(strokes)
    result["structures"] = {"fractals": fractals, "strokes": strokes, "centers": centers, "segments": segment_result["segments"], "segment_pending": segment_result["pending"], "segment_scope": segment_result["scope"]}
    result["signal_history"] = events
    result["divergence_history"] = divergences
    result["center_history"] = center_history
    result["observations"] = [item for item in observations if item["confirmed_date"] == raw[-1]["date"]]
    result["signals"] = [item for item in events if item["confirmed_date"] == raw[-1]["date"]]
    result["bar_count"] = len(raw)
    result["standard_bar_count"] = len(standard)
    if result["signals"]:
        result.update(result["signals"][-1])
    elif len(raw) >= 3:
        result["status"] = "observing" if centers else "forming_structure"
        if centers and centers[-1]["state"].startswith("awaiting_"):
            upward = centers[-1]["state"] == "awaiting_pullback_up"
            result["reason"] = "已向上离开笔中枢代理，等待第一次回试成笔及底分型右侧确认。" if upward else "已向下离开笔中枢代理，等待第一次回抽成笔及顶分型右侧确认。"
        elif result["observations"]:
            result["reason"] = result["observations"][-1]["reason"]
        elif events:
            last = events[-1]
            result["reason"] = f"最新结构信号于 {last['confirmed_date']} 确认，今天没有新确认的结构信号。"
        else:
            result["reason"] = f"已识别 {len(fractals)} 个分型、{len(strokes)} 笔、{len(centers)} 个笔中枢代理，等待首次有效回试确认。"
    return result
