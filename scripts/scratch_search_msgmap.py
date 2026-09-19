import struct

dll_path = r"C:\Program Files (x86)\Cscape 10.2\GrEdit.dll"
data = open(dll_path, "rb").read()

# Search for common command IDs like 2787, 2857, etc. in 0x0111 message map entries
# struct AFX_MSGMAP_ENTRY: nMessage(4), nCode(4), nID(4), nLastID(4), nSig(4), pfn(4) in 32-bit = 24 bytes
# For WM_COMMAND: nMessage == 0x0111, nCode == 0, nID == nLastID
target_ids = [2787, 2825, 2857, 2859, 2788, 2789, 1006, 2841, 2869, 2870, 7803, 38477, 38478, 38570]

for tid in target_ids:
    pattern = struct.pack("<IIII", 0x0111, 0, tid, tid)
    pos = 0
    matches = []
    while True:
        pos = data.find(pattern, pos)
        if pos == -1:
            break
        matches.append(pos)
        pos += 4
    if matches:
        print(f"Command {tid}: found {len(matches)} message map entries")
