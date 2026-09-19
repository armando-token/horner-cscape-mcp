"""Contract Tests for FastMCP Public Scan-List Tool (cscape_inspect_scan_list).

Verifies fail-closed empty-list behavior, offline hardware lockout,
zero PLC download, verified_live=False, and Pydantic v2 schema adherence.
"""

import pytest
from pathlib import Path
from pydantic import ValidationError

from src.mcp.schemas import (
    CscapeInspectScanListInput,
    CscapeInspectScanListOutput,
    TOOL_SCHEMAS,
)
from src.mcp.tools import cscape_inspect_scan_list, cscape_get_scan_list
from src.mcp.server import create_mcp_server


DEDICATED_PROJECT = "artifacts/projects/TankLevel_P5_Dedicated/TankLevel_P5_Dedicated.csp"


def test_default_inspection_returns_empty_list():
    """Verify default offline inspection returns an honest empty scan list with status 'success'."""
    res = cscape_inspect_scan_list(
        project_path=DEDICATED_PROJECT,
        port="MJ1",
        protocol="CT RTU Modbus CMP v5.05",
        require_populated=False,
    )
    assert res["status"] == "success"
    assert res["success"] is True
    assert res["scan_list"] == []
    assert res["count"] == 0
    assert res["scan_list_status"] == "empty"
    assert res["native_fill_status"] == "blocked_offline"
    assert "no PLC connection or download was permitted" in res["blocker"]
    assert res["pending_gate"] == "P7_PHYSICAL_PLC_DOWNLOAD_AND_COMMISSIONING"
    assert res["offline_safety_enforced"] is True
    assert res["zero_download_enforced"] is True
    assert res["verified_live"] is False
    assert res["plc_download"] is False


def test_empty_scan_list_fail_closed_when_require_populated_true():
    """Verify empty scan list triggers fail-closed 'blocked' status when require_populated=True."""
    res = cscape_inspect_scan_list(
        project_path=DEDICATED_PROJECT,
        port="MJ1",
        require_populated=True,
    )
    assert res["status"] == "blocked"
    assert res["success"] is False
    assert res["error_code"] in ("SECURITY_BLOCKED", "SCAN_LIST_EMPTY_FAIL_CLOSED")
    assert res["scan_list"] == []
    assert res["count"] == 0
    assert res["scan_list_status"] == "empty"
    assert res["native_fill_status"] == "blocked_offline"
    assert "require_populated=True assertion failed" in res["message"]


def test_hardware_lockout_when_plc_download_true():
    """Verify plc_download=True triggers fail-closed security lockout."""
    res = cscape_inspect_scan_list(
        project_path=DEDICATED_PROJECT,
        plc_download=True,
    )
    assert res["status"] == "blocked"
    assert res["success"] is False
    assert res["error_code"] == "SECURITY_BLOCKED"
    assert res["zero_download_enforced"] is False


def test_gate_invariant_when_verified_live_true():
    """Verify verified_live=True triggers fail-closed gate lockout."""
    res = cscape_inspect_scan_list(
        project_path=DEDICATED_PROJECT,
        verified_live=True,
    )
    assert res["status"] == "blocked"
    assert res["success"] is False
    assert res["error_code"] == "SECURITY_BLOCKED"


def test_offline_policy_when_request_live_fill_true():
    """Verify request_live_fill=True triggers fail-closed offline policy lockout."""
    res = cscape_inspect_scan_list(
        project_path=DEDICATED_PROJECT,
        request_live_fill=True,
    )
    assert res["status"] == "blocked"
    assert res["success"] is False
    assert res["error_code"] == "SECURITY_BLOCKED"


def test_physical_serial_port_lockout():
    """Verify physical COM ports (e.g. COM1, COM24) are blocked fail-closed."""
    for com_port in ("COM1", "com1", "COM24", "\\\\.\\COM5"):
        res = cscape_inspect_scan_list(
            project_path=DEDICATED_PROJECT,
            port=com_port,
        )
        assert res["status"] == "blocked"
        assert res["success"] is False
        assert res["error_code"] == "SECURITY_BLOCKED"


def test_nonexistent_project_returns_failed():
    """Verify querying a nonexistent project returns status 'failed'."""
    res = cscape_inspect_scan_list(
        project_path="artifacts/projects/nonexistent_container_xyz.csp"
    )
    assert res["status"] == "failed"
    assert res["success"] is False
    assert res["error_code"] in ("PROJECT_NOT_FOUND", "SCAN_LIST_INSPECTION_ERROR")


def test_invalid_cfbf_container_returns_failed(tmp_path):
    """Verify non-CFBF file returns status 'failed' with INVALID_CFBF_CONTAINER."""
    corrupt_file = tmp_path / "corrupt.csp"
    corrupt_file.write_text("NOT_A_VALID_CFBF_FILE", encoding="utf-8")

    res = cscape_inspect_scan_list(project_path=str(corrupt_file))
    assert res["status"] == "failed"
    assert res["success"] is False
    assert res["error_code"] in ("INVALID_CFBF_CONTAINER", "SCAN_LIST_INSPECTION_ERROR")


def test_pydantic_schema_extra_forbid():
    """Verify extra fields are strictly forbidden in CscapeInspectScanListInput."""
    with pytest.raises(ValidationError) as exc:
        CscapeInspectScanListInput(
            project_path=DEDICATED_PROJECT,
            unauthorized_extra_switch="malicious",
        )
    assert "extra_forbidden" in str(exc.value) or "Extra inputs are not permitted" in str(exc.value)


def test_pydantic_schema_direct_validators():
    """Verify direct Pydantic validators reject prohibited parameters."""
    with pytest.raises(ValidationError):
        CscapeInspectScanListInput(plc_download=True)

    with pytest.raises(ValidationError):
        CscapeInspectScanListInput(verified_live=True)

    with pytest.raises(ValidationError):
        CscapeInspectScanListInput(request_live_fill=True)

    with pytest.raises(ValidationError):
        CscapeInspectScanListInput(port="COM2")


def test_alias_cscape_get_scan_list_identity():
    """Verify cscape_get_scan_list is an identical alias for cscape_inspect_scan_list."""
    assert cscape_get_scan_list is cscape_inspect_scan_list
    res = cscape_get_scan_list(require_populated=True)
    assert res["status"] == "blocked"
    assert res["scan_list"] == []


@pytest.mark.asyncio
async def test_fastmcp_server_announces_tool_and_schema_parity():
    """Verify cscape_inspect_scan_list is announced by FastMCP server and in TOOL_SCHEMAS."""
    srv = create_mcp_server()
    tools = await srv.list_tools()
    tool_map = {t.name: t for t in tools}

    assert "cscape_inspect_scan_list" in tool_map
    assert "cscape_inspect_scan_list" in TOOL_SCHEMAS

    schema_info = TOOL_SCHEMAS["cscape_inspect_scan_list"]
    assert schema_info["input"] is CscapeInspectScanListInput
    assert schema_info["output"] is CscapeInspectScanListOutput
