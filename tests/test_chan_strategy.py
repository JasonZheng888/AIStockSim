"""Structural and chronological regressions for the daily stroke experiment."""

from copy import deepcopy
from datetime import date, timedelta
import unittest

from chan_strategy import analyze_chan


def bars_from_prices(prices):
    start = date(2025, 1, 1)
    return [
        {"date": (start + timedelta(days=i)).isoformat(), "open": value,
         "high": value + 0.2, "low": value - 0.2, "close": value, "volume": 1000}
        for i, value in enumerate(prices)
    ]


def swing_prices(pivots, distance=4):
    """Known alternating extrema with one independent bar between fractals."""
    first, second = pivots[:2]
    sign = 1 if first > second else -1
    prices = [first - sign * 2, first - sign, first]
    for left, right in zip(pivots, pivots[1:]):
        prices.extend(left + (right - left) * step / distance for step in range(1, distance + 1))
    prices.append(pivots[-1] + (0.5 if pivots[-1] < pivots[-2] else -0.5))
    return prices


class ChanStrategyTests(unittest.TestCase):
    def setUp(self):
        # Three locked strokes overlap [8.8,11.2], followed by 14.2 departure
        # and 11.8 first return. The bottom is at day 23, confirmed on day 24.
        self.third_buy = bars_from_prices(swing_prices([12, 8, 11, 9, 14, 12]))

    def test_third_buy_waits_for_right_bar_and_uses_confirmation_close(self):
        before = analyze_chan(self.third_buy[:-1])
        self.assertEqual(before["signal"], "wait")
        self.assertEqual(before["signals"], [])
        result = analyze_chan(self.third_buy)
        self.assertEqual(result["signal"], "buy")
        self.assertEqual(result["pattern"], "proxy_3buy")
        self.assertEqual(result["kind"], "third_buy")
        self.assertEqual(result["confirmed_date"], self.third_buy[-1]["date"])
        self.assertEqual(result["pivot_date"], self.third_buy[-2]["date"])
        self.assertEqual(result["reference_price"], self.third_buy[-1]["close"])
        self.assertAlmostEqual(result["stop_price"], 11.8)
        self.assertEqual(len(result["signals"]), 1)
        centre = result["structures"]["centers"][0]
        self.assertAlmostEqual(centre["low"], 8.8)
        self.assertAlmostEqual(centre["high"], 11.2)
        self.assertEqual(centre["state"], "broken_up")

    def test_first_retest_into_zone_is_not_third_buy(self):
        rows = bars_from_prices(swing_prices([12, 8, 11, 9, 14, 10]))
        result = analyze_chan(rows)
        self.assertEqual(result["signal"], "wait")
        self.assertFalse(any(item["kind"] == "third_buy" for item in result["signal_history"]))
        self.assertEqual(result["structures"]["centers"][0]["failed_retests"], 1)

    def test_price_breakout_without_confirmed_return_is_not_entry(self):
        rows = bars_from_prices(swing_prices([12, 8, 11, 9, 14]))
        result = analyze_chan(rows)
        self.assertEqual(result["signal"], "wait")
        self.assertEqual(result["structures"]["centers"][0]["state"], "awaiting_pullback_up")

    def test_third_sell_is_mirrored_structure(self):
        rows = bars_from_prices([30 - p for p in swing_prices([12, 8, 11, 9, 14, 12])])
        result = analyze_chan(rows)
        self.assertEqual(result["signal"], "sell")
        self.assertEqual(result["pattern"], "proxy_3sell")
        self.assertIsNone(result["stop_price"])
        self.assertEqual(result["confirmed_date"], rows[-1]["date"])

    def test_second_buy_is_independent_optional_mode(self):
        rows = bars_from_prices(swing_prices([15, 10, 13, 8, 14, 10]))
        self.assertEqual(analyze_chan(rows)["signal"], "wait")
        result = analyze_chan(rows, mode="second_third")
        self.assertEqual(result["signal"], "buy")
        self.assertEqual(result["pattern"], "proxy_2buy")
        self.assertEqual(result["signal_history"][0]["kind"], "second_buy")
        self.assertAlmostEqual(result["stop_price"], 9.8)

    def test_second_buy_requires_structural_rebound_and_higher_return(self):
        for pivots in ([15, 10, 13, 8, 12, 10], [15, 10, 13, 8, 14, 7]):
            with self.subTest(pivots=pivots):
                result = analyze_chan(bars_from_prices(swing_prices(pivots)), mode="second_third")
                self.assertFalse(any(event["kind"] == "second_buy" for event in result["signal_history"]))

    def test_macd_area_divergence_is_observation_and_never_first_buy(self):
        rows = bars_from_prices(swing_prices([30, 22, 27, 18, 24, 16, 21, 14, 20, 13], distance=6))
        for mode in ("third_buy", "second_third"):
            with self.subTest(mode=mode):
                result = analyze_chan(rows, mode)
                self.assertEqual(result["signal"], "wait")
                self.assertEqual(result["signals"], [])
                self.assertEqual(result["observations"][-1]["kind"], "divergence_watch")
                self.assertEqual(result["observations"][-1]["confirmed_date"], rows[-1]["date"])

    def test_strict_strokes_reject_short_fractal_spacing(self):
        result = analyze_chan(bars_from_prices(swing_prices([12, 8, 11, 9, 14, 12], distance=3)))
        self.assertEqual(result["signal"], "wait")
        self.assertLess(len(result["structures"]["strokes"]), 5)

    def test_directional_inclusion_does_not_invent_extra_bars(self):
        rows = bars_from_prices([10, 11, 12, 11.5, 11])
        # Ascending tail [11.8,12.2] contains this bar. It merges upward into
        # [11.9,12.2] instead of generating a new pivot or an extra standard bar.
        rows[3].update(open=12, close=12, high=12.1, low=11.9)
        result = analyze_chan(rows)
        self.assertEqual(result["standard_bar_count"], 4)
        self.assertEqual(len(result["structures"]["fractals"]), 1)
        fractal = result["structures"]["fractals"][0]
        self.assertEqual(fractal["kind"], "top")
        self.assertAlmostEqual(fractal["high"], 12.2)
        self.assertAlmostEqual(fractal["low"], 11.9)
        self.assertEqual(fractal["confirmed_date"], rows[-1]["date"])

    def test_same_kind_extreme_extends_tail_without_erasing_old_event(self):
        original = analyze_chan(self.third_buy)
        # The shallow rebound is too short to become a strict upward stroke;
        # the new bottom extends the provisional final downward stroke.
        extra_prices = [12.4, 11.0, 11.5]
        extended = bars_from_prices([bar["close"] for bar in self.third_buy] + extra_prices)
        result = analyze_chan(extended)
        self.assertEqual(result["signal"], "wait")
        self.assertEqual(result["signal_history"], original["signal_history"])
        self.assertLess(result["structures"]["strokes"][-1]["end_price"], original["stop_price"])
        self.assertEqual(original["signal_history"][0]["stop_price"], 11.8)

    def test_every_prefix_matches_immutable_full_history(self):
        prices = swing_prices([12, 8, 11, 9, 14, 12]) + [12.4, 11.0, 11.5, 13, 15, 14, 13, 12, 10, 11]
        rows = bars_from_prices(prices)
        full_history = analyze_chan(rows, "second_third")["signal_history"]
        for end in range(1, len(rows) + 1):
            with self.subTest(end=end):
                prefix = analyze_chan(rows[:end], "second_third")
                cutoff = rows[end - 1]["date"]
                expected = [event for event in full_history if event["confirmed_date"] <= cutoff]
                self.assertEqual(prefix["signal_history"], expected)
                self.assertTrue(all(event["confirmed_date"] == cutoff for event in prefix["signals"]))

    def test_extreme_extension_cannot_swallow_opposite_endpoint(self):
        ranges = [(18, 17), (19, 18), (20, 19), (19, 18), (18, 17),
                  (17, 16), (16, 15), (17, 16), (24, 23), (22, 14), (23, 15)]
        rows = bars_from_prices([(hi + lo) / 2 for hi, lo in ranges])
        for row, (hi, lo) in zip(rows, ranges):
            row.update(high=hi, low=lo)
        result = analyze_chan(rows)
        # The new bottom [14,22] encloses the old top [19,20]. Despite its
        # lower extreme, it cannot replace the valid stroke's [15,16] bottom.
        self.assertEqual(result["structures"]["fractals"][-1]["price"], 14)
        self.assertEqual(result["structures"]["strokes"][-1]["end_price"], 15)
        self.assertEqual(result["signal"], "wait")

    def test_signal_is_not_reissued_on_next_day_or_later_same_zone_retest(self):
        rows = bars_from_prices(swing_prices([12, 8, 11, 9, 14, 12, 15, 13]))
        result = analyze_chan(rows)
        buys = [event for event in result["signal_history"] if event["kind"] == "third_buy"]
        self.assertEqual(len(buys), 1)
        self.assertEqual(result["signal"], "wait")
        self.assertEqual(buys[0]["signal_id"], analyze_chan(self.third_buy)["signal_id"])

    def test_disjoint_new_center_replaces_old_zone_without_inventing_past_entry(self):
        # Initial centre is only locked after its departure already happened.
        # Later independent strokes form another centre; the engine must not
        # remain attached to the initial price range for the rest of history.
        prices = swing_prices([8, 12, 9, 14, 13, 17, 15, 19, 16, 22, 20])
        for mirror in (False, True):
            with self.subTest(mirror=mirror):
                rows = bars_from_prices([30 - p for p in prices] if mirror else prices)
                result = analyze_chan(rows)
                centres = result["structures"]["centers"]
                self.assertEqual(len(centres), 2)
                self.assertEqual(centres[0]["state"], "superseded_down" if mirror else "superseded_up")
                self.assertEqual(result["signal"], "sell" if mirror else "buy")
                # 3.3 also emits independently defined divergence exits;
                # this regression concerns the sole third-class zone event.
                self.assertEqual(len([event for event in result["signal_history"] if event["kind"] in ("third_buy", "third_sell")]), 1)
                for end in range(1, len(rows) + 1):
                    prefix = analyze_chan(rows[:end])
                    self.assertEqual(prefix["signal_history"], [e for e in result["signal_history"] if e["confirmed_date"] <= rows[end - 1]["date"]])

    def test_consumed_center_allows_new_independent_three_stroke_center(self):
        rows = bars_from_prices(swing_prices([12, 8, 11, 9, 14, 12, 17, 14, 16, 14.5, 20, 18]))
        result = analyze_chan(rows)
        self.assertEqual(result["signal"], "buy")
        buys = [event for event in result["signal_history"] if event["kind"] == "third_buy"]
        self.assertEqual(len(buys), 2)
        self.assertNotEqual(buys[0]["signal_id"], buys[1]["signal_id"])

    def test_bad_data_never_produces_order(self):
        samples = []
        duplicate = deepcopy(self.third_buy)
        duplicate[-1]["date"] = duplicate[-2]["date"]
        samples.append(duplicate)
        missing = deepcopy(self.third_buy)
        del missing[-1]["low"]
        samples.append(missing)
        for field, value in (("close", float("nan")), ("low", -1), ("high", 0.1)):
            invalid = deepcopy(self.third_buy)
            invalid[-1][field] = value
            samples.append(invalid)
        samples.append(list(reversed(self.third_buy)))
        for rows in samples:
            with self.subTest(last=rows[-1]):
                result = analyze_chan(rows)
                self.assertEqual(result["status"], "data_error")
                self.assertEqual(result["signal"], "wait")
                self.assertEqual(result["signals"], [])

    def test_no_input_mutation_and_invalid_mode(self):
        original = deepcopy(self.third_buy)
        analyze_chan(self.third_buy)
        self.assertEqual(self.third_buy, original)
        self.assertEqual(analyze_chan(self.third_buy, "anything")["status"], "data_error")
        self.assertEqual(analyze_chan([])["status"], "insufficient_data")


if __name__ == "__main__":
    unittest.main()
