from src.ac_mcp.acreplay_parser_native import ACReplayParser

replay_path = r"C:\Users\maxim\OneDrive\Documentos\Assetto Corsa\replay\tatuusfa1_ks_vallelunga_extended_circuit_osrw_180526-230307.acreplay"

parser = ACReplayParser(replay_path)
info = parser.inspect_replay()

drivers = info['drivers']
for i, driver in enumerate(drivers):
    print(f"Car {i}: {driver['driver_name']}")
    if "Kevin" in driver['driver_name']:
        print(f"  ✓ FOUND KEVIN AT INDEX {i}")
        print(f"  Frames: {driver['num_frames']}")
        print(f"  Wings: {driver['num_wings']}")
