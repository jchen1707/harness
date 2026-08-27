#!/usr/bin/env python3
"""Catch a parent ref whose submodules are sitting on the wrong world.

`git checkout` does not move a submodule's working tree. Switch this repo from `main` to
`v2` and the two stacks underneath stay exactly where they were — on the other branch,
with the other harness's assumptions, silently. Nothing warns you. You read
`frontend-harness/CLAUDE.md` while standing on `v2` and conclude the neutral branch says
something it does not.

`git config submodule.recurse true` fixes it for whoever runs it. This is for whoever did
not — which, on a fresh clone, is everybody.

Three callers, one implementation:

    check_submodules.py            human output, non-zero exit  (CI, and by hand)
    check_submodules.py --hook     SessionStart JSON, always exit 0
    check_submodules.py --pins     also ask whether each pin is still on its branch
    check_submodules.py --current  also ask whether each pin is still up to date

`--pins` is the only mode that needs the remote refs fetched, which is why it is a flag
rather than the default: a SessionStart hook that reaches the network on every start is a
hook people turn off.

`--current` is a flag for the opposite reason: it is *expected* to fail for a while. Layer A
merges here first and the stacks vendor it afterwards, so between those two events the pins
are legitimately behind and this says so. Run it where that window is the thing you want to
hear about -- a push to `v2`, once the change is in -- and not on a pull request, where the
answer is "yes, obviously, that is what this PR is about."

Why it exists at all: `--pins` asks only whether a pin is *on* the branch `.gitmodules`
names, never whether it is current. That is how the mounting drifted eight vendor syncs deep
without one check failing, and the mounting is what onboarding, cross-stack review and the
cross-stack CI job all read.

The hook cannot actually refuse: Claude Code's SessionStart event has no blocking exit
code — stderr is shown to the user and that is all. So it does the strongest thing the
event allows, which is to put the mismatch in front of the agent as context, with the
command that fixes it. The CI job is the half that can say no.

Stdlib only, like everything else here: no setup step anywhere.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

# The branches whose name *is* a claim about which world this ref belongs to. A feature
# branch off `v2` inherits `v2`'s `.gitmodules`, so the declared branch is the thing to
# compare against — but when the parent is standing on one of these by name, the two must
# also agree with each other, or the region markers in `.gitmodules` were resolved wrong.
FLAVOUR_BRANCHES = frozenset({"v2", "main"})

FIX_RECURSE = "git config submodule.recurse true"
FIX_INIT = "git submodule update --init --recursive"
FIX_SYNC = "git submodule update --recursive"


def git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run git. Every argument here is a literal or a path this script resolved."""
    return subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def repo_root() -> Path | None:
    result = git("rev-parse", "--show-toplevel")
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip())


def declared(root: Path) -> dict[str, str]:
    """Each submodule path mapped to the branch `.gitmodules` says this ref reads.

    Read with git's own config parser rather than by hand, so the region markers that
    make `branch` differ between `v2` and `main` stay ordinary comments.
    """
    config = str(root / ".gitmodules")
    listing = git("config", "-f", config, "--get-regexp", r"^submodule\..*\.path$", cwd=root)
    if listing.returncode != 0:
        return {}
    branches: dict[str, str] = {}
    for line in listing.stdout.splitlines():
        key, _, path = line.partition(" ")
        name = key.removeprefix("submodule.").removesuffix(".path")
        branch = git("config", "-f", config, "--get", f"submodule.{name}.branch", cwd=root)
        branches[path] = branch.stdout.strip()
    return branches


def parent_branch(root: Path) -> str:
    """The parent's branch, or "" when it is detached — CI checkouts usually are."""
    result = git("symbolic-ref", "--short", "-q", "HEAD", cwd=root)
    return result.stdout.strip() if result.returncode == 0 else ""


