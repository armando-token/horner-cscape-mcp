"""Test suite for Horner Cscape 10.2 Single-Instance Process Enforcement.

Verifies:
1. Clean single-instance state and process inspection.
2. Win32 Named Mutex and file lock acquisition/release semantics.
3. In-process and cross-process concurrency serialization (no launch collisions).
4. Stale lock detection and automatic recovery.
5. CscapeExitedCorrectly registry assertion (DWORD=1).
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.cscape.lifecycle import (
    CscapeLifecycleManager,
    CscapeLifecycleState,
    CscapeLockError,
    CscapeSingleInstanceLock,
    acquire_single_instance_lock,
    set_cscape_exited_correctly,
    verify_cscape_exited_correctly,
    DEFAULT_LOCK_FILE,
    DEFAULT_MUTEX_NAME,
)


class TestSingleInstanceLockBasics:
    """Test fundamental lock file and Win32 mutex operations."""

    def test_acquire_and_release(self, tmp_path: Path):
        lock_file = tmp_path / "test_instance.lock"
        mutex_name = f"Local\\TestMutex_Basic_{os.getpid()}_{int(time.time())}"

        lock = CscapeSingleInstanceLock(lock_file=lock_file, mutex_name=mutex_name, timeout=5.0)
        assert not lock.is_locked()

        # Acquire
        assert lock.acquire() is True
        assert lock.is_locked()
        assert lock_file.exists()

        # Check lock file metadata
        info = lock.get_lock_info()
        assert info is not None
        assert info["pid"] == os.getpid()
        assert "acquired_at" in info

        # Release
        lock.release()
        assert not lock.is_locked()
        assert not lock_file.exists()

    def test_context_manager(self, tmp_path: Path):
        lock_file = tmp_path / "test_ctx.lock"
        mutex_name = f"Local\\TestMutex_Ctx_{os.getpid()}_{int(time.time())}"

        lock = CscapeSingleInstanceLock(lock_file=lock_file, mutex_name=mutex_name, timeout=5.0)

        with lock:
            assert lock.is_locked()
            assert lock_file.exists()

        assert not lock.is_locked()
        assert not lock_file.exists()

    def test_reentrant_acquisition(self, tmp_path: Path):
        lock_file = tmp_path / "test_reentrant.lock"
        mutex_name = f"Local\\TestMutex_Reentrant_{os.getpid()}_{int(time.time())}"

        lock = CscapeSingleInstanceLock(lock_file=lock_file, mutex_name=mutex_name, timeout=5.0)

        # Depth 1
        with lock:
            assert lock._acquire_depth == 1
            # Depth 2
            with lock:
                assert lock._acquire_depth == 2
                # Depth 3
                assert lock.acquire() is True
                assert lock._acquire_depth == 3
                lock.release()
                assert lock._acquire_depth == 2
            assert lock._acquire_depth == 1
        assert lock._acquire_depth == 0
        assert not lock.is_locked()

    def test_update_cscape_pid(self, tmp_path: Path):
        lock_file = tmp_path / "test_update_pid.lock"
        mutex_name = f"Local\\TestMutex_UpdatePid_{os.getpid()}_{int(time.time())}"

        lock = CscapeSingleInstanceLock(lock_file=lock_file, mutex_name=mutex_name, timeout=5.0)
        with lock:
            lock.update_cscape_pid(99999)
            info = lock.get_lock_info()
            assert info is not None
            assert info.get("cscape_pid") == 99999


class TestLockConcurrency:
    """Test thread and process concurrency to guarantee zero launch collisions."""

    def test_thread_concurrency(self, tmp_path: Path):
        lock_file = tmp_path / "test_thread.lock"
        mutex_name = f"Local\\TestMutex_Thread_{os.getpid()}_{int(time.time())}"

        shared_lock = CscapeSingleInstanceLock(lock_file=lock_file, mutex_name=mutex_name, timeout=5.0)
        execution_order = []
        concurrency_violations = []
        active_threads = 0
        lock_counter = threading.Lock()

        def worker(worker_id: int):
            nonlocal active_threads
            with shared_lock:
                with lock_counter:
                    active_threads += 1
                    if active_threads > 1:
                        concurrency_violations.append(active_threads)
                execution_order.append(f"start_{worker_id}")
                time.sleep(0.1)
                execution_order.append(f"end_{worker_id}")
                with lock_counter:
                    active_threads -= 1

        t1 = threading.Thread(target=worker, args=(1,))
        t2 = threading.Thread(target=worker, args=(2,))

        t1.start()
        t2.start()
        t1.join(timeout=5.0)
        t2.join(timeout=5.0)

        assert len(concurrency_violations) == 0, f"Concurrency violations: {concurrency_violations}"
        assert len(execution_order) == 4
        # Verify one finished before the other started
        assert execution_order[1].startswith("end_")
        assert execution_order[2].startswith("start_")

    def test_cross_process_collision_prevention(self, tmp_path: Path):
        lock_file = tmp_path / "test_proc.lock"
        mutex_name = f"Local\\TestMutex_Proc_{os.getpid()}_{int(time.time())}"

        # Script that holds lock for 1.2 seconds
        holder_script = f"""
