import struct

dll_path = r"C:\Program Files (x86)\Cscape 10.2\GrEdit.dll"
data = open(dll_path, "rb").read()

for cid in range(995, 1015):
    pattern = struct.pack("<IIII", 0x0111, 0, cid, cid)
    pos = 0
    cnt = 0
    while True:
        pos = data.find(pattern, pos)
        if pos == -1:
            break
        cnt += 1
        pos += 4
    if cnt > 0:
        print(f"ID {cid}: {cnt} handlers")
