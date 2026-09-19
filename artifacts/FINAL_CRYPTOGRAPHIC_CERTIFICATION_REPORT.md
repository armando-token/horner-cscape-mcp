# Final Cryptographic Certification Report: Evidence Artifacts & Zero-Orphan Verification
**Generated**: 2026-09-04 22:05:04 UTC
**Target Repository**: `C:\HornerAI\horner-cscape-mcp`
**Artifacts Base Directory**: `C:\HornerAI\horner-cscape-mcp\artifacts`
**Auditor Role**: Cryptographic Evidence Certifier (Subagent `dfc028f2-c0db-4154-890f-abbc9a2d23da`)
**Parent Coordinator**: Agent `d9a2b9e2-a2df-4da9-8c3f-1dd6a3bb66bd`

## Executive Certification Summary

| Metric | Status / Value | Cryptographic Assertion |
| :--- | :--- | :--- |
| **Orphaned Cscape.exe Processes** | **0** | **ASSERTED & VERIFIED** (Clean teardown confirmed; 0 orphaned background daemons) |
| **Hardware Lockout / PLC Download** | **STRICT ZERO** | **ASSERTED & VERIFIED** (Air-gapped simulation only; download command IDs 32827/33149 locked out) |
| **Zero-Byte File Count** | **0** | **ASSERTED & VERIFIED** (All 141 evidence files > 0 bytes) |
| **Total Evidence Artifacts Audited** | **141** | Complete recursive inventory across 4 core evidence folders |
| **Total Artifact Payload Volume** | **3,133,058 bytes** (~2.99 MB) | Full cryptographic SHA-256 digests computed |
| **artifacts/logs/** | **17 files** (197,689 bytes) | Non-zero logs verified (master run, incidents, compile scrape, call path) |
| **artifacts/screenshots/** | **4 files** (181,011 bytes) | Valid PNG image containers (compile proof, desktop, dialogs) |
| **artifacts/conversions/** | **2 files** (16,543 bytes) | ST->Ladder conversion & ASCII proof |
| **artifacts/projects/** | **118 files** (2,737,815 bytes) | CFBF OLE2 compound docs (`0xD0CF11E0A1B11AE1`), JSON manifests, ST POU sources |

## 1. Process Assertion: Orphaned Cscape Instances

- **Verification Method**: PowerShell CIM / WMI `Win32_Process` query and `psutil` process iteration filtering for `Cscape.exe`.
- **Result**: Exactly **0** running or orphaned `Cscape.exe` processes on Windows.
- **Teardown Mechanics**: `CscapeLifecycleManager` cleanly orchestrated startup modals (`#32770` splash dialog and `Select Editor Type`), ensured proper STA COM threading, asserted registry key `HKCU\Software\Horner_Electric\Cscape\Setup\CscapeExitedCorrectly = 1`, and executed deterministic clean teardown via `WM_CLOSE` and process tree termination.

## 2. Safety Assertion: Strict Zero PLC Download Lockout

- **Lockout Policy**: `ENFORCED_FAIL_CLOSED`
- **Hardware Communication**: Fully air-gapped / simulation-only. COM serial ports (`COM1`–`COM256`), CAN bus adapters (`can0`, `pcan`), Ethernet raw sockets, USB, and JTAG hardware communication strictly blocked.
- **Command Lockout**: `ID_CONTROLLER_DOWNLOAD` (Command ID `32827`) and `ID_PROGRAM_DOWNLOADOPTIONS` (Command ID `33149`) are programmatically intercepted and raise `UnauthorizedDownloadError` / `UnsafeProcessError`.
- **Audit Proofs**: Verified across `closed_loop_verification_master.log`, `live_cscape_scraped_compile_errors.log`, `tank_level_dry_run_cutoff.log`, and `mcp_closed_loop_failure_location_call_path.json`.

## 3. Evidence Artifacts Cryptographic Hash Registry

### artifacts/logs/ (17 Files)

| Relative Path | Size (Bytes) | SHA-256 Checksum | Non-Zero? |
| :--- | :---: | :--- | :---: |
| `logs/closed_loop_verification_master.log` | 28,609 | `eebcf0128433bf376210e3f1bbb77d697eefa68f9754d96dc0cd0563dfce6055` | PASS |
| `logs/cscape_20260903_202542_247942_8265007c.log` | 349 | `b08a6363d1701ab3f1b0c4abe65bac7cbc46e93129a14bb09dee2b7834e9251b` | PASS |
| `logs/cscape_open_proof.log` | 2,269 | `435bb87832f8e9266c13ef0ef95dc238f588457c20742f467dc98c13c86c63db` | PASS |
| `logs/live_cscape_scraped_compile_errors.log` | 3,407 | `676825252a8b3236f326c8d4530210a051ba1e386cc029c082576314783a9607` | PASS |
| `logs/mcp_closed_loop_failure_location_call_path.json` | 20,728 | `0ae11c1115e2e373b5eb5c522a55eef8a16c11d6ae225d198e4a49e96c399433` | PASS |
| `logs/mcp_closed_loop_failure_location_call_path.log` | 10,347 | `8dff429802872d3733ae4b24803b4644c9638f34d6f0e712287c71f1668820ea` | PASS |
| `logs/mcp_live_gui_tools_evidence.log` | 1,685 | `3239a257e777d41be42805eadc43d645f83b4ad2504b90546ee5e925754c3efd` | PASS |
| `logs/st_clean_compile_proof.log` | 2,679 | `199f9273f62f2143b90fbdae9a1812beb834d7ed3f9f75bb1549cd4afefab27a` | PASS |
| `logs/st_ladder_conversion_proof.log` | 11,292 | `30306b9af7d053e66dce9dbfea802c8d4496bbeaf74cc90866ffe83120c8ee1d` | PASS |
| `logs/st_syntax_error_proof.log` | 3,488 | `f8737af6cdc44380bb272371bcd9f4106c2cb0e16378145275cd927041b44465` | PASS |
| `logs/tank_level_closed_loop_pid_scenarios.log` | 2,565 | `e1f89e6dd2677e2b3bd24d86fcbe750f55b8a41ae4803be6677b1beec3b3e83c` | PASS |
| `logs/tank_level_dry_run_cutoff.log` | 28,105 | `5d7e0fb6e24681aecf5f4a353607aadb0e49b80fc26900aca8fe67d5c3ece1d7` | PASS |
| `logs/tank_level_incident_failure.log` | 31,563 | `f1eb1b2884fb9e6b5fb050c763c3f6dfaf0d5c7ca43c5f32dc771c944d3f1174` | PASS |
| `logs/tank_level_open_live_proof.log` | 1,464 | `182334774b81961aaae2d61885b17cf23e07bda9b4a99e37d24e88bce75b51dc` | PASS |
| `logs/tank_level_overfill_trip.log` | 18,981 | `c66cb81a60f0457228e30baf96cc2dd9ed4631ed5b2e115a1ad277bf4ef71ea7` | PASS |
| `logs/tank_level_sensor_disconnect.log` | 29,759 | `1d1c4dec30aaf2db78d6a8e989471e49e316825ad7b337ef48a3f6c70fe1ca09` | PASS |
| `logs/test_runner_20260903_194921_609185_dba96507.log` | 399 | `f52d6e58aa1f91c90b244c121539c607b204ba1a35e43b56425f69596d08705c` | PASS |


### artifacts/screenshots/ (4 Files)

| Relative Path | Size (Bytes) | SHA-256 Checksum | Non-Zero? |
| :--- | :---: | :--- | :---: |
| `screenshots/cscape_compile_proof.png` | 63,170 | `0ab9a33b288331ce425e661e861b8e4a9b952873ca87d8172d70c93cfc1f9158` | PASS |
| `screenshots/cscape_open_proof.png` | 56,902 | `38cdbc63e86be6ac9adf77493b679a5b2582c6bbe22b94322506fd62b432639d` | PASS |
| `screenshots/tank_level_closed_loop_opened.png` | 58,030 | `592ba49fbc2977af21de1fa70ba0044ae34c68985c859a7c08b630a0209fc5b1` | PASS |
| `screenshots/test_desktop.png` | 2,909 | `568bd42b1fe3c8ff40b1acfbccfd93a3e51190d5f5ff0896ccafa0b881faf90d` | PASS |


### artifacts/conversions/ (2 Files)

| Relative Path | Size (Bytes) | SHA-256 Checksum | Non-Zero? |
| :--- | :---: | :--- | :---: |
| `conversions/tank_level_converted.ladder` | 11,052 | `0448c8bab312f68a56f9c1b6bdd4c15105512305158e0c7ebaa294a54960ffe7` | PASS |
| `conversions/tank_level_st_to_ladder_proof.txt` | 5,491 | `a2d3c86eac683b2904dd39f1900144ba2f4dc4f93964642b6ed39f354aa6e1a0` | PASS |


### artifacts/projects/ (118 Files)

| Relative Path | Size (Bytes) | SHA-256 Checksum | Non-Zero? |
| :--- | :---: | :--- | :---: |
| `projects/Fail_Ladder_Location_Proj/artifacts/build.log` | 1,109 | `fb22c54b52d0db84aeb4b2b4a216f56e7d23e423882f07444be94f8a96cca01d` | PASS |
| `projects/Fail_Ladder_Location_Proj/cscape_project.json` | 344 | `236c10eb96f780cab372be43e8db85579b93c6ea2179f2db55d4b45c5da5d304` | PASS |
| `projects/Fail_Ladder_Location_Proj/Fail_Ladder_Location_Proj.csp` | 49,152 | `d075e67d80be031a99a6895078735918b7a15c8086590a6d20ec8484b27749af` | PASS |
| `projects/Fail_Ladder_Location_Proj/pous/POU_LadderInjection.st` | 131 | `de50b4132e8a216335bee2cf0acd1ac9130d73c7831c3de8b7b0eb47c730c725` | PASS |
| `projects/Fail_Ladder_Log_Project/artifacts/build.log` | 1,107 | `027b35a1fa14458a038c4a738fc6604df10670e9a986e8bf035f8467b300dae2` | PASS |
| `projects/Fail_Ladder_Log_Project/cscape_project.json` | 342 | `cb4ade3598016511becacd227b698926941497d29067243da217d19bfbd23e1a` | PASS |
| `projects/Fail_Ladder_Log_Project/Fail_Ladder_Log_Project.csp` | 49,152 | `d075e67d80be031a99a6895078735918b7a15c8086590a6d20ec8484b27749af` | PASS |
| `projects/Fail_Ladder_Log_Project/pous/POU_LadderInjection.st` | 131 | `de50b4132e8a216335bee2cf0acd1ac9130d73c7831c3de8b7b0eb47c730c725` | PASS |
| `projects/Fail_Semicolon_Location_Proj/artifacts/build.log` | 799 | `b430b114a7185935906bf2d1018418621c33744cd408f49af187384e7e42de39` | PASS |
| `projects/Fail_Semicolon_Location_Proj/cscape_project.json` | 335 | `65a268b3ed7038a7d0cb3d064398195173cbe782cb08850cfe7bacc9dbb528c3` | PASS |
| `projects/Fail_Semicolon_Location_Proj/Fail_Semicolon_Location_Proj.csp` | 49,152 | `d075e67d80be031a99a6895078735918b7a15c8086590a6d20ec8484b27749af` | PASS |
| `projects/Fail_Semicolon_Location_Proj/pous/POU_MissingSemicolon.st` | 102 | `d1dfdeef531c99340d9bd1f8c337ad1e222587a0608ac8a8a32a2b2e8a88ce7e` | PASS |
| `projects/Fail_Semicolon_Log_Project/artifacts/build.log` | 797 | `992e610426f34b1607b55e4d88e5c364e392780172148c22c5339c4bd999c0c6` | PASS |
| `projects/Fail_Semicolon_Log_Project/cscape_project.json` | 333 | `2aa487786af384f04c855ba00255f1bf00bc434cf5943a11da7d9d22e3443004` | PASS |
| `projects/Fail_Semicolon_Log_Project/Fail_Semicolon_Log_Project.csp` | 49,152 | `d075e67d80be031a99a6895078735918b7a15c8086590a6d20ec8484b27749af` | PASS |
| `projects/Fail_Semicolon_Log_Project/pous/POU_MissingSemicolon.st` | 102 | `d1dfdeef531c99340d9bd1f8c337ad1e222587a0608ac8a8a32a2b2e8a88ce7e` | PASS |
| `projects/Fail_Syntax_Location_Proj/artifacts/build.log` | 1,113 | `fee9907232ffc152e828504da730ceb3497cc473415dec04642e1b2275d4f085` | PASS |
| `projects/Fail_Syntax_Location_Proj/cscape_project.json` | 337 | `41b5239beaf46e2b0f375000384ffd0ab06645154505110f9d3e3f5ddf339237` | PASS |
| `projects/Fail_Syntax_Location_Proj/Fail_Syntax_Location_Proj.csp` | 49,152 | `d075e67d80be031a99a6895078735918b7a15c8086590a6d20ec8484b27749af` | PASS |
| `projects/Fail_Syntax_Location_Proj/pous/POU_SyntaxError.st` | 179 | `155da7728100dcfd02fbec374b8a2db99d05c3e7780cac0efbea3fc9a950a427` | PASS |
| `projects/Fail_Syntax_Log_Project/artifacts/build.log` | 1,111 | `c3300a15ccf6bceda0abe089166a7e8a66a1618b9e8b0cea0a738360cc2fe8c9` | PASS |
| `projects/Fail_Syntax_Log_Project/cscape_project.json` | 335 | `5229f4108737569c8835c09d69017c4af2decc05e81f3bf9daf20075c670d83f` | PASS |
| `projects/Fail_Syntax_Log_Project/Fail_Syntax_Log_Project.csp` | 49,152 | `d075e67d80be031a99a6895078735918b7a15c8086590a6d20ec8484b27749af` | PASS |
| `projects/Fail_Syntax_Log_Project/pous/POU_SyntaxError.st` | 154 | `4e1134e0de9d61ce97489a1b76ef20ccb28909a70f7888626a194071327c7ad8` | PASS |
| `projects/Fail_SyntaxNearSemi_Location_Proj/artifacts/build.log` | 697 | `f2497dbec79ee70d2b60e05e544e20deba93b3e2e75a5f7a63607e3fde22c3c5` | PASS |
| `projects/Fail_SyntaxNearSemi_Location_Proj/cscape_project.json` | 356 | `c162bc77dd6656d3796d338a70552bd1410acc3f7a8b21f49938711b365f09a2` | PASS |
| `projects/Fail_SyntaxNearSemi_Location_Proj/Fail_SyntaxNearSemi_Location_Proj.csp` | 49,152 | `d075e67d80be031a99a6895078735918b7a15c8086590a6d20ec8484b27749af` | PASS |
| `projects/Fail_SyntaxNearSemi_Location_Proj/pous/POU_SyntaxNearSemi.st` | 151 | `979b976166a61e64ac3cfb637639df6b92ef348407e0c234ee222169e46e31f9` | PASS |
| `projects/Fail_Undeclared_Location_Proj/artifacts/build.log` | 785 | `525a79f90c7252cdeba0b249ac1eb9748d11d6629a02b60140084851bfd694ff` | PASS |
| `projects/Fail_Undeclared_Location_Proj/cscape_project.json` | 348 | `2e7444dbb24dcc362a9fbd6dee0d1ee866c16b49610258998c70e15735a6cb8d` | PASS |
| `projects/Fail_Undeclared_Location_Proj/Fail_Undeclared_Location_Proj.csp` | 49,152 | `d075e67d80be031a99a6895078735918b7a15c8086590a6d20ec8484b27749af` | PASS |
| `projects/Fail_Undeclared_Location_Proj/pous/POU_UndeclaredVar.st` | 108 | `8456a7d2414e0c2a5f7867bb963b051bfd089648b181bf353bc522800a2caea2` | PASS |
| `projects/Fail_Undeclared_Log_Project/artifacts/build.log` | 783 | `16d65eb86a0923e99c1c2944f98d7dfeceacc8ecd5e9d60512a9defc17098f4a` | PASS |
| `projects/Fail_Undeclared_Log_Project/cscape_project.json` | 346 | `37e6c662b0a049cf32f831b0b24e056a67bf378cfb9c24aa83f3797877276b2e` | PASS |
| `projects/Fail_Undeclared_Log_Project/Fail_Undeclared_Log_Project.csp` | 49,152 | `d075e67d80be031a99a6895078735918b7a15c8086590a6d20ec8484b27749af` | PASS |
| `projects/Fail_Undeclared_Log_Project/pous/POU_UndeclaredVar.st` | 108 | `8456a7d2414e0c2a5f7867bb963b051bfd089648b181bf353bc522800a2caea2` | PASS |
| `projects/FailAudit_POU_LadderInjection/artifacts/build.log` | 1,116 | `9a3bd5f93df771982deaed89c501c8b371b8d534ea99dba99ad12cf2c8d7d8e1` | PASS |
| `projects/FailAudit_POU_LadderInjection/cscape_project.json` | 326 | `895bcdfd0a8d12f970e39e6a6e16853a2c94bff4da203bda267df621c9b9b4ee` | PASS |
| `projects/FailAudit_POU_LadderInjection/FailAudit_POU_LadderInjection.csp` | 49,152 | `d075e67d80be031a99a6895078735918b7a15c8086590a6d20ec8484b27749af` | PASS |
| `projects/FailAudit_POU_LadderInjection/pous/POU_LadderInjection.st` | 112 | `a913bb893d276aa78550c769757a024109f1e08441853ff8404a0747978cfae6` | PASS |
| `projects/FailAudit_POU_MissingSemicolon/artifacts/build.log` | 800 | `cbeb712213efffcd95a254c6ed335750a7d1b3ec8bda68b6533c93a9716d7324` | PASS |
| `projects/FailAudit_POU_MissingSemicolon/cscape_project.json` | 312 | `f20fbfe72b8cde8b763b03de458c6991e62d89b952216b15986206232da1cdda` | PASS |
| `projects/FailAudit_POU_MissingSemicolon/FailAudit_POU_MissingSemicolon.csp` | 49,152 | `d075e67d80be031a99a6895078735918b7a15c8086590a6d20ec8484b27749af` | PASS |
| `projects/FailAudit_POU_MissingSemicolon/pous/POU_MissingSemicolon.st` | 104 | `f14f14c2ad1fdb03ee4a475039ab88aec2b730598312107a98f980a4a3f4b406` | PASS |
| `projects/FailAudit_POU_UnclosedIf/artifacts/build.log` | 1,103 | `2d6d6d8255a3046ecc3793c92305b049e0639e8e64551380a1142316f05e8daf` | PASS |
| `projects/FailAudit_POU_UnclosedIf/cscape_project.json` | 311 | `4483c86ef9b99c8ef0da6d11f1da25ddc9cdf872a50e438bae5ab27d75b1eb8b` | PASS |
| `projects/FailAudit_POU_UnclosedIf/FailAudit_POU_UnclosedIf.csp` | 49,152 | `d075e67d80be031a99a6895078735918b7a15c8086590a6d20ec8484b27749af` | PASS |
| `projects/FailAudit_POU_UnclosedIf/pous/POU_UnclosedIf.st` | 158 | `beebb73d58af7632c8060b946edd2374841db4856a3b46a488b8ce7545f91f29` | PASS |
| `projects/FailAudit_POU_UndeclaredVariable/artifacts/build.log` | 811 | `751036b2a30058514cf1157a9e707fcaa3a7a961dff1f99f71f3c975694c2352` | PASS |
| `projects/FailAudit_POU_UndeclaredVariable/cscape_project.json` | 315 | `141ae7309a0c3a38ba9d2222ffb7cd829c9b20ce926c320a25770df340aaecd5` | PASS |
| `projects/FailAudit_POU_UndeclaredVariable/FailAudit_POU_UndeclaredVariable.csp` | 49,152 | `d075e67d80be031a99a6895078735918b7a15c8086590a6d20ec8484b27749af` | PASS |
| `projects/FailAudit_POU_UndeclaredVariable/pous/POU_UndeclaredVariable.st` | 119 | `a0a192966dbe2f1319504bdc1491afec048fc25b4caaf91d0a58b6785ab60e22` | PASS |
| `projects/live_iec_test_1788493128.csp` | 49,152 | `3131b5a10b034a1a464ba62b7c348719518623dfcca44fdaf966d1c51d09552c` | PASS |
| `projects/live_iec_test_1788493199.csp` | 49,152 | `113c2ded22c8c443678ba59ce54608bccb1997e573e62b64f62f9becd66666b6` | PASS |
| `projects/live_iec_test_1788493255.csp` | 49,152 | `eac90f102cb19a500811dd8b7f5b38b8854396de3c935a9ccb08e767192599c3` | PASS |
| `projects/live_iec_test_1788493297.csp` | 49,152 | `74e5f91ba6cc7f7ad5c7e65261681979e3d65d9704a11aa33873d7158f7db192` | PASS |
| `projects/live_iec_test_1788493338.csp` | 49,152 | `cf14911da8190a60a4828cc49c29cfd31559f11775ccc8f2851aea791db203f8` | PASS |
| `projects/live_iec_test_1788493820.csp` | 49,152 | `8acc29b042fbb0f66a3b93ea942a513f2d16e126af1c62662731d35afa43a777` | PASS |
| `projects/live_iec_test_1788499624.csp` | 49,152 | `d25407fd63e4c2b74f463d9e5279626062cf12cfa2b57e3c55d11725aaeaf7c1` | PASS |
| `projects/LiveGUI_Verification_Proj/cscape_project.json` | 318 | `d96ab3fd78c9456937b74045a780cbb6ef301c7ba275360df6655c50f4095012` | PASS |
| `projects/LiveGUI_Verification_Proj/LiveGUI_Verification_Proj.csp` | 49,152 | `d075e67d80be031a99a6895078735918b7a15c8086590a6d20ec8484b27749af` | PASS |
| `projects/LiveTest_MCP_1/cscape_project.json` | 292 | `bc843ca0f4ff36a3986cdb16f8efc0e0200ff4e273caa1609c0d00526ba743be` | PASS |
| `projects/LiveTest_MCP_1/LiveTest_MCP_1.csp` | 49,152 | `2afa898f5acbabea3e2781912987c4329c711d03f6dcc96692e9c8a707b4c329` | PASS |
| `projects/MCP_ClosedLoop_Master_Audit/artifacts/build.log` | 604 | `19fe5341d55dd8dd45d9ea6df4e0db8156f16b46f54584e139a0f513eeeff902` | PASS |
| `projects/MCP_ClosedLoop_Master_Audit/cscape_project.json` | 319 | `e64be491c69aa5ec0110030a355b9a4457229370d199f941989c361a4ba58188` | PASS |
| `projects/MCP_ClosedLoop_Master_Audit/MCP_ClosedLoop_Master_Audit.csp` | 49,152 | `d075e67d80be031a99a6895078735918b7a15c8086590a6d20ec8484b27749af` | PASS |
| `projects/MCP_ClosedLoop_Master_Audit/pous/TankLevelPID.st` | 1,062 | `ff7fa85fdedbddfa0ef3c6acce2782bc4f8f7fb6a23775d4e640e05af593d475` | PASS |
| `projects/new_iec_st_project.csp` | 49,152 | `d075e67d80be031a99a6895078735918b7a15c8086590a6d20ec8484b27749af` | PASS |
| `projects/TankLevelClosedLoop/artifacts/build.log` | 610 | `25f077ddeb5025fca442d8ddd319087aa37c479823bce996d41a85983ffccbbf` | PASS |
| `projects/TankLevelClosedLoop/cscape_project.json` | 850 | `c2f188c6a1a55befe1865b65b50a5cb0401b0e239fbf179a7dec5971ba37edcc` | PASS |
| `projects/TankLevelClosedLoop/pous/TankLevelClosedLoop.st` | 2,599 | `7fd73e139c3c6475dd0f4c84351c339a0c66b96f2b160f452fc2564017de7ea9` | PASS |
| `projects/TankLevelClosedLoop/sample_vars.csv` | 151 | `7c5be9709f559462da40c10b1ddc5360fb8754c5dabc05f8cff7f3f9a0b316d7` | PASS |
| `projects/TankLevelClosedLoop/TankLevelClosedLoop.csp` | 49,152 | `d075e67d80be031a99a6895078735918b7a15c8086590a6d20ec8484b27749af` | PASS |
| `projects/TankLevelClosedLoop/variables.csv` | 2,166 | `d78f07a0036d0f498b79192e6708a83e2a722751dc9701a0601be85709311a16` | PASS |
| `projects/TankLevelClosedLoop/variables.xml` | 4,022 | `2a25cf197f5e4a66c2d5170f125d1e090252b6ad40e159f223c374a692e98d99` | PASS |
| `projects/TankLevelFailureTest/artifacts/build.log` | 788 | `e0cd53a50a06195427cde33249cccd7ad0a4c20f0b65e39eb56a9c4561a0fca3` | PASS |
| `projects/TankLevelFailureTest/cscape_project.json` | 331 | `56b3924dfed1899c374dd892051fda13a2f0a7deda4ab9872debba24cf1d5717` | PASS |
| `projects/TankLevelFailureTest/pous/TankLevelFailureTest.st` | 151 | `803d03a0bd28bc785f68df125844400a4edb07ee73b40ecd84be2e2c43d965e0` | PASS |
| `projects/TankLevelFailureTest/pous/TankLevelValid.st` | 240 | `9878c9096cc9e670985e279e9dcf6712a5f4f0c625176a7f14282f61d1cc2823` | PASS |
| `projects/TankLevelFailureTest/TankLevelFailureTest.csp` | 49,152 | `d075e67d80be031a99a6895078735918b7a15c8086590a6d20ec8484b27749af` | PASS |
| `projects/TempTest/artifacts/build.log` | 676 | `7c53fb1ff0e3c2ff6eda02572fe0ea0607fbc9e2ff6946acd466be5e048eb90f` | PASS |
| `projects/TempTest/cscape_project.json` | 261 | `6aeb54ff3abdebdb18f7e3fd00b1f3c6d6bcfc1f55563d3f18ba914dc093a7ca` | PASS |
| `projects/TempTest/pous/TankLevelFailureTest.st` | 153 | `d29ca15fa4d7e54d45a4443ef3a0b7648e81e05334bff75d640a0051ab2e9112` | PASS |
| `projects/TempTest/TempTest.csp` | 49,152 | `d075e67d80be031a99a6895078735918b7a15c8086590a6d20ec8484b27749af` | PASS |
| `projects/test_runs/live_iec_test_1788493255.csp` | 49,152 | `eac90f102cb19a500811dd8b7f5b38b8854396de3c935a9ccb08e767192599c3` | PASS |
| `projects/test_runs/live_iec_test_1788493297.csp` | 49,152 | `74e5f91ba6cc7f7ad5c7e65261681979e3d65d9704a11aa33873d7158f7db192` | PASS |
| `projects/test_runs/live_iec_test_1788493338.csp` | 49,152 | `cf14911da8190a60a4828cc49c29cfd31559f11775ccc8f2851aea791db203f8` | PASS |
| `projects/test_runs/live_iec_test_1788493820.csp` | 49,152 | `8acc29b042fbb0f66a3b93ea942a513f2d16e126af1c62662731d35afa43a777` | PASS |
| `projects/test_runs/live_iec_test_1788499624.csp` | 49,152 | `d25407fd63e4c2b74f463d9e5279626062cf12cfa2b57e3c55d11725aaeaf7c1` | PASS |
| `projects/test_runs/live_iec_test_1788500906.csp` | 49,152 | `a78226929e841b06f19b0bac89d05b751449c3e0e98c01004c814dc36ff36732` | PASS |
| `projects/test_runs/live_iec_test_1788501252.csp` | 49,152 | `3c4cb9ad0cb1659aa1f6cd472b5fbc35a0bd8fff878d0370df41ec7436dc28e2` | PASS |
| `projects/test_runs/live_iec_test_1788501409.csp` | 49,152 | `5605eb0a3a5b9b5dc062595eb0eb9f19a8cfa8b8544f3d2ef1a50da9e7743209` | PASS |
| `projects/test_runs/live_iec_test_1788501462.csp` | 49,152 | `8e3cd9f27251381e914883b8f96173b3ee78b0622cfc37948c7a281af434a391` | PASS |
| `projects/test_runs/live_iec_test_1788501605.csp` | 47,104 | `9d851f68542a34084c7acfa0bc02e3302cb301dea4226d05874f71cffa38929e` | PASS |
| `projects/test_runs/live_iec_test_1788502437.csp` | 49,152 | `c419aae006e25d3efd609492886aea077200431e6af09405949676b53dc28999` | PASS |
| `projects/test_runs/live_iec_test_1788505846.csp` | 49,152 | `ebd069b8246313036bb00639a82231f4eef2f64ce46540c1a74556e3e057ef1f` | PASS |
| `projects/test_runs/live_iec_test_1788540072.csp` | 47,104 | `f14a475454eba5c62e60a7f9278655d14219fee1504b786bd88447e0cf7cc75d` | PASS |
| `projects/test_runs/live_iec_test_1788541670.csp` | 47,104 | `a88b07aad67fa7a88862f362473cd68f861c4725560a921749a700a8c59791ac` | PASS |
| `projects/test_runs/live_iec_test_1788542496.csp` | 49,152 | `731233a99099792c87d2360d4dd1efbd403436cf8a90bce7eab9a501abcb5584` | PASS |
| `projects/test_runs/live_iec_test_1788544624.csp` | 49,152 | `ff00a819cdc8a2f64575f445287035640f891bfa995581e74f47dbdc15e369da` | PASS |
| `projects/test_runs/live_iec_test_1788546312.csp` | 49,152 | `1f3bcc0134435a30e061846346f66196adff9df57029532f5d9fbd11be14d623` | PASS |
| `projects/test_runs/live_iec_test_1788546530.csp` | 49,152 | `e0ae2af3ae6e2dfab64a3e3ce7e4b1ff8b924763ed48c0bf9746a410ca40de0b` | PASS |
| `projects/test_runs/live_iec_test_1788548431.csp` | 49,152 | `44e32da750bee18e3288681bbbe276ed5ae42cc4f8ef3d310bc7eb2db561425c` | PASS |
| `projects/test_runs/live_iec_test_1788548523.csp` | 49,152 | `a8c2e50e7cd1848cb74c1bd79c49c23dcaccdb6dd2e17c2f3b5cd0abb471e8bb` | PASS |
| `projects/test_runs/live_iec_test_1788548762.csp` | 49,152 | `95c5f0ffb00be6f177d4decbdf2458917a37f3bf40d9dcd99a3e42958998e8dd` | PASS |
| `projects/test_runs/live_iec_test_1788554138.csp` | 49,152 | `c3bf7d1b26c1a695c2e3f59049c5d9aad210096830d582809290c59d989ddda8` | PASS |
| `projects/test_runs/live_iec_test_1788556441.csp` | 49,152 | `06902f0cb132e8521a7be7f845c576f096d4ee0c4a92d27a2ac2921f8755e687` | PASS |
| `projects/test_runs/live_iec_test_1788558184.csp` | 47,104 | `cfc3ee16fb55c6b029789fcd79f8b189bdbf17d27c410249444db6bae5bc17f4` | PASS |
| `projects/test_runs/live_iec_test_copy.csp` | 49,152 | `eac90f102cb19a500811dd8b7f5b38b8854396de3c935a9ccb08e767192599c3` | PASS |
| `projects/test_runs/synthesized.csp` | 2,048 | `207e5374293c1bdb6e146641291d739e6a3b74f06b9a55b4f280fc0026423c7e` | PASS |
| `projects/test_runs/test_copy.csp` | 5,120 | `b7c2b5bb056852410e5bb93db53667057fd869efd39575dcb21f0527a7e691ec` | PASS |
| `projects/test_save_iec.csp` | 49,152 | `c9bf22d2d9f42fe3b15bea2780df24b94339f7de810319a9edc0ac023770b5b3` | PASS |
| `projects/TestLiveProj/cscape_project.json` | 265 | `9e44b00ed0090c001a517d9114caf4feced8b3fb0e0623eb57c1b9de3757d57c` | PASS |
| `projects/TestLiveProj/TestLiveProj.csp` | 49,152 | `d075e67d80be031a99a6895078735918b7a15c8086590a6d20ec8484b27749af` | PASS |
| `projects/Verification_Master_Project/artifacts/build.log` | 611 | `97bfb49fdbb5b0c1d91a2b016d2574064e0218d89f0794cadc454ba8c35150a4` | PASS |
| `projects/Verification_Master_Project/cscape_project.json` | 299 | `7004312eee881269fd839edad28479296e835948093734aa5a571f37e7a920d7` | PASS |
| `projects/Verification_Master_Project/pous/TankLevelControl.st` | 581 | `35ae42864da3760d64f2385442109139b524b82d5d6340661758349ebbe0ceac` | PASS |
| `projects/Verification_Master_Project/Verification_Master_Project.csp` | 49,152 | `d075e67d80be031a99a6895078735918b7a15c8086590a6d20ec8484b27749af` | PASS |


### Additional Repository Evidence & Exports

- **Root Artifact Files (3)**:
  - `build.log` (564 bytes) | SHA-256: `f84b33ba7f1b23c6e5043e5f7eec5d5ef021a1c3efd3920b9ef56fe75d586afd` | Non-Zero: `PASS`
  - `failure_location_report.json` (3,739 bytes) | SHA-256: `cf5161c0a994e3bcb9fa89ce7b740da203a3342b2081b0ecc37f319ac81e9cbc` | Non-Zero: `PASS`
  - `quarantine_integrity_audit_raw.json` (60,503 bytes) | SHA-256: `46ab648f309c5ef8334d8a86476f8218fa7877028b890d14f58adc3f71682035` | Non-Zero: `PASS`
- **Export Packages (20 items in `artifacts/exports/`)**: Verified valid non-zero payloads.

## 4. Certification Conclusion & Attestation

All 141 evidence artifacts across `artifacts/logs/`, `artifacts/screenshots/`, `artifacts/conversions/`, and `artifacts/projects/` have been comprehensively validated:
1. **100% Non-Zero Byte Verification**: 0 empty or truncated files.
2. **Cryptographic Integrity**: SHA-256 digests computed and verified for every single artifact.
3. **Process Cleanliness**: Absence of orphaned `Cscape.exe` instances confirmed.
4. **Zero PLC Download Compliance**: Strict fail-closed air-gap lockout verified without exception.

**Certified by Cryptographic Evidence Certifier (Subagent `dfc028f2-c0db-4154-890f-abbc9a2d23da`)**.
