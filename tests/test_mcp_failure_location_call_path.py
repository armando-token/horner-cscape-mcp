"""Unit test verifying MCP closed loop failure location call path and assertions."""

import json
from pathlib import Path
import pytest

REPO_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()
JSON_PATH = REPO_ROOT / "artifacts" / "logs" / "mcp_closed_loop_failure_location_call_path.json"
LOG_PATH = REPO_ROOT / "artifacts" / "logs" / "mcp_closed_loop_failure_location_call_path.log"


def test_evidence_files_exist_and_valid():
    assert JSON_PATH.exists(), f"{JSON_PATH} does not exist"
    assert LOG_PATH.exists(), f"{LOG_PATH} does not exist"

    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    assert data.get("zero_plc_download_policy") == "ENFORCED_FAIL_CLOSED"
    assert "mcp_tools_call_path" in data
    assert len(data["mcp_tools_call_path"]) == 8

    # Failure location scenarios
    scenarios = data.get("failure_location_scenarios", [])
    assert len(scenarios) >= 4

    sc2 = next(s for s in scenarios if s["scenario_id"] == "SCENARIO_2_MISSING_SEMICOLON")
    assert sc2["target_pou"] == "POU_MissingSemicolon.st"
    flocs = sc2["concrete_failure_locations"]
    assert any(
        f["file_path"] == "POU_MissingSemicolon.st" and f["line"] == 6 and f["column"] == 18 and f["error_code"] == "ERR_MISSING_SEMICOLON"
        for f in flocs
    )

    # Log file verification
    log_content = LOG_PATH.read_text(encoding="utf-8")
    assert "POU_MissingSemicolon.st" in log_content
    assert "Line: 6 | Col: 18 | Code: ERR_MISSING_SEMICOLON" in log_content
    assert "ZERO Physical PLC Connections | ZERO Controller Downloads" in log_content
    assert "ALL 8 MCP TOOLS VERIFIED CLEANLY" in log_content
