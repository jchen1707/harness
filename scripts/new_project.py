#!/usr/bin/env python3
"""Scaffold a new product repository from `templates/`.

Layer A is shared and generated. Layer B belongs to a stack. This writes **layer C** -- a
product repository, which is copied once and then owned by whoever it was copied for -- and
wires layer A into it by one of the two delivery adapters.

    new_project.py create acme-portal --api python --web react [--agnostic]

The result is a monorepo: `apps/api`, `apps/web`, a contract between them, and one
`harness.config.json` per app so the gates dispatch by changed path rather than running
everything on every turn. That dispatch is the only mechanism the monorepo option depends
on, which is why it is the part with a test rather than a paragraph.

**Why this is not vendored into the stacks.** `templates/` and this script live in `harness`
and reach a new project from a checkout of it, never through the plugin or the vendored
tree. A stack never scaffolds a product from inside itself, so vendoring these would put a
React skeleton in a Python repository and report both stacks' pins as stale on every edit to
it. `--agnostic` needs a checkout anyway: it runs `vendor_sync.py`, which is the tool that
does the vendoring and so cannot be vendored either.

Stdlib only, like everything else in `scripts/`: no setup step, and it runs from a fresh
clone with the python3 that is already there.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

HARNESS = Path(__file__).resolve().parent.parent
TEMPLATES = HARNESS / "templates"
VENDOR_SYNC = HARNESS / "scripts" / "vendor_sync.py"
VENDOR_DIR = Path(".agents/vendor/harness")

# The one token the templates carry. It only ever appears inside a string literal, a title
# or prose -- never in an identifier or a path -- which is what keeps every template file
# real source that this repository can lint and typecheck before it is ever copied.
PLACEHOLDER = "__PROJECT__"

# A PEP 508 distribution name and an npm package name at once, because the scaffold uses it
# as both. Rejecting early beats a `uv sync` that fails three steps later.
NAME = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")

# What each `--api` / `--web` choice maps to. One entry each today; the point of the table
# is that adding a second is a template plus a line, not a new code path.
APIS = {"python": "api"}
WEBS = {"react": "web"}

# Suffixes to substitute in. Anything else is copied byte for byte -- a placeholder has no
# business inside a binary, and guessing wrong there corrupts the file silently.
TEXT_SUFFIXES = frozenset(
    {
        ".md",
        ".py",
        ".json",
        ".toml",
        ".yml",
        ".yaml",
        ".ts",
        ".tsx",
        ".js",
        ".mjs",
        ".css",
        ".html",
        ".txt",
        ".example",
        ".gitignore",
    }
)


def is_text(path: Path) -> bool:
    return path.suffix in TEXT_SUFFIXES or path.name in {".gitignore", ".env.example"}


def copy_template(source: Path, destination: Path, project: str) -> int:
    """Copy one template tree, substituting the project name as it goes."""
    if not source.is_dir():
        raise SystemExit(f"no template at {source.relative_to(HARNESS)}")

    written = 0
    for origin in sorted(source.rglob("*")):
        if not origin.is_file():
            continue
        target = destination / origin.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        if is_text(origin):
            target.write_text(
                origin.read_text(encoding="utf-8").replace(PLACEHOLDER, project),
                encoding="utf-8",
            )
            shutil.copystat(origin, target)
        else:
            shutil.copy2(origin, target)
        written += 1
    return written


def front_matter(text: str) -> dict[str, str]:
    """The `key: value` pairs of a leading `---` block. Flat by construction; these are."""
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end == -1:
        return {}
    fields: dict[str, str] = {}
    for line in text[4:end].split("\n"):
        key, separator, value = line.partition(":")
        if separator:
            fields[key.strip()] = value.strip()
    return fields


STUB_BODY = """Read `{target}` in full and follow it.

