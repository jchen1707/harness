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
`harness.config.json`.

**It runs them by invoking the layer A it just delivered.** `gate_report.mjs`, out of the
freshly synced `.agents/vendor/harness/hooks/`, decides which gates apply, in which
directories, and what each result means; this file reads the JSON document that comes back
and formats it. That is deliberate and it is the whole point of the job:

- Gate selection has one implementation. `gate_report.mjs` states that a caller must never
  re-derive which gates apply, "because that would re-author `dispatch()` and `STOP_KINDS`
  in Python where they would drift silently -- the single failure this repository exists to
  prevent." This file used to be that Python. It kept a `DEFAULT_KINDS` frozenset and its
  own gate loop, and by the time it was replaced it had missed four features in ten commits:
  `enabled: false`, `requires` probes, per-gate opt-in, and monorepo `apps` dispatch. A
  stack that switched a gate off still had it run here, and a gate whose browser was missing
  was reported as a layer A regression.
- The question gets asked of the artifact that ships. Running the working tree's copy
  instead would prove something about a tree no stack will ever execute, and would leave the
  vendoring adapter itself ungated.

The gate list is read, never restated -- and now so is every judgment about it.

Stdlib only, like everything else here. Node is not a new dependency: both stacks declare
Node 22 in `.nvmrc` and both already vendor and gate `.agents/vendor/harness/hooks`.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR_SYNC = ROOT / "scripts" / "vendor_sync.py"

# Where `vendor_sync.py sync` puts layer A inside a consuming repo, and the reporter within
# it. Not configurable, and not read from anywhere: this is the path this repo's own sync
# just wrote, one function call up.
VENDOR_DIR = Path(".agents/vendor/harness")
GATE_REPORT = VENDOR_DIR / "hooks" / "gate_report.mjs"
# Records the harness sha the tree was taken at, so it moves on every commit here even when
# layer A's content did not. See `layer_a_moved`.
MANIFEST_NAME = "MANIFEST.json"

# Statuses that mean a gate actually executed. Everything else is a documented dispatch
# decision -- switched off, not asked for, or belonging to an app the change never touched.
# This is presentation, not selection: it decides what to print, never what to run.
RAN = frozenset({"pass", "fail"})


def run(args: list[str], cwd: Path) -> int:
    print(f"    $ {' '.join(args)}", flush=True)
    return subprocess.run(args, cwd=cwd, check=False).returncode  # noqa: S603


def _capture(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        args, cwd=cwd, capture_output=True, text=True, check=False
    )


def layer_a_moved(stack: Path, exec_=_capture) -> bool:
    """Did the sync actually change this stack's vendored layer A *content*?

    Asked before the toolchain is installed, so an unchanged layer A costs neither an
    install nor a gate run. This is not a gate-selection decision and must not become one:
    it asks only whether *this script's own write* moved anything. Whether that constitutes
    a change the gates care about is `gate_report.mjs`'s judgment, made against the stack's
    own `gatedPaths`, and it is made again independently below.

    **`MANIFEST.json` is excluded, and that exclusion is the whole correctness of this
    function.** The manifest records the harness sha the tree was taken at, so it changes on
    every commit here whether or not a single byte of layer A did. Counting it as movement
    made this function answer "yes" while `gate_report.mjs` -- which looks at the stack's
    `gatedPaths` (`.agents/vendor/harness/hooks`) filtered to its `gatedExtensions` -- kept
    correctly answering "no". Two questions that have to agree, asked in different terms,
    and the disagreement landed in the vacuous-green guard below as a hard failure on every
    harness PR that did not touch layer A. It stayed hidden only while the stacks' pins were
    stale enough that layer A really had moved every time.
    """
    result = exec_(
        [
            "git",
            "status",
            "--porcelain",
            "--",
            str(VENDOR_DIR),
            f":(exclude){VENDOR_DIR / MANIFEST_NAME}",
        ],
        stack,
    )
    if result.returncode != 0:
        return True  # Can't tell -> prove it rather than skip it.
    return bool(result.stdout.strip())


