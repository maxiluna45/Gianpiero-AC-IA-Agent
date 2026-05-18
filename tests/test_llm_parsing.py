from __future__ import annotations

import unittest

from ac_mcp.llm import _extract_json
from ac_mcp.llm import _normalize_llm_changes
from ac_mcp.llm import LlmChange


class LlmParsingTests(unittest.TestCase):
    def test_extract_direct_json(self) -> None:
        data = _extract_json('{"summary":"ok","suggested_changes":[]}')
        self.assertEqual(data["summary"], "ok")

    def test_extract_fenced_json(self) -> None:
        text = """```json\n{\"summary\":\"ok\",\"suggested_changes\":[]}\n```"""
        data = _extract_json(text)
        self.assertEqual(data["summary"], "ok")

    def test_extract_json_from_wrapped_text(self) -> None:
        text = "Resultado:\n{\"summary\":\"ok\",\"suggested_changes\":[]}\nFin"
        data = _extract_json(text)
        self.assertEqual(data["summary"], "ok")

    def test_normalize_changes_resolves_target_and_confidence(self) -> None:
        setup = {"BRAKES": {"BRAKE_BIAS": "60"}}
        changes = [
            LlmChange(
                section="BRAKE_BIAS",
                key="VALUE",
                delta=-1.0,
                reason="fuzzy target",
                confidence=0.9,
            )
        ]

        normalized = _normalize_llm_changes(setup=setup, changes=changes)
        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0]["section"], "BRAKES")
        self.assertEqual(normalized[0]["key"], "BRAKE_BIAS")
        self.assertEqual(normalized[0]["confidence"], 0.9)


if __name__ == "__main__":
    unittest.main()
