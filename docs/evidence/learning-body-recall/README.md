# Automatic body recall measurement — September 9, 2026

The initial regression returned `no_relevant_learnings` for `zebra-reconcile-83 rollback`
when only the note body contained those words. Automatic task recall now falls back to a
bounded body search after zero summary/path matches. It reads at most 32 indexed regular
files and 64 KiB per file, preserving vault containment, and returns at most four matching
excerpts of 3,000 characters. Budget truncation and unreadable files report partial evidence.
SessionStart still returns project summaries only.

A native host Codex 0.153.4 session in a second actual Git worktree consumed SessionStart
and UserPromptSubmit context. Its prompt omitted the verification marker. It returned the
correct repair, `BODY_FALLBACK_OTTER_47`, and `Project Learnings/lesson.md`. Unrelated note
content was excluded. This is a synthetic fixture in a temporary vault, not a capture or
real Obsidian destination test, and not an interactive or sandbox runtime test.

The first native measurement caught an excerpt selection bug: a common prompt word near
the beginning hid the actual matching lesson after character 5,000. The repaired excerpt
anchors on the longest matching query term. Both measured outcomes are preserved in
[native-results.json](native-results.json). Reproduce with Python and
[native-probe.py.txt](native-probe.py.txt), setting HARNESS_ROOT and FACTORY_ROOT to source
checkouts; it needs the installed authenticated Codex runtime and writes only temporary
fixtures. It disables capture, ignores user configuration, and does not edit trust settings.

Validation: 179 hook tests passed; Prettier passed for changed files;
`scripts/check.py --since=origin/v2` passed in the existing isolated recursive validation
clone with the changed source files copied in. The feature source remains unmerged.

Limits: this fallback searches indexed notes only, and runs only after no index match.
It does not replace the skill's wider search for unindexed notes or body-only evidence
alongside summary hits. The skill retains that mandatory wider search. No claim is made
that the automatic hook searches the entire vault or guarantees semantic relevance.