This file exists so a harness that discovers skills under `.agents/skills/` finds the shared
one. The body is layer A: generated, pinned by sha, and the same in every repository that
vendors it. Editing it here is the drift the vendored copy's freshness check exists to
catch -- edit it in [`harness`](https://github.com/jchen1707/harness) and re-sync.
"""


def write_stubs(target: Path) -> int:
    """Write one discovery stub per vendored command and skill.

    A harness that is not Claude Code finds skills under `.agents/skills/`, not inside a
    vendored tree it has never been told about. Both stacks keep these stubs by hand, which
    is one hand-maintained file per shared command in every consuming repository and the
    reason a new command silently fails to appear. A scaffolded repository generates them
    instead, and regenerates them after every sync:

        new_project.py stubs --target .
    """
    vendor = target / VENDOR_DIR
    if not vendor.is_dir():
        raise SystemExit(f"no vendored layer A at {VENDOR_DIR} -- run vendor_sync.py sync first")

    sources: list[tuple[str, Path, str]] = []
    for command in sorted((vendor / "commands").glob("*.md")):
        sources.append((command.stem, command, f"{VENDOR_DIR}/commands/{command.name}"))
    for skill in sorted((vendor / "skills").glob("*/SKILL.md")):
        sources.append((skill.parent.name, skill, f"{VENDOR_DIR}/skills/{skill.parent.name}/SKILL.md"))

    for name, source, pointer in sources:
        fields = front_matter(source.read_text(encoding="utf-8"))
        stub = target / ".agents" / "skills" / name / "SKILL.md"
        stub.parent.mkdir(parents=True, exist_ok=True)
        stub.write_text(
            "---\n"
            f"name: {name}\n"
            f"description: {fields.get('description', name)}\n"
            "---\n\n" + STUB_BODY.format(target=pointer),
            encoding="utf-8",
        )
    return len(sources)


def run(args: list[str], cwd: Path) -> None:
    proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)  # noqa: S603
    if proc.returncode != 0:
        raise SystemExit(f"{' '.join(args)} failed in {cwd}:\n{proc.stderr.strip()}")


def cmd_create(project: str, into: Path, api: str, web: str, agnostic: bool, commit: bool) -> int:
    if not NAME.match(project):
        raise SystemExit(
            f"{project!r} is not a usable project name. Lowercase letters, digits and single "
            f"hyphens: it becomes a Python distribution name and an npm package name."
        )
    if into.exists() and any(into.iterdir()):
        raise SystemExit(f"refusing to scaffold into {into}: it is not empty")

    written = copy_template(TEMPLATES / "monorepo", into, project)
    written += copy_template(TEMPLATES / APIS[api], into / "apps" / "api", project)
    written += copy_template(TEMPLATES / WEBS[web], into / "apps" / "web", project)

    # Exactly one delivery adapter, never both. The plugin path adds one line of settings
    # and nothing to the tree; the vendored path adds real files and a job that shouts when
    # they fall behind. See docs/agents/config.md and section 06 of the plan.
    written += copy_template(TEMPLATES / ("agnostic" if agnostic else "plugin"), into, project)

    run(["git", "init", "--quiet", "-b", "main"], cwd=into)

    stubs = 0
    if agnostic:
        run(
            [sys.executable, str(VENDOR_SYNC), "sync", "--harness", str(HARNESS), "--target", str(into)],
            cwd=HARNESS,
        )
        stubs = write_stubs(into)

    if commit:
        run(["git", "add", "-A"], cwd=into)
        run(
            [
                "git",
                "-c",
                "user.name=harness",
                "-c",
                "user.email=harness@localhost",
                "commit",
                "--quiet",
                "-m",
                f"chore: scaffold {project} from the harness templates",
            ],
            cwd=into,
        )

    print(f"scaffolded {project} into {into} ({written} file(s))")
    if agnostic:
        print(f"  layer A vendored into {VENDOR_DIR}, with {stubs} discovery stub(s)")
    else:
        print("  layer A arrives as the plugin, enabled in .claude/settings.json")
    print()
    print("Next:")
    print("  cd apps/api && uv sync          # then `uv run pytest`")
    print("  cd apps/web && pnpm install     # then `pnpm test`")
    if not agnostic:
        print()
        print("  A clone does not register a marketplace. Once per machine:")
        print("    /plugin marketplace add jchen1707/harness")
        print("  Without it, `harness@harness` in .claude/settings.json resolves to nothing")
        print("  and every shared command, agent and hook is silently absent.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    create = sub.add_parser("create", help="scaffold a new product repository")
    create.add_argument("project", help="the project name, in kebab-case")
    create.add_argument("--api", choices=sorted(APIS), default="python")
    create.add_argument("--web", choices=sorted(WEBS), default="react")
    create.add_argument(
        "--agnostic",
        action="store_true",
        help="vendor layer A and write the Codex adapter instead of enabling the plugin",
    )
    create.add_argument("--into", type=Path, default=None, help="defaults to ./<project>")
    create.add_argument(
        "--no-commit", action="store_true", help="leave the scaffolded tree uncommitted"
    )
    create.add_argument(
        "--split",
        action="store_true",
        help="not implemented -- see section 07 of the plan",
    )

    stubs = sub.add_parser("stubs", help="regenerate the discovery stubs after a vendor sync")
    stubs.add_argument("--target", type=Path, default=Path("."))

    args = parser.parse_args()
    if args.cmd == "stubs":
        written = write_stubs(args.target.resolve())
        print(f"wrote {written} discovery stub(s) under .agents/skills/")
        return 0

    if args.split:
        raise SystemExit(
            "--split is not implemented. Two repositories are only survivable with a "
            "published, versioned contract -- the api emitting its schema on release and the "
            "web repo pinning a version and generating from it -- and that seam is worth "
            "building against a real project's constraints rather than guessing at them. "
            "Scaffold the monorepo; section 07 of the plan carries the split shape and the "
            "four organisational reasons that justify it."
        )

    into = (args.into or Path.cwd() / args.project).resolve()
    return cmd_create(args.project, into, args.api, args.web, args.agnostic, not args.no_commit)


if __name__ == "__main__":
    sys.exit(main())
