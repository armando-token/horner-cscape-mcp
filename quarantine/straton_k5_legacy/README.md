# Quarantined Legacy Straton K5 Code

## Quarantine Reason
Under the HAOR CORRECTION directive, the primary architecture must target real Horner Cscape 10.2 at C:\Program Files (x86)\Cscape 10.2\Cscape.exe and native .csp/.cpj files, rather than relying on pure Straton K5 file mocks.

## Quarantined Components
1. template_project/: Pure Straton K5 project template directories.
2. legacy_project_manager.py: Synthetic generator for appli.k5p, appli.CPO, appli.lge, and K5DBXS.INI (quarantined from src/project/manager.py).
3. legacy_project___init__.py: Package init for legacy project manager (quarantined from src/project/__init__.py).
4. legacy_automation_project_manager.py: Legacy automation manager relying on mock K5 files and bytecode estimation (quarantined from src/automation/project_manager.py).
5. legacy_iec_project_builder.py: Legacy project builder with embedded fallback Straton templates (quarantined from src/iec/project_builder.py).
6. fixtures/sample_project/: Legacy sample Straton files (appli.k5p, appli.CPO, appli.lge, K5DBXS.INI, Default/appli.txt).
7. artifacts/exports/: Quarantined legacy export files (async_mcp_test_proj.k5p, test_unit_project.k5p, test_unit_project_straton.xml).
8. test_legacy_iec_project_builder.py: Quarantined tests for legacy project builder (quarantined from tests/test_iec_st.py).

## Active Real Cscape Architecture
All real automation is now located in src/cscape/:
- src/cscape/lifecycle.py: Live Cscape 10.2 process lifecycle and dialog suppression.
- src/cscape/project_manager.py: Native .csp and .cpj project creation and CFBF OLE2 verification.
- src/cscape/st_inserter.py: Programmatic Structured Text POU injection.
- src/cscape/compiler.py: Live Cscape compilation and error check output scraping.
- src/cscape/st_ld_interop.py: IEC 61131-3 ST enforcement and Ladder rejection.
- src/cscape/variables.py: Horner OCS variable database XML/CSV manager.
- src/cscape/simulation.py: Horner OCS %R/%M/%T/%AI/%AQ/%I/%Q register simulation engine.
