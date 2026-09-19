"""Straton K5 / Cscape Compatible IEC 61131-3 Project Builder.

Assembles and manages complete, standardized Straton K5 / Horner Cscape project directories:
- appli.k5p (Straton project definition, POU registration, global/retain sections)
- appli.CPO (Compiler options, runtime targets, simulation config)
- appli.lge (Language mappings)
- K5DBXS.INI (Straton database schema settings & FB registry)
- Default/appli.txt (Variable dictionary and project metadata)
- ST program source files (*.st)
- project_manifest.json (Project metadata, POU registry, compilation info)
"""

from __future__ import annotations

import json
import os
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from src.iec.st_generator import STGenerator
from src.iec.st_parser import STPOU, STParser, STValidationResult, STVariable, VarScope


# Standard template paths
CSCAPE_DEFAULT_TEMPLATE = Path(r"C:\Program Files (x86)\Cscape 10.2\TEMPLATE\EmptyProject")

# Embedded Fallback Templates when Cscape is not installed
FALLBACK_K5P = """;K5 project

/A,<5>65537,65538,131073,131074,131075,131076,131077,131078,131080,327681,327683,327684,327687,262145,262146,262147,262149,262151,458753,458754,458755,458757,458759,524289,524290,589827,655361,2147483649,2147483650,2147483651,2147483652,2147483653,2147483654,2147483655,2147483656,2147483657,
</A,end>
</P,end>
/G,GLOBAL
/G,RETAIN
</G,end>
"""

FALLBACK_CPO = """[Options]
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
Target=T5RTI
Suffix=.XTI
MotorolaEndian=FALSE
T5Style=ON
Comment=Straton T5 runtime (Intel like byte ordering)
ConfigName=T5RTI
"""

FALLBACK_LGE = "[DEFAULT]\n"

FALLBACK_K5DBXS_INI = """[SETTINGS]
SETONLINE=127.0.0.1
DRVONLINE=K5NET5.DLL
CSCOLC=1

[OCS_ONLY]
FB1=ModbusMaster 
FB2=ModbusSlave 
FB3=ModbusSlaveEx 
FB4=NetGetRemoteIO_A 
FB5=NetGetRemoteIO_D 
FB6=NetPutRemoteIO_A 
FB7=NetPutRemoteIO_D
FB8=DisplayScreen
FB9=StepperMove
FB10=StepperMoveInd
FB11=AlarmStamp
FB12=NetGetW
FB13=NetPutW
FB14=NetPutWex
FB15=Alarm

[T5_ONLY]
FB1=ModbusDoRequest
FB2=ModbusMapSlave
FB3=ModbusMapExtendedSlave 
FB4=ForceScreen
FB5=OldUsersMaster
FB6=ModbusSlaveSizedMap
FB7=ArrayToString
FB8=AsciitoHex\t
FB9=CharAsciiCode
FB10=CRC16
FB11=DeleteChars
FB12=HextoAscii
FB13=InsertChars
FB14=StringConcat
FB15=StringFind
FB16=StringLeft
FB17=StringMid
FB18=StringReplace
FB19=StringRight
FB20=StringToArray
FB21=TextTable
FB22=SunPos
FB23=NetGetWord
FB24=NetPutWord
FB25=NetPutWordex
FB26=SunPos
"""

FALLBACK_CURRENT_ARC = """[DLGTREECTRL]
BARSTATE=1,0,1
MENUSTATE=1
WINDOWPLACEMENT=44,0,1,-1,-1,-1,-1,54,111,378,488
TUTORIAL=1
DLGTYPE=1
"""


