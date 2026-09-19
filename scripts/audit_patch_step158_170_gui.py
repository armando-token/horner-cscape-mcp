import glob
import re

for step in range(158, 171):
    pattern = f'tests/test_step{step}_visible_cscape_gui_driver.py'
    matches = glob.glob(pattern)
    assert len(matches) == 1, f'Expected 1 match for {pattern}, got {matches}'
    filepath = matches[0]
    
    with open(filepath, 'r', encoding='utf-8') as f:
        src = f.read()
    
    # Replace test_task4
    target_pattern = r'def test_task4_execution_and_checkpoint_verification\(self\):.*'
    new_task4 = """def test_task4_execution_and_checkpoint_verification(self):
        gate = get_gate_status()
        live_pid = gate.get("pid")
        if not gate.get("ready_for_tests") or not live_pid or not psutil.pid_exists(live_pid):
            pytest.skip(f"Live Cscape gate not ready or offline: status='{gate.get('status')}', reason='{gate.get('reason')}'")

        for cp in CHECKPOINT_PATHS:
            assert cp.exists(), f"Missing checkpoint: {cp}"
            data = json.loads(cp.read_text(encoding="utf-8"))
            assert data.get("status") == "PASSED"
            assert data.get("step") == STEP_NUM
            assert data.get("live_gui_compile_clean") is True
            assert "checkpoint_sha256" in data

        for lp in LOG_PATHS:
            assert lp.exists(), f"Missing log: {lp}"
            data = json.loads(lp.read_text(encoding="utf-8"))
            assert data.get("status") == "PASSED"
            assert data.get("step") == STEP_NUM
            assert data.get("gui_compilation", {}).get("error_count") == 0
            assert data.get("gui_compilation", {}).get("warning_count") == 0

        for sp in SCREENSHOT_PATHS:
            assert sp.exists(), f"Missing screenshot: {sp}"
            assert sp.stat().st_size > 500, f"Screenshot file too small: {sp.stat().st_size}"
""".replace("STEP_NUM", str(step))
    
    src = re.sub(target_pattern, new_task4, src, flags=re.DOTALL)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(src)
    print(f'Updated {filepath}')
