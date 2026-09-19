import sys
import struct
from pathlib import Path
sys.path.insert(0, ".")
from src.cscape.cfbf import is_valid_cfbf, extract_cfbf_streams
from src.cscape.project_manager import CscapeLiveProjectManager

src_csp = Path(r"C:\HornerAI\horner-cscape-mcp\artifacts\projects\TankLevel_P4_REDO\TankLevel_P4_REDO.csp")
test_csp = Path(r"C:\HornerAI\horner-cscape-mcp\artifacts\projects\TankLevel_P4_REDO\test_same_length.csp")

data = bytearray(src_csp.read_bytes())
sec_size = 512

# Read directory
first_dir = struct.unpack_from("<I", data, 48)[0]
dir_offset = (first_dir + 1) * sec_size
contents_entry_off = dir_offset + 128  # Entry 1

start_sec = struct.unpack_from("<I", data, contents_entry_off + 116)[0]
curr_size = struct.unpack_from("<Q", data, contents_entry_off + 120)[0]

# Read FAT
fat_sec_ids = [s for s in struct.unpack_from("<109I", data, 76) if s < 0xFFFFFFFD]
fat = []
for f_sec in fat_sec_ids:
    f_off = (f_sec + 1) * sec_size
    fat.extend(struct.unpack_from(f"<{sec_size // 4}I", data, f_off))

def get_chain(s):
    c = []
    while s < 0xFFFFFFFD:
        c.append(s)
        s = fat[s]
    return c

chain = get_chain(start_sec)

# Reconstruct stream bytes
stream_bytes = bytearray()
for s in chain:
    s_off = (s + 1) * sec_size
    stream_bytes.extend(data[s_off : s_off + sec_size])
stream_data = bytes(stream_bytes[:curr_size])

old_hi = b"SP HI 65 cm"
new_hi = b"SP HI 75 cm"

old_st_hi = b"HI := TankLevelPV >= 65.0;"
new_st_hi = b"HI := TankLevelPV >= 75.0;"

assert old_hi in stream_data
assert old_st_hi in stream_data

patched_stream = stream_data.replace(old_hi, new_hi)
patched_stream = patched_stream.replace(old_st_hi, new_st_hi)

assert len(patched_stream) == curr_size

padded_stream = bytearray(patched_stream)
remaining_pad = (len(chain) * sec_size) - len(patched_stream)
padded_stream.extend(b"\x00" * remaining_pad)

for i, s in enumerate(chain):
    s_off = (s + 1) * sec_size
    data[s_off : s_off + sec_size] = padded_stream[i * sec_size : (i + 1) * sec_size]

test_csp.write_bytes(data)
print("Saved test_same_length.csp. Testing open...")

mgr = CscapeLiveProjectManager()
mgr._attach_thread_desktop()
res = mgr.open_project(test_csp, require_live_gui=True, timeout_sec=15.0)
print(f"Open result: success={res.success} message={res.message}")
