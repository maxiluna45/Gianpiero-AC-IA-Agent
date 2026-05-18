from __future__ import annotations

from typing import Any
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from ac_mcp.advisor import suggest_changes as advisor_suggest_changes
from ac_mcp.advisor import suggest_changes_heuristic as advisor_suggest_changes_heuristic
from ac_mcp.config import setup_root
from ac_mcp.pipeline import start_from_base_pipeline
from ac_mcp.references import fetch_reference as refs_fetch_reference
from ac_mcp.references import get_circuit_info as refs_get_circuit_info
from ac_mcp.references import search_base_setups as refs_search_base_setups
from ac_mcp.references import search_references as refs_search_references
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
from ac_mcp.telemetry_shared_memory import get_shared_memory_stint_status as shm_get_stint_status
from ac_mcp.telemetry_shared_memory import list_shared_memory_logs
from ac_mcp.telemetry_shared_memory import record_shared_memory_stint as shm_record_stint
from ac_mcp.telemetry_shared_memory import start_shared_memory_stint as shm_start_stint
from ac_mcp.telemetry_shared_memory import stop_shared_memory_stint as shm_stop_stint

mcp = FastMCP("ac-mcp")


@mcp.tool()
def list_setups(car: str = "", track: str = "", root_dir: str | None = None) -> dict[str, Any]:
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
    return io_read_setup(path)


@mcp.tool()
def find_base_setup(car: str, track: str = "", root_dir: str | None = None) -> dict[str, Any]:
    return io_find_base_setup(car=car, track=track, root_dir=root_dir)


@mcp.tool()
def suggest_changes(
    symptoms: str,
    track_conditions: str = "",
    setup: dict[str, dict[str, str]] | None = None,
    setup_path: str | None = None,
    llm_required: bool = True,
) -> dict[str, Any]:
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
    return list_session_context(limit=limit)


@mcp.tool()
def capture_shared_memory_snapshot() -> dict[str, Any]:
    try:
        return {
            "available": True,
            "snapshot": shm_capture_snapshot(),
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
) -> dict[str, Any]:
    try:
        data = shm_record_stint(
            session_id=session_id,
            sample_count=sample_count,
            interval_ms=interval_ms,
            export_csv=export_csv,
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
) -> dict[str, Any]:
    try:
        data = shm_start_stint(
            session_id=session_id,
            sample_count=sample_count,
            interval_ms=interval_ms,
            export_csv=export_csv,
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
    return shm_get_stint_status(capture_id=capture_id)


@mcp.tool()
def stop_shared_memory_capture(capture_id: str) -> dict[str, Any]:
    return shm_stop_stint(capture_id=capture_id)


@mcp.tool()
def analyze_shared_memory_track(
    path: str = "",
    bins: int = 40,
) -> dict[str, Any]:
    return analyze_shared_memory_track_map(path=path, bins=bins)


@mcp.tool()
def analyze_shared_memory_corner_limits(
    path: str = "",
    bins: int = 120,
) -> dict[str, Any]:
    return analyze_corner_limits_map(path=path, bins=bins)


@mcp.tool()
def coach_shared_memory_corner_limits(
    path: str = "",
    bins: int = 120,
    top_n: int = 5,
) -> dict[str, Any]:
    return coach_corner_limits(path=path, bins=bins, top_n=top_n)


@mcp.tool()
def compare_shared_memory_stints(
    base_path: str,
    candidate_path: str,
    bins: int = 120,
    objective: str = "lap_time",
) -> dict[str, Any]:
    return compare_shm_stints(
        base_path=base_path,
        candidate_path=candidate_path,
        bins=bins,
        objective=objective,
    )


@mcp.tool()
def list_shared_memory_sessions(limit: int = 20) -> dict[str, Any]:
    return list_shared_memory_logs(limit=limit)


@mcp.tool()
def search_references(
    car: str,
    track: str,
    symptom: str = "",
    max_results: int = 5,
    provider: str = "auto",
) -> dict[str, Any]:
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
    return refs_get_circuit_info(
        track=track,
        max_results=max_results,
        provider=provider,
    )


@mcp.tool()
def fetch_reference(url: str, max_chars: int = 7000) -> dict[str, Any]:
    return refs_fetch_reference(url=url, max_chars=max_chars)


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
