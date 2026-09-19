"""
Unit tests for IEC 61131-3 Test Bench Runner.
"""
import pytest
from src.simulation.test_runner import TestBench, TestRunner, TestVector

def test_test_runner_pass():
    st_code = """
    PROGRAM LogicCheck
    VAR_INPUT
        a : BOOL := FALSE;
        b : BOOL := FALSE;
    END_VAR
    VAR_OUTPUT
        q : BOOL := FALSE;
    END_VAR
    q := a AND b;
    END_PROGRAM
    """
    tb = TestBench(name="LogicCheck_TruthTable", program_source=st_code, scan_time_ms=10.0)
    tb.add_vector(inputs={"a": False, "b": False}, expected={"q": False}, description="0 AND 0")
    tb.add_vector(inputs={"a": True, "b": False}, expected={"q": False}, description="1 AND 0")
    tb.add_vector(inputs={"a": False, "b": True}, expected={"q": False}, description="0 AND 1")
    tb.add_vector(inputs={"a": True, "b": True}, expected={"q": True}, description="1 AND 1")

    runner = TestRunner()
    result = runner.run(tb)
    assert result.passed is True
    assert result.vectors_passed == 4
    assert result.vectors_run == 4
    assert len(result.failures) == 0
    assert "PASSED" in result.summary

def test_test_runner_failure_detection():
    st_code = """
    PROGRAM BrokenAdd
    VAR_INPUT
        x : INT := 0;
    END_VAR
    VAR_OUTPUT
        y : INT := 0;
    END_VAR
    y := x + 10;
    END_PROGRAM
    """
    tb = TestBench(name="BrokenAddTest", program_source=st_code)
    # Correct expectation
    tb.add_vector(inputs={"x": 5}, expected={"y": 15}, description="5 + 10 = 15")
    # Wrong expectation to verify failure detection
    tb.add_vector(inputs={"x": 10}, expected={"y": 999}, description="Expect failure")

    runner = TestRunner()
    result = runner.run(tb)
    assert result.passed is False
    assert result.vectors_passed == 1
    assert result.vectors_run == 2
    assert len(result.failures) == 1
    fail = result.failures[0]
    assert fail.variable == "y"
    assert fail.expected == 999
    assert fail.actual == 20
    assert "Expect failure" in fail.description

    with pytest.raises(AssertionError, match="Test Bench 'BrokenAddTest' failed"):
        runner.assert_test_bench(tb)

def test_test_bench_from_json():
    json_data = """
    {
        "name": "JsonBench",
        "program": "VAR x : INT; END_VAR x := x + 2;",
        "scan_time_ms": 20.0,
        "setup": {"x": 10},
        "vectors": [
            {"cycles": 1, "inputs": {}, "expected": {"x": 12}, "description": "Step 1"},
            {"cycles": 2, "inputs": {}, "expected": {"x": 16}, "description": "Step 2"}
        ]
    }
    """
    tb = TestBench.from_json(json_data)
    assert tb.name == "JsonBench"
    assert tb.scan_time_ms == 20.0
    assert len(tb.vectors) == 2

    runner = TestRunner()
    res = runner.run(tb)
    assert res.passed is True
    assert res.total_cycles == 3
    assert res.total_time_ms == 60.0

def test_json_loading_and_file_roundtrip(tmp_path):
    """Verifies complete JSON loading, file serialization, and schema defaults."""
    import json
    st_code = "VAR a : INT := 1; END_VAR a := a + 1;"
    tb = TestBench(name="RoundtripBench", program_source=st_code, scan_time_ms=5.0)
    tb.setup_variables = {"a": 10}
    tb.add_vector(inputs={}, expected={"a": 11}, cycles=1, description="Cycle 1", tolerance=1e-3)
    tb.add_vector(inputs={}, expected={"a": 12}, cycles=1, description="Cycle 2", tolerance=1e-3)

    # 1. to_dict and to_json
    tb_dict = tb.to_dict()
    assert tb_dict["name"] == "RoundtripBench"
    assert tb_dict["scan_time_ms"] == 5.0
    assert tb_dict["setup"] == {"a": 10}
    assert len(tb_dict["vectors"]) == 2

    tb_json = tb.to_json()
    assert '"RoundtripBench"' in tb_json

    # 2. File round-trip
    file_path = tmp_path / "test_bench.json"
    tb.to_file(file_path)
    assert file_path.exists()

    loaded_tb = TestBench.from_file(file_path)
    assert loaded_tb.name == "RoundtripBench"
    assert loaded_tb.scan_time_ms == 5.0
    assert loaded_tb.setup_variables == {"a": 10}
    assert len(loaded_tb.vectors) == 2
    assert loaded_tb.vectors[0].tolerance == 1e-3

    # 3. Invalid JSON error handling
    with pytest.raises(json.JSONDecodeError):
        TestBench.from_json("{invalid json structure")

    # 4. Default fallback when minimal JSON is passed
    minimal_tb = TestBench.from_json('{"program": "VAR z : INT; END_VAR"}')
    assert minimal_tb.name == "UnnamedTestBench"
    assert minimal_tb.scan_time_ms == 10.0
    assert minimal_tb.setup_variables == {}
    assert len(minimal_tb.vectors) == 0

