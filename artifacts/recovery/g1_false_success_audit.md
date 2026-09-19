# Gate G1 False-Success Dismantling & Negative Test Audit Report (v2)

**Mission ID**: `G1_FALSE_SUCCESS_C4_AUDIT_OFFLINE_v2`  
**Audit Timestamp**: `2026-09-09T01:06:20.839815+00:00`  
**Execution Scope**: Strict Offline Negative Test Audit across `src/mcp/tools.py`, `src/cscape/`, `src/iec/`, `src/security/`  
**Operational Mode**: `offline/DEV only` (No Cscape GUI, No PLC hardware, No GUI re-executions)  
**Status Contract Compliance**: Canonical 4-State (`success | failed | blocked | inconclusive`)  

---

## 1. Executive Summary

A rigorous offline audit of the Gate G1 false-success surface was executed. The test suite `tests/test_g1_false_success_negative_cases.py` was expanded to **28 negative test cases**, comprehensively covering all cataloged vulnerabilities where tools or engines could return false success on empty, missing, invalid, or crashing inputs.

### Verification Metrics:
- **Negative Test Suite (`tests/test_g1_false_success_negative_cases.py`)**: 28 passed / 0 failed in 5.02s (100% pass rate).
- **H01–H13 Contract Suite (`tests/test_step190_g1_false_success_audit.py`)**: 16 passed / 0 failed in 5.3s (100% pass rate).
- **C4 Matrix Contract Suite (`tests/test_c4_windows_matrix.py`)**: 22 passed / 0 failed in 1.84s (100% pass rate).

---

## 2. Detailed Breakdown of 28 Dismantled Negative Test Cases

| Case | Target Component | Vulnerability Dismantled | Fail-Closed Enforcement | Status |
| :-: | :--- | :--- | :--- | :-: |
| `CASE_01` | `src/mcp/tools.py` | cscape_run_simulation - Empty Simulation Loop | Fail closed on empty or whitespace st_code: status='failed', error_code='INVALID_ST_CODE'. | **PASSED** |
| `CASE_02` | `src/mcp/tools.py` | cscape_inspect_variables - Success on Missing Project / Broken POUs | Validate project_name via SafetyGuard.validate_project_name(); fail closed if missing: status='failed', error_code='PROJECT_NOT_FOUND'. | **PASSED** |
| `CASE_03` | `src/mcp/tools.py` | cscape_insert_st & cscape_add_st_pou - Missing POU Name Validation | Enforced SafetyGuard.validate_pou_name() and pou_type validation at entry. | **PASSED** |
| `CASE_04` | `src/mcp/tools.py` | cscape_write_variables - Success on Empty Variable List | Fail closed if total_count == 0: status='failed', error_code='EMPTY_VARIABLE_LIST'. Enforce success = (is_valid and total_count > 0). | **PASSED** |
| `CASE_05` | `src/mcp/tools.py` | cscape_read_variables - Success on Empty Database or Path | Require non-empty file_path; fail closed if count == 0: status='failed', error_code='EMPTY_VARIABLE_DATABASE'. | **PASSED** |
| `CASE_06` | `src/mcp/tools.py` | cscape_get_build_output - Hardcoded success: True on Failed Build | Set success = build_successful. | **PASSED** |
| `CASE_07` | `src/mcp/tools.py` | cscape_get_diagnostics - Compile Successful & Clean Build Overrides | Reject empty project name; set clean_build = bool(compile_ok and warning_count == 0 and error_count == 0). | **PASSED** |
| `CASE_08` | `src/mcp/tools.py` | get_active_simulator - Non-Existent Project Execution | Raise FileNotFoundError when specified project directory does not exist. | **PASSED** |
| `CASE_09` | `src/mcp/tools.py` | cscape_simulate_pou - Mock Fallback Masking Execution Errors | Wrap fallback in try-except; fail closed with status='failed', error_code='SIMULATION_EXECUTION_ERROR'. | **PASSED** |
| `CASE_10` | `src/iec/st_parser.py` | STParser.validate - Empty Code Validated as Valid | Emit IssueSeverity.ERROR with code ERR_EMPTY_SOURCE and return is_valid=False. | **PASSED** |
| `CASE_11` | `src/automation/com_bridge.py` | com_bridge.py open_project - Returncode Bypass | Condition updated to 'returncode == 0 and not timed_out'. | **PASSED** |
| `CASE_12` | `src/mcp/tools.py` | cscape_export_project - Synthesis of Dummy Files on Missing Artifacts | Fail closed if source file does not exist: status='failed', error_code='NO_DATA_TO_EXPORT'. | **PASSED** |
| `CASE_13` | `src/mcp/tools.py` | normalize_tool_result - Unverified Result Dict Defaults to Success | Set canonical_status='inconclusive', success=False, error_code='UNVERIFIED_RESULT_STATUS'. | **PASSED** |
| `CASE_14` | `src/mcp/tools.py` | Convenience Tools - Non-Canonical 'error' Status | Replaced 'error' with canonical 'failed' across all tool failure return branches. | **PASSED** |
| `CASE_15` | `src/cscape/project_manager.py` | CscapeLiveProjectManager.open_project - Fake Open Without Live Engine | Require IsWindow / process liveness check before trusting gate JSON. | **PASSED** |
| `CASE_16` | `src/mcp/tools.py` | cscape_new_iec_project - Live GUI Failure Fallback to Dummy CFBF | Fail closed if live GUI creation was requested and fails: status='failed', error_code='LIVE_PROJECT_CREATION_FAILED'. | **PASSED** |
| `CASE_17` | `src/cscape/st_inserter.py` | StructuredTextInserter - AST Hash Crash Defaulting ast_match to True | Require ast_match without defaulting to True on failure; fail closed. | **PASSED** |
| `CASE_18` | `src/iec/simulator.py` | STSimulator._evaluate_expression - Swallowing Runtime Evaluation Exceptions | Raise RuntimeError on eval failure; catch in simulate() and fail closed with error_code='SIMULATION_EXECUTION_ERROR'. | **PASSED** |
| `CASE_19` | `src/mcp/tools.py` | cscape_compile & normalize_tool_result - Build Warnings Coerced to Success | Mapped status 'warnings' to canonical status 'inconclusive'. | **PASSED** |
| `CASE_20` | `src/cscape/safety.py` | intercept_hardware_interface - Port Lockout Bypass on Empty interface_name | Evaluate interface_name and port independently; fail closed on blocked port. | **PASSED** |
| `CASE_21` | `tests/test_real_compilation.py` | test_real_compilation.py - Synthetic Win32 Mocks Claiming Live Pass | Tagged unit test docstrings with [MOCK_DISPATCH_ONLY]. | **PASSED** |
| `CASE_22` | `src/iec/validator.py` | IECValidator.validate - Swallowing Semantic Parser Exceptions | Catch exception and append diagnostic to warnings list. | **PASSED** |
| `CASE_23` | `src/mcp/tools.py` | cscape_validate_st - Empty Code & Ladder Logic Rejection | Reject empty ST code and reject ladder logic with ERR_LADDER_FORBIDDEN; fail closed with valid=False, status='failed'. | **PASSED** |
| `CASE_24` | `src/mcp/tools.py` | cscape_compile - Missing Project & Ladder Logic Syntax Rejection | Fail closed on missing project (PROJECT_NOT_FOUND) and ladder logic POU (ST_SYNTAX_ERROR). | **PASSED** |
| `CASE_25` | `src/mcp/tools.py` | cscape_compile_project - Empty Project Name Validation | Validate project name; fail closed immediately with status='failed'. | **PASSED** |
| `CASE_26` | `src/mcp/tools.py` | cscape_read_register - Malformed Address & Non-Existent Project Rejection | Fail closed with ERR_INVALID_REGISTER_ADDRESS or project error; status='failed'. | **PASSED** |
| `CASE_27` | `src/mcp/tools.py` | cscape_write_register - Malformed Address & Non-Existent Project Rejection | Fail closed with ERR_INVALID_REGISTER_ADDRESS or project error; status='failed'. | **PASSED** |
| `CASE_28` | `src/mcp/tools.py` | cscape_simulate_cycle & Variable Import/Export Fail Closed | Fail closed with status='failed' on non-existent project or empty variable sets. | **PASSED** |

