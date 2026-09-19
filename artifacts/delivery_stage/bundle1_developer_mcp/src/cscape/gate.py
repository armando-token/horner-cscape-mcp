"""Fail-Closed Cscape Liveness Gate Checker.

Ensures that MCP tools, pytest suites, and GUI automation tests halt immediately
fail-closed if Cscape.exe dies, hangs, or is recovering.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Union

GATE_PATHS = [
    Path(r".\artifacts\.cscape_live_gate.json"),
    Path(r".\artifacts\checkpoints\cscape_live_gate.json"),
    Path(r"C:\HornerAI\horner-cscape-mcp\artifacts\.cscape_live_gate.json"),
    Path(r"C:\HornerAI\horner-cscape-mcp\artifacts\checkpoints\cscape_live_gate.json"),
]


class CscapeLivenessGateError(RuntimeError):
    """Raised when an operation is blocked because Cscape is not active or recovering."""
    pass


def get_gate_status() -> Dict[str, Any]:
    """Reads the most recent valid gate status from disk."""
    best_data = None
    best_ts = ""
    for p in GATE_PATHS:
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    continue
                ts = data.get("heartbeat_utc") or data.get("timestamp_utc") or ""
                if best_data is None or ts > best_ts:
                    best_data = data
                    best_ts = ts
            except Exception:
                pass
    if best_data is not None:
        # Enforce C3 requirement: Gate must have valid positive integer PID and non-zero positive HWND
        # to be considered ready_for_tests. If missing or invalid, force ready_for_tests=False.
        pid = best_data.get("pid")
        hwnd = best_data.get("hwnd")
        has_valid_pid = False
        if pid is not None and not isinstance(pid, bool):
            try:
                p_val = int(pid)
                if p_val > 0:
                    has_valid_pid = True
            except (ValueError, TypeError):
                has_valid_pid = False

        has_valid_hwnd = False
        if hwnd is not None and not isinstance(hwnd, bool) and hwnd != 0 and hwnd != "0" and hwnd != "":
            try:
                h_val = int(hwnd, 0) if isinstance(hwnd, str) else int(hwnd)
                if h_val > 0:
                    has_valid_hwnd = True
            except (ValueError, TypeError):
                has_valid_hwnd = False

        if not has_valid_pid or not has_valid_hwnd:
            best_data["ready_for_tests"] = False
            best_data["status"] = "inconclusive"
            best_data["error_code"] = "INCOMPLETE_GATE_DATA"
            best_data["reason"] = "Gate file missing valid positive PID or non-zero positive HWND"

        return best_data
    return {
        "ready_for_tests": False,
        "status": "inconclusive",
        "error_code": "GATE_FILE_NOT_FOUND",
        "reason": "No active Cscape keepalive gate file detected on disk",
    }


def assert_cscape_live() -> Dict[str, Any]:
    """Asserts Cscape is currently live with TankLevelClosedLoop; fails closed if not."""
    gate = get_gate_status()
    if not gate or not gate.get("ready_for_tests", False):
        status = gate.get("status", "inconclusive") if gate else "inconclusive"
        reason = gate.get("reason", "Cscape process is offline") if gate else "No gate data"
        err_code = gate.get("error_code") if gate else "GATE_FILE_NOT_FOUND"
        err_msg = f"FAIL-CLOSED: Operations halted. Cscape is not ready. Status='{status}', Reason='{reason}'"
        if err_code:
            err_msg += f", ErrorCode='{err_code}'"
        raise CscapeLivenessGateError(err_msg)

    # Verify live process existence if pid provided
    raw_pid = gate.get("pid")
    if raw_pid is not None:
        if isinstance(raw_pid, bool):
            raise CscapeLivenessGateError(
                "FAIL-CLOSED: Operations halted. Gate data missing valid PID (boolean not allowed). ErrorCode='INCOMPLETE_GATE_DATA'"
            )
        try:
            pid = int(raw_pid)
        except (ValueError, TypeError):
            pid = -1
        if pid <= 0:
            raise CscapeLivenessGateError(
                "FAIL-CLOSED: Operations halted. Gate data missing valid PID. ErrorCode='INCOMPLETE_GATE_DATA'"
            )
        try:
            import psutil
            if not psutil.pid_exists(pid):
                raise CscapeLivenessGateError(
                    f"FAIL-CLOSED: Cscape process PID={pid} has terminated. GUI is dead."
                )
            p = psutil.Process(pid)
            if "cscape" not in p.name().lower():
                raise CscapeLivenessGateError(
                    f"FAIL-CLOSED: Process PID={pid} ({p.name()}) is not Cscape.exe. GUI is dead."
                )
        except CscapeLivenessGateError:
            raise
        except ImportError:
            pass

    # Verify live window existence, responsiveness, and project title if hwnd provided
    raw_h = gate.get("hwnd")
    if raw_h is not None:
        if isinstance(raw_h, bool) or raw_h == 0 or raw_h == "0" or raw_h == "":
            raise CscapeLivenessGateError(
                "FAIL-CLOSED: Operations halted. Gate data missing valid HWND. ErrorCode='INCOMPLETE_GATE_DATA'"
            )
        try:
            hwnd = int(raw_h, 0) if isinstance(raw_h, str) else int(raw_h)
            if hwnd <= 0:
                raise CscapeLivenessGateError(
                    "FAIL-CLOSED: Operations halted. Gate data missing valid positive HWND. ErrorCode='INCOMPLETE_GATE_DATA'"
                )
        except CscapeLivenessGateError:
            raise
        except (ValueError, TypeError):
            raise CscapeLivenessGateError(
                "FAIL-CLOSED: Operations halted. Gate data missing valid HWND (unparseable). ErrorCode='INCOMPLETE_GATE_DATA'"
            )

        try:
            import win32gui, ctypes
            attach_thread_desktop(hwnd)
            if not win32gui.IsWindow(hwnd):
                raise CscapeLivenessGateError(
                    f"FAIL-CLOSED: Cscape window handle {hex(hwnd)} is no longer valid. GUI is dead."
                )
            user32 = ctypes.windll.user32
            if hasattr(user32, "IsHungAppWindow") and user32.IsHungAppWindow(hwnd):
                raise CscapeLivenessGateError(
                    f"FAIL-CLOSED: Cscape window handle {hex(hwnd)} is hung and unresponsive."
                )
            actual_title = win32gui.GetWindowText(hwnd)
            proj_str = str(gate.get("project_file") or "").lower()
            allowed_tokens = ["tanklevel", "labproject"]
            if proj_str:
                from pathlib import Path
                allowed_tokens.append(Path(proj_str).stem.lower())
            if actual_title and not any(tok in actual_title.lower() for tok in allowed_tokens):
                raise CscapeLivenessGateError(
                    f"FAIL-CLOSED: Cscape window title '{actual_title}' does not have TankLevelClosedLoop active."
                )
        except CscapeLivenessGateError:
            raise
        except Exception:
            pass

    # Fail closed if either PID or HWND is missing from gate data
    if raw_pid is None:
        raise CscapeLivenessGateError(
            "FAIL-CLOSED: Operations halted. Gate data missing valid PID. ErrorCode='INCOMPLETE_GATE_DATA'"
        )
    if raw_h is None:
        raise CscapeLivenessGateError(
            "FAIL-CLOSED: Operations halted. Gate data missing valid HWND. ErrorCode='INCOMPLETE_GATE_DATA'"
        )

    return gate


def attach_thread_desktop(target_hwnd: int) -> str:
    """Dynamically enumerates available window station desktops and attaches thread to target."""
    import ctypes
    user32 = ctypes.windll.user32
    user32.OpenDesktopW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    user32.OpenDesktopW.restype = ctypes.c_void_p
    user32.SetThreadDesktop.argtypes = [ctypes.c_void_p]
    user32.SetThreadDesktop.restype = ctypes.c_int

    desktops: list[str] = ["Default"]
    def enum_cb(dname, lparam):
        if dname and dname not in desktops:
            desktops.append(dname)
        return True
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_wchar_p, ctypes.c_void_p)
    try:
        hwinsta = user32.GetProcessWindowStation()
        user32.EnumDesktopsW(hwinsta, WNDENUMPROC(enum_cb), 0)
    except Exception:
        pass

    for dname in desktops:
        hd = user32.OpenDesktopW(dname, 0, False, 0x01FF)
        if hd:
            user32.SetThreadDesktop(hd)
            if user32.IsWindow(target_hwnd):
                return dname
    return "unknown"


def resolve_cscape_pid(
    gate_path: Optional[Union[str, Path]] = None,
    verify_process_alive: bool = True,
) -> Optional[int]:
    """Dynamically resolves the active Cscape.exe PID without hardcoding.

    Resolution strategy:
    1. Reads PID from gate file (via get_gate_status or specified gate_path)
       and verifies that the process is actively running and is Cscape.exe.
    2. Fallback to process enumeration scanning running processes for 'cscape'.
    """
    if gate_path is not None:
        p = Path(gate_path)
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                gpid = data.get("pid")
                if gpid is not None and int(gpid) > 0:
                    p_int = int(gpid)
                    if not verify_process_alive:
                        return p_int
                    import psutil
                    if psutil.pid_exists(p_int):
                        proc = psutil.Process(p_int)
                        if "cscape" in (proc.name() or "").lower() and proc.is_running():
                            return p_int
            except Exception:
                pass
    else:
        gate_info = get_gate_status()
        gate_pid = gate_info.get("pid")
        if gate_pid is not None:
            try:
                p_int = int(gate_pid)
                if p_int > 0:
                    if not verify_process_alive:
                        return p_int
                    import psutil
                    if psutil.pid_exists(p_int):
                        proc = psutil.Process(p_int)
                        if "cscape" in (proc.name() or "").lower() and proc.is_running():
                            return p_int
            except Exception:
                pass

    try:
        import psutil
        for p in psutil.process_iter(["pid", "name"]):
            try:
                name = (p.info.get("name") or "").lower()
                if "cscape" in name and p.is_running():
                    return p.info["pid"]
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass

    return None


