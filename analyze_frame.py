import struct

replay_path = r"C:\Users\maxim\OneDrive\Documentos\Assetto Corsa\replay\tatuusfa1_ks_vallelunga_extended_circuit_osrw_180526-230307.acreplay"

with open(replay_path, "rb") as f:
    # Skip header
    version = struct.unpack("<I", f.read(4))[0]
    interval = struct.unpack("<d", f.read(8))[0]
    
    # Skip weather, track, track_config strings
    for _ in range(3):
        str_len = struct.unpack("<I", f.read(4))[0]
        f.read(str_len)
    
    num_cars = struct.unpack("<I", f.read(4))[0]
    current_recording_index = struct.unpack("<I", f.read(4))[0]
    num_frames = struct.unpack("<I", f.read(4))[0]
    num_track_objects = struct.unpack("<I", f.read(4))[0]
    
    print(f"Num frames: {num_frames}, Num cars: {num_cars}, Num track objects: {num_track_objects}")
    
    # Skip to first car
    f.seek((2 + 2 + 12 * num_track_objects) * num_frames, 1)
    
    # Read first car header
    car_id_len = struct.unpack("<I", f.read(4))[0]
    car_id = f.read(car_id_len).decode('utf-8', errors='replace')
    
    driver_name_len = struct.unpack("<I", f.read(4))[0]
    driver_name = f.read(driver_name_len).decode('utf-8', errors='replace')
    
    print(f"Car ID: {car_id}, Driver: {driver_name}")
    
    # Skip other header fields
    for _ in range(4):
        str_len = struct.unpack("<I", f.read(4))[0]
        f.read(str_len)
    
    num_frames_car = struct.unpack("<I", f.read(4))[0]
    num_wings = struct.unpack("<I", f.read(4))[0]
    
    print(f"Num frames for car: {num_frames_car}, Num wings: {num_wings}")
    
    # Read first CarFrame (256 bytes)
    frame_bytes = f.read(256)
    print(f"\nFirst CarFrame size: {len(frame_bytes)} bytes")
    
    # Try to extract time values at different offsets
    print("\n=== Analyzing time fields ===")
    for offset in range(200, 245, 4):
        try:
            val_u32 = struct.unpack_from("<I", frame_bytes, offset)[0]
            val_f32 = struct.unpack_from("<f", frame_bytes, offset)[0]
            val_u8 = frame_bytes[offset] if offset < len(frame_bytes) else -1
            print(f"Offset {offset:3d}: U32={val_u32:12d} F32={val_f32:12.6f} U8={val_u8}")
        except:
            pass
    
    # Try reading 3 consecutive U32 at different offsets (for current, last, best)
    print("\n=== Looking for 3 U32 time values ===")
    for offset in range(200, 240, 4):
        try:
            times = struct.unpack_from("<III", frame_bytes, offset)
            if any(t > 1000 and t < 600000 for t in times):  # reasonable range for lap times
                print(f"Offset {offset}: Times = {times}")
        except:
            pass
