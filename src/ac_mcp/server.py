from __future__ import annotations

from typing import Any
from pathlib import Path
from datetime import datetime, UTC
import csv
import math
import re

from mcp.server.fastmcp import FastMCP

from ac_mcp.advisor import suggest_changes as advisor_suggest_changes
from ac_mcp.advisor import suggest_changes_heuristic as advisor_suggest_changes_heuristic
from ac_mcp.config import replay_root
from ac_mcp.config import resolve_replay_path
from ac_mcp.config import setup_root
from ac_mcp.pipeline import start_from_base_pipeline
from ac_mcp.references import fetch_reference as refs_fetch_reference
from ac_mcp.references import get_circuit_info as refs_get_circuit_info
from ac_mcp.references import search_base_setups as refs_search_base_setups
from ac_mcp.references import search_references as refs_search_references
from ac_mcp.acreplay_parser_native import ACReplayParser
from ac_mcp.setup_io import apply_changes as io_apply_changes
from ac_mcp.setup_io import compare_setups as io_compare_setups
from ac_mcp.setup_io import find_base_setup as io_find_base_setup
from ac_mcp.setup_io import list_setups as io_list_setups
from ac_mcp.setup_io import read_setup as io_read_setup
from ac_mcp.telemetry_analysis import analyze_shared_memory_corner_limits as analyze_corner_limits_map
from ac_mcp.telemetry_analysis import analyze_shared_memory_track_map
from ac_mcp.telemetry_analysis import coach_shared_memory_corner_limits as coach_corner_limits
from ac_mcp.telemetry_analysis import compare_shared_memory_stints as compare_shm_stints
from ac_mcp.telemetry import list_session_context, record_session_context
from ac_mcp.telemetry_shared_memory import (
    capture_shared_memory_snapshot as shm_capture_snapshot,
)
from ac_mcp.telemetry_shared_memory import get_telemetry_capabilities as shm_get_telemetry_capabilities
from ac_mcp.telemetry_shared_memory import get_iracing_replay_state as shm_get_iracing_replay_state
from ac_mcp.telemetry_shared_memory import get_shared_memory_stint_status as shm_get_stint_status
from ac_mcp.telemetry_shared_memory import (
    iracing_replay_pause as shm_iracing_replay_pause,
)
from ac_mcp.telemetry_shared_memory import (
    iracing_replay_search as shm_iracing_replay_search,
)
from ac_mcp.telemetry_shared_memory import (
    iracing_replay_seek_frame as shm_iracing_replay_seek_frame,
)
from ac_mcp.telemetry_shared_memory import (
    iracing_replay_seek_session_time as shm_iracing_replay_seek_session_time,
)
from ac_mcp.telemetry_shared_memory import (
    iracing_replay_set_play_speed as shm_iracing_replay_set_play_speed,
)
from ac_mcp.telemetry_shared_memory import list_shared_memory_logs
from ac_mcp.telemetry_shared_memory import (
    list_supported_telemetry_simulators as shm_list_supported_simulators,
)
from ac_mcp.telemetry_shared_memory import persist_shared_memory_samples
from ac_mcp.telemetry_shared_memory import (
    capture_iracing_replay_to_shared_memory_json as shm_capture_iracing_replay_json,
)
from ac_mcp.telemetry_shared_memory import read_shared_memory_log as shm_read_log
from ac_mcp.telemetry_shared_memory import record_shared_memory_stint as shm_record_stint
from ac_mcp.telemetry_shared_memory import start_shared_memory_stint as shm_start_stint
from ac_mcp.telemetry_shared_memory import stop_shared_memory_stint as shm_stop_stint

mcp = FastMCP("ac-mcp")

_REPLAY_TIMESTAMP_REGEX = re.compile(r"(\d{6}-\d{6})")


def _parse_timestamp_from_name(name: str) -> datetime | None:
    match = _REPLAY_TIMESTAMP_REGEX.search(name)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%d%m%y-%H%M%S").replace(tzinfo=UTC)
    except ValueError:
        return None


def _extract_replay_tokens(name: str) -> dict[str, str]:
    stem = Path(name).stem
    lower = stem.lower()
    parts = [p for p in lower.split("_") if p]

    category_guess = ""
    if "lfm" in parts:
        category_guess = "lfm"
    elif "osrw" in parts:
        category_guess = "osrw"
    elif "zfr" in parts:
        category_guess = "zfr"

    car_guess = ""
    track_guess = ""
    if parts:
        if lower.startswith("ac_") and len(parts) >= 4:
            car_guess = parts[3]
            if len(parts) > 4:
                track_guess = "_".join(parts[4:])
        else:
            car_guess = parts[0]
            if len(parts) > 1:
                track_guess = "_".join(parts[1:])

    return {
        "car_guess": car_guess,
        "track_guess": track_guess,
        "category_guess": category_guess,
    }


def _matches_filter(value: str, query: str) -> bool:
    if not query:
        return True
    return query.lower() in value.lower()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            # Replay CSVs may serialize numeric fields as float-like strings (e.g. "1250.0").
            return int(float(value))
        except (TypeError, ValueError):
            return default


