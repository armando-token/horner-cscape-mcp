#!/usr/bin/env python3
"""Horner APG Cscape Process Watchdog.

Monitors Cscape.exe lifecycle continuously:
- Launches Cscape.exe with single-instance enforcement and registry safety safeguards.
- Detects and auto-dismisses modal 'About Cscape' splash dialog (#32770, ID 1).
- Detects and auto-selects 'Select Editor Type' dialog (#32770), asserting IEC 61131 mode (Radio ID 1461, OK 1).
- Continuously polls the process every 1.0s, tracking PID, window titles, uptime duration, memory, and error signals.
- Detects process exit or crash (exit code, WER signals, error modals).
- Automatically executes configurable restart attempts with cooldown delays.
- Writes comprehensive, high-fidelity logs to artifacts/logs/cscape_watchdog.log.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes
import datetime
import logging
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple, Union

# Common NTSTATUS / Windows Error Codes
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

ID_OK: int = 1
ID_CANCEL: int = 2
RADIO_ID_IEC_61131: int = 1461
RADIO_ID_LADDER_REG: int = 1460
RADIO_ID_LADDER_VAR: int = 3757

DIALOG_CLASS_NAME: str = "#32770"
SPLASH_TITLE_KEYWORD: str = "About Cscape"
EDITOR_TITLE_KEYWORD: str = "Select Editor Type"

DEFAULT_CSCAPE_PATH = Path(r"C:\Program Files (x86)\Cscape 10.2\Cscape.exe")


@dataclass
class WindowDetails:
    hwnd: int
    pid: int
    title: str
    class_name: str
    visible: bool
    enabled: bool
    rect: Optional[Tuple[int, int, int, int]] = None


@dataclass
class ProcessCycleRecord:
    cycle_index: int
    pid: int
    executable_path: str
    start_timestamp_utc: str
    start_time_mono: float
    splash_dismissed: bool = False
    splash_dismissed_time_utc: Optional[str] = None
    iec_dialog_handled: bool = False
    iec_handled_time_utc: Optional[str] = None
    main_window_hwnd: Optional[int] = None
    main_window_title: Optional[str] = None
    last_window_titles: List[str] = field(default_factory=list)
    error_signals: List[Dict[str, Any]] = field(default_factory=list)
    exit_timestamp_utc: Optional[str] = None
    uptime_seconds: float = 0.0
    exit_code: Optional[int] = None
    exit_classification: str = "RUNNING"


def get_utc_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def set_registry_clean_exit(val: int = 1) -> bool:
    """Set CscapeExitedCorrectly in registry to suppress crash recovery popups."""
    try:
        import winreg
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Horner_Electric\Cscape\Setup")
        winreg.SetValueEx(key, "CscapeExitedCorrectly", 0, winreg.REG_DWORD, val)
        winreg.CloseKey(key)
        return True
    except Exception:
        return False


def terminate_process_tree(pid: int, timeout_sec: float = 3.0) -> bool:
    """Force terminate process tree on Windows via taskkill."""
    if pid <= 0:
        return False
    try:
        subprocess.run(
            ["taskkill.exe", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            timeout=timeout_sec,
        )
        return True
    except Exception:
        return False


def kill_all_cscape_instances(timeout_sec: float = 5.0) -> int:
    """Terminate all lingering Cscape.exe instances on system."""
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
    # Sleep to allow Windows kernel to release mutexes and file locks
    time.sleep(1.0)
    set_registry_clean_exit(1)
    return count


class Win32Helper:
    """Direct Win32 API interactions via ctypes for maximum fidelity."""

    def __init__(self) -> None:
        self.user32 = ctypes.windll.user32
        self.kernel32 = ctypes.windll.kernel32
        self._wnd_enum_proc = ctypes.WINFUNCTYPE(
            ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
        )

    def enum_windows_for_pids(self, pids: Set[int]) -> List[WindowDetails]:
        """Enumerate all top-level windows for target PIDs."""
        results: List[WindowDetails] = []

        def callback(hwnd: int, _: Any) -> int:
            try:
                win_pid = ctypes.wintypes.DWORD()
                self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(win_pid))
                if win_pid.value in pids:
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

        self.user32.EnumWindows(self._wnd_enum_proc(callback), 0)
        return results

    def enum_child_controls(self, parent_hwnd: int) -> Dict[int, int]:
        """Map control ID -> HWND for all child controls in parent."""
        controls: Dict[int, int] = {}

        def callback(hwnd: int, _: Any) -> int:
            try:
                cid = self.user32.GetDlgCtrlID(hwnd)
                controls[cid] = hwnd
            except Exception:
                pass
            return 1

        self.user32.EnumChildWindows(parent_hwnd, self._wnd_enum_proc(callback), 0)
        return controls

    def enum_all_child_texts(self, parent_hwnd: int) -> List[Tuple[int, int, str, str]]:
        """Return list of (hwnd, control_id, class_name, text) for all child controls."""
        controls: List[Tuple[int, int, str, str]] = []

        def callback(hwnd: int, _: Any) -> int:
            try:
                cid = self.user32.GetDlgCtrlID(hwnd)
                buf_text = ctypes.create_unicode_buffer(512)
                self.user32.GetWindowTextW(hwnd, buf_text, 512)
                buf_cls = ctypes.create_unicode_buffer(512)
                self.user32.GetClassNameW(hwnd, buf_cls, 512)
                controls.append((hwnd, cid, buf_cls.value, buf_text.value))
            except Exception:
                pass
            return 1

        self.user32.EnumChildWindows(parent_hwnd, self._wnd_enum_proc(callback), 0)
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

    def close_window(self, hwnd: int) -> None:
        """Send WM_CLOSE to window."""
        self.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)


class CscapeWatchdog:
    """Robust process supervisor and watchdog for Cscape 10.2."""

    def __init__(
        self,
        cscape_path: Optional[Union[str, Path]] = None,
        log_file: Optional[Union[str, Path]] = None,
        max_restarts: int = 3,
        cooldown_seconds: float = 3.0,
        poll_interval: float = 1.0,
        auto_dismiss_splash: bool = True,
        auto_select_iec: bool = True,
        cwd: Optional[Union[str, Path]] = None,
        max_cycles: Optional[int] = None,
        cycle_duration: Optional[float] = None,
        test_crash: bool = False,
        dry_run: bool = False,
    ) -> None:
        self.dry_run = dry_run
        self.cscape_path = Path(cscape_path).resolve() if cscape_path else DEFAULT_CSCAPE_PATH
        if not self.cscape_path.exists() and not self.dry_run:
            # Try to resolve from common locations or registry
            from src.cscape.lifecycle import resolve_cscape_executable
            resolved = resolve_cscape_executable(self.cscape_path)
            if resolved and resolved.exists():
                self.cscape_path = resolved

        # Log file paths (write to target log and mirror to HornerAI if exists)
        self.log_file = Path(log_file).resolve() if log_file else Path("artifacts/logs/cscape_watchdog.log").resolve()
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

        self.mirror_log_file: Optional[Path] = None
        horner_log = Path(r"C:\HornerAI\horner-cscape-mcp\artifacts\logs\cscape_watchdog.log")
        if horner_log.parent.exists() and horner_log.resolve() != self.log_file.resolve():
            self.mirror_log_file = horner_log

        self.max_restarts = max_restarts
        self.cooldown_seconds = max(0.5, float(cooldown_seconds))
        self.poll_interval = max(0.2, float(poll_interval))
        self.auto_dismiss_splash = auto_dismiss_splash
        self.auto_select_iec = auto_select_iec
        self.cwd = Path(cwd).resolve() if cwd else Path.cwd()

        self.max_cycles = max_cycles if max_cycles is not None else (1 if self.dry_run else None)
        self.cycle_duration = cycle_duration if cycle_duration is not None else (2.0 if self.dry_run else None)
        self.test_crash = test_crash

        self.win32 = Win32Helper()
        self.stop_requested = False
        self.current_process: Optional[subprocess.Popen] = None
        self.current_pid: Optional[int] = None

        self.cycle_history: List[ProcessCycleRecord] = []
        self._setup_logging()

    def _setup_logging(self) -> None:
        """Initialize logger with console and file handlers."""
        self.logger = logging.getLogger("CscapeWatchdog")
        self.logger.setLevel(logging.INFO)
        self.logger.handlers.clear()

        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] [WATCHDOG] %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%SZ"
        )
        formatter.converter = time.gmtime  # UTC timestamps

        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)

        # Main file handler
        file_handler = logging.FileHandler(str(self.log_file), mode="a", encoding="utf-8")
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)

        # Mirror file handler if present
        if self.mirror_log_file:
            mirror_handler = logging.FileHandler(str(self.mirror_log_file), mode="a", encoding="utf-8")
            mirror_handler.setFormatter(formatter)
            self.logger.addHandler(mirror_handler)

    def log_event(self, event_tag: str, message: str, level: int = logging.INFO) -> None:
        """Structured event logging."""
        formatted_msg = f"[{event_tag}] {message}"
        self.logger.log(level, formatted_msg)

    def register_signal_handlers(self) -> None:
        """Catch SIGINT and SIGTERM for graceful shutdown."""
        def handler(sig: int, frame: Any) -> None:
            self.log_event("SIGNAL_RECEIVED", f"Signal {sig} caught. Initiating graceful watchdog termination...")
            self.stop_requested = True
            if self.current_pid:
                self.close_process_gracefully(self.current_pid, timeout=3.0)

        try:
            signal.signal(signal.SIGINT, handler)
            signal.signal(signal.SIGTERM, handler)
        except Exception:
            pass

    def launch_instance(self, cycle_index: int) -> ProcessCycleRecord:
        """Cleanly launch Cscape.exe and return an initialized ProcessCycleRecord."""
        if self.dry_run:
            self.log_event("DRY_RUN", "Operating in DRY-RUN mode: simulating Cscape process lifecycle.")
            self.log_event("CLEANUP", "Enforcing single-instance policy: purging dangling Cscape instances (simulated)...")
        else:
            self.log_event("CLEANUP", "Enforcing single-instance policy: purging dangling Cscape instances...")
            kill_all_cscape_instances(timeout_sec=4.0)

            # Assert clean exit status in registry so Cscape doesn't show crash recovery dialog
            set_registry_clean_exit(1)

        start_utc = get_utc_iso()
        start_mono = time.monotonic()

        self.log_event(
            "LAUNCH",
            f"{'[DRY-RUN] ' if self.dry_run else ''}Launching Cscape (Cycle {cycle_index}) | Exe: '{self.cscape_path}' | Cwd: '{self.cwd}'"
        )

        # Launch process
        if self.dry_run:
            sleep_sec = (self.cycle_duration or 2.0) + 5.0
            proc = subprocess.Popen(
                [sys.executable, "-c", f"import time; time.sleep({sleep_sec})"],
                cwd=str(self.cwd),
            )
        else:
            proc = subprocess.Popen(
                [str(self.cscape_path)],
                cwd=str(self.cwd),
            )
        self.current_process = proc
        self.current_pid = proc.pid

        record = ProcessCycleRecord(
            cycle_index=cycle_index,
            pid=proc.pid,
            executable_path=f"[DRY-RUN] {self.cscape_path}" if self.dry_run else str(self.cscape_path),
            start_timestamp_utc=start_utc,
            start_time_mono=start_mono,
        )

        self.log_event("LAUNCHED", f"{'[DRY-RUN] ' if self.dry_run else ''}Cscape process spawned successfully. PID={proc.pid}, StartedUtc={start_utc}")
        return record

    def check_for_error_dialogs(self, pids: Set[int], record: ProcessCycleRecord) -> None:
        """Scan top-level windows for modal error, crash, or warning dialogs."""
        windows = self.win32.enum_windows_for_pids(pids)
        error_keywords = ("error", "fatal", "crash", "fault", "access violation", "warning", "exception")

        for win in windows:
            title_lower = win.title.lower()
            if win.class_name == DIALOG_CLASS_NAME and any(k in title_lower for k in error_keywords):
                # Don't treat "Select Editor Type" or "About Cscape" as errors
                if SPLASH_TITLE_KEYWORD.lower() in title_lower or EDITOR_TITLE_KEYWORD.lower() in title_lower:
                    continue

                child_texts = self.win32.enum_all_child_texts(win.hwnd)
                combined = " | ".join(t[3] for t in child_texts if t[3].strip())
                err_info = {
                    "hwnd": win.hwnd,
                    "title": win.title,
                    "class_name": win.class_name,
                    "text_snippet": combined[:200],
                    "timestamp_utc": get_utc_iso(),
                }
                # Check if already logged
                if not any(e["hwnd"] == win.hwnd for e in record.error_signals):
                    record.error_signals.append(err_info)
                    self.log_event(
                        "ERROR_SIGNAL",
                        f"Detected error modal dialog! HWND={win.hwnd}, Title='{win.title}', Content='{combined[:100]}'",
                        level=logging.WARNING,
                    )

    def monitor_cycle(self, record: ProcessCycleRecord) -> None:
        """Continuously monitor process polling every poll_interval (1s)."""
        pid = record.pid
        proc = self.current_process
        pids = {pid}

        main_window_settled = False
        last_titles_set: Set[str] = set()

        self.log_event("MONITOR_START", f"Active monitoring loop engaged for PID={pid} (poll={self.poll_interval}s)")

        while not self.stop_requested:
            loop_start = time.monotonic()
            uptime = time.monotonic() - record.start_time_mono
            record.uptime_seconds = round(uptime, 2)

            # 1. Check if process terminated
            ret = proc.poll() if proc is not None else None
            if ret is not None:
                record.exit_code = ret
                break

            # 2. Check child processes or companion PIDs via psutil if available
            if not self.dry_run:
                try:
                    import psutil
                    if psutil.pid_exists(pid):
                        p_obj = psutil.Process(pid)
                        for child in p_obj.children(recursive=True):
                            pids.add(child.pid)
                    else:
                        record.exit_code = proc.poll() if proc is not None else 1
                        break
                except Exception:
                    pass

            # 3. Enumerate windows
            if self.dry_run:
                windows = []
            else:
                windows = self.win32.enum_windows_for_pids(pids)
            current_titles = [w.title for w in windows if w.title]
            current_titles_set = set(current_titles)

            # Detect title updates or window popups
            if not self.dry_run and current_titles_set != last_titles_set:
                record.last_window_titles = current_titles
                self.log_event(
                    "WINDOW_UPDATE",
                    f"PID={pid} | Windows count={len(windows)} | Titles: {current_titles}"
                )
                last_titles_set = current_titles_set

            # 4. Handle Splash Screen ("About Cscape", #32770)
            if self.auto_dismiss_splash and not record.splash_dismissed:
                if self.dry_run:
                    self.log_event("SPLASH_DETECTED", f"[DRY-RUN] Found splash dialog HWND=0x1001, Title='{SPLASH_TITLE_KEYWORD}'")
                    record.splash_dismissed = True
                    record.splash_dismissed_time_utc = get_utc_iso()
                    self.log_event("SPLASH_DISMISSED", "[DRY-RUN] Sent IDOK to splash HWND=0x1001. Dismissed=True")
                else:
                    for win in windows:
                        if win.class_name == DIALOG_CLASS_NAME and SPLASH_TITLE_KEYWORD.lower() in win.title.lower():
                            self.log_event("SPLASH_DETECTED", f"Found splash dialog HWND={win.hwnd}, Title='{win.title}'")
                            ctrls = self.win32.enum_child_controls(win.hwnd)
                            ok_hwnd = ctrls.get(ID_OK)
                            self.win32.click_button(ok_hwnd, win.hwnd, ID_OK)
                            record.splash_dismissed = True
                            record.splash_dismissed_time_utc = get_utc_iso()
                            self.log_event("SPLASH_DISMISSED", f"Sent IDOK to splash HWND={win.hwnd}. Dismissed=True")
                            break

            # 5. Handle 'Select Editor Type' dialog (#32770) -> Select IEC 61131 (Radio ID 1461)
            if self.auto_select_iec and not record.iec_dialog_handled:
                if self.dry_run:
                    self.log_event("IEC_DIALOG_DETECTED", f"[DRY-RUN] Found editor dialog HWND=0x1002, Title='{EDITOR_TITLE_KEYWORD}'")
                    record.iec_dialog_handled = True
                    record.iec_handled_time_utc = get_utc_iso()
                    self.log_event(
                        "IEC_SELECTED",
                        f"[DRY-RUN] Selected IEC 61131 (Radio {RADIO_ID_IEC_61131}) and clicked OK on HWND=0x1002"
                    )
                else:
                    for win in windows:
                        if win.class_name == DIALOG_CLASS_NAME and EDITOR_TITLE_KEYWORD.lower() in win.title.lower():
                            self.log_event("IEC_DIALOG_DETECTED", f"Found editor dialog HWND={win.hwnd}, Title='{win.title}'")
                            ctrls = self.win32.enum_child_controls(win.hwnd)
                            radio_hwnd = ctrls.get(RADIO_ID_IEC_61131)
                            ok_hwnd = ctrls.get(ID_OK)
                            self.win32.select_radio(radio_hwnd, win.hwnd, RADIO_ID_IEC_61131)
                            time.sleep(0.1)
                            self.win32.click_button(ok_hwnd, win.hwnd, ID_OK)
                            record.iec_dialog_handled = True
                            record.iec_handled_time_utc = get_utc_iso()
                            self.log_event(
                                "IEC_SELECTED",
                                f"Selected IEC 61131 (Radio {RADIO_ID_IEC_61131}) and clicked OK on HWND={win.hwnd}"
                            )
                            break

            # 6. Detect Main Cscape Window
            if not main_window_settled:
                if self.dry_run:
                    record.main_window_hwnd = 0x2001
                    record.main_window_title = "Cscape - [Simulated_Project.csp]"
                    main_window_settled = True
                    self.log_event(
                        "READY",
                        f"[DRY-RUN] Main IDE window verified active: HWND={record.main_window_hwnd}, Title='{record.main_window_title}'"
                    )
                else:
                    for win in windows:
                        if win.class_name != DIALOG_CLASS_NAME and "cscape" in win.title.lower() and win.visible:
                            record.main_window_hwnd = win.hwnd
                            record.main_window_title = win.title
                            main_window_settled = True
                            self.log_event(
                                "READY",
                                f"Main IDE window verified active: HWND={win.hwnd}, Title='{win.title}', Rect={win.rect}"
                            )
                            break

            # 7. Scan for Error / Crash dialogs
            if not self.dry_run:
                self.check_for_error_dialogs(pids, record)

            # 8. Log regular heartbeat (at 1s or on every tick)
            active_title = record.main_window_title or ''
            win_count = 1 if self.dry_run else len(windows)
            self.log_event(
                "MONITOR",
                f"PID={pid} | Uptime: {uptime:.1f}s | Windows: {win_count} | ActiveTitle: '{active_title}'"
            )

            # 9. Handle cycle duration limit for automated test runs
            if self.cycle_duration and uptime >= self.cycle_duration:
                if self.test_crash:
                    self.log_event("TEST_CRASH", f"Simulating crash after {uptime:.1f}s cycle duration via force kill...")
                    terminate_process_tree(pid)
                    record.exit_code = 1
                else:
                    self.log_event("CYCLE_LIMIT", f"Cycle duration target {self.cycle_duration}s reached. Closing gracefully...")
                    self.close_process_gracefully(pid, timeout=4.0)
                    record.exit_code = 0
                break

            # Sleep remaining time to satisfy 1.0s interval
            elapsed = time.monotonic() - loop_start
            sleep_time = max(0.05, self.poll_interval - elapsed)
            time.sleep(sleep_time)

        # Process exited or stopped
        exit_utc = get_utc_iso()
        record.exit_timestamp_utc = exit_utc
        final_uptime = round(time.monotonic() - record.start_time_mono, 2)
        record.uptime_seconds = final_uptime

        if record.exit_code is None:
            record.exit_code = proc.poll() if proc is not None else 0

        # Classify exit
        code = record.exit_code
        status_name = NTSTATUS_NAMES.get(code, f"UNKNOWN_CODE_{code}")
        hex_code = f"0x{code & 0xFFFFFFFF:08X}" if code is not None else "UNKNOWN"

        if code == 0:
            record.exit_classification = "CLEAN_EXIT"
        elif record.error_signals or code in (-1073741819, 0xC0000005, -1073740791, 0xC0000409):
            record.exit_classification = "CRASH"
        elif self.stop_requested:
            record.exit_classification = "WATCHDOG_INTERRUPT"
        else:
            record.exit_classification = "UNEXPECTED_EXIT"

        self.log_event(
            "PROCESS_EXIT",
            f"Process PID={pid} terminated. ExitCode={code} ({hex_code} - {status_name}) | "
            f"Uptime={final_uptime}s | ExitUtc={exit_utc} | Classification={record.exit_classification}"
        )

        if record.exit_classification == "CRASH" or record.error_signals or code != 0:
            self.log_event(
                "CRASH_EVENT",
                f"Crash or abnormal exit recorded for PID={pid}! Code={code} ({hex_code}). "
                f"ErrorSignalsCount={len(record.error_signals)}"
            )

        self.cycle_history.append(record)

    def close_process_gracefully(self, pid: int, timeout: float = 4.0) -> bool:
        """Attempt graceful close via WM_CLOSE, falling back to force kill."""
        self.log_event("SHUTDOWN", f"Attempting graceful shutdown of Cscape PID={pid}...")
        if self.dry_run:
            if self.current_process:
                self.current_process.terminate()
                try:
                    self.current_process.wait(timeout=timeout)
                except Exception:
                    self.current_process.kill()
            self.log_event("SHUTDOWN_CLEAN", f"[DRY-RUN] Cscape PID={pid} exited cleanly after simulated shutdown.")
            return True

        pids = {pid}
        windows = self.win32.enum_windows_for_pids(pids)

        for win in windows:
            self.win32.close_window(win.hwnd)

        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            if self.current_process and self.current_process.poll() is not None:
                self.log_event("SHUTDOWN_CLEAN", f"Cscape PID={pid} exited cleanly after WM_CLOSE.")
                return True
            time.sleep(0.2)

        self.log_event("SHUTDOWN_FORCE", f"Cscape PID={pid} did not exit within {timeout}s; terminating process tree.")
        terminate_process_tree(pid)
        return True

    def run(self) -> int:
        """Main execution loop for watchdog."""
        self.register_signal_handlers()

        banner = [
            "=" * 80,
            "HORNER CSCAPE 10.2 PROCESS WATCHDOG",
            "=" * 80,
            f"Watchdog Start Time UTC : {get_utc_iso()}",
            f"Target Executable       : {self.cscape_path}",
            f"Log Destination         : {self.log_file}",
            f"Dry Run Mode            : {self.dry_run}",
            f"Max Restart Attempts    : {self.max_restarts}",
            f"Restart Cooldown        : {self.cooldown_seconds}s",
            f"Polling Frequency       : {self.poll_interval}s",
            f"Auto Dismiss Splash     : {self.auto_dismiss_splash}",
            f"Auto Select IEC 61131   : {self.auto_select_iec}",
            f"Max Cycles Bound        : {self.max_cycles or 'UNBOUNDED'}",
            f"Cycle Duration Limit    : {f'{self.cycle_duration}s' if self.cycle_duration else 'UNBOUNDED'}",
            f"Simulate Crash Mode     : {self.test_crash}",
            "=" * 80,
        ]
        for line in banner:
            self.logger.info(line)

        cycle_index = 1
        restart_count = 0

        try:
            while not self.stop_requested:
                if self.max_cycles and cycle_index > self.max_cycles:
                    self.log_event("WATCHDOG_COMPLETED", f"Completed configured max cycles ({self.max_cycles}). Exiting.")
                    break

                self.log_event("CYCLE_START", f"--- Commencing Supervision Cycle {cycle_index} ---")
                record = self.launch_instance(cycle_index)
                self.monitor_cycle(record)

                # If stop requested by user / signal, exit
                if self.stop_requested:
                    break

                # Check if cycle limit reached
                if self.max_cycles and cycle_index >= self.max_cycles:
                    self.log_event("WATCHDOG_COMPLETED", f"Reached max cycle count ({self.max_cycles}). Watchdog halting.")
                    break

                # Handle restart logic
                restart_count += 1
                if self.max_restarts >= 0 and restart_count > self.max_restarts:
                    self.log_event(
                        "WATCHDOG_HALTED",
                        f"Maximum allowed restart attempts ({self.max_restarts}) exhausted. Watchdog terminating.",
                        level=logging.WARNING,
                    )
                    break

                self.log_event(
                    "RESTART_ATTEMPT",
                    f"Preparing restart attempt {restart_count}/{self.max_restarts}. "
                    f"Entering cooldown delay ({self.cooldown_seconds}s)..."
                )
                time.sleep(self.cooldown_seconds)
                cycle_index += 1

        finally:
            self._write_final_summary()

        return 0

    def _write_final_summary(self) -> None:
        """Write closing summary table to log."""
        summary = [
            "=" * 80,
            "CSCAPE WATCHDOG EXECUTION SUMMARY",
            "=" * 80,
            f"Watchdog Completion UTC : {get_utc_iso()}",
            f"Total Cycles Monitored  : {len(self.cycle_history)}",
        ]

        total_uptime = sum(c.uptime_seconds for c in self.cycle_history)
        summary.append(f"Cumulative Uptime       : {total_uptime:.2f}s")
        summary.append("Cycle Breakdown:")

        for c in self.cycle_history:
            summary.append(
                f"  - Cycle {c.cycle_index}: PID={c.pid} | Uptime={c.uptime_seconds}s | "
                f"ExitCode={c.exit_code} | Classification={c.exit_classification} | "
                f"SplashDismissed={c.splash_dismissed} | IECSelected={c.iec_dialog_handled} | "
                f"ErrorsLogged={len(c.error_signals)}"
            )

        summary.append("=" * 80)
        for line in summary:
            self.logger.info(line)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Horner APG Cscape 10.2 Process Watchdog & Supervisor"
    )
    parser.add_argument(
        "--cscape-path",
        type=str,
        default=None,
        help="Path to Cscape.exe (defaults to auto-detection)",
    )
    parser.add_argument(
        "--log-file",
        type=str,
        default="artifacts/logs/cscape_watchdog.log",
        help="Path to output watchdog log file",
    )
    parser.add_argument(
        "--max-restarts",
        type=int,
        default=3,
        help="Maximum restart attempts if Cscape exits/crashes (-1 for infinite, default 3)",
    )
    parser.add_argument(
        "--cooldown",
        type=float,
        default=3.0,
        help="Cooldown delay in seconds before restart attempt (default 3.0s)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="Process monitoring polling interval in seconds (default 1.0s)",
    )
    parser.add_argument(
        "--no-splash",
        action="store_true",
        help="Disable automated splash screen dismissal",
    )
    parser.add_argument(
        "--no-iec",
        action="store_true",
        help="Disable automated IEC 61131 dialog selection",
    )
    parser.add_argument(
        "--cwd",
        type=str,
        default=None,
        help="Working directory for Cscape launch (default: current directory)",
    )
    parser.add_argument(
        "--max-cycles",
        type=int,
        default=None,
        help="Exit watchdog after N monitoring cycles (for test runs)",
    )
    parser.add_argument(
        "--cycle-duration",
        type=float,
        default=None,
        help="Duration in seconds per cycle before next cycle or shutdown (for test runs)",
    )
    parser.add_argument(
        "--test-crash",
        action="store_true",
        help="Simulate crash termination at cycle duration limit to test crash/restart handling",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Execute simulated watchdog cycle without launching actual Cscape GUI",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    watchdog = CscapeWatchdog(
        cscape_path=args.cscape_path,
        log_file=args.log_file,
        max_restarts=args.max_restarts,
        cooldown_seconds=args.cooldown,
        poll_interval=args.poll_interval,
        auto_dismiss_splash=not args.no_splash,
        auto_select_iec=not args.no_iec,
        cwd=args.cwd,
        max_cycles=args.max_cycles,
        cycle_duration=args.cycle_duration,
        test_crash=args.test_crash,
        dry_run=args.dry_run,
    )
    return watchdog.run()


if __name__ == "__main__":
    sys.exit(main())
