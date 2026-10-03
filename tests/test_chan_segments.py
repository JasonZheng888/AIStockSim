"""Feature-fractal geometry and explicit unsupported-gap behaviour."""

import unittest
from datetime import date, timedelta

from chan_strategy import analyze_chan
from chan_segments import analyze_segments
from test_chan_strategy import bars_from_prices, swing_prices


class ChanSegmentTests(unittest.TestCase):
    def test_each_subsequent_confirmed_segment_has_initial_three_stroke_overlap(self):
        # Three successive segments, with standard-feature containment in the
        # first one. Assert the geometric invariant after each boundary reset.
        pivots = [100, 111, 109, 110, 100, 103, 102, 119, 113, 121, 112,
                  126, 114, 132, 123, 141, 138, 157, 143, 159, 146, 158,
                  145, 153, 140, 146, 142, 159, 143, 150, 133]
        for mirror in (False, True):
            prices = [300 - p for p in pivots] if mirror else pivots
            strokes = []
            for index, (a, b) in enumerate(zip(prices, prices[1:])):
                strokes.append({"index": index, "direction": "up" if b > a else "down",
                                "low": min(a, b), "high": max(a, b),
                                "start_price": a, "end_price": b,
                                "start_date": (date(2025, 1, 1) + timedelta(days=index)).isoformat(),
                                "end_date": (date(2025, 1, 1) + timedelta(days=index + 1)).isoformat(),
                                "locked_date": (date(2025, 1, 1) + timedelta(days=index + 2)).isoformat(),
                                "provisional": False})
            result = analyze_segments(strokes)
            self.assertEqual([(item["start_stroke"], item["end_pivot"]) for item in result["segments"]], [(0, 19), (19, 24), (24, 27)])
            for segment in result["segments"]:
                first = segment["start_stroke"]
                triple = strokes[first:first + 3]
                self.assertLess(max(item["low"] for item in triple), min(item["high"] for item in triple))

    def test_three_overlapping_strokes_alone_do_not_confirm_segment(self):
        result = analyze_chan(bars_from_prices(swing_prices([10, 15, 12, 20, 14])))
        self.assertEqual(result["structures"]["segments"], [])

    def test_no_gap_feature_fractal_confirms_only_after_right_feature_locked(self):
        prices = swing_prices([10, 15, 12, 20, 14, 18, 11, 17])
        for mirror in (False, True):
            rows = bars_from_prices([40 - p for p in prices] if mirror else prices)
            self.assertEqual(analyze_chan(rows[:-1])["structures"]["segments"], [])
            result = analyze_chan(rows)
            self.assertEqual(len(result["structures"]["segments"]), 1)
            segment = result["structures"]["segments"][0]
            self.assertEqual(segment["direction"], "down" if mirror else "up")
            self.assertEqual(segment["source_strokes"], [0, 1, 2])
            self.assertEqual(segment["feature_sources"], [[1], [3], [5]])
            self.assertEqual(segment["confirmed_date"], rows[-1]["date"])
            self.assertLess(segment["end_date"], segment["confirmed_date"])
            self.assertEqual(segment["kind"], "standard_feature_no_gap_subset")

    def test_gap_feature_is_pending_and_never_faked_as_finished_segment(self):
        prices = swing_prices([10, 15, 12, 20, 16, 18, 14, 17, 13, 16])
        for mirror in (False, True):
            rows = bars_from_prices([40 - p for p in prices] if mirror else prices)
            result = analyze_chan(rows)
            self.assertEqual(result["structures"]["segments"], [])
            pending = result["structures"]["segment_pending"]
            self.assertEqual(pending["status"], "pending_gap_confirmation")
            self.assertEqual(pending["end_pivot"], 3)

    def test_later_extension_of_locking_pivot_does_not_delay_old_confirmation(self):
        prices = swing_prices([10, 15, 12, 20, 14, 18, 11, 17])
        before = analyze_chan(bars_from_prices(prices))
        after = analyze_chan(bars_from_prices(prices + [16.6, 18, 17.5]))
        self.assertEqual(after["structures"]["segments"], before["structures"]["segments"])
        self.assertEqual(after["structures"]["strokes"][5]["locked_date"], before["structures"]["strokes"][5]["locked_date"])

    def test_every_prefix_preserves_segment_information_timestamp(self):
        rows = bars_from_prices(swing_prices([10, 15, 12, 20, 14, 18, 11, 17, 9, 13, 8, 12]))
        full = analyze_chan(rows)["structures"]["segments"]
        self.assertTrue(full)
        for end in range(1, len(rows) + 1):
            actual = analyze_chan(rows[:end])["structures"]["segments"]
            self.assertEqual(actual, [segment for segment in full if segment["confirmed_date"] <= rows[end - 1]["date"]])


if __name__ == "__main__":
    unittest.main()