def _clamp01(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _read_replay_csv_rows(csv_path: Path) -> list[dict[str, str]]:
    lines = csv_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    data_lines = [line for line in lines if line and not line.startswith("#")]
    reader = csv.DictReader(data_lines)
    return [dict(row) for row in reader]


def _compute_lap_normalized_positions(
    sampled_rows: list[dict[str, str]],
    recording_interval_s: float,
    step: int,
) -> list[float]:
    """Compute normalized_car_position (0-1) per row via velocity integration per lap.

    Groups rows by currentLap, integrates cumulative distance within each lap using
    the velocity vector, then normalizes by that lap's total distance.
    """
    laps: dict[int, list[tuple[int, dict[str, str]]]] = {}
    for idx, row in enumerate(sampled_rows):
        lap_num = _safe_int(row.get("currentLap", "0"), 0)
        laps.setdefault(lap_num, []).append((idx, row))

    dt = recording_interval_s * step
    result: list[float] = [0.0] * len(sampled_rows)

    for lap_rows in laps.values():
        dists: list[float] = []
        cumulative = 0.0
        for _idx, row in lap_rows:
            vx = _safe_float(row.get("velocity.x", "0"))
            vy = _safe_float(row.get("velocity.y", "0"))
            vz = _safe_float(row.get("velocity.z", "0"))
            speed_ms = max(0.0, math.sqrt(vx * vx + vy * vy + vz * vz))
            cumulative += speed_ms * dt
            dists.append(cumulative)

        total_lap_dist = dists[-1] if dists else 1.0
        if total_lap_dist <= 0.0:
            total_lap_dist = 1.0

        for (idx, _row), dist in zip(lap_rows, dists):
            result[idx] = min(0.999999, dist / total_lap_dist)

    return result


def _extract_best_lap_time_ms(rows: list[dict[str, str]], min_valid_ms: int = 30000) -> int:
    """Extract the best VALID lap time from replay rows, filtering out invalid values.
    
    Invalid times: < 30s (e.g., 4ms which indicates early session/debug frame).
    Scans all rows and returns the maximum realistic lap time found.
    
    Args:
        rows: CSV rows from parsed replay
        min_valid_ms: Minimum milliseconds to consider a valid lap time (default 30000ms = 30s)
    
    Returns:
        Best realistic lap time in ms, or 0 if no valid times found
    """
    valid_times = []
    for row in rows:
        best_time = _safe_int(row.get("bestLapTime", "0"), 0)
        if best_time >= min_valid_ms:
            valid_times.append(best_time)
    
    if valid_times:
        best = max(valid_times)
        return best

    # Fallback 1: replays where bestLapTime is corrupted but lastLapTime is usable.
    fallback_last_times = []
    for row in rows:
        last_time = _safe_int(row.get("lastLapTime", "0"), 0)
        if last_time >= min_valid_ms:
            fallback_last_times.append(last_time)

    if fallback_last_times:
        return max(fallback_last_times)

    # Fallback 2 (aggressive): if replay is severely corrupted, use max of any non-zero lastLapTime.
    # This handles cases where replay has bad timing data (e.g., Kevin Woodward replay with times ~1250ms).
    fallback_last_any = []
    for row in rows:
        last_time = _safe_int(row.get("lastLapTime", "0"), 0)
        if last_time > 0:  # Any non-zero value
            fallback_last_any.append(last_time)
    
    if fallback_last_any:
        return max(fallback_last_any)

    return 0


def _replay_rows_to_shared_samples(
    rows: list[dict[str, str]],
    track: str,
    car_model: str,
    max_samples: int,
    recording_interval_s: float = 0.033,
) -> list[dict[str, Any]]:
    if not rows:
        return []

    capped_max = max(10, min(int(max_samples), 30000))
    step = max(1, math.ceil(len(rows) / capped_max))
    sampled_rows = rows[::step]

    # Extract best valid lap time ONCE (filter out invalid times like 4ms)
    best_lap_time_ms_global = _extract_best_lap_time_ms(rows)

    normalized_positions = _compute_lap_normalized_positions(
        sampled_rows=sampled_rows,
        recording_interval_s=recording_interval_s,
        step=step,
    )

    samples: list[dict[str, Any]] = []
    for index, row in enumerate(sampled_rows):
        vel_x = _safe_float(row.get("velocity.x", "0"))
        vel_y = _safe_float(row.get("velocity.y", "0"))
        vel_z = _safe_float(row.get("velocity.z", "0"))
        speed_kmh = max(0.0, math.sqrt((vel_x * vel_x) + (vel_y * vel_y) + (vel_z * vel_z)) * 3.6)

        brake = _clamp01(_safe_float(row.get("brake", "0")) / 255.0)
        gas = _clamp01(_safe_float(row.get("gas", "0")) / 255.0)
        steer = _safe_float(row.get("steerAngle", "0"))
        rpm = _safe_float(row.get("rpm", "0"))
        gear = _safe_int(row.get("gear", "0"), 0)
        frame_index = _safe_int(row.get("frame", str(index)), index)
        completed_laps = _safe_int(row.get("currentLap", "0"), 0) + 1
        current_lap_time_ms = _safe_int(row.get("currentLapTime", "0"), 0)
        last_lap_time_ms = _safe_int(row.get("lastLapTime", "0"), 0)
        best_lap_time_ms = best_lap_time_ms_global  # Use filtered best time, not row's value

        # Normalized slip (ndSlip) is the closest analog to shared-memory wheel_slip
        nd_fl = _safe_float(row.get("wheelFL.ndSlip", "0"))
        nd_fr = _safe_float(row.get("wheelFR.ndSlip", "0"))
        nd_rl = _safe_float(row.get("wheelRL.ndSlip", "0"))
        nd_rr = _safe_float(row.get("wheelRR.ndSlip", "0"))

        load_fl = _safe_float(row.get("wheelFL.load", "0"))
        load_fr = _safe_float(row.get("wheelFR.load", "0"))
        load_rl = _safe_float(row.get("wheelRL.load", "0"))
        load_rr = _safe_float(row.get("wheelRR.load", "0"))

        normalized_position = normalized_positions[index]
        sector_index = min(2, int(normalized_position * 3.0))

        samples.append(
            {
                "timestamp_utc": f"replay_frame_{frame_index}",
                "physics": {
                    "speed_kmh": round(speed_kmh, 3),
                    "brake": round(brake, 4),
                    "gas": round(gas, 4),
                    "steer_angle": round(steer, 4),
                    "rpms": round(rpm, 1),
                    "gear": gear,
                    "wheel_slip": [round(nd_fl, 5), round(nd_fr, 5), round(nd_rl, 5), round(nd_rr, 5)],
                    "wheel_load": [round(load_fl, 1), round(load_fr, 1), round(load_rl, 1), round(load_rr, 1)],
                    "number_of_tyres_out": 0,
                },
                "graphics": {
                    "normalized_car_position": round(normalized_position, 6),
                    "current_sector_index": sector_index,
                    "completed_laps": completed_laps,
                    "i_current_time": current_lap_time_ms,
                    "i_last_time": last_lap_time_ms,
                    "i_best_time": best_lap_time_ms,
                },
                "static": {
                    "car_model": car_model,
                    "track": track,
                },
            }
        )

    return samples


def _create_shared_log_from_replay(
    replay_path: str,
    driver_name: str,
    output_dir: str,
    max_samples: int,
) -> dict[str, Any]:
    parsed = parse_acreplay(replay_path=replay_path, output_dir=output_dir, driver_name=driver_name)
    if not parsed.get("ok"):
        raise RuntimeError(str(parsed.get("error", "Unable to parse replay")))
    if parsed.get("drivers_exported", 0) <= 0:
        raise ValueError("No driver data exported from replay")

    selected_driver = str(parsed.get("drivers", [""])[0])
    output_info = parsed.get("outputs", {}).get(selected_driver, {})
    csv_path = Path(str(output_info.get("csv_path", "")))
    if not csv_path.exists():
        raise FileNotFoundError(f"Replay CSV was not generated: {csv_path}")

    recording_interval_s = float(output_info.get("recording_interval", 0.033) or 0.033)

    rows = _read_replay_csv_rows(csv_path)
    if not rows:
        raise ValueError("Replay CSV has no telemetry rows")

    samples = _replay_rows_to_shared_samples(
        rows=rows,
        track=str(output_info.get("track", "")),
        car_model=str(output_info.get("car_id", "")),
        max_samples=max_samples,
        recording_interval_s=recording_interval_s,
    )
    if not samples:
        raise ValueError("Replay conversion produced no samples")

    replay_stem = Path(str(parsed.get("replay_path", replay_path))).stem
    raw_session = f"replay_{replay_stem}_{selected_driver}"[:90]
    session_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw_session).strip("_") or "replay_bridge"
    persisted = persist_shared_memory_samples(session_id=session_id, samples=samples, export_csv=False)

    return {
        "parsed": parsed,
        "selected_driver": selected_driver,
        "csv_path": str(csv_path),
        "recording_interval_s": recording_interval_s,
        "converted_sample_count": len(samples),
        "shared_memory_json_path": str(persisted.get("json_path", "")),
    }


