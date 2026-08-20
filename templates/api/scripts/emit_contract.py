#!/usr/bin/env python3
"""Emit the OpenAPI contract from the application, or check the committed one is current.

**The api is the source of truth for the contract, and this is what makes that mechanical
rather than aspirational.** The alternative — a hand-written schema beside a hand-written
implementation — is two descriptions of one thing, drifting silently. That is the failure
the whole repository layout exists to prevent, and a contract is where it costs most.

So the committed document is generated, and a gate re-emits it and compares. `--check` is
that gate: it never writes, and it fails with the one command that fixes it.

The path is an argument rather than a constant because the same script serves both shapes:
`packages/contracts/openapi.json` when the web app lives in this repository, and
`contracts/openapi.json` when it does not. `harness.config.json` names the path in the gate's
argv, which is where every other command in this repository gets its paths from.

Stdlib plus the app itself. JSON rather than YAML for one reason: it needs no dependency, and
a contract that cannot be emitted without one is a contract that stops being emitted.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from api.main import app


def document() -> str:
    """The OpenAPI document, as the bytes that belong on disk."""
    return json.dumps(app.openapi(), indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="where the contract is committed")
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if the committed contract is not what the app would emit",
    )
    arguments = parser.parse_args()

    current = document()
    if not arguments.check:
        arguments.path.parent.mkdir(parents=True, exist_ok=True)
        arguments.path.write_text(current, encoding="utf-8")
        print(f"wrote {arguments.path}")
        return 0

    committed = arguments.path.read_text(encoding="utf-8") if arguments.path.exists() else ""
    if committed == current:
        print(f"{arguments.path} is current")
        return 0

    print(
        f"{arguments.path} is not what the app emits.\n"
        f"The contract is generated from the handlers, never hand-edited. Regenerate it:\n"
        f"  uv run python scripts/emit_contract.py {arguments.path}\n"
        f"and commit the result with the change that caused it.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
