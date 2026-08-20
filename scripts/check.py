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
import re
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


def _source_branch() -> str:
    """The branch consumers vendor from, read from `vendor_sync.py` rather than restated.

    Two copies of the same constant is the drift this repository exists to remove, and a
    fixture pinned to the wrong branch fails in a way that reads like a real defect.
    """
    text = (ROOT / "scripts" / "vendor_sync.py").read_text(encoding="utf-8")
    found = re.search(r'^SOURCE_BRANCH = "([^"]+)"', text, re.MULTILINE)
    if not found:
        raise SystemExit("vendor_sync.py no longer declares SOURCE_BRANCH")
    return found.group(1)


SOURCE_BRANCH = _source_branch()
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

        # Against a clone at HEAD, not this working tree. Two reasons: a consumer only ever
        # receives committed content, so that is what the round-trip should exercise; and
        # `sync` now refuses a dirty checkout, which would otherwise make this gate
        # unrunnable for the one person most likely to want it -- somebody midway through
        # editing layer A.
        source = Path(tmp) / "harness"
        cloned = run(["git", "clone", "--quiet", "--no-hardlinks", str(ROOT), str(source)], cwd=ROOT)
        if cloned.returncode != 0:
            fail(f"could not clone the harness for the round-trip: {cloned.stderr.strip()}")
            return

        synced = run(
            [sys.executable, str(VENDOR_SYNC), "sync", "--harness", str(source), "--target", str(target)],
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

        # A sync from a dirty checkout would pin a sha whose content exists nowhere. Dirty
        # the clone rather than this checkout: a gate that edits the repository it is
        # gating has a failure mode of its own.
        scratch = source / PLUGIN_DIR / "docs" / "agents" / ".check-dirty.md"
        scratch.write_text("uncommitted\n")
        dirty = run(
            [sys.executable, str(VENDOR_SYNC), "sync", "--harness", str(source),
             "--target", str(target)],
            cwd=ROOT,
        )
        scratch.unlink()
        if dirty.returncode == 0:
            fail("sync accepts a dirty harness checkout -- the pin would name content that is not in it")
        elif "uncommitted" not in dirty.stderr + dirty.stdout:
            fail("sync refused a dirty checkout but did not say why")
        else:
            ok("sync refuses a dirty harness checkout")

        # And a file that layer A does not ship must not survive a sync.
        stray = vendored / "stray.md"
        stray.write_text("not part of layer A\n")
        extra = run([sys.executable, str(VENDOR_SYNC), "check", "--target", str(target)], cwd=ROOT)
        if extra.returncode == 0:
            fail("check passes with an unrecognised file in the vendored tree")
        else:
            ok("check catches an unrecognised vendored file")


def check_vendor_freshness() -> None:
    """Freshness is measured on content, and both of its answers have to be right.

    A pin behind the branch tip is only stale when layer A actually moved. Most commits
    here touch tooling, workflows or the plugin manifest, none of which is vendored --
    failing on those would red-line every open PR in every consuming repo for a change
    that cannot reach it, and an alarm that is wrong more often than it is right is one
    people learn to ignore.

    Proving both answers needs a harness whose history is known, so this builds one. The
    fixture used to age the pin against this repository's own root commit, which was
    content-identical only by accident: the first phase to add a file to layer A turned
    the guard red for the wrong reason, which is exactly the failure it exists to catch
    elsewhere.
    """
    print("vendor freshness")
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        source, remote, consumer = base / "harness", base / "origin.git", base / "consumer"

        def git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
            return run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd)

        layer_a = source / PLUGIN_DIR / "docs" / "agents"
        layer_a.mkdir(parents=True)
        (source / "README.md").write_text("harness fixture\n")
        (layer_a / "doctrine.md").write_text("shared doctrine\n")
        git("init", "-q", "-b", SOURCE_BRANCH, cwd=source)
        git("add", "-A", cwd=source)
        git("commit", "-qm", "layer A", cwd=source)

        remote.mkdir()
        git("init", "-q", "--bare", cwd=remote)
        git("remote", "add", "origin", str(remote), cwd=source)
        pushed = git("push", "-q", "origin", SOURCE_BRANCH, cwd=source)
        if pushed.returncode != 0:
            fail(f"could not build the fixture remote: {pushed.stderr.strip()}")
            return
        git("fetch", "-q", "origin", cwd=source)

        consumer.mkdir()
        synced = run(
            [sys.executable, str(VENDOR_SYNC), "sync", "--harness", str(source),
             "--target", str(consumer)],
            cwd=ROOT,
        )
        if synced.returncode != 0:
            fail(f"sync failed against the fixture: {synced.stderr.strip()}")
            return

        def freshness_check() -> subprocess.CompletedProcess[str]:
            return run(
                [sys.executable, str(VENDOR_SYNC), "check", "--target", str(consumer),
                 "--harness", str(source)],
                cwd=ROOT,
            )

        # A commit that cannot reach the consumer must not call it stale.
        (source / "README.md").write_text("harness fixture, edited\n")
        git("add", "-A", cwd=source)
        git("commit", "-qm", "docs: nothing layer A ships", cwd=source)
        git("push", "-q", "origin", SOURCE_BRANCH, cwd=source)
        git("fetch", "-q", "origin", cwd=source)

        behind = freshness_check()
        if behind.returncode != 0:
            fail(
                "check fails on a pin that is behind but content-identical -- "
                f"consuming PRs would go red for nothing: {behind.stdout.strip()}"
            )
        elif "no vendored file changed" not in behind.stdout:
            fail("check passed but did not report why the pin is behind")
        else:
            ok("a pin behind on non-vendored commits is not called stale")

        # And a commit that does reach it must.
        (layer_a / "doctrine.md").write_text("shared doctrine, revised\n")
        git("add", "-A", cwd=source)
        git("commit", "-qm", "docs: revise layer A", cwd=source)
        git("push", "-q", "origin", SOURCE_BRANCH, cwd=source)
        git("fetch", "-q", "origin", cwd=source)

        stale = freshness_check()
        if stale.returncode == 0:
            fail("check passes on a pin whose layer A moved upstream -- staleness is silent")
        elif "doctrine.md" not in stale.stdout:
            fail(f"check failed but did not name the changed file: {stale.stdout.strip()}")
        else:
            ok("a pin whose layer A moved is called stale, and the file is named")


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

        if (out / "CLAUDE.md").exists():
            fail("generated main still carries CLAUDE.md")
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


