#!/usr/bin/env python3
"""Debug script to understand where (255, 1250, 1) values come from."""

import struct
from pathlib import Path

replay_path = r"C:\Users\maxim\OneDrive\Documentos\Assetto Corsa\replay\tatuusfa1_ks_vallelunga_extended_circuit_osrw_180526-230307.acreplay"

with open(replay_path, "rb") as f:
    # Read header
    header_version = struct.unpack("<H", f.read(2))[0]
    print(f"Replay version: {header_version}")
    
    num_frames = struct.unpack("<I", f.read(4))[0]
    num_cars = struct.unpack("<I", f.read(4))[0]
    num_track_objects = struct.unpack("<I", f.read(4))[0]
    
    print(f"Frames: {num_frames}, Cars: {num_cars}, Track Objects: {num_track_objects}")
    
    # Skip to first car Kevin (car_index=1)
    current_pos = f.tell()
    
    # Read driver name strings for all cars
    driver_names = []
    for car_idx in range(num_cars):
        f.seek(current_pos)
        
        # Read car header: num_frames_car (U32), num_wings (U32)
        num_frames_car = struct.unpack("<I", f.read(4))[0]
        num_wings = struct.unpack("<I", f.read(4))[0]
        
        # Read driver name
        name_len = struct.unpack("<I", f.read(4))[0]
        driver_name = f.read(name_len).decode('utf-8', errors='replace')
        
        driver_names.append(driver_name)
        
        # Skip to frame data
        current_pos = f.tell()
        
        # Move to next car header by skipping frames
        # Each frame is 256 bytes
        frame_data_size = num_frames_car * 256
        current_pos += frame_data_size
    
    print(f"\nDriver names:")
    for i, name in enumerate(driver_names):
        print(f"  {i}: {name}")
    
    # Now read Kevin's first frame (car 1)
    print(f"\n=== Kevin's First Frame Analysis ===")
    
    # Reset and navigate to Kevin (car 1)
    f.seek(12)  # Start after header
    
    for car_idx in range(2):  # Cars 0 and 1
        num_frames_car = struct.unpack("<I", f.read(4))[0]
        num_wings = struct.unpack("<I", f.read(4))[0]
        name_len = struct.unpack("<I", f.read(4))[0]
        driver_name = f.read(name_len).decode('utf-8', errors='replace')
        
        if car_idx == 1:
            # This is Kevin
            print(f"Driver: {driver_name}")
            print(f"Frames: {num_frames_car}, Wings: {num_wings}")
            
            # Read first frame (256 bytes)
            frame_bytes = f.read(256)
            
            print(f"\n=== Testing Different Offsets ===")
            for offset in range(210, 235):
                try:
                    # Try reading as U32
                    if offset + 4 <= len(frame_bytes):
                        val_u32 = struct.unpack_from("<I", frame_bytes, offset)[0]
                        # Check if it could be a lap time (1000-300000 ms)
                        if 1000 <= val_u32 <= 300000:
                            print(f"Offset {offset:3d}: U32={val_u32:8d} ✓ POSSIBLE LAP TIME")
                    
                    # Also show as bytes
                    if offset + 4 <= len(frame_bytes):
                        b0, b1, b2, b3 = frame_bytes[offset:offset+4]
                        print(f"Offset {offset:3d}: bytes=[{b0:3d}, {b1:3d}, {b2:3d}, {b3:3d}]  U32={struct.unpack_from('<I', frame_bytes, offset)[0]:8d}")
                except:
                    pass
            
            break
        else:
            # Skip this car's frames
            frame_data_size = num_frames_car * 256
            f.seek(frame_data_size, 1)
