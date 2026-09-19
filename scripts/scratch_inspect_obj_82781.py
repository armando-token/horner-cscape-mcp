from pathlib import Path

csp_path = Path(r"C:\HornerAI\horner-cscape-mcp\artifacts\projects\TankLevel_P4_REDO\TankLevel_P4_REDO.csp")
data = csp_path.read_bytes()

idx = 82781
print(f"Data around {idx}:")
print("Hex:\n", data[idx-50:idx+60].hex())
print("Repr:\n", data[idx-50:idx+60])
