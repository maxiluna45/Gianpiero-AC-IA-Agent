from __future__ import annotations

import configparser
import math
import re
import shutil
import unicodedata
from copy import deepcopy
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from ac_mcp.config import resolve_setup_path, setup_root


def _new_parser() -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    return parser


def _as_number(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_like_reference(reference: str, value: float) -> str:
    number = _as_number(reference)
    if number is None:
        if math.isclose(value, round(value), abs_tol=1e-9):
            return str(int(round(value)))
        return f"{value:.3f}".rstrip("0").rstrip(".")

    if "." not in reference:
        return str(int(round(value)))

    decimals = len(reference.split(".", maxsplit=1)[1])
    return f"{value:.{decimals}f}"


def _field_name(section: str, key: str) -> str:
    key_name = key.upper().strip()
    if key_name == "VALUE":
        return section.upper().strip()
    return key_name


def _normalize_text(value: str) -> str:
    lowered = value.lower().strip()
    normalized = unicodedata.normalize("NFKD", lowered)
    ascii_only = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    clean = re.sub(r"[^a-z0-9]+", " ", ascii_only)
    return " ".join(clean.split())


def _compact_text(value: str) -> str:
    return _normalize_text(value).replace(" ", "")


def _segment_candidates(value: str) -> list[str]:
    raw_segments = re.split(r"[\\/]+", value.lower())
    candidates: list[str] = []
    for segment in raw_segments:
        normalized = _normalize_text(segment)
        if not normalized:
            continue
        candidates.append(normalized)
        compact = normalized.replace(" ", "")
        if compact:
            candidates.append(compact)
    return candidates


def _matches_query(text: str, query: str) -> bool:
    query_norm = _normalize_text(query)
    if not query_norm:
        return True

    text_norm = _normalize_text(text)
    text_compact = text_norm.replace(" ", "")
    query_compact = query_norm.replace(" ", "")

    if query_norm in text_norm:
        return True
    if query_compact and query_compact in text_compact:
        return True

    query_tokens = query_norm.split()
    if query_tokens and all(token in text_norm for token in query_tokens):
        return True

    if len(query_compact) >= 5:
        for candidate in _segment_candidates(text):
            ratio = SequenceMatcher(None, query_compact, candidate).ratio()
            if ratio >= 0.84:
                return True

    return False


def _query_score(text: str, query: str) -> int:
    query_norm = _normalize_text(query)
    if not query_norm:
        return 0
    if not _matches_query(text, query):
        return 0

    text_norm = _normalize_text(text)
    text_compact = _compact_text(text)
    query_compact = query_norm.replace(" ", "")

    if text_norm == query_norm or text_compact == query_compact:
        return 100
    if query_compact and (text_compact.endswith(query_compact) or query_compact in text_compact):
        return 85
    return 70


def _value_range_for_field(section: str, key: str) -> tuple[float, float] | None:
    name = _field_name(section, key)

    if "PRESS" in name:
        return (10.0, 50.0)
    if "CAMBER" in name:
        return (-10.0, 1.0)
    if "TOE" in name:
        return (-2.0, 2.0)
    if "ARB" in name or "ANTIROLL" in name:
        return (0.0, 20.0)
    if "SPRING" in name:
        return (0.0, 300000.0)
    if "BRAKE_BIAS" in name or "BRAKEBIAS" in name or "FRONT_BIAS" in name:
        return (50.0, 80.0)
    if "DIFF" in name and "PRELOAD" in name:
        return (0.0, 400.0)
    if "DIFF" in name and ("POWER" in name or "COAST" in name):
        return (0.0, 100.0)

    return None


def _compatible_limits(section: str, key: str, previous_number: float | None) -> tuple[float, float] | None:
    limits = _value_range_for_field(section, key)
    if limits is None or previous_number is None:
        return limits

    # AC setups sometimes store scaled values (for example ARB stiffness in thousands)
    # under VALUE keys; skip incompatible clamping when current data is out of scale.
    if previous_number < limits[0] or previous_number > limits[1]:
        return None
    return limits


def list_setups(car: str = "", track: str = "", root_dir: str | None = None) -> list[dict[str, Any]]:
    root = Path(root_dir).resolve() if root_dir else setup_root()
    if not root.exists():
        return []

    results: list[dict[str, Any]] = []

    for file_path in sorted(root.rglob("*.ini")):
        full = file_path.as_posix()
        if car and not _matches_query(full, car):
            continue
        if track and not _matches_query(full, track):
            continue

        relative = file_path.relative_to(root)
        results.append(
            {
                "path": relative.as_posix(),
                "size_bytes": file_path.stat().st_size,
                "modified_at": datetime.fromtimestamp(file_path.stat().st_mtime).isoformat(),
            }
        )

    return results


def find_base_setup(car: str, track: str = "", root_dir: str | None = None) -> dict[str, Any]:
    root = Path(root_dir).resolve() if root_dir else setup_root()
    if not root.exists():
        return {
            "found": False,
            "recommended": "",
            "reason": "setup root does not exist",
            "alternatives": [],
        }

    car_token = _normalize_text(car)
    track_token = _normalize_text(track)
    if not car_token:
        return {
            "found": False,
            "recommended": "",
            "reason": "car is required",
            "alternatives": [],
        }

    car_dirs: list[Path] = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and _matches_query(child.name, car_token):
            car_dirs.append(child)

    if not car_dirs:
        return {
            "found": False,
            "recommended": "",
            "reason": f"no setup folder found for car: {car}",
            "alternatives": [],
        }

    ranked: list[tuple[int, float, Path, str]] = []
    for car_dir in car_dirs:
        for ini_path in car_dir.rglob("*.ini"):
            relative_car = ini_path.relative_to(car_dir)
            track_bucket = relative_car.parts[0].lower() if len(relative_car.parts) > 1 else ""
            score = 0
            reason_parts: list[str] = []

            if track_token:
                track_score = _query_score(track_bucket, track_token)
                if track_score >= 100:
                    score += 100
                    reason_parts.append("exact track folder")
                elif track_score >= 85:
                    score += 80
                    reason_parts.append("partial track folder match")
                elif track_score >= 70:
                    score += 65
                    reason_parts.append("fuzzy track folder match")

            if track_bucket == "generic":
                score += 30
                reason_parts.append("generic fallback")

            name = ini_path.name.lower()
            if name == "last.ini":
                score += 5
                reason_parts.append("latest setup")
            elif "base" in name or "default" in name:
                score += 8
                reason_parts.append("base/default name")
            else:
                score += 3

            ranked.append((score, ini_path.stat().st_mtime, ini_path, "; ".join(reason_parts)))

    if not ranked:
        return {
            "found": False,
            "recommended": "",
            "reason": "no ini files found for selected car",
            "alternatives": [],
        }

    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    recommended_path = ranked[0][2]
    recommended_rel = recommended_path.relative_to(root).as_posix()

    alternatives: list[dict[str, Any]] = []
    for score, _, path, reason in ranked[:10]:
        alternatives.append(
            {
                "path": path.relative_to(root).as_posix(),
                "score": score,
                "reason": reason,
            }
        )

    return {
        "found": True,
        "recommended": recommended_rel,
        "reason": ranked[0][3],
        "alternatives": alternatives,
    }


def read_setup(path: str) -> dict[str, Any]:
    resolved = resolve_setup_path(path)
    if not resolved.exists():
        raise FileNotFoundError(f"Setup not found: {resolved}")

    parser = _new_parser()
    with resolved.open("r", encoding="utf-8") as handle:
        parser.read_file(handle)

    sections: dict[str, dict[str, str]] = {}
    for section in parser.sections():
        sections[section] = dict(parser.items(section))

    return {
        "path": str(resolved),
        "sections": sections,
    }


def compare_setups(base_path: str, candidate_path: str) -> dict[str, Any]:
    base = read_setup(base_path)["sections"]
    candidate = read_setup(candidate_path)["sections"]

    differences: list[dict[str, str]] = []
    all_sections = sorted(set(base.keys()) | set(candidate.keys()))

    for section in all_sections:
        base_keys = base.get(section, {})
        candidate_keys = candidate.get(section, {})
        all_keys = sorted(set(base_keys.keys()) | set(candidate_keys.keys()))
        for key in all_keys:
            before = base_keys.get(key)
            after = candidate_keys.get(key)
            if before != after:
                differences.append(
                    {
                        "section": section,
                        "key": key,
                        "base": "" if before is None else str(before),
                        "candidate": "" if after is None else str(after),
                    }
                )

    return {
        "difference_count": len(differences),
        "differences": differences,
    }


def _load_parser(path: Path) -> configparser.ConfigParser:
    parser = _new_parser()
    with path.open("r", encoding="utf-8") as handle:
        parser.read_file(handle)
    return parser


def _serialize(parser: configparser.ConfigParser) -> dict[str, dict[str, str]]:
    output: dict[str, dict[str, str]] = {}
    for section in parser.sections():
        output[section] = dict(parser.items(section))
    return output


def _next_versioned_path(path: Path) -> Path:
    parent = path.parent
    suffix = path.suffix
    stem = path.stem

    version_match = re.match(r"^(?P<base>.+)_v(?P<version>\d+)$", stem)
    base_stem = version_match.group("base") if version_match else stem
    escaped = re.escape(base_stem)
    pattern = re.compile(rf"^{escaped}_v(?P<version>\d+){re.escape(suffix)}$", re.IGNORECASE)

    max_version = 0
    for candidate in parent.iterdir():
        if not candidate.is_file():
            continue
        match = pattern.match(candidate.name)
        if not match:
            continue
        max_version = max(max_version, int(match.group("version")))

    next_version = max_version + 1
    return parent / f"{base_stem}_v{next_version:03d}{suffix}"


def apply_changes(
    path: str,
    changes: list[dict[str, Any]],
    dry_run: bool = True,
    create_backup: bool = True,
    save_as_new_version: bool = False,
) -> dict[str, Any]:
    if not changes:
        return {
            "path": str(resolve_setup_path(path)),
            "applied": [],
            "backup_path": None,
            "written": False,
            "preview": read_setup(path)["sections"],
        }

    resolved = resolve_setup_path(path)
    if not resolved.exists():
        raise FileNotFoundError(f"Setup not found: {resolved}")

    parser = _load_parser(resolved)
    applied: list[dict[str, str]] = []

    for item in changes:
        section = str(item.get("section", "")).strip()
        key = str(item.get("key", "")).strip()

        if not section or not key:
            raise ValueError("Each change needs section and key")
        if not parser.has_section(section):
            raise ValueError(f"Section not found: {section}")
        if not parser.has_option(section, key):
            raise ValueError(f"Key not found: {section}.{key}")

        previous_value = parser.get(section, key)
        previous_number = _as_number(previous_value)

        if "new_value" in item:
            new_raw = str(item["new_value"])
            proposed = _as_number(new_raw)
            if proposed is not None:
                limits = _compatible_limits(section, key, previous_number)
                if limits:
                    proposed = max(limits[0], min(limits[1], proposed))
                new_value = _format_like_reference(previous_value, proposed)
            else:
                new_value = new_raw
        elif "delta" in item:
            if previous_number is None:
                raise ValueError(f"Cannot apply delta to non numeric value: {section}.{key}")
            delta = float(item["delta"])
            proposed = previous_number + delta
            limits = _compatible_limits(section, key, previous_number)
            if limits:
                proposed = max(limits[0], min(limits[1], proposed))
            new_value = _format_like_reference(previous_value, proposed)
        else:
            raise ValueError("Each change needs either new_value or delta")

        parser.set(section, key, new_value)
        applied.append(
            {
                "section": section,
                "key": key,
                "old_value": previous_value,
                "new_value": new_value,
                "reason": str(item.get("reason", "")),
            }
        )

    backup_path: str | None = None
    output_path = resolved
    if not dry_run:
        if save_as_new_version:
            output_path = _next_versioned_path(resolved)
        else:
            if create_backup:
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup = resolved.with_suffix(resolved.suffix + f".bak.{stamp}")
                shutil.copy2(resolved, backup)
                backup_path = str(backup)

        with output_path.open("w", encoding="utf-8") as handle:
            # Keep AC-friendly INI style (KEY=VALUE) to avoid parser edge-cases.
            parser.write(handle, space_around_delimiters=False)

    preview = _serialize(parser)
    return {
        "path": str(output_path),
        "source_path": str(resolved),
        "applied": applied,
        "backup_path": backup_path,
        "written": not dry_run,
        "save_as_new_version": save_as_new_version,
        "preview": preview,
    }


def clone_setup_data(setup: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    return deepcopy(setup)
