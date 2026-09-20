"""Documentation Link Sanitizer and Linkage Verifier.

Audits docs/ directory, sanitizes hardcoded machine paths,
replaces external user Downloads links with repo-relative paths,
and ensures professional consistency across documentation.
"""
import os
import re

REPO_ROOT = r'C:\HornerAI\horner-cscape-mcp'
DOCS_DIR = os.path.join(REPO_ROOT, 'docs')

def replace_in_file(path, replacements):
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    orig = content
    for old, new in replacements:
        content = content.replace(old, new)
    if content != orig:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f'Updated: {os.path.relpath(path, REPO_ROOT)}')
    else:
        print(f'No changes: {os.path.relpath(path, REPO_ROOT)}')

def run_sanitization():
    # 1. CORE_08_09_10_RUNTIME_GAPS_AND_ROADMAP.md
    replace_in_file(
        os.path.join(DOCS_DIR, 'CORE_08_09_10_RUNTIME_GAPS_AND_ROADMAP.md'),
        [
            ('[`SUPERVISOR_OFFLINE_ACCEPTANCE.md`](file:///C:/Users/ArmandoSilva/Downloads/SUPERVISOR_OFFLINE_ACCEPTANCE.md)', '[`SUPERVISOR_OFFLINE_ACCEPTANCE.md`](SUPERVISOR_OFFLINE_ACCEPTANCE.md)'),
            ('[`FB_ModbusScaleQuality.st`](file:///C:/Users/ArmandoSilva/Downloads/pous/FB_ModbusScaleQuality.st)', '[`FB_ModbusScaleQuality.st`](../artifacts/projects/TankLevel_P5_Dedicated/pous/FB_ModbusScaleQuality.st)'),
            ('[`modbus_protocol_inventory.json`](file:///C:/Users/ArmandoSilva/Downloads/modbus_protocol_inventory.json)', '[`modbus_protocol_inventory.json`](../modbus_protocol_inventory.json)'),
            ('[`P7_MANUAL_COMMISSIONING_PROCEDURE.md`](file:///C:/Users/ArmandoSilva/Downloads/P7_MANUAL_COMMISSIONING_PROCEDURE.md)', '[`P7_MANUAL_COMMISSIONING_PROCEDURE.md`](P7_MANUAL_COMMISSIONING_PROCEDURE.md)'),
            ('[`P7_MANUAL_LOAD_CHECKLIST.md`](file:///C:/Users/ArmandoSilva/Downloads/P7_MANUAL_LOAD_CHECKLIST.md)', '[`P7_MANUAL_LOAD_CHECKLIST.md`](P7_MANUAL_LOAD_CHECKLIST.md)'),
            ('[`CORE_08_MODBUS_CONVERSION_EXAMPLE.md`](file:///C:/Users/ArmandoSilva/Downloads/CORE_08_MODBUS_CONVERSION_EXAMPLE.md)', '[`CORE_08_MODBUS_CONVERSION_EXAMPLE.md`](CORE_08_MODBUS_CONVERSION_EXAMPLE.md)'),
            ('[`CORE_08_09_10_RUNTIME_GAPS_AND_ROADMAP.md`](file:///C:/Users/ArmandoSilva/Downloads/CORE_08_09_10_RUNTIME_GAPS_AND_ROADMAP.md)', '[`CORE_08_09_10_RUNTIME_GAPS_AND_ROADMAP.md`](CORE_08_09_10_RUNTIME_GAPS_AND_ROADMAP.md)'),
        ]
    )

    # 2. cscape_save_failed_diagnosis.md
    replace_in_file(
        os.path.join(DOCS_DIR, 'cscape_save_failed_diagnosis.md'),
        [
            ('[`Downloads/cscape_save_failed_reproduction.png`](file:///C:/Users/ArmandoSilva/Downloads/cscape_save_failed_reproduction.png)', '[`ops/artifacts/cscape_save_failed_reproduction.png`](../ops/artifacts/cscape_save_failed_reproduction.png)'),
            ('[`Downloads/cscape_save_failed_evidence.json`](file:///C:/Users/ArmandoSilva/Downloads/cscape_save_failed_evidence.json)', '[`ops/artifacts/cscape_save_failed_evidence.json`](../ops/artifacts/cscape_save_failed_evidence.json)'),
            ('[`Downloads/cscape_save_failed_diagnosis.md`](file:///C:/Users/ArmandoSilva/Downloads/cscape_save_failed_diagnosis.md)', '[`docs/cscape_save_failed_diagnosis.md`](cscape_save_failed_diagnosis.md)'),
            ('[`Downloads/save_failed_caveat.txt`](file:///C:/Users/ArmandoSilva/Downloads/save_failed_caveat.txt)', '[`ops/artifacts/save_failed_caveat.txt`](../ops/artifacts/save_failed_caveat.txt)'),
        ]
    )

    # 3. FINAL_REPORT.md
    replace_in_file(
        os.path.join(DOCS_DIR, 'FINAL_REPORT.md'),
        [
            ('[`C:\\Program Files (x86)\\Cscape 10.2\\Cscape.exe`](file:///C:/Program%20Files%20(x86)/Cscape%2010.2/Cscape.exe)', '`C:\\Program Files (x86)\\Cscape 10.2\\Cscape.exe`'),
        ]
    )

    # 4. HANDOFF_INDEX.md
    replace_in_file(
        os.path.join(DOCS_DIR, 'HANDOFF_INDEX.md'),
        [
            ('[`Downloads/cscape_save_failed_diagnosis.md`](file:///C:/Users/ArmandoSilva/Downloads/cscape_save_failed_diagnosis.md)', '[`docs/cscape_save_failed_diagnosis.md`](cscape_save_failed_diagnosis.md)'),
        ]
    )

    # 5. HOW_TO_TEST_PHYSICAL_PLC.md
    replace_in_file(
        os.path.join(DOCS_DIR, 'HOW_TO_TEST_PHYSICAL_PLC.md'),
        [
            ('[`P7_MANUAL_COMMISSIONING_PROCEDURE.md`](file:///C:/Users/ArmandoSilva/Downloads/P7_MANUAL_COMMISSIONING_PROCEDURE.md)', '[`P7_MANUAL_COMMISSIONING_PROCEDURE.md`](P7_MANUAL_COMMISSIONING_PROCEDURE.md)'),
            ('[`P7_MANUAL_LOAD_CHECKLIST.md`](file:///C:/Users/ArmandoSilva/Downloads/P7_MANUAL_LOAD_CHECKLIST.md)', '[`P7_MANUAL_LOAD_CHECKLIST.md`](P7_MANUAL_LOAD_CHECKLIST.md)'),
            ('[`SUPERVISOR_OFFLINE_ACCEPTANCE.md`](file:///C:/Users/ArmandoSilva/Downloads/SUPERVISOR_OFFLINE_ACCEPTANCE.md)', '[`SUPERVISOR_OFFLINE_ACCEPTANCE.md`](SUPERVISOR_OFFLINE_ACCEPTANCE.md)'),
            ('[`modbus_protocol_inventory.json`](file:///C:/Users/ArmandoSilva/Downloads/modbus_protocol_inventory.json)', '[`modbus_protocol_inventory.json`](../modbus_protocol_inventory.json)'),
        ]
    )

    # 6. P7_COMMISSIONING_PREP_MANIFEST.md
    replace_in_file(
        os.path.join(DOCS_DIR, 'P7_COMMISSIONING_PREP_MANIFEST.md'),
        [
            ('[`SUPERVISOR_OFFLINE_ACCEPTANCE.md`](file:///C:/Users/ArmandoSilva/Downloads/SUPERVISOR_OFFLINE_ACCEPTANCE.md)', '[`SUPERVISOR_OFFLINE_ACCEPTANCE.md`](SUPERVISOR_OFFLINE_ACCEPTANCE.md)'),
            ('[`offline_evidence_bundle_v1.0.0.zip`](file:///C:/Users/ArmandoSilva/Downloads/offline_evidence_bundle_v1.0.0.zip)', '[`offline_evidence_bundle_v1.0.0.zip`](../offline_evidence_bundle_v1.0.0.zip)'),
            ('[`P7_MANUAL_COMMISSIONING_PROCEDURE.md`](file:///C:/Users/ArmandoSilva/Downloads/P7_MANUAL_COMMISSIONING_PROCEDURE.md)', '[`P7_MANUAL_COMMISSIONING_PROCEDURE.md`](P7_MANUAL_COMMISSIONING_PROCEDURE.md)'),
            ('[`P7_MANUAL_LOAD_CHECKLIST.md`](file:///C:/Users/ArmandoSilva/Downloads/P7_MANUAL_LOAD_CHECKLIST.md)', '[`P7_MANUAL_LOAD_CHECKLIST.md`](P7_MANUAL_LOAD_CHECKLIST.md)'),
        ]
    )

    # 7. P7_MANUAL_LOAD_CHECKLIST.md
    replace_in_file(
        os.path.join(DOCS_DIR, 'P7_MANUAL_LOAD_CHECKLIST.md'),
        [
            ('[`P7_MANUAL_COMMISSIONING_PROCEDURE.md`](file:///C:/Users/ArmandoSilva/Downloads/P7_MANUAL_COMMISSIONING_PROCEDURE.md)', '[`P7_MANUAL_COMMISSIONING_PROCEDURE.md`](P7_MANUAL_COMMISSIONING_PROCEDURE.md)'),
            ('[`SUPERVISOR_OFFLINE_ACCEPTANCE.md`](file:///C:/Users/ArmandoSilva/Downloads/SUPERVISOR_OFFLINE_ACCEPTANCE.md)', '[`SUPERVISOR_OFFLINE_ACCEPTANCE.md`](SUPERVISOR_OFFLINE_ACCEPTANCE.md)'),
            ('[`offline_evidence_bundle_v1.0.0.zip`](file:///C:/Users/ArmandoSilva/Downloads/offline_evidence_bundle_v1.0.0.zip)', '[`offline_evidence_bundle_v1.0.0.zip`](../offline_evidence_bundle_v1.0.0.zip)'),
            ('[`offline_evidence_bundle_manifest.md`](file:///C:/Users/ArmandoSilva/Downloads/offline_evidence_bundle_manifest.md)', '[`offline_evidence_bundle_manifest.md`](../ops/artifacts/offline_evidence_bundle_manifest.md)'),
            ('[`mj1_devices_scan_list_state_evidence.md`](file:///C:/Users/ArmandoSilva/Downloads/mj1_devices_scan_list_state_evidence.md)', '[`mj1_devices_scan_list_state_evidence.md`](../ops/artifacts/mj1_devices_scan_list_state_evidence.md)'),
            ('[`tanklevel_p5_native_reopen_proof_evidence.md`](file:///C:/Users/ArmandoSilva/Downloads/tanklevel_p5_native_reopen_proof_evidence.md)', '[`tanklevel_p5_native_reopen_proof_evidence.md`](../ops/artifacts/tanklevel_p5_native_reopen_proof_evidence.md)'),
            ('[`modbus_protocol_inventory.json`](file:///C:/Users/ArmandoSilva/Downloads/modbus_protocol_inventory.json)', '[`modbus_protocol_inventory.json`](../modbus_protocol_inventory.json)'),
        ]
    )

    # 8. PLAN_V3_OFFLINE_GAPS_AND_RESOLUTION.md
    replace_in_file(
        os.path.join(DOCS_DIR, 'PLAN_V3_OFFLINE_GAPS_AND_RESOLUTION.md'),
        [
            ('[`SUPERVISOR_OFFLINE_ACCEPTANCE.md`](file:///C:/Users/ArmandoSilva/Downloads/SUPERVISOR_OFFLINE_ACCEPTANCE.md)', '[`SUPERVISOR_OFFLINE_ACCEPTANCE.md`](SUPERVISOR_OFFLINE_ACCEPTANCE.md)'),
            ('[`P7_MANUAL_COMMISSIONING_PROCEDURE.md`](file:///C:/Users/ArmandoSilva/Downloads/P7_MANUAL_COMMISSIONING_PROCEDURE.md)', '[`P7_MANUAL_COMMISSIONING_PROCEDURE.md`](P7_MANUAL_COMMISSIONING_PROCEDURE.md)'),
            ('[`P7_MANUAL_LOAD_CHECKLIST.md`](file:///C:/Users/ArmandoSilva/Downloads/P7_MANUAL_LOAD_CHECKLIST.md)', '[`P7_MANUAL_LOAD_CHECKLIST.md`](P7_MANUAL_LOAD_CHECKLIST.md)'),
            ('[`modbus_protocol_inventory.json`](file:///C:/Users/ArmandoSilva/Downloads/modbus_protocol_inventory.json)', '[`modbus_protocol_inventory.json`](../modbus_protocol_inventory.json)'),
        ]
    )

    # 9. SCAN_LIST_EVIDENCE_VALIDATION_GUIDE.md
    replace_in_file(
        os.path.join(DOCS_DIR, 'SCAN_LIST_EVIDENCE_VALIDATION_GUIDE.md'),
        [
            (r'[`RULE[C:\Users\ArmandoSilva\AGENTS.md]`](file:///C:/Users/ArmandoSilva/AGENTS.md)', '[`AGENTS.md`](../AGENTS.md)'),
            ('[`Downloads/mj1_devices_scan_evidence.json`](file:///C:/Users/ArmandoSilva/Downloads/mj1_devices_scan_evidence.json)', '[`ops/artifacts/mj1_devices_scan_evidence.json`](../ops/artifacts/mj1_devices_scan_evidence.json)'),
            ('[`Downloads/mj1_devices_scan_evidence.md`](file:///C:/Users/ArmandoSilva/Downloads/mj1_devices_scan_evidence.md)', '[`ops/artifacts/mj1_devices_scan_evidence.md`](../ops/artifacts/mj1_devices_scan_evidence.md)'),
            ('[`Downloads/mj1_scan_list_validation_evidence.json`](file:///C:/Users/ArmandoSilva/Downloads/mj1_scan_list_validation_evidence.json)', '[`ops/artifacts/mj1_scan_list_validation_evidence.json`](../ops/artifacts/mj1_scan_list_validation_evidence.json)'),
            ('[`Downloads/mj1_scan_list_validation_evidence.md`](file:///C:/Users/ArmandoSilva/Downloads/mj1_scan_list_validation_evidence.md)', '[`ops/artifacts/mj1_scan_list_validation_evidence.md`](../ops/artifacts/mj1_scan_list_validation_evidence.md)'),
        ]
    )

    # 10. SUPERVISOR_OFFLINE_ACCEPTANCE.md
    replace_in_file(
        os.path.join(DOCS_DIR, 'SUPERVISOR_OFFLINE_ACCEPTANCE.md'),
        [
            ('[`Downloads/p4_selective_edit_evidence.json`](file:///C:/Users/ArmandoSilva/Downloads/p4_selective_edit_evidence.json)', '[`ops/artifacts/p4_selective_edit_evidence.json`](../ops/artifacts/p4_selective_edit_evidence.json)'),
            ('[`Downloads/p6_external_handoff_evidence.json`](file:///C:/Users/ArmandoSilva/Downloads/p6_external_handoff_evidence.json)', '[`ops/artifacts/p6_external_handoff_evidence.json`](../ops/artifacts/p6_external_handoff_evidence.json)'),
            ('[`Downloads/p6_second_context_handoff_evidence.json`](file:///C:/Users/ArmandoSilva/Downloads/p6_second_context_handoff_evidence.json)', '[`ops/artifacts/p6_second_context_handoff_evidence.json`](../ops/artifacts/p6_second_context_handoff_evidence.json)'),
            ('[`Downloads/mj1_scan_list_validation_evidence.json`](file:///C:/Users/ArmandoSilva/Downloads/mj1_scan_list_validation_evidence.json)', '[`ops/artifacts/mj1_scan_list_validation_evidence.json`](../ops/artifacts/mj1_scan_list_validation_evidence.json)'),
            ('[`Downloads/mj1_scan_list_inspection_evidence.json`](file:///C:/Users/ArmandoSilva/Downloads/mj1_scan_list_inspection_evidence.json)', '[`ops/artifacts/mj1_scan_list_inspection_evidence.json`](../ops/artifacts/mj1_scan_list_inspection_evidence.json)'),
            ('[`Downloads/mj1_scan_list_reconciliation_evidence.json`](file:///C:/Users/ArmandoSilva/Downloads/mj1_scan_list_reconciliation_evidence.json)', '[`ops/artifacts/mj1_scan_list_reconciliation_evidence.json`](../ops/artifacts/mj1_scan_list_reconciliation_evidence.json)'),
            ('[`Downloads/offline_evidence_bundle_v1.0.0.zip`](file:///C:/Users/ArmandoSilva/Downloads/offline_evidence_bundle_v1.0.0.zip)', '[`offline_evidence_bundle_v1.0.0.zip`](../offline_evidence_bundle_v1.0.0.zip)'),
            ('[`Downloads/offline_evidence_bundle_manifest.json`](file:///C:/Users/ArmandoSilva/Downloads/offline_evidence_bundle_manifest.json)', '[`ops/artifacts/offline_evidence_bundle_manifest.json`](../ops/artifacts/offline_evidence_bundle_manifest.json)'),
            ('[`Downloads/offline_evidence_bundle_manifest.md`](file:///C:/Users/ArmandoSilva/Downloads/offline_evidence_bundle_manifest.md)', '[`ops/artifacts/offline_evidence_bundle_manifest.md`](../ops/artifacts/offline_evidence_bundle_manifest.md)'),
            ('[`Downloads/modbus_register_scaling_iec_bridge_evidence.json`](file:///C:/Users/ArmandoSilva/Downloads/modbus_register_scaling_iec_bridge_evidence.json)', '[`ops/artifacts/modbus_register_scaling_iec_bridge_evidence.json`](../ops/artifacts/modbus_register_scaling_iec_bridge_evidence.json)'),
            ('[`Downloads/modbus_register_scaling_iec_bridge_evidence.md`](file:///C:/Users/ArmandoSilva/Downloads/modbus_register_scaling_iec_bridge_evidence.md)', '[`ops/artifacts/modbus_register_scaling_iec_bridge_evidence.md`](../ops/artifacts/modbus_register_scaling_iec_bridge_evidence.md)'),
            ('[`tests/test_modbus_register_scaling_bridge.py`](file:///C:/Users/ArmandoSilva/tests/test_modbus_register_scaling_bridge.py)', '[`tests/test_modbus_register_scaling_bridge.py`](../tests/test_modbus_register_scaling_bridge.py)'),
            ('[`Downloads/tanklevel_p5_native_reopen_proof_evidence.json`](file:///C:/Users/ArmandoSilva/Downloads/tanklevel_p5_native_reopen_proof_evidence.json)', '[`ops/artifacts/tanklevel_p5_native_reopen_proof_evidence.json`](../ops/artifacts/tanklevel_p5_native_reopen_proof_evidence.json)'),
            ('[`Downloads/tanklevel_p5_native_reopen_proof_evidence.md`](file:///C:/Users/ArmandoSilva/Downloads/tanklevel_p5_native_reopen_proof_evidence.md)', '[`ops/artifacts/tanklevel_p5_native_reopen_proof_evidence.md`](../ops/artifacts/tanklevel_p5_native_reopen_proof_evidence.md)'),
            ('[`Downloads/tanklevel_p5_native_reopen_proof.png`](file:///C:/Users/ArmandoSilva/Downloads/tanklevel_p5_native_reopen_proof.png)', '[`ops/artifacts/tanklevel_p5_native_reopen_proof.png`](../ops/artifacts/tanklevel_p5_native_reopen_proof.png)'),
            ('[`P7_MANUAL_LOAD_CHECKLIST.md`](file:///C:/Users/ArmandoSilva/Downloads/P7_MANUAL_LOAD_CHECKLIST.md)', '[`P7_MANUAL_LOAD_CHECKLIST.md`](P7_MANUAL_LOAD_CHECKLIST.md)'),
            ('[`P7_MANUAL_COMMISSIONING_PROCEDURE.md`](file:///C:/Users/ArmandoSilva/Downloads/P7_MANUAL_COMMISSIONING_PROCEDURE.md)', '[`P7_MANUAL_COMMISSIONING_PROCEDURE.md`](P7_MANUAL_COMMISSIONING_PROCEDURE.md)'),
        ]
    )

    # 11. CORE_08_09_10_FIELD_VERIFICATION_MATRIX.md
    replace_in_file(
        os.path.join(DOCS_DIR, 'CORE_08_09_10_FIELD_VERIFICATION_MATRIX.md'),
        [
            ('[`SUPERVISOR_OFFLINE_ACCEPTANCE.md`](file:///C:/Users/ArmandoSilva/Downloads/SUPERVISOR_OFFLINE_ACCEPTANCE.md)', '[`SUPERVISOR_OFFLINE_ACCEPTANCE.md`](SUPERVISOR_OFFLINE_ACCEPTANCE.md)'),
        ]
    )

    # 12. AVANCE_2026-09-17.md in docs
    avance_path = os.path.join(DOCS_DIR, 'AVANCE_2026-09-17.md')
    if os.path.exists(avance_path):
        with open(avance_path, 'r', encoding='utf-8') as f:
            t = f.read()
        # General pattern replacement for file:///C:/Users/ArmandoSilva/Downloads/
        # Replace specific docs with local docs reference
        doc_files = [
            'SUPERVISOR_OFFLINE_ACCEPTANCE.md', 'P7_MANUAL_LOAD_CHECKLIST.md',
            'CORE_08_09_10_FIELD_VERIFICATION_MATRIX.md', 'CORE_08_09_10_RUNTIME_GAPS_AND_ROADMAP.md',
            'PLAN_V3_OFFLINE_GAPS_AND_RESOLUTION.md', 'cscape_save_failed_diagnosis.md'
        ]
        for df in doc_files:
            t = t.replace(f'file:///C:/Users/ArmandoSilva/Downloads/{df}', df)
            t = t.replace(f'[`Downloads/{df}`]({df})', f'[`{df}`]({df})')

        # Zip bundles to repo root
        t = t.replace('file:///C:/Users/ArmandoSilva/Downloads/offline_evidence_bundle_v1.0.0.zip', '../offline_evidence_bundle_v1.0.0.zip')
        t = t.replace('file:///C:/Users/ArmandoSilva/Downloads/offline_evidence_bundle_v1.1.0.zip', '../offline_evidence_bundle_v1.1.0.zip')
        t = t.replace('[`Downloads/offline_evidence_bundle_v1.0.0.zip`](../offline_evidence_bundle_v1.0.0.zip)', '[`offline_evidence_bundle_v1.0.0.zip`](../offline_evidence_bundle_v1.0.0.zip)')
        t = t.replace('[`Downloads/offline_evidence_bundle_v1.1.0.zip`](../offline_evidence_bundle_v1.1.0.zip)', '[`offline_evidence_bundle_v1.1.0.zip`](../offline_evidence_bundle_v1.1.0.zip)')

        # Artifacts to ops/artifacts/
        t = re.sub(r'\[`Downloads/([^`]+)`\]\(file:///C:/Users/ArmandoSilva/Downloads/([^)]+)\)', r'[`ops/artifacts/\1`](../ops/artifacts/\2)', t)
        t = re.sub(r'file:///C:/Users/ArmandoSilva/Downloads/([^)]+)', r'../ops/artifacts/\1', t)
        with open(avance_path, 'w', encoding='utf-8') as f:
            f.write(t)
        print('Updated: docs/AVANCE_2026-09-17.md')

    # 13. CAPABILITY_MATRIX.md in docs/product and root
    for cap_path in [os.path.join(DOCS_DIR, 'product', 'CAPABILITY_MATRIX.md'), os.path.join(REPO_ROOT, 'CAPABILITY_MATRIX.md')]:
        if os.path.exists(cap_path):
            replace_in_file(
                cap_path,
                [
                    ('[`Downloads/mj1_scan_list_inspection_evidence.json`](file:///C:/Users/ArmandoSilva/Downloads/mj1_scan_list_inspection_evidence.json)<br>[`Downloads/mj1_scan_list_inspection_evidence.md`](file:///C:/Users/ArmandoSilva/Downloads/mj1_scan_list_inspection_evidence.md)<br>', ''),
                    ('[`Downloads/mj1_scan_list_validation_evidence.json`](file:///C:/Users/ArmandoSilva/Downloads/mj1_scan_list_validation_evidence.json)<br>[`Downloads/mj1_scan_list_validation_evidence.md`](file:///C:/Users/ArmandoSilva/Downloads/mj1_scan_list_validation_evidence.md)<br>', ''),
                    ('[`Downloads/mj1_scan_list_reconciliation_evidence.json`](file:///C:/Users/ArmandoSilva/Downloads/mj1_scan_list_reconciliation_evidence.json)<br>[`Downloads/mj1_scan_list_reconciliation_evidence.md`](file:///C:/Users/ArmandoSilva/Downloads/mj1_scan_list_reconciliation_evidence.md)<br>', ''),
                ]
            )

if __name__ == '__main__':
    run_sanitization()
