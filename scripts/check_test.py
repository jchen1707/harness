#!/usr/bin/env python3
"""The gates' own tests. Run by `check.py`, and runnable on its own.

`scripts/` is 2,200 lines of Python that gates this whole repository, and until this file
existed none of it had a test. The one that matters most says so in its own docstring:
`vendor_sync.py check` "is the only thing standing between a consuming repo and a silently
stale copy of layer A, so a change that makes it pass when it should fail has to fail here."
The only way to know that still held was to run `check.py` and read the output.

The round-trip cases used to live inside `check_vendor_round_trip()` as a sequence of
`run(...)`-then-`fail(...)` blocks. They were already tests -- each one tampers with a
fixture and asserts the guard notices -- but they were written as a check, so nothing could
call one of them, nothing could name one that broke, and the expensive fixture was rebuilt
inline. They are tests here, `check.py` runs this module the same way it runs
`node --test hooks.test.mjs`, and a failure now names the case rather than the file.

Stdlib `unittest`, for the same reason everything else here is stdlib: there is no install
step in this repository and adding one to run its own gates would be a bad trade.

    python3 scripts/check_test.py          # directly
    python3 scripts/check.py               # as a gate, with everything else
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR_SYNC = ROOT / "scripts" / "vendor_sync.py"
PLUGIN_DIR = "plugins/harness"


def run(args: list[str], cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        args, cwd=cwd, capture_output=True, text=True, check=False
    )


def sync(source: Path, target: Path) -> subprocess.CompletedProcess[str]:
    """`vendor_sync.py sync`, the command a consuming repo runs to take layer A."""
    return run(
        [sys.executable, str(VENDOR_SYNC), "sync", "--harness", str(source), "--target", str(target)]
    )


def freshness(target: Path) -> subprocess.CompletedProcess[str]:
    """`vendor_sync.py check`, the guard that runs in each consumer's CI."""
    return run([sys.executable, str(VENDOR_SYNC), "check", "--target", str(target)])


