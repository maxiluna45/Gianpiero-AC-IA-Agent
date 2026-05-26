"""Native .acreplay v16 parser implemented in pure Python.

This module mirrors the core behavior of the C++ parser:
- reads replay header and per-car frame blocks
- exports one CSV per driver
- sanitizes output filenames for Windows compatibility

It intentionally avoids depending on the external acrp.exe binary.
"""

from __future__ import annotations

import argparse
import csv
import re
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO


POSTFIX_STR = b"__AC_SHADERS_PATCH_v1__"
DRIVER_NAME_INI_STR = "DRIVER_NAME="
EXTENSION = "csv"

CAR_FRAME_LABEL = (
    "frame,"
    "position.x,position.y,position.z,"
    "rotation.x,rotation.y,rotation.z,"
    "velocity.x,velocity.y,velocity.z,"
    "wheelFL.staticPosition.x,wheelFL.staticPosition.y,wheelFL.staticPosition.z,"
    "wheelFR.staticPosition.x,wheelFR.staticPosition.y,wheelFR.staticPosition.z,"
    "wheelRL.staticPosition.x,wheelRL.staticPosition.y,wheelRL.staticPosition.z,"
    "wheelRR.staticPosition.x,wheelRR.staticPosition.y,wheelRR.staticPosition.z,"
    "wheelFL.staticRotation.x,wheelFL.staticRotation.y,wheelFL.staticRotation.z,"
    "wheelFR.staticRotation.x,wheelFR.staticRotation.y,wheelFR.staticRotation.z,"
    "wheelRL.staticRotation.x,wheelRL.staticRotation.y,wheelRL.staticRotation.z,"
    "wheelRR.staticRotation.x,wheelRR.staticRotation.y,wheelRR.staticRotation.z,"
    "wheelFL.position.x,wheelFL.position.y,wheelFL.position.z,"
    "wheelFR.position.x,wheelFR.position.y,wheelFR.position.z,"
    "wheelRL.position.x,wheelRL.position.y,wheelRL.position.z,"
    "wheelRR.position.x,wheelRR.position.y,wheelRR.position.z,"
    "wheelFL.rotation.x,wheelFL.rotation.y,wheelFL.rotation.z,"
    "wheelFR.rotation.x,wheelFR.rotation.y,wheelFR.rotation.z,"
    "wheelRL.rotation.x,wheelRL.rotation.y,wheelRL.rotation.z,"
    "wheelRR.rotation.x,wheelRR.rotation.y,wheelRR.rotation.z,"
    "wheelFL.angularVelocity,wheelFR.angularVelocity,wheelRL.angularVelocity,wheelRR.angularVelocity,"
    "wheelFL.slipAngle,wheelFR.slipAngle,wheelRL.slipAngle,wheelRR.slipAngle,"
    "wheelFL.slipRatio,wheelFR.slipRatio,wheelRL.slipRatio,wheelRR.slipRatio,"
    "wheelFL.ndSlip,wheelFR.ndSlip,wheelRL.ndSlip,wheelRR.ndSlip,"
    "wheelFL.load,wheelFR.load,wheelRL.load,wheelRR.load,"
    "wheelFL.dirt,wheelFR.dirt,wheelRL.dirt,wheelRR.dirt,"
    "steerAngle,bodyworkNoise,drivetrainSpeed,"
    "currentLap,currentLapTime,lastLapTime,bestLapTime,"
    "fuel,fuelPerLap,rpm,gear,gas,brake,boost,"
    "damageFrontDeformation,damageFront,damageRear,damageLeft,damageRight,"
    "lights,horn,cameraDir,engineHealth,gearboxBeingDamaged,dirt"
)


@dataclass
class ReplayHeader:
    version: int
    recording_interval: float
    weather: str
    track: str
    track_config: str
    num_cars: int
    current_recording_index: int
    num_frames: int
    num_track_objects: int


@dataclass
class CarHeader:
    car_id: str
    driver_name: str
    nation_code: str
    driver_team: str
    car_skin_id: str
    num_frames: int
    num_wings: int


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    data = stream.read(size)
    if len(data) != size:
        raise EOFError(f"Expected {size} bytes, got {len(data)}")
    return data


def _read_u32(stream: BinaryIO) -> int:
    return struct.unpack("<I", _read_exact(stream, 4))[0]


def _read_f64(stream: BinaryIO) -> float:
    return struct.unpack("<d", _read_exact(stream, 8))[0]


def _read_string(stream: BinaryIO, length: int) -> str:
    return _read_exact(stream, length).decode("utf-8", errors="replace")


def _read_value_string(stream: BinaryIO) -> str:
    return _read_string(stream, _read_u32(stream))


def _sanitize_filename(name: str) -> str:
    sanitized = re.sub(r"[<>:\"/\\|?*]", "_", name).strip()
    return sanitized[:120] or "unknown_driver"


def _ensure_unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    index = 1
    while True:
        candidate = parent / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def _vec3_from(data: bytes, offset: int) -> tuple[float, float, float]:
    return struct.unpack_from("<fff", data, offset)


