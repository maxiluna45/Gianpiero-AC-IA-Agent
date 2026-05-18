from __future__ import annotations

import os
import unittest
from pathlib import Path

from ac_mcp.setup_io import apply_changes, compare_setups, list_setups, read_setup


class SetupIoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = Path(__file__).parent / "fixtures"
        self.workspace.mkdir(parents=True, exist_ok=True)
        os.environ["AC_SETUP_ROOT"] = str(self.workspace)

        self.base = self.workspace / "base.ini"
        self.candidate = self.workspace / "candidate.ini"

        self.base.write_text(
            """[SUSPENSION]\nARB_FRONT = 6\nARB_REAR = 5\n\n[DIFF]\nDIFF_POWER = 30\n""",
            encoding="utf-8",
        )
        self.candidate.write_text(
            """[SUSPENSION]\nARB_FRONT = 5\nARB_REAR = 5\n\n[DIFF]\nDIFF_POWER = 32\n""",
            encoding="utf-8",
        )

        nat_dir = self.workspace / "tatuusfa1" / "ks_brands_hatch"
        nat_dir.mkdir(parents=True, exist_ok=True)
        (nat_dir / "tatuus - brands hatch.ini").write_text(
            "[DIFF_POWER]\nVALUE=20\n",
            encoding="utf-8",
        )

    def test_apply_changes_dry_run(self) -> None:
        result = apply_changes(
            path="base.ini",
            dry_run=True,
            changes=[{"section": "SUSPENSION", "key": "ARB_REAR", "delta": -1}],
        )

        self.assertFalse(result["written"])
        self.assertEqual(result["applied"][0]["new_value"], "4")

        after = read_setup("base.ini")
        self.assertEqual(after["sections"]["SUSPENSION"]["ARB_REAR"], "5")

    def test_compare_setups(self) -> None:
        comparison = compare_setups("base.ini", "candidate.ini")
        self.assertEqual(comparison["difference_count"], 2)

    def test_apply_changes_ac_section_value_format(self) -> None:
        ac_style = self.workspace / "ac_style.ini"
        ac_style.write_text(
            """[DIFF_POWER]\nVALUE = 20\n\n[ARB_REAR]\nVALUE = 25000\n""",
            encoding="utf-8",
        )

        result = apply_changes(
            path="ac_style.ini",
            dry_run=True,
            changes=[
                {"section": "DIFF_POWER", "key": "VALUE", "delta": -3},
                {"section": "ARB_REAR", "key": "VALUE", "delta": -1},
            ],
        )

        mapped = {(x["section"], x["key"]): x["new_value"] for x in result["applied"]}
        self.assertEqual(mapped[("DIFF_POWER", "VALUE")], "17")
        self.assertEqual(mapped[("ARB_REAR", "VALUE")], "24999")

    def test_apply_changes_writes_new_version_file(self) -> None:
        ac_style = self.workspace / "versioned.ini"
        ac_style.write_text("[DIFF_POWER]\nVALUE=20\n", encoding="utf-8")

        result = apply_changes(
            path="versioned.ini",
            dry_run=False,
            save_as_new_version=True,
            create_backup=False,
            changes=[{"section": "DIFF_POWER", "key": "VALUE", "delta": -2}],
        )

        self.assertTrue(result["written"])
        self.assertRegex(result["path"], r"versioned_v\d{3}\.ini$")

        original = read_setup("versioned.ini")
        self.assertEqual(original["sections"]["DIFF_POWER"]["VALUE"], "20")

        created_name = Path(result["path"]).name
        created = read_setup(created_name)
        self.assertEqual(created["sections"]["DIFF_POWER"]["VALUE"], "18")

        created_raw = (self.workspace / created_name).read_text(encoding="utf-8")
        self.assertIn("VALUE=18", created_raw)
        self.assertNotIn("VALUE = 18", created_raw)

    def test_list_setups_accepts_natural_language_car_and_track(self) -> None:
        items = list_setups(car="tatuus fa1", track="brands hatch")
        self.assertGreaterEqual(len(items), 1)
        self.assertTrue(any("tatuusfa1/ks_brands_hatch" in item["path"] for item in items))


if __name__ == "__main__":
    unittest.main()
