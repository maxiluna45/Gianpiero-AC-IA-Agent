from __future__ import annotations

import os
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from ac_mcp.advisor import suggest_changes
from ac_mcp.advisor import suggest_changes_heuristic
from ac_mcp.telemetry_shared_memory import get_shared_memory_stint_status
from ac_mcp.telemetry_shared_memory import get_telemetry_capabilities
from ac_mcp.telemetry_shared_memory import list_supported_telemetry_simulators
from ac_mcp.telemetry_shared_memory import persist_shared_memory_samples
from ac_mcp.telemetry_shared_memory import read_shared_memory_log
from ac_mcp.telemetry_shared_memory import record_shared_memory_stint
from ac_mcp.telemetry_shared_memory import start_shared_memory_stint
from ac_mcp.telemetry_shared_memory import stop_shared_memory_stint


class LlmAndSharedMemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["AC_LLM_PROVIDER"] = "disabled"
        self.temp_root = Path(__file__).parent / "fixtures" / "session_logs"
        os.environ["AC_SESSION_LOG_ROOT"] = str(self.temp_root)

    def test_advisor_raises_when_llm_is_required_and_disabled(self) -> None:
        setup = {
            "SUSPENSION": {"ARB_REAR": "6"},
            "DIFF": {"DIFF_POWER": "30"},
        }
        with self.assertRaises(RuntimeError):
            suggest_changes(
                setup=setup,
                symptoms="sobrevira salida",
                track_conditions="",
                use_llm=True,
                require_llm=True,
            )

    def test_heuristic_suggestions_available_as_guidance(self) -> None:
        setup = {
            "SUSPENSION": {"ARB_REAR": "6"},
            "DIFF": {"DIFF_POWER": "30"},
        }
        result = suggest_changes_heuristic(
            setup=setup,
            symptoms="sobrevira salida",
            track_conditions="",
        )
        self.assertGreaterEqual(len(result["suggested_changes"]), 1)

    def test_persist_shared_memory_samples_exports_files(self) -> None:
        samples = [
            {
                "simulator": "assetto_corsa",
                "timestamp_utc": "2026-01-01T00:00:00Z",
                "physics": {"speed_kmh": 120.0, "rpms": 6400, "gear": 4, "gas": 0.8, "brake": 0.0, "fuel": 20.0, "air_temp_c": 18.0, "road_temp_c": 24.0},
                "graphics": {"completed_laps": 3, "position": 1, "is_in_pit": False, "surface_grip": 0.99},
                "static": {"car_model": "ks_porsche_911_gt3", "track": "spa"},
            }
        ]

        result = persist_shared_memory_samples(session_id="test", samples=samples, export_csv=True)
        self.assertEqual(result["sample_count"], 1)
        self.assertEqual(result["simulator"], "assetto_corsa")
        self.assertTrue(Path(result["json_path"]).exists())
        self.assertTrue(Path(result["csv_path"]).exists())

    def test_list_supported_telemetry_simulators(self) -> None:
        result = list_supported_telemetry_simulators()
        self.assertIn("assetto_corsa", result["supported"])
        self.assertIn("iracing", result["supported"])

    def test_get_telemetry_capabilities_for_iracing(self) -> None:
        result = get_telemetry_capabilities("iracing")
        self.assertEqual(result["simulator"], "iracing")
        self.assertTrue(result["replay_control"])

    def test_read_shared_memory_log_returns_temperature_fields(self) -> None:
        samples = [
            {
                "timestamp_utc": "2026-01-01T00:00:00Z",
                "physics": {
                    "speed_kmh": 120.0,
                    "rpms": 6400,
                    "gear": 4,
                    "gas": 0.8,
                    "brake": 0.0,
                    "fuel": 20.0,
                    "air_temp_c": 18.0,
                    "road_temp_c": 24.0,
                    "tyre_core_temp_c": [78.0, 79.0, 81.0, 82.0],
                    "tyre_pressure": [25.8, 25.7, 25.5, 25.6],
                },
                "graphics": {"completed_laps": 3, "position": 1, "is_in_pit": False, "surface_grip": 0.99},
                "static": {"car_model": "ks_porsche_911_gt3", "track": "spa"},
            }
        ]

        persisted = persist_shared_memory_samples(session_id="read_test", samples=samples, export_csv=False)
        result = read_shared_memory_log(path=persisted["json_path"], max_samples=1)

        self.assertTrue(result["ok"])
        self.assertEqual(result["simulator"], "assetto_corsa")
        self.assertEqual(result["returned_samples"], 1)
        self.assertIn("air_temp_c", result["available_fields"]["physics"])
        self.assertIn("road_temp_c", result["available_fields"]["physics"])
        self.assertIn("tyre_core_temp_c", result["available_fields"]["physics"])

    def test_read_shared_memory_log_unions_available_fields_across_session(self) -> None:
        samples = [
            {
                "timestamp_utc": "2026-01-01T00:00:00Z",
                "physics": {
                    "speed_kmh": 120.0,
                    "rpms": 6400,
                    "gear": 4,
                },
                "graphics": {"completed_laps": 3},
                "static": {"car_model": "ks_porsche_911_gt3", "track": "spa"},
            },
            {
                "timestamp_utc": "2026-01-01T00:00:01Z",
                "physics": {
                    "speed_kmh": 121.0,
                    "tyre_core_temp_c": [78.0, 79.0, 81.0, 82.0],
                    "air_temp_c": 18.0,
                },
                "graphics": {"completed_laps": 3, "surface_grip": 0.99},
                "static": {"car_model": "ks_porsche_911_gt3", "track": "spa"},
            },
        ]

        persisted = persist_shared_memory_samples(session_id="read_union_test", samples=samples, export_csv=False)
        result = read_shared_memory_log(path=persisted["json_path"], max_samples=1)

        self.assertTrue(result["ok"])
        self.assertEqual(result["returned_samples"], 1)
        self.assertIn("tyre_core_temp_c", result["available_fields"]["physics"])
        self.assertIn("air_temp_c", result["available_fields"]["physics"])
        self.assertIn("surface_grip", result["available_fields"]["graphics"])

    @patch("ac_mcp.telemetry_shared_memory.time.sleep", return_value=None)
    @patch("ac_mcp.telemetry_shared_memory.capture_shared_memory_snapshot")
    def test_record_shared_memory_stint_includes_notices(self, mock_snapshot, _mock_sleep) -> None:
        mock_snapshot.return_value = {
            "timestamp_utc": "2026-01-01T00:00:00Z",
            "physics": {"speed_kmh": 100.0, "rpms": 5000, "gear": 4, "gas": 0.6, "brake": 0.0, "fuel": 18.0, "air_temp_c": 18.0, "road_temp_c": 24.0},
            "graphics": {"completed_laps": 1, "position": 1, "is_in_pit": False, "surface_grip": 1.0},
            "static": {"car_model": "tatuusfa1", "track": "most"},
        }

        result = record_shared_memory_stint(
            session_id="notice_test",
            sample_count=3,
            interval_ms=10,
            export_csv=False,
        )

        self.assertEqual(result["sample_count"], 3)
        self.assertEqual(result["requested_sample_count"], 3)
        self.assertIn("AVISO: captura iniciada", result["notice_start"])
        self.assertIn("AVISO: captura finalizada", result["notice_end"])
        self.assertTrue(result["started_at_utc"])
        self.assertTrue(result["finished_at_utc"])

    @patch("ac_mcp.telemetry_shared_memory.persist_shared_memory_samples")
    @patch("ac_mcp.telemetry_shared_memory.time.sleep", return_value=None)
    @patch("ac_mcp.telemetry_shared_memory.capture_shared_memory_snapshot")
    def test_async_capture_start_and_status(self, mock_snapshot, _mock_sleep, mock_persist) -> None:
        mock_snapshot.return_value = {
            "timestamp_utc": "2026-01-01T00:00:00Z",
            "physics": {"speed_kmh": 100.0, "rpms": 5000, "gear": 4, "gas": 0.6, "brake": 0.0, "fuel": 18.0, "air_temp_c": 18.0, "road_temp_c": 24.0},
            "graphics": {"completed_laps": 1, "position": 1, "is_in_pit": False, "surface_grip": 1.0},
            "static": {"car_model": "tatuusfa1", "track": "most"},
        }
        mock_persist.return_value = {
            "session_id": "async_notice",
            "sample_count": 5,
            "json_path": "memory://async_notice.json",
            "csv_path": "",
        }

        started = start_shared_memory_stint(session_id="async_notice", sample_count=5, interval_ms=10, export_csv=False)
        self.assertTrue(started["started"])
        self.assertIn("AVISO: captura iniciada", started["notice"])
        capture_id = str(started["capture_id"])

        final_status = {}
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            status = get_shared_memory_stint_status(capture_id)
            final_status = status
            if status.get("status") in {"completed", "stopped", "failed"}:
                break
            time.sleep(0.005)

        self.assertTrue(final_status.get("found"))
        self.assertEqual(final_status.get("status"), "completed")
        self.assertEqual(final_status.get("samples_collected"), 5)
        self.assertIn("AVISO: captura finalizada", str(final_status.get("notice_end", "")))

    def test_async_capture_status_not_found(self) -> None:
        status = get_shared_memory_stint_status("does-not-exist")
        self.assertFalse(status["found"])

    def test_async_capture_stop_not_found(self) -> None:
        result = stop_shared_memory_stint("does-not-exist")
        self.assertFalse(result["found"])


if __name__ == "__main__":
    unittest.main()
