from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from ac_mcp.llm import llm_suggest_changes


@dataclass(frozen=True)
class ActionRule:
    aliases: tuple[str, ...]
    delta: float
    reason: str


@dataclass(frozen=True)
class SymptomRule:
    keywords: tuple[str, ...]
    actions: tuple[ActionRule, ...]


RULES: tuple[SymptomRule, ...] = (
    SymptomRule(
        keywords=("oversteer exit", "sobrevira salida", "sobreviraje salida"),
        actions=(
            ActionRule(("ARB_REAR", "REAR_ARB", "ARB_R"), -1.0, "Softer rear anti-roll for better traction."),
            ActionRule(("DIFF_POWER", "POWER", "DIFF POWER"), -3.0, "Lower diff power lock to reduce snap oversteer on throttle."),
        ),
    ),
    SymptomRule(
        keywords=("oversteer entry", "sobrevira entrada", "sobreviraje entrada"),
        actions=(
            ActionRule(("BRAKE_BIAS", "BRAKEBIAS"), 1.0, "Move brake bias forward for stability on entry."),
            ActionRule(("DIFF_COAST", "COAST", "DIFF COAST"), 2.0, "Increase coast lock for calmer lift-off behavior."),
        ),
    ),
    SymptomRule(
        keywords=("understeer entry", "subvira entrada", "subviraje entrada"),
        actions=(
            ActionRule(("BRAKE_BIAS", "BRAKEBIAS"), -1.0, "Move brake bias slightly rearward to help rotation."),
            ActionRule(("ARB_FRONT", "FRONT_ARB", "ARB_F"), -1.0, "Softer front anti-roll improves turn-in."),
        ),
    ),
    SymptomRule(
        keywords=("understeer exit", "subvira salida", "subviraje salida"),
        actions=(
            ActionRule(("DIFF_POWER", "POWER", "DIFF POWER"), 2.0, "Increase diff power lock for traction balance if inside wheel spins."),
            ActionRule(("ARB_FRONT", "FRONT_ARB", "ARB_F"), -1.0, "Softer front anti-roll can free front tires on throttle."),
        ),
    ),
    SymptomRule(
        keywords=("rear unstable braking", "inestable frenada", "cola suelta frenada"),
        actions=(
            ActionRule(("BRAKE_BIAS", "BRAKEBIAS"), 1.0, "More front bias stabilizes rear under braking."),
            ActionRule(("DIFF_COAST", "COAST", "DIFF COAST"), 2.0, "Higher coast lock can reduce rear yaw spikes."),
        ),
    ),
)


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def _token(text: str) -> str:
    return text.upper().replace("_", "").replace(" ", "").strip()


def _target_name(section: str, key: str) -> str:
    key_name = key.upper().strip()
    if key_name == "VALUE":
        return section.upper().strip()
    return key_name


def _find_target(setup: dict[str, dict[str, str]], aliases: tuple[str, ...]) -> tuple[str, str] | None:
    alias_set = {alias.upper() for alias in aliases}
    best: tuple[str, str] | None = None
    best_score = 0

    for section, values in setup.items():
        section_space = section.upper().replace("_", " ")
        section_token = _token(section)
        for key in values.keys():
            key_space = key.upper().replace("_", " ")
            key_token = _token(key)
            target = _target_name(section, key)
            target_space = target.replace("_", " ")
            target_token = _token(target)

            for alias in alias_set:
                alias_space = alias.replace("_", " ")
                alias_token = _token(alias)
                score = 0

                if alias_token in {target_token, section_token, key_token}:
                    score = 100
                elif alias_space in {target_space, section_space, key_space}:
                    score = 95
                elif alias_token and (alias_token in target_token or alias_token in section_token):
                    score = 80
                elif alias_space and (alias_space in target_space or alias_space in section_space):
                    score = 75
                elif alias_token and alias_token in key_token:
                    score = 70

                if score > best_score:
                    best_score = score
                    best = (section, key)

    return best


def _is_number(value: str) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def _heuristic_suggestions(
    setup: dict[str, dict[str, str]],
    symptoms: str,
    track_conditions: str,
) -> dict[str, Any]:
    symptom_text = _normalize(symptoms)
    conditions_text = _normalize(track_conditions)

    merged: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"section": "", "key": "", "delta": 0.0, "reason": []}
    )
    not_found: list[str] = []
    matched_keywords: list[str] = []

    for rule in RULES:
        if any(keyword in symptom_text for keyword in rule.keywords):
            matched_keywords.extend(rule.keywords)
            for action in rule.actions:
                target = _find_target(setup, action.aliases)
                if target is None:
                    not_found.append("/".join(action.aliases))
                    continue

                section, key = target
                current = setup[section].get(key, "")
                if not _is_number(current):
                    not_found.append(f"{section}.{key} non numeric")
                    continue

                merged[(section, key)]["section"] = section
                merged[(section, key)]["key"] = key
                merged[(section, key)]["delta"] += action.delta
                merged[(section, key)]["reason"].append(action.reason)

    pressure_delta = 0.0
    if any(flag in conditions_text for flag in ("cold", "frio", "frias", "frios")):
        pressure_delta -= 1.0
    if any(flag in conditions_text for flag in ("hot", "caliente", "altas temp", "temperatura alta")):
        pressure_delta += 1.0

    if pressure_delta != 0.0:
        for section, values in setup.items():
            for key, raw_value in values.items():
                target = _target_name(section, key)
                if "PRESS" in target and _is_number(raw_value):
                    merged[(section, key)]["section"] = section
                    merged[(section, key)]["key"] = key
                    merged[(section, key)]["delta"] += pressure_delta
                    merged[(section, key)]["reason"].append("Track temperature pressure correction.")

    suggestions: list[dict[str, Any]] = []
    for (_, _), data in sorted(merged.items(), key=lambda item: (item[0][0], item[0][1])):
        if data["delta"] == 0.0:
            continue

        suggestions.append(
            {
                "section": data["section"],
                "key": data["key"],
                "delta": round(float(data["delta"]), 3),
                "reason": " ".join(dict.fromkeys(data["reason"])),
                "source": "heuristic",
            }
        )

    return {
        "matched": sorted(set(matched_keywords)),
        "suggested_changes": suggestions,
        "missing_targets": sorted(set(not_found)),
    }


