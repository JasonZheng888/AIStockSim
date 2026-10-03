"""Conservative standard-feature-sequence segment diagnostics (lesson 67).

Only locked strokes enter this module. A segment needs an overlap of its first
three strokes and an opposite-stroke feature fractal. Inclusion is reduced
sequentially. The no-gap case is implemented; a gap between the first and middle
feature needs a second feature sequence and remains explicitly pending. We stop
at that unresolved boundary instead of relabelling arbitrary later triples.
These diagnostics neither establish recursive movement levels nor place trades.
"""

from __future__ import annotations


def _feature(stroke: dict) -> dict:
    up = stroke["direction"] == "up"
    return {
        "low": stroke["low"], "high": stroke["high"],
        "low_pivot": stroke["index"] if up else stroke["index"] + 1,
        "high_pivot": stroke["index"] + 1 if up else stroke["index"],
        "source_strokes": [stroke["index"]], "bootstrap": False,
    }


def _reduce(features: list[dict], item: dict) -> None:
    if not features:
        features.append(item)
        return
    last = features[-1]
    included = (last["high"] >= item["high"] and last["low"] <= item["low"]) or (item["high"] >= last["high"] and item["low"] <= last["low"])
    if not included:
        features.append(item)
        return
    if len(features) == 1:
        # No previous non-contained pair: retain an envelope as warm-up and
        # exclude it from any decisive fractal, rather than invent a direction.
        high_new, low_new = item["high"] > last["high"], item["low"] < last["low"]
        last["bootstrap"] = True
    else:
        rising = last["high"] > features[-2]["high"]
        high_new = item["high"] > last["high"] if rising else item["high"] < last["high"]
        low_new = item["low"] > last["low"] if rising else item["low"] < last["low"]
    if high_new:
        last["high"], last["high_pivot"] = item["high"], item["high_pivot"]
    if low_new:
        last["low"], last["low_pivot"] = item["low"], item["low_pivot"]
    last["source_strokes"].extend(item["source_strokes"])


def _initial_overlap(strokes: list[dict]) -> bool:
    return len(strokes) == 3 and max(item["low"] for item in strokes) < min(item["high"] for item in strokes)


def analyze_segments(strokes: list[dict]) -> dict:
    """Deterministic as-observed segment journal; newest pen is never input.

``locked_date`` is when a subsequent opposite pen first locked this pen, not
the endpoint date. Every segment records this later information timestamp.
    """
    locked = [stroke for stroke in strokes if not stroke["provisional"]]
    segments: list[dict] = []
    features: list[dict] = []
    start = None
    direction = None
    pending = None
    seen: list[dict] = []
    for stroke in locked:
        seen.append(stroke)
        if pending and pending["status"].startswith("pending_"):
            # Completing lesson 67's second sequence is deliberately not
            # approximated by a simple three-pen overlap or a later price high.
            continue
        if start is None:
            if len(seen) < 3:
                continue
            first_three = seen[-3:]
            if not _initial_overlap(first_three):
                continue
            start = first_three[0]["index"]
            direction = first_three[0]["direction"]
            features = [_feature(first_three[1])]
            continue
        if stroke["direction"] == direction:
            continue
        _reduce(features, _feature(stroke))
        if len(features) < 3:
            continue
        left, middle, right = features[-3:]
        if any(item["bootstrap"] for item in (left, middle, right)):
            continue
        upward = direction == "up"
        fractal = (middle["high"] > max(left["high"], right["high"]) and middle["low"] > max(left["low"], right["low"])) if upward else (middle["high"] < min(left["high"], right["high"]) and middle["low"] < min(left["low"], right["low"]))
        if not fractal:
            continue
        end = middle["high_pivot" if upward else "low_pivot"]
        if end - start < 3 or (end - start) % 2 != 1:
            continue
        gap = left["high"] < middle["low"] if upward else left["low"] > middle["high"]
        evidence = {
            "direction": direction, "start_stroke": start, "end_pivot": end,
            "pivot_date": seen[end]["start_date"],
            "confirmed_date": stroke["locked_date"],
            "feature_sources": [list(item["source_strokes"]) for item in (left, middle, right)],
            "feature_ranges": [[item["low"], item["high"]] for item in (left, middle, right)],
        }
        # The preceding no-gap feature fractal normally supplies this geometry
        # for a subsequent segment. Keep the necessary condition explicit for
        # every segment, including after containment / endpoint rule changes.
        if not _initial_overlap(seen[start:start + 3]):
            pending = {**evidence, "status": "pending_initial_overlap", "reason": "候选线段前三笔无正宽度交集，边界待定；不强行拼接为已完成线段。"}
            continue
        if gap:
            pending = {**evidence, "status": "pending_gap_confirmation", "reason": "第一、二特征元素间有缺口，需反向特征序列确认；本版保留待定，不生成已完成线段。"}
            continue
        segment = {
            **evidence, "kind": "standard_feature_no_gap_subset", "status": "confirmed_as_observed",
            "start_date": seen[start]["start_date"], "end_date": seen[end]["start_date"],
            "start_price": seen[start]["start_price"], "end_price": seen[end]["start_price"],
            "source_strokes": list(range(start, end)),
            "reason": "锁定笔的标准特征序列分型，第一、二元素重叠；仅实现无缺口线段子集。",
        }
        segments.append(segment)
        start = end
        direction = "down" if upward else "up"
        features = []
        for prior in seen[start:]:
            if prior["direction"] != direction:
                _reduce(features, _feature(prior))
    if pending is None:
        pending = {"status": "forming", "start_stroke": start, "direction": direction, "reason": "等待锁定笔及标准特征序列分型确认；未完成线段不参与交易。"}
    return {"segments": segments, "pending": pending, "scope": "standard_feature_no_gap_subset; no_recursive_levels"}
