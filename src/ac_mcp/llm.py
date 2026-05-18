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
    confidence: float | None = None


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


def _tokenize(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def _target_name(section: str, key: str) -> str:
    return section if key.upper() == "VALUE" else key


def _clamp_confidence(value: float) -> float:
    return max(0.05, min(1.0, float(value)))


def _resolve_target(
    setup: dict[str, dict[str, str]],
    section: str,
    key: str,
) -> tuple[str, str] | None:
    if section in setup and key in setup[section]:
        return section, key

    section_token = _tokenize(section)
    key_token = _tokenize(key)

    if section in setup and "VALUE" in setup[section] and (not key_token or key_token == "VALUE"):
        return section, "VALUE"

    candidates: list[tuple[int, str, str]] = []
    for sec_name, values in setup.items():
        sec_token = _tokenize(sec_name)
        for key_name in values:
            key_name_token = _tokenize(key_name)
            target_token = _tokenize(_target_name(sec_name, key_name))
            score = 0

            if section_token and section_token == sec_token and key_token and key_token == key_name_token:
                score = 100
            elif key_token and key_token in {key_name_token, target_token}:
                score = 92
            elif section_token and section_token in {sec_token, target_token}:
                score = 88
            elif key_token and key_token in target_token:
                score = 82
            elif section_token and section_token in target_token:
                score = 80
            elif key_token and key_token in key_name_token:
                score = 76

            if score > 0:
                candidates.append((score, sec_name, key_name))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0], reverse=True)
    best = candidates[0]
    if best[0] < 76:
        return None

    return best[1], best[2]


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

        target = _resolve_target(setup, section, key)
        if target is None:
            continue

        resolved_section, resolved_key = target

        current = setup[resolved_section][resolved_key]
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

        confidence = 0.68
        if item.confidence is not None:
            try:
                confidence = _clamp_confidence(float(item.confidence))
            except (TypeError, ValueError):
                confidence = 0.68

        normalized.append(
            {
                "section": resolved_section,
                "key": resolved_key,
                "delta": round(float(delta), 3),
                "reason": item.reason.strip() or "LLM suggestion.",
                "confidence": round(confidence, 3),
                "source": "llm",
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
                numeric_targets.append(
                    {
                        "section": section,
                        "key": key,
                        "target": _target_name(section, key),
                        "value": raw,
                    }
                )

    prompt = {
        "task": "Suggest safe setup deltas for Assetto Corsa.",
        "requirements": [
            "Output strict JSON object only.",
            "Use available setup keys and map to the closest valid target when needed.",
            "Prioritize lap-time impact while preserving drivability.",
            "You may return as many changes as needed for the objective.",
            "confidence must be between 0 and 1 for each change.",
        ],
        "symptoms": symptoms,
        "track_conditions": track_conditions,
        "setup_snapshot": setup,
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
                    "confidence": "number between 0 and 1",
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
