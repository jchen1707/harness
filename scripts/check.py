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
