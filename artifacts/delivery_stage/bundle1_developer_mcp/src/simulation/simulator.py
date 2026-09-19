"""
Pure-Software IEC 61131-3 Structured Text Simulation Engine.
Simulates execution of ST expressions, timers (TON, TOF, TP), counters (CTU, CTD),
and state machines cycle-by-cycle without physical hardware.
"""
import copy
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Callable, Union
# Strict taxonomy classification
CLASSIFICATION: str = "TESTED_MOCK [offline/DEV only]"
VERIFICATION_CLASSIFICATION: str = "TESTED_MOCK [offline/DEV only]"

from src.parser.parser import Parser
from src.parser.ast_nodes import (
    ProgramNode, VarBlockNode, VarDeclNode, StatementNode, AssignmentNode,
    FBInvocationNode, IfNode, CaseNode, CaseRange, ForNode, WhileNode,
    RepeatNode, ExitNode, EmptyStatementNode, ExpressionNode, LiteralNode,
    VariableNode, MemberAccessNode, ArrayAccessNode, BinaryOpNode,
    UnaryOpNode, FunctionCallNode
)
from .function_blocks import (
    IECFunctionBlock, TON, TOF, TP, CTU, CTD, CTUD,
    STANDARD_FB_CLASSES, STANDARD_FUNCTIONS
)

class ExitLoopSignal(Exception):
    """Internal signal used to implement the Structured Text EXIT statement."""
    pass

@dataclass
class CycleSnapshot:
    """Represents a frozen snapshot of variables and state at the end of a simulation cycle."""
    cycle: int
    time_ms: float
    dt_ms: float
    variables: Dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        # Case-insensitive lookup
        k_upper = key.upper()
        for k, v in self.variables.items():
            if k.upper() == k_upper:
                return v
        return default

class SimulationError(Exception):
    """Runtime simulation error with cycle and context information."""
    def __init__(self, message: str, cycle: int = 0, time_ms: float = 0.0):
        super().__init__(f"[Cycle {cycle} @ {time_ms:.1f}ms] {message}")
        self.cycle = cycle
        self.time_ms = time_ms