def test_assertion_execution_and_tolerances():
    """Verifies numeric tolerances, strict boolean matching, None checks, and custom assertions."""
    st_code = """
    PROGRAM FloatCheck
    VAR
        val_real : REAL := 3.14159;
        flag_true : BOOL := TRUE;
        flag_false : BOOL := FALSE;
    END_VAR
    END_PROGRAM
    """
    runner = TestRunner()

    # Float tolerance match
    tb_tol_pass = TestBench(name="TolPass", program_source=st_code)
    tb_tol_pass.add_vector(expected={"val_real": 3.1416}, tolerance=0.001)
    res_tol_pass = runner.run(tb_tol_pass)
    assert res_tol_pass.passed is True

    # Float tolerance failure
    tb_tol_fail = TestBench(name="TolFail", program_source=st_code)
    tb_tol_fail.add_vector(expected={"val_real": 3.1416}, tolerance=1e-6)
    res_tol_fail = runner.run(tb_tol_fail)
    assert res_tol_fail.passed is False
    assert len(res_tol_fail.failures) == 1

    # Strict boolean matching: integer 1 should NOT match BOOL True
    assert runner._values_match(True, True, 1e-4) is True
    assert runner._values_match(False, False, 1e-4) is True
    assert runner._values_match(1, True, 1e-4) is False
    assert runner._values_match(0, False, 1e-4) is False
    assert runner._values_match(True, 1, 1e-4) is False
    assert runner._values_match(False, 0, 1e-4) is False
    assert runner._values_match(None, None, 1e-4) is True
    assert runner._values_match(None, 0, 1e-4) is False

    # Custom assertion passing
    tb_custom_pass = TestBench(name="CustomPass", program_source=st_code)
    tb_custom_pass.custom_assertions.append(lambda sim: None)
    res_custom_pass = runner.run(tb_custom_pass)
    assert res_custom_pass.passed is True

    # Custom assertion failing
    tb_custom_fail = TestBench(name="CustomFail", program_source=st_code)
    tb_custom_fail.custom_assertions.append(lambda sim: "Injected invariant violation")
    res_custom_fail = runner.run(tb_custom_fail)
    assert res_custom_fail.passed is False
    assert len(res_custom_fail.failures) == 1
    assert "Injected invariant violation" in res_custom_fail.failures[0].message

def test_step_evaluation_multi_cycle():
    """Verifies multi-cycle step advancement, cumulative timing, and cycle trace recording."""
    st_code = """
    PROGRAM CounterStep
    VAR
        cnt : INT := 0;
    END_VAR
    cnt := cnt + 1;
    END_PROGRAM
    """
    tb = TestBench(name="StepEvaluation", program_source=st_code, scan_time_ms=25.0)
    tb.add_vector(cycles=4, expected={"cnt": 4}, description="Step 4 cycles")
    tb.add_vector(cycles=3, expected={"cnt": 7}, description="Step 3 more cycles")

    runner = TestRunner()
    res = runner.run(tb)

    assert res.passed is True
    assert res.total_cycles == 7
    assert res.total_time_ms == 175.0  # 7 * 25.0 ms
    assert res.vectors_run == 2
    assert res.vectors_passed == 2
    assert len(res.trace) == 7
    assert res.trace[0].cycle == 1
    assert res.trace[6].cycle == 7
    assert res.trace[6].get("CNT") == 7
    assert res.trace[6].variables.get("cnt") == 7

def test_execution_report_generation():
    """Verifies summary string, structured dictionary, and JSON report generation."""
    st_code = "VAR x : INT := 0; END_VAR x := x + 5;"
    tb = TestBench(name="ReportGenTest", program_source=st_code, scan_time_ms=10.0)
    tb.add_vector(cycles=2, expected={"x": 10}, description="Good Step")
    tb.add_vector(cycles=1, expected={"x": 999}, description="Bad Step")

    runner = TestRunner()
    result = runner.run(tb)
    assert result.passed is False

    # Summary formatting
    summary = result.summary
    assert "Test Bench: ReportGenTest - FAILED" in summary
    assert "Cycles: 3 | Simulated Time: 30.0ms" in summary
    assert "Vectors: 1/2 passed" in summary
    assert "Failures (1):" in summary
    assert "Bad Step" in summary

    # to_dict & to_json without trace
    d_no_trace = result.to_dict(include_trace=False)
    assert d_no_trace["test_name"] == "ReportGenTest"
    assert d_no_trace["passed"] is False
    assert d_no_trace["total_cycles"] == 3
    assert len(d_no_trace["failures"]) == 1
    assert d_no_trace["failures"][0]["expected"] == 999
    assert d_no_trace["failures"][0]["actual"] == 15
    assert "trace" not in d_no_trace

    # to_dict & to_json with trace
    d_with_trace = result.to_dict(include_trace=True)
    assert len(d_with_trace["trace"]) == 3
    assert d_with_trace["trace"][0]["cycle"] == 1

    json_report = result.to_json(include_trace=True)
    assert '"ReportGenTest"' in json_report
    assert '"failures"' in json_report
    assert '"trace"' in json_report

def test_verification_package_exports():
    """Verifies that src.verification.test_runner re-exports identical runner classes."""
    import src.verification.test_runner as verif_runner
    import src.simulation.test_runner as sim_runner

    assert verif_runner.TestBench is sim_runner.TestBench
    assert verif_runner.TestRunner is sim_runner.TestRunner
    assert verif_runner.TestVector is sim_runner.TestVector
    assert verif_runner.AssertionFailure is sim_runner.AssertionFailure
    assert verif_runner.TestBenchResult is sim_runner.TestBenchResult

    # Execute a bench via verification module import
    v_tb = verif_runner.TestBench(name="VerifPackageCheck", program_source="VAR a: INT; END_VAR a := 42;")
    v_tb.add_vector(cycles=1, expected={"a": 42})
    v_runner = verif_runner.TestRunner()
    v_res = v_runner.run(v_tb)
    assert v_res.passed is True