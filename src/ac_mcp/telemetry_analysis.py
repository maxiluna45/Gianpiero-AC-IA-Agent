from __future__ import annotations

import configparser
import json
import math
import os
from pathlib import Path
from typing import Any

from ac_mcp.config import session_log_root


_KNOWN_TRACK_LENGTH_M: dict[str, float] = {
    "rt_autodrom_most": 4212.0,
    "autodrom_most": 4212.0,
    "ks_autodrom_most": 4212.0,
    "ks_brands_hatch": 3908.0,
    "brands_hatch": 3908.0,
    "ks_vallelunga": 4085.0,
    "rt_vallelunga": 4085.0,
    "vallelunga": 4085.0,
    "ks_spa": 7004.0,
    "spa": 7004.0,
}

_KNOWN_CORNER_PROFILES: dict[str, list[dict[str, float | str]]] = {
    "rt_autodrom_most": [
        {"name": "T1", "start_pct": 4.0, "end_pct": 10.5},
        {"name": "T2", "start_pct": 13.0, "end_pct": 18.0},
        {"name": "T3", "start_pct": 21.5, "end_pct": 26.5},
        {"name": "T4", "start_pct": 31.0, "end_pct": 36.0},
        {"name": "T5", "start_pct": 40.0, "end_pct": 44.0},
        {"name": "T6", "start_pct": 49.0, "end_pct": 54.0},
        {"name": "T7", "start_pct": 58.0, "end_pct": 63.0},
        {"name": "T8", "start_pct": 67.5, "end_pct": 72.5},
        {"name": "T9", "start_pct": 77.5, "end_pct": 83.0},
        {"name": "T10", "start_pct": 87.5, "end_pct": 93.5},
    ],
    "ks_brands_hatch": [
        {"name": "Paddock Hill", "start_pct": 2.0, "end_pct": 10.0},
        {"name": "Druids", "start_pct": 12.0, "end_pct": 20.0},
        {"name": "Graham Hill", "start_pct": 24.0, "end_pct": 32.0},
        {"name": "Surtees", "start_pct": 42.0, "end_pct": 50.0},
        {"name": "Hawthorns", "start_pct": 56.0, "end_pct": 64.0},
        {"name": "Westfield", "start_pct": 66.0, "end_pct": 72.0},
        {"name": "Sheene", "start_pct": 73.0, "end_pct": 78.0},
        {"name": "Stirling", "start_pct": 79.0, "end_pct": 85.0},
        {"name": "Clearways", "start_pct": 88.0, "end_pct": 98.5},
    ],
    "ks_vallelunga": [
        {"name": "Cimini 1", "start_pct": 4.0, "end_pct": 9.0},
        {"name": "Cimini 2", "start_pct": 9.0, "end_pct": 14.0},
        {"name": "Campagnano", "start_pct": 18.0, "end_pct": 24.0},
        {"name": "Soratte", "start_pct": 29.0, "end_pct": 33.0},
        {"name": "Trincea", "start_pct": 38.0, "end_pct": 42.0},
        {"name": "Semaforo", "start_pct": 46.0, "end_pct": 51.0},
        {"name": "Tornantino", "start_pct": 56.0, "end_pct": 63.0},
        {"name": "Curvone", "start_pct": 69.0, "end_pct": 76.0},
        {"name": "Esse", "start_pct": 77.5, "end_pct": 84.0},
        {"name": "Roma", "start_pct": 90.0, "end_pct": 97.0},
    ],
}

_MAX_REASONABLE_WHEEL_SLIP = 10.0
_MIN_REASONABLE_TYRE_PRESSURE = 5.0
_MAX_REASONABLE_TYRE_PRESSURE = 60.0
_MIN_REASONABLE_TYRE_TEMP_C = -20.0
_MAX_REASONABLE_TYRE_TEMP_C = 200.0
_MIN_REASONABLE_TYRE_WEAR = 0.0
_MAX_REASONABLE_TYRE_WEAR = 100.0
_MIN_REASONABLE_SUSPENSION_TRAVEL = 0.0
_MAX_REASONABLE_SUSPENSION_TRAVEL = 0.5


def _shared_memory_root() -> Path:
    return session_log_root() / "shared_memory"


def _normalize_track_key(track: str) -> str:
    return str(track or "").strip().lower().replace(" ", "_")


def _track_key_candidates(track: str) -> list[str]:
    key = _normalize_track_key(track)
    if not key:
        return []

    candidates = [key]
    if key.startswith("rt_"):
        suffix = key[3:]
        candidates.extend([suffix, f"ks_{suffix}"])
    elif key.startswith("ks_"):
        suffix = key[3:]
        candidates.extend([suffix, f"rt_{suffix}"])
    else:
        candidates.extend([f"ks_{key}", f"rt_{key}"])

    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate and candidate not in seen:
            unique.append(candidate)
            seen.add(candidate)
    return unique


def _resolve_log_path(path: str) -> Path:
    root = _shared_memory_root()

    if path.strip():
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = root / candidate
        resolved = candidate.resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"Shared-memory log not found: {resolved}")
        return resolved

    files = sorted(root.glob("*.json"), reverse=True)
    if not files:
        raise FileNotFoundError("No shared-memory logs found")
    return files[0]


def _load_shared_memory_payload(path: str) -> tuple[Path, dict[str, Any], list[dict[str, Any]]]:
    resolved = _resolve_log_path(path)
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    samples_raw = payload.get("samples", [])
    if not isinstance(samples_raw, list):
        raise ValueError("No samples in shared-memory log")

    samples: list[dict[str, Any]] = [sample for sample in samples_raw if isinstance(sample, dict)]
    if not samples:
        raise ValueError("No samples in shared-memory log")

    return resolved, payload, samples


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _safe_sequence_avg(value: Any) -> float:
    if isinstance(value, (list, tuple)):
        if not value:
            return 0.0
        numbers = [_safe_float(item) for item in value]
        return sum(numbers) / max(1, len(numbers))
    return _safe_float(value)


def _safe_sequence_max(value: Any) -> float:
    if isinstance(value, (list, tuple)):
        if not value:
            return 0.0
        return max(_safe_float(item) for item in value)
    return _safe_float(value)


def _filtered_sequence_values(value: Any, max_abs: float | None = None) -> list[float]:
    if isinstance(value, (list, tuple)):
        raw_values = [_safe_float(item) for item in value]
    else:
        raw_values = [_safe_float(value)]

    filtered: list[float] = []
    for item in raw_values:
        if not math.isfinite(item):
            continue
        if max_abs is not None and abs(item) > max_abs:
            continue
        filtered.append(item)
    return filtered


def _safe_wheel_slip_avg(value: Any) -> float:
    filtered = _filtered_sequence_values(value, max_abs=_MAX_REASONABLE_WHEEL_SLIP)
    if not filtered:
        return 0.0
    return sum(filtered) / len(filtered)


def _safe_wheel_slip_max(value: Any) -> float:
    filtered = _filtered_sequence_values(value, max_abs=_MAX_REASONABLE_WHEEL_SLIP)
    if not filtered:
        return 0.0
    return max(filtered)


def _safe_bounded_sequence_avg(value: Any, minimum: float, maximum: float) -> float:
    filtered = _filtered_sequence_values(value)
    bounded = [item for item in filtered if minimum <= item <= maximum]
    if not bounded:
        return 0.0
    return sum(bounded) / len(bounded)


def _safe_bounded_sequence_max(value: Any, minimum: float, maximum: float) -> float:
    filtered = _filtered_sequence_values(value)
    bounded = [item for item in filtered if minimum <= item <= maximum]
    if not bounded:
        return 0.0
    return max(bounded)


def _series_summary(values: list[float], digits: int = 3) -> dict[str, Any]:
    if not values:
        return {
            "samples": 0,
            "min": None,
            "max": None,
            "avg": None,
            "start": None,
            "end": None,
            "delta": None,
        }

    start = float(values[0])
    end = float(values[-1])
    avg = sum(values) / len(values)
    return {
        "samples": len(values),
        "min": round(min(values), digits),
        "max": round(max(values), digits),
        "avg": round(avg, digits),
        "start": round(start, digits),
        "end": round(end, digits),
        "delta": round(end - start, digits),
    }


def _extract_wheel_values(
    physics: dict[str, Any],
    keys: list[str],
    minimum: float | None = None,
    maximum: float | None = None,
) -> list[float]:
    for key in keys:
        raw = physics.get(key)
        if isinstance(raw, (list, tuple)):
            values = _filtered_sequence_values(raw)
            if minimum is not None:
                values = [item for item in values if item >= minimum]
            if maximum is not None:
                values = [item for item in values if item <= maximum]
            if values:
                return values
    return []