# The axes `full-review` runs, and the agents behind them. Layer A owns the eight shared
# ones; the ninth is whatever the consuming repo's config names.
SHARED_AXES = (
    "standards-reviewer",
    "spec-checker",
    "security-reviewer",
    "test-reviewer",
    "simplicity-reviewer",
    "design-reviewer",
    "perf-reviewer",
    "cost-reviewer",
)
GATE_KINDS = {"lint", "format", "types", "build", "test", "e2e", "integration"}


def check_layer_a_composition() -> None:
    """A shared frame plus a stack checklist has to actually compose.

    Every reviewer in layer A is half a definition: the frame here carries the role, the
    method and the reporting rules, and the repo's own `docs/agents/subagents/<name>.md`
    carries what "in this repo's terms" means there. Neither half is a review on its own,
    and the failure is silent in both directions -- a frame pointing at a missing file
    still reviews, on nothing but its own general advice, and reports a confident clean.
    """
    print("layer A composition")
    agents_dir = ROOT / PLUGIN_DIR / "agents"
    frames = {p.stem for p in agents_dir.glob("*.md")}

    missing = [a for a in SHARED_AXES if a not in frames]
    if missing:
        fail(f"full-review runs axes with no frame in the plugin: {', '.join(missing)}")
    else:
        ok(f"all {len(SHARED_AXES)} shared axes have a frame")

    # A frame that names a checklist must name its own. A copy-paste that leaves another
    # agent's filename behind sends the reviewer to the wrong checklist, and the review
    # still runs.
    for frame in sorted(frames):
        text = (agents_dir / f"{frame}.md").read_text(encoding="utf-8")
        referenced = set(re.findall(r"docs/agents/subagents/([\w.-]+)\.md", text))
        if not referenced:
            continue
        if referenced != {frame}:
            fail(
                f"{frame}.md points at checklist(s) {sorted(referenced)} rather than its own"
            )
        else:
            ok(f"{frame} points at its own checklist")

    workflow = ROOT / PLUGIN_DIR / "workflows" / "full-review.js"
    if not workflow.exists():
        fail("full-review.js is missing from the plugin")
        return
    body = workflow.read_text(encoding="utf-8")
    declared = set(re.findall(r"agent: '([\w-]+)'", body))
    if declared != set(SHARED_AXES):
        fail(
            "full-review.js declares "
            f"{sorted(declared)}, which is not the shared axis list"
        )
    else:
        ok("full-review.js declares exactly the shared axes")