@mcp.tool()
def list_setups(car: str = "", track: str = "", root_dir: str | None = None) -> dict[str, Any]:
    """List available setup files for a car and track combination. Filter by car/track name."""
    used_root = str(setup_root() if root_dir is None else Path(root_dir).resolve())
    items = io_list_setups(car=car, track=track, root_dir=root_dir)
    return {
        "count": len(items),
        "root_dir": used_root,
        "root_exists": Path(used_root).exists(),
        "items": items,
    }


@mcp.tool()
def read_setup(path: str) -> dict[str, Any]:
    """Read a complete setup file (.ini) and return all sections and values."""
    return io_read_setup(path)


@mcp.tool()
def find_base_setup(car: str, track: str = "", root_dir: str | None = None) -> dict[str, Any]:
    """Find a base/factory setup for a car and track combination to start from."""
    return io_find_base_setup(car=car, track=track, root_dir=root_dir)


@mcp.tool()
def suggest_changes(
    symptoms: str,
    track_conditions: str = "",
    setup: dict[str, dict[str, str]] | None = None,
    setup_path: str | None = None,
    llm_required: bool = True,
) -> dict[str, Any]:
    """Use LLM to suggest setup changes based on driving symptoms. Provide setup dict or setup_path."""
    if setup is None and not setup_path:
        raise ValueError("Provide setup data or setup_path")

    setup_data = setup if setup is not None else io_read_setup(setup_path or "")["sections"]
    return advisor_suggest_changes(
        setup=setup_data,
        symptoms=symptoms,
        track_conditions=track_conditions,
        use_llm=True,
        require_llm=llm_required,
    )


@mcp.tool()
def suggest_changes_heuristic(
    symptoms: str,
    track_conditions: str = "",
    setup: dict[str, dict[str, str]] | None = None,
    setup_path: str | None = None,
) -> dict[str, Any]:
    """Suggest setup changes using heuristics without LLM. Faster but less intelligent than LLM version."""
    if setup is None and not setup_path:
        raise ValueError("Provide setup data or setup_path")

    setup_data = setup if setup is not None else io_read_setup(setup_path or "")["sections"]
    return advisor_suggest_changes_heuristic(
        setup=setup_data,
        symptoms=symptoms,
        track_conditions=track_conditions,
    )


