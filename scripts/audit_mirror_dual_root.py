import filecmp
import hashlib
import shutil
from pathlib import Path

SRC_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp")
DST_ROOT = Path(r"C:\Users\ArmandoSilva")

files_to_sync = [
    # Live MCP fail closed tests
    "tests/test_live_mcp_fail_closed_on_gui_death.py",
    "tests/test_live_mcp_stdio_fail_closed_e2e.py",
    "tests/test_mcp_closed_loop_1000cycle_extended.py",
    # Step 136 & 138 PID alias removals
    "tests/test_step136_cross_pou_symbol_resolution.py",
    "tests/test_step138_mcp_full_lifecycle_diagnostics.py",
    # Scripts
    "scripts/audit_clean_expected_pids.py",
    "scripts/audit_patch_step158_170_gui.py",
    "scripts/audit_patch_step158_170_mcp.py",
    "scripts/verify_offline_gui_drivers.py",
]

# Add step 158-170 MCP tests
mcp_step_names = [
    (158, "decoupled_mimo_level_pressure"),
    (159, "coordinated_blowdown_dosing"),
    (160, "plant_wide_integration_benchmark"),
    (161, "tmr_sensor_voting"),
    (162, "pump_sequencing_runtime_balance"),
    (163, "spillback_recirculation_surge"),
    (164, "vfd_resonance_skipband_protection"),
    (165, "deaerator_pressure_dissolved_oxygen"),
    (166, "economizer_steaming_acid_dewpoint"),
    (167, "superheater_attemperator_spray"),
    (168, "msv_warming_water_hammer"),
    (169, "combustion_control_cross_limiting"),
    (170, "master_header_pressure_grid_balance"),
]

for step, name in mcp_step_names:
    files_to_sync.append(f"tests/test_step{step}_mcp_{name}.py")

# Add step 156-170 visible GUI driver tests
for step in range(156, 171):
    files_to_sync.append(f"tests/test_step{step}_visible_cscape_gui_driver.py")

# Add step 156-170 execute scripts
for step in range(156, 171):
    files_to_sync.append(f"scripts/execute_step{step}_visible_cscape_gui_driver.py")

print(f"Total files scheduled for synchronization: {len(files_to_sync)}")

synced_count = 0
parity_verified = 0

for rel_path in files_to_sync:
    src_file = SRC_ROOT / rel_path
    dst_file = DST_ROOT / rel_path
    
    if not src_file.exists():
        print(f"WARNING: Source file does not exist: {src_file}")
        continue
    
    print(f"Syncing: {rel_path}")
    dst_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(src_file, dst_file)
    except PermissionError as e:
        print(f"  PermissionError on {dst_file}: {e}")
        # Try writing bytes directly
        try:
            dst_file.write_bytes(src_file.read_bytes())
            print(f"  write_bytes succeeded for {dst_file}")
        except Exception as e2:
            print(f"  write_bytes also failed: {e2}")
            continue
    synced_count += 1
    
    src_hash = hashlib.sha256(src_file.read_bytes()).hexdigest()
    dst_hash = hashlib.sha256(dst_file.read_bytes()).hexdigest()
    
    if src_hash == dst_hash:
        parity_verified += 1
    else:
        print(f"ERROR: Hash mismatch for {rel_path}!")

print(f"Sync complete: {synced_count} files synced, {parity_verified} verified with matching SHA-256.")
assert synced_count == parity_verified == len(files_to_sync), "Not all files synced with SHA-256 parity!"
