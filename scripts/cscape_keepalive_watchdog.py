#!/usr/bin/env python3
"""Autonomous Keepalive Watchdog Supervisor Wrapper.

Invokes the hardened Cscape watchdog with:
- Continuous 24-hour supervisor duration (--duration 86400)
- 2-second polling frequency (--poll-interval 2.0)
- Fail-closed gate enforcement
- Persistent crash/restart telemetry in artifacts/logs/cscape_keepalive.log
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()
WORKSPACE_ROOT = Path(r"C:\Users\ArmandoSilva").resolve()
if str(HORNER_ROOT) not in sys.path:
    sys.path.insert(0, str(HORNER_ROOT))
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from scripts.watchdog_cscape_10min import (
    Cscape10MinWatchdog,
    DEFAULT_CSCAPE_PATH,
    DEFAULT_PROJECT_PATH,
    DEFAULT_LOG_PATH,
)


import ctypes
from ctypes import wintypes

MUTEX_NAME = r"Local\CscapeKeepaliveMutex"
ERROR_ALREADY_EXISTS = 183


def acquire_single_instance_mutex():
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE

    mutex_handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    last_error = kernel32.GetLastError()
    if last_error == ERROR_ALREADY_EXISTS:
        if mutex_handle:
            kernel32.CloseHandle(mutex_handle)
        return None
    return mutex_handle


def main() -> int:
    parser = argparse.ArgumentParser(description="Cscape Autonomous Keepalive Supervisor")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="Polling frequency in seconds")
    parser.add_argument("--duration", type=float, default=86400.0, help="Duration in seconds (default 24h)")
    parser.add_argument("--max-restarts", type=int, default=10000, help="Max restarts")
    parser.add_argument("--project-path", type=str, default=str(DEFAULT_PROJECT_PATH), help="Project path")
    args = parser.parse_args()

    mutex = acquire_single_instance_mutex()
    if mutex is None:
        print(f"[KEEPALIVE_MUTEX] Another instance of CscapeKeepaliveWatchdog is already running ({MUTEX_NAME}). Exiting cleanly.")
        return 0

    from scripts.watchdog_cscape_10min import KEEPALIVE_LOG
    try:
        watchdog = Cscape10MinWatchdog(
            cscape_path=DEFAULT_CSCAPE_PATH,
            project_path=Path(args.project_path),
            log_file=KEEPALIVE_LOG,
            target_duration_seconds=args.duration,
            poll_interval=args.poll_interval,
            max_restarts=args.max_restarts,
            initial_backoff=1.0,
            auto_close_on_complete=False,
        )
        return watchdog.run()
    finally:
        if mutex:
            ctypes.windll.kernel32.CloseHandle(mutex)


if __name__ == "__main__":
    sys.exit(main())

