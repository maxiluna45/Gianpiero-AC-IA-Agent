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
    
    # Skip track data
    f.seek((2 + 2 + 12 * num_track_objects) * num_frames, 1)
    
    # Iterate through each car
    for car_idx in range(num_cars):
        # Read car header
        car_id_len = struct.unpack("<I", f.read(4))[0]
        car_id = f.read(car_id_len).decode('utf-8', errors='replace')
        
        driver_name_len = struct.unpack("<I", f.read(4))[0]
        driver_name = f.read(driver_name_len).decode('utf-8', errors='replace')
        
        # Skip other header fields
        for _ in range(4):
            str_len = struct.unpack("<I", f.read(4))[0]
            f.read(str_len)
        
        num_frames_car = struct.unpack("<I", f.read(4))[0]
        num_wings = struct.unpack("<I", f.read(4))[0]
        
        print(f"\nCar {car_idx}: {driver_name}")
        
        if "#1 | Kevin Woodward" in driver_name:
            print(f"  ✓ FOUND KEVIN!")
            print(f"  Num frames: {num_frames_car}, Num wings: {num_wings}")
            
            # Read first frame
            f.seek(20, 1)  # Skip to frame data
            frame_bytes = f.read(256)
            
            # Analyze offsets for times
            print(f"\n  === Kevin's first frame ===")
            for offset in range(200, 245, 4):
                try:
                    val_u32 = struct.unpack_from("<I", frame_bytes, offset)[0]
                    val_f32 = struct.unpack_from("<f", frame_bytes, offset)[0]
                    if val_u32 < 500000:  # Reasonable lap time range
                        print(f"  Offset {offset:3d}: U32={val_u32:10d} ms ({val_u32/1000:.2f}s)")
                except:
                    pass
            break
        else:
            # Skip car data
            f.seek(20 + (256 + (20 + num_wings * 4)) * (num_frames_car - 1) + 256 + num_wings * 4, 1)
            trailing_count = struct.unpack("<I", f.read(4))[0]
            if trailing_count > 0:
                f.seek(trailing_count * 8, 1)
