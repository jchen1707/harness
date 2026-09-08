#!/usr/bin/env python3
"""Reconcile vendored layer A and read-only mounts through checked, managed PRs.

Only --apply writes to GitHub. Work is generated in disposable clones. Branch protection
owns required checks; this tool refuses auto-merge when that protection is missing.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import check_submodules
import vendor_sync

PARENT = 'jchen1707/harness'
BRANCH = 'automation/harness-sync'
MARKER = '<!-- harness-sync:managed-v1 -->'
EMAIL = 'harness-sync@users.noreply.github.com'
VENDOR = '.agents/vendor/harness'
STUBS = '.agents/skills'
TRANSFORM = '.agents/transform/transform.json'


def command(args, cwd=None, *, data=None):
    result = subprocess.run(args, cwd=cwd, input=data, text=True, capture_output=True)
    if result.returncode:
        # Never include environment or auth configuration in diagnostics.
        raise RuntimeError(f'{args[0]} failed: {result.stderr.strip()}')
    return result.stdout.strip()


def git(root, *args):
    return command(['git', *args], root)


def api(endpoint, payload=None, method=None):
    args = ['gh', 'api', endpoint]
    if method:
        args += ['--method', method]
    if payload is not None:
        args += ['--input', '-']
    output = command(args, data=json.dumps(payload) if payload is not None else None)
    return json.loads(output) if output else None


def repo_name(url):
    match = re.fullmatch(r'https://github\.com/([\w.-]+/[\w.-]+?)(?:\.git)?', url)
    if not match:
        raise ValueError(f'unsupported submodule URL: {url}')
    repo = match.group(1)
    if repo.split('/')[0] != PARENT.split('/')[0]:
        raise ValueError('refusing to write outside the harness owner')
    return repo


def protected(repo):
    protection = api(f'repos/{repo}/branches/v2/protection')
    checks = (protection.get('required_status_checks') or {}).get('checks', [])
    if not checks or not protection['required_status_checks'].get('strict'):
        raise RuntimeError(f'{repo}: v2 must require checks and an up-to-date branch')
    if not protection.get('enforce_admins', {}).get('enabled'):
        raise RuntimeError(f'{repo}: required checks must also apply to administrators')
    return protection


def workflow_passed(repo, workflow, sha):
    result = api(f'repos/{repo}/actions/workflows/{workflow}/runs?head_sha={sha}&event=push&per_page=100')
    runs = [r for r in result['workflow_runs'] if r['head_sha'] == sha and r['event'] == 'push']
    if not runs:
        return False
    latest = max(runs, key=lambda r: r['id'])
    return latest['status'] == 'completed' and latest['conclusion'] == 'success'


def clone(repo, destination):
    command(['git', 'clone', '--quiet', '--branch', 'v2', f'https://github.com/{repo}.git', str(destination)])
    git(destination, 'config', 'user.name', 'Harness Sync')
    git(destination, 'config', 'user.email', EMAIL)
    return destination


def allowed_vendor_path(path):
    return path.startswith(VENDOR + '/') or path.startswith(STUBS + '/') or path == TRANSFORM


def prepare_vendor(source, target):
    """Ignore sha-only churn, but retain every generated content/stub change."""
    manifest = target / VENDOR / 'MANIFEST.json'
    previous = manifest.read_bytes()
    vendor_sync.cmd_sync(source, target)
    current = json.loads(manifest.read_text())
    if json.loads(previous)['files'] == current['files']:
        manifest.write_bytes(previous)
    paths = [VENDOR, STUBS] + ([TRANSFORM] if (target / TRANSFORM).exists() else [])
    git(target, 'add', '-A', '--', *paths)
    changed = git(target, 'diff', '--cached', '--name-only').splitlines()
    if any(not allowed_vendor_path(p) for p in changed):
        raise RuntimeError('vendor update escaped generated paths')
    return bool(changed)


def managed_pr(repo):
    prs = api(f'repos/{repo}/pulls?state=open&head={repo.split("/")[0]}:{BRANCH}&base=v2')
    if len(prs) > 1:
        raise RuntimeError(f'{repo}: multiple managed PRs')
    if prs and MARKER not in (prs[0].get('body') or ''):
        raise RuntimeError(f'{repo}: branch belongs to an unmanaged PR')
    return prs[0] if prs else None


def pr_body(summary):
    return (MARKER + '\n\n## Summary\n\n' + summary +
            '\n\n## What changed\n\nThis PR contains only the generated delivery changes described above. '
            'Source ownership remains upstream; stack configuration and application code are unchanged.\n\n'
            '## How to demo\n\nInspect the generated diff and the required checks on this PR. '
            'For vendor updates, run the upstream vendor_sync.py check command against this checkout. '
            'For parent pins, run python3 scripts/check_submodules.py --pins.\n\n'
            '## Evidence\n\nCI results are attached to this exact PR revision. Auto-merge waits for '
            'all required checks and an up-to-date base; this description makes no claim that pending checks passed.\n\n'
            '## Risks and follow-ups\n\nFailed checks pause delivery. The coordinator retries without '
            'overwriting human commits; the parent pins wait for every generated publication.\n')


def push_pr(repo, root, title, body, apply):
    if not git(root, 'diff', '--cached', '--name-only'):
        print(f'{repo}: no update needed')
        return
    if not apply:
        print(f'{repo}: would propose {title}')
        return
    protected(repo)
    pr = managed_pr(repo)
    payload = {'title': title, 'body': pr_body(body)}
    refs = git(root, 'ls-remote', 'origin', f'refs/heads/{BRANCH}')
    expected = refs.split()[0] if refs else ''
    if expected:
        git(root, 'fetch', '--quiet', 'origin', f'{BRANCH}:refs/remotes/origin/{BRANCH}')
        authors = git(root, 'log', f'origin/v2..origin/{BRANCH}', '--format=%ae').splitlines()
        if any(author != EMAIL for author in authors):
            raise RuntimeError(f'{repo}: managed branch has human changes; leaving it untouched')
        # Same generated tree and base needs no new commit or repeated CI.
        base = git(root, 'rev-parse', 'origin/v2')
        branch_parent = git(root, 'rev-parse', f'origin/{BRANCH}^')
        tree = git(root, 'write-tree')
        if pr and branch_parent == base and tree == git(root, 'rev-parse', f'origin/{BRANCH}^{{tree}}'):
            if pr.get('body') != payload['body'] or pr.get('title') != title:
                api(f'repos/{repo}/pulls/{pr["number"]}', payload, 'PATCH')
            enable_auto_merge(repo, pr['number'], expected)
            return
    git(root, 'commit', '-qm', title, '-m', 'Harness-Automation: managed-v1')
    head = git(root, 'rev-parse', 'HEAD')
    git(root, 'push', f'--force-with-lease=refs/heads/{BRANCH}:{expected}', 'origin', f'HEAD:refs/heads/{BRANCH}')
    if pr:
        pr = api(f'repos/{repo}/pulls/{pr["number"]}', payload, 'PATCH')
    else:
        pr = api(f'repos/{repo}/pulls', {**payload, 'head': BRANCH, 'base': 'v2'}, 'POST')
    print(pr['html_url'])
    enable_auto_merge(repo, pr['number'], head)


def enable_auto_merge(repo, number, sha):
    # --match-head-commit and branch protection prevent merging an unchecked replacement.
    command(['gh', 'pr', 'merge', str(number), '--repo', repo, '--auto', '--squash', '--match-head-commit', sha])


def reconcile(source, apply):
    source_sha = git(source, 'rev-parse', 'HEAD')
    if git(source, 'status', '--porcelain', '--untracked-files=no'):
        raise RuntimeError('source checkout must be clean')
    if source_sha != api(f'repos/{PARENT}/commits/v2')['sha']:
        raise RuntimeError('source checkout is not the current upstream v2')
    # A new source may be waiting for its own generated publication. Do not distribute
    # it until that run validates and publishes the plugin tree successfully.
    if not workflow_passed(PARENT, 'generate-main.yml', source_sha):
        print('Waiting for upstream generated publication; the next run will retry.')
        return
    failures, pins = [], {}
    names = check_submodules.declared(source)
    if not names:
        raise RuntimeError('no stacks declared in .gitmodules')
    with tempfile.TemporaryDirectory(prefix='harness-reconcile-') as temp:
        for path, branch in names.items():
            try:
                if branch != 'v2':
                    raise RuntimeError('reconciliation must read authored v2 mounts')
                url = git(source, 'config', '-f', '.gitmodules', '--get', f'submodule.{path}.url')
                repo = repo_name(url)
                target = clone(repo, Path(temp) / path)
                head = git(target, 'rev-parse', 'HEAD')
                if prepare_vendor(source, target):
                    push_pr(repo, target, f'chore: sync harness layer A at {source_sha[:9]}',
                            f'Generated from {PARENT}@{source_sha} using vendor_sync.py.\n\n'
                            'Only vendored files, generated discovery stubs and their generated drop-list entries change. '
                            'Required checks must pass before automatic merge. Human changes on this branch stop automation.', apply)
                    continue
                # A content-identical pin is current. Wait for both delivery flavors:
                # a successful no-op generation is valid too, so do not require main's
                # commit message to mention this v2 SHA.
                main_sha = api(f'repos/{repo}/commits/main')['sha']
                if not workflow_passed(repo, 'generate-main.yml', head) or not workflow_passed(repo, 'ci.yml', main_sha):
                    print(f'{repo}: waiting for v2 publication/main CI')
                    continue
                pins[path] = head
            except (RuntimeError, ValueError, OSError, SystemExit) as exc:
                failures.append(f'{path}: {exc}')
        # Publish one coherent pin update only when every stack is current and certified.
        if len(pins) == len(names) and not failures:
            parent = clone(PARENT, Path(temp) / 'parent')
            if git(parent, 'rev-parse', 'HEAD') != source_sha:
                raise RuntimeError('upstream advanced during reconciliation; retry next run')
            for path, sha in pins.items():
                git(parent, 'update-index', '--add', '--cacheinfo', f'160000,{sha},{path}')
            push_pr(PARENT, parent, 'chore: refresh certified harness stack pins',
                    'All stacks vendor the current layer A. Each pinned v2 commit has a successful '
                    'generated publication, and its current main has passing CI.\n\n' +
                    '\n'.join(f'- `{p}`: `{s}`' for p, s in pins.items()), apply)
        else:
            print('Parent pins wait for all stack updates and generated publications.')
    if failures:
        raise RuntimeError('\n'.join(failures))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path.cwd())
    parser.add_argument('--apply', action='store_true', help='push managed PRs and enable checked auto-merge')
    args = parser.parse_args()
    try:
        reconcile(args.source.resolve(), args.apply)
    except (RuntimeError, ValueError, OSError) as exc:
        print(f'Reconciliation stopped: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
