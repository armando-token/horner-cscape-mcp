"""Horner APG Cscape 10.2 Lifecycle Manager.

Provides robust process lifecycle control for Cscape.exe:
- Process launching via subprocess or pywinauto
- Automated detection and dismissal of modal 'About Cscape' splash window (#32770)
- Automated detection of 'Select Editor Type' dialog (#32770), selection of
  'IEC 61131 Language Editors' (Radio ID 1461), and clicking OK (ID 1)
- Monitoring until main Cscape window is fully ready, visible, and interactive
- Graceful shutdown via WM_CLOSE / Alt+F4 with force termination fallback on timeout
"""

from __future__ import annotations

import asyncio
import contextlib
import enum
import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, Optional, Sequence, Tuple, Union

# Enforce STA COM mode before any COM, win32com, or pywinauto imports
if sys.platform == "win32" or os.name == "nt":
    if not hasattr(sys, "coinit_flags"):
        setattr(sys, "coinit_flags", 2)  # COINIT_APARTMENTTHREADED = 0x2 (STA)

logger = logging.getLogger(__name__)

# Standard candidate paths for Cscape.exe on Windows
DEFAULT_CSCAPE_PATHS: list[Path] = [
    Path(r"C:\Program Files (x86)\Cscape 10.2\Cscape.exe"),
    Path(r"C:\Program Files (x86)\Cscape 10.1\Cscape.exe"),
    Path(r"C:\Program Files (x86)\Cscape 10.0\Cscape.exe"),
    Path(r"C:\Program Files\Cscape 10.2\Cscape.exe"),
    Path(r"C:\Program Files\Cscape 10.1\Cscape.exe"),
]

# Win32 Window Classes and Dialog Identifiers
DIALOG_CLASS_NAME: str = "#32770"
SPLASH_TITLE_SUBSTRING: str = "About Cscape"
EDITOR_TYPE_TITLE_SUBSTRING: str = "Select Editor Type"
SAVE_AS_TITLE_SUBSTRING: str = "Save As"
SAVE_AS_CLASS_NAME: str = "#32770"
MAIN_WINDOW_TITLE_SUBSTRING: str = "Cscape"

# Standard Dialog Control IDs
ID_OK: int = 1
ID_CANCEL: int = 2
RADIO_ID_ADVANCED_LADDER_REGISTER: int = 1460
RADIO_ID_IEC_61131: int = 1461
RADIO_ID_ADVANCED_LADDER_VARIABLE: int = 3757
EDIT_ID_FILE_NAME: int = 1152
BUTTON_ID_SAVE: int = 1

# Win32 Message Constants
WM_SETTEXT: int = 0x000C
WM_GETTEXT: int = 0x000D
WM_GETTEXTLENGTH: int = 0x000E
WM_CLOSE: int = 0x0010
WM_COMMAND: int = 0x0111
WM_SYSCOMMAND: int = 0x0112
SC_CLOSE: int = 0xF060
BM_CLICK: int = 0x00F5
BM_SETCHECK: int = 0x00F1
BST_UNCHECKED: int = 0x0000
BST_CHECKED: int = 0x0001
BN_CLICKED: int = 0

# 'Allow' Security & Firewall Dialog Constants
ALLOW_TEXT_KEYWORDS: tuple[str, ...] = (
    "allow access",
    "allow this app",
    "windows security alert",
    "windows defender firewall",
    "windows security",
    "windows firewall",
    "security alert",
    "security prompt",
    "blocked some features",
    "has blocked some features",
)

ALLOW_BUTTON_KEYWORDS: tuple[str, ...] = (
    "allow",
    "allow access",
    "allow this app",
    "&allow",
    "&allow access",
    "&allow this app",
    "unblock",
    "&unblock",
    "always allow",
    "&always allow",
    "allow once",
    "&allow once",
)


class CscapeLifecycleState(str, enum.Enum):
    """Lifecycle states of the Cscape process."""
    NOT_STARTED = "not_started"
    STARTING = "starting"
    SPLASH_DISMISSED = "splash_dismissed"
    EDITOR_TYPE_SELECTED = "editor_type_selected"
    READY = "ready"
    CLOSING = "closing"
    TERMINATED = "terminated"
    FAILED = "failed"


class CscapeLifecycleError(Exception):
    """Base exception for Cscape lifecycle errors."""
    pass


class CscapeLaunchError(CscapeLifecycleError):
    """Raised when Cscape fails to launch or exits unexpectedly during startup."""
    pass


class CscapeStartupTimeoutError(CscapeLifecycleError):
    """Raised when waiting for Cscape windows or dialogs exceeds configured timeout."""
    pass


class CscapeShutdownError(CscapeLifecycleError):
    """Raised when Cscape shutdown encounters an unrecoverable failure."""
    pass


class CscapeLockError(CscapeLifecycleError):
    """Raised when single-instance lock acquisition fails or times out."""
    pass


# Single-Instance Lock and Mutex Constants
DEFAULT_MUTEX_NAME: str = "Local\\Horner_Cscape_SingleInstance_Mutex"
DEFAULT_LOCK_FILE: Path = Path(os.environ.get("CSCAPE_LOCK_FILE", str(Path(tempfile.gettempdir()) / "cscape_single_instance.lock")))


