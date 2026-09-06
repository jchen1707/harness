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
            install = subprocess.run(config["install"], cwd=destination, text=True, capture_output=True)
            report = {"preset": preset, "install_exit": install.returncode,
                      "install_output": install.stdout + install.stderr}
            if install.returncode == 0:
                gates = subprocess.run(
                    ["node", str(HARNESS / "plugins/harness/hooks/gate_report.mjs"), "--force", "--json"],
                    cwd=destination, text=True, capture_output=True,
                )
                report["gates"] = json.loads(gates.stdout)
                failed |= gates.returncode != 0
            else:
                failed = True
            (args.reports / f"{preset}.json").write_text(json.dumps(report, indent=2) + "\n")
            print(f"{preset}: {report.get('gates', {}).get('verdict', 'install failed')}", flush=True)
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
