import struct
from pathlib import Path

csp_path = Path(r"C:\HornerAI\horner-cscape-mcp\artifacts\projects\TankLevel_P4_REDO\TankLevel_P4_REDO.csp")
data = bytearray(csp_path.read_bytes())

old_hi = b"SP HI 65 cm"
new_hi = b"SP HI 75 cm"
old_st = b"HI := TankLevelPV >= 65.0;"
new_st = b"HI := TankLevelPV >= 75.0;"

assert old_hi in data
assert old_st in data

idx1 = data.find(old_hi)
data[idx1 : idx1 + len(old_hi)] = new_hi

idx2 = data.find(old_st)
data[idx2 : idx2 + len(old_st)] = new_st

csp_path.write_bytes(data)
print(f"Patched {csp_path.name} cleanly with 35/75 limits.")