def _frames_expecting_a_checklist() -> list[str]:
    """The frames that defer half their definition to the consuming repo.

    Read from the frames themselves: a frame states the path it wants, and
    `check_layer_a_composition` has already proved that path is its own name.
    """
    agents_dir = ROOT / PLUGIN_DIR / "agents"
    return sorted(
        p.stem
        for p in agents_dir.glob("*.md")
        if "docs/agents/subagents/" in p.read_text(encoding="utf-8")
    )


def check_shared_hooks() -> None:
    """Layer A's hooks are the first executable thing it ships, so they get a real suite.

    Run here as well as in both stacks, and for a reason the cross-stack job does not
    cover: that job proves the hooks do not break a *stack's* gates, which is a different
    question from whether the hooks themselves still work. A repo that ships enforcement
    code it only tests through its consumers finds out about a regression from its users.

    `node --test` rather than a framework: this same suite runs from a vendored tree in a
    Python repo, which has no pnpm and no test runner beyond the one built into Node.
    """
    print("shared hooks")
    suite = ROOT / PLUGIN_DIR / "hooks" / "hooks.test.mjs"
    if not suite.exists():
        fail("the shared hooks ship no test suite")
        return

    node = shutil.which("node")
    if node is None:
        # Not a pass. The suite is the only thing standing between a narrowed matcher and
        # a guard that goes quiet, and "we could not run it" must not read as "it passed".
        fail("node is not on PATH -- the shared hook suite could not run")
        return

    proc = subprocess.run(  # noqa: S603
        [node, "--test", str(suite)],
        cwd=ROOT / PLUGIN_DIR / "hooks",
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-25:])
        fail(f"the shared hook suite fails:\n{tail}")
        return
    passed = next(
        (line.split()[-1] for line in proc.stdout.splitlines() if line.startswith("# pass ")),
        "?",
    )
    ok(f"{passed} shared hook test(s) pass")