def _merge_with_llm(
    heuristic: list[dict[str, Any]],
    llm: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}

    for item in heuristic:
        token = (item["section"], item["key"])
        merged[token] = {
            "section": item["section"],
            "key": item["key"],
            "delta": float(item["delta"]),
            "reason": item.get("reason", ""),
            "source": "heuristic",
        }

    for item in llm:
        token = (item["section"], item["key"])
        llm_delta = float(item["delta"])
        llm_reason = item.get("reason", "LLM suggestion")

        if token in merged:
            base_delta = float(merged[token]["delta"])
            merged[token]["delta"] = round((base_delta + llm_delta) / 2.0, 3)
            merged[token]["reason"] = f"Heuristic: {merged[token]['reason']} LLM: {llm_reason}"
            merged[token]["source"] = "blended"
        else:
            merged[token] = {
                "section": item["section"],
                "key": item["key"],
                "delta": round(llm_delta, 3),
                "reason": llm_reason,
                "source": "llm",
            }

    return [
        merged[key]
        for key in sorted(merged.keys(), key=lambda item: (item[0], item[1]))
        if merged[key]["delta"] != 0.0
    ]


def suggest_changes_heuristic(
    setup: dict[str, dict[str, str]],
    symptoms: str,
    track_conditions: str = "",
) -> dict[str, Any]:
    heuristic = _heuristic_suggestions(setup=setup, symptoms=symptoms, track_conditions=track_conditions)
    guidance = "No matching rule. Provide symptom details like entry/exit oversteer and tire temp."
    if heuristic["suggested_changes"]:
        guidance = "Heuristic-only guidance. Use suggest_changes (LLM required) for final recommendation."

    return {
        "matched": heuristic["matched"],
        "suggested_changes": heuristic["suggested_changes"],
        "missing_targets": heuristic["missing_targets"],
        "guidance": guidance,
    }


def suggest_changes(
    setup: dict[str, dict[str, str]],
    symptoms: str,
    track_conditions: str = "",
    use_llm: bool | None = None,
    require_llm: bool = False,
) -> dict[str, Any]:
    heuristic = _heuristic_suggestions(setup=setup, symptoms=symptoms, track_conditions=track_conditions)
    llm_meta: dict[str, Any] = {
        "used": False,
        "provider": "",
        "model": "",
        "summary": "",
        "error": "",
    }
    suggestions = list(heuristic["suggested_changes"])

    allow_llm = use_llm is not False
    if require_llm and not allow_llm:
        raise ValueError("LLM is required for suggest_changes. Set use_llm=true.")

    if allow_llm:
        llm_result = llm_suggest_changes(
            setup=setup,
            symptoms=symptoms,
            track_conditions=track_conditions,
            heuristic_suggestions=heuristic["suggested_changes"],
        )
        llm_meta = {
            "used": bool(llm_result.get("used", False)),
            "provider": str(llm_result.get("provider", "")),
            "model": str(llm_result.get("model", "")),
            "summary": str(llm_result.get("summary", "")),
            "error": str(llm_result.get("error", "")),
        }
        if llm_meta["used"] and llm_result.get("suggested_changes"):
            suggestions = _merge_with_llm(
                heuristic=heuristic["suggested_changes"],
                llm=llm_result["suggested_changes"],
            )

    if require_llm and not llm_meta["used"]:
        reason = llm_meta["error"] or "Unknown LLM availability error"
        raise RuntimeError(f"LLM required but unavailable: {reason}")

    if not suggestions:
        guidance = "No matching rule. Provide symptom details like entry/exit oversteer and tire temp."
    else:
        guidance = "Review with dry_run first, then apply with explicit confirm=true."

    if llm_meta["used"] and llm_meta["summary"]:
        guidance = f"{guidance} LLM summary: {llm_meta['summary']}"

    return {
        "matched": heuristic["matched"],
        "suggested_changes": suggestions,
        "missing_targets": heuristic["missing_targets"],
        "guidance": guidance,
        "llm": llm_meta,
    }
