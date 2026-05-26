from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from ac_mcp.acreplay_parser_native import ACReplayParser


def _pack_value_string(value: str) -> bytes:
    payload = value.encode("utf-8")
    return struct.pack("<I", len(payload)) + payload


def _build_minimal_replay(path: Path, driver_name: str) -> None:
    frame = bytearray(256)
    struct.pack_into("<fff", frame, 0, 1.0, 2.0, 3.0)
    struct.pack_into("<III", frame, 220, 12345, 54321, 22222)
    frame[232] = 90
    frame[233] = 10
    frame[234] = 3
    frame[244] = 120
    frame[245] = 40
    frame[246] = 2
    struct.pack_into("<H", frame, 248, 0x1008)
    frame[252] = 12
    frame[253] = 200
    frame[254] = 8

    data = bytearray()
    data += struct.pack("<I", 16)
    data += struct.pack("<d", 16.0)
    data += _pack_value_string("clear")
    data += _pack_value_string("spa")
    data += _pack_value_string("gp")
    data += struct.pack("<I", 1)
    data += struct.pack("<I", 1)
    data += struct.pack("<I", 1)
    data += struct.pack("<I", 0)

    data += b"\x00" * 4

    data += _pack_value_string("ks_test_car")
    data += _pack_value_string(driver_name)
    data += _pack_value_string("ES")
    data += _pack_value_string("Team")
    data += _pack_value_string("skin_01")
    data += struct.pack("<I", 1)
    data += struct.pack("<I", 0)

    data += b"\x00" * 20
    data += frame
    data += struct.pack("<I", 0)

    path.write_bytes(data)


class ACReplayParserNativeTests(unittest.TestCase):
    def test_parse_replay_exports_sanitized_csv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            replay_path = temp_path / "session.acreplay"
            driver_name = "01|Maxim:GT3"
            _build_minimal_replay(replay_path, driver_name)

            parser = ACReplayParser(str(replay_path))
            result = parser.parse_replay()

            self.assertIn(driver_name, result)
            csv_path = Path(str(result[driver_name]["csv_path"]))
            self.assertTrue(csv_path.exists())
            self.assertNotIn("|", csv_path.name)
            self.assertNotIn(":", csv_path.name)

            content = csv_path.read_text(encoding="utf-8")
            self.assertIn("# numFrames 1", content)
            self.assertIn("position.x", content)


if __name__ == "__main__":
    unittest.main()