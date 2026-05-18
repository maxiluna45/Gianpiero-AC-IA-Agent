from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


if load_dotenv:
    # Allow local .env usage for MCP server runtime configuration.
    load_dotenv()


def setup_root() -> Path:
    configured = os.getenv("AC_SETUP_ROOT", "").strip()
    if configured:
        return Path(configured).resolve()

    local_default = Path("setups").resolve()
    if local_default.exists():
        return local_default

    home = Path.home()
    one_drive = os.getenv("OneDrive", "").strip()

    candidates: list[Path] = [
        home / "Documents" / "Assetto Corsa" / "setups",
        home / "Documentos" / "Assetto Corsa" / "setups",
    ]

    if one_drive:
        one_drive_path = Path(one_drive)
        candidates.extend(
            [
                one_drive_path / "Documents" / "Assetto Corsa" / "setups",
                one_drive_path / "Documentos" / "Assetto Corsa" / "setups",
            ]
        )

    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()

    return local_default


def session_log_root() -> Path:
    root = Path(os.getenv("AC_SESSION_LOG_ROOT", "session_logs")).resolve()
    return root


def _clean_env(name: str, default: str = "") -> str:
    value = os.getenv(name, default)
    if value is None:
        return ""

    cleaned = str(value).strip()
    # Accept accidental wrapping/typing characters in .env values.
    while cleaned and cleaned[0] in {'"', "'", "`"}:
        cleaned = cleaned[1:].strip()
    while cleaned and cleaned[-1] in {'"', "'", "`"}:
        cleaned = cleaned[:-1].strip()
    return cleaned


def llm_provider() -> str:
    value = _clean_env("AC_LLM_PROVIDER", "disabled").lower()
    return value or "disabled"


def llm_base_url() -> str:
    return _clean_env("AC_LLM_BASE_URL", "https://api.openai.com/v1")


def llm_api_key() -> str:
    return _clean_env("AC_LLM_API_KEY", "")


def llm_model() -> str:
    return _clean_env("AC_LLM_MODEL", "gpt-4.1-mini")


def llm_timeout_seconds() -> float:
    raw = os.getenv("AC_LLM_TIMEOUT_SECONDS", "20")
    try:
        return max(3.0, float(raw))
    except ValueError:
        return 20.0


def llm_temperature() -> float:
    raw = os.getenv("AC_LLM_TEMPERATURE", "0.2")
    try:
        value = float(raw)
    except ValueError:
        return 0.2
    return max(0.0, min(1.0, value))


def tavily_api_key() -> str:
    return _clean_env("TAVILY_API_KEY", "")


def resolve_setup_path(path: str) -> Path:
    root = setup_root()
    raw = Path(path)
    candidate = raw if raw.is_absolute() else (root / raw)
    resolved = candidate.resolve()

    if resolved != root and root not in resolved.parents:
        raise ValueError("Path is outside of AC_SETUP_ROOT")

    return resolved
