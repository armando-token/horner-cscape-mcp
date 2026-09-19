import sys
import struct
from pathlib import Path
sys.path.insert(0, ".")
from src.cscape.cfbf import is_valid_cfbf, extract_cfbf_streams
from src.cscape.project_manager import CscapeLiveProjectManager

src_csp = Path(r"C:\HornerAI\horner-cscape-mcp\artifacts\projects\TankLevel_P4_REDO\TankLevel_P4_REDO.csp")
test_csp = Path(r"C:\HornerAI\horner-cscape-mcp\artifacts\projects\TankLevel_P4_REDO\test_clean_patch.csp")

data = bytearray(src_csp.read_bytes())
sec_size = 512

first_dir = struct.unpack_from("<I", data, 48)[0]
dir_offset = (first_dir + 1) * sec_size
contents_entry_off = dir_offset + 128

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

# Let's test ONLY the 2 byte replacements (65 -> 75) first, touching NOTHING else
old_hi = b"SP HI 65 cm"
new_hi = b"SP HI 75 cm"
old_st_hi = b"HI := TankLevelPV >= 65.0;"
new_st_hi = b"HI := TankLevelPV >= 75.0;"

patched_stream = stream_data.replace(old_hi, new_hi)
patched_stream = patched_stream.replace(old_st_hi, new_st_hi)
assert len(patched_stream) == curr_size

# Write back ONLY the stream bytes without touching trailing bytes in the last sector
written = 0
for s in chain:
    s_off = (s + 1) * sec_size
    chunk_len = min(sec_size, len(patched_stream) - written)
    data[s_off : s_off + chunk_len] = patched_stream[written : written + chunk_len]
    written += chunk_len
    if written >= len(patched_stream):
        break

test_csp.write_bytes(data)
print("Saved test_clean_patch.csp.")
# Check diff with src_csp
diffs = [i for i in range(len(data)) if data[i] != src_csp.read_bytes()[i]]
print(f"Total diffs with original: {len(diffs)} bytes")
for d in diffs:
    print(f"  Diff at 0x{d:x}: {chr(src_csp.read_bytes()[d])} -> {chr(data[d])}")

assert len(diffs) == 2, f"Expected exactly 2 diffs, got {len(diffs)}"
print("Exact 2-byte diff verified! Now testing open in Cscape...")

mgr = CscapeLiveProjectManager()
mgr._attach_thread_desktop()
res = mgr.open_project(test_csp, require_live_gui=True, timeout_sec=15.0)
print(f"Open result: success={res.success} message={res.message}")
