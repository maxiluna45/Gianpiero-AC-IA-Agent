import struct
import sys
sys.path.insert(0, '.')

from src.ac_mcp.acreplay_parser_native import ACReplayParser

replay_path = r"C:\Users\maxim\OneDrive\Documentos\Assetto Corsa\replay\tatuusfa1_ks_vallelunga_extended_circuit_osrw_180526-230307.acreplay"

# Use the parser to export Kevin's CSV
parser = ACReplayParser(replay_path)
result = parser.parse_replay(output_path="", target_driver_name="#1 | Kevin Woodward")

print("=== Kevin's Replay Parsed ===")
for driver, data in result.items():
    print(f"Driver: {driver}")
    print(f"  CSV: {data['csv_path']}")
    print(f"  Frames: {data['frames']}")
    
    # Now read the CSV and check the time values
    csv_path = data['csv_path']
    with open(csv_path, 'r') as f:
        lines = [l for l in f if not l.startswith('#')]
        rows = [l.strip() for l in lines if l.strip()]
    
    # Get header
    header_fields = rows[0].split(',')
    
    # Find time column indices
    time_indices = {}
    for idx, field in enumerate(header_fields):
        if 'Lap' in field or 'lapTime' in field:
            time_indices[field] = idx
    
    print(f"\n  Time fields in CSV:")
    for name, idx in sorted(time_indices.items(), key=lambda x: x[1]):
        print(f"    [{idx}] {name}")
    
    # Read first data row
    data_row = rows[1].split(',')
    print(f"\n  First row time values:")
    for name, idx in sorted(time_indices.items(), key=lambda x: x[1]):
        try:
            val = float(data_row[idx]) if idx < len(data_row) else "N/A"
            print(f"    {name}: {val}")
        except:
            print(f"    {name}: {data_row[idx] if idx < len(data_row) else 'N/A'}")
    
    # Check a few more rows
    print(f"\n  Checking more rows for time patterns:")
    for row_idx in [10, 50, 100, 500, 1000]:
        if row_idx < len(rows):
            data_row = rows[row_idx].split(',')
            curr_lap = data_row[header_fields.index('currentLap')]
            curr_time = data_row[header_fields.index('currentLapTime')]
            last_time = data_row[header_fields.index('lastLapTime')]
            best_time = data_row[header_fields.index('bestLapTime')]
            print(f"    Row {row_idx}: lap={curr_lap}, current={curr_time}, last={last_time}, best={best_time}")
