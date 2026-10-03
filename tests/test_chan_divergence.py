"""End-to-end A/B/C evidence, mode selection, exits and causal replay."""

from copy import deepcopy
import unittest

from chan_strategy import analyze_chan
from chan_divergence import macd_evidence
from test_chan_strategy import bars_from_prices, swing_prices


TREND = [100, 110, 102, 108, 95, 101, 80, 89, 82, 88, 78]


def rows_for(pivots, mirror=False):
    prices = swing_prices(pivots, distance=6)
    return bars_from_prices([250 - price for price in prices] if mirror else prices)


class ChanDivergenceTests(unittest.TestCase):
    def test_first_buy_requires_explicit_mode_and_structural_evidence(self):
        rows = rows_for(TREND)
        for mode in ("third_buy", "second_third"):
            self.assertEqual(analyze_chan(rows, mode)["signal"], "wait")
        result = analyze_chan(rows, "first_second_third")
        self.assertEqual(result["kind"], "first_buy")
        self.assertEqual(result["pattern"], "proxy_1buy")
        self.assertEqual(result["confirmed_date"], rows[-1]["date"])
        self.assertEqual(result["pivot_date"], rows[-2]["date"])
        self.assertEqual(result["reference_price"], rows[-1]["close"])
        self.assertAlmostEqual(result["stop_price"], 77.8)
        evidence = result["evidence"]
        self.assertEqual(evidence["classification"], "trend")
        self.assertIsNotNone(evidence["previous_center_id"])
        self.assertLess(evidence["center_range"][1], evidence["previous_center_range"][0])
        self.assertLess(evidence["entry_stroke"], evidence["comparison_source_strokes"][0])
        self.assertLess(evidence["comparison_source_strokes"][-1], evidence["exit_stroke"])
        self.assertLess(evidence["exit_area"], evidence["entry_area"])
        # No global above-MA / positive-MACD requirement suppresses this buy.
        self.assertLess(macd_evidence(rows)["diff"][-1], 0)

    def test_first_buy_not_backfilled_to_extreme_day(self):
        rows = rows_for(TREND)
        result = analyze_chan(rows[:-1], "first_second_third")
        self.assertFalse(any(item["kind"] == "first_buy" for item in result["signal_history"]))

    def test_single_zone_divergence_is_not_mislabelled_first_buy(self):
        result = analyze_chan(rows_for([120, 100, 112, 102, 110, 98]), "first_second_third")
        self.assertEqual(result["signal"], "wait")
        evidence = result["divergence_history"][-1]["evidence"]
        self.assertEqual(evidence["classification"], "range")
        self.assertIsNone(evidence["previous_center_id"])
        self.assertFalse(any(item["kind"] == "first_buy" for item in result["signal_history"]))

    def test_disjoint_overlap_bands_with_overlapping_whole_ranges_are_not_trend(self):
        pivots = [75, 100, 87, 95, 81, 86, 70, 80, 73, 79, 68]
        result = analyze_chan(rows_for(pivots), "first_second_third")
        self.assertEqual(result["divergence_history"][-1]["evidence"]["classification"], "range")
        self.assertFalse(any(item["kind"] == "first_buy" for item in result["signal_history"]))

    def test_stronger_exit_leg_is_not_divergence(self):
        result = analyze_chan(rows_for(TREND[:-1] + [40]), "first_second_third")
        self.assertFalse(any(item["kind"] == "first_buy" for item in result["signal_history"]))

    def test_range_divergence_can_exit_without_claiming_first_sell(self):
        for mode in ("third_buy", "second_third", "first_second_third"):
            result = analyze_chan(rows_for([120, 100, 112, 102, 110, 98], mirror=True), mode)
            self.assertEqual(result["kind"], "range_divergence_sell")
            self.assertEqual(result["signal"], "sell")
            self.assertIsNone(result["stop_price"])

    def test_trend_first_sell_and_first_lower_rebound_second_sell(self):
        for mode in ("third_buy", "second_third", "first_second_third"):
            first = analyze_chan(rows_for(TREND, mirror=True), mode)
            self.assertEqual(first["kind"], "first_sell")
            second = analyze_chan(rows_for(TREND + [86, 81], mirror=True), mode)
            self.assertEqual(second["kind"], "second_sell")
            self.assertEqual(second["evidence"]["subtype"], "after_first_divergence")

    def test_second_buy_after_first_need_not_break_previous_lower_high(self):
        # Rebound 86 stays below prior lower high 88. It is a valid higher
        # first retest of the structural first-buy anchor, not the old reversal.
        rows = rows_for(TREND + [86, 81])
        self.assertEqual(analyze_chan(rows, "third_buy")["signal"], "wait")
        for mode in ("second_third", "first_second_third"):
            result = analyze_chan(rows, mode)
            self.assertEqual(result["kind"], "second_buy")
            self.assertEqual(result["evidence"]["subtype"], "after_first_divergence")
            self.assertAlmostEqual(result["stop_price"], 80.8)
            self.assertLess(result["stop_price"], result["reference_price"])

    def test_first_retest_below_anchor_does_not_make_second_buy(self):
        result = analyze_chan(rows_for(TREND + [86, 77]), "first_second_third")
        self.assertFalse(any(item["kind"] == "second_buy" for item in result["signal_history"]))

    def test_first_buy_tail_extension_preserves_original_event_without_reissue(self):
        rows = rows_for(TREND)
        original = analyze_chan(rows, "first_second_third")
        prices = [row["close"] for row in rows] + [79.0, 77.5, 78.0]
        updated = analyze_chan(bars_from_prices(prices), "first_second_third")
        self.assertEqual(updated["signal"], "wait")
        self.assertEqual(updated["signal_history"], original["signal_history"])
        self.assertAlmostEqual(updated["signal_history"][-1]["stop_price"], 77.8)
        self.assertLess(updated["structures"]["strokes"][-1]["end_price"], 77.8)

    def test_failed_departure_extends_range_but_not_the_original_center_band(self):
        result = analyze_chan(rows_for([12, 8, 11, 9, 14, 10]))
        center = result["structures"]["centers"][0]
        self.assertAlmostEqual(center["high"], 11.2)
        self.assertAlmostEqual(center["range_high"], 14.2)
        self.assertEqual(center["extension_strokes"], [3])
        self.assertEqual(result["center_history"][-1]["state"], "seeking_departure")

    def test_all_modes_full_history_equal_prefix_replay_including_diagnostics(self):
        for mirror in (False, True):
            rows = rows_for(TREND + [86, 81, 90, 84], mirror=mirror)
            for mode in ("third_buy", "second_third", "first_second_third"):
                full = analyze_chan(rows, mode)
                for end in range(1, len(rows) + 1):
                    prefix = analyze_chan(rows[:end], mode)
                    day = rows[end - 1]["date"]
                    for key in ("signal_history", "divergence_history", "center_history"):
                        self.assertEqual(prefix[key], [item for item in full[key] if item["confirmed_date"] <= day], (mode, mirror, end, key))
                    self.assertEqual(prefix["structures"]["segments"], [item for item in full["structures"]["segments"] if item["confirmed_date"] <= day])

    def test_future_price_perturbation_preserves_previously_confirmed_signals(self):
        prefix = rows_for(TREND)
        snapshot = analyze_chan(prefix, "first_second_third")["signal_history"]
        future = rows_for(TREND + [90, 65, 98, 60])
        # rows_for uses the same complete right-side path for every old pivot;
        # splice after the observed prefix to make the old input byte-identical.
        future[:len(prefix)] = deepcopy(prefix)
        result = analyze_chan(future, "first_second_third")
        self.assertEqual(snapshot, [event for event in result["signal_history"] if event["confirmed_date"] <= prefix[-1]["date"]])

    def test_macd_prefix_arrays_do_not_use_future_values(self):
        rows = rows_for(TREND)
        full = macd_evidence(rows)
        for end in (1, 12, 30, len(rows) - 1):
            prefix = macd_evidence(rows[:end])
            for field in ("positive", "negative"):
                self.assertEqual(prefix[field], full[field][:end + 1])
            for field in ("diff", "dea"):
                self.assertEqual(prefix[field], full[field][:end])


if __name__ == "__main__":
    unittest.main()
