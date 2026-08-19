#!/usr/bin/env python
"""Generate the `main` tree from the `v2` tree.

`v2` is the source. `main` is a build artifact, and this is the build.

The two branches used to be hand-maintained in parallel, which cost four authorings of
every idea — twice per repository, once per branch — and produced the drift this script
exists to end. The transformation only ever runs one way, because only one direction is
mechanical: Claude-specific assumptions can be *added* to neutral text, never removed
from it.

The manifest (`transform.json`, beside this file) says what the repository needs. Nothing
here is repository-specific.

**Every rule fails loudly.** A substitution whose source text is absent, a path that does
not exist, a symlink that no longer points where the manifest says — each stops the build
rather than silently producing a `main` that is quietly missing something. That is the
whole safety argument for generating a branch: a generator that skips what it cannot find
is worse than the hand-maintenance it replaced, because nobody reads a tree that builds.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# The index mode git records for a submodule. `ls-files -s` reports it in place of a
# blob mode, and it is the marker for "this entry is a commit, not content".
GITLINK_MODE = "160000"

TEXT_SUFFIXES = frozenset(
    {
        ".md",
        ".py",
        ".json",
        ".toml",
        ".yml",
        ".yaml",
        ".sh",
        ".js",
        ".mjs",
        ".ts",
        ".tsx",
        ".mts",
        ".cts",
        ".css",
        ".html",
        ".cfg",
        ".txt",
        ".example",
        ".gitignore",
        ".gitattributes",
    }
)


class TransformError(RuntimeError):
    """A rule did not apply. The build stops rather than emit a partial tree."""


def is_text(path: Path) -> bool:
    """True when the file should have the text rules applied to it."""
    if path.suffix in TEXT_SUFFIXES or path.name in {
        ".gitignore",
        ".gitattributes",
        ".env.example",
    }:
        return True
    try:
        path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return False
    return True


def copy_tracked(source: Path, destination: Path) -> bool:
    """Copy exactly the files git tracks. True when the source is a git checkout.

    The tracked set is the right definition of "the branch": it is what a fresh clone
    would contain, so a local build matches the one CI publishes. Copying the working
    tree instead would sweep in whatever happens to be lying around unstaged — build
    output, caches, and `.env`, which is precisely the file that must never reach a
    branch this job force-pushes.

    Returns False for a source that is not a checkout, so fixtures still build.

    Submodules are listed by `ls-files` too, and they are not files: a gitlink entry
    names a commit in another repository, so there is nothing here to copy and
    `shutil.copy2` on the directory it stands for raises. They are skipped, and the
    parent's publish step is what restores the links in the generated branch's index.
    """
    if not (source / ".git").exists():
        return False
    # `git` resolves from PATH, and every argument is either a literal or the path this
    # script was handed, so there is no untrusted input to inject. An absolute executable
    # path would not survive the Windows leg of the frontend harness's CI.
    #
    # `-s` prefixes each entry with its mode, which is the only way to tell a gitlink
    # from a file before touching the filesystem.
    listing = subprocess.run(  # noqa: S603
        ["git", "-C", str(source), "ls-files", "-sz"],  # noqa: S607
        capture_output=True,
        check=True,
    )
    destination.mkdir(parents=True)
    for entry in listing.stdout.decode("utf-8").split("\0"):
        if not entry:
            continue
        metadata, _, name = entry.partition("\t")
        if metadata.startswith(f"{GITLINK_MODE} "):
            continue
        origin = source / name
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        # `follow_symlinks=False` recreates an adapter symlink as a symlink, which is
        # what `materialise_symlinks` then has to find.
        shutil.copy2(origin, target, follow_symlinks=False)
    return True


def copy_tree(source: Path, destination: Path) -> None:
    """Copy the working tree, minus the things no branch should carry."""
    if copy_tracked(source, destination):
        return
    ignore = shutil.ignore_patterns(
        ".git",
        "__pycache__",
        "*.pyc",
        ".venv",
        "node_modules",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "dist",
        "coverage",
        ".DS_Store",
    )
    shutil.copytree(source, destination, symlinks=True, ignore=ignore)


def materialise_symlinks(root: Path, expected: dict[str, str]) -> None:
    """Replace each adapter symlink with a real copy of what it points at.

    On `v2` the Claude adapter is a symlink into the canonical `.agents/` tree. `main` has
    no `.agents/`, so the link has to become the thing it linked to.
    """
    for link_path, target in expected.items():
        link = root / link_path
        if not link.is_symlink():
            raise TransformError(
                f"{link_path} is not a symlink — either the manifest is stale, or this "
                f"checkout has `core.symlinks=false` and git wrote the link as a text file"
            )
        # `os.readlink` hands back the separator the platform stores, and git writes these
        # links with backslashes on Windows. The manifest is one file read on both, so the
        # comparison is made in the one form a manifest can be written in.
        actual = os.readlink(link).replace("\\", "/")
        if actual != target:
            raise TransformError(f"{link_path} points at {actual!r}, manifest says {target!r}")
        resolved = (link.parent / target).resolve()
        if not resolved.exists():
            raise TransformError(f"{link_path} points at {target!r}, which does not exist")
        link.unlink()
        if resolved.is_dir():
            shutil.copytree(resolved, link, symlinks=False)
        else:
            shutil.copy2(resolved, link)


def materialise_pointers(root: Path, expected: dict[str, str]) -> None:
    """Replace each adapter *pointer file* with the canonical file it points at.

    The frontend harness cannot use symlinks for its adapters: its CI runs on Windows as
    well as Linux, and a checkout with `core.symlinks=false` turns every link into a text
    file containing a path. So the adapter is an ordinary file that carries the Claude
    frontmatter and a one-line body telling the agent to read the canonical file. On
    `main` there is no canonical file to read, so the pointer has to become its target.

    The canonical file repeats the adapter's frontmatter verbatim, which is what makes
    this a whole-file copy rather than a splice.
    """
    for pointer_path, target in expected.items():
        pointer = root / pointer_path
        if pointer.is_symlink() or not pointer.is_file():
            raise TransformError(
                f"{pointer_path} is not a regular file — the manifest expects a pointer stub"
            )
        # A stub that no longer names its target is a stub somebody filled in by hand.
        # Overwriting it would silently discard their edit, so stop instead.
        if target not in pointer.read_text(encoding="utf-8"):
            raise TransformError(
                f"{pointer_path} does not reference {target!r} — either it was edited by "
                f"hand, or the manifest is stale"
            )
        resolved = (pointer.parent / target).resolve()
        if not resolved.is_file():
            raise TransformError(f"{pointer_path} points at {target!r}, which does not exist")
        shutil.copy2(resolved, pointer)


# Harness-specific regions are marked in the source, in whatever comment syntax the file
# uses. Two kinds, and they are not symmetrical:
#
#   `agnostic` — live on `v2`, removed from `main`. The markers are comments; the body is
#   ordinary content.
#
#       <!-- harness:agnostic -->      # harness:agnostic
#       …neutral prose…                GATED = (".codex/config.toml",)
#       <!-- /harness:agnostic -->     # /harness:agnostic
#
#   `claude` — inert on `v2`, live on `main`. The body is *commented out*, and building
#   `main` uncomments it. A Claude-specific paragraph that rendered on the neutral branch
#   would contradict the paragraph beside it, and a Claude-specific assignment that ran
#   there would silently win over the neutral one — so the source must not carry it live.
#
#       <!-- harness:claude              # harness:claude
#       …Claude-specific prose…          # pattern = re.compile(CLAUDE_ONLY)
#       /harness:claude -->              # /harness:claude
#
# How much vertical space a removed region may leave behind, which is a property of the
# language's formatter rather than of any repository. `ruff format` wants two blank lines
# between top-level definitions; Prettier allows one, anywhere, and rewrites the rest.
BLANK_RUN = re.compile(r"\n{3,}")
BLANK_RUN_PYTHON = re.compile(r"\n{4,}")
AGNOSTIC = re.compile(
    r"[ \t]*(?://|#|<!--)[ \t]*harness:agnostic[ \t]*(?:-->)?[ \t]*\n"
    r".*?"
    r"[ \t]*(?://|#|<!--)[ \t]*/harness:agnostic[ \t]*(?:-->)?[ \t]*\n",
    re.DOTALL,
)
CLAUDE = re.compile(
    r"[ \t]*(?P<open>//|#|<!--)[ \t]*harness:claude[ \t]*\n"
    r"(?P<body>.*?)"
    r"[ \t]*(?://|#)?[ \t]*/harness:claude[ \t]*(?:-->)?[ \t]*\n",
    re.DOTALL,
)


def uncomment(body: str, opener: str) -> str:
    """Strip one level of comment from a `claude` region body.

    An HTML region is one comment from `<!--` to `-->`, so its body is already plain text.
    A `#` or `//` region comments each line, and each line gives one back.
    """
    if opener == "<!--":
        return body
    prefix = f"{opener} "
    lines = []
    for line in body.split("\n"):
        stripped = line.lstrip()
        if not stripped:
            lines.append(line)
        elif stripped.startswith(prefix):
            indent = line[: len(line) - len(stripped)]
            lines.append(indent + stripped[len(prefix) :])
        elif stripped == opener:
            lines.append("")
        else:
            raise TransformError(f"claude region line is not commented out: {line!r}")
    return "\n".join(lines)


def resolve_regions(root: Path) -> None:
    """Drop the `agnostic` regions and bring the `claude` ones to life.

    Marking the source is what keeps this script generic. The alternative — anchoring every
    harness-specific paragraph as a find-and-replace in the manifest — puts the knowledge of
    which prose is Claude-specific in a file nobody opens while writing the prose, and it
    goes stale the first time a sentence is reworded.
    """
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink() or not is_text(path):
            continue
        text = path.read_text(encoding="utf-8")
        if "harness:" not in text:
            continue
        updated = AGNOSTIC.sub("", text)
        updated = CLAUDE.sub(lambda m: uncomment(m.group("body"), m.group("open")), updated)
        if "harness:agnostic" in updated or "harness:claude" in updated:
            raise TransformError(f"{path}: a harness region is unclosed or malformed")
        if updated == text:
            continue
        # Removing a region leaves the blank lines that surrounded it stacked against
        # each other, and the repository's formatter rejects the result. Collapse the run
        # to what that file's formatter permits, and drop a trailing one entirely.
        # Applied only to files that actually held a region.
        if path.suffix == ".py":
            updated = BLANK_RUN_PYTHON.sub("\n\n\n", updated)
        else:
            updated = BLANK_RUN.sub("\n\n", updated)
        updated = updated.rstrip("\n") + "\n"
        path.write_text(updated, encoding="utf-8")


def apply_blocks(root: Path, blocks: list[dict[str, str]]) -> None:
    """Replace neutral prose with the Claude-specific prose it stands in for.

    Anchored on the exact source text: when `v2` rewrites a paragraph, the rule stops
    matching and the build fails, which is the point at which a human decides what the
    Claude-specific wording should now say.
    """
    for index, block in enumerate(blocks):
        path = root / block["file"]
        if not path.exists():
            raise TransformError(f"block {index}: {block['file']} does not exist")
        text = path.read_text(encoding="utf-8")
        found = text.count(block["from"])
        if found != 1:
            raise TransformError(
                f"block {index} in {block['file']}: source text found {found} times, expected once"
            )
        path.write_text(text.replace(block["from"], block["to"]), encoding="utf-8")


def apply_substitutions(root: Path, rules: list[dict[str, str]]) -> None:
    """Apply the whole-tree text rules, in the order the manifest lists them."""
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink() or not is_text(path):
            continue
        original = path.read_text(encoding="utf-8")
        text = original
        for rule in rules:
            if "regex" in rule:
                text = re.sub(rule["regex"], rule["to"], text)
            else:
                text = text.replace(rule["from"], rule["to"])
        if text != original:
            path.write_text(text, encoding="utf-8")


def rename_instruction_files(root: Path, source_name: str, target_name: str) -> None:
    """`AGENTS.md` becomes `CLAUDE.md`, replacing the pointer stub that stood there."""
    for path in sorted(root.rglob(source_name)):
        target = path.with_name(target_name)
        if target.exists():
            target.unlink()
        path.rename(target)


def drop(root: Path, paths: list[str]) -> None:
    """Remove what only the agent-agnostic branch carries."""
    for relative in paths:
        path = root / relative
        if not path.exists() and not path.is_symlink():
            raise TransformError(f"drop: {relative} does not exist — the manifest is stale")
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()


def generate(source: Path, destination: Path, manifest: dict) -> None:
    """Build the `main` tree from the `v2` tree at `source`."""
    if destination.exists():
        shutil.rmtree(destination)
    copy_tree(source, destination)
    materialise_symlinks(destination, manifest.get("symlinks", {}))
    materialise_pointers(destination, manifest.get("pointers", {}))
    drop(destination, manifest.get("drop", []))
    resolve_regions(destination)
    apply_blocks(destination, manifest.get("blocks", []))
    apply_substitutions(destination, manifest.get("substitutions", []))
    rename_instruction_files(
        destination,
        manifest.get("instructions", {}).get("from", "AGENTS.md"),
        manifest.get("instructions", {}).get("to", "CLAUDE.md"),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="a checkout of the v2 branch")
    parser.add_argument("destination", type=Path, help="where to write the generated main tree")
    parser.add_argument("--manifest", type=Path, default=None)
    arguments = parser.parse_args(argv)

    manifest_path = arguments.manifest or Path(__file__).with_name("transform.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    try:
        generate(arguments.source, arguments.destination, manifest)
    except TransformError as error:
        print(f"transform failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
