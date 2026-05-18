from __future__ import annotations

import os
import unittest
from pathlib import Path

from ac_mcp.advisor import suggest_changes
from ac_mcp.setup_io import apply_changes, read_setup
from ac_mcp.telemetry import record_session_context


class E2EFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = Path(__file__).parent / "fixtures"
        self.workspace.mkdir(parents=True, exist_ok=True)
        os.environ["AC_SETUP_ROOT"] = str(self.workspace)
        os.environ["AC_SESSION_LOG_ROOT"] = str(self.workspace / "session_logs")
        os.environ["AC_LLM_PROVIDER"] = "disabled"

        self.setup_file = self.workspace / "e2e_setup.ini"
        self.setup_file.write_text(
            """[SUSPENSION]\nARB_FRONT = 6\nARB_REAR = 6\n\n[DIFF]\nDIFF_POWER = 30\nDIFF_COAST = 20\n\n[BRAKES]\nBRAKE_BIAS = 60\n""",
            encoding="utf-8",
        )

    def test_full_flow(self) -> None:
        current = read_setup("e2e_setup.ini")
        suggestion = suggest_changes(
            setup=current["sections"],
            symptoms="sobrevira salida",
            track_conditions="frio",
            use_llm=True,
        )

        self.assertGreater(len(suggestion["suggested_changes"]), 0)

        dry_run = apply_changes(
            path="e2e_setup.ini",
            changes=suggestion["suggested_changes"],
            dry_run=True,
        )
        self.assertFalse(dry_run["written"])

        committed = apply_changes(
            path="e2e_setup.ini",
            changes=suggestion["suggested_changes"],
            dry_run=False,
            create_backup=True,
        )
        self.assertTrue(committed["written"])
        self.assertTrue(bool(committed["backup_path"]))

        session = record_session_context(
            driver="maxim",
            car="ks_porsche_911_gt3",
            track="spa",
            symptoms="sobrevira salida",
            track_conditions="frio",
            lap_time_seconds=131.2,
            notes="e2e test",
        )
        self.assertTrue(session["saved"])


if __name__ == "__main__":
    unittest.main()
