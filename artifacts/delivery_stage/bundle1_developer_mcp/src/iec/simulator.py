"""IEC 61131-3 Structured Text (ST) Software Simulator for Horner Cscape.

Performs offline cyclic software simulation of ST logic without physical PLC hardware.
Evaluates assignments, expressions, conditional logic (IF-THEN-ELSE), timers, and state transitions.
"""

import math
import re
import time
from typing import Any, Dict, List, Optional, Tuple


# Strict taxonomy classification
CLASSIFICATION: str = "TESTED_MOCK [offline/DEV only]"
VERIFICATION_CLASSIFICATION: str = "TESTED_MOCK [offline/DEV only]"


class STSimulator:
    """Simulates IEC 61131-3 Structured Text execution across discrete scan cycles."""

    @classmethod
    def _evaluate_expression(cls, expr_str: str, context: Dict[str, Any]) -> Any:
        """Safely evaluates an ST expression using the current variable context."""
        expr = expr_str.strip()

        # Remove trailing semicolon if present
        if expr.endswith(";"):
            expr = expr[:-1].strip()

        # Normalize TRUE/FALSE
        expr = re.sub(r"\bTRUE\b", "True", expr, flags=re.IGNORECASE)
        expr = re.sub(r"\bFALSE\b", "False", expr, flags=re.IGNORECASE)

        # Handle IEC TIME literals like T#500ms, T#2s
        def time_replacer(match):
            val_str = match.group(1)
            unit = match.group(2).lower()
            val = float(val_str)
            if unit in ("ms", "msec"):
                return str(val)
            elif unit in ("s", "sec"):
                return str(val * 1000.0)
            elif unit in ("m", "min"):
                return str(val * 60000.0)
            return str(val)

        expr = re.sub(r"T#([0-9\.]+)(ms|s|m|msec|sec|min)", time_replacer, expr, flags=re.IGNORECASE)

        # Handle operators (case insensitive)
        expr = re.sub(r"\bAND\b", " and ", expr, flags=re.IGNORECASE)
        expr = re.sub(r"\bOR\b", " or ", expr, flags=re.IGNORECASE)
        expr = re.sub(r"\bNOT\b", " not ", expr, flags=re.IGNORECASE)
        expr = re.sub(r"\bXOR\b", " ^ ", expr, flags=re.IGNORECASE)
        expr = re.sub(r"\bMOD\b", " % ", expr, flags=re.IGNORECASE)

        # Handle comparison: <> to !=, single = to == (avoiding <=, >=, :=, !=)
        expr = expr.replace("<>", "!=")
        expr = re.sub(r"(?<![:<>=!])=(?![=])", "==", expr)

        # Build safe globals
        safe_dict = {
            "abs": abs,
            "min": min,
            "max": max,
            "round": round,
            "sin": math.sin,
            "cos": math.cos,
            "sqrt": math.sqrt,
            "True": True,
            "False": False,
        }

        # Mangle variable names to prevent Python keyword collisions (e.g. 'in', 'is', 'for')
        mangled_ctx = {f"_var_{k}": v for k, v in context.items()}
        mangled_expr = expr
        # Sort keys by length descending to prevent sub-token replacement issues
        for k in sorted(context.keys(), key=len, reverse=True):
            mangled_expr = re.sub(rf"\b{re.escape(k)}\b", f"_var_{k}", mangled_expr)

        eval_scope = {**safe_dict, **mangled_ctx}

        try:
            return eval(mangled_expr, {"__builtins__": None}, eval_scope)
        except Exception as e:
            # Fallback for simple direct string/number if eval fails
            if expr in context:
                return context[expr]
            if re.match(r"^[A-Za-z0-9_.]+$", expr.strip()):
                return expr
            raise RuntimeError(f"Expression evaluation error for '{expr}': {e}") from e

    @classmethod
    def _execute_assignment(cls, line: str, context: Dict[str, Any]) -> None:
        """Executes a single ST assignment statement: var := expr;"""
        if ":=" not in line:
            return

        parts = line.split(":=", 1)
        raw_target = parts[0].strip()
        # Clean leading semicolons or whitespace from target
        target = re.sub(r"^[\s;]+", "", raw_target).strip()
        expr = parts[1].strip().rstrip(";")

        val = cls._evaluate_expression(expr, context)
        context[target] = val

    @classmethod
    def _execute_block(cls, lines: List[str], context: Dict[str, Any]) -> None:
        """Executes a sequence of ST statements, handling IF-THEN-ELSE and assignments."""
        i = 0
        n = len(lines)

        while i < n:
            raw_line = lines[i].strip()
            # Clean leading semicolons
            clean_line = re.sub(r"^[\s;]+", "", raw_line).strip()
            if not clean_line or clean_line.startswith(("//", "(*", "/*")):
                i += 1
                continue

            # Check for IF statement
            if re.match(r"^IF\b", clean_line, re.IGNORECASE):
                # Gather entire IF...END_IF structure
                condition_match = re.match(r"^IF\s+(.+?)\s+THEN", clean_line, re.IGNORECASE)
                main_condition = condition_match.group(1) if condition_match else "True"

                branches = [{"type": "IF", "condition": main_condition, "body": []}]
                current_branch = branches[0]

                i += 1
                nesting = 1
                while i < n and nesting > 0:
                    inner_line = lines[i].strip()
                    inner_clean = re.sub(r"^[\s;]+", "", inner_line).strip()
                    if re.match(r"^IF\b", inner_clean, re.IGNORECASE):
                        nesting += 1
                        current_branch["body"].append(inner_line)
                    elif re.match(r"^END_IF\b", inner_clean, re.IGNORECASE):
                        nesting -= 1
                        if nesting == 0:
                            break
                        current_branch["body"].append(inner_line)
                    elif nesting == 1 and re.match(r"^ELSIF\s+(.+?)\s+THEN", inner_clean, re.IGNORECASE):
                        cond = re.match(r"^ELSIF\s+(.+?)\s+THEN", inner_clean, re.IGNORECASE).group(1)
                        new_branch = {"type": "ELSIF", "condition": cond, "body": []}
                        branches.append(new_branch)
                        current_branch = new_branch
                    elif nesting == 1 and re.match(r"^ELSE\b", inner_clean, re.IGNORECASE):
                        new_branch = {"type": "ELSE", "condition": "True", "body": []}
                        branches.append(new_branch)
                        current_branch = new_branch
                    else:
                        current_branch["body"].append(inner_line)
                    i += 1

                # Evaluate branches
                executed_branch = False
                for branch in branches:
                    cond_result = bool(cls._evaluate_expression(branch["condition"], context))
                    if cond_result:
                        cls._execute_block(branch["body"], context)
                        executed_branch = True
                        break

                i += 1
                continue

            # Check for assignment
            if ":=" in clean_line:
                cls._execute_assignment(clean_line, context)

            i += 1

    @classmethod
    def simulate(cls, code: str, inputs: Dict[str, Any], steps: int = 5) -> Dict[str, Any]:
        """Simulates ST execution across discrete scan cycles."""
        start_time = time.perf_counter()

        # Extract variable initial values from code
        from .validator import IECValidator
        validation = IECValidator.validate(code)
        if not validation.get("valid", False):
            errs = validation.get("errors", [])
            is_ladder = any("ERR_LADDER_FORBIDDEN" in e or "ladder" in e.lower() for e in errs)
            err_code = "ERR_LADDER_FORBIDDEN" if is_ladder else "ST_SYNTAX_ERROR"
            duration_ms = round((time.perf_counter() - start_time) * 1000, 3)
            return {
                "success": False,
                "status": "failed",
                "error_code": err_code,
                "classification": CLASSIFICATION,
                "verification_classification": VERIFICATION_CLASSIFICATION,
                "pou_name": validation.get("pou_name", "Anonymous"),
                "steps_requested": steps,
                "steps_executed": 0,
                "initial_inputs": inputs,
                "final_state": {},
                "trace": [],
                "execution_time_ms": duration_ms,
                "diagnostics": errs,
                "errors": errs,
            }

        context: Dict[str, Any] = {}
        # 1. Initialize variables from declaration defaults
        for v in validation.get("variables", []):
            v_name = v["name"]
            v_type = v.get("type", "INT").upper()
            init_val = v.get("initial_value")

            if init_val is not None:
                if init_val.upper() in ("TRUE", "FALSE"):
                    context[v_name] = init_val.upper() == "TRUE"
                else:
                    try:
                        if "." in init_val:
                            context[v_name] = float(init_val)
                        else:
                            context[v_name] = int(init_val)
                    except ValueError:
                        context[v_name] = init_val
            else:
                # Default zero-initialization according to IEC standard
                if v_type == "BOOL":
                    context[v_name] = False
                elif v_type in ("REAL", "LREAL"):
                    context[v_name] = 0.0
                elif v_type in ("STRING", "WSTRING"):
                    context[v_name] = ""
                else:
                    context[v_name] = 0

        # 2. Extract executable lines (strip VAR ... END_VAR and POU wrappers)
        clean = IECValidator.strip_comments(code)
        clean_no_vars = re.sub(
            r"\b(VAR_INPUT|VAR_OUTPUT|VAR_IN_OUT|VAR_GLOBAL|VAR_TEMP|VAR_EXTERNAL|VAR)\b[\s\S]*?\bEND_VAR\b",
            "",
            clean,
            flags=re.IGNORECASE,
        )
        clean_no_pou = re.sub(
            r"\b(PROGRAM|FUNCTION_BLOCK|FUNCTION|END_PROGRAM|END_FUNCTION_BLOCK|END_FUNCTION)\b[^\n;]*;?",
            "",
            clean_no_vars,
            flags=re.IGNORECASE,
        )

        # Normalize statements by ensuring newlines around semicolons and block keywords
        normalized = clean_no_pou
        # Split on semicolons or newlines while preserving statement integrity
        raw_statements = [s.strip() for s in normalized.splitlines() if s.strip()]
        lines: List[str] = []
        for s in raw_statements:
            # If multiple assignments on one line: e.g. "a := 1; b := 2;"
            if ";" in s and not (s.upper().startswith("IF") or s.upper().startswith("CASE") or s.upper().startswith("FOR")):
                sub_stmts = [sub.strip() for sub in s.split(";") if sub.strip()]
                lines.extend(sub_stmts)
            else:
                lines.append(s)

        trace: List[Dict[str, Any]] = []

        # Execute simulation cycles
        try:
            for step in range(1, steps + 1):
                # Apply step inputs
                step_inputs: Dict[str, Any] = {}
                for k, val in inputs.items():
                    if isinstance(val, list):
                        idx = (step - 1) % len(val)
                        applied = val[idx]
                    else:
                        applied = val
                    context[k] = applied
                    step_inputs[k] = applied

                # Execute logic cycle
                cls._execute_block(lines, context)

                trace.append({
                    "step": step,
                    "inputs": dict(step_inputs),
                    "variables": dict(context),
                })
        except Exception as e:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 3)
            return {
                "success": False,
                "status": "failed",
                "error_code": "SIMULATION_EXECUTION_ERROR",
                "classification": CLASSIFICATION,
                "verification_classification": VERIFICATION_CLASSIFICATION,
                "pou_name": validation.get("pou_name", "Anonymous"),
                "steps_requested": steps,
                "steps_executed": step - 1 if 'step' in locals() else 0,
                "initial_inputs": inputs,
                "final_state": dict(context),
                "trace": trace,
                "execution_time_ms": duration_ms,
                "diagnostics": [{"level": "ERROR", "message": str(e)}],
                "message": f"Simulation runtime error: {e}",
            }

        duration_ms = round((time.perf_counter() - start_time) * 1000, 3)

        return {
            "success": True,
            "status": "success",
            "classification": CLASSIFICATION,
            "verification_classification": VERIFICATION_CLASSIFICATION,
            "pou_name": validation.get("pou_name", "Anonymous"),
            "steps_requested": steps,
            "steps_executed": steps,
            "initial_inputs": inputs,
            "final_state": dict(context),
            "trace": trace,
            "execution_time_ms": duration_ms,
            "diagnostics": [],
        }