class VendorRoundTrip(unittest.TestCase):
    """A consumer takes layer A, and the freshness check notices every way it can rot.

    The fixture is built once for the class: a clone of this repository at HEAD, and a
    consuming repo with layer A synced into it. **A clone, not this working tree** -- a
    consumer only ever receives committed content, so that is what the round-trip should
    exercise, and `sync` refuses a dirty checkout, which would otherwise make these tests
    unrunnable for the one person most likely to want them: somebody midway through editing
    layer A.

    Each test that tampers with the tree undoes its tampering, so the order they run in
    cannot matter.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls._tmp.name)
        cls.source = tmp / "harness"
        cls.target = tmp / "consumer"
        cls.target.mkdir()

        cloned = run(["git", "clone", "--quiet", "--no-hardlinks", str(ROOT), str(cls.source)])
        if cloned.returncode != 0:
            raise unittest.SkipTest(f"could not clone the harness: {cloned.stderr.strip()}")

        synced = sync(cls.source, cls.target)
        if synced.returncode != 0:
            raise AssertionError(f"sync failed: {synced.stderr.strip() or synced.stdout.strip()}")

        cls.vendored = cls.target / ".agents" / "vendor" / "harness"
        manifest = cls.vendored / "MANIFEST.json"
        if not manifest.exists():
            raise AssertionError("sync wrote no MANIFEST.json")
        cls.files = list(json.loads(manifest.read_text())["files"])

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_manifest_pins_the_vendored_files(self) -> None:
        self.assertTrue(self.files, "MANIFEST.json records no files -- layer A vendors as empty")

    def test_check_passes_on_a_freshly_synced_tree(self) -> None:
        result = freshness(self.target)
        self.assertEqual(result.returncode, 0, f"check rejects a fresh sync: {result.stdout}")

    def test_check_catches_a_hand_edited_vendored_file(self) -> None:
        """The gate that earns its keep. Everything else here guards this one."""
        edited = self.vendored / self.files[0]
        original = edited.read_text()
        edited.write_text(original + "\nlocal edit\n")
        try:
            self.assertNotEqual(
                freshness(self.target).returncode,
                0,
                "check passes on a hand-edited vendored file -- drift would go unnoticed",
            )
        finally:
            edited.write_text(original)

    def test_check_catches_an_unrecognised_vendored_file(self) -> None:
        """A file layer A does not ship must not survive a sync."""
        stray = self.vendored / "stray.md"
        stray.write_text("not part of layer A\n")
        try:
            self.assertNotEqual(
                freshness(self.target).returncode,
                0,
                "check passes with an unrecognised file in the vendored tree",
            )
        finally:
            stray.unlink()

    def test_sync_refuses_a_dirty_harness_checkout(self) -> None:
        """A sync from a dirty checkout would pin a sha whose content exists nowhere.

        Dirty the *clone*, never this checkout: a gate that edits the repository it is
        gating has a failure mode of its own.
        """
        scratch = self.source / PLUGIN_DIR / "docs" / "agents" / ".check-dirty.md"
        scratch.write_text("uncommitted\n")
        try:
            result = sync(self.source, self.target)
        finally:
            scratch.unlink()
        self.assertNotEqual(
            result.returncode,
            0,
            "sync accepts a dirty harness checkout -- the pin would name content not in it",
        )
        self.assertIn(
            "uncommitted",
            result.stderr + result.stdout,
            "sync refused a dirty checkout but did not say why",
        )


class CrossStackVerdict(unittest.TestCase):
    """`cross_stack.py` reads the report's verdict; it does not form one of its own.

    The judgment it *does* make is how a verdict maps onto this job's outcome, and the
    distinction that matters is `incomplete` versus `fail`: a gate that could not start does
    not mean layer A broke the stack, it means the job did not find out. Collapsing the two
    would recreate in Python exactly the distinction the reporter was built to draw.
    """

    @classmethod
    def setUpClass(cls) -> None:
        sys.path.insert(0, str(ROOT / "scripts"))
        import cross_stack

        cls.cross_stack = cross_stack

    @staticmethod
    def report(verdict: str, gates: list[dict], missing: list[str] | None = None) -> dict:
        return {"verdict": verdict, "gates": gates, "missingApps": missing or [], "targets": []}

    def test_a_failing_gate_is_a_failure_that_names_the_gate(self) -> None:
        report = self.report("fail", [{"name": "ruff check", "status": "fail"}])
        problems = self.cross_stack._judge("python-harness", report, ran=1)
        self.assertEqual(len(problems), 1)
        self.assertIn("ruff check", problems[0])
        self.assertIn("fail against this layer A", problems[0])

    def test_an_unavailable_gate_is_not_reported_as_a_broken_stack(self) -> None:
        report = self.report(
            "incomplete",
            [{"name": "playwright", "status": "unavailable"}, {"name": "eslint", "status": "pass"}],
        )
        problems = self.cross_stack._judge("frontend-harness", report, ran=1)
        self.assertEqual(len(problems), 1)
        self.assertIn("could not prove", problems[0])
        self.assertNotIn("fail against this layer A", problems[0])

    def test_a_clean_run_is_no_failure(self) -> None:
        report = self.report("pass", [{"name": "ruff check", "status": "pass"}])
        self.assertEqual(self.cross_stack._judge("python-harness", report, ran=1), [])

    def test_layer_a_moved_but_nothing_ran_is_the_vacuous_green(self) -> None:
        """The retargeted guard: a skip is honest only when layer A did not move."""
        report = self.report("pass", [{"name": "ruff check", "status": "skipped_unchanged"}])
        problems = self.cross_stack._judge("python-harness", report, ran=0)
        self.assertEqual(len(problems), 1)
        self.assertIn("no gate ran", problems[0])

    def test_a_run_counts_only_gates_that_executed(self) -> None:
        report = self.report(
            "pass",
            [
                {"name": "a", "status": "pass"},
                {"name": "b", "status": "disabled"},
                {"name": "c", "status": "not_applicable"},
                {"name": "d", "status": "skipped_unchanged"},
            ],
        )
        self.assertEqual(self.cross_stack._print_gates(report), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
