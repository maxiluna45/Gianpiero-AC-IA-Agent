from __future__ import annotations

import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ac_mcp.server import analyze_replay_corner_limits
from ac_mcp.server import compare_iracing_replay_vs_stint
from ac_mcp.server import coach_replay_corner_limits
from ac_mcp.server import get_iracing_replay_state
from ac_mcp.server import iracing_replay_to_shared_memory_json
from ac_mcp.server import list_replay_drivers
from ac_mcp.server import list_replays
from ac_mcp.server import search_iracing_replay
from ac_mcp.server import _extract_best_lap_time_ms


def _pack_value_string(value: str) -> bytes:
    payload = value.encode("utf-8")
    return struct.pack("<I", len(payload)) + payload


def _build_minimal_replay(path: Path, driver_name: str, num_frames: int = 1) -> None:
    count = max(1, int(num_frames))

    data = bytearray()
    data += struct.pack("<I", 16)
    data += struct.pack("<d", 16.0)
    data += _pack_value_string("clear")
    data += _pack_value_string("ks_vallelunga")
    data += _pack_value_string("extended")
    data += struct.pack("<I", 1)
    data += struct.pack("<I", count)
    data += struct.pack("<I", count)
    data += struct.pack("<I", 0)

    data += b"\x00" * (4 * count)

    data += _pack_value_string("tatuusfa1")
    data += _pack_value_string(driver_name)
    data += _pack_value_string("ES")
    data += _pack_value_string("Team")
    data += _pack_value_string("skin_01")
    data += struct.pack("<I", count)
    data += struct.pack("<I", 0)

    data += b"\x00" * 20
    for i in range(count):
        frame = bytearray(256)
        vx = 20.0 + (i % 12)
        vy = 0.0
        vz = 8.0 + (i % 5)
        struct.pack_into("<eee", frame, 164, vx, vy, vz)
        frame[244] = min(255, 100 + (i % 120))
        frame[245] = min(255, 40 + (i % 160))
        frame[246] = i // 50
        struct.pack_into("<III", frame, 220, 1000 + i * 16, 1000, 980)
        data += frame
        if i < count - 1:
            data += b"\x00" * 20

    data += struct.pack("<I", 0)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


class ReplayToolsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.replay_root = Path(self.temp_dir.name) / "replays"
        self.replay_root.mkdir(parents=True, exist_ok=True)
        os.environ["AC_REPLAY_ROOT"] = str(self.replay_root)

        self.newest = self.replay_root / "tatuusfa1_ks_vallelunga_extended_circuit_osrw_180526-230307.acreplay"
        self.oldest = self.replay_root / "toyota_supra_gt4_cup_2019_spa_2022_lfm_standing_130526-214028.acreplay"
        _build_minimal_replay(self.newest, "#1 | Kevin Woodward", num_frames=180)
        _build_minimal_replay(self.oldest, "#22 | Driver B", num_frames=60)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_list_replays_filters_and_orders_by_timestamp(self) -> None:
        result = list_replays(car="tatuusfa1", category="osrw", sort_by="timestamp_desc", limit=10)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["name"], self.newest.name)

        all_result = list_replays(sort_by="timestamp_desc", limit=10)
        self.assertEqual(all_result["count"], 2)
        self.assertEqual(all_result["items"][0]["name"], self.newest.name)
        self.assertEqual(all_result["items"][1]["name"], self.oldest.name)

    def test_list_replay_drivers_reads_driver_data(self) -> None:
        result = list_replay_drivers(replay_path=self.newest.name)
        self.assertTrue(result["ok"])
        self.assertEqual(result["summary"]["track"], "ks_vallelunga")
        self.assertEqual(len(result["drivers"]), 1)
        self.assertEqual(result["drivers"][0]["driver_name"], "#1 | Kevin Woodward")


    def test_analyze_replay_corner_limits_bridge(self) -> None:
        result = analyze_replay_corner_limits(
            replay_path=self.newest.name,
            driver_name="#1 | Kevin Woodward",
            output_dir="parsed_csv",
            bins=80,
            max_samples=500,
        )
        self.assertTrue(result["ok"])
        self.assertGreater(result["bridge"]["converted_sample_count"], 0)
        self.assertTrue(Path(result["bridge"]["shared_memory_json_path"]).exists())
        self.assertTrue(result["analysis"]["ok"])

    def test_coach_replay_corner_limits_bridge(self) -> None:
        result = coach_replay_corner_limits(
            replay_path=self.newest.name,
            driver_name="#1 | Kevin Woodward",
            output_dir="parsed_csv",
            bins=80,
            top_n=3,
            max_samples=500,
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["coaching"]["ok"])
        self.assertIn("priorities", result["coaching"])


