# Comprehensive Handoff File Index & Distribution Catalog

**Release Target**: Milestone CORE-08 / Supervisor Offline Acceptance & Handoff  
**Active Task**: `SUPERVISOR_OFFLINE_ACCEPTANCE`  
**Supervisor Offline Accepted**: `true` (Timestamp: `2026-09-17T14:20:00-07:00`)  
**Accepted Offline Deliverables**: `P4/P6 evidence`, `scan-list tool`, `evidence bundle`, `Modbus IEC FB bridge`, `P5 reopen proof`  
**Next Human Gate**: `P7_MANUAL` (Phase P7 physical PLC download strictly deferred for manual loading by commissioning engineer)  
**State Contract**: `STATE: RUNTIME_PENDING_P7`  
**Operational Mode**: `offline/DEV [PRODUCT_EVIDENCE]` (Zero PLC Download, Fail-Closed Hardware Lockout)  
**Live Telemetry Status**: `verified_live: false` (Zero `VERIFIED_LIVE` claimed)  
**Commissioning Policy**: `P7 deferred manual` (Manual loading by commissioning engineer; do NOT automate download)  
**GUI Ownership**: Single GUI Owner exclusively active on `winsta0\Default` (Cscape PID `12788`, untouched on desktop)  
**Hygiene Loop Status**: ABORTED per user directive (`STOP keep-alive and Error Check loops. TOP Plan v3 offline PRODUCT work only`)  
**Process State**: `1 Dedicated + 1 PS` (Cscape PID `12788` continuously preserved; no Error Check loop)  

---

## 1. Master Distribution & Handoff Table

