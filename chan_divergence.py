"""Causal, explicitly pen-level divergence evidence, without account rules.

Two independently formed zones with disjoint *whole constituent ranges* are
required for a trend label. A single zone may support a range-divergence
observation / exit, never a first-buy label. A and C are actual same-direction
strokes on either side of the latter zone, not arbitrary recent MACD troughs.
They remain proxies for the book's completed lower-level movement types.
"""

from __future__ import annotations


def macd_evidence(bars: list[dict]) -> dict[str, list[float]]:
    """Forward-only EMA(12,26,9); cumulative signed-side histogram areas."""
    positive, negative, diffs, deas = [0.0], [0.0], [], []
    if not bars:
        return {"positive": positive, "negative": negative, "diff": diffs, "dea": deas}
    fast = slow = bars[0]["close"]
    dea = 0.0
    for bar in bars:
        fast += (bar["close"] - fast) * (2.0 / 13.0)
        slow += (bar["close"] - slow) * (2.0 / 27.0)
        diff = fast - slow
        dea += (diff - dea) * 0.2
        histogram = 2.0 * (diff - dea)
        positive.append(positive[-1] + max(0.0, histogram))
        negative.append(negative[-1] + max(0.0, -histogram))
        diffs.append(diff)
        deas.append(dea)
    return {"positive": positive, "negative": negative, "diff": diffs, "dea": deas}


def _comparison_zone(center: dict, pivots: list[dict], downward: bool, out_index: int) -> dict | None:
    """Choose an opposite-direction / same / opposite internal three-stroke B.

An active centre may have been discovered with its incoming trend stroke as
the first constituent. Shift by exactly one stroke in that case; require the
new full triple to be locked and to overlap the active centre. Never count A
both as an entry leg and as B. This deterministic alignment is a pen proxy.
    """
    first = center["source_strokes"][0]
    first_down = pivots[first + 1]["kind"] == "bottom"
    if first_down == downward:
        first += 1
    last = first + 2
    if last >= out_index:
        return None
    points = pivots[first:first + 4]
    low = max(min(a["price"], b["price"]) for a, b in zip(points, points[1:]))
    high = min(max(a["price"], b["price"]) for a, b in zip(points, points[1:]))
    if low >= high or low >= center["high"] or high <= center["low"]:
        return None
    prices = [point["price"] for point in points]
    for index in center["extension_strokes"]:
        if last < index < out_index:
            prices.extend((pivots[index]["price"], pivots[index + 1]["price"]))
    return {**center, "source_strokes": list(range(first, last + 1)), "low": low, "high": high, "range_low": min(prices), "range_high": max(prices)}


def divergence_context(pivots: list[dict], centers: list[dict], macd: dict) -> dict | None:
    """Evidence available when the current endpoint's right bar has closed.

The entry leg precedes all three direction-aligned centre constituents.
    """
    if len(pivots) < 6:
        return None
    out_index = len(pivots) - 2
    end = pivots[-1]
    downward = end["kind"] == "bottom"
    area = macd["negative" if downward else "positive"]
    for center_index in range(len(centers) - 1, -1, -1):
        center = _comparison_zone(centers[center_index], pivots, downward, out_index)
        if center is None:
            continue
        entry_index = center["source_strokes"][0] - 1
        if entry_index < 0:
            continue
        a, b = pivots[entry_index:entry_index + 2]
        c, d = pivots[-2:]
        if (b["kind"] == "bottom") != downward:
            continue
        # Both legs genuinely leave/enter the same zone in the trend direction.
        if downward:
            valid = a["price"] > center["high"] and b["price"] <= center["high"] and c["price"] >= center["low"] and d["price"] < min(center["low"], b["price"])
        else:
            valid = a["price"] < center["low"] and b["price"] >= center["low"] and c["price"] <= center["high"] and d["price"] > max(center["high"], b["price"])
        if not valid:
            continue
        # A later independent centre between B and C makes this old B stale.
        if any(other["source_strokes"][0] > center["source_strokes"][-1] and other["source_strokes"][-1] < out_index for other in centers[center_index + 1:]):
            continue
        prior_area = area[b["raw_index"] + 1] - area[a["raw_index"]]
        current_area = area[d["raw_index"] + 1] - area[c["raw_index"]]
        if not 0 < current_area < prior_area:
            continue
        previous = None
        for prior_center in reversed(centers[:center_index]):
            other = _comparison_zone(prior_center, pivots, downward, entry_index)
            if other is None:
                continue
            if other["source_strokes"][-1] >= entry_index:
                continue
            # Comparing overlap bands alone would mistake expanding ranges
            # for two non-overlapping trend centres (book lesson 20).
            if (center["range_high"] < other["range_low"] if downward else center["range_low"] > other["range_high"]):
                previous = other
                break
            # The immediately preceding independent centre governs; do not
            # skip an overlapping neighbour to cherry-pick an older trend.
            break
        return {
            "classification": "trend" if previous else "range",
            "level": "daily_stroke_proxy", "direction": "down" if downward else "up",
            "center_id": center["id"], "previous_center_id": previous["id"] if previous else None,
            "comparison_source_strokes": list(center["source_strokes"]),
            "center_band": [center["low"], center["high"]],
            "center_range": [center["range_low"], center["range_high"]],
            "previous_center_range": [previous["range_low"], previous["range_high"]] if previous else None,
            "entry_stroke": entry_index, "exit_stroke": out_index,
            "entry_dates": [a["pivot_date"], b["pivot_date"]],
            "exit_dates": [c["pivot_date"], d["pivot_date"]],
            "entry_area": prior_area, "exit_area": current_area,
            "area_ratio": current_area / prior_area,
            "zero_axis_crossed_in_center": min(macd["diff"][b["raw_index"]:c["raw_index"] + 1]) <= 0 <= max(macd["diff"][b["raw_index"]:c["raw_index"] + 1]),
            "confirmation": "right_bar_closed; lower_level_completion_unverified",
        }
    return None
