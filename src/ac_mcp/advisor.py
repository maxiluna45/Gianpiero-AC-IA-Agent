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
    confidence_bias: float = 0.0


@dataclass(frozen=True)
class SymptomRule:
    family: str
    keywords: tuple[str, ...]
    actions: tuple[ActionRule, ...]


RULES: tuple[SymptomRule, ...] = (
    SymptomRule(
        family="traction_exit",
        keywords=("oversteer exit", "sobrevira salida", "sobreviraje salida"),
        actions=(
            ActionRule(("ARB_REAR", "REAR_ARB", "ARB_R"), -1.0, "Softer rear anti-roll for better traction."),
            ActionRule(
                ("DIFF_POWER", "POWER", "DIFF POWER"),
                -3.0,
                "Lower diff power lock to reduce snap oversteer on throttle.",
                0.05,
            ),
        ),
    ),
    SymptomRule(
        family="entry_stability",
        keywords=("oversteer entry", "sobrevira entrada", "sobreviraje entrada"),
        actions=(
            ActionRule(("BRAKE_BIAS", "BRAKEBIAS", "FRONT_BIAS"), 1.0, "Move brake bias forward for stability on entry."),
            ActionRule(
                ("DIFF_COAST", "COAST", "DIFF COAST"),
                2.0,
                "Increase coast lock for calmer lift-off behavior.",
                0.04,
            ),
        ),
    ),
    SymptomRule(
        family="rotation_entry",
        keywords=("understeer entry", "subvira entrada", "subviraje entrada"),
        actions=(
            ActionRule(("BRAKE_BIAS", "BRAKEBIAS", "FRONT_BIAS"), -1.0, "Move brake bias slightly rearward to help rotation."),
            ActionRule(("ARB_FRONT", "FRONT_ARB", "ARB_F"), -1.0, "Softer front anti-roll improves turn-in.", 0.03),
        ),
    ),
    SymptomRule(
        family="traction_exit",
        keywords=("understeer exit", "subvira salida", "subviraje salida"),
        actions=(
            ActionRule(
                ("DIFF_POWER", "POWER", "DIFF POWER"),
                2.0,
                "Increase diff power lock for traction balance if inside wheel spins.",
                0.04,
            ),
            ActionRule(("ARB_FRONT", "FRONT_ARB", "ARB_F"), -1.0, "Softer front anti-roll can free front tires on throttle."),
        ),
    ),
    SymptomRule(
        family="entry_stability",
        keywords=("rear unstable braking", "inestable frenada", "cola suelta frenada"),
        actions=(
            ActionRule(("BRAKE_BIAS", "BRAKEBIAS", "FRONT_BIAS"), 1.0, "More front bias stabilizes rear under braking."),
            ActionRule(("DIFF_COAST", "COAST", "DIFF COAST"), 2.0, "Higher coast lock can reduce rear yaw spikes.", 0.04),
        ),
    ),
    SymptomRule(
        family="braking_balance",
        keywords=("front lock", "bloquea adelante", "bloqueo delantero"),
        actions=(
            ActionRule(("BRAKE_BIAS", "BRAKEBIAS", "FRONT_BIAS"), -1.0, "Reduce front bias to prevent front lock-ups."),
            ActionRule(("ABS",), 1.0, "Increase ABS support if available for heavy braking zones.", 0.03),
        ),
    ),
    SymptomRule(
        family="braking_balance",
        keywords=("rear lock", "bloquea atras", "bloqueo trasero"),
        actions=(
            ActionRule(("BRAKE_BIAS", "BRAKEBIAS", "FRONT_BIAS"), 1.0, "Move bias forward to avoid rear lock-ups."),
            ActionRule(("DIFF_COAST", "COAST", "DIFF COAST"), 1.0, "Slightly more coast lock can calm rear decel instability."),
        ),
    ),
    SymptomRule(
        family="high_speed_balance",
        keywords=("high speed oversteer", "sobrevira rapido", "inestable alta velocidad"),
        actions=(
            ActionRule(("WING_2", "REAR_WING", "AERO_REAR"), 1.0, "Add rear support for high-speed stability.", 0.05),
            ActionRule(("ARB_REAR", "REAR_ARB", "ARB_R"), -1.0, "Soften rear anti-roll to reduce snap in fast corners."),
        ),
    ),
    SymptomRule(
        family="high_speed_balance",
        keywords=("high speed understeer", "subvira rapido", "falta giro rapido"),
        actions=(
            ActionRule(("ARB_FRONT", "FRONT_ARB", "ARB_F"), -1.0, "Soften front anti-roll for better high-speed bite."),
            ActionRule(("WING_1", "FRONT_WING", "AERO_FRONT"), 1.0, "Increase front load if aero setup supports it.", 0.04),
        ),
    ),
    SymptomRule(
        family="kerb_compliance",
        keywords=("unstable over kerbs", "inestable pianos", "salta en pianos"),
        actions=(
            ActionRule(("DAMP_FAST_BUMP", "FAST_BUMP"), -1.0, "Softer fast bump improves kerb compliance.", 0.04),
            ActionRule(("DAMP_FAST_REBOUND", "FAST_REBOUND"), -1.0, "Softer fast rebound reduces post-kerb bounce.", 0.04),
        ),
    ),
    SymptomRule(
        family="platform_control",
        keywords=("bouncy", "rebota", "flota en cambios"),
        actions=(
            ActionRule(("DAMP_REBOUND", "REBOUND"), 1.0, "Increase rebound damping to control chassis oscillation.", 0.03),
            ActionRule(("DAMP_BUMP", "BUMP"), 1.0, "Slightly firmer bump helps platform support on transitions.", 0.03),
        ),
    ),
    SymptomRule(
        family="rotation_mid",
        keywords=("mid-corner understeer", "subvira media", "falta rotacion media"),
        actions=(
            ActionRule(("ARB_FRONT", "FRONT_ARB", "ARB_F"), -1.0, "Reduce front anti-roll to gain front grip in mid-corner."),
            ActionRule(("CAMBER_LF", "CAMBER_RF", "CAMBER_FRONT"), -1.0, "Add front negative camber to improve loaded front tyre grip."),
        ),
    ),
    SymptomRule(
        family="traction_exit",
        keywords=("wheelspin", "patina salida", "falta traccion"),
        actions=(
            ActionRule(("DIFF_POWER", "POWER", "DIFF POWER"), -2.0, "Reduce power lock to limit wheelspin on throttle pick-up.", 0.05),
            ActionRule(("ARB_REAR", "REAR_ARB", "ARB_R"), -1.0, "Softer rear helps traction over bumps and exits."),
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


def _clamp_confidence(value: float) -> float:
    return max(0.05, min(1.0, float(value)))


def _heuristic_suggestions(
    setup: dict[str, dict[str, str]],
    symptoms: str,
    track_conditions: str,
) -> dict[str, Any]:
    symptom_text = _normalize(symptoms)
    conditions_text = _normalize(track_conditions)

    merged: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "section": "",
            "key": "",
            "delta": 0.0,
            "reason": [],
            "families": set(),
            "confidence_sum": 0.0,
            "confidence_votes": 0.0,
        }
    )
    not_found: list[str] = []
    matched_keywords: list[str] = []
    matched_families: set[str] = set()

    for rule in RULES:
        hits = [keyword for keyword in rule.keywords if keyword in symptom_text]
        if not hits:
            continue

        matched_keywords.extend(hits)
        matched_families.add(rule.family)

        hit_strength = min(1.0, 0.45 + (0.12 * len(hits)))
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

            confidence = _clamp_confidence(0.55 + (hit_strength * 0.25) + action.confidence_bias)

            merged[(section, key)]["section"] = section
            merged[(section, key)]["key"] = key
            merged[(section, key)]["delta"] += action.delta
            merged[(section, key)]["reason"].append(action.reason)
            merged[(section, key)]["families"].add(rule.family)
            merged[(section, key)]["confidence_sum"] += confidence
            merged[(section, key)]["confidence_votes"] += 1.0

    pressure_delta = 0.0
    if any(flag in conditions_text for flag in ("cold", "frio", "frias", "frios")):
        pressure_delta -= 1.0
    if any(flag in conditions_text for flag in ("hot", "caliente", "altas temp", "temperatura alta")):
        pressure_delta += 1.0

    if pressure_delta != 0.0:
        matched_families.add("track_conditions")
        for section, values in setup.items():
            for key, raw_value in values.items():
                target = _target_name(section, key)
                if "PRESS" in target and _is_number(raw_value):
                    merged[(section, key)]["section"] = section
                    merged[(section, key)]["key"] = key
                    merged[(section, key)]["delta"] += pressure_delta
                    merged[(section, key)]["reason"].append("Track temperature pressure correction.")
                    merged[(section, key)]["families"].add("track_conditions")
                    merged[(section, key)]["confidence_sum"] += 0.62
                    merged[(section, key)]["confidence_votes"] += 1.0

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
                "families": sorted(str(family) for family in data["families"]),
                "confidence": round(
                    _clamp_confidence(data["confidence_sum"] / max(1.0, data["confidence_votes"])),
                    3,
                ),
                "source": "heuristic",
            }
        )

    return {
        "matched": sorted(set(matched_keywords)),
        "matched_families": sorted(matched_families),
        "suggested_changes": suggestions,
        "missing_targets": sorted(set(not_found)),
    }


