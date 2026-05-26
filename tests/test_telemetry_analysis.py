from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

from ac_mcp.telemetry_analysis import analyze_shared_memory_corner_limits
from ac_mcp.telemetry_analysis import analyze_shared_memory_track_map
from ac_mcp.telemetry_analysis import coach_shared_memory_corner_limits
from ac_mcp.telemetry_analysis import compare_shared_memory_stints


class TelemetryAnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).parent / "fixtures" / "analysis_logs"
        self.shared_root = self.root / "shared_memory"
        self.shared_root.mkdir(parents=True, exist_ok=True)
        for file_path in self.shared_root.glob("*"):
            if file_path.is_file():
                file_path.unlink()
        os.environ["AC_SESSION_LOG_ROOT"] = str(self.root)
        self._previous_content_root = os.environ.get("AC_CONTENT_ROOT")

    def tearDown(self) -> None:
        if self._previous_content_root is None:
            os.environ.pop("AC_CONTENT_ROOT", None)
        else:
            os.environ["AC_CONTENT_ROOT"] = self._previous_content_root

    def _write_log(self, name: str, samples: list[dict]) -> Path:
        path = self.shared_root / name
        payload = {
            "session_id": "analysis_test",
            "created_at_utc": "2026-01-01T00:00:00Z",
            "sample_count": len(samples),
            "samples": samples,
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    def test_analyze_track_map_with_path(self) -> None:
        samples = [
            {
                "physics": {"speed_kmh": 210.0, "brake": 0.0, "gas": 1.0, "steer_angle": 0.03},
                "graphics": {"normalized_car_position": 0.10, "current_sector_index": 0, "completed_laps": 5},
                "static": {"car_model": "tatuusfa1", "track": "rt_autodrom_most"},
            },
            {
                "physics": {"speed_kmh": 85.0, "brake": 0.92, "gas": 0.12, "steer_angle": 0.22},
                "graphics": {"normalized_car_position": 0.30, "current_sector_index": 1, "completed_laps": 5},
                "static": {"car_model": "tatuusfa1", "track": "rt_autodrom_most"},
            },
            {
                "physics": {"speed_kmh": 70.0, "brake": 0.55, "gas": 0.25, "steer_angle": 0.18},
                "graphics": {"normalized_car_position": 0.55, "current_sector_index": 2, "completed_laps": 5},
                "static": {"car_model": "tatuusfa1", "track": "rt_autodrom_most"},
            },
            {
                "physics": {"speed_kmh": 95.0, "brake": 0.02, "gas": 0.96, "steer_angle": 0.15},
                "graphics": {"normalized_car_position": 0.75, "current_sector_index": 2, "completed_laps": 6},
                "static": {"car_model": "tatuusfa1", "track": "rt_autodrom_most"},
            },
        ]
        log = self._write_log("20260101T000000Z_analysis_test.json", samples)

        result = analyze_shared_memory_track_map(path=str(log), bins=20)

        self.assertTrue(result["ok"])
        self.assertEqual(result["sample_count"], 4)
        self.assertEqual(result["mapped_sample_count"], 4)
        self.assertEqual(result["track"], "rt_autodrom_most")
        self.assertEqual(result["track_length_m"], 4212.0)
        self.assertGreaterEqual(len(result["profile"]), 4)

        heavy = result["hotspots"]["heavy_braking"]
        self.assertGreaterEqual(len(heavy), 1)
        self.assertGreaterEqual(float(heavy[0]["avg_brake"]), 0.9)

    def test_analyze_track_map_defaults_to_latest(self) -> None:
        older_samples = [
            {
                "physics": {"speed_kmh": 120.0, "brake": 0.1, "gas": 0.4, "steer_angle": 0.1},
                "graphics": {"normalized_car_position": 0.20, "current_sector_index": 0, "completed_laps": 1},
                "static": {"car_model": "tatuusfa1", "track": "rt_autodrom_most"},
            }
        ]
        newer_samples = [
            {
                "physics": {"speed_kmh": 180.0, "brake": 0.0, "gas": 0.95, "steer_angle": 0.05},
                "graphics": {"normalized_car_position": 0.80, "current_sector_index": 2, "completed_laps": 3},
                "static": {"car_model": "tatuusfa1", "track": "rt_autodrom_most"},
            }
        ]

        self._write_log("20260101T000000Z_old.json", older_samples)
        latest = self._write_log("20260102T000000Z_new.json", newer_samples)

        result = analyze_shared_memory_track_map(path="", bins=16)

        self.assertTrue(result["ok"])
        self.assertEqual(Path(result["path"]).name, latest.name)
        self.assertEqual(result["sample_count"], 1)

    def test_analyze_track_map_includes_session_overview(self) -> None:
        samples = [
            {
                "timestamp_utc": "2026-01-01T00:00:00Z",
                "physics": {
                    "speed_kmh": 180.0,
                    "brake": 0.1,
                    "gas": 0.85,
                    "steer_angle": 0.08,
                    "tyre_core_temp_c": [80.0, 81.0, 82.0, 83.0],
                    "tyre_pressure": [26.1, 26.0, 25.8, 25.9],
                },
                "graphics": {"normalized_car_position": 0.15, "current_sector_index": 0, "completed_laps": 2},
                "static": {"car_model": "tatuusfa1", "track": "rt_autodrom_most"},
            },
            {
                "timestamp_utc": "2026-01-01T00:00:01Z",
                "physics": {
                    "speed_kmh": 95.0,
                    "brake": 0.65,
                    "gas": 0.22,
                    "steer_angle": 0.21,
                    "tyre_core_temp_c": [84.0, 85.0, 86.0, 87.0],
                    "tyre_pressure": [26.4, 26.3, 26.1, 26.2],
                },
                "graphics": {"normalized_car_position": 0.45, "current_sector_index": 1, "completed_laps": 2},
                "static": {"car_model": "tatuusfa1", "track": "rt_autodrom_most"},
            },
        ]
        log = self._write_log("20260102T120000Z_track_session_overview.json", samples)

        result = analyze_shared_memory_track_map(path=str(log), bins=16)

        self.assertTrue(result["ok"])
        overview = result["session_overview"]
        self.assertEqual(overview["sample_count"], 2)
        self.assertEqual(overview["timestamp_range"]["start_utc"], "2026-01-01T00:00:00Z")
        self.assertEqual(overview["metrics"]["speed_kmh"]["max"], 180.0)
        self.assertEqual(overview["tyres"]["temperature_c"]["by_tyre"]["rr"]["end"], 87.0)

    def test_analyze_track_map_filters_impossible_wheel_slip_spikes(self) -> None:
        samples = [
            {
                "timestamp_utc": "2026-01-01T00:00:00Z",
                "physics": {
                    "speed_kmh": 120.0,
                    "brake": 0.15,
                    "gas": 0.7,
                    "steer_angle": 0.08,
                    "wheel_slip": [0.12, 0.11, 0.13, 0.14],
                },
                "graphics": {"normalized_car_position": 0.15, "current_sector_index": 0, "completed_laps": 2},
                "static": {"car_model": "tatuusfa1", "track": "rt_autodrom_most"},
            },
            {
                "timestamp_utc": "2026-01-01T00:00:01Z",
                "physics": {
                    "speed_kmh": 118.0,
                    "brake": 0.18,
                    "gas": 0.68,
                    "steer_angle": 0.09,
                    "wheel_slip": [854610.0, 1.1, 0.9, 0.8],
                },
                "graphics": {"normalized_car_position": 0.18, "current_sector_index": 0, "completed_laps": 2},
                "static": {"car_model": "tatuusfa1", "track": "rt_autodrom_most"},
            },
        ]
        log = self._write_log("20260102T120500Z_track_wheelslip_filter.json", samples)

        result = analyze_shared_memory_track_map(path=str(log), bins=16)

        self.assertTrue(result["ok"])
        self.assertLess(result["session_overview"]["metrics"]["avg_wheel_slip"]["max"], 1.0)
        self.assertLess(result["session_overview"]["metrics"]["max_wheel_slip"]["max"], 2.0)

    def test_analyze_track_map_filters_impossible_pressure_and_suspension_spikes(self) -> None:
        samples = [
            {
                "timestamp_utc": "2026-01-01T00:00:00Z",
                "physics": {
                    "speed_kmh": 120.0,
                    "brake": 0.15,
                    "gas": 0.7,
                    "steer_angle": 0.08,
                    "suspension_travel": [0.05, 0.051, 0.052, 0.053],
                    "tyre_pressure": [25.0, 25.1, 24.9, 25.0],
                    "tyre_core_temp_c": [80.0, 81.0, 82.0, 83.0],
                    "tyre_wear": [98.0, 98.2, 98.4, 98.6],
                },
                "graphics": {"normalized_car_position": 0.15, "current_sector_index": 0, "completed_laps": 2},
                "static": {"car_model": "tatuusfa1", "track": "rt_autodrom_most"},
            },
            {
                "timestamp_utc": "2026-01-01T00:00:01Z",
                "physics": {
                    "speed_kmh": 118.0,
                    "brake": 0.18,
                    "gas": 0.68,
                    "steer_angle": 0.09,
                    "suspension_travel": [9.5, 0.05, 0.05, 0.05],
                    "tyre_pressure": [999.0, 25.2, 25.0, 25.1],
                    "tyre_core_temp_c": [81.0, 82.0, 83.0, 84.0],
                    "tyre_wear": [98.1, 98.3, 98.5, 98.7],
                },
                "graphics": {"normalized_car_position": 0.18, "current_sector_index": 0, "completed_laps": 2},
                "static": {"car_model": "tatuusfa1", "track": "rt_autodrom_most"},
            },
        ]
        log = self._write_log("20260102T120700Z_track_pressure_suspension_filter.json", samples)

        result = analyze_shared_memory_track_map(path=str(log), bins=16)

        self.assertTrue(result["ok"])
        self.assertLess(result["session_overview"]["metrics"]["avg_suspension_travel"]["max"], 0.1)
        self.assertLess(result["session_overview"]["tyres"]["pressure"]["by_tyre"]["lf"]["max"], 30.0)
        self.assertLess(result["session_overview"]["tyres"]["trends"]["by_sector"][0]["pressure"]["by_tyre"]["lf"]["max"], 30.0)

    def test_analyze_corner_limits_loads_local_ac_profile(self) -> None:
        ac_content_root = self.root / "ac_content"
        track_dir = ac_content_root / "tracks" / "ks_autodrom_most"
        track_dir.mkdir(parents=True, exist_ok=True)
        (track_dir / "corner_profile.json").write_text(
            json.dumps(
                {
                    "corners": [
                        {"name": "T1", "start_pct": 5.0, "end_pct": 22.0},
                        {"name": "T2", "start_pct": 28.0, "end_pct": 45.0},
                    ]
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        os.environ["AC_CONTENT_ROOT"] = str(ac_content_root)

        samples = [
            {
                "physics": {
                    "speed_kmh": 95.0,
                    "brake": 0.82,
                    "gas": 0.2,
                    "steer_angle": 0.25,
                    "number_of_tyres_out": 2,
                },
                "graphics": {"normalized_car_position": 0.10, "current_sector_index": 0, "completed_laps": 4},
                "static": {"car_model": "tatuusfa1", "track": "rt_autodrom_most"},
            },
            {
                "physics": {
                    "speed_kmh": 105.0,
                    "brake": 0.31,
                    "gas": 0.6,
                    "steer_angle": 0.16,
                    "number_of_tyres_out": 0,
                },
                "graphics": {"normalized_car_position": 0.14, "current_sector_index": 0, "completed_laps": 4},
                "static": {"car_model": "tatuusfa1", "track": "rt_autodrom_most"},
            },
            {
                "physics": {
                    "speed_kmh": 88.0,
                    "brake": 0.64,
                    "gas": 0.18,
                    "steer_angle": 0.23,
                    "number_of_tyres_out": 3,
                },
                "graphics": {"normalized_car_position": 0.32, "current_sector_index": 1, "completed_laps": 4},
                "static": {"car_model": "tatuusfa1", "track": "rt_autodrom_most"},
            },
            {
                "physics": {
                    "speed_kmh": 97.0,
                    "brake": 0.25,
                    "gas": 0.72,
                    "steer_angle": 0.18,
                    "number_of_tyres_out": 1,
                },
                "graphics": {"normalized_car_position": 0.40, "current_sector_index": 1, "completed_laps": 4},
                "static": {"car_model": "tatuusfa1", "track": "rt_autodrom_most"},
            },
        ]
        log = self._write_log("20260103T000000Z_corner_limits_local.json", samples)

        result = analyze_shared_memory_corner_limits(path=str(log), bins=80)

        self.assertTrue(result["ok"])
        self.assertTrue(str(result["profile_source"]).startswith("ac_content:"))
        self.assertEqual(result["profile_corner_count"], 2)
        self.assertGreaterEqual(len(result["high_risk_corners"]), 1)
        self.assertGreater(float(result["summary"]["over_limit_samples"]), 0)

    def test_analyze_corner_limits_derives_profile_from_telemetry(self) -> None:
        os.environ.pop("AC_CONTENT_ROOT", None)

        samples: list[dict] = []
        for position in (0.01, 0.06, 0.11, 0.16, 0.35, 0.50, 0.85, 0.92):
            samples.append(
                {
                    "physics": {
                        "speed_kmh": 190.0,
                        "brake": 0.02,
                        "gas": 0.95,
                        "steer_angle": 0.02,
                        "number_of_tyres_out": 0,
                    },
                    "graphics": {"normalized_car_position": position, "current_sector_index": 0, "completed_laps": 1},
                    "static": {"car_model": "tatuusfa1", "track": "my_custom_track"},
                }
            )
        for position in (0.20, 0.22, 0.24, 0.26, 0.68, 0.70, 0.72, 0.74):
            samples.append(
                {
                    "physics": {
                        "speed_kmh": 84.0,
                        "brake": 0.78,
                        "gas": 0.22,
                        "steer_angle": 0.26,
                        "number_of_tyres_out": 1,
                    },
                    "graphics": {"normalized_car_position": position, "current_sector_index": 1, "completed_laps": 1},
                    "static": {"car_model": "tatuusfa1", "track": "my_custom_track"},
                }
            )

        log = self._write_log("20260104T000000Z_corner_limits_derived.json", samples)
        result = analyze_shared_memory_corner_limits(path=str(log), bins=120)

        self.assertTrue(result["ok"])
        self.assertEqual(result["profile_source"], "derived_from_telemetry")
        self.assertGreaterEqual(result["profile_corner_count"], 1)
        self.assertGreaterEqual(len(result["corners"]), 1)

    def test_analyze_corner_limits_uses_full_session_tyre_data(self) -> None:
        samples = [
            {
                "timestamp_utc": "2026-01-01T00:00:00Z",
                "physics": {
                    "speed_kmh": 150.0,
                    "brake": 0.12,
                    "gas": 0.8,
                    "steer_angle": 0.08,
                    "number_of_tyres_out": 0,
                    "tyre_core_temp_c": [78.0, 79.0, 80.0, 81.0],
                    "tyre_pressure": [25.8, 25.9, 25.7, 25.8],
                    "tyre_wear": [0.98, 0.98, 0.99, 0.99],
                },
                "graphics": {"normalized_car_position": 0.14, "current_sector_index": 0, "completed_laps": 1},
                "static": {"car_model": "tatuusfa1", "track": "rt_autodrom_most"},
            },
            {
                "timestamp_utc": "2026-01-01T00:00:01Z",
                "physics": {
                    "speed_kmh": 92.0,
                    "brake": 0.72,
                    "gas": 0.25,
                    "steer_angle": 0.22,
                    "number_of_tyres_out": 2,
                    "tyre_core_temp_c": [88.0, 89.0, 90.0, 91.0],
                    "tyre_pressure": [26.2, 26.3, 26.1, 26.2],
                    "tyre_wear": [0.96, 0.96, 0.97, 0.97],
                },
                "graphics": {"normalized_car_position": 0.15, "current_sector_index": 0, "completed_laps": 1},
                "static": {"car_model": "tatuusfa1", "track": "rt_autodrom_most"},
            },
            {
                "timestamp_utc": "2026-01-01T00:00:02Z",
                "physics": {
                    "speed_kmh": 98.0,
                    "brake": 0.68,
                    "gas": 0.3,
                    "steer_angle": 0.24,
                    "number_of_tyres_out": 3,
                    "tyre_core_temp_c": [92.0, 93.0, 94.0, 95.0],
                    "tyre_pressure": [26.5, 26.6, 26.4, 26.5],
                    "tyre_wear": [0.95, 0.95, 0.96, 0.96],
                },
                "graphics": {"normalized_car_position": 0.16, "current_sector_index": 0, "completed_laps": 1},
                "static": {"car_model": "tatuusfa1", "track": "rt_autodrom_most"},
            },
        ]

        log = self._write_log("20260104T120000Z_corner_session_overview.json", samples)
        result = analyze_shared_memory_corner_limits(path=str(log), bins=120)

        self.assertTrue(result["ok"])
        overview = result["session_overview"]
        self.assertEqual(overview["sample_count"], 3)
        self.assertEqual(overview["metrics"]["avg_tyre_temp_c"]["max"], 93.5)
        self.assertEqual(overview["tyres"]["temperature_c"]["by_tyre"]["lf"]["start"], 78.0)
        self.assertEqual(overview["tyres"]["temperature_c"]["by_tyre"]["lf"]["end"], 92.0)
        self.assertEqual(overview["tyres"]["temperature_c"]["by_tyre"]["lf"]["delta"], 14.0)
        self.assertEqual(overview["tyres"]["pressure"]["by_tyre"]["rf"]["max"], 26.6)
        self.assertEqual(len(overview["tyres"]["trends"]["by_sector"]), 1)
        self.assertEqual(len(overview["tyres"]["trends"]["by_lap"]), 1)
        self.assertEqual(overview["tyres"]["trends"]["by_sector"][0]["temperature_c"]["by_tyre"]["rr"]["max"], 95.0)

    def test_coach_corner_limits_prioritizes_actions(self) -> None:
        ac_content_root = self.root / "ac_content"
        track_dir = ac_content_root / "tracks" / "ks_autodrom_most"
        track_dir.mkdir(parents=True, exist_ok=True)
        (track_dir / "corner_profile.json").write_text(
            json.dumps(
                {
                    "corners": [
                        {"name": "T1", "start_pct": 5.0, "end_pct": 22.0},
                        {"name": "T2", "start_pct": 28.0, "end_pct": 45.0},
                    ]
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        os.environ["AC_CONTENT_ROOT"] = str(ac_content_root)

        samples = [
            {
                "physics": {
                    "speed_kmh": 102.0,
                    "brake": 0.42,
                    "gas": 0.58,
                    "steer_angle": 0.14,
                    "number_of_tyres_out": 1,
                },
                "graphics": {"normalized_car_position": 0.12, "current_sector_index": 0, "completed_laps": 3},
                "static": {"car_model": "tatuusfa1", "track": "rt_autodrom_most"},
            },
            {
                "physics": {
                    "speed_kmh": 90.0,
                    "brake": 0.70,
                    "gas": 0.74,
                    "steer_angle": 0.25,
                    "number_of_tyres_out": 3,
                },
                "graphics": {"normalized_car_position": 0.33, "current_sector_index": 1, "completed_laps": 3},
                "static": {"car_model": "tatuusfa1", "track": "rt_autodrom_most"},
            },
            {
                "physics": {
                    "speed_kmh": 94.0,
                    "brake": 0.62,
                    "gas": 0.78,
                    "steer_angle": 0.24,
                    "number_of_tyres_out": 2,
                },
                "graphics": {"normalized_car_position": 0.37, "current_sector_index": 1, "completed_laps": 3},
                "static": {"car_model": "tatuusfa1", "track": "rt_autodrom_most"},
            },
        ]
        log = self._write_log("20260105T000000Z_corner_coach.json", samples)

        result = coach_shared_memory_corner_limits(path=str(log), bins=90, top_n=1)

        self.assertTrue(result["ok"])
        self.assertEqual(result["top_n"], 1)
        self.assertEqual(len(result["priorities"]), 1)
        self.assertEqual(result["priorities"][0]["corner"], "T2")
        self.assertIn("session_overview", result)
        self.assertIn("entry_action", result["priorities"][0])
        self.assertIn("apex_action", result["priorities"][0])
        self.assertIn("exit_action", result["priorities"][0])

    def test_coach_corner_limits_clamps_top_n(self) -> None:
        ac_content_root = self.root / "ac_content"
        track_dir = ac_content_root / "tracks" / "ks_autodrom_most"
        track_dir.mkdir(parents=True, exist_ok=True)
        (track_dir / "corner_profile.json").write_text(
            json.dumps({"corners": [{"name": "T1", "start_pct": 5.0, "end_pct": 22.0}]}, indent=2),
            encoding="utf-8",
        )
        os.environ["AC_CONTENT_ROOT"] = str(ac_content_root)

        samples = [
            {
                "physics": {
                    "speed_kmh": 100.0,
                    "brake": 0.3,
                    "gas": 0.5,
                    "steer_angle": 0.1,
                    "number_of_tyres_out": 0,
                },
                "graphics": {"normalized_car_position": 0.12, "current_sector_index": 0, "completed_laps": 2},
                "static": {"car_model": "tatuusfa1", "track": "rt_autodrom_most"},
            }
        ]
        log = self._write_log("20260106T000000Z_corner_coach_min_topn.json", samples)

        result = coach_shared_memory_corner_limits(path=str(log), bins=90, top_n=0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["top_n"], 1)
        self.assertGreaterEqual(len(result["priorities"]), 1)

    def test_vallelunga_uses_known_profile_without_manual_file(self) -> None:
        os.environ.pop("AC_CONTENT_ROOT", None)

        samples = [
            {
                "physics": {
                    "speed_kmh": 146.0,
                    "brake": 0.32,
                    "gas": 0.58,
                    "steer_angle": 0.12,
                    "number_of_tyres_out": 1,
                },
                "graphics": {"normalized_car_position": 0.06, "current_sector_index": 0, "completed_laps": 2},
                "static": {"car_model": "tatuusfa1", "track": "ks_vallelunga"},
            },
            {
                "physics": {
                    "speed_kmh": 78.0,
                    "brake": 0.74,
                    "gas": 0.20,
                    "steer_angle": 0.26,
                    "number_of_tyres_out": 2,
                },
                "graphics": {"normalized_car_position": 0.58, "current_sector_index": 1, "completed_laps": 2},
                "static": {"car_model": "tatuusfa1", "track": "ks_vallelunga"},
            },
        ]
        log = self._write_log("20260107T000000Z_vallelunga_known_profile.json", samples)

        result = analyze_shared_memory_corner_limits(path=str(log), bins=100)

        self.assertTrue(result["ok"])
        self.assertEqual(result["profile_source"], "known_profile")
        self.assertEqual(result["track"], "ks_vallelunga")
        names = {str(corner.get("name", "")) for corner in result["corners"]}
        self.assertIn("Cimini 1", names)
        self.assertIn("Tornantino", names)

    def test_compare_shared_memory_stints_sector_and_corner_deltas(self) -> None:
        os.environ.pop("AC_CONTENT_ROOT", None)

        base_samples = [
            {
                "physics": {
                    "speed_kmh": 92.0,
                    "brake": 0.72,
                    "gas": 0.35,
                    "steer_angle": 0.24,
                    "number_of_tyres_out": 2,
                    "wheel_slip": [0.13, 0.12, 0.10, 0.11],
                },
                "graphics": {
                    "normalized_car_position": 0.08,
                    "current_sector_index": 0,
                    "last_sector_time": 38000,
                    "i_best_time": 130000,
                    "i_last_time": 132000,
                    "completed_laps": 4,
                },
                "static": {"car_model": "tatuusfa1", "track": "rt_autodrom_most"},
            },
            {
                "physics": {
                    "speed_kmh": 82.0,
                    "brake": 0.78,
                    "gas": 0.28,
                    "steer_angle": 0.28,
                    "number_of_tyres_out": 3,
                    "wheel_slip": [0.15, 0.13, 0.12, 0.13],
                },
                "graphics": {
                    "normalized_car_position": 0.32,
                    "current_sector_index": 1,
                    "last_sector_time": 42000,
                    "i_best_time": 130000,
                    "i_last_time": 132000,
                    "completed_laps": 4,
                },
                "static": {"car_model": "tatuusfa1", "track": "rt_autodrom_most"},
            },
            {
                "physics": {
                    "speed_kmh": 101.0,
                    "brake": 0.24,
                    "gas": 0.52,
                    "steer_angle": 0.15,
                    "number_of_tyres_out": 1,
                    "wheel_slip": [0.10, 0.09, 0.08, 0.09],
                },
                "graphics": {
                    "normalized_car_position": 0.75,
                    "current_sector_index": 2,
                    "last_sector_time": 50000,
                    "i_best_time": 130000,
                    "i_last_time": 132000,
                    "completed_laps": 4,
                },
                "static": {"car_model": "tatuusfa1", "track": "rt_autodrom_most"},
            },
        ]

        candidate_samples = [
            {
                "physics": {
                    "speed_kmh": 94.0,
                    "brake": 0.70,
                    "gas": 0.38,
                    "steer_angle": 0.23,
                    "number_of_tyres_out": 1,
                    "wheel_slip": [0.11, 0.10, 0.09, 0.10],
                },
                "graphics": {
                    "normalized_car_position": 0.08,
                    "current_sector_index": 0,
                    "last_sector_time": 37800,
                    "i_best_time": 125000,
                    "i_last_time": 127000,
                    "completed_laps": 4,
                },
                "static": {"car_model": "tatuusfa1", "track": "rt_autodrom_most"},
            },
            {
                "physics": {
                    "speed_kmh": 90.0,
                    "brake": 0.66,
                    "gas": 0.40,
                    "steer_angle": 0.22,
                    "number_of_tyres_out": 1,
                    "wheel_slip": [0.10, 0.09, 0.08, 0.09],
                },
                "graphics": {
                    "normalized_car_position": 0.32,
                    "current_sector_index": 1,
                    "last_sector_time": 40500,
                    "i_best_time": 125000,
                    "i_last_time": 127000,
                    "completed_laps": 4,
                },
                "static": {"car_model": "tatuusfa1", "track": "rt_autodrom_most"},
            },
            {
                "physics": {
                    "speed_kmh": 103.0,
                    "brake": 0.22,
                    "gas": 0.56,
                    "steer_angle": 0.14,
                    "number_of_tyres_out": 1,
                    "wheel_slip": [0.09, 0.08, 0.07, 0.08],
                },
                "graphics": {
                    "normalized_car_position": 0.75,
                    "current_sector_index": 2,
                    "last_sector_time": 49900,
                    "i_best_time": 125000,
                    "i_last_time": 127000,
                    "completed_laps": 4,
                },
                "static": {"car_model": "tatuusfa1", "track": "rt_autodrom_most"},
            },
        ]

        base_log = self._write_log("20260108T000000Z_base_compare.json", base_samples)
        candidate_log = self._write_log("20260108T000500Z_candidate_compare.json", candidate_samples)

        result = compare_shared_memory_stints(
            base_path=str(base_log),
            candidate_path=str(candidate_log),
            bins=120,
            objective="sector_2",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["track"], "rt_autodrom_most")
        self.assertEqual(result["objective"]["objective"], "sector_2")
        self.assertEqual(result["objective"]["winner"], "candidate")
        self.assertIn("base_session_overview", result)
        self.assertIn("candidate_session_overview", result)

        sector_2 = next((item for item in result["sector_deltas"] if int(item["sector_number"]) == 2), None)
        self.assertIsNotNone(sector_2)
        assert sector_2 is not None
        self.assertLess(int(sector_2["delta_time_ms"]), 0)

        self.assertGreater(len(result["corner_deltas"]), 0)
        self.assertTrue(any(float(item["delta_over_limit_pct"]) < 0 for item in result["corner_deltas"]))
        self.assertEqual(result["candidate_session_overview"]["metrics"]["speed_kmh"]["max"], 103.0)


if __name__ == "__main__":
    unittest.main()
