from __future__ import annotations

import os
import unittest
from pathlib import Path

from ac_mcp.pipeline import start_from_base_pipeline


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = Path(__file__).parent / "fixtures" / "pipeline"
        self.workspace.mkdir(parents=True, exist_ok=True)
        os.environ["AC_SETUP_ROOT"] = str(self.workspace)
        os.environ["AC_LLM_PROVIDER"] = "disabled"

        (self.workspace / "mclaren_720s_gt3_evo" / "generic").mkdir(parents=True, exist_ok=True)
        (self.workspace / "mclaren_720s_gt3_evo" / "generic" / "last.ini").write_text(
            """[ARB_REAR]\nVALUE=25000\n\n[DIFF_POWER]\nVALUE=20\n\n[PRESSURE_LF]\nVALUE=18\n\n[PRESSURE_RF]\nVALUE=18\n""",
            encoding="utf-8",
        )

    def test_pipeline_dry_run_heuristic_only(self) -> None:
        result = start_from_base_pipeline(
            car="mclaren_720s_gt3_evo",
            track="spa",
            symptoms="sobrevira salida",
            track_conditions="",
            dry_run=True,
            llm_required=False,
        )
        self.assertGreaterEqual(result["changes_count"], 1)
        self.assertFalse(result["apply"]["written"])

    def test_pipeline_llm_required_fails_when_disabled(self) -> None:
        with self.assertRaises(RuntimeError):
            start_from_base_pipeline(
                car="mclaren_720s_gt3_evo",
                track="spa",
                symptoms="sobrevira salida",
                track_conditions="",
                dry_run=True,
                llm_required=True,
            )

    def test_pipeline_writes_new_version_file(self) -> None:
        result = start_from_base_pipeline(
            car="mclaren_720s_gt3_evo",
            track="spa",
            symptoms="sobrevira salida",
            track_conditions="",
            dry_run=False,
            llm_required=False,
            confirm=True,
            save_as_new_version=True,
            create_backup=False,
        )

        self.assertTrue(result["apply"]["written"])
        self.assertRegex(str(result["apply"]["path"]), r"last_v\d{3}\.ini$")


if __name__ == "__main__":
    unittest.main()