def inspect(root: Path) -> tuple[list[str], list[str]]:
    """Every way the submodules can disagree with this ref, as human sentences.

    Two lists, because they carry different weight. A *problem* is a working tree that
    disagrees with the ref right now — it fails CI and it is what the hook shouts about.
    An *advisory* is local configuration that will let the problem happen again; a fresh
    CI checkout never has it set and never needs it, so failing on that would red-line
    every run for nothing.
    """
    problems: list[str] = []
    advisories: list[str] = []
    branches = declared(root)
    if not branches:
        return problems, advisories

    # `git submodule status` prefixes each line: `-` never initialised, `+` checked out
    # at a commit other than the one this ref pins, `U` mid-conflict. That prefix is the
    # precise signal, and cheaper than resolving each child's HEAD by hand.
    status = git("submodule", "status", cwd=root)
    if status.returncode != 0:
        return [f"could not read submodule status: {status.stderr.strip()}"], advisories

    seen: set[str] = set()
    for line in status.stdout.splitlines():
        if not line:
            continue
        marker, rest = line[0], line[1:]
        sha, _, remainder = rest.partition(" ")
        path = remainder.split(" (")[0].strip()
        seen.add(path)
        want = branches.get(path, "")

        if marker == "-":
            problems.append(f"{path} is not checked out. Run `{FIX_INIT}`.")
            continue
        if marker == "U":
            problems.append(f"{path} has a merge conflict in its gitlink. Resolve it before working here.")
            continue
        if marker == "+":
            problems.append(
                f"{path} is checked out at {sha[:9]}, which is not what this ref pins. "
                f"Run `{FIX_SYNC}`."
            )

        # A submodule updated the ordinary way sits on a detached HEAD at the pinned
        # commit, which is correct and says nothing about which branch it came from. An
        # *attached* one is a claim, and a wrong claim is the trap this script is for.
        head = git("symbolic-ref", "--short", "-q", "HEAD", cwd=root / path)
        on = head.stdout.strip() if head.returncode == 0 else ""
        if on and want and on != want:
            problems.append(
                f"{path} is on branch {on!r}, but this ref reads {want!r}. "
                f"Run `git -C {path} checkout {want}` — or `{FIX_SYNC}`."
            )

    for path in branches.keys() - seen:
        problems.append(f"{path} is declared in .gitmodules but git does not see it.")

    # If the parent's own name is a flavour, `.gitmodules` has to agree with it. A
    # disagreement means the generated branch was built wrong, not that a checkout drifted.
    parent = parent_branch(root)
    if parent in FLAVOUR_BRANCHES:
        for path, want in sorted(branches.items()):
            if want and want != parent:
                problems.append(
                    f"this ref is {parent!r} but .gitmodules points {path} at {want!r}. "
                    f"The region markers in .gitmodules did not resolve for this branch."
                )

    recurse = git("config", "--get", "submodule.recurse", cwd=root)
    if recurse.stdout.strip() != "true":
        advisories.append(
            f"submodule.recurse is not set, so `git checkout` will leave these behind "
            f"again. Run `{FIX_RECURSE}`."
        )

    return problems, advisories


def check_pins(root: Path, branches: dict[str, str]) -> list[str]:
    """Is each pinned commit still on the branch `.gitmodules` says it came from?

    `git submodule status` compares the working tree against the index and stops there.
    It is entirely happy with a pin at a commit that was force-pushed away, or that only
    ever lived on a feature branch — which clones fine and leaves the reader looking at
    something no stack branch contains. Needs `origin/<branch>` fetched inside each
    submodule; the CI step does that immediately before calling this.
    """
    problems: list[str] = []
    for path, want in sorted(branches.items()):
        if not want:
            continue
        pinned = git("rev-parse", f"HEAD:{path}", cwd=root)
        if pinned.returncode != 0:
            problems.append(f"{path} has no gitlink in this ref's tree.")
            continue
        sha = pinned.stdout.strip()
        remote = f"origin/{want}"
        known = git("rev-parse", "--verify", "-q", f"{remote}^{{commit}}", cwd=root / path)
        if known.returncode != 0:
            problems.append(f"{path} has no {remote} to check the pin against -- fetch it first.")
            continue
        contained = git("merge-base", "--is-ancestor", sha, remote, cwd=root / path)
        if contained.returncode != 0:
            problems.append(
                f"{path} is pinned at {sha[:9]}, which is not on {remote}. "
                f"The commit was rewritten, or the pin was taken from a branch that "
                f"never merged."
            )
    return problems