def gate_stack(stack: Path, asserted: list[str]) -> tuple[bool, list[str]]:
    """Sync layer A into `stack`, then run that stack's gates through the synced reporter.

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

    synced = _capture(
        [sys.executable, str(VENDOR_SYNC), "sync", "--harness", str(ROOT), "--target", str(stack)],
        ROOT,
    )
    if synced.returncode != 0:
        return False, [f"{name}: sync failed: {synced.stderr.strip() or synced.stdout.strip()}"]
    print(f"  layer A synced from the working tree ({synced.stdout.splitlines()[0]})")

    # The sync has to survive its own freshness check, or every consuming PR will fail on
    # a tree this repository just produced.
    verified = _capture([sys.executable, str(VENDOR_SYNC), "check", "--target", str(stack)], ROOT)
    if verified.returncode != 0:
        return False, [f"{name}: the freshly synced tree fails its own check:\n{verified.stdout}"]
    print("  the synced tree passes its own integrity check")

    if not layer_a_moved(stack):
        # The honest answer, and on most branches it is the true one: a PR that touches
        # only `templates/`, `scripts/` or prose leaves this stack's layer A byte-identical
        # to the sha it pinned, and that sha's own CI already proved it. Running the suite
        # anyway would spend twenty minutes re-proving a commit nobody changed.
        #
        # Note this is *not* the same skip `gate_report.mjs` would report. It is the
        # cheaper question asked first, so that an unchanged stack costs no install.
        print(f"  layer A here is identical to {name}'s pin -- nothing to prove")
        return False, []

    config = json.loads(config_path.read_text())

    # Toolchains, not gates: standing up dependencies is a property of the runner, which is
    # why the reporter never installs and this does. Ordered after the "did it move?" check
    # so an unchanged stack never pays for it.
    install = config.get("install")
    if install and run(install, stack) != 0:
        return False, [f"{name}: `{' '.join(install)}` failed -- no gate could run"]

    argv = ["node", str(stack / GATE_REPORT), "--json", "--cwd", str(stack)]
    for gate in asserted:
        argv += ["--gate", gate]
    print(f"  gates: {' '.join(argv)}", flush=True)
    reported = _capture(argv, stack)

    try:
        report = json.loads(reported.stdout)
    except json.JSONDecodeError:
        # The reporter is layer A. If it cannot produce a document, that is itself a layer A
        # regression this job exists to catch, and it is reported as one rather than as a
        # missing tool.
        detail = (reported.stderr.strip() or reported.stdout.strip())[:2000] or "(no output)"
        return False, [f"{name}: the synced gate_report.mjs emitted no report:\n{detail}"]

    ran = _print_gates(report)
    return ran > 0, _judge(name, report, ran)


def _print_gates(report: dict) -> int:
    """Print one line per gate. Returns how many actually executed."""
    ran = 0
    for gate in report.get("gates", []):
        status = gate.get("status")
        where = f" ({gate['app']})" if gate.get("app") and len(report.get("targets", [])) > 1 else ""
        print(f"    {status}\t{gate.get('name')}{where}")
        if status in RAN:
            ran += 1
        if status == "pass" and gate.get("caveat"):
            # A green gate that says how it can pass vacuously is worth printing green
            # *with* the caveat, so a reader does not take it for more than it is.
            print(f"      ok, but: {gate['caveat']}")
        if status in {"fail", "unavailable"} and gate.get("outputTail"):
            for line in gate["outputTail"].splitlines():
                print(f"      | {line}")
    return ran


def _judge(name: str, report: dict, ran: int) -> list[str]:
    """The report's verdict as this job's failures.

    `incomplete` is kept apart from `fail` on purpose. A gate that could not start does not
    mean layer A broke this stack; it means this job did not find out, and saying "fails
    against this layer A" would be a red tick for the wrong reason -- which teaches people
    to ignore the one job that says whether layer A still works.
    """
    verdict = report.get("verdict")
    if verdict == "fail":
        broken = [g["name"] for g in report["gates"] if g.get("status") == "fail"]
        return [f"{name}: gate(s) {', '.join(broken)} fail against this layer A"]
    if verdict == "incomplete":
        stalled = [g["name"] for g in report["gates"] if g.get("status") == "unavailable"]
        missing = report.get("missingApps") or []
        detail = ", ".join(stalled) or f"apps with no config: {', '.join(missing)}"
        return [f"{name}: could not prove layer A -- {detail} never ran"]
    if ran == 0:
        # Layer A moved, the gates were asked, and none of them executed. Every remaining
        # explanation is a defect in the stack's own declaration -- a gate list that is
        # empty, entirely switched off, or whose gatedPaths no longer cover the vendored
        # tree the sync just rewrote. A pass here would be the vacuous green.
        return [
            f"{name}: layer A changed but no gate ran -- check gates and hooks.gatedPaths "
            f"in {name}/harness.config.json"
        ]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "stacks", nargs="*", help="submodule directories to gate (default: all mounted)"
    )
    parser.add_argument(
        "--gate",
        action="append",
        default=[],
        metavar="NAME",
        help=(
            "assert one opt-in gate's `when` clause by name, repeatable. Without this, "
            "e2e and integration gates are not_applicable -- they need a browser or a "
            "container, and standing those up here would mean reimplementing each stack's "
            "service setup, the drift this whole file is written to avoid."
        ),
    )
    args = parser.parse_args()

    names = args.stacks or [
        line.split()[1]
        for line in _capture(
            ["git", "config", "-f", ".gitmodules", "--get-regexp", r"^submodule\..*\.path$"],
            ROOT,
        ).stdout.splitlines()
    ]
    if not names:
        print("no submodules mounted -- run `git submodule update --init`")
        return 1

    failures: list[str] = []
    gated: list[str] = []
    for name in names:
        stack = ROOT / name
        if not (stack / ".git").exists():
            print(f"skip {name} is not checked out")
            continue
        ran, problems = gate_stack(stack, args.gate)
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
            "no stack was gated. Either no stack declares harness.config.json yet, or this\n"
            "branch's layer A is identical to what both stacks already pinned -- in which\n"
            "case the commit they pinned has already proved it, and re-running their suites\n"
            "would measure the same tree twice."
        )
        return 0
    print(f"layer A passes the declared gates of: {', '.join(gated)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
