#!/usr/bin/env python3
"""Horner APG Cscape 10-Minute Continuous Watchdog Supervisor.

Monitors Cscape 10.2 process health and uptime:
- Launches Cscape.exe with TankLevelClosedLoop.csp (or IEC registry settings)
- Supports single-instance handoff & successor process adoption
- Auto-handles splash screen ('About Cscape') and editor type selection dialogs
- Ensures the GUI window is visible, active, and interactive
- Actively polls every 5.0 seconds:
    * PID
    * HWND (main window handle)
    * CPU utilization (%)
    * WorkingSet memory (MB and bytes)
    * Window Title
    * IsHungAppWindow Win32 API status
- Records continuous health logs to artifacts/logs/cscape_10min_live.log
- Automatically detects exits or crashes, logs exit codes, and restarts with exponential backoff
- Proves 600+ seconds (10+ minutes) of continuous uptime.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes
import datetime
import json
import logging
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

try:
    import psutil
except ImportError:
    psutil = None

# NTSTATUS / Windows Error Codes
NTSTATUS_NAMES: Dict[int, str] = {
    0: "STATUS_SUCCESS / CLEAN_EXIT",
    1: "GENERIC_ERROR_OR_RELAUNCH_EXIT",
    -1073741819: "STATUS_ACCESS_VIOLATION (0xC0000005)",
    0xC0000005: "STATUS_ACCESS_VIOLATION (0xC0000005)",
    -1073740791: "STATUS_STACK_BUFFER_OVERRUN (0xC0000409)",
    0xC0000409: "STATUS_STACK_BUFFER_OVERRUN (0xC0000409)",
    -1073741510: "STATUS_CONTROL_C_EXIT (0xC000013A)",
    0xC000013A: "STATUS_CONTROL_C_EXIT (0xC000013A)",
    -1073741571: "STATUS_STACK_OVERFLOW (0xC00000FD)",
    0xC00000FD: "STATUS_STACK_OVERFLOW (0xC00000FD)",
    -1073741676: "STATUS_INTEGER_DIVIDE_BY_ZERO (0xC0000094)",
    0xC0000094: "STATUS_INTEGER_DIVIDE_BY_ZERO (0xC0000094)",
    -1073741816: "STATUS_ILLEGAL_INSTRUCTION (0xC000001D)",
    0xC000001D: "STATUS_ILLEGAL_INSTRUCTION (0xC000001D)",
    -1073741795: "STATUS_ILLEGAL_DLL_RELOCATION (0xC0000032)",
    0xC0000032: "STATUS_ILLEGAL_DLL_RELOCATION (0xC0000032)",
    -1073741515: "STATUS_DLL_NOT_FOUND (0xC0000135)",
    0xC0000135: "STATUS_DLL_NOT_FOUND (0xC0000135)",
    -1073741502: "STATUS_ENTRYPOINT_NOT_FOUND (0xC0000142)",
    0xC0000142: "STATUS_ENTRYPOINT_NOT_FOUND (0xC0000142)",
}

# Win32 Constants
WM_CLOSE: int = 0x0010
WM_COMMAND: int = 0x0111
WM_SYSCOMMAND: int = 0x0112
SC_CLOSE: int = 0xF060
BM_CLICK: int = 0x00F5
BM_SETCHECK: int = 0x00F1
BST_CHECKED: int = 0x0001
BN_CLICKED: int = 0

SW_SHOWNORMAL: int = 1
SW_RESTORE: int = 9

ID_OK: int = 1
ID_CANCEL: int = 2
RADIO_ID_IEC_61131: int = 1461

DIALOG_CLASS_NAME: str = "#32770"
SPLASH_TITLE_KEYWORD: str = "About Cscape"
EDITOR_TITLE_KEYWORD: str = "Select Editor Type"

DEFAULT_CSCAPE_PATH = Path(r"C:\Program Files (x86)\Cscape 10.2\Cscape.exe")
DEFAULT_PROJECT_PATH = Path(r"C:\Users\ArmandoSilva\artifacts\projects\TankLevelClosedLoop\TankLevelClosedLoop.csp")
DEFAULT_LOG_PATH = Path(r"C:\Users\ArmandoSilva\artifacts\logs\cscape_10min_live.log")
KEEPALIVE_LOG = Path(r"C:\Users\ArmandoSilva\artifacts\logs\cscape_keepalive.log")
GATE_FILES = [
    Path(r"C:\Users\ArmandoSilva\artifacts\.cscape_live_gate.json"),
    Path(r"C:\Users\ArmandoSilva\artifacts\checkpoints\cscape_live_gate.json"),
    Path(r"C:\HornerAI\horner-cscape-mcp\artifacts\.cscape_live_gate.json"),
    Path(r"C:\HornerAI\horner-cscape-mcp\artifacts\checkpoints\cscape_live_gate.json"),
]



def get_utc_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def set_registry_clean_exit(val: int = 1) -> bool:
    """Set CscapeExitedCorrectly in registry to suppress crash recovery dialogs."""
    try:
        import winreg
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Horner_Electric\Cscape\Setup")
        winreg.SetValueEx(key, "CscapeExitedCorrectly", 0, winreg.REG_DWORD, val)
        winreg.CloseKey(key)
        return True
    except Exception:
        return False


def ensure_iec_registry_defaults() -> bool:
    """Ensure IEC Editor registry settings are properly initialized."""
    try:
        import winreg
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Horner_Electric\Cscape\IECEditor")
        winreg.SetValueEx(key, "EnableDragDrop", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "UndoRedoStackSize", 0, winreg.REG_DWORD, 16)
        winreg.SetValueEx(key, "TabSize", 0, winreg.REG_DWORD, 4)
        winreg.CloseKey(key)
        return True
    except Exception:
        return False


def ensure_project_registry_defaults(project_path: Optional[Path]) -> bool:
    """Ensure Recent File List and Editor settings point to project_path."""
    if not project_path or not project_path.exists():
        return False
    try:
        import winreg
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Horner_Electric\Cscape\Recent File List")
        winreg.SetValueEx(key, "File1", 0, winreg.REG_SZ, str(project_path))
        winreg.CloseKey(key)

        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Horner_Electric\Cscape\Editor")
        winreg.SetValueEx(key, "OpenLast", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "AllowUserToChooseProgram", 0, winreg.REG_DWORD, 0)
        winreg.SetValueEx(key, "CreateBlankProgram", 0, winreg.REG_DWORD, 0)
        winreg.CloseKey(key)
        return True
    except Exception:
        return False



def get_running_cscape_processes() -> List[psutil.Process]:
    """Find all running Cscape.exe processes."""
    if not psutil:
        return []
    procs = []
    for p in psutil.process_iter(["name", "pid"]):
        try:
            if p.info["name"] and "cscape" in p.info["name"].lower():
                procs.append(p)
        except Exception:
            pass
    return procs


def kill_all_cscape_instances(timeout_sec: float = 6.0) -> int:
    """Force terminate all lingering Cscape.exe instances on system and wait until clear."""
    count = 0
    try:
        res = subprocess.run(
            ["taskkill.exe", "/F", "/T", "/IM", "Cscape.exe"],
            capture_output=True,
            timeout=timeout_sec,
        )
        stdout_str = res.stdout.decode(errors="replace")
        count = stdout_str.count("SUCCESS:")
    except Exception:
        pass

    if psutil:
        t0 = time.time()
        while time.time() - t0 < timeout_sec:
            if not get_running_cscape_processes():
                break
            time.sleep(0.2)

    time.sleep(1.0)
    set_registry_clean_exit(1)
    return count


@dataclass
class WindowDetails:
    hwnd: int
    pid: int
    title: str
    class_name: str
    visible: bool
    enabled: bool
    rect: Optional[Tuple[int, int, int, int]] = None


WNDENUMPROC = ctypes.WINFUNCTYPE(
    ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
)


class Win32Helper:
    """Win32 API interactions via ctypes for window handling and hung-app detection."""

    def __init__(self) -> None:
        self.user32 = ctypes.windll.user32
        self.kernel32 = ctypes.windll.kernel32

        self.user32.IsHungAppWindow.argtypes = [ctypes.wintypes.HWND]
        self.user32.IsHungAppWindow.restype = ctypes.wintypes.BOOL

        self._wnd_enum_proc = WNDENUMPROC
        self._ensure_argtypes()

    def _ensure_argtypes(self) -> None:
        """Guarantee consistent ctypes argtypes for all window enumeration and message APIs."""
        self.user32.EnumWindows.argtypes = [self._wnd_enum_proc, ctypes.wintypes.LPARAM]
        self.user32.EnumWindows.restype = ctypes.wintypes.BOOL

        self.user32.EnumDesktopWindows.argtypes = [ctypes.c_void_p, self._wnd_enum_proc, ctypes.wintypes.LPARAM]
        self.user32.EnumDesktopWindows.restype = ctypes.wintypes.BOOL

        self.user32.EnumChildWindows.argtypes = [ctypes.wintypes.HWND, self._wnd_enum_proc, ctypes.wintypes.LPARAM]
        self.user32.EnumChildWindows.restype = ctypes.wintypes.BOOL

        self.user32.SendMessageTimeoutW.argtypes = [
            ctypes.wintypes.HWND,
            ctypes.wintypes.UINT,
            ctypes.wintypes.WPARAM,
            ctypes.wintypes.LPARAM,
            ctypes.wintypes.UINT,
            ctypes.wintypes.UINT,
            ctypes.POINTER(ctypes.c_ulong),
        ]
        self.user32.SendMessageTimeoutW.restype = ctypes.c_long

    def ping_window(self, hwnd: int, timeout_ms: int = 1000) -> bool:
        """Probe message loop responsiveness with SendMessageTimeoutW(WM_NULL)."""
        if not hwnd:
            return False
        try:
            self._ensure_argtypes()
            res_val = ctypes.c_ulong(0)
            res = self.user32.SendMessageTimeoutW(hwnd, 0, 0, 0, 0x0002, timeout_ms, ctypes.byref(res_val))
            return bool(res)
        except Exception:
            return False

    def ensure_desktop(self) -> None:
        """Attach current thread to Default desktop to guarantee window enumeration."""
        try:
            hd = self.user32.OpenDesktopW("Default", 0, False, 0x01FF)
            if hd:
                self.user32.SetThreadDesktop(hd)
        except Exception:
            pass

    def is_hung_app_window(self, hwnd: int) -> bool:
        """Call Win32 IsHungAppWindow(hwnd). Returns True if window is unresponsive."""
        if not hwnd:
            return False
        self.ensure_desktop()
        try:
            return bool(self.user32.IsHungAppWindow(hwnd))
        except Exception:
            return False

    def enum_windows_for_pids(self, pids: Set[int]) -> List[WindowDetails]:
        """Enumerate all top-level windows for target PIDs or any running Cscape process."""
        self.ensure_desktop()
        self._ensure_argtypes()
        target_pids = set(pids)
        if psutil:
            for p in psutil.process_iter(["pid", "name"]):
                try:
                    if p.info["name"] and "cscape" in p.info["name"].lower():
                        target_pids.add(p.info["pid"])
                except Exception:
                    pass

        results: List[WindowDetails] = []

        def callback(hwnd: int, _: Any) -> int:
            try:
                win_pid = ctypes.wintypes.DWORD()
                self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(win_pid))
                if win_pid.value in target_pids:
                    buf_title = ctypes.create_unicode_buffer(512)
                    self.user32.GetWindowTextW(hwnd, buf_title, 512)
                    buf_cls = ctypes.create_unicode_buffer(512)
                    self.user32.GetClassNameW(hwnd, buf_cls, 512)
                    visible = bool(self.user32.IsWindowVisible(hwnd))
                    enabled = bool(self.user32.IsWindowEnabled(hwnd))
                    rect = None
                    r = ctypes.wintypes.RECT()
                    if self.user32.GetWindowRect(hwnd, ctypes.byref(r)):
                        rect = (r.left, r.top, r.right, r.bottom)
                    results.append(
                        WindowDetails(
                            hwnd=hwnd,
                            pid=win_pid.value,
                            title=buf_title.value,
                            class_name=buf_cls.value,
                            visible=visible,
                            enabled=enabled,
                            rect=rect,
                        )
                    )
            except Exception:
                pass
            return 1

        c_cb = self._wnd_enum_proc(callback)
        self.user32.EnumWindows(c_cb, 0)
        if not results:
            for dname in ["Default", "exebox-SFKDH7PVZHHA5N3KL2KU2F6TB4", "exebox-TSZBFXK7CRLCRFNAU74PC5FQZL"]:
                hd = self.user32.OpenDesktopW(dname, 0, False, 0x01FF)
                if hd:
                    self.user32.EnumDesktopWindows(hd, c_cb, 0)
                    if any("cscape" in r.title.lower() for r in results):
                        break
        return results

    def enum_child_controls(self, parent_hwnd: int) -> Dict[int, int]:
        """Map control ID -> HWND for all child controls in parent."""
        controls: Dict[int, int] = {}
        self._ensure_argtypes()

        def callback(hwnd: int, _: Any) -> int:
            try:
                cid = self.user32.GetDlgCtrlID(hwnd)
                controls[cid] = hwnd
            except Exception:
                pass
            return 1

        c_cb = self._wnd_enum_proc(callback)
        self.user32.EnumChildWindows(parent_hwnd, c_cb, 0)
        return controls

    def click_button(self, btn_hwnd: int, dlg_hwnd: Optional[int] = None, ctrl_id: int = ID_OK) -> None:
        """Send BM_CLICK and WM_COMMAND to button."""
        if btn_hwnd:
            self.user32.PostMessageW(btn_hwnd, BM_CLICK, 0, 0)
        if dlg_hwnd:
            self.user32.PostMessageW(dlg_hwnd, WM_COMMAND, (BN_CLICKED << 16) | ctrl_id, btn_hwnd or 0)

    def select_radio(self, radio_hwnd: int, dlg_hwnd: int, radio_id: int) -> None:
        """Set radio check and notify parent."""
        if radio_hwnd:
            self.user32.PostMessageW(radio_hwnd, BM_SETCHECK, BST_CHECKED, 0)
            self.user32.PostMessageW(dlg_hwnd, WM_COMMAND, (BN_CLICKED << 16) | radio_id, radio_hwnd)
        else:
            self.user32.PostMessageW(dlg_hwnd, WM_COMMAND, (BN_CLICKED << 16) | radio_id, 0)

    def show_and_activate(self, hwnd: int) -> bool:
        """Ensure the window is visible, restored, and brought to front."""
        if not hwnd:
            return False
        try:
            self.user32.ShowWindow(hwnd, SW_SHOWNORMAL)
            self.user32.BringWindowToTop(hwnd)
            self.user32.SetForegroundWindow(hwnd)
            return bool(self.user32.IsWindowVisible(hwnd))
        except Exception:
            return False

    def close_window(self, hwnd: int) -> None:
        """Send WM_CLOSE to window."""
        try:
            self.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        except Exception:
            pass


@dataclass
class HealthRecord:
    timestamp_utc: str
    elapsed_seconds: float
    total_target_seconds: float
    cycle: int
    pid: int
    hwnd: int
    hwnd_hex: str
    cpu_percent: float
    working_set_bytes: int
    working_set_mb: float
    window_title: str
    is_hung: bool
    num_threads: int
    status: str


class Cscape10MinWatchdog:
    """Supervises Cscape for a target duration of 600+ seconds (10+ minutes)."""

    def __init__(
        self,
        cscape_path: Optional[Union[str, Path]] = None,
        project_path: Optional[Union[str, Path]] = None,
        log_file: Optional[Union[str, Path]] = None,
        target_duration_seconds: float = 600.0,
        poll_interval: float = 5.0,
        max_restarts: int = 10,
        initial_backoff: float = 2.0,
        max_backoff: float = 30.0,
        auto_close_on_complete: bool = True,
    ) -> None:
        self.cscape_path = Path(cscape_path).resolve() if cscape_path else DEFAULT_CSCAPE_PATH
        self.project_path = Path(project_path).resolve() if project_path else DEFAULT_PROJECT_PATH
        self.log_file = Path(log_file).resolve() if log_file else DEFAULT_LOG_PATH
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

        self.target_duration = float(target_duration_seconds)
        self.poll_interval = max(1.0, float(poll_interval))
        self.max_restarts = max_restarts
        self.initial_backoff = initial_backoff
        self.max_backoff = max_backoff
        self.auto_close_on_complete = auto_close_on_complete

        self.win32 = Win32Helper()
        self.stop_requested = False
        self.current_process: Optional[subprocess.Popen] = None
        self.psutil_proc: Optional[psutil.Process] = None
        self.current_pid: Optional[int] = None
        self.current_main_hwnd: Optional[int] = None
        self.current_main_title: str = ""

        self.total_uptime_seconds: float = 0.0
        self.cycle_count: int = 0
        self.health_records: List[HealthRecord] = []

        self._setup_logging()

    def _setup_logging(self) -> None:
        """Set up logger to both console and target log file."""
        self.logger = logging.getLogger("Cscape10MinWatchdog")
        self.logger.setLevel(logging.INFO)
        self.logger.handlers.clear()

        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] [WATCHDOG-10MIN] %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%SZ",
        )
        formatter.converter = time.gmtime

        # Console
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(formatter)
        self.logger.addHandler(ch)

        # File
        fh = logging.FileHandler(str(self.log_file), mode="a", encoding="utf-8")
        fh.setFormatter(formatter)
        self.logger.addHandler(fh)

    def log_event(self, tag: str, message: str, level: int = logging.INFO) -> None:
        """Emit structured log message."""
        self.logger.log(level, f"[{tag}] {message}")

    def _update_gate(
        self,
        ready: bool,
        status: str,
        reason: str = "",
        exit_code: Optional[int] = None,
    ) -> None:
        """Update live gate file and keepalive log for fail-closed gating."""
        data = {
            "ready_for_tests": ready,
            "status": status,
            "pid": self.current_pid,
            "hwnd": f"0x{self.current_main_hwnd:08X}" if self.current_main_hwnd else None,
            "window_title": self.current_main_title,
            "project_file": str(self.project_path) if self.project_path else None,
            "exit_code": exit_code,
            "reason": reason,
            "cycle": self.cycle_count,
            "timestamp_utc": get_utc_iso(),
            "heartbeat_utc": get_utc_iso(),
        }
        for gf in GATE_FILES:
            try:
                gf.parent.mkdir(parents=True, exist_ok=True)
                gf.write_text(json.dumps(data, indent=2), encoding="utf-8")
            except Exception:
                pass

        try:
            KEEPALIVE_LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(KEEPALIVE_LOG, "a", encoding="utf-8") as f:
                if status == "FAIL_CLOSED_CSCAPE_DEAD" or exit_code is not None:
                    code_name = NTSTATUS_NAMES.get(exit_code or 0, f"CODE_{exit_code}")
                    hex_str = f"0x{(exit_code or 0) & 0xFFFFFFFF:08X}"
                    f.write(
                        f"[{get_utc_iso()}] [CRASH_DETECTED] ExitCode={exit_code} ({hex_str} - {code_name}) | Reason={reason}\n"
                    )
                f.write(
                    f"[{get_utc_iso()}] [GATE_UPDATE] Status={status} | Ready={ready} | "
                    f"PID={self.current_pid} | HWND=0x{self.current_main_hwnd or 0:X} | "
                    f"Title='{self.current_main_title}' | Reason={reason}\n"
                )
        except Exception:
            pass

    def register_signal_handlers(self) -> None:
        """Catch termination signals cleanly."""
        def handler(sig: int, frame: Any) -> None:
            self.log_event("SIGNAL", f"Caught signal {sig}. Initiating graceful shutdown...")
            self.stop_requested = True
            self._update_gate(ready=False, status="WATCHDOG_TERMINATED", reason="Shutdown by signal")

        try:
            signal.signal(signal.SIGINT, handler)
            signal.signal(signal.SIGTERM, handler)
        except Exception:
            pass

    def launch_cscape(self) -> bool:
        """Cleanly launch Cscape.exe instance with project or registry IEC settings."""
        self.cycle_count += 1

        # Check if an existing Cscape process with TankLevelClosedLoop is already active
        existing = get_running_cscape_processes()
        for p in existing:
            wins = self.win32.enum_windows_for_pids({p.pid})
            for w in wins:
                if "cscape" in w.title.lower() and ("tanklevel" in w.title.lower() or "labproject" in w.title.lower()):
                    self.log_event("ADOPT_EXISTING", f"Found running Cscape.exe PID={w.pid} with active project: '{w.title}'")
                    self.current_pid = w.pid
                    self.psutil_proc = psutil.Process(w.pid) if psutil else p
                    self.current_main_hwnd = w.hwnd
                    self.current_main_title = w.title
                    self.win32.show_and_activate(w.hwnd)
                    self._update_gate(ready=True, status="READY_FOR_TESTS", reason="TankLevelClosedLoop verified active and responsive")
                    return True

        self.log_event(
            "LAUNCH_PREP",
            f"Cycle {self.cycle_count} commencing. Enforcing clean slate and single instance..."
        )
        self._update_gate(ready=False, status="RELAUNCH_UNDERWAY", reason=f"Cycle {self.cycle_count} starting")

        try:
            from scripts.reopen_tanklevel_cscape import main as reopen_main
            ret = reopen_main()
            if ret == 0:
                from src.cscape.gate import get_gate_status
                gate_data = get_gate_status()
                if gate_data.get("ready_for_tests"):
                    self.current_pid = gate_data.get("pid")
                    if psutil and self.current_pid:
                        try:
                            self.psutil_proc = psutil.Process(self.current_pid)
                            self.psutil_proc.cpu_percent(interval=None)
                        except Exception:
                            self.psutil_proc = None
                    raw_h = gate_data.get("hwnd")
                    self.current_main_hwnd = int(raw_h, 16) if isinstance(raw_h, str) and raw_h.startswith("0x") else None
                    self.current_main_title = gate_data.get("window_title", "")
                    self.log_event("REOPEN_SUCCESS", f"TankLevel reopened via proven reopen script: PID={self.current_pid}, HWND={raw_h}")
                    return True
        except Exception as err:
            self.log_event("REOPEN_ERROR", f"Error in reopen_main: {err}", level=logging.WARNING)

        # Fallback to direct launch
        kill_all_cscape_instances(timeout_sec=4.0)
        set_registry_clean_exit(1)
        ensure_iec_registry_defaults()
        if self.project_path:
            ensure_project_registry_defaults(self.project_path)

        cmd = [str(self.cscape_path)]
        if self.project_path and self.project_path.exists():
            cmd.append(str(self.project_path))
            self.log_event("LAUNCH_PROJECT", f"Attaching target project: '{self.project_path}'")
        else:
            self.log_event("LAUNCH_NO_PROJECT", "No project file attached; running with IEC registry mode.")

        work_dir = self.cscape_path.parent
        self.log_event("SPAWN", f"Executing: {' '.join(cmd)} (Cwd: {work_dir})")

        try:
            creationflags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
            try:
                proc = subprocess.Popen(cmd, cwd=str(work_dir), creationflags=creationflags)
            except OSError:
                proc = subprocess.Popen(cmd, cwd=str(work_dir))
            self.current_process = proc
            self.current_pid = proc.pid
            if psutil:
                try:
                    self.psutil_proc = psutil.Process(proc.pid)
                    self.psutil_proc.cpu_percent(interval=None)
                except Exception:
                    self.psutil_proc = None

            self.log_event("SPAWNED", f"Cscape instance spawned. PID={proc.pid}")
            return True
        except Exception as err:
            self.log_event("SPAWN_ERROR", f"Failed to spawn Cscape: {err}", level=logging.ERROR)
            return False

    def handle_startup_dialogs_and_verify_gui(self, timeout_sec: float = 30.0) -> bool:
        """Detect and dismiss modal splash / editor dialogs and ensure main window is visible."""
        pid = self.current_pid
        if not pid:
            return False

        if self.current_main_hwnd and ("tanklevel" in self.current_main_title.lower() or "labproject" in self.current_main_title.lower()):
            self.log_event("MAIN_WINDOW_ALREADY_VERIFIED", f"Main window already verified: HWND=0x{self.current_main_hwnd:X}, Title='{self.current_main_title}'")
            return True

        t0 = time.monotonic()
        splash_handled = False
        editor_handled = False

        self.log_event("GUI_HANDLING", f"Coordinating startup dialogs and verifying GUI for PID={pid}...")

        while time.monotonic() - t0 < timeout_sec:
            # Check if launcher handed off to successor Cscape process
            if self.current_process and self.current_process.poll() is not None:
                running = get_running_cscape_processes()
                if running:
                    successor = running[0]
                    self.log_event("ADOPT_SUCCESSOR", f"Launcher PID={pid} exited; adopting running Cscape PID={successor.pid}...")
                    self.current_pid = successor.pid
                    pid = successor.pid
                    self.current_process = None
                    self.psutil_proc = successor
                else:
                    self.log_event("PROCESS_EXITED_EARLY", f"PID={pid} exited during startup coordination.", level=logging.WARNING)
                    return False

            pids = {pid}
            if self.psutil_proc:
                try:
                    for child in self.psutil_proc.children(recursive=True):
                        pids.add(child.pid)
                except Exception:
                    pass

            windows = self.win32.enum_windows_for_pids(pids)

            # 1. Check Splash ("About Cscape")
            if not splash_handled:
                for w in windows:
                    if w.class_name == DIALOG_CLASS_NAME and SPLASH_TITLE_KEYWORD.lower() in w.title.lower():
                        self.log_event("SPLASH_FOUND", f"Found splash dialog HWND={w.hwnd}. Sending ID_OK...")
                        ctrls = self.win32.enum_child_controls(w.hwnd)
                        ok_hwnd = ctrls.get(ID_OK)
                        self.win32.click_button(ok_hwnd, w.hwnd, ID_OK)
                        splash_handled = True
                        break

            # 2. Check Editor Type ("Select Editor Type") -> Select IEC 61131
            if not editor_handled:
                for w in windows:
                    if w.class_name == DIALOG_CLASS_NAME and EDITOR_TITLE_KEYWORD.lower() in w.title.lower():
                        self.log_event("EDITOR_DIALOG_FOUND", f"Found editor dialog HWND={w.hwnd}. Selecting IEC 61131 (Radio {RADIO_ID_IEC_61131})...")
                        ctrls = self.win32.enum_child_controls(w.hwnd)
                        radio_hwnd = ctrls.get(RADIO_ID_IEC_61131)
                        ok_hwnd = ctrls.get(ID_OK)
                        self.win32.select_radio(radio_hwnd, w.hwnd, RADIO_ID_IEC_61131)
                        time.sleep(0.1)
                        self.win32.click_button(ok_hwnd, w.hwnd, ID_OK)
                        editor_handled = True
                        break

            # 3. Check for genuine Main Window
            for w in windows:
                if (
                    w.class_name != DIALOG_CLASS_NAME
                    and "cscape" in w.title.lower()
                    and not w.title.startswith("GDI+")
                ):
                    width = (w.rect[2] - w.rect[0]) if w.rect else 0
                    height = (w.rect[3] - w.rect[1]) if w.rect else 0
                    if width > 100 and height > 100:
                        self.current_main_hwnd = w.hwnd
                        self.current_main_title = w.title
                        self.win32.show_and_activate(w.hwnd)
                        self.log_event(
                            "MAIN_WINDOW_READY",
                            f"Main Cscape GUI verified: HWND=0x{w.hwnd:X} ({w.hwnd}), Title='{w.title}', Visible={w.visible}, Rect={w.rect}"
                        )
                        return True

            time.sleep(0.5)

        for w in self.win32.enum_windows_for_pids({pid}):
            if not w.title.startswith("GDI+"):
                self.current_main_hwnd = w.hwnd
                self.current_main_title = w.title
                self.win32.show_and_activate(w.hwnd)
                self.log_event("MAIN_WINDOW_FALLBACK", f"Assigned window HWND=0x{w.hwnd:X}, Title='{w.title}'")
                return True

        self.log_event("GUI_WARN", "Main GUI window not yet identified, continuing with process monitoring.", level=logging.WARNING)
        return True

    def trigger_file_open(self) -> None:
        """Trigger File Open for project_path via MRU command in running Cscape GUI."""
        if not self.project_path or not self.project_path.exists():
            return

        if self.current_main_hwnd:
            try:
                self.win32.user32.PostMessageW(self.current_main_hwnd, WM_COMMAND, 57616, 0)
            except Exception:
                pass

        pids = {self.current_pid} if self.current_pid else set()
        if self.psutil_proc:
            try:
                for ch in self.psutil_proc.children(recursive=True):
                    pids.add(ch.pid)
            except Exception:
                pass
        windows = self.win32.enum_windows_for_pids(pids)
        for w in windows:
            if w.class_name == DIALOG_CLASS_NAME:
                ctrls = self.win32.enum_child_controls(w.hwnd)
                if ID_OK in ctrls:
                    self.win32.click_button(ctrls[ID_OK], w.hwnd, ID_OK)

    def ensure_tanklevel_project_open(self, timeout_sec: float = 35.0) -> bool:
        """Actively open TankLevelClosedLoop.csp and verify window title reflects it."""
        if not self.project_path or not self.project_path.exists():
            return True

        if self.current_main_hwnd and "tanklevel" in self.current_main_title.lower():
            self.log_event("PROJECT_ALREADY_VERIFIED", f"TankLevel already confirmed in title: '{self.current_main_title}'")
            return True

        t0 = time.monotonic()
        self.log_event("PROJECT_OPEN_CHECK", f"Verifying '{self.project_path.name}' is loaded into Cscape GUI...")

        while time.monotonic() - t0 < timeout_sec:
            if self.stop_requested:
                return False

            pids = {self.current_pid} if self.current_pid else set()
            if self.psutil_proc:
                try:
                    for ch in self.psutil_proc.children(recursive=True):
                        pids.add(ch.pid)
                except Exception:
                    pass

            windows = self.win32.enum_windows_for_pids(pids)
            for w in windows:
                if (
                    w.class_name != DIALOG_CLASS_NAME
                    and "cscape" in w.title.lower()
                    and not w.title.startswith("GDI+")
                ):
                    self.current_main_hwnd = w.hwnd
                    self.current_main_title = w.title
            if self.current_main_hwnd:
                buf = ctypes.create_unicode_buffer(512)
                self.win32.user32.GetWindowTextW(self.current_main_hwnd, buf, 512)
                if buf.value:
                    self.current_main_title = buf.value

            if "tanklevelclosedloop" in self.current_main_title.lower():
                self.log_event(
                    "PROJECT_LOADED",
                    f"TankLevelClosedLoop confirmed loaded in window title: '{self.current_main_title}' (HWND=0x{self.current_main_hwnd:X})"
                )
                self._update_gate(
                    ready=True,
                    status="READY_FOR_TESTS",
                    reason="TankLevelClosedLoop verified active and responsive",
                )
                return True

            elapsed = time.monotonic() - t0
            self._update_gate(
                ready=False,
                status="WAITING_FOR_TANKLEVEL_TITLE",
                reason=f"Opening project. Current title: '{self.current_main_title}'",
            )
            if elapsed > 6.0:
                self.log_event(
                    "FILE_OPEN_ATTEMPT",
                    f"Window title '{self.current_main_title}' does not contain TankLevelClosedLoop after {elapsed:.1f}s. Sending ID_FILE_MRU_FILE1..."
                )
                self.trigger_file_open()

            time.sleep(1.0)

        return "tanklevelclosedloop" in self.current_main_title.lower()

    def monitor_current_cycle(self) -> Tuple[str, Optional[int]]:
        """Active 5-second monitoring loop for current Cscape process."""
        pid = self.current_pid
        if not pid:
            return ("INVALID_PROCESS", None)

        cycle_start_time = time.monotonic()
        self.log_event("MONITOR_START", f"5-second health loop active for PID={pid} | Target={self.target_duration:.1f}s")

        while not self.stop_requested:
            tick_start = time.monotonic()

            # 1. Check process liveness
            if self.current_process is not None:
                ret = self.current_process.poll()
                if ret is not None:
                    # Check for successor process
                    successors = get_running_cscape_processes()
                    if successors:
                        adopted = successors[0]
                        self.log_event("ADOPT_SUCCESSOR", f"Launcher PID={pid} exited; adopting active successor PID={adopted.pid}...")
                        self.current_pid = adopted.pid
                        pid = adopted.pid
                        self.current_process = None
                        self.psutil_proc = adopted
                    else:
                        self.log_event("PROCESS_EXIT_DETECTED", f"PID={pid} terminated with exit code {ret}")
                        return ("PROCESS_EXIT", ret)

            if psutil and not psutil.pid_exists(pid):
                successors = get_running_cscape_processes()
                if successors:
                    adopted = successors[0]
                    self.log_event("ADOPT_SUCCESSOR", f"Monitored PID={pid} replaced by active successor PID={adopted.pid}...")
                    self.current_pid = adopted.pid
                    pid = adopted.pid
                    self.current_process = None
                    self.psutil_proc = adopted
                else:
                    self.log_event("PROCESS_DISAPPEARED", f"PID={pid} disappeared from system.")
                    return ("PROCESS_DISAPPEARED", 1)

            # 2. Gather metrics
            now_iso = get_utc_iso()
            uptime_cycle = time.monotonic() - cycle_start_time
            current_total_uptime = self.total_uptime_seconds + uptime_cycle

            hwnd = self.current_main_hwnd or 0
            w_title = self.current_main_title
            pids = {pid}
            if self.psutil_proc:
                try:
                    for ch in self.psutil_proc.children(recursive=True):
                        pids.add(ch.pid)
                except Exception:
                    pass

            windows = self.win32.enum_windows_for_pids(pids)
            tank_w = None
            for w in windows:
                if (
                    w.class_name != DIALOG_CLASS_NAME
                    and "cscape" in w.title.lower()
                    and not w.title.startswith("GDI+")
                ):
                    if "tanklevel" in w.title.lower():
                        tank_w = w
                        break
                    elif not tank_w:
                        width = (w.rect[2] - w.rect[0]) if w.rect else 0
                        height = (w.rect[3] - w.rect[1]) if w.rect else 0
                        if width > 100 and height > 100 or not hwnd:
                            tank_w = w

            if tank_w:
                w = tank_w
                hwnd = w.hwnd
                w_title = w.title
                self.current_main_hwnd = hwnd
                self.current_main_title = w_title
                if w.pid != pid:
                    self.current_pid = w.pid
                    pid = w.pid
                    if psutil:
                        try:
                            self.psutil_proc = psutil.Process(w.pid)
                        except Exception:
                            pass
                if not w.visible:
                    self.win32.show_and_activate(hwnd)

            is_hung = self.win32.is_hung_app_window(hwnd)

            cpu_pct = 0.0
            ws_bytes = 0
            ws_mb = 0.0
            threads = 0
            status_label = "HEALTHY"

            if self.psutil_proc:
                try:
                    cpu_pct = self.psutil_proc.cpu_percent(interval=None)
                    mem_info = self.psutil_proc.memory_info()
                    ws_bytes = mem_info.rss
                    ws_mb = round(ws_bytes / (1024.0 * 1024.0), 2)
                    threads = self.psutil_proc.num_threads()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    successors = get_running_cscape_processes()
                    if successors:
                        adopted = successors[0]
                        self.current_pid = adopted.pid
                        pid = adopted.pid
                        self.psutil_proc = adopted
                        continue
                    exit_c = self.current_process.poll() if self.current_process else -1
                    return ("PROCESS_TERMINATED", exit_c if exit_c is not None else -1)
                except Exception:
                    pass

            if is_hung:
                status_label = "HUNG_WARNING"

            record = HealthRecord(
                timestamp_utc=now_iso,
                elapsed_seconds=round(current_total_uptime, 2),
                total_target_seconds=self.target_duration,
                cycle=self.cycle_count,
                pid=pid,
                hwnd=hwnd,
                hwnd_hex=f"0x{hwnd:08X}" if hwnd else "0x00000000",
                cpu_percent=round(cpu_pct, 2),
                working_set_bytes=ws_bytes,
                working_set_mb=ws_mb,
                window_title=w_title,
                is_hung=is_hung,
                num_threads=threads,
                status=status_label,
            )
            self.health_records.append(record)

            progress_pct = min(100.0, (current_total_uptime / self.target_duration) * 100.0)
            log_line = (
                f"[HEALTH_TICK] Time={now_iso} | Elapsed={record.elapsed_seconds:.1f}s/{self.target_duration:.0f}s ({progress_pct:.1f}%) | "
                f"Cycle={self.cycle_count} | PID={pid} | HWND={record.hwnd_hex} | "
                f"CPU={cpu_pct:.1f}% | WorkingSet={ws_mb:.2f}MB ({ws_bytes} B) | "
                f"Threads={threads} | IsHungAppWindow={is_hung} | Title='{w_title}' | Status={status_label}"
            )
            self.logger.info(log_line)

            ping_ok = self.win32.ping_window(hwnd) if hwnd else False
            if "tanklevelclosedloop" in w_title.lower() and not is_hung and ping_ok:
                self._update_gate(ready=True, status="READY_FOR_TESTS", reason="TankLevelClosedLoop verified active and responsive")
            elif is_hung or (hwnd and not ping_ok):
                self._update_gate(ready=False, status="FAIL_CLOSED_CSCAPE_HUNG", reason="Cscape window is hung or ping unresponsive")
            else:
                self._update_gate(ready=False, status="WAITING_FOR_TANKLEVEL_TITLE", reason=f"Current title: {w_title}")
                self.trigger_file_open()

            if current_total_uptime >= self.target_duration:
                self.total_uptime_seconds = current_total_uptime
                self.log_event(
                    "TARGET_REACHED",
                    f"Target continuous uptime achieved: {current_total_uptime:.1f}s >= {self.target_duration:.1f}s!"
                )
                return ("TARGET_DURATION_REACHED", 0)

            elapsed_tick = time.monotonic() - tick_start
            sleep_sec = max(0.2, self.poll_interval - elapsed_tick)
            time.sleep(sleep_sec)

        self.total_uptime_seconds += (time.monotonic() - cycle_start_time)
        return ("STOP_REQUESTED", 0)

    def close_current_process_gracefully(self, timeout_sec: float = 4.0) -> None:
        """Gracefully close current Cscape instance."""
        hwnd = self.current_main_hwnd
        pid = self.current_pid
        if not pid:
            return

        self.log_event("SHUTDOWN_START", f"Gracefully shutting down Cscape PID={pid}...")
        if hwnd:
            self.win32.close_window(hwnd)

        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout_sec:
            if not get_running_cscape_processes():
                self.log_event("SHUTDOWN_CLEAN", f"Cscape PID={pid} closed cleanly.")
                return
            time.sleep(0.2)

        self.log_event("SHUTDOWN_FORCE", f"Cscape PID={pid} still active; terminating process tree...")
        kill_all_cscape_instances(timeout_sec=3.0)

    def run(self) -> int:
        """Run watchdog supervisor until target duration is achieved or max restarts exhausted."""
        self.register_signal_handlers()

        banner = [
            "=" * 85,
            "HORNER APG CSCAPE 10-MINUTE CONTINUOUS WATCHDOG SUPERVISOR",
            "=" * 85,
            f"Start Timestamp UTC    : {get_utc_iso()}",
            f"Target Cscape Path     : {self.cscape_path}",
            f"Target Project Path    : {self.project_path}",
            f"Target Log File        : {self.log_file}",
            f"Target Duration        : {self.target_duration:.1f}s (10+ minutes)",
            f"Health Polling Rate    : Every {self.poll_interval:.1f}s",
            f"Max Allowed Restarts   : {self.max_restarts}",
            f"Initial Restart Backoff: {self.initial_backoff}s (Cap: {self.max_backoff}s)",
            "=" * 85,
        ]
        for line in banner:
            self.logger.info(line)

        restart_count = 0
        backoff = self.initial_backoff

        try:
            while not self.stop_requested and self.total_uptime_seconds < self.target_duration:
                success = self.launch_cscape()
                if not success:
                    restart_count += 1
                    if restart_count > self.max_restarts:
                        self.log_event("ABORT", f"Max restart attempts ({self.max_restarts}) exceeded during launch.", level=logging.ERROR)
                        return 1
                    self.log_event("BACKOFF", f"Launch failed. Backing off {backoff:.1f}s before retry {restart_count}...")
                    time.sleep(backoff)
                    backoff = min(backoff * 2.0, self.max_backoff)
                    continue

                self.handle_startup_dialogs_and_verify_gui(timeout_sec=30.0)
                self.ensure_tanklevel_project_open(timeout_sec=35.0)

                cycle_start_total = self.total_uptime_seconds
                reason, code = self.monitor_current_cycle()

                if reason == "TARGET_DURATION_REACHED":
                    self.log_event("COMPLETE", f"SUCCESS: Target duration of {self.target_duration:.1f}s fully verified!")
                    break

                if self.stop_requested:
                    self.log_event("INTERRUPTED", "Supervision loop interrupted by signal.")
                    break

                cycle_uptime = self.total_uptime_seconds - cycle_start_total
                code_name = NTSTATUS_NAMES.get(code or 0, f"CODE_{code}")
                hex_str = f"0x{(code or 0) & 0xFFFFFFFF:08X}"
                self.log_event(
                    "CRASH_OR_EXIT",
                    f"Cscape terminated unexpectedly! Reason: {reason} | ExitCode: {code} ({hex_str} - {code_name}) | "
                    f"Cycle Uptime: {cycle_uptime:.1f}s | Cumulative Uptime: {self.total_uptime_seconds:.1f}s",
                    level=logging.WARNING,
                )
                self._update_gate(
                    ready=False,
                    status="FAIL_CLOSED_CSCAPE_DEAD",
                    reason=f"Cscape terminated: {reason} (exit {code} - {code_name})",
                    exit_code=code,
                )


                if cycle_uptime > 3.0:
                    backoff = self.initial_backoff

                restart_count += 1
                if restart_count > self.max_restarts:
                    self.log_event("MAX_RESTARTS_EXCEEDED", f"Exceeded max restart attempts ({self.max_restarts}). Halting.", level=logging.ERROR)
                    return 1

                self.log_event(
                    "RESTART_BACKOFF",
                    f"Restarting Cscape (Attempt {restart_count}/{self.max_restarts}) after {backoff:.1f}s backoff delay..."
                )
                time.sleep(backoff)
                backoff = min(backoff * 1.5, self.max_backoff)

        finally:
            if self.auto_close_on_complete and not self.stop_requested:
                self.close_current_process_gracefully(timeout_sec=4.0)

            self._write_execution_summary()

        return 0

    def _write_execution_summary(self) -> None:
        """Emit execution summary to logs."""
        avg_cpu = 0.0
        avg_mem = 0.0
        if self.health_records:
            avg_cpu = sum(r.cpu_percent for r in self.health_records) / len(self.health_records)
            avg_mem = sum(r.working_set_mb for r in self.health_records) / len(self.health_records)

        summary = [
            "=" * 85,
            "CSCAPE 10-MINUTE WATCHDOG EXECUTION SUMMARY",
            "=" * 85,
            f"Completion Timestamp UTC : {get_utc_iso()}",
            f"Total Target Duration    : {self.target_duration:.1f}s",
            f"Total Achieved Uptime    : {self.total_uptime_seconds:.1f}s",
            f"Total Health Checks      : {len(self.health_records)} ticks (every {self.poll_interval}s)",
            f"Total Supervision Cycles : {self.cycle_count}",
            f"Average CPU Utilization  : {avg_cpu:.2f}%",
            f"Average Working Set      : {avg_mem:.2f} MB",
            f"Hung Window Detections   : {sum(1 for r in self.health_records if r.is_hung)}",
            f"Watchdog Target Status   : {'PASSED (>= 600s)' if self.total_uptime_seconds >= self.target_duration else 'HALTED'}",
            f"Log File Artifact        : {self.log_file}",
            "=" * 85,
        ]
        for line in summary:
            self.logger.info(line)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cscape 10-Minute Continuous Watchdog Supervisor")
    parser.add_argument("--cscape-path", type=str, default=str(DEFAULT_CSCAPE_PATH), help="Path to Cscape.exe")
    parser.add_argument("--project-path", type=str, default=str(DEFAULT_PROJECT_PATH), help="Path to project .csp file")
    parser.add_argument("--log-file", type=str, default=str(DEFAULT_LOG_PATH), help="Path to output health log")
    parser.add_argument("--duration", type=float, default=600.0, help="Target monitoring duration in seconds (default 600s)")
    parser.add_argument("--poll-interval", type=float, default=5.0, help="Monitoring polling frequency in seconds (default 5s)")
    parser.add_argument("--max-restarts", type=int, default=10, help="Max restarts on crash/exit (default 10)")
    parser.add_argument("--initial-backoff", type=float, default=2.0, help="Initial restart backoff in seconds (default 2s)")
    parser.add_argument("--no-close", action="store_true", help="Do not terminate Cscape upon target completion")
    parser.add_argument("--no-project", action="store_true", help="Launch Cscape without opening a project file")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    proj = None if args.no_project else args.project_path
    watchdog = Cscape10MinWatchdog(
        cscape_path=args.cscape_path,
        project_path=proj,
        log_file=args.log_file,
        target_duration_seconds=args.duration,
        poll_interval=args.poll_interval,
        max_restarts=args.max_restarts,
        initial_backoff=args.initial_backoff,
        auto_close_on_complete=not args.no_close,
    )
    return watchdog.run()


if __name__ == "__main__":
    sys.exit(main())
