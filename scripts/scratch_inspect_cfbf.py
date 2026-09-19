import struct
from pathlib import Path

csp_path = Path(r"C:\HornerAI\horner-cscape-mcp\artifacts\projects\TankLevel_P4_REDO\TankLevel_P4_REDO.csp")
data = bytearray(csp_path.read_bytes())

sec_size = 512
first_dir = struct.unpack_from("<I", data, 48)[0]
dir_offset = (first_dir + 1) * sec_size

for i in range(4):
    entry_off = dir_offset + i * 128
    block = data[entry_off:entry_off+128]
    nlen = struct.unpack_from("<H", block, 64)[0]
    name = block[:nlen-2].decode("utf-16le", errors="ignore") if 2 <= nlen <= 64 else ""
    start_sec = struct.unpack_from("<I", block, 116)[0]
    size = struct.unpack_from("<Q", block, 120)[0]
    print(f"Dir Entry {i}: name='{name}' start_sec={start_sec} size={size} offset={entry_off}")