All 49 artifacts cataloged below are synchronized across:
- **Downloads Directory**: `C:\Users\ArmandoSilva\Downloads\`
- **Primary Workspace**: `C:\HornerAI\horner-cscape-mcp\`
- **User Mirror**: `C:\Users\ArmandoSilva\`
- **Artifacts Directory**: `ops/artifacts/`

| # | Artifact Filename | Category | Size (Bytes) | SHA-256 Checksum | Operational Purpose & Role |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | **`TankLevel_P5_Dedicated_offline_bundle_v1.0.0.zip`** | P6 Distribution Zip | 71,356 | `d21df9d20c793f85274b21eb928310ef17e5034a638abbf16f92d8c95c97bc08` | Standalone air-gapped package with `MANIFEST-SHA256.json`, POUs, CSP, and Modbus configs. |
| 2 | **`horner-cscape-project-handoff-v1.0.0.zip`** | P6 Distribution Zip | 78,374 | `7a3a58243be55bf561bdd8a6c803a0c72fb6cd2b58dfc63556f0fef343df44c8` | Clean distribution archive for plant controls and PLC commissioning engineers. |
| 3 | **`horner-cscape-mcp-v1.0.0-developer-bundle.zip`** | P6 Distribution Zip | 351,255 | `e7f1b6c8c12152724e715811891c2ee7598b23a5967954accff16326b126e6a8` | Standalone FastMCP developer package with 40 tools, schemas, and stdio transport. |
| 4 | **`P7_MANUAL_COMMISSIONING_PROCEDURE.md`** | P7 Commissioning SOP | 9,893 | `f102e0a902dcfbd8bf47c3504b09509fdf5d0c432b160f75ea81a04380e9530b` | 9-step Standard Operating Procedure: LOTO, cabling, Error Check, connection, and manual download. |
| 5 | **`P7_MANUAL_LOAD_CHECKLIST.md`** | P7 Safety Checklist | 18,411 | `86668215743f2b049d20f6645c3813dd41f7899acdde9c301be244bd9e3da51a` | Bilingual (EN/ES) pre-connection & download checklist aligned with SOP-P7 (9 steps, HE-XPCE2, TankLevel_P5_Dedicated.csp, MJ1 CT RTU Modbus CMP v5.05, Scan List empty until live, pointers to SUPERVISOR_OFFLINE_ACCEPTANCE.md and offline_evidence_bundle_v1.0.0.zip). |
| 6 | **`P8_HARDENING_AND_KNOWN_LIMITATIONS.md`** | P8 Limitations Doc | 15,066 | `cf60c7723d5b6995ae4cf4a429bcbc6962c7f6307d7433180d41904e0af32c28` | Platform boundaries: hardware lockout, Straton quarantine, ST->LD `BLOCKED_NATIVE`. |
| 7 | **`modbus_protocol_inventory.json`** | CORE-08 Protocol JSON | 5,943 | `d1d0809eb48d4ad9b274276f817adcfdcdae1b6476ca6c8d5613eaf1f2fa14ac` | Deep Modbus inventory with channels `LAN1_TCP`, `MJ1_RTU`, `MJ2_RTU`, 3 devices, and 3 scan items. |
| 8 | **`modbus_pv_config.json`** | CORE-08 PV Sidecar | 1,675 | `fb06d8740cccaf3f90312715723b1960971ad4da15b34f21c0d305380b91314d` | Primary process variable sidecar binding `TankLevelPV` to `%AI1` (Modicon 40001, wire offset 0). |
| 9 | **`core08_labeled_test_server_verification.json`** | CORE-08 Evidence JSON | 3,908 | `1a5306c1bf9362283e327e3ddf63847923835ab54e130ca53e2ab804123f6383` | Proof log: reads 55% (17600), multi-read, dynamic 75% (24000), write lockout Exception 0x01. |
| 10 | **`core08_cscape_gui_evidence.json`** | CORE-08 Evidence JSON | 3,246 | `72d3a75a22f9a3b77e3c11c5d8bfe221e70703e04d6689c7bf0f301d13ca2403` | Live Cscape GUI liveness log: `Protocols` node verified; native scan list documented empty in GUI. |
| 11 | **`core08_security_lockout_evidence.json`** | CORE-08 Evidence JSON | 11,007 | `d3aae87be49e3b906bdfc9fba7d898ce8a7b0712d384a1dfa81c697849a9c9d9` | Fail-closed security proof: 792 checks blocking ports COM1-256, CAN, USB, and Win32 32827/33149. |
| 12 | **`TankLevel_P5_Dedicated.csp`** | Native Project Container | 140,800 | `9f69f6a2ee12dab54087ab27bb839f40e01d6d65544a546139788519acd80ab1` | CFBF/OLE2 container with pure ST logic, Modbus function blocks, and clean compile (0 errors). |
| 13 | **`CORE_08_MODBUS_CONVERSION_EXAMPLE.md`** | Technical Spec Doc | 24,939 | `de7b51859dcba600b9adf46f1e15099728aace1805bb8a42d2dd779a03672032` | Mathematical linear scaling (0..32000 counts), hex frame breakdowns, ST logic, and quality matrix. |
| 14 | **`CORE_08_PROTOCOL_DRIVER_FORENSICS.md`** | Technical Forensics Doc| 25,447 | `8086b2140d1219d94a6a6d5ed3d9c5bf118478d172b2466e54c1cd38a8dc4a7b` | PE binary forensics on `CTRtu.dll` ("CT RTU Modbus CMP") and `Modbus.dll` ("Modbus Master"). |
| 15 | **`LEEME_HANDOFF.txt`** | Bilingual Readme | 8,250 | Dynamic Update | Complete Spanish & English delivery guide with procedural instructions for the plant engineer. |
| 16 | **`LEEME.txt`** | Summary Readme | 1,850 | Dynamic Update | High-level summary of handoff artifacts, P4/P6 evidence, and operational invariants. |
| 17 | **`p4_selective_edit_evidence.json`** | P4 Evidence JSON | 14,406 | `e4c4e97c14c3c34f6825f6d6d36c0633ad3dfc064ab95193c7b3c80fc658b86c` | Full FastMCP JSON-RPC transcript of selective edit on Dedicated (30/70->35/75, label, durability proof). |
| 18 | **`p4_selective_edit_evidence.md`** | P4 Evidence Markdown | 20,408 | `e3221302b35923b54426322201ea8a7fc18fb517b4de5b9d701a2f99f0a098ec` | Comprehensive technical report for P4 selective edit, AST diff, durability save/reopen proof. |
| 19 | **`p6_external_handoff_evidence.json`** | P6 Evidence JSON | 7,725 | `e1bf28cc69fffc77f1f7eb36cbf15d43b58686618e8d9095357625b931087334` | Verification JSON from secondary context (`C:\Users\Public\HornerHandoffSecondary` and temp staging). |
| 20 | **`p6_external_handoff_evidence.md`** | P6 Evidence Markdown | 6,725 | `d10e223564e976dc51d5cad156f16dff9d5bf31ddfa6f86d1a5bc2baf87b2cae` | Technical report documenting handoff extraction, CFBF inspection, pure ST AST, Modbus sidecars, paths+SHAs. |
| 21 | **`p4_selective_edit_continuation_evidence.json`** | P4 Evidence JSON | 4,175 | `81193ef63c3e87e68694dd65c896bd5cc15cf6de8e7125a2a0841d43b05ec470` | Stage 3 continuation edit on Dedicated: Rev 1.1.0 -> 1.2.0, limits 32.0/78.0%, label "Buffer Tank 01 Level PV", idempotency NO_OP, negative lockout. |
| 22 | **`p4_selective_edit_continuation_evidence.md`** | P4 Evidence Markdown | 4,497 | `26c86cb38cc8ace5cb22e9f1ce33b7b305ad06dacd9d9102b342894817ef71ba` | Technical report covering multi-stage evolution (Rev 1.0.0 -> 1.1.0 -> 1.2.0), untouched variable/HMI audit, concurrency protection. |
| 23 | **`p6_second_context_handoff_evidence.json`** | P6 Evidence JSON | 7,631 | `c6b61d86ecdf7120aa83845e770dfe9db56925cc7607ca16771b3f03bf131906` | Verification JSON from second independent external context (`C:\Users\Public\HornerHandoffContext2`), 100% manifest match, valid CFBF, pure ST AST. |
| 24 | **`p6_second_context_handoff_evidence.md`** | P6 Evidence Markdown | 4,531 | `df7386a21839bc249a33733570943bb122c32c81ec2bbab9e46eb17e3a031708` | Technical report documenting handoff extraction and validation in clean independent profile context, relocation invariance. |
| 25 | **`save_failed_caveat.txt`** | Operational Caveat | 19 | `797d7e2cb29bc5a7c9c3fb45f8c9f21fa2f82cfca439c4d9aa39ded45fed4175` | Operational caveat note recording the recurring Cscape Save-failed dialog condition (`Save-failed dialog.`). |
| 26 | **`cscape_save_failed_diagnosis.md`** | Forensic Diagnosis Doc | 16,560 | `e7b8c556fbe9af5de90322e4b4f98ac1c0362987699876d4073e2518124f5e11` | In-depth forensic diagnosis of Cscape 10.2 "Failed to save document" dialog, reproduction conditions, 5 root hypotheses, and safe Save As workaround. |
| 27 | **`cscape_save_failed_evidence.json`** | Forensic Evidence JSON | 885 | `27c86d2eba955b90be8830ff307363eb152ba45e35444d9dc16599c93c6dd3d8` | Win32 control-level capture of reproduced modal `#32770` dialog (HWND 0x000707C2, controls, rect, error text). |
| 28 | **`cscape_save_failed_reproduction.png`** | Forensic Screenshot | 156,882 | `32551bcfef4ac339cfd337e5d1bf07f55cfcee4077b0048ef79fe21bc6f74704` | High-resolution visual proof of live Cscape displaying the reproduced "Failed to save document." dialog. |
| 29 | **`mj1_devices_scan_evidence.json`** | Scan List Evidence JSON | 333 | `d38d30b3a7c1354578faa4604438db320713a29409d97d9fcfda0c615ee4199a` | Cscape inspection record confirming MJ1 (CT RTU Modbus CMP v5.05) scan list is empty; native fill blocked offline pending P7. |
| 30 | **`mj1_devices_scan_evidence.md`** | Scan List Evidence MD | 467 | `dff792e7e9077dc9fc7198bb588817feafb6f0e89167832fc26a6c7b32f30f29` | Companion executive and technical summary of empty MJ1 scan list and offline fail-closed rationale. |
| 31 | **`mj1_scan_list_validation_evidence.json`** | FastMCP Validation JSON | 3,317 | `b2b68d13da3661d23b0b97bac6908623cc890f24d952bc13cd335d634e4b6c87` | FastMCP validation results, tool registry confirmation, fail-closed assertion matrix, 16/16 contract test pass. |
| 32 | **`mj1_scan_list_validation_evidence.md`** | FastMCP Validation MD | 11,443 | `e03379a4370e77b85213837ca77c030417041ac1dae929a2fbf7ef839994fe83` | Comprehensive executive report on FastMCP scan-list validation, zero PLC download certification, and offline safety. |
| 33 | **`mj1_scan_list_inspection_evidence.json`** | Public Tool Evidence JSON | 4,899 | `fce014fd65caeadbad695bcc30ee0338955c74473bd58d671aa7a1d17dead94c` | Live tool execution capture of `cscape_inspect_scan_list`, proving empty scan list baseline and fail-closed blocked return on `require_populated=True`. |
| 34 | **`mj1_scan_list_inspection_evidence.md`** | Public Tool Evidence MD | 8,124 | `56fa26fdae24ba2a3296d4636471654ab28c1510eae47c41f3e60a2ec0dd4362` | Comprehensive technical and executive summary of public scan-list tool inspection, fail-closed contract, and next offline gap definition. |
| 35 | **`mj1_scan_list_reconciliation_evidence.json`** | Reconciliation Evidence JSON | 8,894 | `e5c53f1756f8b02031cba33952a571422d091422359caf0f93969fc823d7f2db` | Automated offline reconciliation audit between planned Modbus RTU inventory (3 transactions: %AI1, %AI2, %AI3) and native CFBF container (0 entries); fail-closed explanation of offline lockout. |
| 36 | **`mj1_scan_list_reconciliation_evidence.md`** | Reconciliation Evidence MD | 8,843 | `b8116b33e196aebc10836642e78ddf59e6822833478c466b001c618baef0eeb8` | Comprehensive technical and executive report on offline scan-list reconciliation, planned vs. native audit, root cause of native empty table, zero PLC download certification, and Phase P7 manual deferral. |
| 37 | **`offline_evidence_bundle_v1.0.0.zip`** | Air-Gapped Evidence Bundle ZIP | 335,933 | `16a1ac91445a9067c24617b61063ddf9585ef272af6fa1c707fd83f1d8fec512` | Complete air-gapped distribution bundle consolidating all 28 recent offline forensic, verification, and diagnosis files (P4/P6 continuation, MJ1 scan baseline, validation, inspection, reconciliation, save-failed diagnosis, sidecars, and Error Check proof) with internal cryptographic manifest. |
| 38 | **`offline_evidence_bundle_manifest.json` / `.md`** | Cryptographic Manifest & Report | 8,629 / 7,872 | `ac543ffbf408c1d76272cae6724814f106f43a4da2ccac0ba563ca98f35dde10` / `5a6fd6b4ae440a082b373a9eb5070f72e7533b2e6c20575f7ee988dc0ed76865` | Cryptographic SHA-256 manifest and engineering verification report detailing all 30 archived assets, exact byte sizes, SHA-256 digests, zero PLC download certification, and fail-closed security guarantees. |
| 39 | **`modbus_register_scaling_iec_bridge_evidence.json`** | Bridge Evidence JSON | 6,685 | `392cbe5fc617dd19e0a6ae917dd35c894debaa3399ce5eb533d27c4f0732ab29` | Offline Modbus register scaling & IEC FB bridge execution evidence; nominal/underflow/overflow/fail-safe validation. |
| 40 | **`modbus_register_scaling_iec_bridge_evidence.md`** | Bridge Evidence MD | 9,948 | `d77a3cf8b68218f10b20a3e316be0dd0ba12e35219c9f10b6b95d983e28c77ab` | Comprehensive engineering report on pure ST FB_ModbusScaleQuality, TankLevelModbusBridge, and 3-channel telemetry. |
| 41 | **`mj1_devices_scan_list_state_evidence.json`** | State Evidence JSON | 9,301 | `ae537e70b9401cd6e9dc818637f50303fc20ce58b9789e16f164dbd98fdf21ec` | Comprehensive offline MJ1 port, driver, devices, and scan list state documentation evidence. |
| 42 | **`mj1_devices_scan_list_state_evidence.md`** | State Evidence MD | 11,273 | `fbcae293862678c584ac728d5594775ce89415b90acc99a5bbfd3abd6fc428f3` | Authoritative engineering report on MJ1 scan list empty state, offline blocker root cause, planned inventory, and P7 deferral. |
| 43 | **`tanklevel_p5_native_reopen_proof_evidence.json`** | Reopen Evidence JSON | 5,403 | `c8c9e9f53d79de567d07f29125d162b0c81fbe8560e18acb86e830cd730f440b` | FastMCP `cscape_open_project` native reopen execution evidence on PID 12788 with scaling bridge. |
| 44 | **`tanklevel_p5_native_reopen_proof_evidence.md`** | Reopen Evidence MD | 7,664 | `b4e7c3956c298315c9d30a86b2ff17c8e43e567977506116f08635b6f60180f2` | Comprehensive engineering report on native reopen proof, visible Cscape window, and pure ST scaling bridge. |
| 45 | **`tanklevel_p5_native_reopen_proof.png`** | High-Res Screenshot | 84,067 | `75aee77a599713e5c4eb73597ee42546d3aa9825b727a769546956ba061d6074` | High-resolution visual proof of live visible Cscape displaying TankLevel_P5_Dedicated.csp. |
| 46 | **`SUPERVISOR_OFFLINE_ACCEPTANCE.md`** | Supervisor Signoff MD | 11,130 | `3872f24557fef03948785bed018af364013a500bf8ca8f956b8ad2af30542510` | Formal supervisor offline acceptance of all Plan v3 deliverables, signoff summary, remaining P7/CORE-09/CORE-10 gates, and pointer to P7 checklist. |
| 47 | **`P7_COMMISSIONING_PREP_MANIFEST.md`** | P7 Preparation Manifest | 5,506 | `13ba9061f3a60a69ac887ae6eca36ae0014310a5133de4ec164620e7813d69bf` | Autonomous agent consortium verification sign-off (10 specialized agents), safety lockout directives, Cscape dedicated GUI owner, and MJ1 configuration manifest. |
| 48 | **`PLAN_V3_OFFLINE_GAPS_AND_RESOLUTION.md`** | Gap Analysis & Audit | 20,427 | `55823255c01e52e6c51d90da95c900ba74d1d50739eca9bce9844f31a08c73d4` | Comprehensive technical audit of Plan v3 offline gaps: MJ1 empty scan list, 43 FastMCP tools 4-tier capability classification, live GUI partial boundaries, ST->LD blocked native, and P7 manual handoff. |
| 49 | **`CORE_08_09_10_RUNTIME_GAPS_AND_ROADMAP.md`** | Operational Roadmap & Gaps | 11,745 | `b25c3b85f6ff24a6ba71fd8ffa73824543f9de0f50cb355a773d1b7c6c30130c` | Technical audit and operational roadmap for CORE-08 live runtime (RS-485 MJ1), CORE-09 physical HMI/WebMI screen verification, and CORE-10 24h hardware telemetry soak. |