class ExtractBestLapTimeTests(unittest.TestCase):
    """Test _extract_best_lap_time_ms filters invalid times correctly."""

    def test_filters_out_invalid_times_below_threshold(self) -> None:
        """Times < 30s (30000ms) should be filtered out."""
        rows = [
            {"bestLapTime": "4"},       # Invalid (debug frame)
            {"bestLapTime": "100"},     # Invalid (too short)
            {"bestLapTime": "5000"},    # Invalid (5s)
            {"bestLapTime": "90000"},   # Valid (90s)
            {"bestLapTime": "95000"},   # Valid (95s)
        ]
        result = _extract_best_lap_time_ms(rows)
        self.assertEqual(result, 95000, "Should return max of valid times (95s)")

    def test_returns_zero_when_no_valid_times(self) -> None:
        """If no valid times, should return 0."""
        rows = [
            {"bestLapTime": "4"},
            {"bestLapTime": "100"},
            {"bestLapTime": "5000"},
        ]
        result = _extract_best_lap_time_ms(rows)
        self.assertEqual(result, 0, "Should return 0 when no valid times found")

    def test_handles_empty_rows(self) -> None:
        """Should handle empty row list gracefully."""
        rows: list[dict[str, str]] = []
        result = _extract_best_lap_time_ms(rows)
        self.assertEqual(result, 0, "Should return 0 for empty rows")

    def test_custom_threshold(self) -> None:
        """Should respect custom min_valid_ms threshold."""
        rows = [
            {"bestLapTime": "50000"},   # 50s - valid for default (30s)
            {"bestLapTime": "60000"},   # 60s - valid for default
        ]
        # With default threshold (30000ms)
        result_default = _extract_best_lap_time_ms(rows, min_valid_ms=30000)
        self.assertEqual(result_default, 60000)

        # With higher threshold (55000ms)
        result_high = _extract_best_lap_time_ms(rows, min_valid_ms=55000)
        self.assertEqual(result_high, 60000)

        # With very high threshold (65000ms)
        result_too_high = _extract_best_lap_time_ms(rows, min_valid_ms=65000)
        self.assertEqual(result_too_high, 0)

    def test_falls_back_to_last_lap_time_when_best_is_invalid(self) -> None:
        """Should use lastLapTime if bestLapTime is corrupted in replay rows."""
        rows = [
            {"bestLapTime": "4", "lastLapTime": "65200.0"},
            {"bestLapTime": "7", "lastLapTime": "64100.0"},
            {"bestLapTime": "1", "lastLapTime": "0"},
        ]
        result = _extract_best_lap_time_ms(rows)
        self.assertEqual(result, 65200)


class IRacingReplayToolsTests(unittest.TestCase):
    @patch("ac_mcp.server.shm_get_iracing_replay_state")
    def test_get_iracing_replay_state_ok(self, mock_state) -> None:
        mock_state.return_value = {
            "simulator": "iracing",
            "connected": True,
            "is_replay_active": True,
            "replay_frame_num": 123,
            "replay_frame_num_end": 999,
            "replay_session_num": 2,
            "replay_session_time_s": 75.0,
            "replay_play_speed": 1.0,
            "replay_slow_motion": False,
            "is_paused": False,
            "is_initialized": True,
        }

        result = get_iracing_replay_state()

        self.assertTrue(result["ok"])
        self.assertEqual(result["state"]["replay_frame_num"], 123)

    @patch("ac_mcp.server.shm_iracing_replay_search")
    def test_search_iracing_replay_ok(self, mock_search) -> None:
        mock_search.return_value = {
            "ok": True,
            "command": "search",
            "mode": "next_lap",
            "state": {"replay_frame_num": 200},
        }

        result = search_iracing_replay(mode="next_lap")

        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["mode"], "next_lap")

    @patch("ac_mcp.server.shm_capture_iracing_replay_json")
    def test_iracing_replay_to_shared_memory_json_ok(self, mock_capture) -> None:
        mock_capture.return_value = {
            "ok": True,
            "json_path": "C:/tmp/iracing_replay.json",
            "csv_path": "",
            "sample_count": 240,
            "requested_sample_count": 240,
            "interval_ms": 33,
            "before": {"replay_frame_num": 1000},
            "after": {"replay_frame_num": 1240},
        }

        result = iracing_replay_to_shared_memory_json(sample_count=240, interval_ms=33)

        self.assertTrue(result["ok"])
        self.assertEqual(result["sample_count"], 240)
        self.assertIn("iracing_replay.json", result["shared_memory_json_path"])

    @patch("ac_mcp.server.compare_shm_stints")
    @patch("ac_mcp.server.shm_capture_iracing_replay_json")
    def test_compare_iracing_replay_vs_stint_ok(self, mock_capture, mock_compare) -> None:
        mock_capture.return_value = {
            "ok": True,
            "json_path": "C:/tmp/iracing_replay.json",
            "sample_count": 500,
        }
        mock_compare.return_value = {
            "ok": True,
            "objective": "lap_time",
            "corner_deltas": [],
        }

        result = compare_iracing_replay_vs_stint(
            stint_path="C:/tmp/candidate_stint.json",
            sample_count=500,
            interval_ms=33,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["captured_replay_samples"], 500)
        self.assertTrue(result["comparison"]["ok"])


if __name__ == "__main__":
    unittest.main()