def _merge_with_llm(
    heuristic: list[dict[str, Any]],
    llm: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    def _weighted_delta(base_delta: float, base_conf: float, llm_delta: float, llm_conf: float) -> float:
        if base_delta * llm_delta < 0:
            if base_conf >= (llm_conf + 0.2):
                return round((base_delta * 0.85) + (llm_delta * 0.15), 3)
            if llm_conf >= (base_conf + 0.2):
                return round((llm_delta * 0.85) + (base_delta * 0.15), 3)

        total = max(0.0001, base_conf + llm_conf)
        return round(((base_delta * base_conf) + (llm_delta * llm_conf)) / total, 3)

    merged: dict[tuple[str, str], dict[str, Any]] = {}

    for item in heuristic:
        token = (item["section"], item["key"])
        confidence = _clamp_confidence(float(item.get("confidence", 0.68)))
        merged[token] = {
            "section": item["section"],
            "key": item["key"],
            "delta": float(item["delta"]),
            "reason": item.get("reason", ""),
            "families": list(item.get("families", [])),
            "confidence": confidence,
            "source": "heuristic",
        }

    for item in llm:
        token = (item["section"], item["key"])
        llm_delta = float(item["delta"])
        llm_reason = item.get("reason", "LLM suggestion")
        llm_confidence = _clamp_confidence(float(item.get("confidence", 0.68)))

        if token in merged:
            base_delta = float(merged[token]["delta"])
            base_confidence = _clamp_confidence(float(merged[token].get("confidence", 0.68)))
            blended_delta = _weighted_delta(base_delta, base_confidence, llm_delta, llm_confidence)

            merged[token]["delta"] = blended_delta
            merged[token]["reason"] = (
                f"Heuristic ({base_confidence:.2f}): {merged[token]['reason']} "
                f"LLM ({llm_confidence:.2f}): {llm_reason}"
            )
            merged[token]["confidence"] = round(max(base_confidence, llm_confidence), 3)
            merged[token]["source"] = "blended_confidence_weighted"
        else:
            merged[token] = {
                "section": item["section"],
                "key": item["key"],
                "delta": round(llm_delta, 3),
                "reason": llm_reason,
                "confidence": round(llm_confidence, 3),
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
        "matched_families": heuristic.get("matched_families", []),
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
        "matched_families": heuristic.get("matched_families", []),
        "suggested_changes": suggestions,
        "missing_targets": heuristic["missing_targets"],
        "guidance": guidance,
        "llm": llm_meta,
    }