---

## 2. Operational Caveat Note: Cscape Save Behavior & Safe "Save As" Workaround

> [!WARNING]
> **Operational Caveat on Cscape 10.2 Save Operations (`save_failed_caveat.txt`)**:
> During both manual GUI usage and automated scripting in Cscape 10.2 (Build 10.2.751.4), executing a direct `File -> Save` (`Ctrl+S` / `WM_COMMAND 57603`) can intermittently trigger an MFC modal warning dialog:
> **`"Failed to save document."`** (PE String ID `AFX_IDP_FAILED_TO_SAVE_DOC = 0xF183`).

### Root Causes & Forensic Findings
As detailed in [`docs/cscape_save_failed_diagnosis.md`](cscape_save_failed_diagnosis.md), this occurs due to:
1. **File Sharing Violations (`ERROR_SHARING_VIOLATION = 32`)**: Another process or background worker holds an open handle without `FILE_SHARE_WRITE`.
2. **CFBF OLE2 Storage Desynchronization**: External tools modifying `.csp` containers on disk while Cscape has the file open in-memory.
3. **MFC Working Directory Drift**: Common Dialog navigation mutating the process current working directory (`CWD`), breaking relative path resolution.
4. **Editor Modal Lockout**: Child editor views (`W5EditST`) or property dialogs in an uncommitted edit state.

