"""Quick smoke test for MCP tool calls across the 5 client targets."""
import sys
from pathlib import Path

# Add project root to sys.path
WORKSPACE_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from src.mcp.tools import (
    cscape_read_variables,
    cscape_write_register,
    cscape_read_register,
    cscape_simulate_cycle,
    cscape_compile_project,
    cscape_get_diagnostics,
    get_active_simulator,
)

def main():
    print("Testing Client 1: cscape_read_variables...")
    csv_path = WORKSPACE_ROOT / "artifacts" / "projects" / "TankLevel_Client1" / "variables.csv"
    res1 = cscape_read_variables(str(csv_path))
    assert res1["success"], f"Client 1 failed: {res1}"
    print(f"Client 1 Success: {res1['count']} variables read, status: {res1['validation_status']}")

    print("Testing Client 2: Tank Filling init...")
    sim2 = get_active_simulator("TankLevel_Client2_Fill")
    w2 = cscape_write_register("%R3", 80.0, data_type="REAL", project_name="TankLevel_Client2_Fill")
    assert w2["success"], f"Client 2 write failed: {w2}"
    r2 = cscape_read_register("%R3", data_type="REAL", project_name="TankLevel_Client2_Fill")
    assert r2["success"], f"Client 2 read failed: {r2}"
    print(f"Client 2 %R3 = {r2['value']}")

    print("Testing Client 3: Tank Draining init...")
    sim3 = get_active_simulator("TankLevel_Client3_Drain")
    w3 = cscape_write_register("%R3", 20.0, data_type="REAL", project_name="TankLevel_Client3_Drain")
    assert w3["success"], f"Client 3 write failed: {w3}"
    r3 = cscape_read_register("%R3", data_type="REAL", project_name="TankLevel_Client3_Drain")
    assert r3["success"], f"Client 3 read failed: {r3}"
    print(f"Client 3 %R3 = {r3['value']}")

    # Check state isolation
    r2_check = cscape_read_register("%R3", data_type="REAL", project_name="TankLevel_Client2_Fill")
    print(f"Client 2 %R3 check after Client 3 write: {r2_check['value']}")
    assert abs(r2_check["value"] - 80.0) < 1e-3, f"Leakage! Client 2 is {r2_check['value']}"
    assert abs(r3["value"] - 20.0) < 1e-3, f"Leakage! Client 3 is {r3['value']}"

    print("Testing Client 4: Register Inspection...")
    for reg in ["%R1", "%R3", "%R7", "%AQ1", "%AQ2", "%M7", "%M8", "%M9", "%M10"]:
        r4 = cscape_read_register(reg, project_name="TankLevel_Client4_Inspect")
        assert r4["success"], f"Client 4 inspection failed for {reg}: {r4}"
    print("Client 4 register inspection successful!")

    print("Testing Client 5: Compile & Diagnostics...")
    comp_res = cscape_compile_project("TankLevel_Client5_Compile")
    assert comp_res["success"], f"Client 5 compile failed: {comp_res}"
    diag_res = cscape_get_diagnostics("TankLevel_Client5_Compile")
    assert diag_res["success"], f"Client 5 diagnostics failed: {diag_res}"
    print("Client 5 compile & diagnostics successful!")

    print("ALL 5 CLIENT TOOL BASICS PASSED CLEANLY!")

if __name__ == "__main__":
    main()