@mcp.tool()
def apply_changes(
    path: str,
    changes: list[dict[str, Any]],
    dry_run: bool = True,
    confirm: bool = False,
    create_backup: bool = True,
    save_as_new_version: bool = True,
) -> dict[str, Any]:
    """Apply setup changes to a file. Set dry_run=false and confirm=true to write to disk."""
    if not dry_run and not confirm:
        raise ValueError("Set confirm=true to write changes")

    return io_apply_changes(
        path=path,
        changes=changes,
        dry_run=dry_run,
        create_backup=create_backup,
        save_as_new_version=save_as_new_version,
    )


@mcp.tool()
def compare_setups(base: str, candidate: str) -> dict[str, Any]:
    """Compare two setup files and extract all differences between them."""
    return io_compare_setups(base_path=base, candidate_path=candidate)


@mcp.tool()
def record_session(
    driver: str,
    car: str,
    track: str,
    symptoms: str,
    track_conditions: str = "",
    lap_time_seconds: float | None = None,
    notes: str = "",
) -> dict[str, Any]:
    """Register a session with symptoms before recording telemetry in AC. Initiates shared-memory capture."""
    return record_session_context(
        driver=driver,
        car=car,
        track=track,
        symptoms=symptoms,
        track_conditions=track_conditions,
        lap_time_seconds=lap_time_seconds,
        notes=notes,
    )


@mcp.tool()
def list_sessions(limit: int = 20) -> dict[str, Any]:
    """List recorded sessions with metadata (driver, car, track, symptoms)."""
    return list_session_context(limit=limit)


@mcp.tool()
def list_telemetry_simulators() -> dict[str, Any]:
    """List telemetry simulators supported by this MCP and current default selection."""
    return shm_list_supported_simulators()


@mcp.tool()
def get_telemetry_simulator_capabilities(simulator: str = "") -> dict[str, Any]:
    """Describe telemetry/replay capabilities for a selected simulator (AC or iRacing)."""
    try:
        return {
            "ok": True,
            **shm_get_telemetry_capabilities(simulator=simulator),
        }
    except Exception as exc:
        return {
            "ok": False,
            "simulator": simulator,
            "error": str(exc),
        }


@mcp.tool()
def get_iracing_replay_state() -> dict[str, Any]:
    """Get current iRacing replay state (frame, session time, playback speed, paused/active flags)."""
    try:
        return {
            "ok": True,
            "state": shm_get_iracing_replay_state(),
            "error": "",
        }
    except Exception as exc:
        return {
            "ok": False,
            "state": {},
            "error": str(exc),
        }


@mcp.tool()
def set_iracing_replay_play_speed(speed: int = 1, slow_motion: bool = False) -> dict[str, Any]:
    """Set iRacing replay playback speed. Use speed=0 to pause, 1 for normal, up to 16."""
    try:
        result = shm_iracing_replay_set_play_speed(speed=speed, slow_motion=slow_motion)
        return {
            "ok": True,
            "result": result,
            "error": "",
        }
    except Exception as exc:
        return {
            "ok": False,
            "result": {},
            "error": str(exc),
        }


@mcp.tool()
def pause_iracing_replay() -> dict[str, Any]:
    """Pause iRacing replay playback."""
    try:
        result = shm_iracing_replay_pause()
        return {
            "ok": True,
            "result": result,
            "error": "",
        }
    except Exception as exc:
        return {
            "ok": False,
            "result": {},
            "error": str(exc),
        }


@mcp.tool()
def search_iracing_replay(mode: str = "next_lap") -> dict[str, Any]:
    """Search replay timeline in iRacing (next_lap, prev_lap, next_incident, to_start, etc.)."""
    try:
        result = shm_iracing_replay_search(mode=mode)
        return {
            "ok": True,
            "result": result,
            "error": "",
        }
    except Exception as exc:
        return {
            "ok": False,
            "result": {},
            "error": str(exc),
        }


@mcp.tool()
def seek_iracing_replay_frame(frame_num: int, pos_mode: str = "current") -> dict[str, Any]:
    """Seek iRacing replay by frame number (relative to begin/current/end)."""
    try:
        result = shm_iracing_replay_seek_frame(frame_num=frame_num, pos_mode=pos_mode)
        return {
            "ok": True,
            "result": result,
            "error": "",
        }
    except Exception as exc:
        return {
            "ok": False,
            "result": {},
            "error": str(exc),
        }


@mcp.tool()
def seek_iracing_replay_time(session_num: int, session_time_ms: int) -> dict[str, Any]:
    """Seek iRacing replay by session number and session time in milliseconds."""
    try:
        result = shm_iracing_replay_seek_session_time(
            session_num=session_num,
            session_time_ms=session_time_ms,
        )
        return {
            "ok": True,
            "result": result,
            "error": "",
        }
    except Exception as exc:
        return {
            "ok": False,
            "result": {},
            "error": str(exc),
        }


