"""
IEC 61131-3 Structured Text Test Bench Runner.
Executes verification test benches on ST programs against expected test vectors.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable, Union
import json
import math

from .simulator import STSimulator, CycleSnapshot, SimulationError

@dataclass
class TestVector:
    __test__ = False
    """
    Defines a test vector: inputs applied for N cycles, followed by expected variable checks.
    """
    inputs: Dict[str, Any] = field(default_factory=dict)
    expected: Dict[str, Any] = field(default_factory=dict)
    cycles: int = 1
    description: str = ""
    tolerance: float = 1e-4

    def to_dict(self) -> Dict[str, Any]:
        return {
            "inputs": dict(self.inputs),
            "expected": dict(self.expected),
            "cycles": self.cycles,
            "description": self.description,
            "tolerance": self.tolerance,
        }

@dataclass
class AssertionFailure:
    """Records a failure when actual value does not match expected test vector value."""
    cycle: int
    time_ms: float
    variable: str
    expected: Any
    actual: Any
    description: str
    message: str

    def __str__(self) -> str:
        return (
            f"[Cycle {self.cycle} @ {self.time_ms:.1f}ms] Variable '{self.variable}' "
            f"expected {self.expected!r}, got {self.actual!r}. ({self.description})"
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cycle": self.cycle,
            "time_ms": self.time_ms,
            "variable": self.variable,
            "expected": self.expected,
            "actual": self.actual,
            "description": self.description,
            "message": self.message,
        }

@dataclass
class TestBenchResult:
    __test__ = False
    """Structured report produced after executing a test bench."""
    test_name: str
    passed: bool
    total_cycles: int
    total_time_ms: float
    vectors_run: int
    vectors_passed: int
    failures: List[AssertionFailure] = field(default_factory=list)
    trace: List[CycleSnapshot] = field(default_factory=list)

    @property
    def summary(self) -> str:
        status = "PASSED" if self.passed else "FAILED"
        lines = [
            f"Test Bench: {self.test_name} - {status}",
            f"  Cycles: {self.total_cycles} | Simulated Time: {self.total_time_ms:.1f}ms",
            f"  Vectors: {self.vectors_passed}/{self.vectors_run} passed",
        ]
        if self.failures:
            lines.append(f"  Failures ({len(self.failures)}):")
            for f in self.failures:
                lines.append(f"    - {f}")
        return "\n".join(lines)

    def to_dict(self, include_trace: bool = False) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "test_name": self.test_name,
            "passed": self.passed,
            "total_cycles": self.total_cycles,
            "total_time_ms": self.total_time_ms,
            "vectors_run": self.vectors_run,
            "vectors_passed": self.vectors_passed,
            "failures": [f.to_dict() for f in self.failures],
            "summary": self.summary,
        }
        if include_trace:
            data["trace"] = [
                {
                    "cycle": s.cycle,
                    "time_ms": s.time_ms,
                    "dt_ms": s.dt_ms,
                    "variables": dict(s.variables),
                }
                for s in self.trace
            ]
        return data

    def to_json(self, indent: int = 2, include_trace: bool = False) -> str:
        return json.dumps(self.to_dict(include_trace=include_trace), indent=indent, default=str)

class TestBench:
    __test__ = False
    """
    Represents an IEC 61131-3 Structured Text Test Bench.
    """
    def __init__(
        self,
        name: str,
        program_source: str,
        scan_time_ms: float = 10.0,
        vectors: Optional[List[TestVector]] = None,
        setup_variables: Optional[Dict[str, Any]] = None,
        custom_assertions: Optional[List[Callable[[STSimulator], Optional[str]]]] = None
    ):
        self.name = name
        self.program_source = program_source
        self.scan_time_ms = scan_time_ms
        self.vectors: List[TestVector] = vectors or []
        self.setup_variables: Dict[str, Any] = setup_variables or {}
        self.custom_assertions: List[Callable[[STSimulator], Optional[str]]] = custom_assertions or []

    def add_vector(
        self,
        inputs: Optional[Dict[str, Any]] = None,
        expected: Optional[Dict[str, Any]] = None,
        cycles: int = 1,
        description: str = "",
        tolerance: float = 1e-4
    ) -> "TestBench":
        self.vectors.append(TestVector(
            inputs=inputs or {},
            expected=expected or {},
            cycles=cycles,
            description=description,
            tolerance=tolerance
        ))
        return self

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TestBench":
        tb = cls(
            name=d.get("name", "UnnamedTestBench"),
            program_source=d.get("program", ""),
            scan_time_ms=d.get("scan_time_ms", 10.0),
            setup_variables=d.get("setup", {})
        )
        for vec_data in d.get("vectors", []):
            tb.add_vector(
                inputs=vec_data.get("inputs", {}),
                expected=vec_data.get("expected", {}),
                cycles=vec_data.get("cycles", 1),
                description=vec_data.get("description", ""),
                tolerance=vec_data.get("tolerance", 1e-4)
            )
        return tb

    def to_dict(self) -> Dict[str, Any]:
        """Serializes TestBench configuration to a dictionary."""
        return {
            "name": self.name,
            "program": self.program_source,
            "scan_time_ms": self.scan_time_ms,
            "setup": dict(self.setup_variables),
            "vectors": [v.to_dict() for v in self.vectors],
        }

    def to_json(self, indent: int = 2) -> str:
        """Serializes TestBench configuration to a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_file(cls, file_path: Union[str, Path]) -> "TestBench":
        """Loads a TestBench definition from a JSON file."""
        p = Path(file_path)
        with open(p, "r", encoding="utf-8") as f:
            return cls.from_json(f.read())

    def to_file(self, file_path: Union[str, Path], indent: int = 2) -> None:
        """Writes TestBench definition to a JSON file."""
        p = Path(file_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(self.to_json(indent=indent))

    @classmethod
    def from_json(cls, json_str: str) -> "TestBench":
        return cls.from_dict(json.loads(json_str))

class TestRunner:
    __test__ = False
    """
    Executes TestBench suites against the STSimulator pure software runtime.
    """
    def __init__(self):
        pass

    def run(self, test_bench: TestBench) -> TestBenchResult:
        """Executes the test bench and returns a comprehensive TestBenchResult."""
        sim = STSimulator(default_dt_ms=test_bench.scan_time_ms)
        sim.load_program(test_bench.program_source)

        # Apply setup variables
        for var_name, val in test_bench.setup_variables.items():
            sim.set_variable(var_name, val)

        failures: List[AssertionFailure] = []
        vectors_passed = 0

        for vec_idx, vec in enumerate(test_bench.vectors):
            # Apply inputs before stepping
            for var_name, val in vec.inputs.items():
                sim.set_variable(var_name, val)

            # Step the required number of cycles
            for _ in range(max(1, vec.cycles)):
                sim.step()

            # Verify expected outputs
            vec_failed = False
            for var_name, exp_val in vec.expected.items():
                actual_val = sim.get_variable(var_name)
                matched = self._values_match(exp_val, actual_val, vec.tolerance)
                if not matched:
                    vec_failed = True
                    failures.append(AssertionFailure(
                        cycle=sim.cycle_count,
                        time_ms=sim.elapsed_time_ms,
                        variable=var_name,
                        expected=exp_val,
                        actual=actual_val,
                        description=vec.description or f"Vector {vec_idx + 1}",
                        message=f"Expected {exp_val!r} but found {actual_val!r}"
                    ))

            if not vec_failed:
                vectors_passed += 1

        # Run any custom assertion callbacks
        for custom_fn in test_bench.custom_assertions:
            err = custom_fn(sim)
            if err:
                failures.append(AssertionFailure(
                    cycle=sim.cycle_count,
                    time_ms=sim.elapsed_time_ms,
                    variable="custom_assertion",
                    expected="Pass",
                    actual="Fail",
                    description="Custom assertion hook",
                    message=err
                ))

        passed = (len(failures) == 0)

        return TestBenchResult(
            test_name=test_bench.name,
            passed=passed,
            total_cycles=sim.cycle_count,
            total_time_ms=sim.elapsed_time_ms,
            vectors_run=len(test_bench.vectors),
            vectors_passed=vectors_passed,
            failures=failures,
            trace=list(sim.trace)
        )

    def assert_test_bench(self, test_bench: TestBench) -> TestBenchResult:
        """Executes test bench and raises AssertionError if any check fails."""
        result = self.run(test_bench)
        if not result.passed:
            raise AssertionError(f"Test Bench '{test_bench.name}' failed:\n{result.summary}")
        return result

    def _values_match(self, expected: Any, actual: Any, tolerance: float) -> bool:
        if expected is None:
            return actual is None
        if isinstance(expected, bool):
            return isinstance(actual, bool) and (actual == expected)
        if isinstance(actual, bool):
            return False
        if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
            return math.isclose(float(expected), float(actual), abs_tol=tolerance)
        return expected == actual