def check_stack_configs() -> None:
    """`harness.config.json` is the contract; a stack that breaks it breaks layer A.

    Only the meta-repo can run this: the schema lives here and the configs live in the
    submodules, and nothing inside either stack can see both. A stack that has not adopted
    the config yet is reported as such rather than passed over in silence -- the whole
    point of the file is that the shared half stops working without it.
    """
    print("stack configs")
    for name in ("python-harness", "frontend-harness"):
        stack = ROOT / name
        if not stack.exists():
            print(f"  skip {name} is not checked out -- run `git submodule update --init`")
            continue
        config_path = stack / "harness.config.json"
        if not config_path.exists():
            print(f"  skip {name} has no harness.config.json yet")
            continue
        try:
            config = json.loads(config_path.read_text())
        except json.JSONDecodeError as exc:
            fail(f"{name}/harness.config.json does not parse: {exc}")
            continue

        for key in ("name", "gates"):
            if key not in config:
                fail(f"{name}: harness.config.json has no {key!r}")
        gates = config.get("gates") or []
        if not gates:
            fail(f"{name}: declares no gates -- /lint, /test and /verify have nothing to run")
        for gate in gates:
            kind = gate.get("kind")
            if kind not in GATE_KINDS:
                fail(f"{name}: gate {gate.get('name')!r} has kind {kind!r}")
            if not isinstance(gate.get("run"), list) or not gate.get("run"):
                fail(f"{name}: gate {gate.get('name')!r} has no argv in `run`")
        if not any(g.get("kind") in {"lint", "format", "types"} for g in gates):
            fail(f"{name}: no lint, format or types gate -- /lint would run nothing")
        if not any(g.get("kind") == "test" for g in gates):
            fail(f"{name}: no test gate -- /test would run nothing")

        review = config.get("review", {})
        checklist_dir = stack / review.get("checklistDir", "docs/agents/subagents")
        # Which agents need a checklist is a property of the frames, not a list kept here.
        # A frame that carries its whole review needs none; one that defers to the stack
        # cannot work without it. Restating the set would put the two out of step the first
        # time a frame changed its mind.
        expected = _frames_expecting_a_checklist()
        absent = [a for a in expected if not (checklist_dir / f"{a}.md").exists()]
        if absent:
            fail(
                f"{name}: no checklist for {', '.join(absent)} under "
                f"{checklist_dir.relative_to(stack)} -- those axes review on the frame alone"
            )
        else:
            ok(f"{name}: all {len(expected)} frames that need a checklist have one")

        ninth = review.get("ninthAxis")
        if ninth:
            agent_dir = stack / review.get("agentDir", ".agents/agents")
            if not (agent_dir / f"{ninth['agent']}.md").exists():
                fail(
                    f"{name}: ninth axis {ninth['agent']!r} has no definition under "
                    f"{agent_dir.relative_to(stack)}"
                )
            else:
                ok(f"{name}: ninth axis {ninth['label']} resolves")
        # The hooks read their whole pathspec from here. A stack that adopts the shared
        # Stop gate and declares no gated paths gets a gate that never fires -- green, and
        # measuring nothing. That is the failure mode this whole repository exists to make
        # loud, so it is checked rather than left to the stack.
        hooks = config.get("hooks")
        if hooks is None:
            print(f"  skip {name} declares no hooks block yet")
        else:
            for key in ("gatedPaths", "gatedExtensions"):
                if not hooks.get(key):
                    fail(f"{name}: hooks.{key} is empty -- the Stop gate would never fire")
            for entry in hooks.get("protected", []):
                if not entry.get("glob") or not entry.get("why"):
                    fail(f"{name}: a protected entry has no glob or no reason: {entry}")
                if entry.get("scope") not in (None, "write", "secret"):
                    fail(f"{name}: protected {entry['glob']!r} has scope {entry.get('scope')!r}")
            for entry in hooks.get("formatters", []):
                for argv in entry.get("run", []):
                    if not isinstance(argv, list) or not argv:
                        fail(f"{name}: a formatter for {entry.get('match')} has no argv")
            ok(f"{name}: hooks contract declared")

        if not gates:
            continue
        ok(f"{name}: {len(gates)} gate(s) declared")


# One probe per app, written into a scaffolded repo in place of its real gates. `node`
# rather than a shell one-liner: the marker has to record which app it ran as, and a quoted
# `-e` argument is the one thing that does not survive both a POSIX shell and cmd.exe.
PROBE = """import { appendFileSync } from 'node:fs';
appendFileSync(new URL('../../ran.log', import.meta.url), '%s\\n');
process.exit(%s);
"""


