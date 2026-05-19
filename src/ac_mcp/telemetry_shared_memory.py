from __future__ import annotations

import csv
import ctypes
import json
import mmap
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ac_mcp.config import session_log_root


_CAPTURE_LOCK = threading.Lock()
_CAPTURE_JOBS: dict[str, dict[str, Any]] = {}


class ACPhysics(ctypes.Structure):
    _fields_ = [
        ("packet_id", ctypes.c_int),
        ("gas", ctypes.c_float),
        ("brake", ctypes.c_float),
        ("fuel", ctypes.c_float),
        ("gear", ctypes.c_int),
        ("rpms", ctypes.c_int),
        ("steer_angle", ctypes.c_float),
        ("speed_kmh", ctypes.c_float),
        ("velocity", ctypes.c_float * 3),
        ("acc_g", ctypes.c_float * 3),
        ("wheel_slip", ctypes.c_float * 4),
        ("wheel_load", ctypes.c_float * 4),
        ("wheel_pressure", ctypes.c_float * 4),
        ("wheel_angular_speed", ctypes.c_float * 4),
        ("tyre_wear", ctypes.c_float * 4),
        ("tyre_dirty_level", ctypes.c_float * 4),
        ("tyre_core_temp", ctypes.c_float * 4),
        ("camber_rad", ctypes.c_float * 4),
        ("suspension_travel", ctypes.c_float * 4),
        ("drs", ctypes.c_float),
        ("tc", ctypes.c_float),
        ("heading", ctypes.c_float),
        ("pitch", ctypes.c_float),
        ("roll", ctypes.c_float),
        ("cg_height", ctypes.c_float),
        ("car_damage", ctypes.c_float * 5),
        ("number_of_tyres_out", ctypes.c_int),
        ("pit_limiter_on", ctypes.c_int),
        ("abs", ctypes.c_float),
        ("kers_charge", ctypes.c_float),
        ("kers_input", ctypes.c_float),
        ("auto_shifter_on", ctypes.c_int),
        ("ride_height", ctypes.c_float * 2),
        ("turbo_boost", ctypes.c_float),
        ("ballast", ctypes.c_float),
        ("air_density", ctypes.c_float),
        ("air_temp", ctypes.c_float),
        ("road_temp", ctypes.c_float),
    ]


class ACGraphics(ctypes.Structure):
    _fields_ = [
        ("packet_id", ctypes.c_int),
        ("status", ctypes.c_int),
        ("session", ctypes.c_int),
        ("current_time", ctypes.c_wchar * 15),
        ("last_time", ctypes.c_wchar * 15),
        ("best_time", ctypes.c_wchar * 15),
        ("split", ctypes.c_wchar * 15),
        ("completed_laps", ctypes.c_int),
        ("position", ctypes.c_int),
        ("i_current_time", ctypes.c_int),
        ("i_last_time", ctypes.c_int),
        ("i_best_time", ctypes.c_int),
        ("session_time_left", ctypes.c_float),
        ("distance_traveled", ctypes.c_float),
        ("is_in_pit", ctypes.c_int),
        ("current_sector_index", ctypes.c_int),
        ("last_sector_time", ctypes.c_int),
        ("number_of_laps", ctypes.c_int),
        ("tyre_compound", ctypes.c_wchar * 33),
        ("replay_time_multiplier", ctypes.c_float),
        ("normalized_car_position", ctypes.c_float),
        ("car_coordinates", ctypes.c_float * 3),
        ("penalty_time", ctypes.c_float),
        ("flag", ctypes.c_int),
        ("ideal_line_on", ctypes.c_int),
        ("is_in_pit_lane", ctypes.c_int),
        ("surface_grip", ctypes.c_float),
    ]


class ACStatic(ctypes.Structure):
    _fields_ = [
        ("sm_version", ctypes.c_wchar * 15),
        ("ac_version", ctypes.c_wchar * 15),
        ("number_of_sessions", ctypes.c_int),
        ("num_cars", ctypes.c_int),
        ("car_model", ctypes.c_wchar * 33),
        ("track", ctypes.c_wchar * 33),
        ("player_name", ctypes.c_wchar * 33),
        ("player_surname", ctypes.c_wchar * 33),
        ("player_nick", ctypes.c_wchar * 33),
    ]