@mcp.tool()
def iracing_replay_to_shared_memory_json(
    replay_label: str = "",
    sample_count: int = 4000,
    interval_ms: int = 33,
    export_csv: bool = False,
    auto_pause_after_capture: bool = True,
) -> dict[str, Any]:
    """Capture telemetry from currently open iRacing replay into shared-memory JSON format."""
    try:
        bridge = shm_capture_iracing_replay_json(
            replay_label=replay_label,
            sample_count=sample_count,
            interval_ms=interval_ms,
            export_csv=export_csv,
            auto_pause_after_capture=auto_pause_after_capture,
        )
        return {
            "ok": True,
            "simulator": "iracing",
            "shared_memory_json_path": bridge.get("json_path", ""),
            "csv_path": bridge.get("csv_path", ""),
            "sample_count": bridge.get("sample_count", 0),
            "requested_sample_count": bridge.get("requested_sample_count", 0),
            "interval_ms": bridge.get("interval_ms", interval_ms),
            "before": bridge.get("before", {}),
            "after": bridge.get("after", {}),
            "error": "",
        }
    except Exception as exc:
        return {
            "ok": False,
            "simulator": "iracing",
            "shared_memory_json_path": "",
            "csv_path": "",
            "sample_count": 0,
            "requested_sample_count": 0,
            "interval_ms": interval_ms,
            "before": {},
            "after": {},
            "error": str(exc),
        }


@mcp.tool()
def compare_iracing_replay_vs_stint(
    stint_path: str,
    replay_label: str = "",
    sample_count: int = 4000,
    interval_ms: int = 33,
    bins: int = 120,
    objective: str = "lap_time",
    auto_pause_after_capture: bool = True,
) -> dict[str, Any]:
    """One-shot: capture current iRacing replay telemetry and compare against your stint JSON.

    BASE (reference) = captured iRacing replay segment
    CANDIDATE (test) = your shared-memory stint path
    """
    try:
        bridge = shm_capture_iracing_replay_json(
            replay_label=replay_label,
            sample_count=sample_count,
            interval_ms=interval_ms,
            export_csv=False,
            auto_pause_after_capture=auto_pause_after_capture,
        )
        replay_json_path = str(bridge.get("json_path", ""))
        comparison = compare_shm_stints(
            base_path=replay_json_path,
            candidate_path=stint_path,
            bins=bins,
            objective=objective,
        )
        return {
            "ok": bool(comparison.get("ok", False)),
            "simulator": "iracing",
            "replay_json_path": replay_json_path,
            "captured_replay_samples": int(bridge.get("sample_count", 0)),
            "comparison": comparison,
            "bridge": bridge,
            "error": "",
        }
    except Exception as exc:
        return {
            "ok": False,
            "simulator": "iracing",
            "replay_json_path": "",
            "captured_replay_samples": 0,
            "comparison": {},
            "bridge": {},
            "error": str(exc),
        }


@mcp.tool()
def capture_shared_memory_snapshot(simulator: str = "") -> dict[str, Any]:
    """Capture a single frame snapshot of live telemetry (Assetto Corsa or iRacing)."""
    try:
        return {
            "available": True,
            "snapshot": shm_capture_snapshot(simulator=simulator),
            "error": "",
        }
    except Exception as exc:
        return {
            "available": False,
            "snapshot": {},
            "error": str(exc),
        }


@mcp.tool()
def record_shared_memory_stint(
    session_id: str,
    sample_count: int = 30,
    interval_ms: int = 100,
    export_csv: bool = True,
    simulator: str = "",
) -> dict[str, Any]:
    """Record a short stint of shared-memory telemetry (blocking). Duration ≈ (sample_count * interval_ms) ms."""
    try:
        data = shm_record_stint(
            session_id=session_id,
            sample_count=sample_count,
            interval_ms=interval_ms,
            export_csv=export_csv,
            simulator=simulator,
        )
        notice = ""
        if data.get("notice_start") and data.get("notice_end"):
            notice = f"{data['notice_start']} | {data['notice_end']}"
        return {
            "saved": True,
            "notice": notice,
            "data": data,
            "error": "",
        }
    except Exception as exc:
        return {
            "saved": False,
            "notice": "",
            "data": {},
            "error": str(exc),
        }


@mcp.tool()
def start_shared_memory_capture(
    session_id: str,
    sample_count: int = 30,
    interval_ms: int = 100,
    export_csv: bool = True,
    simulator: str = "",
) -> dict[str, Any]:
    """Start an asynchronous shared-memory capture. Returns capture_id for monitoring/stopping."""
    try:
        data = shm_start_stint(
            session_id=session_id,
            sample_count=sample_count,
            interval_ms=interval_ms,
            export_csv=export_csv,
            simulator=simulator,
        )
        return {
            "started": True,
            "notice": str(data.get("notice", "")),
            "data": data,
            "error": "",
        }
    except Exception as exc:
        return {
            "started": False,
            "notice": "",
            "data": {},
            "error": str(exc),
        }


@mcp.tool()
def get_shared_memory_capture_status(capture_id: str) -> dict[str, Any]:
    """Check status of an ongoing shared-memory capture (samples collected, progress)."""
    return shm_get_stint_status(capture_id=capture_id)


@mcp.tool()
def stop_shared_memory_capture(capture_id: str) -> dict[str, Any]:
    """Stop an ongoing capture and return the final JSON path and sample count."""
    return shm_stop_stint(capture_id=capture_id)


@mcp.tool()
def analyze_shared_memory_track(
    path: str = "",
    bins: int = 40,
) -> dict[str, Any]:
    """Analyze speed/braking/acceleration by track zones. Understand where you lose time on track."""
    return analyze_shared_memory_track_map(path=path, bins=bins)


@mcp.tool()
def analyze_shared_memory_corner_limits(
    path: str = "",
    bins: int = 120,
) -> dict[str, Any]:
    """Analyze track-limit violations (over_limit_pct, severity). Identify where you exceed track boundaries."""
    return analyze_corner_limits_map(path=path, bins=bins)