def _vec3_yxz_half_from(data: bytes, offset: int) -> tuple[float, float, float]:
    y, x, z = struct.unpack_from("<eee", data, offset)
    return (x, y, z)


def _vec3_half_from(data: bytes, offset: int) -> tuple[float, float, float]:
    return struct.unpack_from("<eee", data, offset)


def _parse_car_frame_row(data: bytes, frame_index: int) -> list[object]:
    if len(data) != 256:
        raise ValueError(f"Unexpected CarFrame size: {len(data)} (expected 256)")

    row: list[object] = [frame_index]

    pos = _vec3_from(data, 0)
    rot = _vec3_yxz_half_from(data, 12)
    vel = _vec3_half_from(data, 164)
    row.extend([*pos, *rot, *vel])

    for i in range(4):
        row.extend(_vec3_from(data, 20 + i * 12))
    for i in range(4):
        row.extend(_vec3_yxz_half_from(data, 68 + i * 6))
    for i in range(4):
        row.extend(_vec3_from(data, 92 + i * 12))
    for i in range(4):
        row.extend(_vec3_yxz_half_from(data, 140 + i * 6))

    row.extend(struct.unpack_from("<eeee", data, 172))
    row.extend(struct.unpack_from("<eeee", data, 180))
    row.extend(struct.unpack_from("<eeee", data, 188))
    row.extend(struct.unpack_from("<eeee", data, 196))
    row.extend(struct.unpack_from("<eeee", data, 204))

    steer_angle, bodywork_noise, drivetrain_speed = struct.unpack_from("<eee", data, 212)
    row.extend([steer_angle, bodywork_noise, drivetrain_speed])

    current_lap_time, last_lap_time, best_lap_time = struct.unpack_from("<III", data, 218)

    fuel = data[232]
    fuel_per_lap = data[233]
    gear = data[234]
    tire_dirt = data[235:239]
    damage_front_deformation = data[239]
    damage_rear = data[240]
    damage_left = data[241]
    damage_right = data[242]
    damage_front = data[243]
    gas = data[244]
    brake = data[245]
    current_lap = data[246]

    status = struct.unpack_from("<H", data, 248)[0]
    dirt = data[252]
    engine_health = data[253]
    boost = data[254]
    rpm = struct.unpack_from("<e", data, 170)[0]

    lights = int((status >> 12) & 0x1)
    horn = int((status >> 3) & 0x1)
    camera_dir = int((status >> 4) & 0b11)
    gearbox_being_damaged = int((status >> 9) & 0x1)

    row.extend(
        [
            int(current_lap),
            int(current_lap_time),
            int(last_lap_time),
            int(best_lap_time),
            int(fuel),
            int(fuel_per_lap),
            rpm,
            int(gear),
            int(gas),
            int(brake),
            int(boost),
            int(damage_front_deformation),
            int(damage_front),
            int(damage_rear),
            int(damage_left),
            int(damage_right),
            lights,
            horn,
            camera_dir,
            int(engine_health),
            gearbox_being_damaged,
            int(dirt),
        ]
    )
    return row


