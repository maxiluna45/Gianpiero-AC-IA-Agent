#!/usr/bin/env python3
from src.ac_mcp.acreplay_parser_native import ACReplayParser
import csv

replay_path = r"C:\Users\maxim\OneDrive\Documentos\Assetto Corsa\replay\tatuusfa1_ks_vallelunga_extended_circuit_osrw_180526-230307.acreplay"

# Parse the replay
parser = ACReplayParser(replay_path)
result = parser.parse_replay()

if result:
    print(f"Drivers found in replay:")
    for driver, info in result.items():
        print(f"  - {driver} (frames: {info['frames']})")
        
    # Now check the times in the CSV
    print("\n" + "="*70)
    print("Validando tiempos de vuelta extraídos (offset 218)")
    print("="*70)
    
    for driver, info in result.items():
        csv_path = info['csv_path']
        with open(csv_path, 'r') as f:
            reader = csv.reader(f)
            header = next(reader)
            rows = list(reader)
        
        print(f"\n{driver}:")
        print(f"  Total frames: {len(rows)}")
        
        # Find the time columns
        try:
            clap_idx = header.index('currentLapTime')
            llap_idx = header.index('lastLapTime')
            blap_idx = header.index('bestLapTime')
        except ValueError as e:
            print(f"  Error finding columns: {e}")
            continue
        
        print(f"  Índices: currentLapTime={clap_idx}, lastLapTime={llap_idx}, bestLapTime={blap_idx}")
        print(f"\n  Sample de 5 frames (currentLapTime, lastLapTime, bestLapTime en ms):")
        
        for i in [0, len(rows)//4, len(rows)//2, 3*len(rows)//4, len(rows)-1]:
            if i < len(rows):
                try:
                    clap = int(float(rows[i][clap_idx])) if rows[i][clap_idx] else 0
                    llap = int(float(rows[i][llap_idx])) if rows[i][llap_idx] else 0
                    blap = int(float(rows[i][blap_idx])) if rows[i][blap_idx] else 0
                    print(f"    Frame {i:5d}: currentLap={clap:8d}ms  lastLap={llap:8d}ms  bestLap={blap:8d}ms")
                except (ValueError, IndexError) as e:
                    print(f"    Frame {i:5d}: Error - {e}")
else:
    print("No drivers found")
print(f"Generated: {csv_path}")

# Read and check first few values
with open(csv_path, 'r') as f:
    lines = [l for l in f if not l.startswith('#')]
    for i, line in enumerate(lines[:6]):
        if i == 0:
            print("Header fields (time-related):")
            fields = line.split(',')
            for idx in [86, 87, 88]:
                print(f"  [{idx}] {fields[idx]}")
        else:
            fields = line.split(',')
            print(f"Row {i}: current={fields[86]}, last={fields[87]}, best={fields[88]}")
