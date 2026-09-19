# Cryptographic Manifest & Engineering Audit: offline_evidence_bundle_v1.1.0.zip

**Bundle File**: `offline_evidence_bundle_v1.1.0.zip`  
**Bundle Size**: `364,842 bytes`  
**Bundle SHA-256**: `3ebfc66e7489954a243c630b6eff46da819104f44cefae78305e5669de72bed9`  
**Created UTC**: `2026-09-18T01:20:55.547760+00:00`  
**Operational Mode**: `offline/DEV [PRODUCT_EVIDENCE]` -> `P7_MANUAL`  
**State Contract**: `STATE: CORE-08 CONFIG_AND_TEST_OK RUNTIME_PENDING_P7`  
**Supervisor Offline Accepted**: `true` (Signoff: `2026-09-17T14:20:00-07:00`)  
**Total Archived Files**: `42` (40 evidence files + `MANIFEST-SHA256.json` + `README.md`)  
**Total Uncompressed Bytes**: `590,553 bytes`  

---

## 1. Safety & Lockout Guarantees

1. **Zero PLC Download**: Automated scripts, FastMCP servers, and background daemons permanently barred from physical COM ports (COM1..COM256) and Win32 download command IDs (32827, 33149).
2. **Phase P7 Deferred Manual**: Physical loading to Horner XL4 Prime (HE-XPCE2) is deferred strictly to manual execution by commissioning engineer Armando Silva via Cscape 10.2 GUI.
3. **Zero VERIFIED_LIVE**: Operational mode remains strictly offline DEV; zero claims of physical live execution offline.
4. **Single GUI Owner**: Exclusive desktop access on winsta0\Default reserved for Cscape PID 12788.
5. **No Error Check Loop**: Zero repetitive compiler polling loops.

---

## 2. Complete Archive File Inventory & SHA-256 Manifest