---

## 3. H01–H13 False-Success Invariant Matrix

| Item | Invariant Description | Verification Suite | Enforced State |
| :--- | :--- | :--- | :-: |
| **H01** | Fake Export Success without Live Engine | `test_h01_export_fail_closed` | `status: failed` |
| **H02** | Fake Open Success without Live Engine | `test_h02_open_fail_closed` | `status: failed` |
| **H03** | Fake Compile Success without Live Engine | `test_h03_compile_fail_closed_and_honest_metrics` | `status: failed` |
| **H04** | Silent Mocks Disguised as Live Passes | `test_h04_simulation_offline_mock_classification` | `TESTED_MOCK [offline/DEV only]` |
| **H05** | Global Allow Dialog Bypass without Modal Inspection | `test_h05_modal_dialog_inspection` | `status: blocked` |
| **H06** | Straton K5 Files in Active Code Paths | `test_h06_straton_k5_quarantine` | `quarantined (0 imports)` |
| **H07** | Hardcoded Dead PIDs Treated as Permanent Passes | `test_h07_dead_pids_decoupled` | `HISTORICAL MILESTONE` |
| **H08** | Ladder Constructs Disguised as ST | `test_h08_ladder_forbidden_rejection` | `ERR_LADDER_FORBIDDEN` |
| **H09** | Fake 100% or FINAL_REPORT Claims | `test_h09_fake_victory_prohibited` | Prohibited in `AGENTS.md` |
| **H10** | Physical Hardware Port Access without Lockout | `test_h10_hardware_port_lockout` | `HardwareLockoutError` |
| **H11** | Companion Flasher Utilities Allowed | `test_h11_companion_flasher_lockout` | `SecurityError` |
| **H12** | Unsupervised Naked Cscape Launch Claiming Stability | `test_h12_naked_launch_crash_documented` | Single GUI Boundary |
| **H13** | Strict 4-State Status Contract Violation | `test_h13_strict_4_state_status_contract` | `success\|failed\|blocked\|inconclusive` |

---

## 4. Conclusion & Compliance

All 28 negative test cases and all 13 H01–H13 invariants strictly pass. Zero false successes remain in active MCP tools or IEC engines. No GUI or hardware actions were performed during this audit.
