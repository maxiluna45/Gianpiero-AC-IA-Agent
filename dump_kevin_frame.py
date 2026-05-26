import struct
import sys
sys.path.insert(0, '.')

from src.ac_mcp.acreplay_parser_native import (
    _read_exact, _read_u32, _read_f64, _read_string, 
    _read_value_string, ReplayHeader
)

replay_path = r"C:\Users\maxim\OneDrive\Documentos\Assetto Corsa\replay\tatuusfa1_ks_vallelunga_extended_circuit_osrw_180526-230307.acreplay"

with open(replay_path, "rb") as f:
    # Read header
    version = _read_u32(f)
    interval = _read_f64(f)
    weather = _read_value_string(f)
    track = _read_value_string(f)
    track_config = _read_value_string(f)
    num_cars = _read_u32(f)
    current_recording_index = _read_u32(f)
    num_frames = _read_u32(f)
    num_track_objects = _read_u32(f)
    
    print(f"Num frames: {num_frames}, Num cars: {num_cars}, Track objects: {num_track_objects}")
    
    # Skip track data
    f.seek((2 + 2 + 12 * num_track_objects) * num_frames, 1)
    
    # Skip to Kevin (car index 1)
    # First car (Maximiliano Luna)
    car_id = _read_value_string(f)
    driver_name = _read_value_string(f)
    nation = _read_value_string(f)
    team = _read_value_string(f)
    skin = _read_value_string(f)
    num_frames_car1 = _read_u32(f)
    num_wings1 = _read_u32(f)
    
    print(f"Car 0: {driver_name}, frames={num_frames_car1}, wings={num_wings1}")
    
    # Skip car 0 data
    f.seek(20 + (256 + (20 + num_wings1 * 4)) * (num_frames_car1 - 1) + 256 + num_wings1 * 4, 1)
    trailing_count = _read_u32(f)
    if trailing_count > 0:
        f.seek(trailing_count * 8, 1)
    
    # Now read Kevin (car index 1)
    car_id = _read_value_string(f)
    driver_name = _read_value_string(f)
    nation = _read_value_string(f)
    team = _read_value_string(f)
    skin = _read_value_string(f)
    num_frames_kevin = _read_u32(f)
    num_wings_kevin = _read_u32(f)
    
    print(f"\nCar 1 (Kevin): {driver_name}, frames={num_frames_kevin}, wings={num_wings_kevin}")
    
    # Skip to first frame data
    f.seek(20, 1)
    
    # Read Kevin's first frame
    frame_bytes = _read_exact(f, 256)
    
    print(f"\n=== Kevin's First Frame (256 bytes) ===")
    print("\nLooking for lap time values in different offsets:")
    print("(Lap times should be in range 1000-300000 ms for F1 cars)")
    
    found_times = []
    for offset in range(200, 232):
        try:
            val_u32 = struct.unpack_from("<I", frame_bytes, offset)[0]
            if 1000 < val_u32 < 500000:  # Reasonable lap time range
                found_times.append((offset, val_u32))
        except:
            pass
    
    if found_times:
        print("\nPossible lap time values:")
        for offset, val in found_times:
            print(f"  Offset {offset}: {val} ms ({val/1000:.2f}s)")
    
    # Also try reading from different byte positions
    print("\n=== Raw byte dump (200-232) ===")
    print("Offset | Bytes (hex)                 | U8  U8  U8  U8 | U32       | F32")
    for offset in range(200, 233, 4):
        if offset + 3 < 256:
            bytes_hex = ' '.join(f'{frame_bytes[i]:02x}' for i in range(offset, min(offset+4, 256)))
            u32_val = struct.unpack_from("<I", frame_bytes, offset)[0] if offset + 3 < 256 else 0
            f32_val = struct.unpack_from("<f", frame_bytes, offset)[0] if offset + 3 < 256 else 0.0
            u8_vals = ' '.join(str(frame_bytes[i]) for i in range(offset, min(offset+4, 256)))
            print(f"{offset:3d}    | {bytes_hex:26s} | {u8_vals:11s} | {u32_val:9d} | {f32_val:8.4f}")
