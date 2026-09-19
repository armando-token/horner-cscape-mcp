"""Horner Cscape Model Context Protocol (MCP) Resources.

Exposes resources over the cscape:// URI scheme:
- cscape://projects: Catalog of all managed projects
- cscape://project/{project_name}/state: Project metadata, POU list, and build status
- cscape://project/{project_name}/diagnostics: Compilation diagnostics and error traces
- cscape://templates: Catalog of available IEC 61131-3 Structured Text templates
- cscape://template/{template_name}: Structured Text source code of a specific template
- cscape://safety/status: Hardware lockout and simulation-only safety verification
"""

import json
from typing import Any

from pathlib import Path
from ..iec.templates import get_template, get_template_catalog, get_template_code
from ..security.guard import SafetyGuard

WORKSPACE_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()


def get_projects_resource() -> str:
    """Returns JSON listing of all managed Cscape projects."""
    projects_dir = WORKSPACE_ROOT / "artifacts" / "projects"
    projects = []
    if projects_dir.exists():
        for item in sorted(projects_dir.iterdir()):
            if item.is_dir():
                manifest_file = item / "cscape_project.json"
                meta_file = item / "project_meta.json"
                if manifest_file.exists():
                    try:
                        data = json.loads(manifest_file.read_text(encoding="utf-8"))
                        projects.append({
                            "name": data.get("name", item.name),
                            "target_plc": data.get("controller", "XL4"),
                            "path": str(item),
                            "pous_count": len(data.get("pous", [])),
                        })
                        continue
                    except Exception:
                        pass
                if meta_file.exists():
                    try:
                        data = json.loads(meta_file.read_text(encoding="utf-8"))
                        projects.append({
                            "name": data.get("name", item.name),
                            "target_plc": data.get("target_plc", "XL4"),
                            "path": str(item),
                            "pous_count": len(data.get("pous", [])),
                        })
                        continue
                    except Exception:
                        pass
                pous_dir = item / "pous"
                st_count = len(list(pous_dir.glob("*.st"))) if pous_dir.exists() else 0
                projects.append({
                    "name": item.name,
                    "target_plc": "XL4",
                    "path": str(item),
                    "pous_count": st_count,
                })
            elif item.suffix.lower() in (".csp", ".cpj"):
                projects.append({
                    "name": item.stem,
                    "target_plc": "XL4",
                    "path": str(item),
                    "file_type": item.suffix.lower(),
                })
    return json.dumps({"projects": projects, "total_count": len(projects)}, indent=2)


def get_project_state_resource(project_name: str) -> str:
    """Returns JSON state for a specific project."""
    try:
        clean_name = SafetyGuard.validate_project_name(project_name)
        projects_dir = WORKSPACE_ROOT / "artifacts" / "projects"
        proj_dir = projects_dir / clean_name
        manifest_file = proj_dir / "cscape_project.json"
        if manifest_file.exists():
            return manifest_file.read_text(encoding="utf-8")
        meta_file = proj_dir / "project_meta.json"
        if meta_file.exists():
            return meta_file.read_text(encoding="utf-8")
        csp_file = projects_dir / f"{clean_name}.csp"
        if csp_file.exists():
            return json.dumps({
                "name": clean_name,
                "file_path": str(csp_file),
                "type": "Cscape Native Project (.csp)",
                "size_bytes": csp_file.stat().st_size,
            }, indent=2)
        return json.dumps({"error": f"Project '{clean_name}' not found", "project_name": clean_name}, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "project_name": project_name}, indent=2)


def get_project_diagnostics_resource(project_name: str) -> str:
    """Returns JSON diagnostics for a specific project."""
    try:
        clean_name = SafetyGuard.validate_project_name(project_name)
        projects_dir = WORKSPACE_ROOT / "artifacts" / "projects"
        diag_path = projects_dir / clean_name / "build" / "diagnostics.json"
        if diag_path.exists():
            return diag_path.read_text(encoding="utf-8")
        return json.dumps({
            "project_name": clean_name,
            "diagnostics": {
                "errors": [],
                "warnings": [],
                "info": ["No compilation diagnostics found for project."],
            },
            "compile_successful": True,
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "project_name": project_name}, indent=2)


def get_templates_catalog_resource() -> str:
    """Returns JSON catalog of available IEC 61131-3 Structured Text templates."""
    catalog = get_template_catalog()
    return json.dumps({"templates": catalog, "total_count": len(catalog)}, indent=2)


def get_template_content_resource(template_name: str) -> str:
    """Returns Structured Text source code for a template."""
    code = get_template_code(template_name)
    if code is not None:
        return code
    return f"// Error: Template '{template_name}' not found."


def get_safety_status_resource() -> str:
    """Returns JSON verification of safety directives and hardware lockout."""
    status = SafetyGuard.get_safety_status()
    return json.dumps(status, indent=2)


def register_resources(server: Any) -> None:
    """Registers all Cscape MCP resources on the given MCPServer instance."""
    server.resource("cscape://projects")(get_projects_resource)
    server.resource("cscape://project/{project_name}/state")(get_project_state_resource)
    server.resource("cscape://project/{project_name}/diagnostics")(get_project_diagnostics_resource)
    server.resource("cscape://templates")(get_templates_catalog_resource)
    server.resource("cscape://template/{template_name}")(get_template_content_resource)
    server.resource("cscape://safety/status")(get_safety_status_resource)
