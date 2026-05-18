from __future__ import annotations

import json
import re
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError

from ac_mcp.config import (
    llm_api_key,
    llm_base_url,
    llm_model,
    llm_provider,
    llm_temperature,
    llm_timeout_seconds,
)


class LlmChange(BaseModel):
    section: str
    key: str
    delta: float | None = None
    new_value: float | int | str | None = None
    reason: str = ""


class LlmPayload(BaseModel):
    summary: str = ""
    suggested_changes: list[LlmChange] = Field(default_factory=list)


def _extract_json(content: str) -> dict[str, Any]:
    text = content.strip()

    fenced = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text, flags=re.IGNORECASE)
    if fenced:
        return json.loads(fenced.group(1))

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    starts = [index for index, char in enumerate(text) if char == "{"]
    for start in starts:
        depth = 0
        for pos in range(start, len(text)):
            char = text[pos]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : pos + 1]
                    try:
                        parsed = json.loads(candidate)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(parsed, dict):
                        return parsed
                    break

    raise ValueError("LLM did not return parseable JSON object")


def _is_number(value: str) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def _normalize_llm_changes(
    setup: dict[str, dict[str, str]],
    changes: list[LlmChange],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []

    for item in changes:
        section = item.section.strip()
        key = item.key.strip()

        if not section or not key:
            continue
        if section not in setup:
            continue
        if key not in setup[section]:
            continue

        current = setup[section][key]
        if not _is_number(current):
            continue
        current_num = float(current)

        delta: float | None = item.delta
        if delta is None and item.new_value is not None:
            try:
                delta = float(item.new_value) - current_num
            except (TypeError, ValueError):
                continue

        if delta is None:
            continue

        normalized.append(
            {
                "section": section,
                "key": key,
                "delta": round(float(delta), 3),
                "reason": item.reason.strip() or "LLM suggestion.",
            }
        )

    return normalized


def llm_suggest_changes(
    setup: dict[str, dict[str, str]],
    symptoms: str,
    track_conditions: str,
    heuristic_suggestions: list[dict[str, Any]],
) -> dict[str, Any]:
    provider = llm_provider()
    if provider in {"", "disabled", "none"}:
        return {
            "used": False,
            "provider": provider,
            "model": "",
            "summary": "",
            "suggested_changes": [],
            "error": "LLM provider disabled",
        }

    if provider not in {"openai", "openai_compatible", "github_models"}:
        return {
            "used": False,
            "provider": provider,
            "model": "",
            "summary": "",
            "suggested_changes": [],
            "error": f"Unsupported provider: {provider}",
        }

    api_key = llm_api_key()
    if not api_key:
        return {
            "used": False,
            "provider": provider,
            "model": "",
            "summary": "",
            "suggested_changes": [],
            "error": "Missing AC_LLM_API_KEY",
        }

    numeric_targets: list[dict[str, str]] = []
    for section, values in setup.items():
        for key, raw in values.items():
            if _is_number(raw):
                numeric_targets.append({"section": section, "key": key, "value": raw})

    prompt = {
        "task": "Suggest safe setup deltas for Assetto Corsa.",
        "constraints": [
            "Only use keys that exist in numeric_targets.",
            "Return at most 8 changes.",
            "Prefer conservative deltas.",
            "Output strict JSON object only.",
        ],
        "symptoms": symptoms,
        "track_conditions": track_conditions,
        "numeric_targets": numeric_targets,
        "heuristic_suggestions": heuristic_suggestions,
        "output_schema": {
            "summary": "short text",
            "suggested_changes": [
                {
                    "section": "string",
                    "key": "string",
                    "delta": "number optional",
                    "new_value": "number optional",
                    "reason": "string",
                }
            ],
        },
    }

    base_url = llm_base_url().rstrip("/")
    headers: dict[str, str] = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if provider == "github_models":
        if base_url in {"", "https://api.openai.com/v1"}:
            base_url = "https://models.github.ai/inference"
        headers["Accept"] = "application/vnd.github+json"
        headers["X-GitHub-Api-Version"] = "2022-11-28"

    endpoint = f"{base_url}/chat/completions"
    model = llm_model()
    request_json: dict[str, Any] = {
        "model": model,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "You are a motorsport setup engineer. Output JSON only."},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=True)},
        ],
    }
    if provider != "github_models":
        request_json["temperature"] = llm_temperature()

    try:
        with httpx.Client(timeout=llm_timeout_seconds()) as client:
            response = client.post(
                endpoint,
                headers=headers,
                json=request_json,
            )
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as exc:
        detail = ""
        try:
            detail = str(exc.response.text)[:800]
        except Exception:
            detail = ""
        return {
            "used": False,
            "provider": provider,
            "model": model,
            "summary": "",
            "suggested_changes": [],
            "error": f"LLM request failed ({exc.response.status_code}): {detail}",
        }
    except Exception as exc:
        return {
            "used": False,
            "provider": provider,
            "model": model,
            "summary": "",
            "suggested_changes": [],
            "error": f"LLM request failed: {exc}",
        }

    try:
        content = payload["choices"][0]["message"]["content"]
        parsed = _extract_json(str(content))
        validated = LlmPayload.model_validate(parsed)
    except (KeyError, IndexError, TypeError, ValueError, ValidationError) as exc:
        return {
            "used": False,
            "provider": provider,
            "model": model,
            "summary": "",
            "suggested_changes": [],
            "error": f"Invalid LLM response: {exc}",
        }

    normalized = _normalize_llm_changes(setup=setup, changes=validated.suggested_changes)
    return {
        "used": True,
        "provider": provider,
        "model": model,
        "summary": validated.summary.strip(),
        "suggested_changes": normalized,
        "error": "",
    }