| Index | Archive Path | Filename | Size (Bytes) | SHA-256 Digest |
| :--- | :--- | :--- | :--- | :--- |
| 1 | `p4_continuation/p4_selective_edit_evidence.json` | `p4_selective_edit_evidence.json` | 14,406 | `e4c4e97c14c3c34f6825f6d6d36c0633ad3dfc064ab95193c7b3c80fc658b86c` |
| 2 | `p4_continuation/p4_selective_edit_evidence.md` | `p4_selective_edit_evidence.md` | 20,408 | `e3221302b35923b54426322201ea8a7fc18fb517b4de5b9d701a2f99f0a098ec` |
| 3 | `p4_continuation/p4_selective_edit_continuation_evidence.json` | `p4_selective_edit_continuation_evidence.json` | 4,175 | `81193ef63c3e87e68694dd65c896bd5cc15cf6de8e7125a2a0841d43b05ec470` |
| 4 | `p4_continuation/p4_selective_edit_continuation_evidence.md` | `p4_selective_edit_continuation_evidence.md` | 4,497 | `26c86cb38cc8ace5cb22e9f1ce33b7b305ad06dacd9d9102b342894817ef71ba` |
| 5 | `p6_continuation/p6_external_handoff_evidence.json` | `p6_external_handoff_evidence.json` | 7,725 | `e1bf28cc69fffc77f1f7eb36cbf15d43b58686618e8d9095357625b931087334` |
| 6 | `p6_continuation/p6_external_handoff_evidence.md` | `p6_external_handoff_evidence.md` | 6,725 | `d10e223564e976dc51d5cad156f16dff9d5bf31ddfa6f86d1a5bc2baf87b2cae` |
| 7 | `p6_continuation/p6_second_context_handoff_evidence.json` | `p6_second_context_handoff_evidence.json` | 7,631 | `c6b61d86ecdf7120aa83845e770dfe9db56925cc7607ca16771b3f03bf131906` |
| 8 | `p6_continuation/p6_second_context_handoff_evidence.md` | `p6_second_context_handoff_evidence.md` | 4,531 | `df7386a21839bc249a33733570943bb122c32c81ec2bbab9e46eb17e3a031708` |
| 9 | `save_failed_forensics/save_failed_caveat.txt` | `save_failed_caveat.txt` | 19 | `797d7e2cb29bc5a7c9c3fb45f8c9f21fa2f82cfca439c4d9aa39ded45fed4175` |
| 10 | `save_failed_forensics/cscape_save_failed_diagnosis.md` | `cscape_save_failed_diagnosis.md` | 16,560 | `e7b8c556fbe9af5de90322e4b4f98ac1c0362987699876d4073e2518124f5e11` |
| 11 | `save_failed_forensics/cscape_save_failed_evidence.json` | `cscape_save_failed_evidence.json` | 885 | `27c86d2eba955b90be8830ff307363eb152ba45e35444d9dc16599c93c6dd3d8` |
| 12 | `save_failed_forensics/cscape_save_failed_reproduction.png` | `cscape_save_failed_reproduction.png` | 156,882 | `32551bcfef4ac339cfd337e5d1bf07f55cfcee4077b0048ef79fe21bc6f74704` |
| 13 | `mj1_scan_baseline/mj1_devices_scan_evidence.json` | `mj1_devices_scan_evidence.json` | 450 | `bced2807f59136494b5cbf7950d651b9f922a393971fb01f9913d8298fb4f97a` |
| 14 | `mj1_scan_baseline/mj1_devices_scan_evidence.md` | `mj1_devices_scan_evidence.md` | 11,124 | `a01c7644872270ccc5a8dd9fde379c78645d9f2b67356baedd7637585abea600` |
| 15 | `mj1_scan_baseline/mj1_scan_list_validation_evidence.json` | `mj1_scan_list_validation_evidence.json` | 3,317 | `b2b68d13da3661d23b0b97bac6908623cc890f24d952bc13cd335d634e4b6c87` |
| 16 | `mj1_scan_baseline/mj1_scan_list_validation_evidence.md` | `mj1_scan_list_validation_evidence.md` | 11,443 | `e03379a4370e77b85213837ca77c030417041ac1dae929a2fbf7ef839994fe83` |
| 17 | `mj1_scan_baseline/mj1_scan_list_inspection_evidence.json` | `mj1_scan_list_inspection_evidence.json` | 4,899 | `fce014fd65caeadbad695bcc30ee0338955c74473bd58d671aa7a1d17dead94c` |
| 18 | `mj1_scan_baseline/mj1_scan_list_inspection_evidence.md` | `mj1_scan_list_inspection_evidence.md` | 8,124 | `56fa26fdae24ba2a3296d4636471654ab28c1510eae47c41f3e60a2ec0dd4362` |
| 19 | `mj1_scan_baseline/mj1_scan_list_reconciliation_evidence.json` | `mj1_scan_list_reconciliation_evidence.json` | 8,894 | `e5c53f1756f8b02031cba33952a571422d091422359caf0f93969fc823d7f2db` |
| 20 | `mj1_scan_baseline/mj1_scan_list_reconciliation_evidence.md` | `mj1_scan_list_reconciliation_evidence.md` | 8,843 | `b8116b33e196aebc10836642e78ddf59e6822833478c466b001c618baef0eeb8` |
| 21 | `core08_configs/modbus_protocol_inventory.json` | `modbus_protocol_inventory.json` | 5,943 | `d1d0809eb48d4ad9b274276f817adcfdcdae1b6476ca6c8d5613eaf1f2fa14ac` |
| 22 | `core08_configs/modbus_pv_config.json` | `modbus_pv_config.json` | 1,675 | `fb06d8740cccaf3f90312715723b1960971ad4da15b34f21c0d305380b91314d` |
| 23 | `core08_configs/core08_labeled_test_server_verification.json` | `core08_labeled_test_server_verification.json` | 3,908 | `1a5306c1bf9362283e327e3ddf63847923835ab54e130ca53e2ab804123f6383` |
| 24 | `core08_configs/core08_cscape_gui_evidence.json` | `core08_cscape_gui_evidence.json` | 3,246 | `72d3a75a22f9a3b77e3c11c5d8bfe221e70703e04d6689c7bf0f301d13ca2403` |
| 25 | `core08_configs/core08_security_lockout_evidence.json` | `core08_security_lockout_evidence.json` | 11,007 | `d3aae87be49e3b906bdfc9fba7d898ce8a7b0712d384a1dfa81c697849a9c9d9` |
| 26 | `core08_configs/CORE_08_MODBUS_CONVERSION_EXAMPLE.md` | `CORE_08_MODBUS_CONVERSION_EXAMPLE.md` | 24,939 | `de7b51859dcba600b9adf46f1e15099728aace1805bb8a42d2dd779a03672032` |
| 27 | `core08_configs/CORE_08_PROTOCOL_DRIVER_FORENSICS.md` | `CORE_08_PROTOCOL_DRIVER_FORENSICS.md` | 25,447 | `8086b2140d1219d94a6a6d5ed3d9c5bf118478d172b2466e54c1cd38a8dc4a7b` |
| 28 | `iec_scaling_bridge/modbus_register_scaling_iec_bridge_evidence.json` | `modbus_register_scaling_iec_bridge_evidence.json` | 6,685 | `392cbe5fc617dd19e0a6ae917dd35c894debaa3399ce5eb533d27c4f0732ab29` |
| 29 | `iec_scaling_bridge/modbus_register_scaling_iec_bridge_evidence.md` | `modbus_register_scaling_iec_bridge_evidence.md` | 9,948 | `d77a3cf8b68218f10b20a3e316be0dd0ba12e35219c9f10b6b95d983e28c77ab` |
| 30 | `mj1_state_evidence/mj1_devices_scan_list_state_evidence.json` | `mj1_devices_scan_list_state_evidence.json` | 9,301 | `ae537e70b9401cd6e9dc818637f50303fc20ce58b9789e16f164dbd98fdf21ec` |
| 31 | `mj1_state_evidence/mj1_devices_scan_list_state_evidence.md` | `mj1_devices_scan_list_state_evidence.md` | 11,273 | `fbcae293862678c584ac728d5594775ce89415b90acc99a5bbfd3abd6fc428f3` |
| 32 | `native_reopen_proof/tanklevel_p5_native_reopen_proof_evidence.json` | `tanklevel_p5_native_reopen_proof_evidence.json` | 5,403 | `c8c9e9f53d79de567d07f29125d162b0c81fbe8560e18acb86e830cd730f440b` |
| 33 | `native_reopen_proof/tanklevel_p5_native_reopen_proof_evidence.md` | `tanklevel_p5_native_reopen_proof_evidence.md` | 7,664 | `b4e7c3956c298315c9d30a86b2ff17c8e43e567977506116f08635b6f60180f2` |
| 34 | `native_reopen_proof/tanklevel_p5_native_reopen_proof.png` | `tanklevel_p5_native_reopen_proof.png` | 84,067 | `75aee77a599713e5c4eb73597ee42546d3aa9825b727a769546956ba061d6074` |
| 35 | `supervisor_acceptance/SUPERVISOR_OFFLINE_ACCEPTANCE.md` | `SUPERVISOR_OFFLINE_ACCEPTANCE.md` | 11,130 | `3872f24557fef03948785bed018af364013a500bf8ca8f956b8ad2af30542510` |
| 36 | `supervisor_acceptance/P7_COMMISSIONING_PREP_MANIFEST.md` | `P7_COMMISSIONING_PREP_MANIFEST.md` | 5,506 | `13ba9061f3a60a69ac887ae6eca36ae0014310a5133de4ec164620e7813d69bf` |
| 37 | `gap_docs_and_roadmap/PLAN_V3_OFFLINE_GAPS_AND_RESOLUTION.md` | `PLAN_V3_OFFLINE_GAPS_AND_RESOLUTION.md` | 20,427 | `55823255c01e52e6c51d90da95c900ba74d1d50739eca9bce9844f31a08c73d4` |
| 38 | `gap_docs_and_roadmap/CORE_08_09_10_RUNTIME_GAPS_AND_ROADMAP.md` | `CORE_08_09_10_RUNTIME_GAPS_AND_ROADMAP.md` | 11,745 | `b25c3b85f6ff24a6ba71fd8ffa73824543f9de0f50cb355a773d1b7c6c30130c` |
| 39 | `gap_docs_and_roadmap/CORE_08_09_10_FIELD_VERIFICATION_MATRIX.md` | `CORE_08_09_10_FIELD_VERIFICATION_MATRIX.md` | 17,523 | `515f769f77584b3baab575ae8d253c3a2ede5abcc9ae89fe1664e0ffc3a5e7ba` |
| 40 | `gap_docs_and_roadmap/core08_09_10_field_verification_matrix.json` | `core08_09_10_field_verification_matrix.json` | 12,178 | `c76b625b32927bf2d7988d271b7d7a81c8d003beac9b893ff7e56bb7ad6b34df` |

---

## 3. Cryptographic Verification Command

```powershell
Get-FileHash -Path C:\Users\ArmandoSilva\Downloads\offline_evidence_bundle_v1.1.0.zip -Algorithm SHA256
```
Expected SHA-256: `3ebfc66e7489954a243c630b6eff46da819104f44cefae78305e5669de72bed9`
