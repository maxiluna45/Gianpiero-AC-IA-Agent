from __future__ import annotations

import os
import unittest
from pathlib import Path

from ac_mcp.setup_io import find_base_setup


class BaseSetupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = Path(__file__).parent / "fixtures" / "base_setup"
        self.workspace.mkdir(parents=True, exist_ok=True)
        os.environ["AC_SETUP_ROOT"] = str(self.workspace)

        (self.workspace / "mclaren_720s_gt3_evo" / "generic").mkdir(parents=True, exist_ok=True)
        (self.workspace / "mclaren_720s_gt3_evo" / "spa").mkdir(parents=True, exist_ok=True)

        (self.workspace / "mclaren_720s_gt3_evo" / "generic" / "last.ini").write_text(
            "[DIFF_POWER]\nVALUE=20\n",
            encoding="utf-8",
        )
        (self.workspace / "mclaren_720s_gt3_evo" / "spa" / "From Julio Coria.ini").write_text(
            "[DIFF_POWER]\nVALUE=18\n",
            encoding="utf-8",
        )

        (self.workspace / "tatuusfa1" / "ks_brands_hatch").mkdir(parents=True, exist_ok=True)
        (self.workspace / "tatuusfa1" / "ks_brands_hatch" / "tatuus - brands hatch.ini").write_text(
            "[DIFF_POWER]\nVALUE=17\n",
            encoding="utf-8",
        )

    def test_find_base_prefers_track_specific(self) -> None:
        result = find_base_setup(car="mclaren_720s_gt3_evo", track="spa")
        self.assertTrue(result["found"])
        self.assertIn("spa/From Julio Coria.ini", result["recommended"])

    def test_find_base_falls_back_to_generic(self) -> None:
        result = find_base_setup(car="mclaren_720s_gt3_evo", track="imola")
        self.assertTrue(result["found"])
        self.assertIn("generic/last.ini", result["recommended"])

    def test_find_base_accepts_natural_language(self) -> None:
        result = find_base_setup(car="tatuus fa1", track="brands hatch")
        self.assertTrue(result["found"])
        self.assertIn("tatuusfa1/ks_brands_hatch", result["recommended"])


if __name__ == "__main__":
    unittest.main()
