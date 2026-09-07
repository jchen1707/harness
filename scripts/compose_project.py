"""Compose a standalone project from a stack-owned catalog. No framework choices live here."""

from __future__ import annotations

import json
import re
import tempfile

from config_contract import load_schema, violations
from pathlib import Path

from new_project import HARNESS, copy_template, initialise


def merge(base: dict, extra: dict) -> dict:
    result = dict(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        elif isinstance(value, list) and isinstance(result.get(key), list):
            result[key] = result[key] + [item for item in value if item not in result[key]]
        else:
            result[key] = value
    return result


def toml(document: dict) -> str:
    lines = []

    def table(body: dict, path: list[str]) -> None:
        if path:
            lines.append("[" + ".".join(json.dumps(part) for part in path) + "]")
        for key, value in body.items():
            if not isinstance(value, dict):
                lines.append(f"{json.dumps(key)} = {json.dumps(value)}")
        lines.append("")
        for key, value in body.items():
            if isinstance(value, dict):
                table(value, [*path, key])

    table(document, [])
    return "\n".join(lines)


def compose(
    catalog_path: Path,
    preset: str,
    components: list[str],
    destination: Path,
    project: str,
    *,
    agnostic: bool = True,
    commit: bool = False,
) -> None:
    if not re.fullmatch(r"[a-z][a-z0-9-]*", project):
        raise ValueError("Project name must be a lowercase package slug")
    catalog = json.loads(catalog_path.read_text())
    if catalog.get("schemaVersion") != 1:
        raise ValueError("Unsupported component catalog version")
    manifest_path = Path(catalog["manifest"]["path"])
    if manifest_path.is_absolute() or ".." in manifest_path.parts or len(manifest_path.parts) != 1:
        raise ValueError("Manifest must be a root filename")
    if manifest_path.name in {".git", "harness.config.json", "AGENTS.md", "README.md"}:
        raise ValueError("Reserved manifest destination")
    if catalog["manifest"]["format"] not in {"toml", "json"}:
        raise ValueError("Unsupported manifest format")
    if preset not in catalog["presets"]:
        raise ValueError(f"Unknown preset: {preset}")
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Destination must be empty")
    selected = []
    visiting = set()

    def add(name: str) -> None:
        if name in selected:
            return
        if name in visiting:
            raise ValueError(f"Component dependency cycle: {name}")
        if name not in catalog["components"]:
            raise ValueError(f"Unknown component: {name}")
        visiting.add(name)
        for dependency in catalog["components"][name].get("requires", []):
            add(dependency)
        visiting.remove(name)
        selected.append(name)

    for component in [*catalog["presets"][preset], *components]:
        add(component)
    for name in selected:
        if set(catalog["components"][name].get("conflicts", [])) & set(selected):
            raise ValueError(f"Incompatible component: {name}")
    manifest = catalog["manifest"]["body"]
    config = catalog["config"]
    guidance = [
        "# " + project,
        "",
        "Implement approved tickets after the shared ticket-readiness check.",
        "Use one failing test and implementation slice at a time. Planning is optional.",
        "Run the gates declared in harness.config.json.",
        "",
    ]
    # Validate every source and collision before creating the destination.
    reserved = {manifest_path, Path("harness.config.json"), Path("AGENTS.md"), Path("README.md")}
    adapter = HARNESS / "templates" / ("agnostic" if agnostic else "plugin")
    reserved.update(path.relative_to(adapter) for path in adapter.rglob("*") if path.is_file())
    files = set(reserved)
    for name in selected:
        component = catalog["components"][name]
        template = component.get("template")
        if not template:
            continue
        relative = Path(template)
        source = catalog_path.parent / relative
        if relative.is_absolute() or ".." in relative.parts or not source.is_dir():
            raise ValueError("Invalid component template path")
        overrides = {Path(item) for item in component.get("overrides", [])}
        for origin in [source, *source.rglob("*")]:
            if origin.is_symlink() or not origin.resolve().is_relative_to(catalog_path.parent.resolve()):
                raise ValueError("Template path escapes the stack catalog")
            if not origin.is_file():
                continue
            target = origin.relative_to(source)
            if ".git" in target.parts or target in reserved:
                raise ValueError(f"Reserved template destination: {target}")
            if target in files and target not in overrides:
                raise ValueError(f"Undeclared template collision: {target}")
            files.add(target)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".compose-", dir=destination.parent) as temporary:
        staging = Path(temporary) / "project"
        staging.mkdir()
        _render(catalog_path, catalog, selected, staging, project, preset, guidance, manifest, config, agnostic, commit)
        if destination.exists():
            destination.rmdir()  # Refuse a destination populated since the initial check.
        staging.rename(destination)


def _render(catalog_path, catalog, selected, destination, project, preset, guidance, manifest, config, agnostic, commit):
    for name in selected:
        component = catalog["components"][name]
        template = component.get("template")
        if template:
            source = catalog_path.parent / template
            if not source.resolve().is_relative_to(catalog_path.parent.resolve()):
                raise ValueError("Template path escapes the stack catalog")
            copy_template(source, destination, project)
        manifest = merge(manifest, component.get("manifest", {}))
        config = merge(config, component.get("config", {}))
        guidance += [f"## {name}", "", component.get("guidance", ""), ""]
    config["name"] = project
    config["stackSelection"] = {"preset": preset, "components": selected}
    errors = violations(config, load_schema(HARNESS))
    if errors:
        raise ValueError("Generated config violates contract: " + "; ".join(errors))
    manifest_text = (
        toml(manifest)
        if catalog["manifest"]["format"] == "toml"
        else json.dumps(manifest, indent=2) + "\n"
    )
    (destination / catalog["manifest"]["path"]).write_text(
        manifest_text.replace("__PROJECT__", project)
    )
    (destination / "harness.config.json").write_text(json.dumps(config, indent=2) + "\n")
    (destination / "AGENTS.md").write_text("\n".join(guidance))
    (destination / "README.md").write_text("\n".join(guidance))
    copy_template(
        HARNESS / "templates" / ("agnostic" if agnostic else "plugin"), destination, project
    )
    initialise(destination, project, agnostic, commit, f"chore: scaffold {project} from {preset}")