def _append_tyre_group_entry(target: dict[str, Any], sample: dict[str, Any]) -> None:
    physics = sample.get("physics", {}) if isinstance(sample, dict) else {}
    if not isinstance(physics, dict):
        physics = {}

    temps = _extract_wheel_values(
        physics,
        ["tyre_core_temp_c"],
        minimum=_MIN_REASONABLE_TYRE_TEMP_C,
        maximum=_MAX_REASONABLE_TYRE_TEMP_C,
    )
    pressures = _extract_wheel_values(
        physics,
        ["tyre_pressure", "wheel_pressure"],
        minimum=_MIN_REASONABLE_TYRE_PRESSURE,
        maximum=_MAX_REASONABLE_TYRE_PRESSURE,
    )
    wear = _extract_wheel_values(
        physics,
        ["tyre_wear"],
        minimum=_MIN_REASONABLE_TYRE_WEAR,
        maximum=_MAX_REASONABLE_TYRE_WEAR,
    )
    tyre_labels = ("lf", "rf", "lr", "rr")

    target["sample_count"] = int(target.get("sample_count", 0)) + 1
    for index, label in enumerate(tyre_labels):
        if index < len(temps):
            target["temperature_c"][label].append(temps[index])
        if index < len(pressures):
            target["pressure"][label].append(pressures[index])
        if index < len(wear):
            target["wear"][label].append(wear[index])


