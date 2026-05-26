#!/usr/bin/env python3
"""Regenerate Kevin's replay JSON with corrected offset 218."""

from src.ac_mcp.server import (
    replay_to_shared_memory_json,
    _extract_best_lap_time_ms
)
import json

# Kevin's replay
replay_path = r"C:\Users\maxim\OneDrive\Documentos\Assetto Corsa\replay\tatuusfa1_ks_vallelunga_extended_circuit_osrw_180526-230307.acreplay"

print("=== Converting replay with offset 218 (corrected) ===\n")

result = replay_to_shared_memory_json(replay_path, "#1 | Kevin Woodward")

if result and "json_path" in result:
    json_path = result["json_path"]
    print(f"JSON saved to: {json_path}")
    print(f"Samples: {result['samples']}")
    
    # Read and check lap times
    with open(json_path, 'r') as f:
        data = json.load(f)
    
    samples = data.get("samples", [])
    print(f"\nTotal samples: {len(samples)}")
    
    if samples:
        print("\n=== First 3 samples ===")
        for i in range(min(3, len(samples))):
            s = samples[i]
            print(f"[{i}] i_best_time={s['graphics'].get('i_best_time', '?')}, " + 
                  f"i_last_time={s['graphics'].get('i_last_time', '?')}")
        
        print("\n=== Last sample ===")
        s = samples[-1]
        print(f"i_best_time={s['graphics'].get('i_best_time', '?')}, " + 
              f"i_last_time={s['graphics'].get('i_last_time', '?')}")
        
        # Check the ranges
        best_times = [s['graphics'].get('i_best_time', 0) for s in samples if s['graphics'].get('i_best_time')]
        last_times = [s['graphics'].get('i_last_time', 0) for s in samples if s['graphics'].get('i_last_time')]
        
        print(f"\n=== Time Statistics ===")
        if best_times:
            print(f"Best lap time range: {min(best_times)} - {max(best_times)} ms")
        if last_times:
            print(f"Last lap time range: {min(last_times)} - {max(last_times)} ms")
            print(f"Last lap time median: {sorted(last_times)[len(last_times)//2]} ms")

else:
    print("Failed to convert replay")
