import sys
import pytest

class OfflinePlugin:
    def pytest_sessionstart(self, session):
        import src.cscape.gate as g
        g.get_gate_status = lambda: {'ready_for_tests': False, 'status': 'FAIL_CLOSED_GATE_OFFLINE', 'reason': 'Audit offline simulation'}

if __name__ == "__main__":
    targets = [f"tests/test_step{i}_visible_cscape_gui_driver.py" for i in range(156, 171)]
    ret = pytest.main(targets + ["-v"], plugins=[OfflinePlugin()])
    print("Pytest return code:", ret)
    sys.exit(ret)
