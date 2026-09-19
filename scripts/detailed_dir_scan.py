import os
import json
from collections import defaultdict

cscape_dir = r"C:\Program Files (x86)\Cscape 10.2"

ext_counts = defaultdict(int)
ext_sizes = defaultdict(int)
subdirs = []
root_files = []

for entry in os.scandir(cscape_dir):
    if entry.is_dir():
        # count files in subdir
        count = 0
        total_sz = 0
        for r, dirs, files in os.walk(entry.path):
            count += len(files)
            for f in files:
                try:
                    total_sz += os.path.getsize(os.path.join(r, f))
                except Exception:
                    pass
        subdirs.append({
            "name": entry.name,
            "files": count,
            "size_bytes": total_sz,
            "size_mb": round(total_sz / (1024*1024), 2)
        })
    elif entry.is_file():
        sz = entry.stat().st_size
        ext = os.path.splitext(entry.name)[1].lower()
        ext_counts[ext] += 1
        ext_sizes[ext] += sz
        root_files.append({
            "name": entry.name,
            "size": sz,
            "ext": ext
        })

print(f"Total root files: {len(root_files)}")
print(f"Total subdirectories: {len(subdirs)}")

print("\nSubdirectories:")
for sd in sorted(subdirs, key=lambda x: x["name"].lower()):
    print(f"  {sd['name']:<25} | {sd['files']:4d} files | {sd['size_mb']:7.2f} MB")

print("\nRoot Extensions:")
for ext, count in sorted(ext_counts.items(), key=lambda x: x[1], reverse=True):
    sz_mb = ext_sizes[ext] / (1024*1024)
    print(f"  {ext:<10} | {count:4d} files | {sz_mb:7.2f} MB")
