from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ac_mcp.config import session_log_root


def record_session_context(
    driver: str,
    car: str,
    track: str,
    symptoms: str,
    track_conditions: str = "",
    lap_time_seconds: float | None = None,
    notes: str = "",
) -> dict[str, Any]:
    root = session_log_root()
    root.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    file_name = f"{timestamp}_{car}_{track}.json".replace(" ", "_")
    output = root / file_name

    payload = {
        "timestamp_utc": timestamp,
        "driver": driver,
        "car": car,
        "track": track,
        "symptoms": symptoms,
        "track_conditions": track_conditions,
        "lap_time_seconds": lap_time_seconds,
        "notes": notes,
    }

    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {
        "saved": True,
        "path": str(output),
        "payload": payload,
    }


def list_session_context(limit: int = 20) -> dict[str, Any]:
    root = session_log_root()
    if not root.exists():
        return {"items": []}

    files = sorted(root.glob("*.json"), reverse=True)[: max(1, limit)]
    items: list[dict[str, str]] = []
    for file_path in files:
        items.append(
            {
                "path": str(file_path),
                "name": file_path.name,
                "modified_at": datetime.fromtimestamp(file_path.stat().st_mtime).isoformat(),
            }
        )

    return {"items": items}
