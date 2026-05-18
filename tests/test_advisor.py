from __future__ import annotations

import unittest

from ac_mcp.advisor import suggest_changes


class AdvisorTests(unittest.TestCase):
    def test_oversteer_exit_generates_changes(self) -> None:
        setup = {
            "SUSPENSION": {"ARB_REAR": "6"},
            "DIFF": {"DIFF_POWER": "30"},
        }

        result = suggest_changes(setup=setup, symptoms="sobrevira salida", track_conditions="", use_llm=False)
        self.assertGreaterEqual(len(result["suggested_changes"]), 1)

    def test_cold_track_reduces_pressure(self) -> None:
        setup = {"TYRES": {"PRESSURE_LF": "26.0", "PRESSURE_RF": "26.0"}}
        result = suggest_changes(setup=setup, symptoms="", track_conditions="frio", use_llm=False)
        deltas = [x["delta"] for x in result["suggested_changes"]]
        self.assertTrue(all(delta < 0 for delta in deltas))

    def test_ac_section_value_format_generates_changes(self) -> None:
        setup = {
            "ARB_REAR": {"VALUE": "25000"},
            "DIFF_POWER": {"VALUE": "20"},
        }
        result = suggest_changes(setup=setup, symptoms="sobrevira salida", track_conditions="", use_llm=False)
        self.assertGreaterEqual(len(result["suggested_changes"]), 1)
        self.assertTrue(any(x["key"] == "VALUE" for x in result["suggested_changes"]))

    def test_ac_pressure_sections_detected(self) -> None:
        setup = {
            "PRESSURE_LF": {"VALUE": "18"},
            "PRESSURE_RF": {"VALUE": "18"},
        }
        result = suggest_changes(setup=setup, symptoms="", track_conditions="frio", use_llm=False)
        deltas = [x["delta"] for x in result["suggested_changes"]]
        self.assertTrue(all(delta < 0 for delta in deltas))


if __name__ == "__main__":
    unittest.main()