class ACReplayParser:
    """Pure Python parser for Assetto Corsa .acreplay v16 files."""

    def __init__(self, replay_path: str):
        self.replay_path = Path(replay_path)
        if not self.replay_path.exists():
            raise FileNotFoundError(f"Replay not found: {self.replay_path}")

    def parse_replay(self, output_path: str = "", target_driver_name: str = "") -> dict[str, dict[str, object]]:
        with self.replay_path.open("rb") as in_file:
            header = self._read_header(in_file)
            in_file.seek((2 + 2 + 12 * header.num_track_objects) * header.num_frames, 1)

            results: dict[str, dict[str, object]] = {}
            for _car_index in range(header.num_cars):
                car_header = self._read_car_header(in_file)

                if target_driver_name and target_driver_name != car_header.driver_name:
                    self._skip_car_data(in_file, car_header)
                    continue

                out_file_path = self._resolve_output_path(
                    preferred_output=output_path,
                    replay_path=self.replay_path,
                    driver_name=car_header.driver_name,
                    multiple_cars=header.num_cars > 1 and not target_driver_name,
                )

                frame_count = self._export_car_csv(in_file, header, car_header, out_file_path)
                results[car_header.driver_name] = {
                    "csv_path": str(out_file_path),
                    "frames": frame_count,
                    "car_id": car_header.car_id,
                    "track": header.track,
                    "track_config": header.track_config,
                    "recording_interval": header.recording_interval,
                    "sanitized_name": _sanitize_filename(car_header.driver_name),
                    "file_size": out_file_path.stat().st_size,
                }

            return results

    def parse(self) -> dict[str, object]:
        results = self.parse_replay()
        return {
            "num_drivers": len(results),
            "drivers": list(results.keys()),
            "outputs": results,
        }

    def inspect_replay(self) -> dict[str, object]:
        with self.replay_path.open("rb") as in_file:
            header = self._read_header(in_file)
            in_file.seek((2 + 2 + 12 * header.num_track_objects) * header.num_frames, 1)

            drivers: list[dict[str, object]] = []
            for _car_index in range(header.num_cars):
                car_header = self._read_car_header(in_file)
                drivers.append(
                    {
                        "driver_name": car_header.driver_name,
                        "car_id": car_header.car_id,
                        "nation_code": car_header.nation_code,
                        "driver_team": car_header.driver_team,
                        "car_skin_id": car_header.car_skin_id,
                        "num_frames": car_header.num_frames,
                        "num_wings": car_header.num_wings,
                    }
                )
                self._skip_car_data(in_file, car_header)

            return {
                "replay_path": str(self.replay_path),
                "version": header.version,
                "recording_interval": header.recording_interval,
                "weather": header.weather,
                "track": header.track,
                "track_config": header.track_config,
                "num_cars": header.num_cars,
                "num_frames": header.num_frames,
                "drivers": drivers,
            }

    def _read_header(self, stream: BinaryIO) -> ReplayHeader:
        version = _read_u32(stream)
        if version != 16:
            raise ValueError(f"Only .acreplay version 16 is supported (got {version})")

        return ReplayHeader(
            version=version,
            recording_interval=_read_f64(stream),
            weather=_read_value_string(stream),
            track=_read_value_string(stream),
            track_config=_read_value_string(stream),
            num_cars=_read_u32(stream),
            current_recording_index=_read_u32(stream),
            num_frames=_read_u32(stream),
            num_track_objects=_read_u32(stream),
        )

    def _read_car_header(self, stream: BinaryIO) -> CarHeader:
        return CarHeader(
            car_id=_read_value_string(stream),
            driver_name=_read_value_string(stream),
            nation_code=_read_value_string(stream),
            driver_team=_read_value_string(stream),
            car_skin_id=_read_value_string(stream),
            num_frames=_read_u32(stream),
            num_wings=_read_u32(stream),
        )

    def _skip_car_data(self, stream: BinaryIO, car_header: CarHeader) -> None:
        stream.seek(20 + (256 + (20 + car_header.num_wings * 4)) * (car_header.num_frames - 1) + 256 + car_header.num_wings * 4, 1)
        trailing_count = _read_u32(stream)
        if trailing_count > 0:
            stream.seek(trailing_count * 8, 1)

    def _resolve_output_path(
        self,
        preferred_output: str,
        replay_path: Path,
        driver_name: str,
        multiple_cars: bool,
    ) -> Path:
        output = Path(preferred_output) if preferred_output else Path()
        as_directory = False
        if preferred_output:
            output_text = str(preferred_output)
            if output_text.endswith("/") or output_text.endswith("\\"):
                as_directory = True
            elif output.exists() and output.is_dir():
                as_directory = True
            elif output.suffix == "":
                # For this parser, a suffix-less path is treated as an output directory.
                as_directory = True

        if not output.name or as_directory:
            base_name = replay_path.stem
            if multiple_cars:
                base_name = f"{base_name}_{_sanitize_filename(driver_name)}"
            base_dir = output if as_directory else (Path.cwd() if preferred_output else replay_path.parent)
            output = base_dir / f"{base_name}.{EXTENSION}"
            output = _ensure_unique_path(output)
        else:
            if multiple_cars:
                output = output.with_name(f"{output.stem}_{_sanitize_filename(driver_name)}{output.suffix or f'.{EXTENSION}'}")
            elif not output.suffix:
                output = output.with_suffix(f".{EXTENSION}")

        output.parent.mkdir(parents=True, exist_ok=True)
        return output

    def _export_car_csv(self, stream: BinaryIO, header: ReplayHeader, car_header: CarHeader, output_path: Path) -> int:
        stream.seek(20, 1)
        with output_path.open("w", encoding="utf-8", newline="") as csv_file:
            writer = csv.writer(csv_file)
            csv_file.write(f"# numFrames {car_header.num_frames}\n")
            csv_file.write(f"# recordingInterval {header.recording_interval}\n")
            writer.writerow(CAR_FRAME_LABEL.split(","))

            for frame_idx in range(car_header.num_frames):
                frame_bytes = _read_exact(stream, 256)
                row = _parse_car_frame_row(frame_bytes, frame_idx)
                writer.writerow(row)

                if frame_idx < car_header.num_frames - 1:
                    stream.seek(20 + car_header.num_wings * 4, 1)
                else:
                    stream.seek(car_header.num_wings * 4, 1)
                    trailing_count = _read_u32(stream)
                    if trailing_count > 0:
                        stream.seek(trailing_count * 8, 1)

        return car_header.num_frames


def main() -> None:
    parser = argparse.ArgumentParser(description="Pure Python .acreplay parser")
    parser.add_argument("replay", help="Path to .acreplay file")
    parser.add_argument("--output", default="", help="Output CSV path or directory")
    parser.add_argument("--driver-name", default="", help="Export only this exact driver name")
    args = parser.parse_args()

    parsed = ACReplayParser(args.replay).parse_replay(output_path=args.output, target_driver_name=args.driver_name)
    if not parsed:
        print("No drivers exported")
        return

    print(f"Exported {len(parsed)} driver(s)")
    for driver, info in parsed.items():
        print(f"- {driver} -> {info['csv_path']} ({info['frames']} frames)")


if __name__ == "__main__":
    main()
