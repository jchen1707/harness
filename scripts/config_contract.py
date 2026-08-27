#!/usr/bin/env python3
"""Validate a `harness.config.json` against the schema that declares its contract.

`plugins/harness/schema/harness.config.schema.json` is published as *the* contract for the
one file layer A reads. Until this module existed, `check.py` enforced a hand-written subset
of it in Python -- a `GATE_KINDS` set copied out of the schema's `enum`, the required keys of
a `protected` entry restated in an `if`, the argv shape of a `formatter` asserted twice. Every
one of those is a second copy of a rule that already had an authoritative statement one
directory over, and a schema change nobody mirrored left the checker enforcing last month's
contract while printing a pass.

`check.py` already had the right instinct once: `_source_branch()` greps `SOURCE_BRANCH` out
of `vendor_sync.py` rather than restate it, because "two copies of the same constant is the
drift this repository exists to remove." This is that instinct applied to the contract itself.

## Why a validator here rather than a dependency

Stdlib only, like everything else in this repo: there is no install step anywhere, and adding
one to run the checks would be a worse trade than the ~150 lines below. The subset implemented
is exactly what this schema uses, and **an unrecognised keyword raises** rather than being
skipped. That rule is the whole safety argument. A validator that silently ignores what it
does not understand under-enforces exactly as the hand-written copies did, and it does it
invisibly; this one fails loudly the first time the schema grows a keyword it cannot honour,
which is a build break in the repository that owns the schema -- the cheapest place for it.

## What it does not do

It validates structure, not meaning. "This stack declares no `test` gate, so `/test` would run
nothing" is a true and important failure that no schema can express, because the schema cannot
know that `/test` exists. Those judgments stay in `check.py`, and the split is the point: if a
rule can be written in the schema it belongs there, where every consumer's editor enforces it
too.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Keywords that carry no constraint -- documentation, identity, and the editor-facing hints.
# Listed rather than ignored wholesale, so that an unknown keyword is still an error.
ANNOTATIONS = frozenset(
    {"$comment", "$id", "$schema", "default", "description", "examples", "title"}
)

# Everything this validator actually enforces. `_check` raises on anything outside the union
# of this and ANNOTATIONS.
SUPPORTED = frozenset(
    {
        "$defs",
        "$ref",
        "additionalProperties",
        "allOf",
        "else",
        "enum",
        "if",
        "items",
        "minItems",
        "minLength",
        "properties",
        "required",
        "then",
        "type",
    }
)

TYPES: dict[str, Any] = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "integer": int,
    "number": (int, float),
    "null": type(None),
}


class SchemaUnsupported(Exception):
    """The schema uses a keyword this validator does not implement.

    Deliberately not a validation failure: it means the checker can no longer prove what it
    claims to prove, which is a defect in this file rather than in the document being checked.
    """


def _matches_type(value: Any, expected: str) -> bool:
    if expected == "integer":
        # `True` is an `int` in Python and is not an integer in JSON Schema.
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, TYPES["number"]) and not isinstance(value, bool)
    return isinstance(value, TYPES[expected])


def _resolve(ref: str, root: dict) -> dict:
    """Resolve a local `#/$defs/name` pointer. Remote refs are not supported and never appear."""
    if not ref.startswith("#/"):
        raise SchemaUnsupported(f"non-local $ref: {ref}")
    node: Any = root
    for part in ref[2:].split("/"):
        node = node[part.replace("~1", "/").replace("~0", "~")]
    return node


def _check(document: Any, schema: dict, root: dict, path: str, out: list[str]) -> None:
    """Append one message per violation of `schema` by `document`, at `path`."""
    unknown = set(schema) - SUPPORTED - ANNOTATIONS
    if unknown:
        raise SchemaUnsupported(
            f"{path or '<root>'}: schema uses {', '.join(sorted(unknown))}, which "
            f"config_contract.py does not implement -- teach it or the check under-enforces"
        )

    if "$ref" in schema:
        _check(document, _resolve(schema["$ref"], root), root, path, out)

    where = path or "the document"

    expected = schema.get("type")
    if expected and not _matches_type(document, expected):
        out.append(f"{where} should be {expected}, not {type(document).__name__}")
        return  # Every keyword below assumes the type held; reporting them too is noise.

    if "enum" in schema and document not in schema["enum"]:
        allowed = ", ".join(json.dumps(v) for v in schema["enum"])
        out.append(f"{where} is {json.dumps(document)}, which is not one of: {allowed}")

    if isinstance(document, str) and "minLength" in schema:
        if len(document) < schema["minLength"]:
            out.append(f"{where} is shorter than {schema['minLength']} character(s)")

    if isinstance(document, list):
        if "minItems" in schema and len(document) < schema["minItems"]:
            out.append(f"{where} needs at least {schema['minItems']} item(s)")
        if "items" in schema:
            for index, item in enumerate(document):
                _check(item, schema["items"], root, f"{where}[{index}]", out)

    if isinstance(document, dict):
        for key in schema.get("required", []):
            if key not in document:
                out.append(f"{where} has no {key!r}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in document:
                if key not in properties:
                    out.append(f"{where} has an unknown key {key!r}")
        for key, subschema in properties.items():
            if key in document:
                _check(document[key], subschema, root, f"{where}.{key}" if path else key, out)

    for subschema in schema.get("allOf", []):
        _check(document, subschema, root, path, out)

    # `if/then/else`. The conditional's own failures are not reported -- it is a test, not an
    # assertion -- which is what makes "a router config names apps, everything else declares
    # gates" expressible at all.
    if "if" in schema:
        probe: list[str] = []
        _check(document, schema["if"], root, path, probe)
        branch = schema.get("then") if not probe else schema.get("else")
        if isinstance(branch, dict):
            _check(document, branch, root, path, out)


def violations(document: Any, schema: dict) -> list[str]:
    """Every way `document` breaks `schema`, as readable lines. Empty means it conforms."""
    out: list[str] = []
    _check(document, schema, schema, "", out)
    return out


def load_schema(root: Path) -> dict:
    """The published contract for `harness.config.json`."""
    path = root / "plugins" / "harness" / "schema" / "harness.config.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


def gate_kinds(schema: dict) -> list[str]:
    """The declared gate kinds, read from the schema rather than restated.

    `check.py` kept this as a literal set. It is the single value most likely to be extended
    -- `e2e` and `integration` were both added after the first four -- and the copy would have
    gone stale silently, rejecting a kind the schema had already blessed.
    """
    return list(schema["properties"]["gates"]["items"]["properties"]["kind"]["enum"])
