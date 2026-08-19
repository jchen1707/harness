#!/usr/bin/env python3
"""Sync layer A into a mounted stack and run that stack's own gates against the result.

This is the job phase 3 deferred, and the reason it was deferred is the reason it is
shaped this way. The obvious version -- "run both stacks' gate suites at their pinned
commits" -- re-specifies ruff/mypy/pytest and the pnpm equivalents here, which is a second
authoring of each stack's Definition of Done in the one repository that exists to end
second authorings. It would drift, and its signal was already covered: a pin that is not
on a merged branch is refused by `check_submodules.py --pins`, so that commit's own CI was
green.

What only the meta-repo can do is the other question: **does a change to layer A break a
stack?** Nothing inside either stack can ask it -- they see layer A only at the sha they
pinned, which is by construction the last one that worked. So this syncs the working
tree's layer A into each stack and runs the gates the stack itself declares in
`harness.config.json`. The gate list is read, never restated.

While layer A was prose this had nothing to measure. It now carries a workflow, a schema
and eight review frames, and phase 5 puts the hooks in it.

Stdlib only, like everything else here.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR_SYNC = ROOT / "scripts" / "vendor_sync.py"

# Kinds that run without a browser, a container or a network. The rest are opt-in in the
# stack's own CI too, and standing them up here would mean this job reimplementing each
# stack's service setup -- the drift the whole file is written to avoid.
DEFAULT_KINDS = frozenset({"lint", "format", "types", "test"})


def run(args: list[str], cwd: Path) -> int:
    print(f"    $ {' '.join(args)}", flush=True)
    return subprocess.run(args, cwd=cwd, check=False).returncode  # noqa: S603


def gate_stack(stack: Path, kinds: frozenset[str]) -> tuple[bool, list[str]]:
    """Sync layer A into `stack`, run its declared gates.

    Returns whether any gate actually ran, and the failures. The first half matters:
    a job that skips both stacks and prints a pass is the vacuous green this repository
    keeps finding in other people's gates.

    **This writes to the stack's working tree.** It replaces `.agents/vendor/harness/`
    with the layer A in this checkout, which is the whole point -- the question is what
    the stack does with the layer A you are about to publish, not with the one it pinned.
    Nothing is committed. Restore a local run with `git -C <stack> checkout -- .`.
    """
    name = stack.name
    print(f"\n=== {name} ===", flush=True)

    config_path = stack / "harness.config.json"
    if not config_path.exists():
        print(f"  skip {name} has no harness.config.json -- nothing declares its gates")
        return False, []

    synced = subprocess.run(  # noqa: S603
        [sys.executable, str(VENDOR_SYNC), "sync", "--harness", str(ROOT), "--target", str(stack)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if synced.returncode != 0:
        return False, [f"{name}: sync failed: {synced.stderr.strip() or synced.stdout.strip()}"]
    print(f"  layer A synced from the working tree ({synced.stdout.splitlines()[0]})")

    # The sync has to survive its own freshness check, or every consuming PR will fail on
    # a tree this repository just produced.
    verified = subprocess.run(  # noqa: S603
        [sys.executable, str(VENDOR_SYNC), "check", "--target", str(stack)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if verified.returncode != 0:
        return False, [f"{name}: the freshly synced tree fails its own check:\n{verified.stdout}"]
    print("  the synced tree passes its own integrity check")

    config = json.loads(config_path.read_text())
    failures: list[str] = []

    install = config.get("install")
    if install and run(install, stack) != 0:
        return False, [f"{name}: `{' '.join(install)}` failed -- no gate could run"]

    ran = 0
    for gate in config.get("gates", []):
        if gate.get("kind") not in kinds:
            print(f"    skip {gate['name']} ({gate.get('kind')})")
            continue
        ran += 1
        print(f"  gate: {gate['name']}")
        if run(gate["run"], stack) != 0:
            failures.append(f"{name}: gate {gate['name']!r} fails against this layer A")
        elif gate.get("caveat"):
            # A green gate that says how it can pass vacuously is worth printing green
            # *with* the caveat, so a reader does not take it for more than it is.
            print(f"    ok, but: {gate['caveat']}")

    if not ran:
        failures.append(f"{name}: declares no gate of kind {sorted(kinds)} -- nothing was proved")
    return ran > 0, failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "stacks", nargs="*", help="submodule directories to gate (default: all mounted)"
    )
    parser.add_argument(
        "--kinds",
        default=",".join(sorted(DEFAULT_KINDS)),
        help="comma-separated gate kinds to run",
    )
    args = parser.parse_args()

    names = args.stacks or [
        line.split()[1]
        for line in subprocess.run(  # noqa: S603
            ["git", "config", "-f", ".gitmodules", "--get-regexp", r"^submodule\..*\.path$"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        ).stdout.splitlines()
    ]
    if not names:
        print("no submodules mounted -- run `git submodule update --init`")
        return 1

    kinds = frozenset(k.strip() for k in args.kinds.split(",") if k.strip())
    failures: list[str] = []
    gated: list[str] = []
    for name in names:
        stack = ROOT / name
        if not (stack / ".git").exists():
            print(f"skip {name} is not checked out")
            continue
        ran, problems = gate_stack(stack, kinds)
        failures.extend(problems)
        if ran:
            gated.append(name)

    print()
    if failures:
        print(f"{len(failures)} cross-stack failure(s):")
        for f in failures:
            print(f"  - {f}")
        return 1
    if not gated:
        print(
            "no stack was gated. Until a stack declares harness.config.json this job has\n"
            "nothing to run, and saying so is the honest result -- a green tick here would\n"
            "mean layer A had been proved against two repositories it never touched."
        )
        return 0
    print(f"layer A passes the declared gates of: {', '.join(gated)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
