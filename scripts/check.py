#!/usr/bin/env python3
"""The harness repo's own gates.

Small on purpose: this repo is prose and two manifests, so the things that can break are
a manifest that no longer parses, a plugin source path that points at nothing, and a
vendor round-trip that stops detecting the drift it exists to detect.

The last one is the gate that matters. `vendor_sync.py check` is the only thing standing
between a consuming repo and a silently stale copy of layer A, so a change that makes it
pass when it should fail has to fail here.

Stdlib only, for the same reason the rest of this repo is: no setup step anywhere.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# When gating a *generated* tree, this script is invoked from the source checkout while
# the working directory is the built tree. Prefer the working directory when it looks like
# a harness root, so the manifests that get checked are the built ones.
def _root() -> Path:
    here = Path.cwd()
    if (here / ".claude-plugin" / "marketplace.json").exists():
        return here
    return Path(__file__).resolve().parent.parent


ROOT = _root()
VENDOR_SYNC = ROOT / "scripts" / "vendor_sync.py"
SUBMODULE_CHECK = ROOT / "scripts" / "check_submodules.py"
GENERATOR = Path(".agents") / "transform" / "generate_main.py"
PLUGIN_DIR = "plugins/harness"
failures: list[str] = []


def fail(message: str) -> None:
    failures.append(message)
    print(f"  FAIL {message}")


def ok(message: str) -> None:
    print(f"  ok   {message}")


def check_manifests() -> None:
    print("manifests")
    marketplace_path = ROOT / ".claude-plugin" / "marketplace.json"
    plugin_path = ROOT / "plugins" / "harness" / ".claude-plugin" / "plugin.json"

    try:
        marketplace = json.loads(marketplace_path.read_text())
        ok("marketplace.json parses")
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"marketplace.json: {exc}")
        return

    try:
        plugin = json.loads(plugin_path.read_text())
        ok("plugin.json parses")
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"plugin.json: {exc}")
        return

    entries = marketplace.get("plugins", [])
    if not entries:
        fail("marketplace.json lists no plugins")
        return

    for entry in entries:
        source = entry.get("source")
        if not isinstance(source, str):
            # A git-source entry is legal in the schema but this repo hosts its own.
            fail(f"{entry.get('name')}: expected a relative source, got {source!r}")
            continue
        if not (ROOT / source).is_dir():
            fail(f"{entry.get('name')}: source {source} does not exist")
        else:
            ok(f"{entry.get('name')}: source {source} exists")
        # The name a consumer writes in enabledPlugins is <plugin>@<marketplace>, so a
        # mismatch here is a line of settings that silently resolves to nothing.
        if entry.get("name") != plugin.get("name"):
            fail(
                f"marketplace entry {entry.get('name')!r} does not match "
                f"plugin.json name {plugin.get('name')!r}"
            )
        else:
            ok(f"{entry.get('name')}@{marketplace.get('name')} resolves")


def run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)  # noqa: S603


def check_vendor_round_trip() -> None:
    print("vendor round-trip")
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "consumer"
        target.mkdir()

        synced = run(
            [sys.executable, str(VENDOR_SYNC), "sync", "--harness", str(ROOT), "--target", str(target)],
            cwd=ROOT,
        )
        if synced.returncode != 0:
            fail(f"sync failed: {synced.stderr.strip() or synced.stdout.strip()}")
            return
        ok("sync writes a vendored tree")

        vendored = target / ".agents" / "vendor" / "harness"
        manifest = vendored / "MANIFEST.json"
        if not manifest.exists():
            fail("sync wrote no MANIFEST.json")
            return

        files = json.loads(manifest.read_text())["files"]
        if not files:
            fail("MANIFEST.json records no files -- layer A would vendor as empty")
            return
        ok(f"manifest pins {len(files)} file(s)")

        clean = run([sys.executable, str(VENDOR_SYNC), "check", "--target", str(target)], cwd=ROOT)
        if clean.returncode != 0:
            fail(f"check rejects a freshly synced tree: {clean.stdout.strip()}")
        else:
            ok("check passes on a freshly synced tree")

        # The gate that earns its keep: a hand edit to generated content must be caught.
        edited = vendored / next(iter(files))
        edited.write_text(edited.read_text() + "\nlocal edit\n")
        tampered = run([sys.executable, str(VENDOR_SYNC), "check", "--target", str(target)], cwd=ROOT)
        if tampered.returncode == 0:
            fail("check passes on a hand-edited vendored file -- drift would go unnoticed")
        else:
            ok("check catches a hand-edited vendored file")

        # A pin behind HEAD is only stale when the vendored content actually moved.
        # Most harness commits touch tooling or the plugin manifest, neither of which is
        # vendored; failing on those would red-line every consuming PR for a change that
        # cannot reach it. Restore the tree, then age the pin without touching content.
        edited.write_text(edited.read_text().removesuffix("\nlocal edit\n"))
        older = run(["git", "rev-list", "--max-parents=0", "-n", "1", "HEAD"], cwd=ROOT)
        if older.returncode == 0 and older.stdout.strip():
            manifest_path = vendored / "MANIFEST.json"
            aged = json.loads(manifest_path.read_text())
            aged["sha"] = older.stdout.strip()
            manifest_path.write_text(json.dumps(aged, indent=2) + "\n")
            behind = run(
                [sys.executable, str(VENDOR_SYNC), "check", "--target", str(target),
                 "--harness", str(ROOT)],
                cwd=ROOT,
            )
            if behind.returncode != 0:
                fail(
                    "check fails on a pin that is behind but content-identical -- "
                    f"consuming PRs would go red for nothing: {behind.stdout.strip()}"
                )
            elif "no vendored file changed" not in behind.stdout:
                fail("check passed but did not report why the pin is behind")
            else:
                ok("check tolerates a behind-but-identical pin, and says so")

        # And a file that layer A does not ship must not survive a sync.
        stray = vendored / "stray.md"
        stray.write_text("not part of layer A\n")
        extra = run([sys.executable, str(VENDOR_SYNC), "check", "--target", str(target)], cwd=ROOT)
        if extra.returncode == 0:
            fail("check passes with an unrecognised file in the vendored tree")
        else:
            ok("check catches an unrecognised vendored file")


def check_generated_tree() -> None:
    print("main generation")
    generator = ROOT / ".agents" / "transform" / "generate_main.py"
    if not generator.exists():
        fail("generate_main.py is missing")
        return
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "main"
        built = run([sys.executable, str(generator), str(ROOT), str(out)], cwd=ROOT)
        if built.returncode != 0:
            fail(f"generator failed: {built.stderr.strip() or built.stdout.strip()}")
            return
        ok("generator builds a main tree")

        if (out / "AGENTS.md").exists():
            fail("generated main still carries AGENTS.md")
        elif not (out / "CLAUDE.md").exists():
            fail("generated main has no CLAUDE.md")
        else:
            ok("instruction file renamed for main")

        if (out / ".agents").exists():
            fail("generated main still carries .agents/")
        else:
            ok(".agents/ dropped from main")

        # The neutral branch's Codex paragraph must not survive into the Claude branch.
        tracker = out / "plugins" / "harness" / "docs" / "agents" / "issue-tracker.md"
        if not tracker.exists():
            fail("generated main lost the plugin docs")
        elif "sbx mcp add" in tracker.read_text():
            fail("an agnostic region survived into main")
        else:
            ok("agnostic regions resolved out of main")


def check_shared_generator() -> None:
    """The generator is one file in three repos, and nothing until now noticed a drift.

    `generate_main.py` is byte-identical in both stacks and here; only `transform.json`
    differs. That was maintained by hand because no repo could see the other two. The
    submodules are what make it checkable, which is most of why they are mounted.
    """
    print("shared generator")
    mine = ROOT / GENERATOR
    if not mine.exists():
        fail(f"{GENERATOR} is missing")
        return

    checked = 0
    for name in ("python-harness", "frontend-harness"):
        theirs = ROOT / name / GENERATOR
        if not theirs.exists():
            print(f"  skip {name} is not checked out -- run `git submodule update --init`")
            continue
        checked += 1
        if theirs.read_bytes() != mine.read_bytes():
            fail(
                f"{name}/{GENERATOR} differs from this repo's copy. It is one file in "
                f"three repos -- reconcile it before either branch is regenerated."
            )
        else:
            ok(f"{name} carries the same generator")
    if not checked:
        print("  skip no submodule checked out -- nothing to compare")


def check_submodule_guard() -> None:
    """The guard has to keep catching the trap it was written for.

    `git checkout` does not move a submodule's working tree, so a `v2` parent can sit on
    `main` children in silence. `check_submodules.py` is the only thing that says so, and
    a guard that quietly stops guarding is worse than no guard -- so build the trap and
    prove it still trips.
    """
    print("submodule guard")
    if not SUBMODULE_CHECK.exists():
        fail("check_submodules.py is missing")
        return

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        child, parent = base / "child", base / "parent"

        def git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
            # Literals and paths this function just made. `protocol.file.allow` is
            # needed because git refuses a local-path submodule by default.
            return run(["git", "-c", "protocol.file.allow=always", *args], cwd)

        child.mkdir()
        git("init", "-q", "-b", "v2", cwd=child)
        (child / "README.md").write_text("child\n")
        git("add", "-A", cwd=child)
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "v2", cwd=child)
        git("branch", "main", cwd=child)

        parent.mkdir()
        git("init", "-q", "-b", "v2", cwd=parent)
        added = git("submodule", "add", "-q", "-b", "v2", str(child), "child", cwd=parent)
        if added.returncode != 0:
            fail(f"could not build the fixture: {added.stderr.strip()}")
            return
        git("add", "-A", cwd=parent)
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "mount", cwd=parent)

        clean = run([sys.executable, str(SUBMODULE_CHECK)], parent)
        if clean.returncode != 0:
            fail(f"guard rejects a consistent parent: {clean.stdout.strip()}")
        else:
            ok("guard passes when the child matches the parent")

        # The trap: move the child to the other branch, exactly as `git checkout` on the
        # parent would have failed to do.
        git("checkout", "-q", "main", cwd=parent / "child")
        tripped = run([sys.executable, str(SUBMODULE_CHECK)], parent)
        if tripped.returncode == 0:
            fail("guard passes with the child on the wrong branch -- the trap is unguarded")
        elif "wrong" not in tripped.stdout and "main" not in tripped.stdout:
            fail(f"guard failed but did not name the branch: {tripped.stdout.strip()}")
        else:
            ok("guard catches a child sitting on the other branch")

        # And the SessionStart adapter has to hand Claude Code something it can parse.
        hooked = run([sys.executable, str(SUBMODULE_CHECK), "--hook"], parent)
        if hooked.returncode != 0:
            fail("hook mode exits non-zero -- SessionStart has no blocking code to use")
            return
        try:
            payload = json.loads(hooked.stdout)
        except json.JSONDecodeError:
            fail(f"hook mode emitted non-JSON: {hooked.stdout.strip()[:120]}")
            return
        if not payload.get("hookSpecificOutput", {}).get("additionalContext"):
            fail("hook mode emitted no additionalContext for a real mismatch")
        else:
            ok("hook mode emits SessionStart context for a mismatch")


def check_version_bump(base: str) -> None:
    """Layer A content must never change without the plugin version changing with it.

    `claude plugin update` compares the `version` field, not the commit sha. A content
    change shipped under an unchanged version reports "already at the latest version" and
    never reaches the cache a session actually reads -- silently, which is the whole failure
    mode this repo exists to remove. The vendored adapter shouts when it is stale; without
    this gate the plugin adapter does not.
    """
    print(f"version bump (vs {base})")
    changed = run(["git", "diff", "--name-only", base, "--", PLUGIN_DIR], cwd=ROOT)
    if changed.returncode != 0:
        fail(f"could not diff against {base}: {changed.stderr.strip()}")
        return

    touched = [f for f in changed.stdout.split("\n") if f.strip()]
    if not touched:
        ok("no layer A change in this ref")
        return

    content = [f for f in touched if not f.endswith("plugin.json")]
    if not content:
        ok("only the manifest changed")
        return

    before = run(["git", "show", f"{base}:{PLUGIN_DIR}/.claude-plugin/plugin.json"], cwd=ROOT)
    if before.returncode != 0:
        ok("no baseline manifest -- treating as the first release")
        return

    was = json.loads(before.stdout).get("version")
    now = json.loads((ROOT / PLUGIN_DIR / ".claude-plugin" / "plugin.json").read_text()).get("version")
    if was == now:
        fail(
            f"{len(content)} layer A file(s) changed but version is still {now!r}. "
            f"Consumers would be told they are already up to date. Bump it."
        )
        for f in content:
            print(f"       {f}")
    else:
        ok(f"version {was} -> {now} for {len(content)} changed file(s)")


def main() -> int:
    # `main` is built without `.agents/`, so the generator is not present in that tree and
    # the round-trip and generation checks cannot run there. The manifests are the part
    # that still has to hold, because they are what the marketplace reads.
    manifests_only = "--manifests-only" in sys.argv
    base = next(
        (a.split("=", 1)[1] for a in sys.argv if a.startswith("--since=")), None
    )

    check_manifests()
    if not manifests_only:
        check_vendor_round_trip()
        check_generated_tree()
        check_shared_generator()
        check_submodule_guard()
        if base:
            check_version_bump(base)
    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