def _clean_wchar(value: Any) -> str:
    text = str(value)
    return text.split("\x00", maxsplit=1)[0].strip()


def _read_struct(tag_name: str, cls: type[ctypes.Structure]) -> Any:
    size = ctypes.sizeof(cls)
    with mmap.mmap(-1, size, tagname=tag_name, access=mmap.ACCESS_READ) as mm:
        raw = mm.read(size)
    return cls.from_buffer_copy(raw)


def _now_utc_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _avg(values: Any) -> float:
    if not isinstance(values, (list, tuple)):
        return 0.0
    nums: list[float] = []
    for value in values:
        try:
            nums.append(float(value))
        except (TypeError, ValueError):
            continue
    if not nums:
        return 0.0
    return sum(nums) / len(nums)


def _max(values: Any) -> float:
    if not isinstance(values, (list, tuple)):
        return 0.0
    nums: list[float] = []
    for value in values:
        try:
            nums.append(float(value))
        except (TypeError, ValueError):
            continue
    if not nums:
        return 0.0
    return max(nums)


def _wheel_metric(values: Any, index: int) -> float:
    if not isinstance(values, (list, tuple)):
        return 0.0
    if index < 0 or index >= len(values):
        return 0.0
    try:
        return float(values[index])
    except (TypeError, ValueError):
        return 0.0


def _public_capture_view(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "capture_id": str(job.get("capture_id", "")),
        "session_id": str(job.get("session_id", "")),
        "status": str(job.get("status", "unknown")),
        "started_at_utc": str(job.get("started_at_utc", "")),
        "finished_at_utc": str(job.get("finished_at_utc", "")),
        "duration_seconds": float(job.get("duration_seconds", 0.0) or 0.0),
        "requested_sample_count": int(job.get("requested_sample_count", 0) or 0),
        "samples_collected": int(job.get("samples_collected", 0) or 0),
        "interval_ms": int(job.get("interval_ms", 0) or 0),
        "notice_start": str(job.get("notice_start", "")),
        "notice_end": str(job.get("notice_end", "")),
        "result": job.get("result", {}),
        "error": str(job.get("error", "")),
    }


