# FastMCP Tool Capability Matrix (40 Tools)

| Tool Name | Scope | Operational Mode | Return Contract |
| :--- | :--- | :--- | :--- |
| `cscape_launch_ide` | Process Lifecycle | Live GUI | `status: success | failed | blocked` |
| `cscape_new_iec_project` | Container Init | Live GUI / CFBF | `status: success | failed | blocked` |
| `cscape_open_project` | Project Open | Live GUI / CFBF | `status: success | failed | blocked` |
| `cscape_insert_st` | ST Insertion | ST Editor | `status: success | failed | blocked` |
| `cscape_insert_st_pou` | POU Ingestion | ST AST | `status: success | failed | blocked` |
| `cscape_compile` | Error Check (32826) | Live GUI | `status: success | failed | blocked` |
| `cscape_get_build_output`| Output Window | Live GUI ListBox | `status: success | failed | blocked` |
| `cscape_read_variables` | OCS Map | Memory Model | `status: success | failed | blocked` |
| `cscape_write_variables`| OCS Map | Memory Model | `status: success | failed | blocked` |
| `cscape_import_variables`| Tag Import | CSV / Table | `status: success | failed | blocked` |
| `cscape_export_variables`| Tag Export | CSV / Table | `status: success | failed | blocked` |
| `cscape_run_simulation` | Scan Runner | In-Memory | `status: success | failed | blocked` |
| `cscape_create_project` | CFBF Init | Pure CFBF OLE2 | `status: success | failed | blocked` |
| `cscape_add_st_pou` | Transactional POU | Pure ST | `status: success | failed | blocked` |
| `cscape_validate_st` | AST Validator | Pure ST / No Ladder| `status: success | failed | blocked` |
| `cscape_inspect_variables`| OCS Memory Map | Variable Table | `status: success | failed | blocked` |
| `cscape_compile_project`| Compiler Check | 32826 / AST | `status: success | failed | blocked` |
| `cscape_get_diagnostics`| Compiler Markers | Diagnostic Stream | `status: success | failed | blocked` |
| `cscape_simulate_pou` | Multi-Cycle Scan | In-Memory | `status: success | failed | blocked` |
| `cscape_export_project` | Structured Export | Interchange JSON | `status: success | failed | blocked` |
| `cscape_simulate_cycle` | Single Scan Cycle| In-Memory | `status: success | failed | blocked` |
| `cscape_read_register` | Register Query | Horner OCS Model | `status: success | failed | blocked` |
| `cscape_write_register`| Register Modify| Horner OCS Model | `status: success | failed | blocked` |
| `cscape_hmi_inventory` | Screen Inventory | HMI Object Model | `status: success | failed | blocked` |
| `cscape_hmi_apply_group`| Group Mutation | HMI Screen Data | `status: success | failed | blocked` |
| `cscape_hmi_read_properties`| Property Query| HMI Screen Data | `status: success | failed | blocked` |
| `cscape_hmi_verify_bindings`| Variable Bindings| HMI & OCS Table| `status: success | failed | blocked` |
| `cscape_hmi_save_close_reopen`| Durability Cycle| Live GUI MDI | `status: success | failed | blocked` |
| `cscape_fixture_request_to_spec`| Natural Lang Spec| AST Parser | `status: success | failed | blocked` |
| `cscape_fixture_create` | Project Fixture | CFBF Evolution | `status: success | failed | blocked` |
| `cscape_fixture_selective_edit`| Selective Mutation| ST & HMI Editor | `status: success | failed | blocked` |
| `cscape_fixture_revision_impact`| Impact Analysis | AST Diff Engine | `status: success | failed | blocked` |
| `cscape_fixture_durability_check`| Durability Cycle| Live GUI Check | `status: success | failed | blocked` |
| `cscape_fixture_detect_conflict`| Conflict Detection| SHA-256 Check | `status: failed (ERR_EXTERNAL_CONFLICT)` |
| `cscape_modbus_create_config`| Modbus Inventory | Data Model | `status: success | failed | blocked` |
| `cscape_modbus_persist_config`| Sidecar & ST | CFBF & ST Logic | `status: success | failed | blocked` |
| `cscape_modbus_read_config` | Sidecar Re-read | Data Model | `status: success | failed | blocked` |
| `cscape_modbus_protocol_check`| Labeled Endpoint| Modbus MBAP/PDU | `status: success | failed | blocked` |
| `cscape_modbus_conversion_doc`| Mathematical Doc| Protocol Walkthrough| `status: success | failed | blocked` |
| `cscape_package_offline_bundle`| Air-Gapped Packaging| Offline Bundler | `status: success | failed | blocked` |
