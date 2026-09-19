import glob
import re

for step in range(158, 171):
    pattern = f'tests/test_step{step}_mcp_*.py'
    matches = glob.glob(pattern)
    assert len(matches) == 1, f'Expected 1 match for {pattern}, got {matches}'
    filepath = matches[0]
    
    with open(filepath, 'r', encoding='utf-8') as f:
        src = f.read()
    
    # 1. Update import
    if 'CscapeLivenessGateError' not in src:
        src = src.replace(
            'from src.cscape.gate import get_gate_status, assert_cscape_live',
            'from src.cscape.gate import get_gate_status, assert_cscape_live, CscapeLivenessGateError'
        )
    
    # 2. Update test_full_step
    target_match = re.search(r'(async def test_full_step' + str(step) + r'_[a-zA-Z0-9_]+\(self\):\s*\n)(\s+report = await run_step' + str(step) + r'_mcp_simulation\(\))', src)
    if target_match:
        old_block = target_match.group(0)
        def_line = target_match.group(1)
        new_block = (
            def_line +
            '        gate = get_gate_status()\n'
            '        live_pid = gate.get("pid")\n'
            '        if not gate.get("ready_for_tests") or not live_pid or not psutil.pid_exists(live_pid):\n'
            '            pytest.skip(f"Live Cscape gate not ready or offline: status=\'{gate.get(\"status\")}\', reason=\'{gate.get(\"reason\")}\'")\n'
            '        try:\n'
            f'            report = await run_step{step}_mcp_simulation()\n'
            '        except CscapeLivenessGateError as e:\n'
            '            pytest.skip(f"Live Cscape gate not ready or offline: {e}")'
        )
        src = src.replace(old_block, new_block)
        print(f'Updated {filepath}')
    else:
        print('Could not find target_match for', filepath)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(src)