def capture_shared_memory_snapshot() -> dict[str, Any]:
    try:
        physics = _read_struct("acpmf_physics", ACPhysics)
        graphics = _read_struct("acpmf_graphics", ACGraphics)
        static = _read_struct("acpmf_static", ACStatic)
    except Exception as exc:
        raise RuntimeError(
            "Shared memory unavailable. Make sure Assetto Corsa is running and shared memory is enabled."
        ) from exc

    return {
        "timestamp_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "physics": {
            "packet_id": int(physics.packet_id),
            "speed_kmh": round(float(physics.speed_kmh), 3),
            "rpms": int(physics.rpms),
            "gear": int(physics.gear),
            "gas": round(float(physics.gas), 4),
            "brake": round(float(physics.brake), 4),
            "fuel": round(float(physics.fuel), 3),
            "steer_angle": round(float(physics.steer_angle), 4),
            "velocity_xyz": [round(float(v), 4) for v in physics.velocity],
            "acc_g_xyz": [round(float(v), 4) for v in physics.acc_g],
            "wheel_slip": [round(float(v), 4) for v in physics.wheel_slip],
            "wheel_load": [round(float(v), 3) for v in physics.wheel_load],
            "wheel_pressure": [round(float(v), 3) for v in physics.wheel_pressure],
            "wheel_angular_speed": [round(float(v), 4) for v in physics.wheel_angular_speed],
            "tyre_wear": [round(float(v), 4) for v in physics.tyre_wear],
            "tyre_dirty_level": [round(float(v), 4) for v in physics.tyre_dirty_level],
            "number_of_tyres_out": int(physics.number_of_tyres_out),
            "camber_rad": [round(float(v), 6) for v in physics.camber_rad],
            "suspension_travel": [round(float(v), 5) for v in physics.suspension_travel],
            "drs": round(float(physics.drs), 4),
            "tc": round(float(physics.tc), 4),
            "abs": round(float(physics.abs), 4),
            "pit_limiter_on": bool(physics.pit_limiter_on),
            "kers_charge": round(float(physics.kers_charge), 4),
            "kers_input": round(float(physics.kers_input), 4),
            "auto_shifter_on": bool(physics.auto_shifter_on),
            "ride_height": [round(float(v), 5) for v in physics.ride_height],
            "turbo_boost": round(float(physics.turbo_boost), 4),
            "ballast": round(float(physics.ballast), 3),
            "air_density": round(float(physics.air_density), 5),
            "heading": round(float(physics.heading), 5),
            "pitch": round(float(physics.pitch), 5),
            "roll": round(float(physics.roll), 5),
            "cg_height": round(float(physics.cg_height), 5),
            "car_damage": [round(float(v), 4) for v in physics.car_damage],
            "air_temp_c": round(float(physics.air_temp), 3),
            "road_temp_c": round(float(physics.road_temp), 3),
            "tyre_core_temp_c": [round(float(v), 3) for v in physics.tyre_core_temp],
            "tyre_pressure": [round(float(v), 3) for v in physics.wheel_pressure],
            "avg_wheel_slip": round(_avg(physics.wheel_slip), 5),
            "max_wheel_slip": round(_max(physics.wheel_slip), 5),
            "avg_suspension_travel": round(_avg(physics.suspension_travel), 6),
            "avg_tyre_temp_c": round(_avg(physics.tyre_core_temp), 4),
            "avg_tyre_wear": round(_avg(physics.tyre_wear), 5),
        },
        "graphics": {
            "packet_id": int(graphics.packet_id),
            "status": int(graphics.status),
            "session": int(graphics.session),
            "current_time": _clean_wchar(graphics.current_time),
            "last_time": _clean_wchar(graphics.last_time),
            "best_time": _clean_wchar(graphics.best_time),
            "split": _clean_wchar(graphics.split),
            "completed_laps": int(graphics.completed_laps),
            "position": int(graphics.position),
            "i_current_time": int(graphics.i_current_time),
            "i_last_time": int(graphics.i_last_time),
            "i_best_time": int(graphics.i_best_time),
            "current_sector_index": int(graphics.current_sector_index),
            "last_sector_time": int(graphics.last_sector_time),
            "number_of_laps": int(graphics.number_of_laps),
            "tyre_compound": _clean_wchar(graphics.tyre_compound),
            "distance_traveled": round(float(graphics.distance_traveled), 3),
            "replay_time_multiplier": round(float(graphics.replay_time_multiplier), 3),
            "normalized_car_position": round(float(graphics.normalized_car_position), 6),
            "car_coordinates": [round(float(v), 3) for v in graphics.car_coordinates],
            "session_time_left": round(float(graphics.session_time_left), 3),
            "is_in_pit": bool(graphics.is_in_pit),
            "penalty_time": round(float(graphics.penalty_time), 4),
            "flag": int(graphics.flag),
            "ideal_line_on": bool(graphics.ideal_line_on),
            "is_in_pit_lane": bool(graphics.is_in_pit_lane),
            "surface_grip": round(float(graphics.surface_grip), 4),
        },
        "static": {
            "sm_version": _clean_wchar(static.sm_version),
            "ac_version": _clean_wchar(static.ac_version),
            "number_of_sessions": int(static.number_of_sessions),
            "num_cars": int(static.num_cars),
            "car_model": _clean_wchar(static.car_model),
            "track": _clean_wchar(static.track),
            "player_name": _clean_wchar(static.player_name),
            "player_surname": _clean_wchar(static.player_surname),
            "player_nick": _clean_wchar(static.player_nick),
        },
    }


def _shared_memory_root() -> Path:
    root = session_log_root() / "shared_memory"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _resolve_shared_memory_log_path(path: str) -> Path:
    root = _shared_memory_root()

    if path.strip():
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = root / candidate
        resolved = candidate.resolve()
        if not resolved.exists() or not resolved.is_file():
            raise FileNotFoundError(f"Shared-memory log not found: {resolved}")
        return resolved

    files = sorted(root.glob("*.json"), reverse=True)
    if not files:
        raise FileNotFoundError("No shared-memory logs found")
    return files[0]


