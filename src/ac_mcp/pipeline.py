from __future__ import annotations

from typing import Any

from ac_mcp.advisor import suggest_changes, suggest_changes_heuristic
from ac_mcp.setup_io import apply_changes, find_base_setup, read_setup


def start_from_base_pipeline(
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
    if not dry_run and not confirm:
        raise ValueError("Set confirm=true to write changes")

    base = find_base_setup(car=car, track=track, root_dir=root_dir)
    if not base.get("found"):
        raise ValueError(str(base.get("reason", "No base setup found")))

    setup_path = str(base["recommended"])
    setup_data = read_setup(setup_path)
    sections = setup_data["sections"]

    heuristic = suggest_changes_heuristic(
        setup=sections,
        symptoms=symptoms,
        track_conditions=track_conditions,
    )

    llm_suggestion = suggest_changes(
        setup=sections,
        symptoms=symptoms,
        track_conditions=track_conditions,
        use_llm=True,
        require_llm=llm_required,
    )

    changes = llm_suggestion.get("suggested_changes", [])
    apply_result = apply_changes(
        path=setup_path,
        changes=changes,
        dry_run=dry_run,
        create_backup=create_backup,
        save_as_new_version=save_as_new_version,
    )

    return {
        "car": car,
        "track": track,
        "symptoms": symptoms,
        "track_conditions": track_conditions,
        "base_setup": base,
        "setup": {
            "path": setup_data["path"],
            "section_count": len(sections),
        },
        "heuristic": heuristic,
        "llm": llm_suggestion.get("llm", {}),
        "suggested_changes": changes,
        "changes_count": len(changes),
        "apply": apply_result,
    }
