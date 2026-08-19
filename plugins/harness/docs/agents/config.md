# `harness.config.json` — what layer A asks of a repository

Layer A is authored once and is byte-identical everywhere it lands. That is only possible if
nothing in it names a toolchain, a directory, a team key or a command. Everything it needs to
know about the repository it is running in comes from one file at that repository's root.

`plugins/harness/schema/harness.config.schema.json` is the contract. This file is why it has
the shape it does.

## The rule

> **If a shared file would have to state a fact true in only one stack, that fact becomes a
> config key instead.**

It is the layer rule from `AGENTS.md` applied to executable content. Prose could split — the
doctrine here, the fact there, with a pointer between them. A command cannot: `/lint` has to
actually run something. So the shared half runs _what the config names_, and the naming is the
stack's own.

## Why the gates are one list

`gates` is the Definition of Done written as commands, and it is deliberately the only place
that list exists. Four things read it:

- `/lint` runs the `lint`, `format` and `types` gates;
- `/test` runs the `test` gates, and the `e2e` and `integration` gates on request;
- the verify hook runs them as the Stop gate;
- the meta-repo's cross-stack CI job runs them against a freshly synced layer A.

Before this file, each of those had its own copy of the same four commands, in a different
notation, in a different repository. A gate added to CI and forgotten in the command is the
ordinary failure — and it fails in the direction that looks green.

`kind` is what lets one list serve all four. Without it `/lint` would either run the test
suite or need a second list, which is the copy again.

## Why commands are argv, never strings

A gate is `["uv", "run", "ruff", "check", "."]`, not `"uv run ruff check ."`.

A string has to be parsed by something before it can be run, and every reader would have to
agree on quoting, on globbing, and on what happens to a path with a space in it. Two of the
four readers are JavaScript and two are Python; the odds of them agreeing are poor and the
disagreement would be silent. argv has one meaning.

## What is not in here yet

Hook configuration — the gated paths, the protected files, the formatters — belongs in this
file and is not in it yet. The hooks are still four implementations across two stacks, and
the right shape for their config is not knowable until they are one. It arrives with them.

Declaring the keys now and leaving them unread would be worse than leaving them out: a config
key nothing consumes is a claim the repository cannot check, and it will be wrong by the time
something does read it.

## Adding a key

The test is the rule at the top. A key earns its place when a _shared_ file needs it. A fact
only this repository's own code reads is not config — it belongs wherever that code is, and
putting it here just moves it further from its reader.