@mcp.tool()
def coach_shared_memory_corner_limits(
    path: str = "",
    bins: int = 120,
    top_n: int = 5,
) -> dict[str, Any]:
    """Coach: Prioritize top-N corners with most track-limit violations. Focus on critical areas first."""
    return coach_corner_limits(path=path, bins=bins, top_n=top_n)


@mcp.tool()
def compare_shared_memory_stints(
    base_path: str,
    candidate_path: str,
    bins: int = 120,
    objective: str = "lap_time",
) -> dict[str, Any]:
    """Compare two shared-memory JSON stints or converted replays.
    
    BASE (reference) = faster/better driving
    CANDIDATE (test) = what you're comparing against BASE
    
    USE CASE 1 - Compare your stints:
    - base_path = your best stint
    - candidate_path = newer stint to improve on
    
    USE CASE 2 - Compare vs replay driver (WORKFLOW STEP 3):
    - base_path = replay converted to JSON (from replay_to_shared_memory_json)
    - candidate_path = your recorded stint
    
    Returns: lap_time delta, sector deltas, corner deltas (speed, brake, gas, wheel_slip, impact_score).
    """
    return compare_shm_stints(
        base_path=base_path,
        candidate_path=candidate_path,
        bins=bins,
        objective=objective,
    )


@mcp.tool()
def list_shared_memory_sessions(limit: int = 20) -> dict[str, Any]:
    """List saved shared-memory JSON stint files (telemetry recordings)."""
    return list_shared_memory_logs(limit=limit)


@mcp.tool()
def read_shared_memory_session(path: str = "", max_samples: int = 0) -> dict[str, Any]:
    """Read raw contents of a shared-memory JSON stint file (telemetry data)."""
    return shm_read_log(path=path, max_samples=max_samples)


@mcp.tool()
def search_references(
    car: str,
    track: str,
    symptom: str = "",
    max_results: int = 5,
    provider: str = "auto",
) -> dict[str, Any]:
    """Search for online references (setups, guides, articles) for a car+track+symptom combination."""
    return refs_search_references(
        car=car,
        track=track,
        symptom=symptom,
        max_results=max_results,
        provider=provider,
    )


@mcp.tool()
def search_base_setups(
    car: str,
    track: str,
    max_results: int = 5,
    provider: str = "auto",
) -> dict[str, Any]:
    """Search for recommended base/factory setups online for a car and track."""
    return refs_search_base_setups(
        car=car,
        track=track,
        max_results=max_results,
        provider=provider,
    )


@mcp.tool()
def get_circuit_info(
    track: str,
    max_results: int = 5,
    provider: str = "auto",
) -> dict[str, Any]:
    """Get circuit information (length, corners, elevation, weather trends, etc.) for a track."""
    return refs_get_circuit_info(
        track=track,
        max_results=max_results,
        provider=provider,
    )


@mcp.tool()
def fetch_reference(url: str, max_chars: int = 7000) -> dict[str, Any]:
    """Download and extract content from a URL (article, guide, reference page)."""
    return refs_fetch_reference(url=url, max_chars=max_chars)


@mcp.tool()
def list_replays(
    replay_root_dir: str = "",
    car: str = "",
    track: str = "",
    category: str = "",
    path_contains: str = "",
    sort_by: str = "timestamp_desc",
    limit: int = 50,
) -> dict[str, Any]:
    """[DISCOVERY] List available .acreplay files on disk. Filter by car, track, category, or path.
    
    WORKFLOW START:
    1. list_replays(car='tatuusfa1', track='vallelunga')  ← Find a replay
    2. list_replay_drivers(replay_path)                    ← See drivers in it
    3. replay_to_shared_memory_json(...)                   ← Convert driver
    4. compare_replay_vs_stint(...)                        ← Compare vs your stint
    """
    root = Path(replay_root_dir).resolve() if replay_root_dir else replay_root()
    if not root.exists():
        return {
            "count": 0,
            "root_dir": str(root),
            "root_exists": False,
            "sort_by": sort_by,
            "items": [],
        }

    items: list[dict[str, Any]] = []
    for replay_path in root.rglob("*.acreplay"):
        timestamp = _parse_timestamp_from_name(replay_path.stem)
        token_meta = _extract_replay_tokens(replay_path.name)

        relative_path = replay_path.relative_to(root).as_posix()
        candidate_text = " ".join(
            [
                replay_path.name,
                relative_path,
                token_meta["car_guess"],
                token_meta["track_guess"],
                token_meta["category_guess"],
            ]
        )

        if not _matches_filter(token_meta["car_guess"] + " " + candidate_text, car):
            continue
        if not _matches_filter(token_meta["track_guess"] + " " + candidate_text, track):
            continue
        if not _matches_filter(token_meta["category_guess"] + " " + candidate_text, category):
            continue
        if not _matches_filter(candidate_text, path_contains):
            continue

        stat = replay_path.stat()
        modified_at = datetime.fromtimestamp(stat.st_mtime, UTC)
        items.append(
            {
                "name": replay_path.name,
                "path": relative_path,
                "absolute_path": str(replay_path),
                "size_bytes": stat.st_size,
                "modified_at_utc": modified_at.isoformat(),
                "timestamp_guess_utc": timestamp.isoformat() if timestamp else "",
                "car_guess": token_meta["car_guess"],
                "track_guess": token_meta["track_guess"],
                "category_guess": token_meta["category_guess"],
            }
        )

    normalized_sort = sort_by.strip().lower()
    if normalized_sort == "timestamp_asc":
        items.sort(key=lambda i: i["timestamp_guess_utc"] or i["modified_at_utc"])
    elif normalized_sort == "modified_desc":
        items.sort(key=lambda i: i["modified_at_utc"], reverse=True)
    elif normalized_sort == "modified_asc":
        items.sort(key=lambda i: i["modified_at_utc"])
    elif normalized_sort == "name_desc":
        items.sort(key=lambda i: i["name"].lower(), reverse=True)
    elif normalized_sort == "name_asc":
        items.sort(key=lambda i: i["name"].lower())
    else:
        items.sort(key=lambda i: i["timestamp_guess_utc"] or i["modified_at_utc"], reverse=True)
        normalized_sort = "timestamp_desc"

    safe_limit = max(1, min(int(limit), 500))
    limited = items[:safe_limit]
    return {
        "count": len(limited),
        "total_found": len(items),
        "limit": safe_limit,
        "root_dir": str(root),
        "root_exists": True,
        "sort_by": normalized_sort,
        "items": limited,
    }