### Recommended Safe Workaround Procedure
1. **Never blind-save (`Ctrl+S` / `57603`)** when external modifications or path transitions have occurred.
2. **Always use "Save As" (`ID_FILE_SAVEAS = 57604`)**:
   - Provide an explicit, canonical, versioned full path (e.g. `ProjectName_safe_vX.Y.Z.csp`).
   - Confirm overwrite cleanly if prompted (`Confirm Save As` $\to$ `&Yes`).
   - Verify on-disk CFBF container integrity via `is_valid_cfbf()` post-save.

---

## 3. Invariants & Safety Declarations

1. **Hygiene Keep-Alive Loop Aborted**: All periodic keep-alive loops and cyclic Error Check routines are officially stopped per user directive. Focused strictly on Plan v3 offline product work.
2. **Zero PLC Download**: No automated script, FastMCP tool, or test runner may communicate with or download to physical PLC hardware.
3. **Phase P7 Deferred Manual**: When physical hardware is connected, the commissioning engineer must execute all connection and download steps manually via Cscape 10.2 menus (`Controller -> Download` / `Ctrl+F9`).
4. **No `VERIFIED_LIVE`**: All verifications are conducted in-memory against deterministic emulators (`SimulationBackend.EMULATED`) and labeled test endpoints (`[TEST_MODBUS_PV_PROVIDER]`).
5. **Single GUI Automation Owner**: Exclusive access to `winsta0\Default` is reserved for live Cscape supervision.
6. **Process Continuity**: 1 Dedicated Cscape instance (`PID 12788`) preserved untouched on `winsta0\Default`.
7. **Native Reopen Proof & Evidence Synchronized**:
   - Evidence items 39–40: `modbus_register_scaling_iec_bridge_evidence.*` (IEC FB scaling bridge)
   - Evidence items 41–42: `mj1_devices_scan_list_state_evidence.*` (MJ1 port & scan list baseline state)
   - Evidence items 43–45: `tanklevel_p5_native_reopen_proof_evidence.*`, `tanklevel_p5_native_reopen_proof.png` (Live Cscape native reopen proof & visual confirmation)
   - Acceptance item 46: `SUPERVISOR_OFFLINE_ACCEPTANCE.md` (Formal supervisor offline acceptance & signoff)
   - Manifest item 47: `P7_COMMISSIONING_PREP_MANIFEST.md` (P7 preparation manifest & multi-agent sign-off)
   - Gap audit item 48: `PLAN_V3_OFFLINE_GAPS_AND_RESOLUTION.md` (Authoritative offline gaps analysis and resolution report)
   - Roadmap item 49: `CORE_08_09_10_RUNTIME_GAPS_AND_ROADMAP.md` (Technical audit and operational roadmap for CORE-08/09/10 field gaps)
