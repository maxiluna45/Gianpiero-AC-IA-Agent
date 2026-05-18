from __future__ import annotations

import configparser
import json
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

    under_penalty = max(0.0, under - 82.0)
    traccion_risk = gas * over
    return round(
        (over * 1.55)
        + (severe * 2.25)
        + (under_penalty * 0.55)
        + (coverage * 0.25)
        + (steer * 12.0)
        + (traccion_risk * 0.15),
        3,
    )


def _wear_risk_level(corner: dict[str, Any]) -> str:
    over = _safe_float(corner.get("over_limit_pct", 0.0))
    severe = _safe_float(corner.get("severe_over_limit_pct", 0.0))
    gas = _safe_float(corner.get("avg_gas", 0.0))
    steer = _safe_float(corner.get("avg_abs_steer", 0.0))

    wear_load = (over * 0.8) + (severe * 2.2) + (gas * 18.0) + (steer * 28.0)
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
        {"count": 0.0, "sum_speed": 0.0, "sum_brake": 0.0, "sum_gas": 0.0, "sum_steer": 0.0}
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

        bucket = buckets[bucket_index]
        bucket["count"] += 1.0
        bucket["sum_speed"] += speed
        bucket["sum_brake"] += brake
        bucket["sum_gas"] += gas
        bucket["sum_steer"] += steer
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
        key=lambda row: (row["avg_gas"] * (1.0 - min(row["avg_speed_kmh"] / 250.0, 1.0)), row["sample_count"]),
        reverse=True,
    )[:5]

    lap_start = completed_laps[0] if completed_laps else 0
    lap_end = completed_laps[-1] if completed_laps else 0

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

        tyres_out_raw = physics.get("number_of_tyres_out")
        if tyres_out_raw is None:
            missing_tyres_out_count += 1
        tyres_out = max(0, min(4, _safe_int(tyres_out_raw)))

        current["sample_count"] += 1.0
        current["sum_speed"] += speed
        current["sum_brake"] += brake
        current["sum_gas"] += gas
        current["sum_steer"] += steer
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
                ),
            }
        )

    high_risk = sorted(
        [corner for corner in corners if int(corner.get("sample_count", 0)) > 0],
        key=lambda item: (float(item.get("over_limit_pct", 0.0)), float(item.get("severe_over_limit_pct", 0.0))),
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
        "priorities": priorities,
        "summary": analysis.get("summary", {}),
        "high_risk_corners": analysis.get("high_risk_corners", []),
        "underused_corners": analysis.get("underused_corners", []),
    }