class ProjectBuilder:
    """Builds and manages Straton K5 / Horner Cscape compatible IEC 61131-3 projects."""

    def __init__(self, template_dir: Optional[Union[str, Path]] = None):
        self.template_dir = Path(template_dir) if template_dir else CSCAPE_DEFAULT_TEMPLATE

    # ------------------------------------------------------------------------
    # Project Initialization
    # ------------------------------------------------------------------------

    def create_project(
        self,
        project_dir: Union[str, Path],
        project_name: str,
        description: str = "",
    ) -> Path:
        """Creates a new Straton K5 project directory initialized from template.

        Args:
            project_dir: Destination path for the project.
            project_name: Logical project name.
            description: Optional human-readable project description.

        Returns:
            Path to the initialized project directory.
        """
        proj_path = Path(project_dir).resolve()
        proj_path.mkdir(parents=True, exist_ok=True)
        default_dir = proj_path / "Default"
        default_dir.mkdir(parents=True, exist_ok=True)

        # Copy from official Cscape template if available
        if self.template_dir.exists() and (self.template_dir / "appli.k5p").exists():
            for item in self.template_dir.iterdir():
                dest = proj_path / item.name
                if item.is_dir():
                    shutil.copytree(item, dest, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, dest)
        else:
            # Populate with built-in templates
            (proj_path / "appli.k5p").write_text(FALLBACK_K5P, encoding="utf-8")
            (proj_path / "appli.CPO").write_text(FALLBACK_CPO, encoding="utf-8")
            (proj_path / "appli.lge").write_text(FALLBACK_LGE, encoding="utf-8")
            (proj_path / "K5DBXS.INI").write_text(FALLBACK_K5DBXS_INI, encoding="utf-8")
            (proj_path / "__Current.ARC").write_text(FALLBACK_CURRENT_ARC, encoding="utf-8")
            (proj_path / "__Default.ARC").write_text(FALLBACK_CURRENT_ARC, encoding="utf-8")

        # Initialize Default/appli.txt
        appli_txt_path = default_dir / "appli.txt"
        init_appli_txt = STGenerator.generate_appli_txt(
            project_name=project_name,
            variables=[],
            description=description or project_name,
        )
        appli_txt_path.write_text(init_appli_txt, encoding="utf-8")

        # Write project manifest
        manifest = {
            "name": project_name,
            "description": description,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "target": "T5RTI",
            "language": "IEC 61131-3 Structured Text",
            "programs": [],
            "variables": [],
            "version": "1.0.0",
        }
        (proj_path / "project_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        return proj_path

    # ------------------------------------------------------------------------
    # Program / POU Registration
    # ------------------------------------------------------------------------

    def add_program(
        self,
        project_dir: Union[str, Path],
        name: str,
        code: str,
        validate_first: bool = True,
    ) -> Path:
        """Adds or updates a Structured Text program in the project.

        Args:
            project_dir: Path to the project root.
            name: Program / POU name.
            code: IEC 61131-3 Structured Text source code.
            validate_first: If True, validates syntax and rejects ladder/errors.

        Returns:
            Path to the created .st program file.

        Raises:
            ValueError: If validation fails and validate_first is True.
        """
        proj_path = Path(project_dir).resolve()
        if not proj_path.exists():
            raise FileNotFoundError(f"Project directory does not exist: {proj_path}")

        # Validate code
        if validate_first:
            res = STParser.validate(code)
            if not res.is_valid:
                err_msgs = "; ".join(f"[{e.code}] {e.message} (line {e.line})" for e in res.errors)
                raise ValueError(f"IEC ST validation failed for '{name}': {err_msgs}")

        # Write program source file
        st_file = proj_path / f"{name}.st"
        st_file.write_text(code, encoding="utf-8")

        # Update appli.k5p with /P entry
        self._register_program_in_k5p(proj_path, name)

        # Parse variables and merge into Default/appli.txt
        parsed = STParser.validate(code)
        if parsed.pous:
            new_vars = parsed.pous[0].variables
            self._merge_variables_into_appli_txt(proj_path, new_vars)

        # Update manifest
        self._update_manifest_program(proj_path, name, str(st_file.relative_to(proj_path)))

        return st_file

    def add_pou(
        self,
        project_dir: Union[str, Path],
        pou: STPOU,
        validate_first: bool = True,
    ) -> Path:
        """Generates and adds a POU to the project from an STPOU AST object."""
        code = STGenerator.generate_pou(pou)
        return self.add_program(project_dir, pou.name, code, validate_first=validate_first)

    def add_global_variables(
        self,
        project_dir: Union[str, Path],
        variables: Sequence[STVariable],
    ) -> None:
        """Registers global variables in the project."""
        proj_path = Path(project_dir).resolve()
        self._merge_variables_into_appli_txt(proj_path, variables)

        # Also maintain a globals.st file in the project
        globals_file = proj_path / "globals.st"
        existing_vars: List[STVariable] = []
        if globals_file.exists():
            parsed = STParser.validate(globals_file.read_text(encoding="utf-8"))
            existing_vars = parsed.global_variables

        merged_dict = {v.name.upper(): v for v in existing_vars}
        for v in variables:
            v.scope = VarScope.VAR_GLOBAL
            merged_dict[v.name.upper()] = v

        all_globals = list(merged_dict.values())
        code_lines = [
            "(* Global Variables Definition *)",
            STGenerator.format_var_block(VarScope.VAR_GLOBAL, all_globals, indent_level=0),
            "",
        ]
        globals_file.write_text("\n".join(code_lines), encoding="utf-8")

    # ------------------------------------------------------------------------
    # Internal File Synchronizers
    # ------------------------------------------------------------------------

    def _register_program_in_k5p(self, project_dir: Path, prog_name: str) -> None:
        """Ensures the program is listed in the /P section of appli.k5p."""
        k5p_path = project_dir / "appli.k5p"
        if not k5p_path.exists():
            return

        content = k5p_path.read_text(encoding="utf-8")
        entry = f"/P,0,{prog_name}"

        # Avoid duplicate entries
        if entry in content:
            return

        # Insert before </P,end>
        if "</P,end>" in content:
            content = content.replace("</P,end>", f"{entry}\n</P,end>")
        else:
            # Add /P section before /G
            if "/G,GLOBAL" in content:
                content = content.replace("/G,GLOBAL", f"{entry}\n</P,end>\n/G,GLOBAL")
            else:
                content += f"\n{entry}\n</P,end>\n"

        k5p_path.write_text(content, encoding="utf-8")

    def _merge_variables_into_appli_txt(
        self,
        project_dir: Path,
        new_vars: Sequence[STVariable],
    ) -> None:
        """Merges new variables into Default/appli.txt."""
        appli_txt_path = project_dir / "Default" / "appli.txt"
        if not appli_txt_path.exists():
            return

        manifest_path = project_dir / "project_manifest.json"
        proj_name = project_dir.name
        desc = ""
        if manifest_path.exists():
            try:
                m = json.loads(manifest_path.read_text(encoding="utf-8"))
                proj_name = m.get("name", proj_name)
                desc = m.get("description", "")
            except Exception:
                pass

        # Parse existing variables from appli.txt if present
        existing_vars: Dict[str, STVariable] = {}
        content = appli_txt_path.read_text(encoding="utf-8")

        in_vars = False
        for line in content.splitlines():
            line = line.strip()
            if line.lower() == "[variables]":
                in_vars = True
                continue
            if in_vars and line and not line.startswith("["):
                # Format: Name:TYPE[:=init][@addr]
                parts = line.split(":", 1)
                name = parts[0].strip()
                t_rest = parts[1].strip() if len(parts) > 1 else "INT"
                existing_vars[name.upper()] = STVariable(name=name, data_type=t_rest)

        # Merge with new vars
        for v in new_vars:
            existing_vars[v.name.upper()] = v

        # Re-generate appli.txt
        updated_txt = STGenerator.generate_appli_txt(
            project_name=proj_name,
            variables=list(existing_vars.values()),
            description=desc,
        )
        appli_txt_path.write_text(updated_txt, encoding="utf-8")

    def _update_manifest_program(self, project_dir: Path, prog_name: str, rel_path: str) -> None:
        """Updates program list in project_manifest.json."""
        manifest_path = project_dir / "project_manifest.json"
        if not manifest_path.exists():
            return

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            programs = manifest.get("programs", [])
            # Update or append
            found = False
            for p in programs:
                if p["name"] == prog_name:
                    p["file"] = rel_path
                    p["updated_at"] = datetime.now(timezone.utc).isoformat()
                    found = True
                    break
            if not found:
                programs.append({
                    "name": prog_name,
                    "file": rel_path,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })
            manifest["programs"] = programs
            manifest["last_modified"] = datetime.now(timezone.utc).isoformat()
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        except Exception:
            pass

    # ------------------------------------------------------------------------
    # Project Inspection, Validation, and Export
    # ------------------------------------------------------------------------

    def get_project_summary(self, project_dir: Union[str, Path]) -> Dict[str, Any]:
        """Returns structured summary of project status, files, POUs, and variables."""
        proj_path = Path(project_dir).resolve()
        if not proj_path.exists():
            raise FileNotFoundError(f"Project not found: {proj_path}")

        st_files = list(proj_path.glob("*.st"))
        programs_info = []

        total_vars = 0
        for f in st_files:
            try:
                code = f.read_text(encoding="utf-8")
                res = STParser.validate(code)
                for pou in res.pous:
                    total_vars += len(pou.variables)
                    programs_info.append({
                        "pou_name": pou.name,
                        "kind": pou.kind.value,
                        "file": f.name,
                        "variables_count": len(pou.variables),
                        "is_valid": res.is_valid,
                    })
            except Exception as e:
                programs_info.append({
                    "pou_name": f.stem,
                    "file": f.name,
                    "error": str(e),
                    "is_valid": False,
                })

        return {
            "project_name": proj_path.name,
            "project_path": str(proj_path),
            "st_programs_count": len(st_files),
            "programs": programs_info,
            "total_variables": total_vars,
            "k5p_exists": (proj_path / "appli.k5p").exists(),
            "cpo_exists": (proj_path / "appli.CPO").exists(),
            "appli_txt_exists": (proj_path / "Default" / "appli.txt").exists(),
        }

    def validate_project(self, project_dir: Union[str, Path]) -> Dict[str, Any]:
        """Validates all ST files in the project."""
        proj_path = Path(project_dir).resolve()
        st_files = list(proj_path.glob("*.st"))

        overall_valid = True
        file_results: Dict[str, Any] = {}

        for f in st_files:
            code = f.read_text(encoding="utf-8")
            res = STParser.validate(code)
            if not res.is_valid:
                overall_valid = False
            file_results[f.name] = res.to_dict()

        return {
            "project": proj_path.name,
            "is_valid": overall_valid,
            "checked_files_count": len(st_files),
            "files": file_results,
        }

    def export_zip(
        self,
        project_dir: Union[str, Path],
        output_zip_path: Optional[Union[str, Path]] = None,
    ) -> Path:
        """Packages the entire project into a portable ZIP archive."""
        proj_path = Path(project_dir).resolve()
        if not proj_path.exists():
            raise FileNotFoundError(f"Project not found: {proj_path}")

        out_zip = Path(output_zip_path) if output_zip_path else proj_path.with_suffix(".zip")

        with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(proj_path):
                for f in files:
                    full_p = Path(root) / f
                    arcname = full_p.relative_to(proj_path)
                    zf.write(full_p, arcname)

        return out_zip

