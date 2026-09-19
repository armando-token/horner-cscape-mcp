"""
Horner Cscape Legacy Project Manager Adapter.

Delegates cleanly to src/cscape/ and native CFBF files without any Straton K5 dependencies.
Strictly IEC 61131-3 Structured Text - Advanced Ladder rejected.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import struct
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from src.cscape.project_manager import (
    CFBF_MAGIC,
    CscapeLiveProjectManager,
    ProjectCreationResult,
    ProjectFileInfo,
    generate_minimal_cfbf_bytes,
)
from src.cscape.compiler import CscapeCompiler, CscapeBuildResult
from src.cscape.st_ld_interop import STLadderInteropGuard, LadderConstructRejectedError
from src.parser.parser import Parser

logger = logging.getLogger(__name__)

Union_Path_Str = Union[str, Path]


@dataclass
class POUInfo:
    name: str
    pou_type: str  # PROGRAM, FUNCTION_BLOCK, FUNCTION
    file_path: str
    created_at: str
    st_code: str
    variable_count: int = 0
    statement_count: int = 0


class CscapeProject:
    """Legacy adapter for Cscape projects.

    Delegates cleanly to src/cscape/ and native CFBF files without any Straton K5 dependencies.
    Creates and validates authentic CFBF .csp files, manages IEC 61131-3 ST POUs,
    and supports AST validation and native Cscape compilation.
    """
    def __init__(self, project_dir: Union_Path_Str, name: str = "", controller: str = "XL4"):
        self.project_dir = Path(project_dir).resolve()
        self.name = name or self.project_dir.name
        self.controller = controller
        self.manifest_file = self.project_dir / "cscape_project.json"
        self.pous_dir = self.project_dir / "pous"
        self.csp_file = self.project_dir / f"{self.name}.csp"
        self.pous: Dict[str, POUInfo] = {}

    @classmethod
    def create(cls, project_dir: Union_Path_Str, name: str, controller: str = "XL4", seed_cfbf: bool = True) -> "CscapeProject":
        """Initializes a new native Cscape project with CFBF file container."""
        p_dir = Path(project_dir).resolve()
        p_dir.mkdir(parents=True, exist_ok=True)

        pous_dir = p_dir / "pous"
        pous_dir.mkdir(exist_ok=True)

        # Native CFBF project container (.csp)
        csp_path = p_dir / f"{name}.csp"
        if not csp_path.exists() and seed_cfbf:
            sample_csp = Path("C:/HornerAI/horner-cscape-mcp/artifacts/projects/new_iec_st_project.csp")
            if not sample_csp.exists():
                sample_csp = Path("C:/HornerAI/horner-cscape-mcp/fixtures/cscape_native_samples/reg_min.csp")

            if sample_csp.exists():
                shutil.copyfile(sample_csp, csp_path)
            else:
                cfbf_data = generate_minimal_cfbf_bytes(name)
                csp_path.write_bytes(cfbf_data)

        project = cls(p_dir, name=name, controller=controller)
        project._save_manifest()
        return project

    @classmethod
    def load(cls, project_dir: Union_Path_Str) -> "CscapeProject":
        """Loads an existing Cscape project from directory."""
        p_dir = Path(project_dir).resolve()
        manifest_file = p_dir / "cscape_project.json"
        if not manifest_file.exists():
            raise FileNotFoundError(f"Project manifest not found at {manifest_file}")

        data = json.loads(manifest_file.read_text(encoding="utf-8"))
        name = data.get("name", data.get("project", p_dir.name))
        proj = cls(p_dir, name=name, controller=data.get("controller", "XL4"))

        # Load POUs
        for pou_dict in data.get("pous", []):
            pou_file = Path(pou_dict["file_path"])
            st_code = ""
            if pou_file.exists():
                st_code = pou_file.read_text(encoding="utf-8")
            pou_info = POUInfo(
                name=pou_dict["name"],
                pou_type=pou_dict["pou_type"],
                file_path=str(pou_file),
                created_at=pou_dict.get("created_at", ""),
                st_code=st_code,
                variable_count=pou_dict.get("variable_count", 0),
                statement_count=pou_dict.get("statement_count", 0),
            )
            proj.pous[pou_info.name] = pou_info

        return proj

    def inject_pou(self, name: str, st_code: str, pou_type: str = "PROGRAM") -> POUInfo:
        """Injects an IEC 61131-3 Structured Text POU into the project.

        Strictly enforces IEC 61131-3 ST and rejects Ladder logic.
        """
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("POU name cannot be empty")

        pou_type_upper = pou_type.upper()
        if pou_type_upper not in ("PROGRAM", "FUNCTION_BLOCK", "FUNCTION"):
            raise ValueError(f"Invalid POU type: {pou_type}")

        # Enforce pure Structured Text (reject Ladder constructs)
        STLadderInteropGuard.enforce_st_code(st_code, context_name=clean_name)

        # Write POU file
        self.pous_dir.mkdir(exist_ok=True)
        pou_file = self.pous_dir / f"{clean_name}.st"
        pou_file.write_text(st_code, encoding="utf-8")

        # Parse AST metrics
        var_count = 0
        stmt_count = 0
        try:
            p = Parser.from_source(st_code)
            ast = p.parse()
            for vb in ast.var_blocks:
                var_count += len(vb.declarations)
            stmt_count = len(ast.body)
        except Exception:
            pass

        pou_info = POUInfo(
            name=clean_name,
            pou_type=pou_type_upper,
            file_path=str(pou_file),
            created_at=datetime.now(timezone.utc).isoformat(),
            st_code=st_code,
            variable_count=var_count,
            statement_count=stmt_count,
        )
        self.pous[clean_name] = pou_info
        self._save_manifest()
        return pou_info

    def get_pou(self, name: str) -> Optional[POUInfo]:
        """Retrieves POU by name (case-insensitive)."""
        target = name.strip().lower()
        for k, v in self.pous.items():
            if k.lower() == target:
                return v
        return None

    def list_pous(self) -> List[POUInfo]:
        """Returns list of all registered POUs."""
        return list(self.pous.values())

    def compile(self, clean_build: bool = True) -> CscapeBuildResult:
        """Executes Cscape compiler pass on project POUs."""
        compiler = CscapeCompiler(workspace_root=self.project_dir.parent)
        return compiler.compile_project(self.project_dir, clean_build=clean_build)

    def inspect_binary(self) -> ProjectFileInfo:
        """Inspects native CFBF project container."""
        if not self.csp_file.exists():
            raise FileNotFoundError(f"CFBF project file not found: {self.csp_file}")
        return CscapeLiveProjectManager.inspect_project_file(self.csp_file)

    def _save_manifest(self) -> None:
        """Persists project manifest JSON."""
        data = {
            "name": self.name,
            "project": self.name,
            "controller": self.controller,
            "format": "CFBF_OLE2",
            "editor_mode": "IEC 61131",
            "csp_file": str(self.csp_file),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "pous": [asdict(p) for p in self.pous.values()],
        }
        self.manifest_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def export_summary(self) -> Dict[str, Any]:
        """Returns structural summary of project."""
        cfbf_info = None
        if self.csp_file.exists():
            try:
                cfbf_info = self.inspect_binary().to_dict()
            except Exception:
                pass
        return {
            "name": self.name,
            "controller": self.controller,
            "project_dir": str(self.project_dir),
            "csp_file": str(self.csp_file),
            "cfbf_info": cfbf_info,
            "pou_count": len(self.pous),
            "pous": [p.name for p in self.pous.values()],
        }
