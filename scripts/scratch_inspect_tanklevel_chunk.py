import sys
sys.path.insert(0, ".")
from pathlib import Path
from src.cscape.cfbf import extract_cfbf_streams

csp_path = Path(r"C:\HornerAI\horner-cscape-mcp\artifacts\projects\TankLevel_P4_REDO\TankLevel_P4_REDO.csp")
streams = extract_cfbf_streams(csp_path)
contents = streams["Contents"]

idx = contents.find(b"Tank Level")
print(f"Index of 'Tank Level': {idx}")
chunk = contents[idx-100:idx+150]
print("Hex:\n", chunk.hex())
print("Repr:\n", chunk)
