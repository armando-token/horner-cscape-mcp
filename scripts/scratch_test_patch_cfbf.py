import sys
import struct
import shutil
from pathlib import Path
sys.path.insert(0, ".")
from src.cscape.cfbf import is_valid_cfbf, extract_cfbf_streams

src_csp = Path(r"C:\HornerAI\horner-cscape-mcp\artifacts\projects\TankLevel_P4_REDO\TankLevel_P4_REDO.csp")
test_csp = Path(r"C:\HornerAI\horner-cscape-mcp\artifacts\projects\TankLevel_P4_REDO\test_patch.csp")

data = bytearray(src_csp.read_bytes())
sec_size = 512

# Read directory
first_dir = struct.unpack_from("<I", data, 48)[0]
dir_offset = (first_dir + 1) * sec_size
contents_entry_off = dir_offset + 128  # Entry 1

start_sec = struct.unpack_from("<I", data, contents_entry_off + 116)[0]
curr_size = struct.unpack_from("<Q", data, contents_entry_off + 120)[0]
print(f"Contents start_sec={start_sec}, curr_size={curr_size}")

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
print(f"Chain sectors count: {len(chain)} ({len(chain) * sec_size} bytes)")

# Reconstruct stream bytes
stream_bytes = bytearray()
for s in chain:
    s_off = (s + 1) * sec_size
    stream_bytes.extend(data[s_off : s_off + sec_size])
stream_data = bytes(stream_bytes[:curr_size])

# Check replacements
old_label = b"\xff\xfe\xff\x00\x0aTank Level\xfe"
new_label = b"\xff\xfe\xff\x00\x14Buffer Tank Level PV\xfe"

old_hi = b"SP HI 65 cm"
new_hi = b"SP HI 75 cm"

old_st_hi = b"HI := TankLevelPV >= 65.0;"
new_st_hi = b"HI := TankLevelPV >= 75.0;"

assert old_label in stream_data, "old_label not found in stream_data"
assert old_hi in stream_data, "old_hi not found in stream_data"
assert old_st_hi in stream_data, "old_st_hi not found in stream_data"

patched_stream = stream_data.replace(old_label, new_label)
patched_stream = patched_stream.replace(old_hi, new_hi)
patched_stream = patched_stream.replace(old_st_hi, new_st_hi)

new_size = len(patched_stream)
print(f"Patched stream size: {new_size} (diff: {new_size - curr_size})")
assert new_size <= len(chain) * sec_size, "New stream exceeds allocated sectors!"

# Pad patched stream to fill full sectors
padded_stream = bytearray(patched_stream)
remaining_pad = (len(chain) * sec_size) - new_size
padded_stream.extend(b"\x00" * remaining_pad)

# Write back to sectors in data
for i, s in enumerate(chain):
    s_off = (s + 1) * sec_size
    data[s_off : s_off + sec_size] = padded_stream[i * sec_size : (i + 1) * sec_size]

# Update size in directory entry
struct.pack_into("<Q", data, contents_entry_off + 120, new_size)

# Write to test_csp
test_csp.write_bytes(data)
print("Saved test_csp. Validating CFBF...")
assert is_valid_cfbf(test_csp), "Patched test_csp is not valid CFBF!"
print("CFBF valid! Extracting streams from test_csp...")
new_streams = extract_cfbf_streams(test_csp)
new_contents = new_streams["Contents"]
assert len(new_contents) == new_size, f"Stream size mismatch: {len(new_contents)} != {new_size}"
assert b"Buffer Tank Level PV" in new_contents, "Buffer Tank Level PV not in new_contents!"
assert b"SP HI 75 cm" in new_contents, "SP HI 75 cm not in new_contents!"
assert b"SP LO 35 cm" in new_contents, "SP LO 35 cm not in new_contents!"
assert b"HI := TankLevelPV >= 75.0;" in new_contents, "ST 75.0 not in new_contents!"
print("ALL ASSERTIONS PASSED! Patching is 100% SUCCESSFUL!")
