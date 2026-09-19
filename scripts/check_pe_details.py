import os
import pefile

cscape_path = r"C:\Program Files (x86)\Cscape 10.2\Cscape.exe"
pe = pefile.PE(cscape_path)

print("=== PE SECTIONS ===")
for s in pe.sections:
    name = s.Name.decode(errors="ignore").strip("\x00")
    print(f"  {name:<10} | VirtSize: {s.Misc_VirtualSize:8d} (0x{s.Misc_VirtualSize:08x}) | RawSize: {s.SizeOfRawData:8d} | Characteristics: {hex(s.Characteristics)}")

print("\n=== OPTIONAL HEADER ===")
opt = pe.OPTIONAL_HEADER
print(f"  AddressOfEntryPoint: {hex(opt.AddressOfEntryPoint)}")
print(f"  ImageBase: {hex(opt.ImageBase)}")
print(f"  SectionAlignment: {hex(opt.SectionAlignment)}")
print(f"  FileAlignment: {hex(opt.FileAlignment)}")
print(f"  MajorOperatingSystemVersion: {opt.MajorOperatingSystemVersion}")
print(f"  Subsystem: {opt.Subsystem} ({'IMAGE_SUBSYSTEM_WINDOWS_GUI' if opt.Subsystem == 2 else opt.Subsystem})")
print(f"  DllCharacteristics: {hex(opt.DllCharacteristics)}")

print("\n=== DATA DIRECTORIES ===")
for idx, entry in enumerate(opt.DATA_DIRECTORY):
    if entry.VirtualAddress != 0 or entry.Size != 0:
        print(f"  [{idx}] {entry.name:<30} | VA: {hex(entry.VirtualAddress)} | Size: {entry.Size}")

