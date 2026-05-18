from __future__ import annotations

import unittest

from ac_mcp.llm import _extract_json


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


if __name__ == "__main__":
    unittest.main()
