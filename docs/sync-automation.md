# Automated harness delivery

Review and merge the authored change into `harness/v2`. The coordinator handles the
mechanical delivery PRs, required checks, automatic merges and final submodule pin PR.
It discovers consumers from `.gitmodules`; mounted checkouts remain read-only.

The `Reconcile harness sync` workflow runs after successful upstream main generation,
on a fifteen-minute schedule, and through `workflow_dispatch`. It also ships on generated
`main`, because GitHub registers scheduled and workflow-run events from the default branch.
Every run checks out trusted `v2` with full history and waits for successful upstream
publication at that exact commit. Concurrent reconciliations are serialized.

Each stack gets at most one `automation/harness-sync` PR against `v2`. The existing
`vendor_sync.py` creates its vendored content, discovery stubs and applicable generated
transformation drop entries in a disposable clone. Required source and generated-tree
checks must pass before automatic merge. The coordinator refuses branches with human
commits or PRs without its ownership marker. Updates use an explicit force-with-lease.

Once every stack vendors the current content, has successfully published its current
`v2`, and has passing CI on its current `main`, one parent PR updates all source pins.
The parent's generated publisher then refreshes the corresponding main mounts. A parent
pin-only commit does not change vendored content and therefore starts no new delivery PRs.
A successful no-op main generation counts: vendor-only changes often leave the plugin
consumer tree unchanged.

Failures remain visible as failing checks and a failed coordinator run; other consumers
can progress, but the parent pin PR waits for the complete set. Open the Actions run and
its managed PR to see the failing gate. Fix the source in its authored branch, then rerun
or let the next schedule retry. Do not edit a managed branch: if human edits are needed,
close its PR and move the work to a separate branch. Missed events require no manual sync.
Schedules can be delayed by GitHub; fifteen minutes is a requested cadence, not a deadline.

`python3 scripts/reconcile_sync.py --source /path/to/clean/harness-v2` previews the current
reconciliation without writing to GitHub. `--apply` creates/updates PRs and enables their
auto-merge. It requires `gh`, Git, Python 3 and authenticated access to the four repositories.
Gate selection remains in the shared gate reporter and each repository's existing CI.

## Credentials and merge requirements

The coordinator supports a GitHub App via repository variable `HARNESS_APP_ID` and secret
`HARNESS_APP_PRIVATE_KEY`. Install it on all consuming repositories and the parent with
Contents and Pull requests write, Actions read, and Administration read for inspecting
branch protection. Grant Workflows write if generated updates can change workflow files.
Tokens are created per run. An encrypted `HARNESS_SYNC_TOKEN` is the fallback currently
used by this installation. It must access all four repositories and trigger subsequent CI;
the repository-local `GITHUB_TOKEN` is insufficient for that delivery chain.

Every `v2` branch requires its normal PR checks, must be up to date before merging, and
enforces those checks for administrators too. Auto-merge is enabled in repository settings;
the coordinator enables it only for its generated PRs. No approval requirement is bypassed.
`main` remains a generated artifact and keeps the publishing workflow's explicit lease.
The parent publisher uses `WORKFLOW_PAT`; PR validation uses the ordinary GitHub token.
Rotate either credential through GitHub's encrypted Actions secrets, never through files.