@mcp.tool()
def list_replay_drivers(replay_path: str) -> dict[str, Any]:
    """[REPLAY WORKFLOW STEP 1] List all drivers in a replay file.
    
    Returns: drivers[], track, num_cars, num_frames, recording_interval.
    Use driver_name from this result with replay_to_shared_memory_json or compare_replay_vs_stint.
    
    WORKFLOW:
    1. list_replay_drivers(replay_path)  ← You are here
    2. replay_to_shared_memory_json(..., driver_name=<from_step1>)
    3. compare_replay_vs_stint(...) or compare_shared_memory_stints(...)
    """
    try:
        resolved = resolve_replay_path(replay_path)
        parser = ACReplayParser(str(resolved))
        info = parser.inspect_replay()
        return {
            "ok": True,
            "replay_path": str(resolved),
            "summary": {
                "track": info.get("track", ""),
                "track_config": info.get("track_config", ""),
                "num_cars": info.get("num_cars", 0),
                "num_frames": info.get("num_frames", 0),
                "recording_interval": info.get("recording_interval", 0.0),
            },
            "drivers": info.get("drivers", []),
            "error": "",
        }
    except Exception as exc:
        return {
            "ok": False,
            "replay_path": replay_path,
            "summary": {},
            "drivers": [],
            "error": str(exc),
        }


@mcp.tool()
def parse_acreplay(
    replay_path: str,
    output_dir: str = "",
    driver_name: str = "",
) -> dict[str, Any]:
    """[ADVANCED] Export replay to raw CSV files per driver. For custom analysis or debugging.
    
    Usually NOT needed. Use replay_to_shared_memory_json instead for standard comparisons.
    """
    try:
        resolved_replay = resolve_replay_path(replay_path)
        resolved_output = output_dir
        if output_dir:
            out_path = Path(output_dir)
            if not out_path.is_absolute():
                out_path = replay_root() / out_path
            resolved_output = str(out_path.resolve())

        parser = ACReplayParser(str(resolved_replay))
        parsed = parser.parse_replay(output_path=resolved_output, target_driver_name=driver_name)
        drivers = list(parsed.keys())
        return {
            "ok": True,
            "replay_path": str(resolved_replay),
            "driver_filter": driver_name,
            "drivers_exported": len(drivers),
            "drivers": drivers,
            "outputs": parsed,
            "error": "",
        }
    except Exception as exc:
        return {
            "ok": False,
            "replay_path": replay_path,
            "driver_filter": driver_name,
            "drivers_exported": 0,
            "drivers": [],
            "outputs": {},
            "error": str(exc),
        }


@mcp.tool()
def analyze_replay_corner_limits(
    replay_path: str,
    driver_name: str = "",
    output_dir: str = "parsed_csv",
    bins: int = 120,
    max_samples: int = 4000,
) -> dict[str, Any]:
    """[ADVANCED - NOT RECOMMENDED] Analyze track-limit violations from a replay driver.
    
    WARNING: Replay data does NOT include off-track info (number_of_tyres_out=0 always).
    All metrics will show 0% — this tool is not useful.
    
    Prefer: Use compare_replay_vs_stint to compare speed/brake/gas deltas instead.
    """
    try:
        bridge = _create_shared_log_from_replay(
            replay_path=replay_path,
            driver_name=driver_name,
            output_dir=output_dir,
            max_samples=max_samples,
        )
        analysis = analyze_corner_limits_map(path=bridge["shared_memory_json_path"], bins=bins)
        return {
            "ok": bool(analysis.get("ok", False)),
            "bridge": bridge,
            "analysis": analysis,
            "error": "",
        }
    except Exception as exc:
        return {
            "ok": False,
            "bridge": {},
            "analysis": {},
            "error": str(exc),
        }