class STSimulator:
    """
    Pure-software IEC 61131-3 Structured Text Simulator.
    Simulates execution cycle-by-cycle without requiring physical PLC hardware.
    """
    def __init__(self, default_dt_ms: float = 10.0, max_loop_iterations: int = 10000):
        self.default_dt_ms = default_dt_ms
        self.max_loop_iterations = max_loop_iterations

        # Simulation state
        self.cycle_count: int = 0
        self.elapsed_time_ms: float = 0.0
        self.program: Optional[ProgramNode] = None

        # Storage
        self._raw_names: Dict[str, str] = {}         # UPPER -> original casing
        self._variables: Dict[str, Any] = {}         # UPPER -> current value
        self._initial_values: Dict[str, Any] = {}   # UPPER -> default value
        self._types: Dict[str, str] = {}             # UPPER -> declared type
        self._fbs: Dict[str, IECFunctionBlock] = {}  # UPPER -> FB instance

        # Trace history
        self.trace: List[CycleSnapshot] = []
        self.record_trace: bool = True

    def load_program(self, source_or_ast: Union[str, ProgramNode]) -> None:
        """Loads and parses an IEC 61131-3 ST program into the simulator."""
        if isinstance(source_or_ast, str):
            from ..iec.validator import IECValidator
            val_res = IECValidator.validate(source_or_ast)
            if not val_res.get("valid", False):
                errs = val_res.get("errors", [])
                is_ladder = any("ERR_LADDER_FORBIDDEN" in e or "ladder" in e.lower() for e in errs)
                err_code = "ERR_LADDER_FORBIDDEN" if is_ladder else "ST_SYNTAX_ERROR"
                raise ValueError(f"[{err_code}] Simulation POU validation failed: {'; '.join(errs)}")
            parser = Parser.from_source(source_or_ast)
            self.program = parser.parse()
        elif isinstance(source_or_ast, ProgramNode):
            self.program = source_or_ast
        else:
            raise TypeError(f"Expected str or ProgramNode, got {type(source_or_ast)}")

        self._initialize_declarations()

    def _initialize_declarations(self) -> None:
        """Initializes variables and function block instances from AST declarations."""
        self._raw_names.clear()
        self._variables.clear()
        self._initial_values.clear()
        self._types.clear()
        self._fbs.clear()
        self.cycle_count = 0
        self.elapsed_time_ms = 0.0
        self.trace.clear()

        if not self.program:
            return

        for block in self.program.var_blocks:
            for decl in block.declarations:
                name_upper = decl.name.upper()
                self._raw_names[name_upper] = decl.name
                type_upper = decl.data_type.upper()
                self._types[name_upper] = type_upper

                # Check if Function Block type
                if type_upper in STANDARD_FB_CLASSES:
                    fb_cls = STANDARD_FB_CLASSES[type_upper]
                    fb_inst = fb_cls(name=decl.name)
                    self._fbs[name_upper] = fb_inst
                    self._variables[name_upper] = fb_inst
                    self._initial_values[name_upper] = fb_cls(name=decl.name)
                elif decl.array_bounds is not None:
                    # Array variable
                    low, high = decl.array_bounds
                    size = high - low + 1
                    default_elem = self._get_default_for_type(type_upper)
                    arr_val = [copy.deepcopy(default_elem) for _ in range(size)]
                    self._variables[name_upper] = arr_val
                    self._initial_values[name_upper] = copy.deepcopy(arr_val)
                else:
                    # Scalar variable
                    if decl.initial_value is not None:
                        val = self._evaluate_expression(decl.initial_value)
                    else:
                        val = self._get_default_for_type(type_upper)
                    self._variables[name_upper] = val
                    self._initial_values[name_upper] = copy.deepcopy(val)

    def _get_default_for_type(self, type_upper: str) -> Any:
        if type_upper in ("BOOL",):
            return False
        elif type_upper in ("INT", "SINT", "DINT", "LINT", "UINT", "USINT", "UDINT", "ULINT", "BYTE", "WORD", "DWORD", "LWORD"):
            return 0
        elif type_upper in ("REAL", "LREAL"):
            return 0.0
        elif type_upper in ("TIME",):
            return 0.0
        elif type_upper in ("STRING",):
            return ""
        return 0

    def reset(self) -> None:
        """Resets the simulator variables to initial declared values and clears time counters."""
        self.cycle_count = 0
        self.elapsed_time_ms = 0.0
        self.trace.clear()
        for k, v in self._initial_values.items():
            if isinstance(v, IECFunctionBlock):
                fb_cls = STANDARD_FB_CLASSES[self._types[k]]
                fb_inst = fb_cls(name=self._raw_names[k])
                self._fbs[k] = fb_inst
                self._variables[k] = fb_inst
            else:
                self._variables[k] = copy.deepcopy(v)

    def set_variable(self, name: str, value: Any) -> None:
        """Sets the value of a variable (case-insensitive)."""
        name_upper = name.upper()
        if "." in name_upper:
            # Struct or FB member: e.g. "timer1.IN"
            base, member = name_upper.split(".", 1)
            if base in self._fbs:
                self._fbs[base].set_member(member, value)
                return
        if name_upper in self._variables:
            self._variables[name_upper] = value
        else:
            # Dynamically register variable
            self._raw_names[name_upper] = name
            self._variables[name_upper] = value

    def get_variable(self, name: str, default: Any = None) -> Any:
        """Gets the value of a variable (case-insensitive)."""
        name_upper = name.upper()
        if "." in name_upper:
            base, member = name_upper.split(".", 1)
            if base in self._fbs:
                return self._fbs[base].get_member(member)
        if name_upper in self._variables:
            val = self._variables[name_upper]
            return val
        return default

    def get_all_variables(self) -> Dict[str, Any]:
        """Returns a dict of all variables using original case names."""
        result = {}
        for k_upper, val in self._variables.items():
            orig_name = self._raw_names.get(k_upper, k_upper)
            if isinstance(val, IECFunctionBlock):
                # Flatten FB outputs/inputs into dict
                fb_dict = {
                    "inputs": dict(val.inputs),
                    "outputs": dict(val.outputs)
                }
                result[orig_name] = fb_dict
            else:
                result[orig_name] = val
        return result

    def step(self, dt_ms: Optional[float] = None) -> CycleSnapshot:
        """
        Executes one complete PLC scan cycle.
        1. Advances elapsed time and cycle count.
        2. Executes POU statements.
        3. Records snapshot in trace.
        """
        if dt_ms is None:
            dt_ms = self.default_dt_ms

        self.cycle_count += 1
        self.elapsed_time_ms += dt_ms

        # Execute statements
        if self.program:
            self._current_dt_ms = dt_ms
            for stmt in self.program.body:
                self._execute_statement(stmt)

        # Create cycle snapshot
        snap_vars = {}
        for k_upper, val in self._variables.items():
            orig = self._raw_names.get(k_upper, k_upper)
            if isinstance(val, IECFunctionBlock):
                snap_vars[orig] = {
                    "Q": val.outputs.get("Q", False),
                    "ET": val.outputs.get("ET", 0.0),
                    "CV": val.outputs.get("CV", 0),
                    "inputs": dict(val.inputs),
                    "outputs": dict(val.outputs),
                }
            else:
                snap_vars[orig] = copy.deepcopy(val)

        snapshot = CycleSnapshot(
            cycle=self.cycle_count,
            time_ms=self.elapsed_time_ms,
            dt_ms=dt_ms,
            variables=snap_vars
        )

        if self.record_trace:
            self.trace.append(snapshot)

        return snapshot

    def run_cycles(self, num_cycles: int, dt_ms: Optional[float] = None,
                   input_feed: Optional[Dict[str, List[Any]]] = None) -> List[CycleSnapshot]:
        """Runs the simulation for a specified number of cycles, optionally feeding inputs each cycle."""
        snapshots: List[CycleSnapshot] = []
        for i in range(num_cycles):
            # Apply input feed if available
            if input_feed:
                for var_name, values in input_feed.items():
                    if i < len(values):
                        self.set_variable(var_name, values[i])
            snap = self.step(dt_ms)
            snapshots.append(snap)
        return snapshots

    def run_until(self, condition: Callable[['STSimulator'], bool],
                  max_cycles: int = 1000, dt_ms: Optional[float] = None) -> List[CycleSnapshot]:
        """Runs scan cycles until the given condition function returns True or max_cycles is reached."""
        snapshots: List[CycleSnapshot] = []
        for _ in range(max_cycles):
            snap = self.step(dt_ms)
            snapshots.append(snap)
            if condition(self):
                break
        return snapshots

    # --- Statement Execution ---

    def _execute_statement(self, stmt: StatementNode) -> None:
        if isinstance(stmt, EmptyStatementNode):
            return
        elif isinstance(stmt, AssignmentNode):
            self._execute_assignment(stmt)
        elif isinstance(stmt, FBInvocationNode):
            self._execute_fb_invocation(stmt)
        elif isinstance(stmt, IfNode):
            self._execute_if(stmt)
        elif isinstance(stmt, CaseNode):
            self._execute_case(stmt)
        elif isinstance(stmt, ForNode):
            self._execute_for(stmt)
        elif isinstance(stmt, WhileNode):
            self._execute_while(stmt)
        elif isinstance(stmt, RepeatNode):
            self._execute_repeat(stmt)
        elif isinstance(stmt, ExitNode):
            raise ExitLoopSignal()
        else:
            raise SimulationError(f"Unsupported statement type: {type(stmt).__name__}", self.cycle_count, self.elapsed_time_ms)

    def _execute_assignment(self, stmt: AssignmentNode) -> None:
        val = self._evaluate_expression(stmt.value)
        target = stmt.target

        if isinstance(target, VariableNode):
            name_upper = target.name.upper()
            self._variables[name_upper] = val
            if name_upper not in self._raw_names:
                self._raw_names[name_upper] = target.name
        elif isinstance(target, MemberAccessNode):
            # Target is fb.field or obj.field
            base_val = self._evaluate_expression(target.target)
            if isinstance(base_val, IECFunctionBlock):
                base_val.set_member(target.member, val)
            elif isinstance(base_val, dict):
                base_val[target.member] = val
            else:
                raise SimulationError(f"Cannot assign member '{target.member}' on non-object {type(base_val)}", self.cycle_count, self.elapsed_time_ms)
        elif isinstance(target, ArrayAccessNode):
            arr = self._evaluate_expression(target.target)
            idx = int(self._evaluate_expression(target.index))
            # Handle 1-based indexing if standard, or 0-based
            if isinstance(arr, list):
                if 0 <= idx < len(arr):
                    arr[idx] = val
                elif 1 <= idx <= len(arr):
                    arr[idx - 1] = val
                else:
                    raise SimulationError(f"Array index out of bounds: index {idx}, size {len(arr)}", self.cycle_count, self.elapsed_time_ms)
            else:
                raise SimulationError(f"Cannot index non-array object {type(arr)}", self.cycle_count, self.elapsed_time_ms)
        else:
            raise SimulationError(f"Invalid assignment target: {type(target).__name__}", self.cycle_count, self.elapsed_time_ms)

    def _execute_fb_invocation(self, stmt: FBInvocationNode) -> None:
        # Determine target FB instance
        fb_name = ""
        if isinstance(stmt.target, VariableNode):
            fb_name = stmt.target.name.upper()
        else:
            raise SimulationError(f"Unsupported FB target: {stmt.target}", self.cycle_count, self.elapsed_time_ms)

        if fb_name not in self._fbs:
            # Check if dynamically created or auto-instantiated
            raise SimulationError(f"Unknown Function Block instance '{fb_name}'", self.cycle_count, self.elapsed_time_ms)

        fb_inst = self._fbs[fb_name]
        # Evaluate parameters
        eval_args = {}
        for param, expr in stmt.args.items():
            eval_args[param] = self._evaluate_expression(expr)

        dt = getattr(self, "_current_dt_ms", self.default_dt_ms)
        fb_inst.call(eval_args, dt_ms=dt)

    def _execute_if(self, stmt: IfNode) -> None:
        cond_val = bool(self._evaluate_expression(stmt.condition))
        if cond_val:
            for s in stmt.then_body:
                self._execute_statement(s)
            return

        for elif_cond, elif_body in stmt.elsif_blocks:
            if bool(self._evaluate_expression(elif_cond)):
                for s in elif_body:
                    self._execute_statement(s)
                return

        if stmt.else_body:
            for s in stmt.else_body:
                self._execute_statement(s)

    def _execute_case(self, stmt: CaseNode) -> None:
        selector_val = self._evaluate_expression(stmt.selector)
        matched = False

        for labels, body in stmt.cases:
            for label in labels:
                if isinstance(label, CaseRange):
                    low = self._evaluate_expression(label.start)
                    high = self._evaluate_expression(label.end)
                    if low <= selector_val <= high:
                        matched = True
                        break
                else:
                    lbl_val = self._evaluate_expression(label)
                    if lbl_val == selector_val:
                        matched = True
                        break
            if matched:
                for s in body:
                    self._execute_statement(s)
                return

        if not matched and stmt.else_body:
            for s in stmt.else_body:
                self._execute_statement(s)

    def _execute_for(self, stmt: ForNode) -> None:
        var_name = stmt.var_name.upper()
        start_val = int(self._evaluate_expression(stmt.start_expr))
        end_val = int(self._evaluate_expression(stmt.end_expr))
        step_val = int(self._evaluate_expression(stmt.step_expr)) if stmt.step_expr else 1

        if step_val == 0:
            raise SimulationError("FOR loop step BY cannot be zero", self.cycle_count, self.elapsed_time_ms)

        self._variables[var_name] = start_val
        iterations = 0

        while True:
            cur_val = self._variables[var_name]
            if (step_val > 0 and cur_val > end_val) or (step_val < 0 and cur_val < end_val):
                break

            iterations += 1
            if iterations > self.max_loop_iterations:
                raise SimulationError(f"Infinite loop detected in FOR {var_name} (exceeded {self.max_loop_iterations} iterations)", self.cycle_count, self.elapsed_time_ms)

            try:
                for s in stmt.body:
                    self._execute_statement(s)
            except ExitLoopSignal:
                break

            self._variables[var_name] += step_val

    def _execute_while(self, stmt: WhileNode) -> None:
        iterations = 0
        while bool(self._evaluate_expression(stmt.condition)):
            iterations += 1
            if iterations > self.max_loop_iterations:
                raise SimulationError(f"Infinite loop detected in WHILE (exceeded {self.max_loop_iterations} iterations)", self.cycle_count, self.elapsed_time_ms)
            try:
                for s in stmt.body:
                    self._execute_statement(s)
            except ExitLoopSignal:
                break

    def _execute_repeat(self, stmt: RepeatNode) -> None:
        iterations = 0
        while True:
            iterations += 1
            if iterations > self.max_loop_iterations:
                raise SimulationError(f"Infinite loop detected in REPEAT (exceeded {self.max_loop_iterations} iterations)", self.cycle_count, self.elapsed_time_ms)
            try:
                for s in stmt.body:
                    self._execute_statement(s)
            except ExitLoopSignal:
                break

            if bool(self._evaluate_expression(stmt.condition)):
                break

    # --- Expression Evaluation ---

    def _evaluate_expression(self, expr: ExpressionNode) -> Any:
        if isinstance(expr, LiteralNode):
            return expr.value

        elif isinstance(expr, VariableNode):
            name_upper = expr.name.upper()
            if name_upper in self._variables:
                return self._variables[name_upper]
            if name_upper in self._fbs:
                return self._fbs[name_upper]
            # Check if boolean literal representation
            if name_upper == "TRUE":
                return True
            elif name_upper == "FALSE":
                return False
            # Direct IEC / Horner register address (e.g. %S1, %R1, %I1, %Q1)
            if name_upper.startswith("%"):
                prefix = name_upper[1:3] if len(name_upper) >= 3 and name_upper[1:3].isalpha() else name_upper[1:2]
                if prefix in ("I", "Q", "M", "T", "S", "IX", "QX", "MX"):
                    val = False
                else:
                    val = 0
                self._raw_names[name_upper] = expr.name
                self._variables[name_upper] = val
                return val
            raise SimulationError(f"Undeclared or uninitialized variable '{expr.name}'", self.cycle_count, self.elapsed_time_ms)

        elif isinstance(expr, MemberAccessNode):
            target_val = self._evaluate_expression(expr.target)
            if isinstance(target_val, IECFunctionBlock):
                return target_val.get_member(expr.member)
            elif isinstance(target_val, dict):
                return target_val.get(expr.member)
            raise SimulationError(f"Cannot access member '{expr.member}' on {type(target_val)}", self.cycle_count, self.elapsed_time_ms)

        elif isinstance(expr, ArrayAccessNode):
            arr = self._evaluate_expression(expr.target)
            idx = int(self._evaluate_expression(expr.index))
            if isinstance(arr, list):
                if 0 <= idx < len(arr):
                    return arr[idx]
                elif 1 <= idx <= len(arr):
                    return arr[idx - 1]
                raise SimulationError(f"Array index {idx} out of range [0..{len(arr)-1}]", self.cycle_count, self.elapsed_time_ms)
            raise SimulationError(f"Cannot index non-array object {type(arr)}", self.cycle_count, self.elapsed_time_ms)

        elif isinstance(expr, UnaryOpNode):
            val = self._evaluate_expression(expr.operand)
            op = expr.op.upper()
            if op == "NOT":
                return not bool(val)
            elif op == "-":
                return -val
            elif op == "+":
                return +val
            raise SimulationError(f"Unknown unary operator '{op}'", self.cycle_count, self.elapsed_time_ms)

        elif isinstance(expr, BinaryOpNode):
            op = expr.op.upper()
            left = self._evaluate_expression(expr.left)
            # Short-circuit logic for AND / OR
            if op in ("AND", "&"):
                return bool(left) and bool(self._evaluate_expression(expr.right))
            elif op == "OR":
                return bool(left) or bool(self._evaluate_expression(expr.right))
            elif op == "XOR":
                return bool(left) ^ bool(self._evaluate_expression(expr.right))

            right = self._evaluate_expression(expr.right)
            if op == "+":
                return left + right
            elif op == "-":
                return left - right
            elif op == "*":
                return left * right
            elif op == "/":
                if right == 0:
                    raise SimulationError("Division by zero in ST expression", self.cycle_count, self.elapsed_time_ms)
                return left / right
            elif op == "MOD":
                if right == 0:
                    raise SimulationError("Modulo by zero in ST expression", self.cycle_count, self.elapsed_time_ms)
                return left % right
            elif op == "**":
                return left ** right
            elif op == "=":
                return left == right
            elif op == "<>":
                return left != right
            elif op == "<":
                return left < right
            elif op == "<=":
                return left <= right
            elif op == ">":
                return left > right
            elif op == ">=":
                return left >= right
            raise SimulationError(f"Unsupported binary operator '{op}'", self.cycle_count, self.elapsed_time_ms)

        elif isinstance(expr, FunctionCallNode):
            func_name = expr.name.upper()
            # Standard functions: ABS, SQRT, LIMIT, MIN, MAX, SEL, etc.
            if func_name in STANDARD_FUNCTIONS:
                func = STANDARD_FUNCTIONS[func_name]
                evaluated_args = [self._evaluate_expression(a) for a in expr.args]
                return func(*evaluated_args)
            elif func_name in self._fbs:
                # FB invocation inline
                fb = self._fbs[func_name]
                args_dict = {}
                for a in expr.args:
                    if isinstance(a, AssignmentNode) and isinstance(a.target, VariableNode):
                        args_dict[a.target.name.upper()] = self._evaluate_expression(a.value)
                dt = getattr(self, "_current_dt_ms", self.default_dt_ms)
                fb.call(args_dict, dt_ms=dt)
                return fb.outputs.get("Q", False)

            raise SimulationError(f"Unknown function '{expr.name}'", self.cycle_count, self.elapsed_time_ms)

        raise SimulationError(f"Unsupported expression node: {type(expr).__name__}", self.cycle_count, self.elapsed_time_ms)