class CscapeSingleInstanceLock:
    """Manages single-instance synchronization across threads and processes.

    Uses a Win32 Named Mutex and an OS-level file lock to ensure that
    concurrent launches never collide or spawn duplicate Cscape instances.
    """

    def __init__(
        self,
        lock_file: Optional[Union[str, Path]] = None,
        mutex_name: str = DEFAULT_MUTEX_NAME,
        timeout: float = 30.0,
    ) -> None:
        self.lock_file: Path = Path(lock_file).resolve() if lock_file else DEFAULT_LOCK_FILE
        self.mutex_name: str = mutex_name
        self.timeout: float = float(timeout)
        self._thread_lock = threading.RLock()
        self._mutex_handle: Optional[Any] = None
        self._file_handle: Optional[Any] = None
        self._acquire_depth: int = 0
        self._acquired_at: Optional[float] = None
        self._cscape_pid: Optional[int] = None
        self._metadata: Optional[dict[str, Any]] = None

    def acquire(self, timeout: Optional[float] = None) -> bool:
        """Acquire the single-instance mutex and file lock.

        Args:
            timeout: Maximum seconds to wait. If None, uses self.timeout.

        Returns:
            True if lock was acquired.

        Raises:
            CscapeLockError: If lock cannot be acquired within the timeout.
        """
        wait_sec = float(timeout) if timeout is not None else self.timeout
        deadline = time.time() + wait_sec

        # 1. Acquire in-process re-entrant thread lock
        acquired_thread = self._thread_lock.acquire(timeout=wait_sec)
        if not acquired_thread:
            raise CscapeLockError(
                f"Timed out after {wait_sec}s waiting for internal thread lock on Cscape single-instance lock"
            )

        if self._acquire_depth > 0:
            self._acquire_depth += 1
            return True

        try:
            # 2. Acquire Win32 System-Wide Named Mutex
            if is_windows():
                remaining_sec = max(0.01, deadline - time.time())
                remaining_ms = max(1, int(remaining_sec * 1000))
                mutex_acquired = False

                # Primary: win32event
                try:
                    import win32event
                    import win32api
                    self._mutex_handle = win32event.CreateMutex(None, False, self.mutex_name)
                    res = win32event.WaitForSingleObject(self._mutex_handle, remaining_ms)
                    # WAIT_OBJECT_0 (0) or WAIT_ABANDONED (128)
                    if res in (
                        win32event.WAIT_OBJECT_0,
                        getattr(win32event, "WAIT_ABANDONED", 128),
                        getattr(win32event, "WAIT_ABANDONED_0", 128),
                    ):
                        mutex_acquired = True
                        if res != win32event.WAIT_OBJECT_0:
                            logger.warning(
                                "Win32 mutex '%s' was abandoned by a terminated process; acquired ownership safely.",
                                self.mutex_name,
                            )
                    else:
                        try:
                            win32api.CloseHandle(self._mutex_handle)
                        except Exception:
                            pass
                        self._mutex_handle = None
                except ImportError:
                    # Fallback: ctypes.windll.kernel32
                    try:
                        import ctypes
                        import ctypes.wintypes
                        k32 = ctypes.windll.kernel32
                        self._mutex_handle = k32.CreateMutexW(None, False, self.mutex_name)
                        res = k32.WaitForSingleObject(self._mutex_handle, ctypes.wintypes.DWORD(remaining_ms))
                        if res in (0, 0x80):
                            mutex_acquired = True
                            if res == 0x80:
                                logger.warning(
                                    "Win32 mutex '%s' was abandoned (ctypes); acquired ownership safely.",
                                    self.mutex_name,
                                )
                        else:
                            k32.CloseHandle(self._mutex_handle)
                            self._mutex_handle = None
                    except Exception as ct_err:
                        logger.debug("ctypes mutex error: %s", ct_err)
                except Exception as w32_err:
                    logger.debug("win32event mutex error: %s", w32_err)

                if not mutex_acquired:
                    raise CscapeLockError(
                        f"Timed out after {wait_sec}s acquiring Win32 mutex '{self.mutex_name}'"
                    )

            # 3. Acquire File Lock
            self.lock_file.parent.mkdir(parents=True, exist_ok=True)
            file_locked = False

            while time.time() < deadline:
                f = None
                try:
                    if self.is_stale():
                        logger.warning("Stale Cscape lock file detected at %s; cleaning up...", self.lock_file)
                        self.break_lock()

                    f = open(self.lock_file, "a+", encoding="utf-8")
                    if is_windows():
                        import msvcrt
                        f.seek(0)
                        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

                    self._file_handle = f
                    file_locked = True
                    break
                except (OSError, IOError, PermissionError):
                    if f is not None and not f.closed:
                        try:
                            f.close()
                        except Exception:
                            pass
                    time.sleep(0.1)

            if not file_locked:
                self._release_mutex()
                raise CscapeLockError(
                    f"Timed out after {wait_sec}s acquiring single-instance lock file '{self.lock_file}'"
                )

            # Write lock metadata
            metadata = {
                "pid": os.getpid(),
                "cscape_pid": self._cscape_pid,
                "acquired_at": time.time(),
                "mutex_name": self.mutex_name,
                "lock_file": str(self.lock_file),
            }
            try:
                self._file_handle.seek(0)
                self._file_handle.truncate(0)
                json.dump(metadata, self._file_handle)
                self._file_handle.flush()
            except Exception as write_err:
                logger.debug("Failed writing lock file metadata: %s", write_err)

            self._metadata = dict(metadata)
            self._acquire_depth = 1
            self._acquired_at = time.time()
            logger.debug("Single-instance lock acquired successfully (file=%s, mutex=%s)", self.lock_file, self.mutex_name)
            return True

        except Exception:
            self._thread_lock.release()
            raise

    def release(self) -> None:
        """Release the single-instance lock and mutex."""
        if self._acquire_depth == 0:
            return
        self._acquire_depth -= 1
        if self._acquire_depth > 0:
            self._thread_lock.release()
            return

        try:
            # Release file lock
            if self._file_handle is not None:
                try:
                    if is_windows():
                        import msvcrt
                        self._file_handle.seek(0)
                        msvcrt.locking(self._file_handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(self._file_handle.fileno(), fcntl.LOCK_UN)
                except Exception:
                    pass
                try:
                    self._file_handle.close()
                except Exception:
                    pass
                self._file_handle = None

            # Safely remove lock file
            try:
                if self.lock_file.exists():
                    self.lock_file.unlink(missing_ok=True)
            except Exception:
                pass

            # Release Win32 Named Mutex
            self._release_mutex()
            self._acquired_at = None
            self._metadata = None
            logger.debug("Single-instance lock released (file=%s, mutex=%s)", self.lock_file, self.mutex_name)
        finally:
            self._thread_lock.release()

    def _release_mutex(self) -> None:
        """Release and close the Win32 Named Mutex handle."""
        if is_windows() and self._mutex_handle is not None:
            try:
                import win32event
                import win32api
                win32event.ReleaseMutex(self._mutex_handle)
                win32api.CloseHandle(self._mutex_handle)
            except ImportError:
                import ctypes
                ctypes.windll.kernel32.ReleaseMutex(self._mutex_handle)
                ctypes.windll.kernel32.CloseHandle(self._mutex_handle)
            except Exception as e:
                logger.debug("Error releasing Win32 mutex: %s", e)
            finally:
                self._mutex_handle = None

    def update_cscape_pid(self, cscape_pid: int) -> None:
        """Update Cscape PID recorded in lock file."""
        self._cscape_pid = cscape_pid
        if self._metadata is not None:
            self._metadata["cscape_pid"] = cscape_pid
        if self._file_handle and not self._file_handle.closed:
            try:
                info = {
                    "pid": os.getpid(),
                    "cscape_pid": cscape_pid,
                    "acquired_at": self._acquired_at or time.time(),
                    "updated_at": time.time(),
                    "mutex_name": self.mutex_name,
                    "lock_file": str(self.lock_file),
                }
                self._file_handle.seek(0)
                self._file_handle.truncate(0)
                json.dump(info, self._file_handle)
                self._file_handle.flush()
            except Exception as e:
                logger.debug("Failed updating lock file with Cscape PID: %s", e)

    def get_lock_info(self) -> Optional[dict[str, Any]]:
        """Read and parse lock file metadata if present."""
        if self._metadata is not None:
            return dict(self._metadata)

        if self._file_handle is not None and not self._file_handle.closed:
            try:
                pos = self._file_handle.tell()
                self._file_handle.seek(0)
                content = self._file_handle.read().strip()
                self._file_handle.seek(pos)
                if content:
                    return json.loads(content)
            except Exception:
                pass

        if not self.lock_file.exists():
            return None
        try:
            with open(self.lock_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    return json.loads(content)
        except Exception:
            return None
        return None

    def is_stale(self) -> bool:
        """Check if existing lock file belongs to a dead process."""
        if self._acquire_depth > 0:
            return False
        if not self.lock_file.exists():
            return False
        info = self.get_lock_info()
        if info:
            owner_pid = info.get("pid")
            if owner_pid is not None:
                if owner_pid == os.getpid():
                    return False
                try:
                    import psutil
                    return not psutil.pid_exists(owner_pid)
                except Exception:
                    return False
        # If info could not be read or is empty, test if an active OS process holds file lock
        if is_windows():
            try:
                f = open(self.lock_file, "a+", encoding="utf-8")
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                # Succeeded: no active live process holds file lock
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                f.close()
                return True
            except (PermissionError, OSError):
                # An active process currently holds the lock
                return False
        return False

    def break_lock(self) -> bool:
        """Forcefully remove stale lock file."""
        try:
            if self.lock_file.exists():
                self.lock_file.unlink(missing_ok=True)
                return True
        except Exception as e:
            logger.debug("Failed to remove stale lock file %s: %s", self.lock_file, e)
        return False

    def is_locked(self) -> bool:
        """Return True if lock is currently held."""
        if self._acquire_depth > 0:
            return True
        if not self.lock_file.exists():
            return False
        if self.is_stale():
            return False
        return True

    @contextlib.contextmanager
    def acquire_context(self, timeout: Optional[float] = None) -> Generator[CscapeSingleInstanceLock, None, None]:
        """Context manager to acquire and automatically release the lock."""
        self.acquire(timeout=timeout)
        try:
            yield self
        finally:
            self.release()

    def __enter__(self) -> CscapeSingleInstanceLock:
        self.acquire()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.release()


def acquire_single_instance_lock(
    lock_file: Optional[Union[str, Path]] = None,
    mutex_name: str = DEFAULT_MUTEX_NAME,
    timeout: float = 30.0,
) -> CscapeSingleInstanceLock:
    """Helper to create and acquire a single-instance lock."""
    lock = CscapeSingleInstanceLock(lock_file=lock_file, mutex_name=mutex_name, timeout=timeout)
    lock.acquire()
    return lock


def is_windows() -> bool:
    """Return True if running on Windows."""
    return sys.platform == "win32" or os.name == "nt"


def set_cscape_exited_correctly(val: int = 1) -> bool:
    """Assert CscapeExitedCorrectly DWORD value in registry to prevent crash recovery modals.

    Args:
        val: 1 for clean exit status (suppresses popup), 0 for abnormal status.

    Returns:
        True if successfully set in registry, False otherwise.
    """
    if not is_windows():
        return False
    success = False
    try:
        import winreg
        # Standard view
        try:
            reg_key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Horner_Electric\Cscape\Setup")
            winreg.SetValueEx(reg_key, "CscapeExitedCorrectly", 0, winreg.REG_DWORD, int(val))
            winreg.CloseKey(reg_key)
            success = True
        except Exception as err:
            logger.debug("winreg standard view error: %s", err)

        # Explicitly update 32-bit and 64-bit views if supported
        for view_flag in (getattr(winreg, "KEY_WOW64_32KEY", 0), getattr(winreg, "KEY_WOW64_64KEY", 0)):
            if view_flag:
                try:
                    reg_key = winreg.CreateKeyEx(
                        winreg.HKEY_CURRENT_USER,
                        r"Software\Horner_Electric\Cscape\Setup",
                        0,
                        winreg.KEY_SET_VALUE | view_flag,
                    )
                    winreg.SetValueEx(reg_key, "CscapeExitedCorrectly", 0, winreg.REG_DWORD, int(val))
                    winreg.CloseKey(reg_key)
                    success = True
                except Exception:
                    pass
    except Exception as reg_err:
        logger.debug("Could not set CscapeExitedCorrectly=%s in registry: %s", val, reg_err)
    return success


def verify_cscape_exited_correctly() -> bool:
    """Verify that HKCU\\Software\\Horner_Electric\\Cscape\\Setup\\CscapeExitedCorrectly is 1."""
    if not is_windows():
        return True
    try:
        import winreg
        for view_flag in (0, getattr(winreg, "KEY_WOW64_32KEY", 0), getattr(winreg, "KEY_WOW64_64KEY", 0)):
            try:
                flags = winreg.KEY_READ | view_flag if view_flag else winreg.KEY_READ
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Horner_Electric\Cscape\Setup", 0, flags) as k:
                    val, _ = winreg.QueryValueEx(k, "CscapeExitedCorrectly")
                    if val == 1:
                        return True
            except Exception:
                pass
    except Exception:
        pass
    return False


def resolve_cscape_executable(custom_path: Optional[Union[str, Path]] = None) -> Optional[Path]:
    """Resolve the location of Cscape.exe across custom path, env vars, registry, and standard paths."""
    if custom_path is not None:
        p = Path(custom_path).resolve()
        if p.exists() and p.is_file():
            return p
        return p

    env_path = os.getenv("CSCAPE_BIN_PATH")
    if env_path:
        p = Path(env_path)
        if p.exists() and p.is_file():
            return p.resolve()

    env_dir = os.getenv("CSCAPE_DIR")
    if env_dir:
        p = Path(env_dir) / "Cscape.exe"
        if p.exists() and p.is_file():
            return p.resolve()

    for candidate in DEFAULT_CSCAPE_PATHS:
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()

    if is_windows():
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"cpj.Cscape\shell\open\command") as key:
                cmd_str = winreg.QueryValue(key, "")
                if cmd_str:
                    import shlex
                    parts = shlex.split(cmd_str, posix=False)
                    if parts:
                        p = Path(parts[0].strip('"'))
                        if p.exists() and p.is_file():
                            return p.resolve()
        except Exception:
            pass

    return None


@dataclass
class WindowInfo:
    """Information about a Win32 window."""
    hwnd: int
    pid: int
    class_name: str
    title: str
    visible: bool
    enabled: bool = True
    rect: Optional[Tuple[int, int, int, int]] = None


@dataclass
class ChildControlInfo:
    """Information about a Win32 child control."""
    hwnd: int
    control_id: int
    class_name: str
    text: str
    visible: bool = True
    enabled: bool = True
    rect: Optional[Tuple[int, int, int, int]] = None


class CscapeLifecycleManager:
    """Manages the full lifecycle of a Horner Cscape 10.2 process.

    Handles launching the process, detecting and dismissing startup modals
    (splash, 'Allow' security/firewall dialogs, and editor selection),
    enforcing single-instance policy ('No second window'), verifying readiness
    of the main IDE window, and performing graceful Alt+F4 / WM_CLOSE shutdown
    with forced timeout termination.
    """

    def __init__(
        self,
        executable_path: Optional[Union[str, Path]] = None,
        auto_dismiss_splash: bool = True,
        auto_select_iec: bool = True,
        auto_accept_allow: bool = True,
        single_instance_mode: str = "connect",  # "connect" or "recycle"
        reuse_existing: bool = True,
        launch_method: str = "subprocess",  # "subprocess" or "pywinauto"
        launch_timeout: float = 45.0,
        shutdown_timeout: float = 12.0,
        lock_file: Optional[Union[str, Path]] = None,
        lock_timeout: Optional[float] = None,
        mutex_name: str = DEFAULT_MUTEX_NAME,
    ) -> None:
        self.executable_path = resolve_cscape_executable(executable_path)
        self.auto_dismiss_splash = auto_dismiss_splash
        self.auto_select_iec = auto_select_iec
        self.auto_accept_allow = auto_accept_allow
        self.single_instance_mode = single_instance_mode.lower()
        self.reuse_existing = reuse_existing
        self.launch_method = launch_method.lower()
        self.launch_timeout = launch_timeout
        self.shutdown_timeout = shutdown_timeout

        self.lock_file: Path = Path(lock_file).resolve() if lock_file else DEFAULT_LOCK_FILE
        self.lock_timeout: float = float(lock_timeout) if lock_timeout is not None else max(45.0, self.launch_timeout)
        self.lock = CscapeSingleInstanceLock(
            lock_file=self.lock_file,
            mutex_name=mutex_name,
            timeout=self.lock_timeout,
        )

        self.process: Optional[subprocess.Popen] = None
        self.pid: Optional[int] = None
        self.pywinauto_app: Optional[Any] = None

        self.main_hwnd: Optional[int] = None
        self.splash_hwnd: Optional[int] = None
        self.editor_dialog_hwnd: Optional[int] = None

        self.state: CscapeLifecycleState = CscapeLifecycleState.NOT_STARTED
        self.start_time: Optional[float] = None
        self.exit_code: Optional[int] = None

    @property
    def is_running(self) -> bool:
        """Check if Cscape process is currently running."""
        if self.state == CscapeLifecycleState.TERMINATED:
            return False
        if self.process is not None:
            return self.process.poll() is None
        if self.pid is not None and is_windows():
            try:
                import psutil
                return psutil.pid_exists(self.pid) and psutil.Process(self.pid).status() != psutil.STATUS_ZOMBIE
            except Exception:
                return False
        return False

    @property
    def is_ready(self) -> bool:
        """Check if main window is ready and state is READY."""
        return self.state == CscapeLifecycleState.READY and self.is_running and self.main_hwnd is not None

    def get_main_window_handle(self) -> Optional[int]:
        """Return the window handle (HWND) of the main Cscape window."""
        return self.main_hwnd

    def get_main_window_title(self) -> Optional[str]:
        """Return the title of the main Cscape window."""
        if not self.main_hwnd or not is_windows():
            return None
        try:
            import win32gui
            return win32gui.GetWindowText(self.main_hwnd)
        except Exception:
            return None

    @property
    def main_window_title(self) -> Optional[str]:
        """Return the title of the main Cscape window."""
        return self.get_main_window_title()

    @property
    def iec_mode_active(self) -> bool:
        """Return True if IEC 61131 mode has been selected/active."""
        return self.state in (CscapeLifecycleState.EDITOR_TYPE_SELECTED, CscapeLifecycleState.READY)

    @property
    def value(self) -> str:
        """Return lifecycle state string value."""
        return self.state.value

    def __eq__(self, other: Any) -> bool:
        """Allow equality check against CscapeLifecycleState or state string."""
        if isinstance(other, CscapeLifecycleState):
            return self.state == other
        if isinstance(other, str):
            return self.state.value == other
        return super().__eq__(other)

    # =========================================================================
    # Single-Instance Management: 'No second window' enforcement
    # =========================================================================

    @classmethod
    def find_running_instances(cls) -> list[Any]:
        """Find all running Cscape.exe processes."""
        if not is_windows():
            return []
        import psutil
        instances = []
        for p in psutil.process_iter(["pid", "name"]):
            try:
                name = p.info.get("name") or ""
                if name.lower() == "cscape.exe":
                    if p.is_running() and p.status() != psutil.STATUS_ZOMBIE:
                        instances.append(p)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        return instances

    @classmethod
    def recycle_running_instances(
        cls,
        timeout: float = 5.0,
        lock_file: Optional[Union[str, Path]] = None,
        mutex_name: str = DEFAULT_MUTEX_NAME,
    ) -> int:
        """Cleanly terminate all running Cscape.exe instances without leaving remnants.

        Enforces 'No second window' directive by ensuring zero dangling instances.
        Synchronized with single-instance lock and mutex.
        """
        temp_lock = CscapeSingleInstanceLock(lock_file=lock_file, mutex_name=mutex_name)
        if temp_lock.is_stale():
            temp_lock.break_lock()

        if not is_windows():
            temp_lock.break_lock()
            return 0

        procs = cls.find_running_instances()
        if not procs:
            temp_lock.break_lock()
            set_cscape_exited_correctly(1)
            return 0

        logger.info("Recycling %d existing Cscape.exe instance(s)...", len(procs))

        # Proactively send WM_CLOSE to top-level Cscape windows first
        try:
            import win32gui
            import win32process

            pids = {p.pid for p in procs}

            def _close_cb(hwnd: int, extra: Any) -> bool:
                try:
                    _, win_pid = win32process.GetWindowThreadProcessId(hwnd)
                    if win_pid in pids:
                        win32gui.PostMessage(hwnd, WM_CLOSE, 0, 0)
                except Exception:
                    pass
                return True

            win32gui.EnumWindows(_close_cb, None)
            time.sleep(0.4)
        except Exception:
            pass

        # Force terminate via taskkill
        try:
            subprocess.run(
                ["taskkill.exe", "/F", "/T", "/IM", "Cscape.exe"],
                capture_output=True,
                timeout=timeout,
            )
        except Exception as e:
            logger.debug("taskkill error in recycle_running_instances: %s", e)

        # Explicitly kill any remaining process objects
        for p in procs:
            try:
                p.kill()
            except Exception:
                pass

        start_t = time.time()
        while time.time() - start_t < timeout:
            remaining = cls.find_running_instances()
            if not remaining:
                break
            time.sleep(0.15)

        # Buffer delay to allow Windows kernel to release file locks and mutexes
        time.sleep(2.5)
        # Clean up lock file
        temp_lock.break_lock()
        # Restore clean registry exit status to prevent crash recovery popup on subsequent launches
        set_cscape_exited_correctly(1)
        return len(procs)

    def _connect_to_existing_instance(self, proc: Any, timeout: float = 15.0) -> bool:
        """Connect to an existing running Cscape process and verify readiness without spawning."""
        if not is_windows():
            return False

        try:
            self.pid = proc.pid
            self.process = None  # Existing process is externally owned
            self.state = CscapeLifecycleState.STARTING
            self.start_time = time.time()

            logger.info("Connecting to existing Cscape process PID %s...", self.pid)

            # Connect pywinauto application instance if available
            try:
                import pywinauto
                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore", category=UserWarning, module="pywinauto")
                    self.pywinauto_app = pywinauto.Application().connect(process=self.pid)
            except Exception as e:
                logger.debug("pywinauto connect to existing pid %s: %s", self.pid, e)

            # Proactively coordinate startup modals and verify main window readiness
            self._coordinate_startup(timeout=timeout)
            if self.is_ready and self.main_hwnd is not None:
                logger.info("Successfully connected to existing Cscape instance PID %s (main_hwnd=%s)", self.pid, self.main_hwnd)
                return True
        except Exception as err:
            logger.warning("Could not connect to existing Cscape PID %s: %s", getattr(proc, "pid", None), err)
            self.pid = None
            self.pywinauto_app = None
            self.main_hwnd = None
            self.state = CscapeLifecycleState.NOT_STARTED

        return False

    # =========================================================================
    # Window Enumeration and Control Helpers (Win32 & pywinauto)
    # =========================================================================

    def _get_allowed_pids(self) -> set[int]:
        """Return set of PIDs strictly belonging to supervised Cscape process and direct children."""
        if not self.pid:
            return set()
        pids = {self.pid}
        if is_windows():
            try:
                import psutil
                for child in psutil.Process(self.pid).children(recursive=False):
                    pids.add(child.pid)
            except Exception:
                pass
        return pids

    def _enum_process_windows(self) -> list[WindowInfo]:
        if not self.pid and self.main_hwnd:
            try:
                import win32process
                _, self.pid = win32process.GetWindowThreadProcessId(self.main_hwnd)
            except Exception:
                pass

        if not self.pid or not is_windows():
            return []

        windows: list[WindowInfo] = []
        pids = self._get_allowed_pids()

        # Primary: ctypes user32 EnumWindows (deterministic, safe across all desktops/sessions)
        try:
            import ctypes
            import ctypes.wintypes

            user32 = ctypes.windll.user32
            WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)

            def enum_cb(hwnd: int, lparam: Any) -> int:
                try:
                    win_pid = ctypes.wintypes.DWORD()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(win_pid))
                    if win_pid.value in pids:
                        buf = ctypes.create_unicode_buffer(512)
                        user32.GetWindowTextW(hwnd, buf, 512)
                        cls_buf = ctypes.create_unicode_buffer(512)
                        user32.GetClassNameW(hwnd, cls_buf, 512)
                        visible = bool(user32.IsWindowVisible(hwnd))
                        enabled = bool(user32.IsWindowEnabled(hwnd))
                        rect = None
                        r = ctypes.wintypes.RECT()
                        if user32.GetWindowRect(hwnd, ctypes.byref(r)):
                            rect = (r.left, r.top, r.right, r.bottom)
                        windows.append(
                            WindowInfo(
                                hwnd=hwnd,
                                pid=win_pid.value,
                                class_name=cls_buf.value,
                                title=buf.value,
                                visible=visible,
                                enabled=enabled,
                                rect=rect,
                            )
                        )
                except Exception:
                    pass
                return 1

            user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
            return windows
        except Exception as err:
            logger.debug("Error in ctypes EnumWindows: %s", err)

        # Fallback: win32gui EnumWindows (with explicit return True so enumeration doesn't halt)
        try:
            import win32gui
            import win32process

            def win32_cb(hwnd: int, extra: Any) -> bool:
                try:
                    _, win_pid = win32process.GetWindowThreadProcessId(hwnd)
                    if win_pid in pids:
                        cls_name = win32gui.GetClassName(hwnd)
                        title = win32gui.GetWindowText(hwnd)
                        visible = bool(win32gui.IsWindowVisible(hwnd))
                        enabled = bool(win32gui.IsWindowEnabled(hwnd))
                        rect = None
                        try:
                            rect = win32gui.GetWindowRect(hwnd)
                        except Exception:
                            pass
                        windows.append(
                            WindowInfo(
                                hwnd=hwnd,
                                pid=win_pid,
                                class_name=cls_name,
                                title=title,
                                visible=visible,
                                enabled=enabled,
                                rect=rect,
                            )
                        )
                except Exception:
                    pass
                return True

            win32gui.EnumWindows(win32_cb, None)
        except Exception as win32_err:
            logger.debug("Error in win32gui EnumWindows fallback: %s", win32_err)

        return windows

    def _enum_child_controls(self, parent_hwnd: int) -> dict[int, int]:
        """Map control ID -> HWND for all child controls in a parent window."""
        if not is_windows():
            return {}

        controls: dict[int, int] = {}
        # Primary: ctypes user32 EnumChildWindows
        try:
            import ctypes
            import ctypes.wintypes

            user32 = ctypes.windll.user32
            WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)

            def child_cb(hwnd: int, lparam: Any) -> int:
                try:
                    cid = user32.GetDlgCtrlID(hwnd)
                    controls[cid] = hwnd
                except Exception:
                    pass
                return 1

            user32.EnumChildWindows(parent_hwnd, WNDENUMPROC(child_cb), 0)
            return controls
        except Exception as err:
            logger.debug("Error in ctypes EnumChildWindows for hwnd %s: %s", parent_hwnd, err)

        # Fallback: win32gui EnumChildWindows (with explicit return True)
        try:
            import win32gui

            def win32_child_cb(hwnd: int, extra: Any) -> bool:
                try:
                    cid = win32gui.GetDlgCtrlID(hwnd)
                    controls[cid] = hwnd
                except Exception:
                    pass
                return True

            win32gui.EnumChildWindows(parent_hwnd, win32_child_cb, None)
        except Exception as win32_err:
            logger.debug("Error in win32gui EnumChildWindows fallback: %s", win32_err)

        return controls

    def _enum_all_child_controls(self, parent_hwnd: int) -> list[ChildControlInfo]:
        """Enumerate all child controls of a parent window with full metadata."""
        if not is_windows():
            return []

        children: list[ChildControlInfo] = []
        try:
            import ctypes
            import ctypes.wintypes

            user32 = ctypes.windll.user32
            WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)

            def child_cb(hwnd: int, lparam: Any) -> int:
                try:
                    cid = user32.GetDlgCtrlID(hwnd)
                    buf = ctypes.create_unicode_buffer(512)
                    user32.GetWindowTextW(hwnd, buf, 512)
                    cls_buf = ctypes.create_unicode_buffer(512)
                    user32.GetClassNameW(hwnd, cls_buf, 512)
                    vis = bool(user32.IsWindowVisible(hwnd))
                    enb = bool(user32.IsWindowEnabled(hwnd))
                    r = ctypes.wintypes.RECT()
                    rect = None
                    if user32.GetWindowRect(hwnd, ctypes.byref(r)):
                        rect = (r.left, r.top, r.right, r.bottom)
                    children.append(
                        ChildControlInfo(
                            hwnd=hwnd,
                            control_id=cid,
                            class_name=cls_buf.value,
                            text=buf.value,
                            visible=vis,
                            enabled=enb,
                            rect=rect,
                        )
                    )
                except Exception:
                    pass
                return 1

            user32.EnumChildWindows(parent_hwnd, WNDENUMPROC(child_cb), 0)
            return children
        except Exception as err:
            logger.debug("Error in ctypes EnumChildWindows for hwnd %s: %s", parent_hwnd, err)

        try:
            import win32gui

            def win32_child_cb(hwnd: int, extra: Any) -> bool:
                try:
                    cid = win32gui.GetDlgCtrlID(hwnd)
                    cls_name = win32gui.GetClassName(hwnd)
                    text = win32gui.GetWindowText(hwnd)
                    vis = bool(win32gui.IsWindowVisible(hwnd))
                    enb = bool(win32gui.IsWindowEnabled(hwnd))
                    children.append(
                        ChildControlInfo(
                            hwnd=hwnd,
                            control_id=cid,
                            class_name=cls_name,
                            text=text,
                            visible=vis,
                            enabled=enb,
                        )
                    )
                except Exception:
                    pass
                return True

            win32gui.EnumChildWindows(parent_hwnd, win32_child_cb, None)
        except Exception as win32_err:
            logger.debug("Error in win32gui EnumChildWindows fallback: %s", win32_err)

        return children

    # =========================================================================
    # Dialog Handlers: 'Allow' Security/Firewall Modals, Splash & Select Editor
    # =========================================================================

    def find_allow_dialogs(self, check_system_windows: bool = False) -> list[dict[str, Any]]:
        """Find 'Allow' security or firewall modal dialogs strictly belonging to Cscape and its direct children.

        Detects dialogs with:
        - Text containing 'Allow access' or specific firewall/security prompt keywords
        - Buttons containing 'Allow access', 'Allow this app', or 'Unblock'
        - Strictly restricted to Cscape PID and its direct children; no system-wide window enumeration
        """
        # Kill global allow bypass: enforce check_system_windows is hardcoded to False (H05, H13)
        check_system_windows = False

        if not is_windows():
            return []

        results: list[dict[str, Any]] = []

        # Strictly restrict candidate windows to Cscape process PID and its direct children.
        # Dangerous system-wide EnumWindows is completely eliminated.
        candidate_windows: list[WindowInfo] = list(self._enum_process_windows())
        if not candidate_windows and not self.pid:
            return []

        allowed_pids = self._get_allowed_pids() if self.pid else set()

        for win in candidate_windows:
            # Any window not belonging to Cscape PID must NEVER be clicked or dismissed
            if self.pid is not None and win.pid not in allowed_pids:
                continue

            # Ensure modal dialog class is strictly #32770
            if win.class_name != DIALOG_CLASS_NAME:
                continue

            title_lower = win.title.lower()

            # Strictly ignore Splash and Editor Selection dialogs (they have dedicated handlers)
            if SPLASH_TITLE_SUBSTRING.lower() in title_lower or EDITOR_TYPE_TITLE_SUBSTRING.lower() in title_lower:
                continue

            # Strictly ignore non-fatal compilation error dialogs (H13, C3 fail-closed invariant)
            if "non-fatal" in title_lower or "nonfatal" in title_lower:
                continue

            is_dialog_class = True
            is_security_title = any(kw in title_lower for kw in ALLOW_TEXT_KEYWORDS)

            children = self._enum_all_child_controls(win.hwnd)

            allow_button: Optional[ChildControlInfo] = None
            for child in children:
                c_cls = child.class_name.lower()
                if "button" not in c_cls and c_cls in ("static", "edit", "combobox", "listbox"):
                    continue
                c_text = child.text.replace("&", "").strip().lower()
                if any(bkw.replace("&", "").strip().lower() in c_text for bkw in ALLOW_BUTTON_KEYWORDS) or c_text in ("allow access", "allow this app", "unblock", "always allow"):
                    allow_button = child
                    break

            dialog_texts = [win.title] + [c.text for c in children if c.text]
            combined_text = " ".join(dialog_texts).lower()

            # Strict exclusion for compilation error / non-fatal dialogs
            if (
                "non-fatal" in title_lower
                or "nonfatal" in title_lower
                or "errors occurred" in combined_text
                or "do you wish to continue" in combined_text
                or "build error" in combined_text
            ):
                continue

            import re
            has_allow_phrase = bool(
                re.search(r"\ballow\s+access\b", combined_text)
                or re.search(r"\ballow\s+this\s+app\b", combined_text)
                or any(kw in combined_text for kw in ALLOW_TEXT_KEYWORDS)
            )

            # Match if:
            # 1) An explicit 'Allow access' / security button exists, OR
            # 2) Text contains 'Allow access' or specific security phrase in a dialog context
            if allow_button is not None or (has_allow_phrase and (is_security_title or is_dialog_class)):
                if allow_button is None:
                    for child in children:
                        c_cls = child.class_name.lower()
                        if "button" not in c_cls and c_cls in ("static", "edit", "combobox", "listbox"):
                            continue
                        c_text = child.text.replace("&", "").strip().lower()
                        if child.control_id == ID_OK or c_text in ("ok", "yes", "allow access", "unblock"):
                            allow_button = child
                            break

                results.append({
                    "hwnd": win.hwnd,
                    "pid": win.pid,
                    "title": win.title,
                    "class_name": win.class_name,
                    "allow_button_hwnd": allow_button.hwnd if allow_button else None,
                    "allow_button_id": allow_button.control_id if allow_button else ID_OK,
                    "allow_button_text": allow_button.text if allow_button else "OK",
                    "text_content": combined_text[:300],
                })

        return results

    def handle_allow_dialogs(self, timeout: float = 3.0, check_system_windows: bool = False) -> int:
        """Detect any 'Allow' security or firewall modal dialogs and auto-accept them.

        Auto-accepts dialogs with:
        - Text containing 'Allow' or 'Allow access'
        - Buttons containing 'Allow' or 'Allow access'

        Returns:
            Number of dialogs successfully accepted.
        """
        # Kill global allow bypass: enforce check_system_windows is hardcoded to False (H05, H13)
        check_system_windows = False

        if not is_windows():
            return 0

        import win32gui

        accepted_count = 0
        dialogs = self.find_allow_dialogs(check_system_windows=False)
        allowed_pids = self._get_allowed_pids() if self.pid else set()
        for dlg in dialogs:
            dlg_hwnd = dlg["hwnd"]
            dlg_pid = dlg.get("pid")
            dlg_cls = dlg.get("class_name")
            btn_hwnd = dlg["allow_button_hwnd"]
            btn_id = dlg["allow_button_id"]
            title = dlg["title"]
            btn_text = dlg["allow_button_text"]

            # Ensure modal dialog class is strictly #32770
            if dlg_cls != DIALOG_CLASS_NAME:
                logger.warning(
                    "Skipping dialog hwnd=%s: class '%s' is not strictly %s",
                    dlg_hwnd,
                    dlg_cls,
                    DIALOG_CLASS_NAME,
                )
                continue

            # Any window not belonging to Cscape PID must NEVER be clicked or dismissed
            if self.pid is not None:
                if dlg_pid is not None and dlg_pid not in allowed_pids:
                    logger.warning(
                        "Skipping dialog hwnd=%s: PID %s does not match supervised Cscape PID %s",
                        dlg_hwnd,
                        dlg_pid,
                        self.pid,
                    )
                    continue

                if is_windows():
                    try:
                        import win32process
                        _, win_proc_id = win32process.GetWindowThreadProcessId(dlg_hwnd)
                        if win_proc_id and win_proc_id not in allowed_pids:
                            logger.warning(
                                "Skipping dialog hwnd=%s: live window PID %s does not match supervised Cscape PID %s",
                                dlg_hwnd,
                                win_proc_id,
                                self.pid,
                            )
                            continue
                    except Exception:
                        pass

            logger.info(
                "Auto-accepting 'Allow' security/firewall dialog (hwnd=%s, title='%s', btn_id=%s, btn_text='%s')",
                dlg_hwnd,
                title,
                btn_id,
                btn_text,
            )

            # 1. Click button via BM_CLICK
            if btn_hwnd and win32gui.IsWindow(btn_hwnd):
                try:
                    win32gui.SendMessage(btn_hwnd, BM_CLICK, 0, 0)
                except Exception as err:
                    logger.debug("BM_CLICK error on allow button: %s", err)

            # 2. Post WM_COMMAND to dialog
            try:
                win32gui.PostMessage(dlg_hwnd, WM_COMMAND, (BN_CLICKED << 16) | btn_id, btn_hwnd or 0)
            except Exception as err:
                logger.debug("WM_COMMAND error on allow dialog: %s", err)

            # 3. pywinauto click fallback
            if self.pywinauto_app is not None and btn_hwnd:
                try:
                    import pywinauto
                    with warnings.catch_warnings():
                        warnings.filterwarnings("ignore", category=UserWarning)
                        pywinauto.controls.HwndWrapper.HwndWrapper(btn_hwnd).click()
                except Exception:
                    pass

            # 4. Verify dismissal
            dismissed = False
            start_verify = time.time()
            while time.time() - start_verify < timeout:
                time.sleep(0.1)
                if not win32gui.IsWindow(dlg_hwnd):
                    dismissed = True
                    break

            if dismissed:
                logger.info("'Allow' dialog hwnd=%s accepted and dismissed successfully.", dlg_hwnd)
                accepted_count += 1
            else:
                logger.debug("'Allow' dialog hwnd=%s still present after click attempt", dlg_hwnd)

        return accepted_count

    def harvest_modal_dialog_diagnostics(self, hwnd: int) -> Dict[str, Any]:
        """Harvests structured diagnostic text and control content from a modal #32770 dialog.

        Extracts:
        - Title and class name
        - Static text lines (warning and error messages)
        - Edit control values
        - ListBox item texts
        - Button options
        - Semantic classification: is_error, is_warning, is_compilation, is_dirty_prompt

        Returns:
            Structured diagnostic dictionary.
        """
        if not is_windows():
            return {"hwnd": hwnd, "status": "inconclusive", "error": "Not on Windows platform"}

        if not hwnd or hwnd <= 0:
            return {
                "hwnd": hwnd,
                "status": "inconclusive",
                "error": f"Invalid or non-existent window handle: {hwnd}",
                "title": "",
                "static_texts": [],
                "edit_texts": [],
                "listbox_texts": [],
                "buttons": [],
                "classification": {
                    "is_error": False,
                    "is_warning": False,
                    "is_compilation": False,
                    "is_dirty_prompt": False,
                },
            }

        import win32gui
        import win32process

        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            title = win32gui.GetWindowText(hwnd)
            cls_name = win32gui.GetClassName(hwnd)
        except Exception as e:
            return {
                "hwnd": hwnd,
                "status": "inconclusive",
                "error": f"Unable to query window handle: {e}",
                "title": "",
                "static_texts": [],
                "edit_texts": [],
                "listbox_texts": [],
                "buttons": [],
                "classification": {
                    "is_error": False,
                    "is_warning": False,
                    "is_compilation": False,
                    "is_dirty_prompt": False,
                },
            }

        children = self._enum_all_child_controls(hwnd)
        static_texts: list[str] = []
        edit_texts: list[str] = []
        listbox_texts: list[str] = []
        buttons: list[dict[str, Any]] = []

        for child in children:
            c_cls = child.class_name.lower()
            t = child.text.strip()
            if "static" in c_cls:
                if t and t not in static_texts:
                    static_texts.append(t)
            elif "edit" in c_cls:
                if t and t not in edit_texts:
                    edit_texts.append(t)
            elif "listbox" in c_cls:
                if t and t not in listbox_texts:
                    listbox_texts.append(t)
            elif "button" in c_cls:
                buttons.append({
                    "id": child.control_id,
                    "text": t,
                    "hwnd": child.hwnd,
                })

        combined_text = f"{title} " + " ".join(static_texts + edit_texts + listbox_texts)
        t_lower = combined_text.lower()

        is_error = any(k in t_lower for k in ("error", "failed", "fatal", "invalid", "cannot", "exception"))
        is_warning = any(k in t_lower for k in ("warning", "warn", "caution", "notice"))
        is_compilation = any(k in t_lower for k in ("compile", "compilation", "error check", "build"))
        is_dirty_prompt = any(k in t_lower for k in ("save changes", "save modified", "do you want to save"))

        return {
            "hwnd": hwnd,
            "pid": pid,
            "title": title,
            "class_name": cls_name,
            "static_texts": static_texts,
            "edit_texts": edit_texts,
            "listbox_texts": listbox_texts,
            "buttons": buttons,
            "raw_message": "\n".join(static_texts) if static_texts else title,
            "combined_text": combined_text,
            "classification": {
                "is_error": is_error,
                "is_warning": is_warning,
                "is_compilation": is_compilation,
                "is_dirty_prompt": is_dirty_prompt,
            },
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

    def harvest_all_modal_diagnostics(self) -> List[Dict[str, Any]]:
        """Scans all active modal #32770 dialogs belonging to Cscape and harvests structured diagnostics."""
        results: List[Dict[str, Any]] = []
        if not is_windows():
            return results

        allowed_pids = self._get_allowed_pids() if self.pid else set()
        candidate_windows = list(self._enum_process_windows())
        for win in candidate_windows:
            if self.pid is not None and win.pid not in allowed_pids:
                continue
            if win.class_name == DIALOG_CLASS_NAME:
                diag = self.harvest_modal_dialog_diagnostics(win.hwnd)
                results.append(diag)
        return results

    def find_splash_dialog(self) -> Optional[WindowInfo]:
        """Find the 'About Cscape' modal splash dialog (#32770, IDOK=1) if present."""
        for win in self._enum_process_windows():
            if win.class_name == DIALOG_CLASS_NAME and win.visible:
                title_lower = win.title.lower()
                if SPLASH_TITLE_SUBSTRING.lower() in title_lower:
                    return win
                # Check child controls for splash identifier if title is generic
                try:
                    for child in self._enum_all_child_controls(win.hwnd):
                        if SPLASH_TITLE_SUBSTRING.lower() in child.text.lower():
                            return win
                except Exception:
                    pass
        return None

    def dismiss_splash_window(self, timeout: float = 10.0) -> bool:
        """Detect and dismiss the modal 'About Cscape' splash window (#32770, IDOK=1).

        Sends BM_CLICK to the OK button (Control ID 1) and WM_COMMAND with ID_OK,
        retrying robustly until the splash dialog disappears.
        """
        if not is_windows():
            return False

        import win32gui

        start_t = time.time()
        while time.time() - start_t < timeout:
            splash = self.find_splash_dialog()
            if splash:
                self.splash_hwnd = splash.hwnd
                logger.info("Detected 'About Cscape' splash window (hwnd=%s, visible=%s)", splash.hwnd, splash.visible)
                # Settle delay so dialog message pump is stable
                time.sleep(0.25)
                controls = self._enum_child_controls(splash.hwnd)
                ok_btn = controls.get(ID_OK)
                if not ok_btn:
                    try:
                        ok_btn = win32gui.GetDlgItem(splash.hwnd, ID_OK)
                    except Exception:
                        ok_btn = None
                if not ok_btn:
                    for child in self._enum_all_child_controls(splash.hwnd):
                        if child.class_name.lower() == "button" and (
                            child.control_id == ID_OK
                            or child.text.replace("&", "").strip().lower() in ("ok", "yes")
                        ):
                            ok_btn = child.hwnd
                            break

                for retry in range(5):
                    logger.info("Posting WM_COMMAND ID_OK to 'About Cscape' splash (hwnd=%s, ok_btn=%s, attempt %s)", splash.hwnd, ok_btn, retry + 1)
                    if ok_btn and win32gui.IsWindow(ok_btn):
                        try:
                            win32gui.SendMessage(ok_btn, BM_CLICK, 0, 0)
                        except Exception:
                            pass
                        try:
                            win32gui.PostMessage(ok_btn, BM_CLICK, 0, 0)
                        except Exception:
                            pass
                    try:
                        win32gui.PostMessage(splash.hwnd, WM_COMMAND, (BN_CLICKED << 16) | ID_OK, ok_btn or 0)
                    except Exception:
                        pass

                    # Polling check if dismissed
                    for _ in range(5):
                        time.sleep(0.1)
                        if not self.find_splash_dialog():
                            logger.info("'About Cscape' splash window dismissed successfully.")
                            self.state = CscapeLifecycleState.SPLASH_DISMISSED
                            return True

                time.sleep(0.2)
                if not self.find_splash_dialog():
                    logger.info("'About Cscape' splash window dismissed successfully.")
                    self.state = CscapeLifecycleState.SPLASH_DISMISSED
                    return True

            time.sleep(0.2)

        logger.debug("No 'About Cscape' splash dialog detected or dismissed within %ss", timeout)
        return False

    def find_editor_type_dialog(self) -> Optional[WindowInfo]:
        """Find the 'Select Editor Type' dialog (#32770) if present and visible."""
        for win in self._enum_process_windows():
            if win.class_name == DIALOG_CLASS_NAME and win.visible:
                title_lower = win.title.lower()
                if EDITOR_TYPE_TITLE_SUBSTRING.lower() in title_lower:
                    return win
                try:
                    for child in self._enum_all_child_controls(win.hwnd):
                        if (
                            EDITOR_TYPE_TITLE_SUBSTRING.lower() in child.text.lower()
                            or child.control_id == RADIO_ID_IEC_61131
                        ):
                            return win
                except Exception:
                    pass
        return None

    def handle_editor_type_dialog(
        self,
        radio_id: int = RADIO_ID_IEC_61131,
        timeout: float = 15.0,
    ) -> bool:
        """Detect 'Select Editor Type' dialog (#32770), select specified editor radio button (1461), and click OK (1).

        Default radio_id is 1461 ('IEC 61131 Language Editors').
        Executes robust message retries until dialog dismissal is verified.
        Strictly rejects legacy ladder mode radio IDs (1460, 3757).
        """
        if radio_id in (RADIO_ID_ADVANCED_LADDER_REGISTER, RADIO_ID_ADVANCED_LADDER_VARIABLE):
            raise CscapeLifecycleError(
                f"Legacy ladder mode radio ID {radio_id} is strictly rejected. "
                f"Only IEC 61131 mode (ID {RADIO_ID_IEC_61131}) is permitted."
            )
        if radio_id != RADIO_ID_IEC_61131:
            raise CscapeLifecycleError(
                f"Non-IEC editor mode radio ID {radio_id} is strictly rejected. "
                f"Only IEC 61131 mode (ID {RADIO_ID_IEC_61131}) is permitted."
            )

        if not is_windows():
            return False

        import win32gui

        start_t = time.time()
        while time.time() - start_t < timeout:
            dlg = self.find_editor_type_dialog()
            if dlg:
                self.editor_dialog_hwnd = dlg.hwnd
                logger.info("Detected 'Select Editor Type' dialog (hwnd=%s, visible=%s)", dlg.hwnd, dlg.visible)
                # Settle delay so dialog message pump is stable
                time.sleep(0.25)
                controls = self._enum_child_controls(dlg.hwnd)
                radio_hwnd = controls.get(radio_id)
                ok_btn = controls.get(ID_OK)

                for retry in range(5):
                    if not radio_hwnd or not ok_btn:
                        controls = self._enum_child_controls(dlg.hwnd)
                        radio_hwnd = controls.get(radio_id)
                        ok_btn = controls.get(ID_OK)

                    if not radio_hwnd:
                        try:
                            radio_hwnd = win32gui.GetDlgItem(dlg.hwnd, radio_id)
                        except Exception:
                            pass
                    if not ok_btn:
                        try:
                            ok_btn = win32gui.GetDlgItem(dlg.hwnd, ID_OK)
                        except Exception:
                            pass

                    if not radio_hwnd or not ok_btn:
                        for child in self._enum_all_child_controls(dlg.hwnd):
                            if child.control_id == radio_id:
                                radio_hwnd = child.hwnd
                            elif child.control_id == ID_OK or child.text.replace("&", "").strip().lower() in ("ok", "yes"):
                                ok_btn = child.hwnd

                    if radio_hwnd and win32gui.IsWindow(radio_hwnd):
                        logger.info("Selecting editor radio button ID %s (hwnd=%s, attempt %s)", radio_id, radio_hwnd, retry + 1)
                        try:
                            win32gui.SendMessage(radio_hwnd, BM_CLICK, 0, 0)
                            win32gui.SendMessage(radio_hwnd, BM_SETCHECK, BST_CHECKED, 0)
                            win32gui.PostMessage(radio_hwnd, BM_SETCHECK, BST_CHECKED, 0)
                            win32gui.PostMessage(dlg.hwnd, WM_COMMAND, (BN_CLICKED << 16) | radio_id, radio_hwnd)
                        except Exception as err:
                            logger.debug("Error selecting radio %s: %s", radio_id, err)
                    else:
                        try:
                            win32gui.PostMessage(dlg.hwnd, WM_COMMAND, (BN_CLICKED << 16) | radio_id, 0)
                        except Exception:
                            pass

                    time.sleep(0.1)

                    if ok_btn and win32gui.IsWindow(ok_btn):
                        logger.info("Clicking OK button (ID 1, hwnd=%s, attempt %s)", ok_btn, retry + 1)
                        try:
                            win32gui.SendMessage(ok_btn, BM_CLICK, 0, 0)
                            win32gui.PostMessage(dlg.hwnd, WM_COMMAND, (BN_CLICKED << 16) | ID_OK, ok_btn)
                        except Exception as err:
                            logger.debug("Error clicking OK: %s", err)
                    else:
                        try:
                            win32gui.PostMessage(dlg.hwnd, WM_COMMAND, (BN_CLICKED << 16) | ID_OK, 0)
                        except Exception:
                            pass

                    # Polling check if dismissed
                    for _ in range(5):
                        time.sleep(0.1)
                        if not self.find_editor_type_dialog():
                            logger.info("'Select Editor Type' dialog dismissed successfully.")
                            self.state = CscapeLifecycleState.EDITOR_TYPE_SELECTED
                            return True

                time.sleep(0.2)
                if not self.find_editor_type_dialog():
                    logger.info("'Select Editor Type' dialog dismissed successfully.")
                    self.state = CscapeLifecycleState.EDITOR_TYPE_SELECTED
                    return True

            time.sleep(0.2)

        logger.debug("No 'Select Editor Type' dialog detected or dismissed within %ss", timeout)
        return False

    def _is_editor_dialog_suppressed(self) -> bool:
        """Check if 'Select Editor Type' dialog is suppressed in Windows Registry."""
        if not is_windows():
            return False
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Horner_Electric\Cscape\Editor",
            ) as k:
                val, _ = winreg.QueryValueEx(k, "AllowUserToChooseProgram")
                return int(val) == 0
        except Exception:
            return False


    def find_save_as_dialog(self) -> Optional[WindowInfo]:
        """Find the 'Save As' modal common dialog (#32770, Edit 1152, ID 1) if present."""
        for win in self._enum_process_windows():
            if win.class_name == DIALOG_CLASS_NAME:
                title_lower = win.title.lower()
                if "save as" in title_lower or "save" in title_lower:
                    return win
        return None

    def handle_save_as_dialog(
        self,
        destination_path: Union[str, Path],
        timeout: float = 15.0,
    ) -> bool:
        """Automated detection and handling of Save As dialog (#32770, Edit 1152, ID 1).

        Locates Edit 1152, sets destination path, clicks Save button (ID 1),
        handles any confirmation/replace modals or firewall/security prompts,
        and verifies dismissal.

        Returns:
            True if dialog was successfully detected, operated, and dismissed.
        """
        if not is_windows():
            return False

        import win32gui

        target_path = Path(destination_path).resolve()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        full_path_str = str(target_path)

        start_t = time.time()
        save_dlg: Optional[WindowInfo] = None
        while time.time() - start_t < timeout:
            save_dlg = self.find_save_as_dialog()
            if save_dlg:
                break
            time.sleep(0.2)

        if not save_dlg:
            logger.debug("Save As dialog (#32770) not found within %ss", timeout)
            return False

        dlg_hwnd = save_dlg.hwnd
        logger.info("Handling Save As dialog (#32770, hwnd=%s) for target: %s", dlg_hwnd, target_path)

        # 1. UIAutomation path
        saved = False
        try:
            import uiautomation as auto
            save_win = auto.ControlFromHandle(dlg_hwnd)
            name_cb = save_win.ComboBoxControl(AutomationId="FileNameControlHost")
            edit = name_cb.EditControl() if name_cb.Exists(0, 0) else save_win.EditControl(searchDepth=6)
            save_btn = save_win.ButtonControl(AutomationId="1")
            if edit.Exists(0, 0) and save_btn.Exists(0, 0):
                edit.GetValuePattern().SetValue(full_path_str)
                time.sleep(0.2)
                save_btn.GetInvokePattern().Invoke()
                saved = True
        except Exception as uia_err:
            logger.debug("UIAutomation Save As attempt deferred/failed: %s", uia_err)

        # 2. Win32 messages path: Edit 1152, Button 1
        if not saved:
            edit_hwnd = None
            try:
                edit_hwnd = win32gui.GetDlgItem(dlg_hwnd, EDIT_ID_FILE_NAME)
            except Exception:
                pass
            if not edit_hwnd:
                for child in self._enum_all_child_controls(dlg_hwnd):
                    if child.control_id == EDIT_ID_FILE_NAME or child.class_name.lower() == "edit":
                        edit_hwnd = child.hwnd
                        break

            save_btn_hwnd = None
            try:
                save_btn_hwnd = win32gui.GetDlgItem(dlg_hwnd, BUTTON_ID_SAVE)
            except Exception:
                pass
            if not save_btn_hwnd:
                for child in self._enum_all_child_controls(dlg_hwnd):
                    if child.control_id == BUTTON_ID_SAVE or (
                        child.class_name.lower() == "button" and child.text.replace("&", "").strip().lower() in ("save", "ok")
                    ):
                        save_btn_hwnd = child.hwnd
                        break

            if edit_hwnd:
                logger.debug("Setting Edit control (ID %s, hwnd=%s) text to '%s'", EDIT_ID_FILE_NAME, edit_hwnd, full_path_str)
                win32gui.SendMessage(edit_hwnd, WM_SETTEXT, 0, full_path_str)
                time.sleep(0.2)

            if save_btn_hwnd:
                logger.debug("Clicking Save button (ID %s, hwnd=%s)", BUTTON_ID_SAVE, save_btn_hwnd)
                try:
                    win32gui.PostMessage(save_btn_hwnd, BM_CLICK, 0, 0)
                except Exception:
                    pass
                win32gui.PostMessage(dlg_hwnd, WM_COMMAND, (BN_CLICKED << 16) | BUTTON_ID_SAVE, save_btn_hwnd)
            else:
                win32gui.PostMessage(dlg_hwnd, WM_COMMAND, (BN_CLICKED << 16) | BUTTON_ID_SAVE, 0)

        # 3. Post-save modal dismissal: replace confirmation (#32770) or firewall/security prompts
        confirm_start = time.time()
        while time.time() - confirm_start < 8.0:
            if self.auto_accept_allow:
                self.handle_allow_dialogs(timeout=0.3)

            for win in self._enum_process_windows():
                if win.hwnd != dlg_hwnd and win.hwnd != self.main_hwnd:
                    w_title = win.title.lower()
                    w_cls = win.class_name
                    if w_cls == DIALOG_CLASS_NAME or any(kw in w_title for kw in ("confirm", "replace", "warning", "allow", "security")):
                        # Click Yes (ID 6) or OK (ID 1)
                        for child in self._enum_all_child_controls(win.hwnd):
                            c_text = child.text.replace("&", "").strip().lower()
                            if child.control_id in (6, 1) or c_text in ("yes", "ok", "replace"):
                                try:
                                    win32gui.PostMessage(child.hwnd, BM_CLICK, 0, 0)
                                    win32gui.PostMessage(win.hwnd, WM_COMMAND, (BN_CLICKED << 16) | child.control_id, child.hwnd)
                                except Exception:
                                    pass
                                break

            if not win32gui.IsWindow(dlg_hwnd) or not win32gui.IsWindowVisible(dlg_hwnd):
                logger.info("Save As dialog dismissed successfully.")
                return True
            time.sleep(0.2)

        return not win32gui.IsWindow(dlg_hwnd) or not win32gui.IsWindowVisible(dlg_hwnd)

    def find_main_cscape_window(self) -> Optional[WindowInfo]:
        """Find the main Cscape IDE window if fully created and visible."""
        for win in self._enum_process_windows():
            # Class is MFC Frame (starts with Afx:), not a modal dialog (#32770)
            if win.class_name != DIALOG_CLASS_NAME and MAIN_WINDOW_TITLE_SUBSTRING.lower() in win.title.lower():
                if win.visible:
                    # Check window size
                    if win.rect:
                        left, top, right, bottom = win.rect
                        width = right - left
                        height = bottom - top
                        if width > 200 and height > 200:
                            return win
                    else:
                        return win
        return None

    # =========================================================================
    # Lifecycle Execution: Launch & Startup Coordination
    # =========================================================================

    def launch(
        self,
        project_path: Optional[Union[str, Path]] = None,
        extra_args: Sequence[Union[str, Path]] = (),
        cwd: Optional[Union[str, Path]] = None,
        max_retries: int = 3,
        single_instance_mode: Optional[str] = None,
        reuse_existing: Optional[bool] = None,
        timeout: Optional[float] = None,
        headless: bool = False,
        enter_iec_mode: bool = True,
        lock_timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> CscapeLifecycleManager:
        """Launch Cscape.exe, dismiss splash, select IEC editor, and wait for main window.

        Enforces 'No second window' directive:
        - Single-instance check: if Cscape.exe is already running, connects to it
          or recycles it cleanly without ever spawning a second window.
        - Synchronized via system-wide Named Mutex and file lock to ensure concurrent launches never collide.
        - Robust retry handling to recover from transient file locks or OS startup errors.
        """
        if timeout is not None:
            self.launch_timeout = float(timeout)
        if single_instance_mode is not None:
            self.single_instance_mode = single_instance_mode.lower()
        if reuse_existing is not None:
            self.reuse_existing = bool(reuse_existing)
        if not enter_iec_mode:
            self.auto_select_iec = False

        if not self.executable_path or not self.executable_path.exists():
            raise CscapeLaunchError(
                f"Cscape executable not found. Configured path: {self.executable_path}"
            )

        cmd = [str(self.executable_path)]
        if project_path:
            p_path = Path(project_path).resolve()
            if not p_path.exists():
                raise FileNotFoundError(f"Project file not found: {p_path}")
            cmd.append(str(p_path))
        cmd.extend(str(a) for a in extra_args)

        work_dir = Path(cwd).resolve() if cwd else self.executable_path.parent

        effective_lock_timeout = float(lock_timeout) if lock_timeout is not None else max(self.launch_timeout, self.lock_timeout)

        # ---------------------------------------------------------------------
        # Single-Instance Synchronization Lock
        # ---------------------------------------------------------------------
        with self.lock.acquire_context(timeout=effective_lock_timeout):
            # Proactively assert clean exit status in registry
            set_cscape_exited_correctly(1)

            # -----------------------------------------------------------------
            # Single-Instance Enforcement ('No second window' directive)
            # -----------------------------------------------------------------
            existing_instances = self.find_running_instances()
            if existing_instances:
                logger.info("Single-instance check: found %d running Cscape.exe process(es)", len(existing_instances))
                if self.single_instance_mode in ("connect", "reuse") and self.reuse_existing and not project_path:
                    primary = existing_instances[0]
                    logger.info("Enforcing 'No second window': connecting to existing Cscape instance PID %s...", primary.pid)
                    connected = self._connect_to_existing_instance(primary, timeout=self.launch_timeout)
                    if connected:
                        logger.info("Connected to existing Cscape PID %s without spawning second window.", self.pid)
                        for orphan in existing_instances[1:]:
                            try:
                                orphan.kill()
                            except Exception:
                                pass
                        if self.pid:
                            self.lock.update_cscape_pid(self.pid)
                        return self
                    else:
                        logger.warning("Existing Cscape PID %s could not be connected; recycling cleanly...", primary.pid)
                        self.recycle_running_instances()
                        time.sleep(1.5)
                else:
                    logger.info("Enforcing 'No second window': recycling existing Cscape instance(s) before launch...")
                    self.recycle_running_instances()
                    time.sleep(1.5)

            last_error: Optional[Exception] = None
            for attempt in range(max_retries):
                # Proactively suppress crash recovery popup by asserting clean exit status in registry
                set_cscape_exited_correctly(1)

                # Ensure no orphan Cscape instance is lingering before spawn attempt
                if attempt > 0:
                    self.recycle_running_instances()

                logger.info("Launching Cscape (attempt %s/%s) using method '%s': %s", attempt + 1, max_retries, self.launch_method, " ".join(cmd))
                self.state = CscapeLifecycleState.STARTING
                self.start_time = time.time()

                if self.launch_method == "pywinauto":
                    try:
                        import pywinauto
                        with warnings.catch_warnings():
                            warnings.filterwarnings("ignore", category=UserWarning, module="pywinauto")
                            self.pywinauto_app = pywinauto.Application().start(" ".join(cmd), work_dir=str(work_dir))
                            self.pid = self.pywinauto_app.process
                            self.process = getattr(self.pywinauto_app, "_process", None)
                    except Exception as err:
                        self.state = CscapeLifecycleState.FAILED
                        raise CscapeLaunchError(f"Failed to start Cscape via pywinauto: {err}") from err
                else:
                    # Subprocess launch
                    try:
                        self.process = subprocess.Popen(
                            cmd,
                            cwd=str(work_dir),
                        )
                        self.pid = self.process.pid
                    except (PermissionError, OSError) as err:
                        logger.warning(
                            "Transient OS error launching Cscape (%s) on attempt %s/%s; recycling and retrying...",
                            err, attempt + 1, max_retries
                        )
                        last_error = CscapeLaunchError(f"Failed to launch Cscape subprocess: {err}")
                        self.recycle_running_instances()
                        time.sleep(1.0)
                        continue
                    except Exception as err:
                        self.state = CscapeLifecycleState.FAILED
                        raise CscapeLaunchError(f"Failed to launch Cscape subprocess: {err}") from err

                # Defer pywinauto connect until process is fully initialized, or when launch_method == 'pywinauto'
                if is_windows() and self.launch_method == "pywinauto" and self.pywinauto_app is None:
                    try:
                        import pywinauto
                        with warnings.catch_warnings():
                            warnings.filterwarnings("ignore", category=UserWarning, module="pywinauto")
                            self.pywinauto_app = pywinauto.Application().connect(process=self.pid)
                    except Exception as e:
                        logger.debug("pywinauto connect deferred or unavailable: %s", e)

                # Coordinate startup modals and wait for main window readiness
                try:
                    self._coordinate_startup(timeout=self.launch_timeout)
                    if self.pid:
                        self.lock.update_cscape_pid(self.pid)
                    return self
                except (CscapeLaunchError, CscapeStartupTimeoutError) as err:
                    last_error = err
                    logger.warning("Cscape launch attempt %s failed (%s); cleaning up before retry...", attempt + 1, err)
                    self.terminate(force_timeout=2.0)
                    if is_windows():
                        subprocess.run(["taskkill.exe", "/F", "/T", "/IM", "Cscape.exe"], capture_output=True)
                    if attempt < max_retries - 1:
                        time.sleep(2.5)

            if last_error is not None:
                raise last_error
            return self

    def start(
        self,
        project_path: Optional[Union[str, Path]] = None,
        extra_args: Sequence[Union[str, Path]] = (),
        cwd: Optional[Union[str, Path]] = None,
    ) -> CscapeLifecycleManager:
        """Alias for launch()."""
        return self.launch(project_path=project_path, extra_args=extra_args, cwd=cwd)

    def _coordinate_startup(self, timeout: float = 45.0) -> None:
        """Poll and handle splash dialog, editor type dialog, and main window ready state."""
        start_t = time.time()
        splash_dismissed = False
        editor_selected = False

        while time.time() - start_t < timeout:
            # Verify process is still alive
            if not self.is_running:
                if is_windows():
                    successors = self.find_running_instances()
                    if successors:
                        adopted = successors[0]
                        logger.info("Adopting successor Cscape process PID %s (original %s exited)", adopted.pid, self.pid)
                        self.pid = adopted.pid
                        self.process = None
                        self.exit_code = None
                        continue
                self.exit_code = self.process.poll() if self.process is not None else (self.exit_code or 1)
                self.state = CscapeLifecycleState.FAILED
                raise CscapeLaunchError(
                    f"Cscape terminated unexpectedly during startup with code {self.exit_code}"
                )

            # 0. Detect and auto-accept 'Allow' security/firewall modals
            if self.auto_accept_allow:
                self.handle_allow_dialogs(timeout=0.3)

            # 1. Detect and dismiss modal 'About Cscape' splash window (#32770)
            if self.auto_dismiss_splash and not splash_dismissed:
                splash = self.find_splash_dialog()
                if splash:
                    logger.info("Handling 'About Cscape' splash dialog (hwnd=%s)...", splash.hwnd)
                    if self.dismiss_splash_window(timeout=6.0):
                        splash_dismissed = True

            # 2. Detect and handle 'Select Editor Type' dialog (#32770)
            if self.auto_select_iec and not editor_selected:
                editor_dlg = self.find_editor_type_dialog()
                if editor_dlg:
                    logger.info("Handling 'Select Editor Type' dialog (hwnd=%s)...", editor_dlg.hwnd)
                    if self.handle_editor_type_dialog(radio_id=RADIO_ID_IEC_61131, timeout=6.0):
                        editor_selected = True

            # 3. Detect main Cscape window readiness:
            # - Must be visible and enabled (modal dialogs disable the main window)
            # - Must not have active modal #32770 dialogs or allow modals
            # - Splash and editor dialogs must be handled or confirmed settled
            main_win = self.find_main_cscape_window()
            if main_win and main_win.visible and main_win.enabled:
                has_active_modal = bool(
                    self.find_splash_dialog()
                    or self.find_editor_type_dialog()
                    or (self.auto_accept_allow and bool(self.find_allow_dialogs()))
                )
                if not has_active_modal:
                    # If connecting to an existing external instance, main window is already established
                    if self.process is None:
                        self.main_hwnd = main_win.hwnd
                        self.state = CscapeLifecycleState.READY
                        logger.info(
                            "Connected to existing Cscape main window: hwnd=%s, title='%s'",
                            self.main_hwnd,
                            main_win.title,
                        )
                        return

                    elapsed = time.time() - start_t
                    # In headless execution, splash (#32770) can take up to ~5-6s to appear.
                    # Ensure we don't prematurely declare readiness while splash is still pending.
                    splash_settled = (
                        (not self.auto_dismiss_splash)
                        or splash_dismissed
                        or ("[" in main_win.title)
                        or (elapsed >= 10.0)
                    )
                    editor_settled = (
                        (not self.auto_select_iec)
                        or editor_selected
                        or ("[" in main_win.title)
                        or (elapsed >= 10.0)
                        or self._is_editor_dialog_suppressed()
                    )

                    if splash_settled and editor_settled:
                        self.main_hwnd = main_win.hwnd
                        self.state = CscapeLifecycleState.READY
                        logger.info(
                            "Cscape main window fully ready: hwnd=%s, title='%s' (startup took %.2fs)",
                            self.main_hwnd,
                            main_win.title,
                            elapsed,
                        )
                        return

            time.sleep(0.2)

        self.state = CscapeLifecycleState.FAILED
        raise CscapeStartupTimeoutError(
            f"Timed out after {timeout}s waiting for Cscape main window to become ready (pid={self.pid})"
        )

    def wait_for_main_window(self, timeout: float = 30.0) -> int:
        """Explicitly wait until the main Cscape window is ready, returning its HWND."""
        if self.is_ready and self.main_hwnd is not None:
            return self.main_hwnd

        start_t = time.time()
        while time.time() - start_t < timeout:
            main_win = self.find_main_cscape_window()
            if main_win and main_win.visible and main_win.enabled:
                if not self.find_splash_dialog() and not self.find_editor_type_dialog():
                    self.main_hwnd = main_win.hwnd
                    self.state = CscapeLifecycleState.READY
                    return self.main_hwnd
            time.sleep(0.2)

        raise CscapeStartupTimeoutError(f"Main Cscape window did not become ready within {timeout}s")

    # =========================================================================
    # Lifecycle Termination: Graceful Shutdown & Force Kill
    # =========================================================================

    def close(
        self,
        graceful_timeout: Optional[float] = None,
        force_timeout: float = 3.0,
        force_kill_on_timeout: bool = True,
    ) -> bool:
        """Gracefully close Cscape via WM_CLOSE / Alt+F4, falling back to force kill on timeout.

        Args:
            graceful_timeout: Max seconds to wait for graceful exit. Defaults to self.shutdown_timeout.
            force_timeout: Max seconds to wait after force kill.
            force_kill_on_timeout: If True, invokes kill_process_tree on timeout.

        Returns:
            True if process terminated successfully.
        """
        if not self.is_running:
            self.state = CscapeLifecycleState.TERMINATED
            return True

        timeout = graceful_timeout if graceful_timeout is not None else self.shutdown_timeout
        logger.info("Initiating graceful shutdown of Cscape PID %s (timeout=%ss)", self.pid, timeout)
        self.state = CscapeLifecycleState.CLOSING

        # Step 0: Dismiss any lingering modal dialogs so they don't block main frame closing
        if is_windows():
            try:
                import win32gui
                for dlg in (self.find_splash_dialog(), self.find_editor_type_dialog()):
                    if dlg:
                        win32gui.PostMessage(dlg.hwnd, WM_CLOSE, 0, 0)
            except Exception:
                pass

        # Step 1: Send WM_CLOSE to main window if available
        if is_windows() and self.main_hwnd:
            try:
                import win32gui
                if win32gui.IsWindow(self.main_hwnd):
                    logger.info("Sending WM_CLOSE to main Cscape window hwnd=%s", self.main_hwnd)
                    win32gui.PostMessage(self.main_hwnd, WM_CLOSE, 0, 0)
            except Exception as err:
                logger.debug("Failed to send WM_CLOSE: %s", err)

        t0 = time.time()
        # Wait up to initial wait for clean exit after WM_CLOSE
        wait_initial = min(3.0, timeout * 0.4)
        while time.time() - t0 < wait_initial:
            if not self.is_running:
                logger.info("Cscape exited cleanly after WM_CLOSE in %.2fs", time.time() - t0)
                self._record_exit()
                return True
            time.sleep(0.2)

        # Step 2: Attempt SC_CLOSE / WM_CLOSE on all process windows
        if self.is_running and is_windows():
            logger.info("Cscape still running; sending SC_CLOSE / WM_CLOSE to all process windows...")
            try:
                import win32gui
                for win in self._enum_process_windows():
                    win32gui.PostMessage(win.hwnd, WM_SYSCOMMAND, SC_CLOSE, 0)
                    win32gui.PostMessage(win.hwnd, WM_CLOSE, 0, 0)
            except Exception:
                pass

            if self.pywinauto_app is not None:
                try:
                    top_win = self.pywinauto_app.top_window()
                    top_win.type_keys("%{F4}")
                except Exception:
                    pass

        # Wait remaining graceful timeout
        while time.time() - t0 < timeout:
            if not self.is_running:
                logger.info("Cscape exited gracefully in %.2fs", time.time() - t0)
                self._record_exit()
                return True
            time.sleep(0.2)

        # Step 3: Force termination if still running
        if force_kill_on_timeout and self.is_running:
            logger.warning("Cscape PID %s did not exit within %ss; force terminating...", self.pid, timeout)
            self.terminate(force_timeout=force_timeout)
            return not self.is_running

        if not self.is_running:
            self._record_exit()

        return not self.is_running

    def terminate(self, force_timeout: float = 3.0) -> bool:
        """Forcefully terminate the Cscape process and all child processes."""
        if not self.is_running:
            self.state = CscapeLifecycleState.TERMINATED
            return True

        logger.info("Force killing Cscape process tree PID %s", self.pid)
        if self.pid and is_windows():
            try:
                subprocess.run(
                    ["taskkill.exe", "/F", "/T", "/PID", str(self.pid)],
                    capture_output=True,
                    timeout=force_timeout,
                )
            except Exception as e:
                logger.debug("taskkill error: %s", e)

        if self.process is not None:
            try:
                self.process.kill()
                self.process.wait(timeout=min(1.0, force_timeout))
            except Exception:
                pass

        if self.pywinauto_app is not None:
            try:
                self.pywinauto_app.kill()
            except Exception:
                pass

        # Wait briefly to confirm process is no longer running
        if self.pid and is_windows():
            t_start = time.time()
            while time.time() - t_start < force_timeout:
                if not self.is_running:
                    break
                time.sleep(0.1)

        self._record_exit()
        return not self.is_running

    def _record_exit(self) -> None:
        """Record final process termination state."""
        if self.process is not None:
            try:
                self.process.wait(timeout=1.0)
            except Exception:
                pass
            self.exit_code = self.process.poll()
        if self.exit_code is None:
            self.exit_code = 0
        elif self.exit_code in (4294967295, -1) or self.exit_code >= 0x80000000 or self.exit_code < 0:
            self.exit_code = 1
        self.state = CscapeLifecycleState.TERMINATED
        self.main_hwnd = None
        self.splash_hwnd = None
        self.editor_dialog_hwnd = None
        set_cscape_exited_correctly(1)
        if hasattr(self, "lock") and self.lock is not None:
            try:
                self.lock.release()
                self.lock.break_lock()
            except Exception:
                pass
        logger.info("Cscape lifecycle ended. State: %s, Exit Code: %s", self.state, self.exit_code)

    # =========================================================================
    # Context Manager & Asynchronous Support
    # =========================================================================

    def __enter__(self) -> CscapeLifecycleManager:
        """Enter context manager: launch Cscape and wait for readiness."""
        self.launch()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit context manager: gracefully shutdown Cscape."""
        self.close()

    async def launch_async(
        self,
        project_path: Optional[Union[str, Path]] = None,
        extra_args: Sequence[Union[str, Path]] = (),
        cwd: Optional[Union[str, Path]] = None,
    ) -> CscapeLifecycleManager:
        """Asynchronously launch Cscape without blocking the event loop."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.launch(project_path=project_path, extra_args=extra_args, cwd=cwd),
        )

    async def close_async(
        self,
        graceful_timeout: Optional[float] = None,
        force_timeout: float = 3.0,
    ) -> bool:
        """Asynchronously close Cscape without blocking the event loop."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.close(graceful_timeout=graceful_timeout, force_timeout=force_timeout),
        )


def launch_cscape(
    project_path: Optional[Union[str, Path]] = None,
    timeout: float = 45.0,
    launch_method: str = "subprocess",
    single_instance_mode: str = "connect",
    reuse_existing: bool = True,
    auto_accept_allow: bool = True,
) -> CscapeLifecycleManager:
    """Convenience helper to launch Cscape and wait for readiness.

    Enforces 'No second window' directive:
    If Cscape.exe is already running, connects to it or recycles it cleanly
    without ever spawning a second window.
    """
    manager = CscapeLifecycleManager(
        launch_timeout=timeout,
        launch_method=launch_method,
        single_instance_mode=single_instance_mode,
        reuse_existing=reuse_existing,
        auto_accept_allow=auto_accept_allow,
    )
    return manager.launch(project_path=project_path)


def find_running_cscape_instances() -> list[Any]:
    """Module-level helper to find all running Cscape.exe processes."""
    return CscapeLifecycleManager.find_running_instances()


def recycle_running_cscape_instances(
    timeout: float = 5.0,
    lock_file: Optional[Union[str, Path]] = None,
    mutex_name: str = DEFAULT_MUTEX_NAME,
) -> int:
    """Module-level helper to recycle all running Cscape.exe processes cleanly."""
    return CscapeLifecycleManager.recycle_running_instances(
        timeout=timeout,
        lock_file=lock_file,
        mutex_name=mutex_name,
    )


def handle_allow_dialogs(timeout: float = 3.0, check_system_windows: bool = False) -> int:
    """Module-level helper to detect and auto-accept any 'Allow' security/firewall dialogs.

    Strictly restricted to Cscape PID and direct children.
    """
    check_system_windows = False
    mgr = CscapeLifecycleManager()
    return mgr.handle_allow_dialogs(timeout=timeout, check_system_windows=False)


def harvest_modal_dialog_diagnostics(hwnd: int) -> Dict[str, Any]:
    """Module-level helper to harvest structured diagnostics from a modal dialog."""
    mgr = CscapeLifecycleManager()
    return mgr.harvest_modal_dialog_diagnostics(hwnd)


def harvest_all_modal_diagnostics() -> List[Dict[str, Any]]:
    """Module-level helper to harvest diagnostics from all active modal dialogs."""
    mgr = CscapeLifecycleManager()
    return mgr.harvest_all_modal_diagnostics()