@mcp.tool()
def coach_replay_corner_limits(
    replay_path: str,
    driver_name: str = "",
    output_dir: str = "parsed_csv",
    bins: int = 120,
    top_n: int = 5,
    max_samples: int = 4000,
) -> dict[str, Any]:
    """[ADVANCED - NOT RECOMMENDED] Get coaching from a replay driver on track limits.
    
    WARNING: Replay data does NOT include off-track info (number_of_tyres_out=0 always).
    Coaching on track limits will be empty/meaningless.
    
    Prefer: Use compare_replay_vs_stint to compare corner speed and technique instead.
    """
    try:
        bridge = _create_shared_log_from_replay(
            replay_path=replay_path,
            driver_name=driver_name,
            output_dir=output_dir,
            max_samples=max_samples,
        )
        coaching = coach_corner_limits(path=bridge["shared_memory_json_path"], bins=bins, top_n=top_n)
        return {
            "ok": bool(coaching.get("ok", False)),
            "bridge": bridge,
            "coaching": coaching,
            "error": "",
        }
    except Exception as exc:
        return {
            "ok": False,
            "bridge": {},
            "coaching": {},
            "error": str(exc),
        }


@mcp.tool()
def replay_to_shared_memory_json(
    replay_path: str,
    driver_name: str = "",
    output_dir: str = "parsed_csv",
    max_samples: int = 4000,
) -> dict[str, Any]:
    """[REPLAY WORKFLOW STEP 2] Convert a replay driver to shared-memory JSON format.
    
    Transforms replay telemetry data into the same format as recorded stints, enabling direct comparison.
    Uses velocity-integrated positions for accurate normalized_car_position.
    
    WARNING: Replay data does NOT include off-track info (number_of_tyres_out=0 always).
    Use for comparing: speed, brake, gas, wheel_slip deltas. Track-limit comparisons are NOT meaningful.
    
    Returns: shared_memory_json_path, recording_interval_s, converted_sample_count.
    
    WORKFLOW:
    1. list_replay_drivers(replay_path)
    2. replay_to_shared_memory_json(..., driver_name=<from_step1>)  ← You are here
    3. compare_replay_vs_stint(...) or compare_shared_memory_stints(base_path=<from_this_step>, ...)
    """
    try:
        bridge = _create_shared_log_from_replay(
            replay_path=replay_path,
            driver_name=driver_name,
            output_dir=output_dir,
            max_samples=max_samples,
        )
        return {
            "ok": True,
            "selected_driver": bridge["selected_driver"],
            "recording_interval_s": bridge["recording_interval_s"],
            "converted_sample_count": bridge["converted_sample_count"],
            "shared_memory_json_path": bridge["shared_memory_json_path"],
            "csv_path": bridge["csv_path"],
            "error": "",
        }
    except Exception as exc:
        return {
            "ok": False,
            "selected_driver": "",
            "recording_interval_s": 0.0,
            "converted_sample_count": 0,
            "shared_memory_json_path": "",
            "csv_path": "",
            "error": str(exc),
        }


@mcp.tool()
def compare_replay_vs_stint(
    replay_path: str,
    stint_path: str = "",
    replay_driver_name: str = "",
    output_dir: str = "parsed_csv",
    bins: int = 120,
    objective: str = "lap_time",
    max_samples: int = 4000,
) -> dict[str, Any]:
    """[REPLAY WORKFLOW - ONE-SHOT ALTERNATIVE] Compare replay driver vs your stint in one call.

    RECOMMENDED WORKFLOW (explicit steps):
    1. list_replay_drivers(replay_path)
    2. replay_to_shared_memory_json(..., driver_name=<from_step1>)
    3. compare_shared_memory_stints(base_path=<json_from_step2>, candidate_path=<your_stint>)

    OR USE THIS TOOL (all-in-one):
    - compare_replay_vs_stint(replay_path, replay_driver_name, stint_path)

    Returns: comparison with corner deltas (speed, brake, gas, wheel_slip, impact_score).
    
    BASE (reference) = Replay driver
    CANDIDATE (test) = Your captured stint
    
    Valid deltas: speed_kmh, avg_brake, avg_gas, wheel_slip per corner.
    INVALID deltas: over_limit_pct (replay has no off-track data, always 0).
    """
    try:
        bridge = _create_shared_log_from_replay(
            replay_path=replay_path,
            driver_name=replay_driver_name,
            output_dir=output_dir,
            max_samples=max_samples,
        )
        replay_json_path = bridge["shared_memory_json_path"]
        comparison = compare_shm_stints(
            base_path=replay_json_path,
            candidate_path=stint_path,
            bins=bins,
            objective=objective,
        )
        return {
            "ok": bool(comparison.get("ok", False)),
            "replay_driver": bridge["selected_driver"],
            "replay_json_path": replay_json_path,
            "recording_interval_s": bridge["recording_interval_s"],
            "converted_replay_samples": bridge["converted_sample_count"],
            "comparison": comparison,
            "error": "",
        }
    except Exception as exc:
        return {
            "ok": False,
            "replay_driver": "",
            "replay_json_path": "",
            "recording_interval_s": 0.0,
            "converted_replay_samples": 0,
            "comparison": {},
            "error": str(exc),
        }


@mcp.tool()
def start_from_base(
    car: str,
    track: str,
    symptoms: str,
    track_conditions: str = "",
    root_dir: str | None = None,
    dry_run: bool = True,
    llm_required: bool = True,
    confirm: bool = False,
    create_backup: bool = True,
    save_as_new_version: bool = True,
) -> dict[str, Any]:
    """Integrated pipeline: Find base setup → Get LLM suggestions → Optionally apply changes (if confirm=true)."""
    return start_from_base_pipeline(
        car=car,
        track=track,
        symptoms=symptoms,
        track_conditions=track_conditions,
        root_dir=root_dir,
        dry_run=dry_run,
        llm_required=llm_required,
        confirm=confirm,
        create_backup=create_backup,
        save_as_new_version=save_as_new_version,
    )


def run() -> None:
    mcp.run()