import sys, time
sys.path.insert(0, '.')
from src.cscape.lifecycle import CscapeSingleInstanceLock

lock = CscapeSingleInstanceLock(lock_file=r'{lock_file}', mutex_name=r'{mutex_name}', timeout=5.0)
with lock:
    print('LOCKED', flush=True)
    time.sleep(1.2)
print('UNLOCKED', flush=True)
"""
        proc = subprocess.Popen(
            [sys.executable, "-c", holder_script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        try:
            # Wait until child acquires lock
            first_line = proc.stdout.readline().strip()
            assert first_line == "LOCKED"

            # Attempt 1: Immediate acquisition should time out and fail
            competing_lock = CscapeSingleInstanceLock(
                lock_file=lock_file,
                mutex_name=mutex_name,
                timeout=0.2,
            )
            with pytest.raises(CscapeLockError):
                competing_lock.acquire(timeout=0.2)

            # Attempt 2: Acquisition with sufficient timeout waits and succeeds
            competing_lock_patient = CscapeSingleInstanceLock(
                lock_file=lock_file,
                mutex_name=mutex_name,
                timeout=5.0,
            )
            acquired = competing_lock_patient.acquire(timeout=3.0)
            assert acquired is True
            competing_lock_patient.release()

        finally:
            proc.communicate(timeout=3.0)


class TestStaleLockRecovery:
    """Test that stale locks from dead processes are safely detected and reclaimed."""

    def test_stale_lock_detection_and_reclaim(self, tmp_path: Path):
        lock_file = tmp_path / "test_stale.lock"
        mutex_name = f"Local\\TestMutex_Stale_{os.getpid()}_{int(time.time())}"

        # Write lock info with a guaranteed dead PID (e.g. 999999)
        dead_pid = 999999
        stale_info = {
            "pid": dead_pid,
            "cscape_pid": None,
            "acquired_at": time.time() - 100,
            "mutex_name": mutex_name,
            "lock_file": str(lock_file),
        }
        with open(lock_file, "w", encoding="utf-8") as f:
            json.dump(stale_info, f)

        lock = CscapeSingleInstanceLock(lock_file=lock_file, mutex_name=mutex_name, timeout=5.0)
        assert lock.is_stale() is True

        # Acquiring should automatically detect stale lock, break it, and succeed
        assert lock.acquire(timeout=3.0) is True
        assert lock.is_locked() is True

        info = lock.get_lock_info()
        assert info["pid"] == os.getpid()
        lock.release()


class TestRegistryVerification:
    """Verify registry key HKCU\\Software\\Horner_Electric\\Cscape\\Setup\\CscapeExitedCorrectly = 1."""

    def test_set_and_verify_cscape_exited_correctly(self):
        # Assert clean exit status
        success = set_cscape_exited_correctly(1)
        assert success is True

        # Verify registry key
        verified = verify_cscape_exited_correctly()
        assert verified is True


class TestLifecycleManagerSingleInstanceIntegration:
    """Verify CscapeLifecycleManager integrates single-instance lock."""

    def test_manager_has_lock(self, tmp_path: Path):
        lock_file = tmp_path / "lifecycle_inst.lock"
        mgr = CscapeLifecycleManager(lock_file=lock_file)
        assert mgr.lock is not None
        assert mgr.lock.lock_file == lock_file

    def test_recycle_running_instances_cleans_lock_and_asserts_registry(self, tmp_path: Path):
        lock_file = tmp_path / "recycle_test.lock"
        lock_file.write_text("dummy", encoding="utf-8")

        with patch.object(CscapeLifecycleManager, "find_running_instances", return_value=[]), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=b"SUCCESS: PID 1234 terminated")
            count = CscapeLifecycleManager.recycle_running_instances(timeout=1.0, lock_file=lock_file)
            assert isinstance(count, int)
            assert not lock_file.exists()
            assert verify_cscape_exited_correctly() is True