def check_currency(root: Path, branches: dict[str, str], exec_=None) -> list[str]:
    """Does each pinned stack still vendor the layer A this ref carries?

    Delegates to `vendor_sync.py check`, which is the freshness check each consumer's own CI
    runs, so the answer here and the answer there cannot disagree. It is the right judgment
    already: a pin some commits behind whose vendored files are byte-identical is reported as
    a note and passes, because layer A did not actually move. Only content drift fails.

    Read against the *working tree*, which `inspect()` has already established matches the
    pin -- so a currency answer is only meaningful when the base check passed, and `main`
    skips this when it did not.
    """
    vendor_sync = root / "scripts" / "vendor_sync.py"
    if exec_ is None and not vendor_sync.exists():
        return []

    def default(argv: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603
            argv, capture_output=True, text=True, check=False, cwd=root
        )

    exec_ = exec_ or default

    problems: list[str] = []
    for path in sorted(branches):
        if exec_ is default and not (root / path / ".git").exists():
            continue  # Not checked out; `inspect()` has already said so.
        result = exec_(
            [sys.executable, str(vendor_sync), "check", "--target", str(root / path),
             "--harness", str(root)]
        )
        if result.returncode == 0:
            continue

        # "Stale" and "could not tell" are different answers, and reporting the second as
        # the first is worse than not checking at all. `vendor_sync.py` prints its verdict
        # on stdout and dies on stderr -- a `SystemExit` from a git command it could not
        # run -- so an empty stdout means the check never reached a verdict. The shape that
        # produced this: a shallow CI checkout, where the sha the stack vendors is simply
        # not in the clone, so `git rev-list <pinned>..HEAD` fails. It read as a confident
        # "your pins are stale" with no detail attached, against pins that were current.
        #
        # Named rather than swallowed, and it still fails: the same rule the gate report
        # applies to a gate that could not start. A check that did not run must never be
        # rounded to either green or a specific red.
        verdict = next(
            (line.strip() for line in result.stdout.splitlines() if "stale pin" in line), ""
        )
        if not verdict:
            reason = (result.stderr.strip() or result.stdout.strip() or "no output").splitlines()
            problems.append(
                f"{path}: could not determine whether the pin is current -- "
                f"`vendor_sync.py check` did not reach a verdict: {reason[0]} "
                f"(a shallow checkout does this; the job needs fetch-depth: 0)"
            )
            continue

        problems.append(
            f"{path} pins a commit whose layer A is behind this ref. {verdict} "
            f"Sync and merge in {path}, then bump the pin here."
        )
    return problems


def main(argv: list[str]) -> int:
    root = repo_root()
    if root is None or not (root / ".gitmodules").exists():
        return 0

    problems, advisories = inspect(root)
    if "--pins" in argv:
        problems += check_pins(root, declared(root))
    # Only when the pins point where this ref says they do -- otherwise the freshness answer
    # describes whatever the working tree happens to be sitting on, not the pin.
    if "--current" in argv and not problems:
        problems += check_currency(root, declared(root))

    if "--hook" in argv:
        if problems:
            body = "\n".join(f"- {line}" for line in problems + advisories)
            context = (
                "The submodules under this repo do not match the branch you are on, so "
                "anything read out of those directories may belong to the other branch.\n"
                f"{body}\n\n"
                "Tell the user what is out of step and stop until it is fixed. These "
                "submodules are for reading only — a stack's work is never committed "
                "through this repo."
            )
            print(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "SessionStart",
                            "additionalContext": context,
                        }
                    }
                )
            )
            print(context, file=sys.stderr)
        # A SessionStart hook that exits non-zero buys nothing — the event has no
        # blocking code — and costs a scary line in the transcript on every clean start.
        return 0

    for advisory in advisories:
        print(f"  note {advisory}")
    for problem in problems:
        print(f"  FAIL {problem}")
    if problems:
        print(f"\n{len(problems)} submodule problem(s)")
        return 1
    print("  ok   submodules match this ref")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