def _load_shared_memory_log_payload(path: str) -> tuple[Path, dict[str, Any], list[dict[str, Any]]]:
    resolved = _resolve_shared_memory_log_path(path)
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    samples_raw = payload.get("samples", [])
    if not isinstance(samples_raw, list):
        raise ValueError("No samples in shared-memory log")

    samples: list[dict[str, Any]] = [item for item in samples_raw if isinstance(item, dict)]
    if not samples:
        raise ValueError("No samples in shared-memory log")
    return resolved, payload, samples


def _flatten_for_csv(snapshot: dict[str, Any]) -> dict[str, Any]:
    physics = snapshot.get("physics", {})
    graphics = snapshot.get("graphics", {})
    static = snapshot.get("static", {})

    return {
        "timestamp_utc": snapshot.get("timestamp_utc", ""),
        "car_model": static.get("car_model", ""),
        "track": static.get("track", ""),
        "session_status": graphics.get("status", ""),
        "session_type": graphics.get("session", ""),
        "speed_kmh": physics.get("speed_kmh", ""),
        "rpms": physics.get("rpms", ""),
        "gear": physics.get("gear", ""),
        "gas": physics.get("gas", ""),
        "brake": physics.get("brake", ""),
        "fuel": physics.get("fuel", ""),
        "steer_angle": physics.get("steer_angle", ""),
        "number_of_tyres_out": physics.get("number_of_tyres_out", ""),
        "pit_limiter_on": physics.get("pit_limiter_on", ""),
        "tc": physics.get("tc", ""),
        "abs": physics.get("abs", ""),
        "avg_wheel_slip": physics.get("avg_wheel_slip", round(_avg(physics.get("wheel_slip", [])), 5)),
        "max_wheel_slip": physics.get("max_wheel_slip", round(_max(physics.get("wheel_slip", [])), 5)),
        "avg_suspension_travel": physics.get("avg_suspension_travel", round(_avg(physics.get("suspension_travel", [])), 6)),
        "avg_tyre_temp_c": physics.get("avg_tyre_temp_c", round(_avg(physics.get("tyre_core_temp_c", [])), 4)),
        "avg_tyre_wear": physics.get("avg_tyre_wear", round(_avg(physics.get("tyre_wear", [])), 5)),
        "tyre_temp_lf_c": round(_wheel_metric(physics.get("tyre_core_temp_c", []), 0), 3),
        "tyre_temp_rf_c": round(_wheel_metric(physics.get("tyre_core_temp_c", []), 1), 3),
        "tyre_temp_lr_c": round(_wheel_metric(physics.get("tyre_core_temp_c", []), 2), 3),
        "tyre_temp_rr_c": round(_wheel_metric(physics.get("tyre_core_temp_c", []), 3), 3),
        "tyre_pressure_lf": round(_wheel_metric(physics.get("tyre_pressure", physics.get("wheel_pressure", [])), 0), 3),
        "tyre_pressure_rf": round(_wheel_metric(physics.get("tyre_pressure", physics.get("wheel_pressure", [])), 1), 3),
        "tyre_pressure_lr": round(_wheel_metric(physics.get("tyre_pressure", physics.get("wheel_pressure", [])), 2), 3),
        "tyre_pressure_rr": round(_wheel_metric(physics.get("tyre_pressure", physics.get("wheel_pressure", [])), 3), 3),
        "air_temp_c": physics.get("air_temp_c", ""),
        "road_temp_c": physics.get("road_temp_c", ""),
        "completed_laps": graphics.get("completed_laps", ""),
        "position": graphics.get("position", ""),
        "current_time": graphics.get("current_time", ""),
        "last_time": graphics.get("last_time", ""),
        "best_time": graphics.get("best_time", ""),
        "split": graphics.get("split", ""),
        "distance_traveled": graphics.get("distance_traveled", ""),
        "penalty_time": graphics.get("penalty_time", ""),
        "flag": graphics.get("flag", ""),
        "current_sector_index": graphics.get("current_sector_index", ""),
        "normalized_car_position": graphics.get("normalized_car_position", ""),
        "is_in_pit": graphics.get("is_in_pit", ""),
        "is_in_pit_lane": graphics.get("is_in_pit_lane", ""),
        "tyre_compound": graphics.get("tyre_compound", ""),
        "surface_grip": graphics.get("surface_grip", ""),
    }


