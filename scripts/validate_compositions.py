#!/usr/bin/env python3
"""Install every preset in isolation and execute its declared shared gate report."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from compose_project import compose
from new_project import HARNESS


def missing_review_inputs(destination: Path, config: dict) -> list[str]:
    """Check composed language-specific checklists against the shared frame catalog."""
    shared = HARNESS / "plugins/harness"
    axes = json.loads((shared / "workflows/review-axes.json").read_text())
    review = config.get("review", {})
    if review.get("ninthAxis"):
        axes.append(review["ninthAxis"])
    missing = []
    for axis in axes:
        name = axis["agent"] + ".md"
        own = destination / review.get("agentDir", ".agents/agents") / name
        frame = own if own.is_file() else shared / "agents" / name
        checklist = destination / review.get("checklistDir", "docs/agents/subagents") / name
        if not frame.is_file():
            missing.append(f"frame:{name}")
        if not checklist.is_file():
            missing.append(f"checklist:{name}")
    return missing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalog", type=Path)
    parser.add_argument("--reports", type=Path, required=True)
    args = parser.parse_args()
    catalog = args.catalog.resolve()
    presets = json.loads(catalog.read_text())["presets"]
    args.reports.mkdir(parents=True, exist_ok=True)
    failed = False
    for preset in presets:
        with tempfile.TemporaryDirectory(prefix="harness-preset-") as temporary:
            destination = Path(temporary) / "project"
            compose(catalog, preset, [], destination, f"validate-{preset}", agnostic=False)
            config = json.loads((destination / "harness.config.json").read_text())
            missing = missing_review_inputs(destination, config)
            failed |= bool(missing)
            install = subprocess.run(
                config["install"],
                cwd=destination,
                text=True,
                capture_output=True,
                check=False,
                timeout=600,
            )
            report = {
                "preset": preset,
                "missing_review_inputs": missing,
                "install_exit": install.returncode,
                "install_output": install.stdout + install.stderr,
            }
            if install.returncode == 0:
                gates = subprocess.run(
                    [
                        "node",
                        str(HARNESS / "plugins/harness/hooks/gate_report.mjs"),
                        "--force",
                        "--json",
                        "--authority",
                        str(destination),
                        "--profile",
                        config.get("delivery", {}).get("default", ""),
                    ],
                    cwd=destination,
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=1800,
                )
                report["gates"] = json.loads(gates.stdout)
                failed |= gates.returncode != 0
            else:
                failed = True
            (args.reports / f"{preset}.json").write_text(json.dumps(report, indent=2) + "\n")
            verdict = (
                "incomplete review inputs"
                if missing
                else report.get("gates", {}).get("verdict", "install failed")
            )
            print(f"{preset}: {verdict}", flush=True)
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
