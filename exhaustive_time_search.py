import struct
import sys
sys.path.insert(0, '.')

from src.ac_mcp.acreplay_parser_native import ACReplayParser

replay_path = r"C:\Users\maxim\OneDrive\Documentos\Assetto Corsa\replay\tatuusfa1_ks_vallelunga_extended_circuit_osrw_180526-230307.acreplay"

# First let's use the current parser to get a frame dump
parser = ACReplayParser(replay_path)

# Parse and get the CSV
result = parser.parse_replay(output_path="", target_driver_name="#1 | Kevin Woodward")
csv_path = result["#1 | Kevin Woodward"]['csv_path']

# Read CSV and verify what the current parser is outputting
with open(csv_path, 'r') as f:
    header_line = [l for l in f if not l.startswith('#')][0]
    headers = header_line.strip().split(',')

print("Current parser output:")
print(f"  currentLapTime (index 86): Uses offset 220?")
print(f"  lastLapTime (index 87): Uses offset 220+4=224?")
print(f"  bestLapTime (index 88): Uses offset 220+8=228?")

# Now let's extract the raw frame from the replay directly
with open(replay_path, "rb") as f:
    # Skip to Kevin's first frame using the parser's method
    version = struct.unpack("<I", f.read(4))[0]
    interval = struct.unpack("<d", f.read(8))[0]
    
    # Helper functions
    def read_u32(f):
        return struct.unpack("<I", f.read(4))[0]
    
    def read_f64(f):
        return struct.unpack("<d", f.read(8))[0]
    
    def read_value_string(f):
        length = read_u32(f)
        return f.read(length).decode('utf-8', errors='replace')
    
    weather = read_value_string(f)
    track = read_value_string(f)
    track_config = read_value_string(f)
    num_cars = read_u32(f)
    current_recording_index = read_u32(f)
    num_frames = read_u32(f)
    num_track_objects = read_u32(f)
    
    # Skip track data
    f.seek((2 + 2 + 12 * num_track_objects) * num_frames, 1)
    
    # Skip car 0
    for _ in range(5):
        read_value_string(f)
    num_frames_car0 = read_u32(f)
    num_wings0 = read_u32(f)
    f.seek(20 + (256 + (20 + num_wings0 * 4)) * (num_frames_car0 - 1) + 256 + num_wings0 * 4, 1)
    read_u32(f)  # trailing
    
    # Read Kevin
    for _ in range(5):
        read_value_string(f)
    num_frames_kevin = read_u32(f)
    num_wings_kevin = read_u32(f)
    f.seek(20, 1)
    
    frame_raw = f.read(256)

print("\n=== Testing all 3-U32 combinations from offset 200-240 ===")
print("(Looking for realistic lap times: 5000-250000 ms)")

found_candidates = []
for offset in range(200, 237, 4):
    try:
        vals = struct.unpack_from("<III", frame_raw, offset)
        # Check if this looks like time triplet
        if all(1000 < v < 500000 for v in vals):
            found_candidates.append((offset, vals))
    except:
        pass

if found_candidates:
    print(f"\nFound {len(found_candidates)} candidate time triplets:")
    for offset, (c, l, b) in found_candidates:
        print(f"\n  Offset {offset}:")
        print(f"    Triplet: {c}, {l}, {b}")
        print(f"    As times: {c/1000:.2f}s, {l/1000:.2f}s, {b/1000:.2f}s")
        print(f"    (current > last > best? {c > l > b})")
else:
    print("\nNo clean triplets found. Checking individual values:")
    print("\nAll U32 values in range 1000-500000 in frame bytes 200-240:")
    for offset in range(200, 240):
        try:
            val = struct.unpack_from("<I", frame_raw, offset)[0]
            if 1000 < val < 500000:
                print(f"  Offset {offset}: {val} ({val/1000:.2f}s)")
        except:
            pass