def persist_shared_memory_samples(
    session_id: str,
    samples: list[dict[str, Any]],
    export_csv: bool = True,
) -> dict[str, Any]:
    root = _shared_memory_root()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    session_slug = "_".join(session_id.strip().split()) or "session"

    json_path = root / f"{stamp}_{session_slug}.json"
    payload = {
        "session_id": session_id,
        "created_at_utc": stamp,
        "sample_count": len(samples),
        "samples": samples,
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    csv_path = ""
    if export_csv:
        csv_file = root / f"{stamp}_{session_slug}.csv"
        rows = [_flatten_for_csv(sample) for sample in samples]
        fieldnames = list(rows[0].keys()) if rows else ["timestamp_utc"]
        with csv_file.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        csv_path = str(csv_file)

    return {
        "session_id": session_id,
        "sample_count": len(samples),
        "json_path": str(json_path),
        "csv_path": csv_path,
    }


def record_shared_memory_stint(
    session_id: str,
    sample_count: int = 30,
    interval_ms: int = 100,
    export_csv: bool = True,
) -> dict[str, Any]:
    count = max(1, min(sample_count, 5000))
    wait_seconds = max(0.01, interval_ms / 1000.0)
    started_at = datetime.now(UTC)
    started_at_utc = started_at.isoformat().replace("+00:00", "Z")

    samples: list[dict[str, Any]] = []
    for index in range(count):
        try:
            sample = capture_shared_memory_snapshot()
        except RuntimeError:
            if index == 0:
                raise
            break

        samples.append(sample)
        if index < count - 1:
            time.sleep(wait_seconds)

    finished_at = datetime.now(UTC)
    finished_at_utc = finished_at.isoformat().replace("+00:00", "Z")
    duration_seconds = round((finished_at - started_at).total_seconds(), 3)

    result = persist_shared_memory_samples(session_id=session_id, samples=samples, export_csv=export_csv)
    result["requested_sample_count"] = count
    result["interval_ms"] = int(interval_ms)
    result["started_at_utc"] = started_at_utc
    result["finished_at_utc"] = finished_at_utc
    result["duration_seconds"] = duration_seconds
    result["notice_start"] = f"AVISO: captura iniciada {started_at_utc}"
    result["notice_end"] = (
        "AVISO: captura finalizada "
        f"{finished_at_utc} ({len(samples)}/{count} muestras, {duration_seconds}s)"
    )
    return result


def start_shared_memory_stint(
    session_id: str,
    sample_count: int = 30,
    interval_ms: int = 100,
    export_csv: bool = True,
) -> dict[str, Any]:
    count = max(1, min(sample_count, 5000))
    wait_seconds = max(0.01, interval_ms / 1000.0)
    capture_id = uuid.uuid4().hex
    started_at_utc = _now_utc_iso()

    job: dict[str, Any] = {
        "capture_id": capture_id,
        "session_id": session_id,
        "status": "running",
        "started_at_utc": started_at_utc,
        "finished_at_utc": "",
        "duration_seconds": 0.0,
        "requested_sample_count": count,
        "samples_collected": 0,
        "interval_ms": int(interval_ms),
        "notice_start": f"AVISO: captura iniciada {started_at_utc}",
        "notice_end": "",
        "result": {},
        "error": "",
        "stop_event": threading.Event(),
        "thread": None,
    }

    def _worker() -> None:
        started_at = datetime.now(UTC)
        samples: list[dict[str, Any]] = []
        status = "completed"
        error = ""

        for index in range(count):
            with _CAPTURE_LOCK:
                stop_event = job["stop_event"]
            if stop_event.is_set():
                status = "stopped"
                break

            try:
                sample = capture_shared_memory_snapshot()
            except RuntimeError as exc:
                if index == 0:
                    status = "failed"
                    error = str(exc)
                    break
                status = "stopped"
                break

            samples.append(sample)
            with _CAPTURE_LOCK:
                job["samples_collected"] = len(samples)

            if index < count - 1:
                time.sleep(wait_seconds)

        result: dict[str, Any] = {}
        if status in {"completed", "stopped"}:
            try:
                result = persist_shared_memory_samples(
                    session_id=session_id,
                    samples=samples,
                    export_csv=export_csv,
                )
            except Exception as exc:  # pragma: no cover
                status = "failed"
                error = str(exc)

        finished_at = datetime.now(UTC)
        finished_at_utc = finished_at.isoformat().replace("+00:00", "Z")
        duration_seconds = round((finished_at - started_at).total_seconds(), 3)
        notice_end = (
            "AVISO: captura finalizada "
            f"{finished_at_utc} ({len(samples)}/{count} muestras, {duration_seconds}s)"
        )

        with _CAPTURE_LOCK:
            job["status"] = status
            job["error"] = error
            job["finished_at_utc"] = finished_at_utc
            job["duration_seconds"] = duration_seconds
            job["samples_collected"] = len(samples)
            job["notice_end"] = notice_end
            job["result"] = result

    thread = threading.Thread(target=_worker, name=f"ac-capture-{capture_id[:8]}", daemon=True)
    with _CAPTURE_LOCK:
        job["thread"] = thread
        _CAPTURE_JOBS[capture_id] = job
    thread.start()

    return {
        "started": True,
        "notice": job["notice_start"],
        **_public_capture_view(job),
    }


def get_shared_memory_stint_status(capture_id: str) -> dict[str, Any]:
    key = capture_id.strip()
    with _CAPTURE_LOCK:
        job = _CAPTURE_JOBS.get(key)
        if not job:
            return {
                "found": False,
                "capture_id": key,
                "error": "capture_id not found",
            }
        return {
            "found": True,
            **_public_capture_view(job),
        }


def stop_shared_memory_stint(capture_id: str) -> dict[str, Any]:
    key = capture_id.strip()
    with _CAPTURE_LOCK:
        job = _CAPTURE_JOBS.get(key)
        if not job:
            return {
                "found": False,
                "capture_id": key,
                "stopped": False,
                "error": "capture_id not found",
            }

        if str(job.get("status", "")) != "running":
            return {
                "found": True,
                "stopped": False,
                "message": f"capture already {job.get('status', 'unknown')}",
                **_public_capture_view(job),
            }

        stop_event = job["stop_event"]
        thread = job["thread"]
        stop_event.set()

    if isinstance(thread, threading.Thread):
        thread.join(timeout=3.0)

    with _CAPTURE_LOCK:
        updated = _CAPTURE_JOBS.get(key)
        if not updated:  # pragma: no cover
            return {
                "found": False,
                "capture_id": key,
                "stopped": False,
                "error": "capture disappeared",
            }
        return {
            "found": True,
            "stopped": str(updated.get("status", "")) in {"stopped", "completed", "failed"},
            **_public_capture_view(updated),
        }


def list_shared_memory_logs(limit: int = 20) -> dict[str, Any]:
    root = _shared_memory_root()
    files = sorted(root.glob("*.json"), reverse=True)[: max(1, limit)]
    return {
        "items": [
            {
                "path": str(file_path),
                "name": file_path.name,
                "modified_at": datetime.fromtimestamp(file_path.stat().st_mtime).isoformat(),
            }
            for file_path in files
        ]
    }


def read_shared_memory_log(path: str = "", max_samples: int = 0) -> dict[str, Any]:
    try:
        resolved, payload, samples = _load_shared_memory_log_payload(path)
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

    limit = int(max_samples)
    if limit > 0:
        selected = samples[:limit]
    else:
        selected = samples

    first_sample = selected[0] if selected else {}
    physics = first_sample.get("physics", {}) if isinstance(first_sample, dict) else {}
    graphics = first_sample.get("graphics", {}) if isinstance(first_sample, dict) else {}

    available_physics_keys = sorted(physics.keys()) if isinstance(physics, dict) else []
    available_graphics_keys = sorted(graphics.keys()) if isinstance(graphics, dict) else []

    return {
        "ok": True,
        "path": str(resolved),
        "session_id": str(payload.get("session_id", "")),
        "total_samples": len(samples),
        "returned_samples": len(selected),
        "max_samples": limit,
        "available_fields": {
            "physics": available_physics_keys,
            "graphics": available_graphics_keys,
        },
        "samples": selected,
    }
