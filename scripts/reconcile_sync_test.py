"""Safety and convergence tests for cross-repository reconciliation."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import reconcile_sync as sync


class PolicyTests(unittest.TestCase):
    def test_repository_scope(self):
        self.assertEqual(sync.repo_name('https://github.com/jchen1707/go-harness.git'), 'jchen1707/go-harness')
        for url in ['https://github.com/other/harness.git', 'file:///tmp/repo', 'https://example.com/a/b']:
            with self.assertRaises(ValueError):
                sync.repo_name(url)

    def test_unprotected_or_bypassable_branches_cannot_auto_merge(self):
        cases = [{}, {'required_status_checks': {'checks': [{'context': 'test'}], 'strict': False}},
                 {'required_status_checks': {'checks': [{'context': 'test'}], 'strict': True}}]
        for protection in cases:
            with patch.object(sync, 'api', return_value=protection), self.assertRaises(RuntimeError):
                sync.protected('owner/repo')

    def test_latest_workflow_attempt_must_pass_at_exact_sha(self):
        success = {'id': 1, 'head_sha': 'abc', 'event': 'push', 'status': 'completed', 'conclusion': 'success'}
        for runs, expected in [([], False), ([success], True),
                               ([success, dict(success, id=2, status='in_progress', conclusion=None)], False),
                               ([dict(success, head_sha='wrong')], False),
                               ([dict(success, event='pull_request')], False)]:
            with patch.object(sync, 'api', return_value={'workflow_runs': runs}):
                self.assertEqual(sync.workflow_passed('repo', 'ci.yml', 'abc'), expected)

    def test_unmanaged_pull_request_is_not_adopted(self):
        with patch.object(sync, 'api', return_value=[{'body': 'Human work'}]), self.assertRaises(RuntimeError):
            sync.managed_pr('owner/repo')

    def test_auto_merge_matches_verified_head(self):
        with patch.object(sync, 'command') as command:
            sync.enable_auto_merge('owner/repo', 12, 'exact-sha')
            args = command.call_args.args[0]
            self.assertEqual(args[-2:], ['--match-head-commit', 'exact-sha'])
            self.assertIn('--auto', args)


class VendorConvergenceTests(unittest.TestCase):
    def test_parent_pin_only_changes_do_not_start_another_sync_round(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            manifest = root / sync.VENDOR / 'MANIFEST.json'
            manifest.parent.mkdir(parents=True)
            (root / sync.STUBS).mkdir(parents=True)
            old = {'sha': 'old', 'files': {'a': 'same'}}
            manifest.write_text(json.dumps(old))
            subprocess.run(['git', '-C', str(root), 'add', '.'], check=True)
            subprocess.run(['git', '-C', str(root), '-c', 'user.name=Test', '-c', 'user.email=t@t', 'commit', '-qm', 'fixture'], check=True)

            def regenerate(*_):
                manifest.write_text(json.dumps({'sha': 'new', 'files': {'a': 'same'}}))

            with patch.object(sync.vendor_sync, 'cmd_sync', side_effect=regenerate):
                self.assertFalse(sync.prepare_vendor(root, root))
                self.assertEqual(json.loads(manifest.read_text()), old)

            def changed_content(*_):
                manifest.write_text(json.dumps({'sha': 'new', 'files': {'a': 'different'}}))

            with patch.object(sync.vendor_sync, 'cmd_sync', side_effect=changed_content):
                self.assertTrue(sync.prepare_vendor(root, root))

    def test_generated_stub_change_is_not_mistaken_for_sha_only_churn(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            manifest = root / sync.VENDOR / 'MANIFEST.json'
            manifest.parent.mkdir(parents=True)
            manifest.write_text(json.dumps({'sha': 'old', 'files': {}}))
            stub = root / sync.STUBS / 'verify/SKILL.md'
            stub.parent.mkdir(parents=True)
            stub.write_text('old stub')
            subprocess.run(['git', '-C', str(root), 'add', '.'], check=True)
            subprocess.run(['git', '-C', str(root), '-c', 'user.name=Test', '-c', 'user.email=t@t', 'commit', '-qm', 'fixture'], check=True)
            with patch.object(sync.vendor_sync, 'cmd_sync', side_effect=lambda *_: stub.write_text('new stub')):
                self.assertTrue(sync.prepare_vendor(root, root))




class RolloutTests(unittest.TestCase):
    def test_unpublished_upstream_does_not_touch_consumers(self):
        with patch.object(sync, 'git', side_effect=['abc', '']), \
             patch.object(sync, 'api', return_value={'sha': 'abc'}), \
             patch.object(sync, 'workflow_passed', return_value=False), \
             patch.object(sync, 'clone') as clone:
            sync.reconcile(Path('/source'), True)
            clone.assert_not_called()

    def test_human_commits_on_managed_branch_stop_before_push(self):
        def fake_git(root, *args):
            if args[:3] == ('diff', '--cached', '--name-only'): return 'generated/file'
            if args[0] == 'ls-remote': return 'deadbeef refs/heads/' + sync.BRANCH
            if args[0] == 'log': return 'human@example.com'
            return ''
        with patch.object(sync, 'git', side_effect=fake_git) as git, \
             patch.object(sync, 'protected'), patch.object(sync, 'managed_pr', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'human changes'):
                sync.push_pr('owner/repo', Path('/fixture'), 'title', 'body', True)
            self.assertFalse(any(call.args[1] == 'push' for call in git.call_args_list))

    def test_missing_stack_publication_prevents_parent_pin_update(self):
        def fake_git(root, *args):
            if args[:2] == ('rev-parse', 'HEAD'): return 'abc'
            if args[0] == 'config': return 'https://github.com/jchen1707/go-harness.git'
            return ''
        with patch.object(sync, 'git', side_effect=fake_git), \
             patch.object(sync, 'api', return_value={'sha': 'abc'}), \
             patch.object(sync.check_submodules, 'declared', return_value={'go-harness': 'v2'}), \
             patch.object(sync, 'clone', return_value=Path('/consumer')) as clone, \
             patch.object(sync, 'prepare_vendor', return_value=False), \
             patch.object(sync, 'workflow_passed', side_effect=[True, False]), \
             patch.object(sync, 'push_pr') as push:
            sync.reconcile(Path('/source'), True)
            self.assertEqual(clone.call_count, 1)
            push.assert_not_called()


if __name__ == '__main__':
    unittest.main()
