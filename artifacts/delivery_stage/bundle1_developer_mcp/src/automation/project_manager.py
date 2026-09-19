"""
Horner Cscape Legacy Automation Project Manager Adapter.

Delegates cleanly to src/cscape/ and native CFBF files without any Straton K5 dependencies.
Provides high-level project management, ST POU lifecycle, variable introspection,
native compilation, and simulation dispatch.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from src.cscape.compiler import CscapeCompiler, CscapeBuildResult
from src.cscape.project_manager import (
    CFBF_MAGIC,
    CscapeLiveProjectManager,
    ProjectCreationResult,
    ProjectFileInfo,
    create_new_iec_project,
    open_project as cscape_open,
    cscape_open_project,
    export_project as cscape_export,
    cscape_export_project as _cscape_export_pm,
    resolve_cscape_pid,
)
from src.cscape.st_ld_interop import STLadderInteropGuard, LadderConstructRejectedError
from src.cscape.variables import CscapeVariable, CscapeVariableManager
from src.security.policy import SecurityConfig
from src.security.guard import SafetyGuard, SecurityError
from src.parser.parser import Parser

logger = logging.getLogger(__name__)


class ProjectManager:
    """Legacy adapter for automation project management delegating cleanly to src/cscape/"""

    DEFAULT_WORKSPACE = (
        Path(os.environ.get("HORNER_WORKSPACE", ""))
        if os.environ.get("HORNER_WORKSPACE")
        else Path.cwd()
        if (Path.cwd() / "artifacts").exists()
        else Path(r".")
        if Path(r".\artifacts").exists()
        else Path("C:/HornerAI/horner-cscape-mcp")
    )

    def __init__(self, workspace_root: Optional[Union[str, Path]] = None):
        self.workspace = Path(workspace_root) if workspace_root else self.DEFAULT_WORKSPACE
        self.projects_dir = self.workspace / "artifacts" / "projects"
        self.exports_dir = self.workspace / "artifacts" / "exports"
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.exports_dir.mkdir(parents=True, exist_ok=True)
        self._last_diagnostics: Dict[str, Any] = {}

    def _get_project_dir(self, project_name: str) -> Path:
        clean_name = SafetyGuard.validate_project_name(project_name)
        return self.projects_dir / clean_name

    def open_project(
        self,
        project_name_or_path: Union[str, Path],
        read_only: bool = False,
        timeout_sec: float = 30.0,
    ) -> Dict[str, Any]:
        """Opens and verifies an authentic Horner Cscape native project (.csp / .cpj).

        Validates genuine CFBF OLE2 container, directory entries, streams, and Horner tags.
        Prevents double-open modal traps and handles dirty project prompts cleanly.
        """
        raw_path = Path(project_name_or_path)
        if raw_path.suffix.lower() in (".csp", ".cpj") and raw_path.exists():
            target_path = raw_path.resolve()
        else:
            proj_name = str(project_name_or_path).rstrip("/\\")
            proj_name = Path(proj_name).stem
            p_dir = self._get_project_dir(proj_name)
            target_path = p_dir / f"{proj_name}.csp"
            if not target_path.exists():
                alt_path = self.projects_dir / f"{proj_name}.csp"
                if alt_path.exists():
                    target_path = alt_path

        if not target_path.exists():
            raise FileNotFoundError(f"Project file '{target_path}' does not exist.")

        res = cscape_open_project(
            file_path=target_path,
            read_only=read_only,
            timeout_seconds=timeout_sec,
        )
        if not res.get("success", False):
            raise ValueError(res.get("message", "Failed to open and verify project file."))
        return res

    def create_project(
        self,
        name: str,
        description: str = "",
        target_plc: str = "XL4",
    ) -> Dict[str, Any]:
        """Creates a new Horner Cscape native project with genuine CFBF container.

        Zero Straton K5 dependencies.
        """
        from src.project.manager import CscapeProject

        p_dir = self._get_project_dir(name)
        project = CscapeProject.create(p_dir, name=name, controller=target_plc)

        file_info = None
        if project.csp_file.exists():
            try:
                info = CscapeLiveProjectManager.inspect_project_file(project.csp_file)
                file_info = info.to_dict()
            except Exception as e:
                logger.warning(f"Failed to inspect created CFBF file: {e}")

        return {
            "success": True,
            "project_name": name,
            "project_dir": str(p_dir),
            "csp_file": str(project.csp_file),
            "format": "CFBF_OLE2",
            "editor_mode": "IEC 61131",
            "controller": target_plc,
            "description": description,
            "file_info": file_info,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    def add_st_pou(
        self,
        project_name: str,
        pou_name: str,
        st_code: str,
        pou_type: str = "PROGRAM",
        cycle_time_ms: int = 10,
    ) -> Dict[str, Any]:
        """Adds and validates an IEC 61131-3 Structured Text POU.

        Rejects ladder logic.
        """
        from src.project.manager import CscapeProject

        p_dir = self._get_project_dir(project_name)
        if not p_dir.exists():
            raise FileNotFoundError(f"Project '{project_name}' does not exist.")

        project = CscapeProject.load(p_dir)
        pou_info = project.inject_pou(pou_name, st_code, pou_type=pou_type)

        return {
            "success": True,
            "project_name": project_name,
            "pou_name": pou_info.name,
            "pou_type": pou_info.pou_type,
            "file_path": pou_info.file_path,
            "variable_count": pou_info.variable_count,
            "statement_count": pou_info.statement_count,
        }

    def inspect_variables(self, project_name: str) -> Dict[str, Any]:
        """Inspects variables using CscapeVariableManager."""
        from src.cscape.variables import CscapeVariable, CscapeVariableManager

        p_dir = self._get_project_dir(project_name)
        if not p_dir.exists():
            raise FileNotFoundError(f"Project '{project_name}' does not exist.")

        vm = CscapeVariableManager()
        pous_dir = p_dir / "pous"
        if pous_dir.exists():
            for st_file in pous_dir.glob("*.st"):
                try:
                    code = st_file.read_text(encoding="utf-8", errors="replace")
                    p = Parser.from_source(code)
                    ast = p.parse()
                    for vb in ast.var_blocks:
                        for decl in vb.declarations:
                            scope_str = vb.block_type.name.lower() if hasattr(vb.block_type, "name") else "program"
                            cvar = CscapeVariable(
                                name=decl.name,
                                data_type=str(decl.data_type),
                                scope=scope_str,
                            )
                            vm.add_variable(cvar)
                except Exception as e:
                    logger.debug(f"Parsing error inspecting variables in {st_file}: {e}")

        vars_list = vm.list_variables()
        return {
            "project_name": project_name,
            "variable_count": len(vars_list),
            "variables": [v.to_dict() for v in vars_list],
            "conflicts": vm.detect_conflicts(),
        }

    def compile_project(self, project_name: str, clean_build: bool = True) -> Dict[str, Any]:
        """Compiles project POUs using CscapeCompiler."""
        p_dir = self._get_project_dir(project_name)
        if not p_dir.exists():
            raise FileNotFoundError(f"Project '{project_name}' does not exist.")

        compiler = CscapeCompiler(workspace_root=self.workspace)
        res = compiler.compile_project(p_dir, clean_build=clean_build)
        res_dict = res.to_dict()
        self._last_diagnostics[project_name] = res_dict
        return res_dict

    def get_diagnostics(self, project_name: str) -> Dict[str, Any]:
        """Retrieves last compile diagnostics."""
        return self._last_diagnostics.get(project_name, {"diagnostics": [], "status": "inconclusive"})

    def export_project(self, project_name: str, output_format: str = "csp") -> Dict[str, Any]:
        """Exports project in specified format (csp, cpj, csv, xml, st, json, zip).

        Enforces authentic CFBF headers and Horner markers for native Cscape containers (.csp, .cpj).
        Enforces CscapeVariableManager register scope handling without truncation for .csv and .xml.
        Enforces strict SafetyGuard sandbox and export validation policies.
        """
        p_dir = self._get_project_dir(project_name)
        if not p_dir.exists():
            raise FileNotFoundError(f"Project directory or source file not found: Project '{project_name}' does not exist.")

        raw_fmt = output_format.lower().strip()
        if raw_fmt in ("zip", "bundle", "cfbf", "structured_text"):
            clean_fmt = raw_fmt
        else:
            clean_fmt = SafetyGuard.validate_export_format(raw_fmt)

        timestamp = int(time.time())

        # Determine output path and handle quarantine if legacy k5p
        if clean_fmt == "k5p":
            out_dir = self.workspace / "quarantine" / "straton_k5_legacy" / "artifacts" / "exports"
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / f"{project_name}_{timestamp}.k5p"
        else:
            self.exports_dir.mkdir(parents=True, exist_ok=True)
            if clean_fmt in ("csp", "cfbf"):
                ext = "csp"
            elif clean_fmt == "cpj":
                ext = "cpj"
            elif clean_fmt in ("st", "structured_text"):
                ext = "st"
            elif clean_fmt in ("zip", "bundle"):
                ext = "zip"
            else:
                ext = clean_fmt
            out_path = self.exports_dir / f"{project_name}_{timestamp}.{ext}"

        # Enforce sandbox and export policy
        guard = SafetyGuard(config=SecurityConfig(workspace_root=self.workspace))
        guard.validate_export(
            source_path=p_dir,
            destination_path=out_path,
            format=clean_fmt,
        )

        if clean_fmt in ("csp", "cpj", "cfbf"):
            target_ext = "cpj" if clean_fmt == "cpj" else "csp"
            source_file = None
            cand_files: List[Path] = [p_dir / f"{project_name}.{target_ext}"]
            for alt_ext in ("csp", "cpj"):
                alt_cand = p_dir / f"{project_name}.{alt_ext}"
                if alt_cand not in cand_files:
                    cand_files.append(alt_cand)
            for cand in sorted(p_dir.glob("*.csp")) + sorted(p_dir.glob("*.cpj")):
                if cand not in cand_files:
                    cand_files.append(cand)

            invalid_reason = None
            for cand in cand_files:
                if cand.exists() and cand.is_file():
                    if cand.stat().st_size < 512:
                        invalid_reason = f"File '{cand.name}' is smaller than 512 bytes ({cand.stat().st_size} bytes)"
                        continue
                    try:
                        with open(cand, "rb") as f_in:
                            hdr = f_in.read(8)
                        if hdr == CFBF_MAGIC:
                            source_file = cand
                            break
                        else:
                            invalid_reason = f"File '{cand.name}' has invalid CFBF magic header (got {hdr.hex().upper()}, expected D0CF11E0A1B11AE1)"
                    except Exception as read_err:
                        invalid_reason = f"Failed to read '{cand.name}': {read_err}"

            if not source_file or not source_file.exists():
                detail = invalid_reason or f"No valid CFBF container (.csp/.cpj) found in '{p_dir}'"
                raise FileNotFoundError(f"Project directory or source file not found: {detail}.")

            shutil.copyfile(source_file, out_path)

            # Inspect and verify CFBF container integrity
            cfbf_inspection = {}
            try:
                info = CscapeLiveProjectManager.inspect_project_file(out_path)
                cfbf_inspection = info.to_dict()
            except Exception as e:
                logger.warning(f"CFBF inspection failed on {out_path}: {e}")
                cfbf_inspection = {"error": str(e)}

            file_bytes = out_path.read_bytes()
            if not cfbf_inspection.get("is_valid_cfbf") or len(file_bytes) <= 512 or file_bytes[:8] != CFBF_MAGIC or file_bytes[8:512] == b"\x00" * 504:
                if out_path.exists():
                    out_path.unlink(missing_ok=True)
                raise ValueError(f"Exported container '{out_path.name}' failed CFBF validation (corrupt container or 512-byte magic+zeros rejected).")

            return {
                "success": True,
                "status": "success",
                "project_name": project_name,
                "export_path": str(out_path),
                "format": "CFBF_OLE2",
                "size_bytes": len(file_bytes),
                "sha256": hashlib.sha256(file_bytes).hexdigest(),
                "cfbf_inspection": cfbf_inspection,
                "error_count": 0,
                "errors": [],
            }

        elif clean_fmt == "csv":
            vm = CscapeVariableManager(project_name=project_name)
            var_csv = p_dir / "variables.csv"
            var_xml = p_dir / "variables.xml"
            if var_csv.exists():
                vm.import_csv(var_csv)
            elif var_xml.exists():
                vm.import_xml(var_xml)
            else:
                pous_dir = p_dir / "pous"
                if pous_dir.exists():
                    for st_file in pous_dir.glob("*.st"):
                        try:
                            code = st_file.read_text(encoding="utf-8", errors="replace")
                            p = Parser.from_source(code)
                            ast = p.parse()
                            for vb in ast.var_blocks:
                                for decl in vb.declarations:
                                    scope_str = vb.block_type.name.lower() if hasattr(vb.block_type, "name") else "program"
                                    vm.add_variable(CscapeVariable(name=decl.name, data_type=str(decl.data_type), scope=scope_str))
                        except Exception:
                            pass
            vm.export_csv(out_path)
            file_bytes = out_path.read_bytes()
            return {
                "success": True,
                "status": "success",
                "project_name": project_name,
                "export_path": str(out_path),
                "format": "CSV_VARIABLES",
                "variable_count": vm.total_count,
                "size_bytes": len(file_bytes),
                "sha256": hashlib.sha256(file_bytes).hexdigest(),
                "error_count": 0,
                "errors": [],
            }

        elif clean_fmt == "xml":
            vm = CscapeVariableManager(project_name=project_name)
            var_xml = p_dir / "variables.xml"
            var_csv = p_dir / "variables.csv"
            if var_xml.exists():
                vm.import_xml(var_xml)
            elif var_csv.exists():
                vm.import_csv(var_csv)
            else:
                pous_dir = p_dir / "pous"
                if pous_dir.exists():
                    for st_file in pous_dir.glob("*.st"):
                        try:
                            code = st_file.read_text(encoding="utf-8", errors="replace")
                            p = Parser.from_source(code)
                            ast = p.parse()
                            for vb in ast.var_blocks:
                                for decl in vb.declarations:
                                    scope_str = vb.block_type.name.lower() if hasattr(vb.block_type, "name") else "program"
                                    vm.add_variable(CscapeVariable(name=decl.name, data_type=str(decl.data_type), scope=scope_str))
                        except Exception:
                            pass
            vm.export_xml(out_path)
            file_bytes = out_path.read_bytes()
            return {
                "success": True,
                "status": "success",
                "project_name": project_name,
                "export_path": str(out_path),
                "format": "XML_VARIABLES",
                "variable_count": vm.total_count,
                "size_bytes": len(file_bytes),
                "sha256": hashlib.sha256(file_bytes).hexdigest(),
                "error_count": 0,
                "errors": [],
            }

        elif clean_fmt == "json":
            from src.project.manager import CscapeProject
            proj = CscapeProject.load(p_dir)
            summary = proj.export_summary()
            out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
            file_bytes = out_path.read_bytes()
            return {
                "success": True,
                "status": "success",
                "project_name": project_name,
                "export_path": str(out_path),
                "format": "JSON_PROJECT_MANIFEST",
                "size_bytes": len(file_bytes),
                "sha256": hashlib.sha256(file_bytes).hexdigest(),
                "error_count": 0,
                "errors": [],
            }

        elif clean_fmt in ("zip", "bundle"):
            with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for file_path in p_dir.rglob("*"):
                    if file_path.is_file():
                        zf.write(file_path, arcname=file_path.relative_to(p_dir))
            file_bytes = out_path.read_bytes()
            return {
                "success": True,
                "status": "success",
                "project_name": project_name,
                "export_path": str(out_path),
                "format": "ZIP_NATIVE_BUNDLE",
                "size_bytes": len(file_bytes),
                "sha256": hashlib.sha256(file_bytes).hexdigest(),
                "error_count": 0,
                "errors": [],
            }

        elif clean_fmt in ("st", "structured_text"):
            st_lines = [
                f"(* Consolidated Structured Text for {project_name} *)",
                f"(* Exported: {datetime.now(timezone.utc).isoformat()} *)",
                f"(* Hardware Lockout: Enforced *)",
                "",
            ]
            pous_dir = p_dir / "pous"
            if pous_dir.exists():
                for st_file in sorted(pous_dir.glob("*.st")):
                    st_lines.append(f"\n(* POU: {st_file.name} *)\n")
                    st_lines.append(st_file.read_text(encoding="utf-8", errors="replace"))
            out_path.write_text("\n".join(st_lines), encoding="utf-8")
            file_bytes = out_path.read_bytes()
            return {
                "success": True,
                "status": "success",
                "project_name": project_name,
                "export_path": str(out_path),
                "format": "CONSOLIDATED_ST",
                "size_bytes": len(file_bytes),
                "sha256": hashlib.sha256(file_bytes).hexdigest(),
                "error_count": 0,
                "errors": [],
            }

        else:
            raise ValueError(f"Unsupported export format: {output_format}")

    def get_project_state(self, project_name: str) -> Dict[str, Any]:
        """Returns comprehensive project metadata."""
        from src.project.manager import CscapeProject

        p_dir = self._get_project_dir(project_name)
        if not p_dir.exists():
            raise FileNotFoundError(f"Project '{project_name}' does not exist.")

        project = CscapeProject.load(p_dir)
        return project.export_summary()

    def list_projects(self) -> List[Dict[str, Any]]:
        """Lists all projects in the projects directory."""
        from src.project.manager import CscapeProject

        projects = []
        if not self.projects_dir.exists():
            return []

        for item in self.projects_dir.iterdir():
            if item.is_dir() and (item / "cscape_project.json").exists():
                try:
                    p = CscapeProject.load(item)
                    projects.append(p.export_summary())
                except Exception:
                    pass
        return projects


def cscape_export_project(
    project_name: str,
    output_format: str = "csp",
    workspace_root: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """Exports a project in specified format with fail-closed validation."""
    pm = ProjectManager(workspace_root=workspace_root)
    return pm.export_project(project_name=project_name, output_format=output_format)

