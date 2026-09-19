import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# mover.py 在 import 时就按 AUTOMATION_STATE_DIR 建目录，所以先把它指到临时目录再加载
_STATE_TMP = tempfile.mkdtemp(prefix="mover-test-state-")
os.environ["AUTOMATION_STATE_DIR"] = _STATE_TMP
_MOVER_PATH = Path(__file__).resolve().parents[2] / "automation" / "mover.py"
_spec = importlib.util.spec_from_file_location("mover_under_test", _MOVER_PATH)
mover = importlib.util.module_from_spec(_spec)
sys.modules["mover_under_test"] = mover
_spec.loader.exec_module(mover)

NOW = 1_800_000_000
HOUR = 3600


class BackfillCutoffTests(unittest.TestCase):
    def test_default_mode_is_all_and_touches_nothing(self):
        state = {}
        cutoff, changed = mover.resolve_backfill_cutoff({}, state, now=NOW)
        self.assertIsNone(cutoff)
        self.assertFalse(changed)
        self.assertEqual(state, {})

    def test_explicit_all_mode_ignores_existing_marker(self):
        state = {"first_start_at": NOW - 10 * 24 * HOUR}
        cutoff, changed = mover.resolve_backfill_cutoff({"backfill": {"mode": "all"}}, state, now=NOW)
        self.assertIsNone(cutoff)
        self.assertFalse(changed)

    def test_first_start_records_now_and_uses_default_lookback(self):
        state = {}
        cutoff, changed = mover.resolve_backfill_cutoff({"backfill": {"mode": "since_first_start"}}, state, now=NOW)
        self.assertTrue(changed)
        self.assertEqual(state["first_start_at"], NOW)
        self.assertEqual(cutoff, NOW - mover.DEFAULT_LOOKBACK_HOURS * HOUR)

    def test_restart_keeps_original_start_point(self):
        first = NOW - 5 * 24 * HOUR
        state = {"first_start_at": first}
        cfg = {"backfill": {"mode": "since_first_start", "lookback_hours": 24}}
        cutoff, changed = mover.resolve_backfill_cutoff(cfg, state, now=NOW)
        self.assertFalse(changed)
        self.assertEqual(cutoff, first - 24 * HOUR)

    def test_lookback_change_is_applied_without_reset(self):
        first = NOW - 2 * 24 * HOUR
        state = {"first_start_at": first}
        cutoff_a, _ = mover.resolve_backfill_cutoff({"backfill": {"mode": "since_first_start", "lookback_hours": 6}}, state, now=NOW)
        cutoff_b, _ = mover.resolve_backfill_cutoff({"backfill": {"mode": "since_first_start", "lookback_hours": 72}}, state, now=NOW)
        self.assertEqual(cutoff_a, first - 6 * HOUR)
        self.assertEqual(cutoff_b, first - 72 * HOUR)
        self.assertEqual(state["first_start_at"], first)

    def test_garbage_marker_or_lookback_falls_back(self):
        state = {"first_start_at": "yesterday"}
        cfg = {"backfill": {"mode": "since_first_start", "lookback_hours": "lots"}}
        cutoff, changed = mover.resolve_backfill_cutoff(cfg, state, now=NOW)
        self.assertTrue(changed)
        self.assertEqual(state["first_start_at"], NOW)
        self.assertEqual(cutoff, NOW - mover.DEFAULT_LOOKBACK_HOURS * HOUR)


class CutoffDecisionTests(unittest.TestCase):
    def test_older_than_cutoff_is_skipped(self):
        self.assertTrue(mover.is_before_cutoff({"timestamp": NOW - 1}, NOW))

    def test_newer_or_equal_passes(self):
        self.assertFalse(mover.is_before_cutoff({"timestamp": NOW}, NOW))
        self.assertFalse(mover.is_before_cutoff({"timestamp": NOW + 1}, NOW))

    def test_unknown_date_or_no_cutoff_passes(self):
        self.assertFalse(mover.is_before_cutoff({"timestamp": None}, NOW))
        self.assertFalse(mover.is_before_cutoff({}, NOW))
        self.assertFalse(mover.is_before_cutoff({"timestamp": 0}, None))


class FlatPlaylistLineTests(unittest.TestCase):
    def test_parses_timestamp_and_keeps_pipes_in_title(self):
        e = mover.parse_flat_playlist_line("abc123|1789802280|https://www.youtube.com/watch?v=abc123|A|B|C")
        self.assertEqual(e, {"id": "abc123", "timestamp": 1789802280,
                             "url": "https://www.youtube.com/watch?v=abc123", "title": "A|B|C"})

    def test_missing_timestamp_is_none(self):
        e = mover.parse_flat_playlist_line("abc123|NA|https://www.youtube.com/watch?v=abc123|title")
        self.assertIsNone(e["timestamp"])

    def test_short_line_is_rejected(self):
        self.assertIsNone(mover.parse_flat_playlist_line("abc123|title"))


class StateFileTests(unittest.TestCase):
    def test_state_round_trip(self):
        mover.save_state({"first_start_at": NOW})
        self.assertEqual(mover.load_state(), {"first_start_at": NOW})
        self.assertTrue(str(mover.STATE_FILE).startswith(_STATE_TMP))


if __name__ == "__main__":
    unittest.main()
