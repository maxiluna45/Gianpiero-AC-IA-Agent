import struct
import sys
sys.path.insert(0, '.')

from src.ac_mcp.acreplay_parser_native import (
    _read_exact, _read_u32, _read_f64, _read_string, 
    _read_value_string
)

replay_path = r"C:\Users\maxim\OneDrive\Documentos\Assetto Corsa\replay\tatuusfa1_ks_vallelunga_extended_circuit_osrw_180526-230307.acreplay"

with open(replay_path, "rb") as f:
    # Skip to Kevin (following same logic as before)
    _read_u32(f)  # version
    _read_f64(f)  # interval
    _read_value_string(f)  # weather
    _read_value_string(f)  # track
    _read_value_string(f)  # track_config
    num_cars = _read_u32(f)
    _read_u32(f)  # current_recording_index
    num_frames = _read_u32(f)
    num_track_objects = _read_u32(f)
    
    f.seek((2 + 2 + 12 * num_track_objects) * num_frames, 1)
    
    # Skip car 0
    for _ in range(5):
        _read_value_string(f)
    num_frames_car0 = _read_u32(f)
    num_wings0 = _read_u32(f)
    f.seek(20 + (256 + (20 + num_wings0 * 4)) * (num_frames_car0 - 1) + 256 + num_wings0 * 4, 1)
    _read_u32(f)  # trailing
    
    # Read Kevin
    for _ in range(5):
        _read_value_string(f)
    num_frames_kevin = _read_u32(f)
    num_wings_kevin = _read_u32(f)
    f.seek(20, 1)
    
    frame_bytes = _read_exact(f, 256)
    
    print("=== Looking for time triplets (current_lap_time, last_lap_time, best_lap_time) ===")
    print("\nTesting possible time offset patterns:\n")
    
    # Try different offset combinations
    patterns = [
        (206, "3x U32 @ 206"),
        (210, "3x U32 @ 210"),  
        (214, "3x U32 @ 214"),
        (218, "3x U32 @ 218"),
        (220, "3x U32 @ 220 (current offset in parser)"),
    ]
    
    for offset, desc in patterns:
        try:
            vals = struct.unpack_from("<III", frame_bytes, offset)
            print(f"{desc}: {vals}")
            print(f"  As times: {vals[0]//1000:.2f}s, {vals[1]//1000:.2f}s, {vals[2]//1000:.2f}s")
            print()
        except:
            print(f"{desc}: ERROR\n")
    
    # Also look at what comes BEFORE offset 212
    print("\n=== Bytes before offset 212 ===")
    for off in range(200, 212, 4):
        val = struct.unpack_from("<I", frame_bytes, off)[0]
        f_val = struct.unpack_from("<f", frame_bytes, off)[0]
        print(f"Offset {off}: U32={val}, F32={f_val:.6f}")
