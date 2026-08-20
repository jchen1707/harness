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

`--split` emits two repositories instead, joined by a published, versioned contract. Default
to the monorepo: one branch, one PR, one CI run, and a cross-cutting change that lands
atomically. Reach for `--split` only when an organisational constraint makes that
impossible -- deploy cadences that cannot be gated together, different access boundaries,
separate review authority, or an api consumed by third parties on its own release cycle.

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

import vendor_sync

HARNESS = Path(__file__).resolve().parent.parent
TEMPLATES = HARNESS / "templates"
VENDOR_SYNC = HARNESS / "scripts" / "vendor_sync.py"
VENDOR_DIR = vendor_sync.VENDOR_DIR

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


def place_contract(destination: Path, project: str) -> int:
    """Put the seed contract where this shape keeps it.

    One authoring, three destinations. The document is generated -- it is what
    `emit_contract.py` produces against the api skeleton -- and keeping a copy per template
    directory would be three copies of a generated file, which is the drift this repository
    exists to remove.

    The seed's own README stays in `harness`: it explains the template, which is nothing a
    scaffolded repository needs to carry.
    """
    source = TEMPLATES / "contract" / "openapi.json"
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "openapi.json").write_text(
        source.read_text(encoding="utf-8").replace(PLACEHOLDER, project), encoding="utf-8"
    )
    return 1


def run(args: list[str], cwd: Path) -> None:
    proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)  # noqa: S603
    if proc.returncode != 0:
        raise SystemExit(f"{' '.join(args)} failed in {cwd}:\n{proc.stderr.strip()}")


def initialise(repo: Path, project: str, agnostic: bool, commit: bool, message: str) -> int:
    """`git init`, optionally vendor layer A, optionally commit. Returns the stub count."""
    run(["git", "init", "--quiet", "-b", "main"], cwd=repo)

    stubs = 0
    if agnostic:
        run(
            [sys.executable, str(VENDOR_SYNC), "sync", "--harness", str(HARNESS), "--target", str(repo)],
            cwd=HARNESS,
        )
        # `sync` writes the discovery stubs itself, so there is one implementation of what a
        # stub says and one moment it is written -- here, and in every re-sync afterwards.
        stubs = len(vendor_sync.shared_entries(repo))

    if commit:
        run(["git", "add", "-A"], cwd=repo)
        run(
            ["git", "-c", "user.name=harness", "-c", "user.email=harness@localhost",
             "commit", "--quiet", "-m", message],
            cwd=repo,
        )
    return stubs


def cmd_split(project: str, into: Path, api: str, web: str, agnostic: bool, commit: bool) -> int:
    """Two repositories and the published contract between them.

    The monorepo is the default for a reason -- one branch, one PR, one CI run, and a
    cross-cutting change that lands atomically. This shape exists for the constraints that
    make that impossible: deploy cadences that cannot be gated together, different access
    boundaries, separate review authority, or an api consumed by third parties on its own
    release cycle. Every one of them is organisational, not technical.

    What makes it survivable is the seam, and it is not optional: the api emits its document
    from its handlers and publishes it on a tag; the web repo pins a version and generates
    its types from it. Without that, two repositories guarantee exactly the failure this
    whole arrangement exists to prevent.
    """
    api_repo = into / f"{project}-api"
    web_repo = into / f"{project}-web"
    for repo in (api_repo, web_repo):
        if repo.exists() and any(repo.iterdir()):
            raise SystemExit(f"refusing to scaffold into {repo}: it is not empty")

    written = copy_template(TEMPLATES / APIS[api], api_repo, project)
    written += copy_template(TEMPLATES / "split-api", api_repo, project)
    written += copy_template(TEMPLATES / WEBS[web], web_repo, project)
    written += copy_template(TEMPLATES / "split-web", web_repo, project)
    # Both repositories start from the same document. The web repo has to build before the
    # api has published anything, and a client seeded from a different schema than the one
    # the api emits would be broken from its first commit in a way nothing checks.
    written += place_contract(api_repo / "contracts", project)
    written += place_contract(web_repo / "contracts", project)

    delivery = TEMPLATES / ("agnostic" if agnostic else "plugin")
    for repo in (api_repo, web_repo):
        written += copy_template(delivery, repo, project)

    stubs = 0
    for repo in (api_repo, web_repo):
        stubs += initialise(
            repo, project, agnostic, commit,
            f"chore: scaffold {repo.name} from the harness templates",
        )

    print(f"scaffolded {project} into two repositories ({written} file(s))")
    print(f"  {api_repo.name}  publishes contracts/openapi.json on a v* tag")
    print(f"  {web_repo.name}  pins a version in contract.json and generates from it")
    if agnostic:
        print(f"  layer A vendored into each, with {stubs} discovery stub(s) in total")
    else:
        print("  layer A arrives as the plugin, enabled in each .claude/settings.json")
    print()
    print("Next:")
    print(f"  cd {api_repo.name} && uv sync          # then `uv run pytest`")
    print(f"  cd {web_repo.name} && pnpm install && pnpm test")
    print()
    print("  The seam needs two things you have to do by hand, in this order:")
    print(f"    1. push {api_repo.name}, tag it v0.1.0 -- that publishes the contract")
    print(f"    2. set `repo` in {web_repo.name}/contract.json, then `pnpm contract:update`")
    print("  Until step 2, the web repo builds against the contract seeded at scaffold time.")
    return 0


def cmd_create(project: str, into: Path, api: str, web: str, agnostic: bool, commit: bool) -> int:
    if into.exists() and any(into.iterdir()):
        raise SystemExit(f"refusing to scaffold into {into}: it is not empty")

    written = copy_template(TEMPLATES / "monorepo", into, project)
    written += copy_template(TEMPLATES / APIS[api], into / "apps" / "api", project)
    written += copy_template(TEMPLATES / WEBS[web], into / "apps" / "web", project)
    written += place_contract(into / "packages" / "contracts", project)

    # Exactly one delivery adapter, never both. The plugin path adds one line of settings
    # and nothing to the tree; the vendored path adds real files and a job that shouts when
    # they fall behind. See docs/agents/config.md and section 06 of the plan.
    written += copy_template(TEMPLATES / ("agnostic" if agnostic else "plugin"), into, project)

    stubs = initialise(
        into, project, agnostic, commit,
        f"chore: scaffold {project} from the harness templates",
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
        help="two repositories plus a published contract, instead of one tree",
    )

    args = parser.parse_args()
    if not NAME.match(args.project):
        raise SystemExit(
            f"{args.project!r} is not a usable project name. Lowercase letters, digits and "
            f"single hyphens: it becomes a Python distribution name and an npm package name."
        )

    if args.split:
        # Two repositories side by side, so `--into` names their parent rather than a repo.
        into = (args.into or Path.cwd()).resolve()
        into.mkdir(parents=True, exist_ok=True)
        return cmd_split(
            args.project, into, args.api, args.web, args.agnostic, not args.no_commit
        )

    into = (args.into or Path.cwd() / args.project).resolve()
    return cmd_create(args.project, into, args.api, args.web, args.agnostic, not args.no_commit)


if __name__ == "__main__":
    sys.exit(main())
