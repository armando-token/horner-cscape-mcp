"""Horner Cscape & Straton K5 Project Manager.

Handles project lifecycle:
- Creation of Straton K5 projects (appli.k5p, appli.CPO, appli.txt, K5DBXS.INI)
- Addition and validation of IEC 61131-3 Structured Text POUs
- Inspection and indexing of global and local variables
- Local headless compilation loop and diagnostic generation
- Software simulation dispatch
- Multi-format project export (k5p bundle, Straton XML, consolidated ST, JSON)
"""

import hashlib
import json
import os
import shutil
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.iec.simulator import STSimulator
from src.iec.validator import IECValidator
from src.security.guard import SafetyGuard, SecurityError


class ProjectManager:
    """Manages Horner Cscape / Straton IEC 61131-3 projects."""

    DEFAULT_WORKSPACE = Path("C:/HornerAI/horner-cscape-mcp")
    CSCAPE_TEMPLATE_PATH = Path("C:/Program Files (x86)/Cscape 10.2/TEMPLATE/EmptyProject")

    def __init__(self, workspace_root: Optional[Path] = None):
        self.workspace = Path(workspace_root) if workspace_root else self.DEFAULT_WORKSPACE
        self.projects_dir = self.workspace / "artifacts" / "projects"
        self.exports_dir = self.workspace / "artifacts" / "exports"
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.exports_dir.mkdir(parents=True, exist_ok=True)

    def _get_project_dir(self, project_name: str) -> Path:
        clean_name = SafetyGuard.validate_project_name(project_name)
        return self.projects_dir / clean_name

    def _generate_cpo_content(self, target_plc: str) -> str:
        """Generates appli.CPO configuration matching Horner Cscape requirements."""
        return f"""[Options]
Trace=OFF
TraceTime=OFF
Simul=ON
Lock=IO
DEBUG=ON
CSCAPE=ON
CTSEG=OFF
NOCODESTAMP=ON
EMBEDSYMBOLS=ON
EMBEDSYBCASE=ON
NoCodeStamp = ON
FBDOPTIM=ON
LDOPTIM=ON
CHECKSYBCONFLICTS=ON
MAPBOOL=ON
MAPUSINT=ON
MAPUINT=ON
MAPUDINT=ON
MAPULINT=ON
MAPREAL=ON
MAPLREAL=ON
MAPTIME=ON
MAPSTRING=ON
MAPCOMPLEX=ON

[SimulCode]
Target=T5SIMUL
Suffix=.XWS
MotorolaEndian=FALSE
T5Style=ON

[TargetCode]
Target={target_plc}
Suffix=.XTI
MotorolaEndian=FALSE
T5Style=ON
Comment=Straton T5 runtime for {target_plc}
ConfigName={target_plc}
"""

    def _generate_k5p_content(self, project_name: str, pous: Optional[List[Dict[str, Any]]] = None) -> str:
        """Generates appli.k5p content with registered POUs and section layout."""
        lines = [
            ";K5 project - Horner Cscape IEC 61131-3",
            f";Project: {project_name}",
            "",
            "/A,<5>65537,65538,131073,131074,131075,131076,131077,131078,131080,327681,327683,327684,327687,262145,262146,262147,262149,262151,458753,458754,458755,458757,458759,524289,524290,589827,655361,2147483649,2147483650,2147483651,2147483652,2147483653,2147483654,2147483655,2147483656,2147483657,",
            "</A,end>",
        ]

        if pous:
            for p in pous:
                lines.append(f"/P,{p['name']},{p['type']},{p.get('cycle_time_ms', 10)},ST")
        lines.append("</P,end>")
        lines.append("/G,GLOBAL")
        lines.append("/G,RETAIN")
        lines.append("</G,end>")
        lines.append("")
        return "\n".join(lines)

    def create_project(self, name: str, description: str = "", target_plc: str = "T5RTI") -> Dict[str, Any]:
        """Initializes a new Horner Cscape / Straton K5 IEC 61131-3 project."""
        clean_name = SafetyGuard.validate_project_name(name)
        clean_target = SafetyGuard.validate_target_plc(target_plc)

        project_dir = self._get_project_dir(clean_name)
        if project_dir.exists():
            # If project already exists, return existing project info
            meta_path = project_dir / "project_meta.json"
            if meta_path.exists():
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                return {
                    "status": "exists",
                    "project_name": clean_name,
                    "target_plc": meta.get("target_plc", clean_target),
                    "project_path": str(project_dir),
                    "message": f"Project '{clean_name}' already exists.",
                }

        # Create project directory structure
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "Default").mkdir(parents=True, exist_ok=True)
        (project_dir / "pous").mkdir(parents=True, exist_ok=True)
        (project_dir / "build").mkdir(parents=True, exist_ok=True)
        (project_dir / "export").mkdir(parents=True, exist_ok=True)

        files_created = []

        # 1. appli.CPO
        cpo_file = project_dir / "appli.CPO"
        cpo_file.write_text(self._generate_cpo_content(clean_target), encoding="utf-8")
        files_created.append("appli.CPO")

        # 2. appli.k5p
        k5p_file = project_dir / "appli.k5p"
        k5p_file.write_text(self._generate_k5p_content(clean_name), encoding="utf-8")
        files_created.append("appli.k5p")

        # 3. appli.lge
        lge_file = project_dir / "appli.lge"
        lge_file.write_text("[LGE]\n0\n", encoding="utf-8")
        files_created.append("appli.lge")

        # 4. K5DBXS.INI
        ini_file = project_dir / "K5DBXS.INI"
        ini_content = "[Options]\nVersion=1.0\nEncoding=UTF-8\nTarget=Straton\n"
        ini_file.write_text(ini_content, encoding="utf-8")
        files_created.append("K5DBXS.INI")

        # 5. Default/appli.txt
        txt_file = project_dir / "Default" / "appli.txt"
        txt_content = f"\n\n[long]\nA-<PROJECT>={clean_name}\n"
        txt_file.write_text(txt_content, encoding="utf-8")
        files_created.append("Default/appli.txt")

        # 6. project_meta.json
        now_iso = datetime.now(timezone.utc).isoformat()
        metadata = {
            "name": clean_name,
            "description": description,
            "target_plc": clean_target,
            "created_at": now_iso,
            "updated_at": now_iso,
            "pous": [],
            "last_build": None,
        }
        meta_file = project_dir / "project_meta.json"
        meta_file.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        files_created.append("project_meta.json")

        return {
            "status": "success",
            "project_name": clean_name,
            "target_plc": clean_target,
            "project_path": str(project_dir),
            "files_created": files_created,
            "message": f"Horner Cscape project '{clean_name}' created successfully for target '{clean_target}'.",
        }

    def add_st_pou(
        self,
        project_name: str,
        pou_name: str,
        pou_type: str,
        code: str,
        cycle_time_ms: int = 10,
    ) -> Dict[str, Any]:
        """Adds or updates an IEC 61131-3 Structured Text POU in the project."""
        clean_name = SafetyGuard.validate_project_name(project_name)
        clean_pou_name = SafetyGuard.validate_pou_name(pou_name)
        clean_pou_type = SafetyGuard.validate_pou_type(pou_type)
        valid_cycle = SafetyGuard.validate_cycle_time(cycle_time_ms)

        project_dir = self._get_project_dir(clean_name)
        if not project_dir.exists():
            raise FileNotFoundError(f"Project '{clean_name}' does not exist at {project_dir}.")

        # Validate ST code
        validation = IECValidator.validate(code)
        if not validation["valid"]:
            return {
                "status": "validation_failed",
                "project_name": clean_name,
                "pou_name": clean_pou_name,
                "errors": validation["errors"],
                "warnings": validation["warnings"],
                "message": f"ST code validation failed for POU '{clean_pou_name}'.",
            }

        # Save POU code file
        pous_dir = project_dir / "pous"
        pous_dir.mkdir(parents=True, exist_ok=True)
        pou_file = pous_dir / f"{clean_pou_name}.st"
        pou_file.write_text(code, encoding="utf-8")

        # Update metadata
        meta_path = project_dir / "project_meta.json"
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        # Update or append POU in metadata
        pous = meta.get("pous", [])
        existing = next((p for p in pous if p["name"].lower() == clean_pou_name.lower()), None)
        pou_entry = {
            "name": clean_pou_name,
            "type": clean_pou_type,
            "cycle_time_ms": valid_cycle,
            "file": f"pous/{clean_pou_name}.st",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "variables": validation["variables"],
            "line_count": validation["metrics"]["total_lines"],
        }

        if existing:
            pous.remove(existing)
        pous.append(pou_entry)
        meta["pous"] = pous
        meta["updated_at"] = datetime.now(timezone.utc).isoformat()

        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

        # Update appli.k5p
        k5p_path = project_dir / "appli.k5p"
        k5p_path.write_text(self._generate_k5p_content(clean_name, pous), encoding="utf-8")

        return {
            "status": "success",
            "project_name": clean_name,
            "pou_name": clean_pou_name,
            "pou_type": clean_pou_type,
            "cycle_time_ms": valid_cycle,
            "file_path": str(pou_file),
            "variables_count": len(validation["variables"]),
            "warnings": validation["warnings"],
            "message": f"POU '{clean_pou_name}' added to project '{clean_name}'.",
        }

    def inspect_variables(self, project_name: str) -> Dict[str, Any]:
        """Inspects and indexes all variables defined across all POUs in the project."""
        clean_name = SafetyGuard.validate_project_name(project_name)
        project_dir = self._get_project_dir(clean_name)
        if not project_dir.exists():
            raise FileNotFoundError(f"Project '{clean_name}' does not exist at {project_dir}.")

        meta_path = project_dir / "project_meta.json"
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        pous_dir = project_dir / "pous"
        pous_vars: Dict[str, List[Dict[str, Any]]] = {}
        all_inputs = []
        all_outputs = []
        all_in_out = []
        all_locals = []
        all_globals = []

        if pous_dir.exists():
            for st_file in pous_dir.glob("*.st"):
                pou_name = st_file.stem
                code = st_file.read_text(encoding="utf-8")
                vars_found, _ = IECValidator.parse_variables(code)
                pous_vars[pou_name] = vars_found

                for v in vars_found:
                    v_item = {**v, "pou": pou_name}
                    scope = v.get("scope", "VAR").upper()
                    if scope == "VAR_INPUT":
                        all_inputs.append(v_item)
                    elif scope == "VAR_OUTPUT":
                        all_outputs.append(v_item)
                    elif scope == "VAR_IN_OUT":
                        all_in_out.append(v_item)
                    elif scope == "VAR_GLOBAL":
                        all_globals.append(v_item)
                    else:
                        all_locals.append(v_item)

        total_vars = sum(len(v) for v in pous_vars.values())

        return {
            "project_name": clean_name,
            "target_plc": meta.get("target_plc", "T5RTI"),
            "total_variables": total_vars,
            "pous": pous_vars,
            "by_scope": {
                "inputs": all_inputs,
                "outputs": all_outputs,
                "in_out": all_in_out,
                "locals": all_locals,
                "globals": all_globals,
            },
        }

    def compile_project(self, project_name: str, clean_build: bool = True) -> Dict[str, Any]:
        """Compiles project POUs, performs symbol validation, and produces diagnostics."""
        SafetyGuard.assert_compile_only("compile_project")
        clean_name = SafetyGuard.validate_project_name(project_name)
        project_dir = self._get_project_dir(clean_name)
        if not project_dir.exists():
            raise FileNotFoundError(f"Project '{clean_name}' does not exist at {project_dir}.")

        start_time = time.perf_counter()
        build_dir = project_dir / "build"
        build_dir.mkdir(parents=True, exist_ok=True)

        if clean_build:
            for item in build_dir.iterdir():
                if item.is_file():
                    item.unlink()

        meta_path = project_dir / "project_meta.json"
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        pous_dir = project_dir / "pous"
        errors: List[str] = []
        warnings: List[str] = []
        info: List[str] = []

        total_code_lines = 0
        total_symbols = 0
        pous_compiled = []

        # Check for Straton / Cscape compiler toolchain
        cscape_path = Path("C:/Program Files (x86)/Cscape 10.2")
        k5cmp_dll = cscape_path / "K5Cmp.dll"
        if k5cmp_dll.exists():
            info.append(f"Cscape 10.2 Straton compiler detected at {k5cmp_dll}.")
        else:
            info.append("Operating in autonomous headless IEC 61131-3 compilation mode.")

        # Compile each POU
        st_files = list(pous_dir.glob("*.st")) if pous_dir.exists() else []
        for st_file in st_files:
            pou_name = st_file.stem
            code = st_file.read_text(encoding="utf-8")
            val = IECValidator.validate(code)

            if not val["valid"]:
                for e in val["errors"]:
                    errors.append(f"[{pou_name}] {e}")
            for w in val["warnings"]:
                warnings.append(f"[{pou_name}] {w}")

            total_code_lines += val["metrics"]["code_lines"]
            total_symbols += val["metrics"]["variable_count"]
            pous_compiled.append({
                "name": pou_name,
                "type": val["pou_type"],
                "valid": val["valid"],
                "lines": val["metrics"]["total_lines"],
                "variables": val["metrics"]["variable_count"],
            })

        compile_successful = len(errors) == 0

        # Memory footprint estimation for Straton T5 target
        code_size_bytes = total_code_lines * 16  # Estimated Straton bytecode byte per statement
        data_size_bytes = total_symbols * 4     # Estimated variable table footprint
        symbol_count = total_symbols

        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        now_iso = datetime.now(timezone.utc).isoformat()

        diagnostics_data = {
            "project_name": clean_name,
            "target_plc": meta.get("target_plc", "T5RTI"),
            "timestamp": now_iso,
            "compile_successful": compile_successful,
            "clean_build": clean_build,
            "duration_ms": duration_ms,
            "pous_compiled": pous_compiled,
            "memory_footprint": {
                "code_size_bytes": code_size_bytes,
                "data_size_bytes": data_size_bytes,
                "symbol_count": symbol_count,
            },
            "diagnostics": {
                "errors": errors,
                "warnings": warnings,
                "info": info,
            },
        }

        # Save build diagnostics
        diag_path = build_dir / "diagnostics.json"
        diag_path.write_text(json.dumps(diagnostics_data, indent=2), encoding="utf-8")

        # Save build log
        log_path = build_dir / "build.log"
        log_lines = [
            f"=== Cscape IEC 61131-3 Build Log for {clean_name} ===",
            f"Target PLC: {meta.get('target_plc', 'T5RTI')}",
            f"Timestamp: {now_iso}",
            f"POUs compiled: {len(pous_compiled)}",
            f"Errors: {len(errors)}",
            f"Warnings: {len(warnings)}",
            f"Result: {'BUILD SUCCESS' if compile_successful else 'BUILD FAILED'}",
            "",
            "--- Details ---",
        ]
        for inf in info:
            log_lines.append(f"INFO: {inf}")
        for w in warnings:
            log_lines.append(f"WARNING: {w}")
        for e in errors:
            log_lines.append(f"ERROR: {e}")
        log_path.write_text("\n".join(log_lines), encoding="utf-8")

        # Update metadata
        meta["last_build"] = {
            "timestamp": now_iso,
            "successful": compile_successful,
            "errors_count": len(errors),
            "warnings_count": len(warnings),
        }
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

        return diagnostics_data

    def get_diagnostics(self, project_name: str) -> Dict[str, Any]:
        """Retrieves the latest compilation diagnostics for a project."""
        clean_name = SafetyGuard.validate_project_name(project_name)
        project_dir = self._get_project_dir(clean_name)
        if not project_dir.exists():
            raise FileNotFoundError(f"Project '{clean_name}' does not exist at {project_dir}.")

        diag_path = project_dir / "build" / "diagnostics.json"
        if diag_path.exists():
            with open(diag_path, "r", encoding="utf-8") as f:
                return json.load(f)

        # If not compiled yet, run compile to get diagnostics
        return self.compile_project(clean_name, clean_build=False)

    def export_project(self, project_name: str, output_format: str = "k5p") -> Dict[str, Any]:
        """Exports a Horner Cscape project into the requested format (k5p, xml, st, json)."""
        clean_name = SafetyGuard.validate_project_name(project_name)
        clean_fmt = SafetyGuard.validate_export_format(output_format)
        project_dir = self._get_project_dir(clean_name)
        if not project_dir.exists():
            raise FileNotFoundError(f"Project '{clean_name}' does not exist at {project_dir}.")

        meta_path = project_dir / "project_meta.json"
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        now_iso = datetime.now(timezone.utc).isoformat()
        export_file: Path

        if clean_fmt == "k5p":
            # Package complete Straton K5 project into a .k5p bundle archive
            export_file = self.exports_dir / f"{clean_name}.k5p"
            with zipfile.ZipFile(export_file, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, _, files in os.walk(project_dir):
                    rel_root = Path(root).relative_to(project_dir)
                    # Skip build artifacts
                    if "build" in rel_root.parts:
                        continue
                    for f in files:
                        file_path = Path(root) / f
                        arcname = str(rel_root / f)
                        zf.write(file_path, arcname)

        elif clean_fmt == "st":
            # Consolidate all POUs and declarations into a single IEC 61131-3 .st file
            export_file = self.exports_dir / f"{clean_name}_consolidated.st"
            pous_dir = project_dir / "pous"
            st_content = [
                f"(* ========================================== *)",
                f"(* Project: {clean_name}                      *)",
                f"(* Target PLC: {meta.get('target_plc', 'T5RTI')} *)",
                f"(* Exported at: {now_iso}                     *)",
                f"(* ========================================== *)",
                "",
            ]
            if pous_dir.exists():
                for st_path in sorted(pous_dir.glob("*.st")):
                    st_content.append(f"(* --- POU: {st_path.stem} --- *)")
                    st_content.append(st_path.read_text(encoding="utf-8"))
                    st_content.append("")
            export_file.write_text("\n".join(st_content), encoding="utf-8")

        elif clean_fmt == "xml":
            # Straton XML exchange format
            export_file = self.exports_dir / f"{clean_name}_straton.xml"
            xml_lines = [
                '<?xml version="1.0" encoding="UTF-8"?>',
                f'<K5Project Name="{clean_name}" Target="{meta.get("target_plc", "T5RTI")}" ExportTime="{now_iso}">',
                '  <Programs>',
            ]
            pous_dir = project_dir / "pous"
            if pous_dir.exists():
                for st_path in sorted(pous_dir.glob("*.st")):
                    code_esc = (
                        st_path.read_text(encoding="utf-8")
                        .replace("&", "&amp;")
                        .replace("<", "&lt;")
                        .replace(">", "&gt;")
                    )
                    xml_lines.append(f'    <Program Name="{st_path.stem}" Language="ST">')
                    xml_lines.append(f'      <SourceCode><![CDATA[{code_esc}]]></SourceCode>')
                    xml_lines.append("    </Program>")
            xml_lines.append("  </Programs>")
            xml_lines.append("</K5Project>")
            export_file.write_text("\n".join(xml_lines), encoding="utf-8")

        elif clean_fmt == "json":
            # Structured JSON project export
            export_file = self.exports_dir / f"{clean_name}_package.json"
            pous_data = []
            pous_dir = project_dir / "pous"
            if pous_dir.exists():
                for st_path in sorted(pous_dir.glob("*.st")):
                    code = st_path.read_text(encoding="utf-8")
                    val = IECValidator.validate(code)
                    pous_data.append({
                        "name": st_path.stem,
                        "code": code,
                        "validation": val,
                    })
            json_export = {
                "meta": meta,
                "exported_at": now_iso,
                "pous": pous_data,
            }
            export_file.write_text(json.dumps(json_export, indent=2), encoding="utf-8")

        # Compute checksum
        file_bytes = export_file.read_bytes()
        sha256_hash = hashlib.sha256(file_bytes).hexdigest()

        return {
            "status": "success",
            "project_name": clean_name,
            "output_format": clean_fmt,
            "export_file": str(export_file),
            "size_bytes": len(file_bytes),
            "sha256": sha256_hash,
            "exported_at": now_iso,
            "message": f"Project '{clean_name}' exported successfully to '{export_file.name}'.",
        }

    def get_project_state(self, project_name: str) -> Dict[str, Any]:
        """Returns the complete state of a project."""
        clean_name = SafetyGuard.validate_project_name(project_name)
        project_dir = self._get_project_dir(clean_name)
        if not project_dir.exists():
            raise FileNotFoundError(f"Project '{clean_name}' does not exist at {project_dir}.")

        meta_path = project_dir / "project_meta.json"
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        pous_dir = project_dir / "pous"
        pou_names = [f.stem for f in pous_dir.glob("*.st")] if pous_dir.exists() else []

        return {
            "project_name": clean_name,
            "target_plc": meta.get("target_plc", "T5RTI"),
            "description": meta.get("description", ""),
            "created_at": meta.get("created_at"),
            "updated_at": meta.get("updated_at"),
            "pous": pou_names,
            "pou_count": len(pou_names),
            "last_build": meta.get("last_build"),
            "project_path": str(project_dir),
        }

    def list_projects(self) -> List[Dict[str, Any]]:
        """Lists all managed projects in the workspace."""
        projects = []
        if not self.projects_dir.exists():
            return projects

        for p_dir in self.projects_dir.iterdir():
            if p_dir.is_dir() and (p_dir / "project_meta.json").exists():
                try:
                    with open(p_dir / "project_meta.json", "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    pous_dir = p_dir / "pous"
                    pou_count = len(list(pous_dir.glob("*.st"))) if pous_dir.exists() else 0
                    projects.append({
                        "name": meta.get("name", p_dir.name),
                        "target_plc": meta.get("target_plc", "T5RTI"),
                        "description": meta.get("description", ""),
                        "pou_count": pou_count,
                        "created_at": meta.get("created_at"),
                        "last_build": meta.get("last_build"),
                    })
                except Exception:
                    continue

        return projects