def _compact_tyre_trends(samples: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    tyre_labels = ("lf", "rf", "lr", "rr")
    by_sector_raw: dict[int, dict[str, Any]] = {}
    by_lap_raw: dict[int, dict[str, Any]] = {}

    for sample in samples:
        if not isinstance(sample, dict):
            continue

        graphics = sample.get("graphics", {})
        if not isinstance(graphics, dict):
            graphics = {}

        sector_index = _safe_int(graphics.get("current_sector_index", -1))
        if sector_index >= 0:
            sector_bucket = by_sector_raw.setdefault(
                sector_index,
                {
                    "group_key": sector_index,
                    "sample_count": 0,
                    "temperature_c": {label: [] for label in tyre_labels},
                    "pressure": {label: [] for label in tyre_labels},
                    "wear": {label: [] for label in tyre_labels},
                },
            )
            _append_tyre_group_entry(sector_bucket, sample)

        lap_number = _safe_int(graphics.get("completed_laps", -1))
        if lap_number >= 0:
            lap_bucket = by_lap_raw.setdefault(
                lap_number,
                {
                    "group_key": lap_number,
                    "sample_count": 0,
                    "temperature_c": {label: [] for label in tyre_labels},
                    "pressure": {label: [] for label in tyre_labels},
                    "wear": {label: [] for label in tyre_labels},
                },
            )
            _append_tyre_group_entry(lap_bucket, sample)

    def _finalize_group(raw: dict[str, Any], *, label_key: str, label_value: int, number_key: str, number_value: int) -> dict[str, Any]:
        return {
            label_key: label_value,
            number_key: number_value,
            "sample_count": int(raw.get("sample_count", 0)),
            "temperature_c": {
                "avg_all_tyres": _series_summary(
                    [value for values in raw["temperature_c"].values() for value in values],
                    4,
                ),
                "by_tyre": {tyre: _series_summary(values, 4) for tyre, values in raw["temperature_c"].items()},
            },
            "pressure": {
                "by_tyre": {tyre: _series_summary(values, 3) for tyre, values in raw["pressure"].items()},
            },
            "wear": {
                "avg_all_tyres": _series_summary(
                    [value for values in raw["wear"].values() for value in values],
                    5,
                ),
                "by_tyre": {tyre: _series_summary(values, 5) for tyre, values in raw["wear"].items()},
            },
        }

    by_sector = [
        _finalize_group(raw, label_key="sector_index", label_value=sector_index, number_key="sector_number", number_value=sector_index + 1)
        for sector_index, raw in sorted(by_sector_raw.items())
    ]
    by_lap = [
        _finalize_group(raw, label_key="completed_laps", label_value=lap_number, number_key="lap_number", number_value=lap_number + 1)
        for lap_number, raw in sorted(by_lap_raw.items())
    ]

    return {
        "by_sector": by_sector,
        "by_lap": by_lap,
    }


def _build_session_overview(samples: list[dict[str, Any]]) -> dict[str, Any]:
    scalar_metrics: dict[str, tuple[int, list[float]]] = {
        "speed_kmh": (3, []),
        "rpms": (0, []),
        "gear": (0, []),
        "gas": (4, []),
        "brake": (4, []),
        "fuel": (3, []),
        "steer_angle_abs": (4, []),
        "tc": (4, []),
        "abs": (4, []),
        "avg_wheel_slip": (5, []),
        "max_wheel_slip": (5, []),
        "avg_suspension_travel": (6, []),
        "avg_tyre_temp_c": (4, []),
        "avg_tyre_wear": (5, []),
        "air_temp_c": (3, []),
        "road_temp_c": (3, []),
        "number_of_tyres_out": (0, []),
        "normalized_car_position": (6, []),
        "distance_traveled": (3, []),
        "completed_laps": (0, []),
        "current_sector_index": (0, []),
    }
    tyre_labels = ("lf", "rf", "lr", "rr")
    tyre_temp_series: dict[str, list[float]] = {label: [] for label in tyre_labels}
    tyre_pressure_series: dict[str, list[float]] = {label: [] for label in tyre_labels}
    tyre_wear_series: dict[str, list[float]] = {label: [] for label in tyre_labels}
    timestamps: list[str] = []
    tyre_trends = _compact_tyre_trends(samples)

    for sample in samples:
        if not isinstance(sample, dict):
            continue

        timestamp = str(sample.get("timestamp_utc", "") or "")
        if timestamp:
            timestamps.append(timestamp)

        physics = sample.get("physics", {})
        graphics = sample.get("graphics", {})
        if not isinstance(physics, dict):
            physics = {}
        if not isinstance(graphics, dict):
            graphics = {}

        metric_map = {
            "speed_kmh": _safe_float(physics.get("speed_kmh", 0.0)),
            "rpms": float(_safe_int(physics.get("rpms", 0))),
            "gear": float(_safe_int(physics.get("gear", 0))),
            "gas": _safe_float(physics.get("gas", 0.0)),
            "brake": _safe_float(physics.get("brake", 0.0)),
            "fuel": _safe_float(physics.get("fuel", 0.0)),
            "steer_angle_abs": abs(_safe_float(physics.get("steer_angle", 0.0))),
            "tc": _safe_float(physics.get("tc", 0.0)),
            "abs": _safe_float(physics.get("abs", 0.0)),
            "avg_wheel_slip": _safe_wheel_slip_avg(physics.get("wheel_slip", physics.get("avg_wheel_slip", 0.0))),
            "max_wheel_slip": _safe_wheel_slip_max(physics.get("wheel_slip", physics.get("max_wheel_slip", 0.0))),
            "avg_suspension_travel": _safe_bounded_sequence_avg(
                physics.get("suspension_travel", physics.get("avg_suspension_travel", 0.0)),
                minimum=_MIN_REASONABLE_SUSPENSION_TRAVEL,
                maximum=_MAX_REASONABLE_SUSPENSION_TRAVEL,
            ),
            "avg_tyre_temp_c": _safe_bounded_sequence_avg(
                physics.get("tyre_core_temp_c", physics.get("avg_tyre_temp_c", 0.0)),
                minimum=_MIN_REASONABLE_TYRE_TEMP_C,
                maximum=_MAX_REASONABLE_TYRE_TEMP_C,
            ),
            "avg_tyre_wear": _safe_bounded_sequence_avg(
                physics.get("tyre_wear", physics.get("avg_tyre_wear", 0.0)),
                minimum=_MIN_REASONABLE_TYRE_WEAR,
                maximum=_MAX_REASONABLE_TYRE_WEAR,
            ),
            "air_temp_c": _safe_float(physics.get("air_temp_c", 0.0)),
            "road_temp_c": _safe_float(physics.get("road_temp_c", 0.0)),
            "number_of_tyres_out": float(_safe_int(physics.get("number_of_tyres_out", 0))),
            "normalized_car_position": _safe_float(graphics.get("normalized_car_position", 0.0)),
            "distance_traveled": _safe_float(graphics.get("distance_traveled", 0.0)),
            "completed_laps": float(_safe_int(graphics.get("completed_laps", 0))),
            "current_sector_index": float(_safe_int(graphics.get("current_sector_index", 0))),
        }

        for name, value in metric_map.items():
            scalar_metrics[name][1].append(value)

        tyre_temp_values = _extract_wheel_values(
            physics,
            ["tyre_core_temp_c"],
            minimum=_MIN_REASONABLE_TYRE_TEMP_C,
            maximum=_MAX_REASONABLE_TYRE_TEMP_C,
        )
        tyre_pressure_values = _extract_wheel_values(
            physics,
            ["tyre_pressure", "wheel_pressure"],
            minimum=_MIN_REASONABLE_TYRE_PRESSURE,
            maximum=_MAX_REASONABLE_TYRE_PRESSURE,
        )
        tyre_wear_values = _extract_wheel_values(
            physics,
            ["tyre_wear"],
            minimum=_MIN_REASONABLE_TYRE_WEAR,
            maximum=_MAX_REASONABLE_TYRE_WEAR,
        )

        for index, label in enumerate(tyre_labels):
            if index < len(tyre_temp_values):
                tyre_temp_series[label].append(tyre_temp_values[index])
            if index < len(tyre_pressure_values):
                tyre_pressure_series[label].append(tyre_pressure_values[index])
            if index < len(tyre_wear_values):
                tyre_wear_series[label].append(tyre_wear_values[index])

    metrics = {
        name: _series_summary(values, digits)
        for name, (digits, values) in scalar_metrics.items()
    }

    return {
        "sample_count": len(samples),
        "timestamp_range": {
            "start_utc": timestamps[0] if timestamps else "",
            "end_utc": timestamps[-1] if timestamps else "",
        },
        "metrics": metrics,
        "tyres": {
            "temperature_c": {
                "avg_all_tyres": metrics["avg_tyre_temp_c"],
                "by_tyre": {label: _series_summary(values, 4) for label, values in tyre_temp_series.items()},
            },
            "pressure": {
                "by_tyre": {label: _series_summary(values, 3) for label, values in tyre_pressure_series.items()},
            },
            "wear": {
                "avg_all_tyres": metrics["avg_tyre_wear"],
                "by_tyre": {label: _series_summary(values, 5) for label, values in tyre_wear_series.items()},
            },
            "trends": tyre_trends,
        },
    }


def _load_corner_profile_rows(raw_rows: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_rows, list):
        return []

    profile: list[dict[str, Any]] = []
    for index, row in enumerate(raw_rows, start=1):
        if not isinstance(row, dict):
            continue

        name = str(row.get("name") or row.get("corner") or row.get("turn") or f"T{index}").strip()
        start_raw = row.get("start_pct", row.get("start", row.get("from_pct", row.get("from"))))
        end_raw = row.get("end_pct", row.get("end", row.get("to_pct", row.get("to"))))
        if start_raw is None or end_raw is None:
            continue

        try:
            start_pct = float(start_raw)
            end_pct = float(end_raw)
        except (TypeError, ValueError):
            continue

        if start_pct < 0.0:
            start_pct = 0.0
        if end_pct < 0.0:
            end_pct = 0.0
        if start_pct > 100.0:
            start_pct = 100.0
        if end_pct > 100.0:
            end_pct = 100.0
        if start_pct == end_pct:
            continue

        profile.append(
            {
                "name": name,
                "start_pct": round(start_pct, 3),
                "end_pct": round(end_pct, 3),
            }
        )

    profile.sort(key=lambda item: float(item["start_pct"]))
    return profile


def _load_corner_profile_json(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return _load_corner_profile_rows(data)
    if isinstance(data, dict):
        return _load_corner_profile_rows(data.get("corners") or data.get("profile") or data.get("turns") or [])
    return []


def _load_corner_profile_ini(path: Path) -> list[dict[str, Any]]:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(path, encoding="utf-8")

    rows: list[dict[str, Any]] = []
    for section in parser.sections():
        start_raw = parser.get(section, "start_pct", fallback=parser.get(section, "start", fallback=""))
        end_raw = parser.get(section, "end_pct", fallback=parser.get(section, "end", fallback=""))
        if not start_raw or not end_raw:
            continue

        rows.append(
            {
                "name": parser.get(section, "name", fallback=section),
                "start_pct": start_raw,
                "end_pct": end_raw,
            }
        )

    return _load_corner_profile_rows(rows)


def _ac_tracks_root() -> Path | None:
    configured = os.getenv("AC_CONTENT_ROOT", "").strip()
    candidates: list[Path] = []

    if configured:
        candidates.append(Path(configured))

    program_files_x86 = os.getenv("ProgramFiles(x86)", "C:/Program Files (x86)").strip()
    program_files = os.getenv("ProgramFiles", "C:/Program Files").strip()
    candidates.extend(
        [
            Path(program_files_x86) / "Steam" / "steamapps" / "common" / "assettocorsa" / "content",
            Path(program_files) / "Steam" / "steamapps" / "common" / "assettocorsa" / "content",
            Path.home() / "SteamLibrary" / "steamapps" / "common" / "assettocorsa" / "content",
        ]
    )

    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved.name.lower() == "tracks" and resolved.exists():
            return resolved

        direct_tracks = resolved / "tracks"
        if direct_tracks.exists():
            return direct_tracks

        nested_tracks = resolved / "content" / "tracks"
        if nested_tracks.exists():
            return nested_tracks

    return None


def _candidate_track_dirs(tracks_root: Path, track: str) -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()
    for key in _track_key_candidates(track):
        candidate = tracks_root / key
        if candidate.exists() and candidate.is_dir():
            text = str(candidate.resolve())
            if text not in seen:
                seen.add(text)
                found.append(candidate)
    return found


def _load_corner_profile_from_content(track: str) -> tuple[list[dict[str, Any]], str]:
    tracks_root = _ac_tracks_root()
    if tracks_root is None:
        return [], ""

    profile_relatives = [
        Path("corner_profile.json"),
        Path("corners.json"),
        Path("data") / "corner_profile.json",
        Path("data") / "corners.json",
        Path("corner_profile.ini"),
        Path("corners.ini"),
        Path("data") / "corner_profile.ini",
        Path("data") / "corners.ini",
    ]

    search_roots: list[Path] = []
    for track_dir in _candidate_track_dirs(tracks_root, track):
        search_roots.append(track_dir)
        try:
            for child in track_dir.iterdir():
                if child.is_dir():
                    search_roots.append(child)
        except OSError:
            continue

    for base in search_roots:
        for relative in profile_relatives:
            candidate = base / relative
            if not candidate.exists() or not candidate.is_file():
                continue

            try:
                if candidate.suffix.lower() == ".json":
                    profile = _load_corner_profile_json(candidate)
                else:
                    profile = _load_corner_profile_ini(candidate)
            except Exception:
                continue

            if profile:
                return profile, str(candidate.resolve())

    return [], ""


def _load_known_corner_profile(track: str) -> list[dict[str, Any]]:
    for key in _track_key_candidates(track):
        if key in _KNOWN_CORNER_PROFILES:
            return [dict(corner) for corner in _KNOWN_CORNER_PROFILES[key]]
    return []


def _derive_corner_profile_from_samples(samples: list[dict[str, Any]], bins: int = 120) -> list[dict[str, Any]]:
    bucket_count = max(30, min(int(bins), 300))
    intensity_sum: list[float] = [0.0 for _ in range(bucket_count)]
    bucket_samples: list[int] = [0 for _ in range(bucket_count)]
    sparse_points: list[tuple[float, float]] = []

    for sample in samples:
        graphics = sample.get("graphics", {})
        physics = sample.get("physics", {})
        position = graphics.get("normalized_car_position")
        if position is None:
            continue

        position_value = max(0.0, min(0.999999, _safe_float(position)))
        index = min(int(position_value * bucket_count), bucket_count - 1)

        brake = max(0.0, min(1.0, _safe_float(physics.get("brake", 0.0))))
        steer = abs(_safe_float(physics.get("steer_angle", 0.0)))
        steer_factor = min(1.4, steer / 0.3)
        speed = max(0.0, _safe_float(physics.get("speed_kmh", 0.0)))
        speed_factor = 1.0 - min(1.0, speed / 230.0)

        intensity = (0.55 * steer_factor) + (0.35 * brake) + (0.10 * speed_factor)
        intensity_sum[index] += intensity
        bucket_samples[index] += 1
        sparse_points.append((position_value * 100.0, intensity))

    values = [intensity_sum[i] / bucket_samples[i] for i in range(bucket_count) if bucket_samples[i] > 0]
    if len(values) < 10:
        return []

    values_sorted = sorted(values)
    threshold = max(0.34, values_sorted[int((len(values_sorted) - 1) * 0.68)])
    active = [bucket_samples[i] > 0 and (intensity_sum[i] / bucket_samples[i]) >= threshold for i in range(bucket_count)]
    if sum(1 for item in active if item) < 8:
        threshold = max(0.26, values_sorted[int((len(values_sorted) - 1) * 0.55)])
        active = [bucket_samples[i] > 0 and (intensity_sum[i] / bucket_samples[i]) >= threshold for i in range(bucket_count)]

    groups: list[tuple[int, int]] = []
    start: int | None = None
    for index, is_active in enumerate(active):
        if is_active and start is None:
            start = index
            continue
        if not is_active and start is not None:
            groups.append((start, index - 1))
            start = None

    if start is not None:
        groups.append((start, bucket_count - 1))

    if len(groups) >= 2 and active[0] and active[-1]:
        first_start, first_end = groups[0]
        last_start, _last_end = groups[-1]
        merged = (last_start, first_end)
        groups = [merged] + groups[1:-1]

    profile: list[dict[str, Any]] = []
    index = 1
    for start_idx, end_idx in groups:
        if start_idx <= end_idx:
            width = (end_idx - start_idx) + 1
        else:
            width = (bucket_count - start_idx) + (end_idx + 1)

        if width < 2:
            continue

        start_pct = (start_idx / bucket_count) * 100.0
        end_pct = (((end_idx + 1) % bucket_count) / bucket_count) * 100.0
        profile.append(
            {
                "name": f"T{index}",
                "start_pct": round(start_pct, 3),
                "end_pct": round(end_pct, 3),
            }
        )
        index += 1

    if profile:
        return profile

    if len(sparse_points) < 8:
        return []

    sparse_values = sorted(value for _position, value in sparse_points)
    sparse_threshold = max(0.30, sparse_values[int((len(sparse_values) - 1) * 0.60)])
    hot_points = sorted([point for point in sparse_points if point[1] >= sparse_threshold], key=lambda item: item[0])
    if len(hot_points) < 4:
        return []

    groups: list[list[tuple[float, float]]] = []
    current_group: list[tuple[float, float]] = [hot_points[0]]
    for point in hot_points[1:]:
        if (point[0] - current_group[-1][0]) <= 6.0:
            current_group.append(point)
        else:
            groups.append(current_group)
            current_group = [point]
    groups.append(current_group)

    if len(groups) >= 2:
        first_min = min(point[0] for point in groups[0])
        last_max = max(point[0] for point in groups[-1])
        if first_min <= 5.0 and last_max >= 95.0:
            merged = groups[-1] + groups[0]
            groups = [merged] + groups[1:-1]

    fallback_profile: list[dict[str, Any]] = []
    turn_index = 1
    for group in groups:
        if len(group) < 2:
            continue

        start_raw = min(point[0] for point in group) - 1.5
        end_raw = max(point[0] for point in group) + 1.5
        start_pct = max(0.0, start_raw)
        end_pct = min(100.0, end_raw)
        if end_pct <= start_pct:
            continue

        fallback_profile.append(
            {
                "name": f"T{turn_index}",
                "start_pct": round(start_pct, 3),
                "end_pct": round(end_pct, 3),
            }
        )
        turn_index += 1

    return fallback_profile


def _resolve_corner_profile(track: str, samples: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    local_profile, local_source = _load_corner_profile_from_content(track)
    if local_profile:
        return local_profile, f"ac_content:{local_source}"

    known_profile = _load_known_corner_profile(track)
    if known_profile:
        return known_profile, "known_profile"

    derived_profile = _derive_corner_profile_from_samples(samples)
    if derived_profile:
        return derived_profile, "derived_from_telemetry"

    return [], ""


def _find_corner_for_position(position_pct: float, profile: list[dict[str, Any]]) -> dict[str, Any] | None:
    for corner in profile:
        start = _safe_float(corner.get("start_pct", 0.0))
        end = _safe_float(corner.get("end_pct", 0.0))
        if start <= end:
            if start <= position_pct < end:
                return corner
        else:
            if position_pct >= start or position_pct < end:
                return corner
    return None


def _build_corner_advice(
    over_limit_pct: float,
    severe_over_limit_pct: float,
    under_limit_pct: float,
    avg_abs_steer: float,
    avg_speed_kmh: float,
    avg_gas: float,
    avg_wheel_slip: float,
    avg_suspension_travel: float,
    avg_tc_setting: float,
    avg_abs_setting: float,
) -> str:
    notes: list[str] = []

    if over_limit_pct >= 18.0:
        notes.append("Exceso alto de limites: recorta menos la salida y retrasa un poco el gas.")
    elif over_limit_pct >= 8.0:
        notes.append("Exceso moderado de limites: suaviza apertura de volante al acelerar.")

    if severe_over_limit_pct >= 4.0:
        notes.append("Hay eventos severos: riesgo de penalizacion y desgaste lateral elevado.")

    if under_limit_pct >= 85.0 and avg_abs_steer >= 0.12 and avg_speed_kmh <= 150.0:
        notes.append("Parece que dejas pista util sin usar: abre mas entrada y salida progresiva.")

    if avg_gas >= 0.7 and over_limit_pct >= 10.0:
        notes.append("Traccion comprometida en salida: aplica gas mas progresivo para cuidar neumatico.")

    if avg_wheel_slip >= 0.12:
        notes.append("Slip alto en la curva: prioriza una salida menos agresiva y lineas mas limpias.")

    if avg_suspension_travel >= 0.085:
        notes.append("Movimiento vertical elevado: evita pianos agresivos y estabiliza transferencia de carga.")

    if avg_tc_setting >= 4.5 and avg_wheel_slip >= 0.1:
        notes.append("Aun con mucho TC hay patinaje: revisar balance mecanico/diferencial para mejorar traccion real.")

    if avg_abs_setting >= 4.5 and severe_over_limit_pct >= 3.0:
        notes.append("ABS alto con salidas de pista: puede haber entrada pasada, ajusta referencia de frenada.")

    if not notes:
        notes.append("Uso de limites estable en esta curva.")
    return " ".join(notes)


def _corner_impact_score(corner: dict[str, Any]) -> float:
    over = _safe_float(corner.get("over_limit_pct", 0.0))
    severe = _safe_float(corner.get("severe_over_limit_pct", 0.0))
    under = _safe_float(corner.get("under_limit_pct", 0.0))
    coverage = _safe_float(corner.get("coverage_pct", 0.0))
    steer = _safe_float(corner.get("avg_abs_steer", 0.0))
    gas = _safe_float(corner.get("avg_gas", 0.0))
    slip = _safe_float(corner.get("avg_wheel_slip", 0.0))
    suspension = _safe_float(corner.get("avg_suspension_travel", 0.0))

    under_penalty = max(0.0, under - 82.0)
    traccion_risk = gas * over
    return round(
        (over * 1.55)
        + (severe * 2.25)
        + (under_penalty * 0.55)
        + (coverage * 0.25)
        + (steer * 12.0)
        + (traccion_risk * 0.15)
        + (slip * 45.0)
        + (suspension * 80.0),
        3,
    )


def _wear_risk_level(corner: dict[str, Any]) -> str:
    over = _safe_float(corner.get("over_limit_pct", 0.0))
    severe = _safe_float(corner.get("severe_over_limit_pct", 0.0))
    gas = _safe_float(corner.get("avg_gas", 0.0))
    steer = _safe_float(corner.get("avg_abs_steer", 0.0))
    slip = _safe_float(corner.get("avg_wheel_slip", 0.0))
    tyre_temp = _safe_float(corner.get("avg_tyre_temp_c", 0.0))

    wear_load = (over * 0.8) + (severe * 2.2) + (gas * 18.0) + (steer * 28.0) + (slip * 30.0)
    if tyre_temp >= 95.0:
        wear_load += (tyre_temp - 95.0) * 0.3
    if wear_load >= 42.0:
        return "high"
    if wear_load >= 24.0:
        return "medium"
    return "low"


def _build_corner_phase_actions(corner: dict[str, Any]) -> dict[str, str]:
    over = _safe_float(corner.get("over_limit_pct", 0.0))
    severe = _safe_float(corner.get("severe_over_limit_pct", 0.0))
    under = _safe_float(corner.get("under_limit_pct", 0.0))
    brake = _safe_float(corner.get("avg_brake", 0.0))
    gas = _safe_float(corner.get("avg_gas", 0.0))
    slip = _safe_float(corner.get("avg_wheel_slip", 0.0))
    suspension = _safe_float(corner.get("avg_suspension_travel", 0.0))

    entry = "Mantener punto de frenada actual y repetir referencia visual."
    apex = "Buscar apice limpio y estable sin sobrecorregir volante."
    exit_action = "Abrir direccion antes de aplicar gas alto."
    objective = "Consolidar consistencia y ritmo sin forzar limites."

    if severe >= 4.0 or over >= 16.0:
        objective = "Reducir exceso de limites y bajar riesgo de penalizacion/desgaste."
        if brake < 0.35:
            entry = "Frenar 5-10 m antes y soltar freno progresivo para no llegar pasado."
        else:
            entry = "Mantener freno inicial pero liberar antes para colocar mejor el coche."
        apex = "Retrasar apice medio coche para evitar recorte agresivo interno."
        if gas >= 0.65:
            exit_action = "Retrasar gas fuerte hasta ver volante mas abierto en salida."
        else:
            exit_action = "Usar salida completa sin cruzar limite externo."
    elif under >= 85.0:
        objective = "Usar mas ancho de pista y mejorar velocidad minima sin exceder limites."
        entry = "Abrir mas la entrada usando todo el exterior disponible."
        apex = "Aproximar apice de forma progresiva para rotar antes el coche."
        exit_action = "Dejar correr el coche hasta el borde externo con volante suave."
    elif gas >= 0.7 and over >= 8.0:
        objective = "Mejorar traccion de salida manteniendo el coche dentro de limites."
        entry = "Priorizar estabilidad en frenada y evitar llegar con exceso de velocidad."
        apex = "Apuntar a apice ligeramente tardio para mejorar linea de salida."
        exit_action = "Dosificar gas en dos fases (60-70% y luego 100% con volante abierto)."

    if slip >= 0.12:
        objective = "Recuperar traccion real y reducir desgaste en salida."
        exit_action = "Modular gas en rampa y abrir volante antes para reducir patinaje."

    if suspension >= 0.085:
        apex = "Evitar atacar piano interior agresivo para no desestabilizar el chasis en apoyo."

    return {
        "objective": objective,
        "entry": entry,
        "apex": apex,
        "exit": exit_action,
    }


def _bucket_summary(index: int, bins: int, total_count: int, bucket: dict[str, float], track_length_m: float) -> dict[str, Any]:
    count = int(bucket["count"])
    start_ratio = index / bins
    end_ratio = (index + 1) / bins
    center_ratio = (start_ratio + end_ratio) / 2.0

    avg_speed = bucket["sum_speed"] / count
    avg_brake = bucket["sum_brake"] / count
    avg_gas = bucket["sum_gas"] / count
    avg_steer = bucket["sum_steer"] / count
    avg_tc = bucket["sum_tc"] / count
    avg_abs = bucket["sum_abs"] / count
    avg_slip = bucket["sum_slip"] / count
    max_slip = bucket["sum_slip_max"] / count
    avg_susp = bucket["sum_suspension"] / count

    distance_m = round(center_ratio * track_length_m, 1) if track_length_m > 0 else None

    return {
        "bin_index": index,
        "start_pct": round(start_ratio * 100.0, 3),
        "end_pct": round(end_ratio * 100.0, 3),
        "center_pct": round(center_ratio * 100.0, 3),
        "sample_count": count,
        "coverage_pct": round(100.0 * count / max(1, total_count), 3),
        "avg_speed_kmh": round(avg_speed, 3),
        "avg_brake": round(avg_brake, 4),
        "avg_gas": round(avg_gas, 4),
        "avg_abs_steer": round(avg_steer, 4),
        "avg_tc_setting": round(avg_tc, 4),
        "avg_abs_setting": round(avg_abs, 4),
        "avg_wheel_slip": round(avg_slip, 5),
        "max_wheel_slip": round(max_slip, 5),
        "avg_suspension_travel": round(avg_susp, 6),
        "estimated_distance_m": distance_m,
    }


def analyze_shared_memory_track_map(path: str = "", bins: int = 40) -> dict[str, Any]:
    bucket_count = max(8, min(int(bins), 200))

    try:
        resolved, payload, samples = _load_shared_memory_payload(path)
    except FileNotFoundError as exc:
        return {
            "ok": False,
            "error": str(exc),
            "path": path,
        }
    except ValueError as exc:
        return {
            "ok": False,
            "error": str(exc),
            "path": path,
        }

    first_static = samples[0].get("static", {}) if isinstance(samples[0], dict) else {}
    track = str(first_static.get("track", "") or "")
    car = str(first_static.get("car_model", "") or "")
    track_key = track.lower().strip()
    track_length_m = _KNOWN_TRACK_LENGTH_M.get(track_key, 0.0)

    buckets: list[dict[str, float]] = [
        {
            "count": 0.0,
            "sum_speed": 0.0,
            "sum_brake": 0.0,
            "sum_gas": 0.0,
            "sum_steer": 0.0,
            "sum_tc": 0.0,
            "sum_abs": 0.0,
            "sum_slip": 0.0,
            "sum_slip_max": 0.0,
            "sum_suspension": 0.0,
        }
        for _ in range(bucket_count)
    ]

    missing_position_count = 0
    mapped_count = 0
    sectors: dict[str, int] = {}
    completed_laps: list[int] = []

    for sample in samples:
        if not isinstance(sample, dict):
            continue

        graphics = sample.get("graphics", {})
        physics = sample.get("physics", {})

        completed_laps.append(_safe_int(graphics.get("completed_laps", 0)))

        sector_index = _safe_int(graphics.get("current_sector_index", -1))
        sectors[str(sector_index)] = sectors.get(str(sector_index), 0) + 1

        position = graphics.get("normalized_car_position")
        position_value = _safe_float(position)
        if position is None:
            missing_position_count += 1
            continue

        position_value = max(0.0, min(0.999999, position_value))
        bucket_index = min(int(position_value * bucket_count), bucket_count - 1)

        speed = _safe_float(physics.get("speed_kmh", 0.0))
        brake = _safe_float(physics.get("brake", 0.0))
        gas = _safe_float(physics.get("gas", 0.0))
        steer = abs(_safe_float(physics.get("steer_angle", 0.0)))
        tc_setting = _safe_float(physics.get("tc", 0.0))
        abs_setting = _safe_float(physics.get("abs", 0.0))
        wheel_slip_avg = _safe_wheel_slip_avg(physics.get("wheel_slip", physics.get("avg_wheel_slip", 0.0)))
        wheel_slip_max = _safe_wheel_slip_max(physics.get("wheel_slip", physics.get("max_wheel_slip", 0.0)))
        suspension_avg = _safe_bounded_sequence_avg(
            physics.get("suspension_travel", physics.get("avg_suspension_travel", 0.0)),
            minimum=_MIN_REASONABLE_SUSPENSION_TRAVEL,
            maximum=_MAX_REASONABLE_SUSPENSION_TRAVEL,
        )

        bucket = buckets[bucket_index]
        bucket["count"] += 1.0
        bucket["sum_speed"] += speed
        bucket["sum_brake"] += brake
        bucket["sum_gas"] += gas
        bucket["sum_steer"] += steer
        bucket["sum_tc"] += tc_setting
        bucket["sum_abs"] += abs_setting
        bucket["sum_slip"] += wheel_slip_avg
        bucket["sum_slip_max"] += wheel_slip_max
        bucket["sum_suspension"] += suspension_avg
        mapped_count += 1

    if mapped_count == 0:
        return {
            "ok": False,
            "error": "Samples do not include normalized_car_position",
            "path": str(resolved),
            "sample_count": len(samples),
        }

    profile = [
        _bucket_summary(i, bucket_count, mapped_count, bucket, track_length_m)
        for i, bucket in enumerate(buckets)
        if int(bucket["count"]) > 0
    ]

    heavy_braking = sorted(profile, key=lambda row: (row["avg_brake"], row["sample_count"]), reverse=True)[:5]
    low_speed = sorted(profile, key=lambda row: row["avg_speed_kmh"])[:5]
    traction = sorted(
        profile,
        key=lambda row: (
            row["avg_gas"] * (1.0 - min(row["avg_speed_kmh"] / 250.0, 1.0))
            + (row.get("avg_wheel_slip", 0.0) * 1.8),
            row["sample_count"],
        ),
        reverse=True,
    )[:5]

    lap_start = completed_laps[0] if completed_laps else 0
    lap_end = completed_laps[-1] if completed_laps else 0
    session_overview = _build_session_overview(samples)

    return {
        "ok": True,
        "path": str(resolved),
        "session_id": str(payload.get("session_id", "")),
        "sample_count": len(samples),
        "mapped_sample_count": mapped_count,
        "missing_position_count": missing_position_count,
        "mapping_coverage_pct": round(100.0 * mapped_count / max(1, len(samples)), 3),
        "car_model": car,
        "track": track,
        "track_length_m": track_length_m if track_length_m > 0 else None,
        "bins": bucket_count,
        "lap_start": lap_start,
        "lap_end": lap_end,
        "sectors_seen": sectors,
        "session_overview": session_overview,
        "profile": profile,
        "hotspots": {
            "heavy_braking": heavy_braking,
            "low_speed": low_speed,
            "traction_demand": traction,
        },
    }


def analyze_shared_memory_corner_limits(path: str = "", bins: int = 120) -> dict[str, Any]:
    bucket_count = max(30, min(int(bins), 300))

    try:
        resolved, payload, samples = _load_shared_memory_payload(path)
    except FileNotFoundError as exc:
        return {
            "ok": False,
            "error": str(exc),
            "path": path,
        }
    except ValueError as exc:
        return {
            "ok": False,
            "error": str(exc),
            "path": path,
        }

    first_static = samples[0].get("static", {}) if isinstance(samples[0], dict) else {}
    track = str(first_static.get("track", "") or "")
    car = str(first_static.get("car_model", "") or "")

    profile, profile_source = _resolve_corner_profile(track, samples)
    if not profile:
        return {
            "ok": False,
            "error": "No corner profile available for this track",
            "path": str(resolved),
            "track": track,
        }

    stats: dict[str, dict[str, float]] = {}
    for corner in profile:
        name = str(corner.get("name", "")).strip() or "unknown"
        stats[name] = {
            "sample_count": 0.0,
            "sum_speed": 0.0,
            "sum_brake": 0.0,
            "sum_gas": 0.0,
            "sum_steer": 0.0,
            "sum_tc": 0.0,
            "sum_abs": 0.0,
            "sum_wheel_slip": 0.0,
            "sum_wheel_slip_max": 0.0,
            "sum_suspension_travel": 0.0,
            "sum_tyre_temp": 0.0,
            "sum_tyre_wear": 0.0,
            "under_limit": 0.0,
            "on_limit": 0.0,
            "over_limit": 0.0,
            "severe_over_limit": 0.0,
        }

    missing_position_count = 0
    missing_tyres_out_count = 0
    mapped_sample_count = 0

    for sample in samples:
        graphics = sample.get("graphics", {}) if isinstance(sample, dict) else {}
        physics = sample.get("physics", {}) if isinstance(sample, dict) else {}

        position = graphics.get("normalized_car_position")
        if position is None:
            missing_position_count += 1
            continue

        position_pct = max(0.0, min(99.999, _safe_float(position) * 100.0))
        corner = _find_corner_for_position(position_pct, profile)
        if corner is None:
            continue

        corner_name = str(corner.get("name", "unknown"))
        current = stats.get(corner_name)
        if current is None:
            continue

        speed = _safe_float(physics.get("speed_kmh", 0.0))
        brake = _safe_float(physics.get("brake", 0.0))
        gas = _safe_float(physics.get("gas", 0.0))
        steer = abs(_safe_float(physics.get("steer_angle", 0.0)))
        tc_setting = _safe_float(physics.get("tc", 0.0))
        abs_setting = _safe_float(physics.get("abs", 0.0))
        wheel_slip_avg = _safe_wheel_slip_avg(physics.get("wheel_slip", physics.get("avg_wheel_slip", 0.0)))
        wheel_slip_max = _safe_wheel_slip_max(physics.get("wheel_slip", physics.get("max_wheel_slip", 0.0)))
        suspension_avg = _safe_bounded_sequence_avg(
            physics.get("suspension_travel", physics.get("avg_suspension_travel", 0.0)),
            minimum=_MIN_REASONABLE_SUSPENSION_TRAVEL,
            maximum=_MAX_REASONABLE_SUSPENSION_TRAVEL,
        )
        tyre_temp_avg = _safe_bounded_sequence_avg(
            physics.get("tyre_core_temp_c", physics.get("avg_tyre_temp_c", 0.0)),
            minimum=_MIN_REASONABLE_TYRE_TEMP_C,
            maximum=_MAX_REASONABLE_TYRE_TEMP_C,
        )
        tyre_wear_avg = _safe_bounded_sequence_avg(
            physics.get("tyre_wear", physics.get("avg_tyre_wear", 0.0)),
            minimum=_MIN_REASONABLE_TYRE_WEAR,
            maximum=_MAX_REASONABLE_TYRE_WEAR,
        )

        tyres_out_raw = physics.get("number_of_tyres_out")
        if tyres_out_raw is None:
            missing_tyres_out_count += 1
        tyres_out = max(0, min(4, _safe_int(tyres_out_raw)))

        current["sample_count"] += 1.0
        current["sum_speed"] += speed
        current["sum_brake"] += brake
        current["sum_gas"] += gas
        current["sum_steer"] += steer
        current["sum_tc"] += tc_setting
        current["sum_abs"] += abs_setting
        current["sum_wheel_slip"] += wheel_slip_avg
        current["sum_wheel_slip_max"] += wheel_slip_max
        current["sum_suspension_travel"] += suspension_avg
        current["sum_tyre_temp"] += tyre_temp_avg
        current["sum_tyre_wear"] += tyre_wear_avg
        if tyres_out == 0:
            current["under_limit"] += 1.0
        elif tyres_out == 1:
            current["on_limit"] += 1.0
        else:
            current["over_limit"] += 1.0
            if tyres_out >= 3:
                current["severe_over_limit"] += 1.0

        mapped_sample_count += 1

    if mapped_sample_count == 0:
        return {
            "ok": False,
            "error": "Samples do not include usable normalized_car_position",
            "path": str(resolved),
            "track": track,
            "profile_source": profile_source,
        }

    corners: list[dict[str, Any]] = []
    for corner in profile:
        name = str(corner.get("name", "unknown"))
        data = stats.get(name, {})
        count = int(data.get("sample_count", 0.0))
        if count <= 0:
            corners.append(
                {
                    "name": name,
                    "start_pct": corner.get("start_pct"),
                    "end_pct": corner.get("end_pct"),
                    "sample_count": 0,
                    "coverage_pct": 0.0,
                    "advice": "Sin muestras en esta captura.",
                }
            )
            continue

        avg_speed = float(data["sum_speed"]) / count
        avg_brake = float(data["sum_brake"]) / count
        avg_gas = float(data["sum_gas"]) / count
        avg_steer = float(data["sum_steer"]) / count
        avg_tc = float(data["sum_tc"]) / count
        avg_abs = float(data["sum_abs"]) / count
        avg_wheel_slip = float(data["sum_wheel_slip"]) / count
        max_wheel_slip = float(data["sum_wheel_slip_max"]) / count
        avg_suspension_travel = float(data["sum_suspension_travel"]) / count
        avg_tyre_temp = float(data["sum_tyre_temp"]) / count
        avg_tyre_wear = float(data["sum_tyre_wear"]) / count
        under_limit = int(data["under_limit"])
        on_limit = int(data["on_limit"])
        over_limit = int(data["over_limit"])
        severe_over_limit = int(data["severe_over_limit"])

        under_limit_pct = round((under_limit / count) * 100.0, 3)
        on_limit_pct = round((on_limit / count) * 100.0, 3)
        over_limit_pct = round((over_limit / count) * 100.0, 3)
        severe_over_limit_pct = round((severe_over_limit / count) * 100.0, 3)

        corners.append(
            {
                "name": name,
                "start_pct": corner.get("start_pct"),
                "end_pct": corner.get("end_pct"),
                "sample_count": count,
                "coverage_pct": round((count / mapped_sample_count) * 100.0, 3),
                "avg_speed_kmh": round(avg_speed, 3),
                "avg_brake": round(avg_brake, 4),
                "avg_gas": round(avg_gas, 4),
                "avg_abs_steer": round(avg_steer, 4),
                "avg_tc_setting": round(avg_tc, 4),
                "avg_abs_setting": round(avg_abs, 4),
                "avg_wheel_slip": round(avg_wheel_slip, 5),
                "max_wheel_slip": round(max_wheel_slip, 5),
                "avg_suspension_travel": round(avg_suspension_travel, 6),
                "avg_tyre_temp_c": round(avg_tyre_temp, 4),
                "avg_tyre_wear": round(avg_tyre_wear, 5),
                "under_limit_count": under_limit,
                "on_limit_count": on_limit,
                "over_limit_count": over_limit,
                "severe_over_limit_count": severe_over_limit,
                "under_limit_pct": under_limit_pct,
                "on_limit_pct": on_limit_pct,
                "over_limit_pct": over_limit_pct,
                "severe_over_limit_pct": severe_over_limit_pct,
                "advice": _build_corner_advice(
                    over_limit_pct=over_limit_pct,
                    severe_over_limit_pct=severe_over_limit_pct,
                    under_limit_pct=under_limit_pct,
                    avg_abs_steer=avg_steer,
                    avg_speed_kmh=avg_speed,
                    avg_gas=avg_gas,
                    avg_wheel_slip=avg_wheel_slip,
                    avg_suspension_travel=avg_suspension_travel,
                    avg_tc_setting=avg_tc,
                    avg_abs_setting=avg_abs,
                ),
            }
        )

    high_risk = sorted(
        [corner for corner in corners if int(corner.get("sample_count", 0)) > 0],
        key=lambda item: (
            float(item.get("over_limit_pct", 0.0)),
            float(item.get("severe_over_limit_pct", 0.0)),
            float(item.get("avg_wheel_slip", 0.0)),
        ),
        reverse=True,
    )[:5]
    underused = sorted(
        [corner for corner in corners if int(corner.get("sample_count", 0)) > 0],
        key=lambda item: (float(item.get("under_limit_pct", 0.0)), float(item.get("avg_abs_steer", 0.0))),
        reverse=True,
    )[:5]

    total_under = sum(int(corner.get("under_limit_count", 0)) for corner in corners)
    total_on = sum(int(corner.get("on_limit_count", 0)) for corner in corners)
    total_over = sum(int(corner.get("over_limit_count", 0)) for corner in corners)
    total_severe_over = sum(int(corner.get("severe_over_limit_count", 0)) for corner in corners)

    tyres_out_available = max(0, mapped_sample_count - missing_tyres_out_count)
    session_overview = _build_session_overview(samples)

    return {
        "ok": True,
        "path": str(resolved),
        "session_id": str(payload.get("session_id", "")),
        "track": track,
        "car_model": car,
        "sample_count": len(samples),
        "mapped_sample_count": mapped_sample_count,
        "missing_position_count": missing_position_count,
        "missing_tyres_out_count": missing_tyres_out_count,
        "mapping_coverage_pct": round((mapped_sample_count / max(1, len(samples))) * 100.0, 3),
        "tyres_out_coverage_pct": round((tyres_out_available / max(1, mapped_sample_count)) * 100.0, 3),
        "profile_source": profile_source,
        "profile_corner_count": len(profile),
        "bins": bucket_count,
        "session_overview": session_overview,
        "summary": {
            "under_limit_samples": total_under,
            "on_limit_samples": total_on,
            "over_limit_samples": total_over,
            "severe_over_limit_samples": total_severe_over,
        },
        "high_risk_corners": high_risk,
        "underused_corners": underused,
        "corners": corners,
    }


def coach_shared_memory_corner_limits(path: str = "", bins: int = 120, top_n: int = 5) -> dict[str, Any]:
    analysis = analyze_shared_memory_corner_limits(path=path, bins=bins)
    if not analysis.get("ok"):
        return analysis

    requested_top_n = max(1, min(int(top_n), 12))
    corners = analysis.get("corners", [])
    if not isinstance(corners, list):
        corners = []

    actionable = [corner for corner in corners if _safe_int(corner.get("sample_count", 0)) > 0]
    ranked = sorted(
        actionable,
        key=lambda corner: (_corner_impact_score(corner), _safe_float(corner.get("coverage_pct", 0.0))),
        reverse=True,
    )

    priorities: list[dict[str, Any]] = []
    for index, corner in enumerate(ranked[:requested_top_n], start=1):
        phase_actions = _build_corner_phase_actions(corner)
        impact_score = _corner_impact_score(corner)

        priorities.append(
            {
                "priority": index,
                "corner": str(corner.get("name", "unknown")),
                "impact_score": impact_score,
                "objective": phase_actions["objective"],
                "entry_action": phase_actions["entry"],
                "apex_action": phase_actions["apex"],
                "exit_action": phase_actions["exit"],
                "tyre_wear_risk": _wear_risk_level(corner),
                "metrics": {
                    "over_limit_pct": _safe_float(corner.get("over_limit_pct", 0.0)),
                    "severe_over_limit_pct": _safe_float(corner.get("severe_over_limit_pct", 0.0)),
                    "under_limit_pct": _safe_float(corner.get("under_limit_pct", 0.0)),
                    "avg_speed_kmh": _safe_float(corner.get("avg_speed_kmh", 0.0)),
                    "avg_brake": _safe_float(corner.get("avg_brake", 0.0)),
                    "avg_gas": _safe_float(corner.get("avg_gas", 0.0)),
                    "avg_wheel_slip": _safe_float(corner.get("avg_wheel_slip", 0.0)),
                    "avg_suspension_travel": _safe_float(corner.get("avg_suspension_travel", 0.0)),
                    "avg_tc_setting": _safe_float(corner.get("avg_tc_setting", 0.0)),
                    "avg_abs_setting": _safe_float(corner.get("avg_abs_setting", 0.0)),
                    "coverage_pct": _safe_float(corner.get("coverage_pct", 0.0)),
                },
                "advice": str(corner.get("advice", "")),
            }
        )

    if priorities:
        overall_risk = round(sum(float(item.get("impact_score", 0.0)) for item in priorities) / len(priorities), 3)
    else:
        overall_risk = 0.0

    return {
        "ok": True,
        "path": analysis.get("path", ""),
        "session_id": analysis.get("session_id", ""),
        "track": analysis.get("track", ""),
        "car_model": analysis.get("car_model", ""),
        "profile_source": analysis.get("profile_source", ""),
        "sample_count": analysis.get("sample_count", 0),
        "mapped_sample_count": analysis.get("mapped_sample_count", 0),
        "top_n": requested_top_n,
        "overall_risk_score": overall_risk,
        "session_overview": analysis.get("session_overview", {}),
        "priorities": priorities,
        "summary": analysis.get("summary", {}),
        "high_risk_corners": analysis.get("high_risk_corners", []),
        "underused_corners": analysis.get("underused_corners", []),
    }


def _median(values: list[float]) -> float | None:
    if not values:
        return None

    ordered = sorted(values)
    size = len(ordered)
    mid = size // 2
    if size % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _summarize_sectors(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[int, dict[str, Any]] = {}

    for sample in samples:
        if not isinstance(sample, dict):
            continue

        graphics = sample.get("graphics", {})
        physics = sample.get("physics", {})
        sector_index = _safe_int(graphics.get("current_sector_index", -1))
        if sector_index < 0:
            continue

        bucket = buckets.setdefault(
            sector_index,
            {
                "count": 0,
                "sum_speed": 0.0,
                "sum_brake": 0.0,
                "sum_gas": 0.0,
                "sum_slip": 0.0,
                "times_ms": [],
            },
        )

        speed = _safe_float(physics.get("speed_kmh", 0.0))
        brake = _safe_float(physics.get("brake", 0.0))
        gas = _safe_float(physics.get("gas", 0.0))
        slip = _safe_wheel_slip_avg(physics.get("wheel_slip", physics.get("avg_wheel_slip", 0.0)))
        sector_time_ms = _safe_int(graphics.get("last_sector_time", 0))

        bucket["count"] += 1
        bucket["sum_speed"] += speed
        bucket["sum_brake"] += brake
        bucket["sum_gas"] += gas
        bucket["sum_slip"] += slip
        if sector_time_ms > 0:
            bucket["times_ms"].append(float(sector_time_ms))

    sectors: list[dict[str, Any]] = []
    for sector_index in sorted(buckets.keys()):
        data = buckets[sector_index]
        count = max(1, int(data["count"]))
        avg_speed = data["sum_speed"] / count
        avg_brake = data["sum_brake"] / count
        avg_gas = data["sum_gas"] / count
        avg_slip = data["sum_slip"] / count

        sector_time = _median([_safe_float(item) for item in data["times_ms"]])
        pace_index = avg_speed - (avg_brake * 95.0) + (avg_gas * 18.0) - (avg_slip * 45.0)

        sectors.append(
            {
                "sector_index": sector_index,
                "sector_number": sector_index + 1,
                "sample_count": count,
                "avg_speed_kmh": round(avg_speed, 3),
                "avg_brake": round(avg_brake, 4),
                "avg_gas": round(avg_gas, 4),
                "avg_wheel_slip": round(avg_slip, 5),
                "sector_time_ms": int(round(sector_time)) if sector_time is not None else None,
                "pace_index": round(pace_index, 3),
            }
        )

    return sectors


def _estimate_lap_time_ms(samples: list[dict[str, Any]], sector_summary: list[dict[str, Any]]) -> tuple[int | None, str]:
    best_times: list[float] = []
    last_times: list[float] = []

    for sample in samples:
        if not isinstance(sample, dict):
            continue
        graphics = sample.get("graphics", {})

        best_ms = _safe_int(graphics.get("i_best_time", 0))
        last_ms = _safe_int(graphics.get("i_last_time", 0))
        if best_ms > 0:
            best_times.append(float(best_ms))
        if last_ms > 0:
            last_times.append(float(last_ms))

    best_median = _median(best_times)
    if best_median is not None:
        return int(round(best_median)), "i_best_time_median"

    last_median = _median(last_times)
    if last_median is not None:
        return int(round(last_median)), "i_last_time_median"

    sector_times = [
        _safe_int(sector.get("sector_time_ms", 0))
        for sector in sector_summary
        if _safe_int(sector.get("sector_time_ms", 0)) > 0
    ]
    if len(sector_times) >= 3:
        return int(sum(sector_times[:3])), "sum_sector_times"

    return None, "unavailable"


def _evaluate_objective(
    objective: str,
    base_lap_time_ms: int | None,
    candidate_lap_time_ms: int | None,
    base_sectors: dict[int, dict[str, Any]],
    candidate_sectors: dict[int, dict[str, Any]],
    base_corners: dict[str, dict[str, Any]],
    candidate_corners: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    normalized = str(objective or "lap_time").strip().lower()

    def _winner(delta: float, lower_is_better: bool) -> str:
        if abs(delta) < 1e-9:
            return "tie"
        if lower_is_better:
            return "candidate" if delta < 0.0 else "base"
        return "candidate" if delta > 0.0 else "base"

    if normalized in {"lap_time", "lap", "overall"}:
        if base_lap_time_ms is not None and candidate_lap_time_ms is not None:
            delta = float(candidate_lap_time_ms - base_lap_time_ms)
            return {
                "objective": "lap_time",
                "metric": "lap_time_ms",
                "base_value": base_lap_time_ms,
                "candidate_value": candidate_lap_time_ms,
                "delta": round(delta, 3),
                "lower_is_better": True,
                "winner": _winner(delta, lower_is_better=True),
                "source": "timing",
            }

    if normalized.startswith("sector_"):
        try:
            sector_number = int(normalized.split("_", maxsplit=1)[1])
        except (TypeError, ValueError, IndexError):
            sector_number = 0

        sector_index = sector_number - 1
        base_sector = base_sectors.get(sector_index, {})
        candidate_sector = candidate_sectors.get(sector_index, {})
        base_time = base_sector.get("sector_time_ms")
        candidate_time = candidate_sector.get("sector_time_ms")

        if base_time is not None and candidate_time is not None:
            delta = float(candidate_time - base_time)
            return {
                "objective": f"sector_{sector_number}",
                "metric": "sector_time_ms",
                "base_value": int(base_time),
                "candidate_value": int(candidate_time),
                "delta": round(delta, 3),
                "lower_is_better": True,
                "winner": _winner(delta, lower_is_better=True),
                "source": "timing",
            }

        base_pace = _safe_float(base_sector.get("pace_index", 0.0))
        candidate_pace = _safe_float(candidate_sector.get("pace_index", 0.0))
        delta = candidate_pace - base_pace
        return {
            "objective": f"sector_{max(1, sector_number)}",
            "metric": "pace_index",
            "base_value": round(base_pace, 3),
            "candidate_value": round(candidate_pace, 3),
            "delta": round(delta, 3),
            "lower_is_better": False,
            "winner": _winner(delta, lower_is_better=False),
            "source": "proxy",
        }

    if normalized in {"slow_corner_exit", "slow_exit"}:
        names = sorted(set(base_corners.keys()) | set(candidate_corners.keys()))
        base_scores: list[float] = []
        candidate_scores: list[float] = []

        for name in names:
            base_corner = base_corners.get(name, {})
            candidate_corner = candidate_corners.get(name, {})

            base_speed = _safe_float(base_corner.get("avg_speed_kmh", 0.0))
            candidate_speed = _safe_float(candidate_corner.get("avg_speed_kmh", 0.0))
            if min(base_speed, candidate_speed) > 120.0:
                continue

            base_score = (
                (_safe_float(base_corner.get("avg_gas", 0.0)) * 40.0)
                + (base_speed * 0.60)
                - (_safe_float(base_corner.get("over_limit_pct", 0.0)) * 0.50)
                - (_safe_float(base_corner.get("avg_wheel_slip", 0.0)) * 35.0)
            )
            candidate_score = (
                (_safe_float(candidate_corner.get("avg_gas", 0.0)) * 40.0)
                + (candidate_speed * 0.60)
                - (_safe_float(candidate_corner.get("over_limit_pct", 0.0)) * 0.50)
                - (_safe_float(candidate_corner.get("avg_wheel_slip", 0.0)) * 35.0)
            )
            base_scores.append(base_score)
            candidate_scores.append(candidate_score)

        base_value = _safe_float(_median(base_scores) or 0.0)
        candidate_value = _safe_float(_median(candidate_scores) or 0.0)
        delta = candidate_value - base_value
        return {
            "objective": "slow_corner_exit",
            "metric": "exit_quality_score",
            "base_value": round(base_value, 3),
            "candidate_value": round(candidate_value, 3),
            "delta": round(delta, 3),
            "lower_is_better": False,
            "winner": _winner(delta, lower_is_better=False),
            "source": "proxy",
        }

    # Fallback: cualquier objetivo desconocido cae a lap_time (sin recursión)
    if base_lap_time_ms is not None and candidate_lap_time_ms is not None:
        delta = float(candidate_lap_time_ms - base_lap_time_ms)
        return {
            "objective": "lap_time",
            "metric": "lap_time_ms",
            "base_value": base_lap_time_ms,
            "candidate_value": candidate_lap_time_ms,
            "delta": round(delta, 3),
            "lower_is_better": True,
            "winner": _winner(delta, lower_is_better=True),
            "source": "timing",
        }
    
    # Si no hay lap times, retornar error
    return {
        "objective": "unknown",
        "metric": "none",
        "base_value": 0,
        "candidate_value": 0,
        "delta": 0,
        "lower_is_better": True,
        "winner": "unknown",
        "source": "error",
        "error": f"Cannot evaluate objective '{objective}' - no data available",
    }


def compare_shared_memory_stints(
    base_path: str,
    candidate_path: str,
    bins: int = 120,
    objective: str = "lap_time",
) -> dict[str, Any]:
    try:
        base_resolved, base_payload, base_samples = _load_shared_memory_payload(base_path)
        candidate_resolved, candidate_payload, candidate_samples = _load_shared_memory_payload(candidate_path)
    except FileNotFoundError as exc:
        return {
            "ok": False,
            "error": str(exc),
            "base_path": base_path,
            "candidate_path": candidate_path,
        }
    except ValueError as exc:
        return {
            "ok": False,
            "error": str(exc),
            "base_path": base_path,
            "candidate_path": candidate_path,
        }

    base_corner_analysis = analyze_shared_memory_corner_limits(path=str(base_resolved), bins=bins)
    if not base_corner_analysis.get("ok"):
        return {
            "ok": False,
            "error": f"Base analysis failed: {base_corner_analysis.get('error', 'unknown error')}",
            "base_path": str(base_resolved),
            "candidate_path": str(candidate_resolved),
        }

    candidate_corner_analysis = analyze_shared_memory_corner_limits(path=str(candidate_resolved), bins=bins)
    if not candidate_corner_analysis.get("ok"):
        return {
            "ok": False,
            "error": f"Candidate analysis failed: {candidate_corner_analysis.get('error', 'unknown error')}",
            "base_path": str(base_resolved),
            "candidate_path": str(candidate_resolved),
        }

    base_sector_summary = _summarize_sectors(base_samples)
    candidate_sector_summary = _summarize_sectors(candidate_samples)

    base_lap_time_ms, base_lap_time_source = _estimate_lap_time_ms(base_samples, base_sector_summary)
    candidate_lap_time_ms, candidate_lap_time_source = _estimate_lap_time_ms(candidate_samples, candidate_sector_summary)

    base_sectors = {int(item.get("sector_index", -1)): item for item in base_sector_summary}
    candidate_sectors = {int(item.get("sector_index", -1)): item for item in candidate_sector_summary}
    sector_indices = sorted(set(base_sectors.keys()) | set(candidate_sectors.keys()))

    sector_deltas: list[dict[str, Any]] = []
    for sector_index in sector_indices:
        base_sector = base_sectors.get(sector_index, {})
        candidate_sector = candidate_sectors.get(sector_index, {})
        base_time = base_sector.get("sector_time_ms")
        candidate_time = candidate_sector.get("sector_time_ms")

        time_delta = None
        if base_time is not None and candidate_time is not None:
            time_delta = int(candidate_time) - int(base_time)

        base_pace = _safe_float(base_sector.get("pace_index", 0.0))
        candidate_pace = _safe_float(candidate_sector.get("pace_index", 0.0))
        pace_delta = candidate_pace - base_pace

        if time_delta is not None:
            status = "improved" if time_delta < 0 else "worse" if time_delta > 0 else "equal"
        else:
            status = "improved" if pace_delta > 0 else "worse" if pace_delta < 0 else "equal"

        sector_deltas.append(
            {
                "sector_index": sector_index,
                "sector_number": sector_index + 1,
                "base_sector_time_ms": base_time,
                "candidate_sector_time_ms": candidate_time,
                "delta_time_ms": time_delta,
                "base_pace_index": round(base_pace, 3),
                "candidate_pace_index": round(candidate_pace, 3),
                "delta_pace_index": round(pace_delta, 3),
                "status": status,
            }
        )

    base_corner_rows = base_corner_analysis.get("corners", [])
    candidate_corner_rows = candidate_corner_analysis.get("corners", [])
    if not isinstance(base_corner_rows, list):
        base_corner_rows = []
    if not isinstance(candidate_corner_rows, list):
        candidate_corner_rows = []

    base_corners = {str(item.get("name", "unknown")): item for item in base_corner_rows}
    candidate_corners = {str(item.get("name", "unknown")): item for item in candidate_corner_rows}

    corner_deltas: list[dict[str, Any]] = []
    for name in sorted(set(base_corners.keys()) | set(candidate_corners.keys())):
        base_corner = base_corners.get(name, {})
        candidate_corner = candidate_corners.get(name, {})

        base_impact = _corner_impact_score(base_corner) if base_corner else 0.0
        candidate_impact = _corner_impact_score(candidate_corner) if candidate_corner else 0.0
        impact_delta = candidate_impact - base_impact

        corner_deltas.append(
            {
                "corner": name,
                "base_sample_count": _safe_int(base_corner.get("sample_count", 0)),
                "candidate_sample_count": _safe_int(candidate_corner.get("sample_count", 0)),
                "delta_avg_speed_kmh": round(
                    _safe_float(candidate_corner.get("avg_speed_kmh", 0.0))
                    - _safe_float(base_corner.get("avg_speed_kmh", 0.0)),
                    3,
                ),
                "delta_over_limit_pct": round(
                    _safe_float(candidate_corner.get("over_limit_pct", 0.0))
                    - _safe_float(base_corner.get("over_limit_pct", 0.0)),
                    3,
                ),
                "delta_severe_over_limit_pct": round(
                    _safe_float(candidate_corner.get("severe_over_limit_pct", 0.0))
                    - _safe_float(base_corner.get("severe_over_limit_pct", 0.0)),
                    3,
                ),
                "delta_avg_gas": round(
                    _safe_float(candidate_corner.get("avg_gas", 0.0))
                    - _safe_float(base_corner.get("avg_gas", 0.0)),
                    4,
                ),
                "delta_avg_wheel_slip": round(
                    _safe_float(candidate_corner.get("avg_wheel_slip", 0.0))
                    - _safe_float(base_corner.get("avg_wheel_slip", 0.0)),
                    5,
                ),
                "base_impact_score": round(base_impact, 3),
                "candidate_impact_score": round(candidate_impact, 3),
                "delta_impact_score": round(impact_delta, 3),
                "status": "improved" if impact_delta < 0 else "worse" if impact_delta > 0 else "equal",
            }
        )

    corner_deltas_sorted = sorted(corner_deltas, key=lambda item: abs(_safe_float(item.get("delta_impact_score", 0.0))), reverse=True)
    improved_corners = [item for item in corner_deltas_sorted if item.get("status") == "improved"][:5]
    regressed_corners = [item for item in corner_deltas_sorted if item.get("status") == "worse"][:5]

    objective_result = _evaluate_objective(
        objective=objective,
        base_lap_time_ms=base_lap_time_ms,
        candidate_lap_time_ms=candidate_lap_time_ms,
        base_sectors=base_sectors,
        candidate_sectors=candidate_sectors,
        base_corners=base_corners,
        candidate_corners=candidate_corners,
    )

    track = str(base_corner_analysis.get("track", "") or candidate_corner_analysis.get("track", ""))
    car_model = str(base_corner_analysis.get("car_model", "") or candidate_corner_analysis.get("car_model", ""))

    return {
        "ok": True,
        "base_path": str(base_resolved),
        "candidate_path": str(candidate_resolved),
        "base_session_id": str(base_payload.get("session_id", "")),
        "candidate_session_id": str(candidate_payload.get("session_id", "")),
        "track": track,
        "car_model": car_model,
        "objective": objective_result,
        "base_session_overview": base_corner_analysis.get("session_overview", {}),
        "candidate_session_overview": candidate_corner_analysis.get("session_overview", {}),
        "lap_time": {
            "base_ms": base_lap_time_ms,
            "candidate_ms": candidate_lap_time_ms,
            "delta_ms": (candidate_lap_time_ms - base_lap_time_ms)
            if base_lap_time_ms is not None and candidate_lap_time_ms is not None
            else None,
            "base_source": base_lap_time_source,
            "candidate_source": candidate_lap_time_source,
        },
        "sector_deltas": sector_deltas,
        "corner_deltas": corner_deltas_sorted,
        "top_improved_corners": improved_corners,
        "top_regressed_corners": regressed_corners,
        "base_summary": base_corner_analysis.get("summary", {}),
        "candidate_summary": candidate_corner_analysis.get("summary", {}),
    }