def _template_configs() -> dict[str, dict]:
    """Every `harness.config.json` under `templates/`, keyed by its directory."""
    found = {}
    for path in sorted((ROOT / "templates").rglob("harness.config.json")):
        try:
            found[str(path.parent.relative_to(ROOT / "templates"))] = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            fail(f"templates/{path.parent.name}/harness.config.json does not parse: {exc}")
    return found


def check_templates() -> None:
    """The scaffolds have to satisfy the same contract they hand to a new repository.

    A template is the one place a broken config would not be caught by anything else: no
    hook runs against `templates/`, and the repository it becomes is somebody else's the
    moment it is copied. So the contract is checked here, before it can be inherited.
    """
    print("templates")
    configs = _template_configs()
    if "monorepo" not in configs:
        fail("templates/monorepo has no harness.config.json -- there is nothing to scaffold")
        return

    root = configs["monorepo"]
    apps = root.get("apps") or []
    if not apps:
        fail("the monorepo template's root config names no apps -- the gates would not dispatch")

    # The directory an app lands in, and the template that lands there. `apps/api` comes
    # from `templates/api`, which is the whole of the mapping.
    for app in apps:
        template = app.split("/")[-1]
        config = configs.get(template)
        if config is None:
            fail(f"the root config names {app} but templates/{template} has no config of its own")
            continue

        gates = config.get("gates") or []
        if not gates:
            fail(f"templates/{template}: declares no gates -- /lint and /test would run nothing")
        for gate in gates:
            if gate.get("kind") not in GATE_KINDS:
                fail(f"templates/{template}: gate {gate.get('name')!r} has kind {gate.get('kind')!r}")
            if not isinstance(gate.get("run"), list) or not gate.get("run"):
                fail(f"templates/{template}: gate {gate.get('name')!r} has no argv in `run`")

        hooks = config.get("hooks") or {}
        for entry in hooks.get("protected", []):
            if not entry.get("glob") or not entry.get("why"):
                fail(f"templates/{template}: a protected entry has no glob or no reason: {entry}")

        # The two cross-app declarations that make the dispatch work. Each app names the
        # shared contract and the root config in its own pathspec, and nothing else says so:
        # drop either and a contract change quietly stops running that app's gates, or a
        # change to the file that defines the apps stops running any.
        if "../../packages/contracts" not in (hooks.get("gatedPaths") or []):
            fail(
                f"templates/{template}: does not gate ../../packages/contracts -- a contract "
                f"change would not run this app's gates, and nothing else declares that it should"
            )
        if "../../harness.config.json" not in (hooks.get("gatedFiles") or []):
            fail(
                f"templates/{template}: does not gate ../../harness.config.json -- an edit to "
                f"the config that names the apps would run no gates at all"
            )
    ok(f"the monorepo template dispatches to {len(apps)} app(s)")

    # One placeholder, and only one. A second spelling is how a scaffold ships a repository
    # with `__TEAM__` still in it, which nothing downstream would notice.
    strays = set()
    for path in sorted((ROOT / "templates").rglob("*")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        strays.update(set(re.findall(r"__[A-Z][A-Z0-9_]*__", text)) - {"__PROJECT__"})
    if strays:
        fail(f"templates carry placeholders nothing substitutes: {', '.join(sorted(strays))}")
    else:
        ok("__PROJECT__ is the only placeholder")


def check_scaffold_dispatch() -> None:
    """The note's section 11 experiment, kept rather than run once.

    A monorepo is only cheaper than two repositories if the gates run per app, and that is
    one mechanism with four answers to get right: one app's change runs one app's gates, a
    shared contract runs both, and prose runs none. Every one of them fails silently in the
    direction that looks fine -- a gate that did not run reports nothing at all.

    So it is driven, not asserted. A real scaffold, a real `git status`, the real
    `verify.mjs`, with each app's gates swapped for a probe that records which app it ran
    as. The gate commands are the only thing replaced: the `gatedPaths` under test are the
    ones the template ships.
    """
    print("scaffold dispatch")
    scaffold = ROOT / "scripts" / "new_project.py"
    verify = ROOT / PLUGIN_DIR / "hooks" / "verify.mjs"
    node = shutil.which("node")
    if node is None:
        fail("node is not on PATH -- the dispatch experiment could not run")
        return

    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / "acme-portal"
        built = run([sys.executable, str(scaffold), "create", "acme-portal", "--into", str(project)], cwd=ROOT)
        if built.returncode != 0:
            fail(f"new_project.py could not scaffold: {(built.stderr or built.stdout).strip()}")
            return
        ok("new_project.py scaffolds a monorepo")

        # Swap each app's gates for a probe, leaving its pathspec exactly as shipped.
        for app, code in (("api", 0), ("web", 0)):
            directory = project / "apps" / app
            (directory / "gate.mjs").write_text(PROBE % (app, code), encoding="utf-8")
            config = json.loads((directory / "harness.config.json").read_text())
            config["gates"] = [{"name": f"{app} probe", "kind": "test", "run": ["node", "gate.mjs"]}]
            (directory / "harness.config.json").write_text(json.dumps(config, indent=2) + "\n")

        log = project / "ran.log"

        def turn(*touched: str) -> list[str]:
            """Touch some paths, run the Stop hook, and report which apps gated."""
            log.write_text("", encoding="utf-8")
            for name in touched:
                path = project / name
                # A JSON file has to stay parseable through the touch: the config that
                # names the apps is one of the cases, and a broken one would be read as
                # "no config" rather than as the change it is meant to represent.
                if path.suffix == ".json":
                    data = json.loads(path.read_text(encoding="utf-8"))
                    data["$comment"] = "touched"
                    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
                else:
                    path.write_text(
                        path.read_text(encoding="utf-8") + "\n# touched\n", encoding="utf-8"
                    )
            payload = json.dumps({"cwd": str(project)})
            result = subprocess.run(  # noqa: S603
                [node, str(verify)], input=payload, cwd=project,
                capture_output=True, text=True, check=False,
            )
            for name in touched:
                run(["git", "checkout", "--", name], cwd=project)
            turn.last = result  # type: ignore[attr-defined]
            return [line for line in log.read_text(encoding="utf-8").split("\n") if line]

        cases = {
            "a change in one app runs that app's gates and no others": (
                ("apps/api/src/api/health.py",), ["api"],
            ),
            "and the same holds for the other app": (
                ("apps/web/src/health.ts",), ["web"],
            ),
            "a change to the shared contract runs both": (
                ("packages/contracts/openapi.yaml",), ["api", "web"],
            ),
            "a change to the config that names the apps runs both": (
                ("harness.config.json",), ["api", "web"],
            ),
            "prose ends the turn freely": (
                ("docs/architecture.md",), [],
            ),
        }
        for label, (touched, expected) in cases.items():
            actual = turn(*touched)
            if actual != expected:
                fail(f"{label}: expected {expected or 'no gates'}, ran {actual or 'none'}")
            else:
                ok(label)

        # And a failing gate has to block, naming the app whose gate it was. A dispatch that
        # runs the right gates and swallows their verdict is the same green as no gate.
        (project / "apps" / "web" / "gate.mjs").write_text(PROBE % ("web", 1), encoding="utf-8")
        turn("apps/web/src/health.ts")
        blocked = turn.last  # type: ignore[attr-defined]
        if blocked.returncode != 2:
            fail(f"a failing app gate exited {blocked.returncode}, so the turn would end anyway")
        elif "acme-portal-web" not in blocked.stderr:
            fail(f"the block did not name the app that failed: {blocked.stderr.strip()[:160]}")
        else:
            ok("a failing gate blocks the turn and names its app")


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
        check_vendor_freshness()
        check_generated_tree()
        check_shared_generator()
        check_submodule_guard()
        check_layer_a_composition()
        check_shared_hooks()
        check_stack_configs()
        check_templates()
        check_scaffold_dispatch()
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
