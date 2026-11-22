"""Behavioral coverage for fixed-snapshot engineering-record checks."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from consistency_core import CoverageError, evaluate, load_coverage, scope_digest, source_excludes
from consistency_snapshot import GitRepo


class ConsistencyCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git('init', '-q')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'user.name', 'Test')
        self.write('src/a.py', 'a = 1\n')
        self.write('docs/module.md', '# Module\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'initial source')
        self.anchor = self.git('rev-parse', 'HEAD')
        self.config = {'coverage': {'version': 1, 'enabled': True, 'adopted_at': self.anchor,
            'source_roots': ['src/**'], 'exclude': [],
            'defaults': {'warn_at': 1, 'block_at': 3},
            'groups': [{'id': 'module', 'sources': ['src/**'],
                        'record': {'path': 'docs/module.md'}, 'rules': ['record', 'review']}]}}
        self.save_config()
        self.commit('adopt')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], text=True, stderr=subprocess.STDOUT).strip()

    def write(self, path, body):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding='utf-8')

    def save_config(self):
        self.write('docs/project-harness/harness-config.json', json.dumps(self.config))

    def commit(self, message):
        self.git('add', '.')
        self.git('commit', '-qm', message)
        return self.git('rev-parse', 'HEAD')

    def report(self, kind='worktree', **kwargs):
        repo = GitRepo(self.root)
        snap = repo.worktree() if kind == 'worktree' else repo.index() if kind == 'staged' else repo.snapshot(kind)
        return evaluate(repo, snap, 'docs/project-harness/harness-config.json', **kwargs)

    def codes(self, report):
        return {f['code'] for f in report['findings']}

    def group(self, report):
        return report['groups'][0]

    def proof(self, reason='Reviewed the implementation and tests', review='Verified behavior against module contract', parent=None):
        repo = GitRepo(self.root)
        cov = load_coverage(self.config)
        group = cov['groups'][0]
        snapshot = repo.worktree()
        return {'version': 1, 'group': 'module', 'rule': 'review/v1',
            'scope_digest': scope_digest(group, cov),
            'source_digest': snapshot.digest(group['sources'], exclude=source_excludes(group, cov, 'docs/module.md')),
            'decision': 'reviewed-no-doc-change', 'actor': 'reviewer', 'reason': reason,
            'basis': {'parent': parent or repo.head(), 'review': review}}

    def put_proof(self, proof):
        self.write('docs/module.md', '# Module\n\n```exharness-review\n' + json.dumps(proof) + '\n```\n')

    def test_new_source_without_coverage_is_error(self):
        self.config['coverage']['groups'][0]['sources'] = ['src/a.py']
        self.save_config()
        self.write('src/new.py', 'new = True\n')
        report = self.report()
        self.assertIn('SOURCE_UNCOVERED', self.codes(report))
        self.assertEqual(report['exit_code'], 1)

    def test_debt_crosses_three_small_commits(self):
        for n in range(2, 5):
            self.write('src/a.py', f'a = {n}\n')
            self.commit(f'change {n}')
        report = self.report()
        self.assertEqual(self.group(report)['debt'], 3)
        self.assertEqual(report['exit_code'], 1)
        self.assertIn('REVIEW_DEBT', self.codes(report))

    def test_unrelated_commits_do_not_count_and_pending_counts_once(self):
        self.write('other.txt', 'unrelated')
        self.commit('unrelated')
        self.write('src/a.py', 'a = 2\n')
        self.assertEqual(self.group(self.report())['debt'], 1)
        self.assertEqual(self.report()['exit_code'], 0)

    def test_same_commit_source_and_review_is_checkpoint(self):
        self.write('src/a.py', 'a = 2\n')
        self.put_proof(self.proof())
        checkpoint = self.commit('source and exact evidence')
        report = self.report()
        self.assertEqual(report['exit_code'], 0)
        self.assertEqual(self.group(report)['debt'], 0)
        self.assertEqual(self.group(report)['checkpoint'], checkpoint)

    def test_staged_proof_does_not_borrow_unstaged_fix(self):
        self.write('src/a.py', 'a = 2\n')
        self.git('add', 'src/a.py')
        self.put_proof(self.proof())
        self.assertEqual(self.group(self.report('staged'))['debt'], 1)
        self.assertEqual(self.group(self.report())['debt'], 0)

    def test_a_b_a_never_reaccepts_old_unchanged_block(self):
        self.put_proof(self.proof())
        original = self.commit('review A')
        self.write('src/a.py', 'a = 2\n')
        self.commit('B')
        self.write('src/a.py', 'a = 1\n')
        self.commit('return A')
        report = self.report()
        self.assertEqual(self.group(report)['checkpoint'], original)
        self.assertEqual(self.group(report)['debt'], 2)

    def test_date_only_does_not_reset_debt(self):
        proof = self.proof()
        self.put_proof(proof)
        self.commit('review')
        self.write('src/a.py', 'a = 2\n')
        self.commit('changed')
        proof['date'] = '2099-01-01'
        self.put_proof(proof)
        self.commit('date')
        self.assertEqual(self.group(self.report())['debt'], 1)

    def test_refresh_requires_new_substantive_basis(self):
        self.put_proof(self.proof())
        self.commit('review')
        self.write('src/a.py', 'a = 2\n')
        self.put_proof(self.proof())
        report = self.report()
        self.assertIn('REVIEW_REFRESH_INVALID', self.codes(report))
        self.assertEqual(self.group(report)['debt'], 1)
        self.put_proof(self.proof(review='Compared new behavior and regression evidence'))
        self.assertEqual(self.group(self.report())['debt'], 0)

    def test_invalid_or_unknown_proof_blocks_are_errors(self):
        for mutation in ({'reason': ''}, {'group': 'unknown'}, {'unexpected': True}):
            with self.subTest(mutation=mutation):
                proof = self.proof()
                proof.update(mutation)
                self.put_proof(proof)
                self.assertIn('REVIEW_INVALID', self.codes(self.report()))

    def test_deleted_record_is_error(self):
        (self.root / 'docs/module.md').unlink()
        self.assertIn('RECORD_MISSING', self.codes(self.report()))

    @unittest.skipUnless(hasattr(os, 'symlink'), 'symlinks unavailable')
    def test_record_symlink_does_not_read_external_target(self):
        (self.root / 'docs/module.md').unlink()
        os.symlink(str(self.root / 'src/a.py'), self.root / 'docs/module.md')
        self.assertIn('RECORD_TYPE', self.codes(self.report()))

    def test_legacy_item_locator_uses_snapshot_bytes(self):
        self.config['coverage']['groups'][0]['record'] = {'item': 'task-one'}
        self.save_config()
        self.write('docs/project-harness/mvp-checklist.json', json.dumps({'items': [
            {'id': 'task-one', 'plan_path': 'docs/module.md'}]}))
        self.assertEqual(self.group(self.report())['record_path'], 'docs/module.md')
        self.write('docs/project-harness/harness-checklist.json', '{"items": []}')
        self.assertIn('CHECKLIST_AMBIGUOUS', self.codes(self.report()))

    def test_item_conflicting_locators_fail_closed(self):
        self.config['coverage']['groups'][0]['record'] = {'item': 'task-one'}
        self.save_config()
        self.write('docs/project-harness/harness-checklist.json', json.dumps({'items': [
            {'id': 'task-one', 'plan_path': 'docs/module.md', 'artifacts': {'plan': 'docs/other.md'}}]}))
        self.assertIn('RECORD_LOCATOR_INVALID', self.codes(self.report()))

    def test_missing_or_disabled_coverage_is_incomplete(self):
        self.write('docs/project-harness/harness-config.json', '{}')
        self.assertEqual(self.report()['exit_code'], 2)
        self.config['coverage']['enabled'] = False
        self.save_config()
        self.assertEqual(self.report()['exit_code'], 2)

    def test_strict_configuration_rejects_unknown_and_invalid_fields(self):
        mutations = [lambda c: c.update({'typo': True}), lambda c: c.update({'version': True}),
                     lambda c: c['groups'][0].update({'oops': 1}),
                     lambda c: c['groups'][0].update({'rules': ['review']}),
                     lambda c: c.update({'defaults': {'warn_at': 3, 'block_at': 1}})]
        for mutate in mutations:
            cov = copy.deepcopy(self.config['coverage'])
            mutate(cov)
            with self.subTest(cov=cov), self.assertRaises(CoverageError):
                load_coverage({'coverage': cov})

    def test_missing_adoption_history_is_incomplete(self):
        self.config['coverage']['adopted_at'] = 'f' * 40
        self.save_config()
        self.assertEqual(self.report()['exit_code'], 2)

    def test_scan_budget_is_incomplete(self):
        self.config['coverage']['history_limit'] = 1
        self.save_config()
        self.write('src/a.py', 'a=2')
        self.commit('one')
        self.write('src/a.py', 'a=3')
        self.commit('two')
        self.assertEqual(self.report()['exit_code'], 2)

    def test_scope_change_invalidates_previous_review(self):
        self.put_proof(self.proof())
        self.commit('review')
        self.write('src/a.py', 'a=2')
        self.commit('changed')
        self.config['coverage']['groups'][0]['sources'] = ['src/a.py']
        self.save_config()
        self.assertEqual(self.group(self.report())['debt'], 1)

    def test_baseline_only_suppresses_exact_old_evidence_and_requires_pruning(self):
        self.write('src/a.py', 'a=2')
        origin = self.commit('old debt')
        before = self.report(apply_baseline=False)
        finding = next(f for f in before['findings'] if f['code'] == 'REVIEW_DEBT')
        self.config['coverage']['baseline'] = 'docs/baseline.json'
        self.save_config()
        self.write('docs/baseline.json', json.dumps({'version': 1, 'origin': origin, 'entries': [
            {k: finding[k] for k in ('fingerprint', 'code', 'group', 'path', 'evidence')}]}))
        self.assertTrue(any(f.get('suppressed') for f in self.report()['findings']))
        self.write('src/a.py', 'a=3')
        self.assertIn('BASELINE_STALE', self.codes(self.report()))
        self.assertFalse(any(f.get('suppressed') for f in self.report()['findings']))

    def test_external_record_without_fixed_caller_evidence_is_incomplete(self):
        self.config['coverage']['groups'][0]['record'] = {'item': 'task-one'}
        self.save_config()
        self.write('docs/project-harness/harness-checklist.json', json.dumps({'items': [
            {'id': 'task-one', 'plan_path': str(self.root.parent / 'external.md')}]}))
        self.git('add', '.')
        self.assertEqual(self.report('staged')['exit_code'], 2)

    def test_committed_invalid_refresh_still_reports_structural_error(self):
        self.put_proof(self.proof())
        self.commit('initial review')
        self.write('src/a.py', 'a=2')
        self.put_proof(self.proof())
        self.commit('invalid refresh with same basis')
        self.assertIn('REVIEW_REFRESH_INVALID', self.codes(self.report()))

    def test_baseline_cannot_invent_old_evidence_using_an_older_origin(self):
        self.write('src/a.py', 'a=2')
        self.commit('new debt')
        finding = next(f for f in self.report()['findings'] if f['code'] == 'REVIEW_DEBT')
        self.config['coverage']['baseline'] = 'docs/baseline.json'
        self.save_config()
        self.write('docs/baseline.json', json.dumps({'version': 1, 'origin': self.git('rev-parse', 'HEAD^'), 'entries': [
            {k: finding[k] for k in ('fingerprint', 'code', 'group', 'path', 'evidence')}]}))
        report = self.report()
        self.assertIn('BASELINE_INVALID', self.codes(report))
        self.assertFalse(any(f.get('suppressed') for f in report['findings']))

    def test_fixed_external_record_manifest_is_verified_against_object_bytes(self):
        with tempfile.TemporaryDirectory() as external:
            root = Path(external)
            subprocess.check_call(['git', 'init', '-q', external])
            subprocess.check_call(['git', '-C', external, 'config', 'user.name', 'Test'])
            subprocess.check_call(['git', '-C', external, 'config', 'user.email', 'test@example.invalid'])
            (root / 'plan.md').write_text('# Canonical external plan', encoding='utf-8')
            subprocess.check_call(['git', '-C', external, 'add', '.'])
            subprocess.check_call(['git', '-C', external, 'commit', '-qm', 'external record'])
            revision = subprocess.check_output(['git', '-C', external, 'rev-parse', 'HEAD'], text=True).strip()
            blob = subprocess.check_output(['git', '-C', external, 'rev-parse', 'HEAD:plan.md'], text=True).strip()
            self.config['coverage']['groups'][0]['record'] = {'item': 'task-one'}
            self.save_config()
            self.write('docs/project-harness/harness-checklist.json', json.dumps({'items': [
                {'id': 'task-one', 'plan_path': str(root / 'plan.md')}]}))
            self.git('add', '.')
            manifest = {'version': 1, 'records': [{'locator': str(root / 'plan.md'), 'repo': external,
                         'revision': revision, 'path': 'plan.md', 'blob': blob}]}
            report = self.report('staged', external_records=manifest)
            self.assertEqual(report['exit_code'], 0, report)
            self.assertEqual(self.group(report)['record_source']['revision'], revision)
            manifest['records'][0]['blob'] = '0' * 40
            self.assertEqual(self.report('staged', external_records=manifest)['exit_code'], 2)

    def test_structural_and_history_failure_are_both_preserved(self):
        self.config['coverage']['adopted_at'] = 'f' * 40
        self.config['coverage']['groups'][0]['sources'] = ['src/other.py']
        self.save_config()
        report = self.report()
        self.assertIn('SOURCE_UNCOVERED', self.codes(report))
        self.assertIn('HISTORY_INCOMPLETE', self.codes(report))
        self.assertEqual(report['exit_code'], 2)

    def test_local_standalone_external_plain_file_remains_diagnosable(self):
        with tempfile.TemporaryDirectory() as external:
            path = Path(external) / 'plan.md'
            path.write_text('# Existing canonical plan', encoding='utf-8')
            self.config['coverage']['groups'][0]['record'] = {'item': 'task-one'}
            self.save_config()
            self.write('docs/project-harness/harness-checklist.json', json.dumps({'items': [
                {'id': 'task-one', 'plan_path': str(path)}]}))
            report = self.report()
            self.assertEqual(self.group(report)['record_digest'], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(self.group(report)['record_source']['kind'], 'external-file')

    def test_ownership_uses_same_posix_globs_as_source_projection(self):
        self.config['coverage']['groups'][0]['sources'] = ['src/*']
        self.save_config()
        self.write('src/sub/new.py', 'new=1')
        report = self.report()
        self.assertIn('SOURCE_UNCOVERED', self.codes(report))

    def test_stricter_threshold_does_not_reuse_old_warning_fingerprint(self):
        self.write('src/a.py', 'a=2')
        self.commit('debt')
        old = next(f for f in self.report()['findings'] if f['code'] == 'REVIEW_DEBT')
        self.config['coverage']['defaults']['block_at'] = 1
        self.save_config()
        new = next(f for f in self.report()['findings'] if f['code'] == 'REVIEW_DEBT')
        self.assertNotEqual(old['fingerprint'], new['fingerprint'])

    def reviewed_branch(self):
        base = self.git('rev-parse', 'HEAD')
        main = self.git('branch', '--show-current')
        self.git('checkout', '-qb', 'feature')
        self.write('src/a.py', 'a=2')
        self.put_proof(self.proof())
        head = self.commit('reviewed source on branch')
        self.git('checkout', '-q', main)
        return base, head

    def test_real_merge_accepts_proof_introduced_on_fixed_side_branch(self):
        base, head = self.reviewed_branch()
        self.write('unrelated.txt', 'advanced integration branch')
        self.commit('advance integration')
        self.git('merge', '--no-ff', '-qm', 'merge feature', 'feature')
        result = self.git('rev-parse', 'HEAD')
        report = self.report(result)
        self.assertEqual(report['exit_code'], 0, report)
        self.assertEqual(self.group(report)['debt'], 0)
        self.assertEqual(self.group(report)['checkpoint'], result)

    def test_squash_accepts_fixed_head_proof_without_counting_side_commits(self):
        base, head = self.reviewed_branch()
        self.git('merge', '--squash', 'feature')
        result = self.commit('squash integration')
        report = self.report(result)
        self.assertEqual(report['exit_code'], 0, report)
        self.assertEqual(self.group(report)['debt'], 0)

    def test_side_proof_cannot_acknowledge_extra_integrated_source(self):
        base, head = self.reviewed_branch()
        self.git('merge', '--squash', 'feature')
        self.write('src/extra.py', 'extra=1')
        result = self.commit('integrate with additional source')
        report = self.report(result)
        self.assertIn('REVIEW_BINDING_INVALID', self.codes(report))
        self.assertEqual(self.group(report)['debt'], 1)

    def test_corrected_old_malformed_block_is_not_permanent_history_failure(self):
        self.write('docs/module.md', '```exharness-review\n{bad}\n```\n')
        self.commit('malformed evidence')
        self.write('src/a.py', 'a=2')
        self.put_proof(self.proof())
        self.commit('correct evidence')
        report = self.report()
        self.assertEqual(report['exit_code'], 0, report)
        self.assertEqual(self.group(report)['debt'], 0)

    def test_pending_handoff_uses_selected_record_bytes(self):
        repo = GitRepo(self.root)
        cov = load_coverage(self.config)
        group = cov['groups'][0]
        packet = 'docs/project-harness/tasks/task-one/handoff.md'
        item = {'id': 'task-one', 'status': 'doing', 'plan_path': 'docs/module.md',
                'workflow': {'status': 'handoff_requested', 'handoff_target': 'next'},
                'artifacts': {'handoff_packet': packet}}
        binding = {'version': 1, 'item': 'task-one', 'target': 'next', 'plan': 'docs/module.md',
            'plan_sha256': hashlib.sha256((self.root / 'docs/module.md').read_bytes()).hexdigest(),
            'sources': [{'group': 'module', 'scope_digest': scope_digest(group, cov),
                         'source_digest': repo.worktree().digest(group['sources'], source_excludes(group, cov, 'docs/module.md'))}]}
        self.write('docs/project-harness/harness-checklist.json', json.dumps({'items': [item]}))
        from harness_common import render_plan_snapshot
        body = (self.root / 'docs/module.md').read_text(encoding='utf-8')
        self.write(packet, '<!-- exharness-handoff ' + json.dumps(binding) + ' -->\n\n'
                   + '## Canonical Plan Content\n\n' + render_plan_snapshot(body) + '\n')
        self.git('add', '.')
        self.write('docs/module.md', '# Changed after handoff\n')
        self.assertIn('handoff-stale', self.codes(self.report()))
        self.assertNotIn('handoff-stale', self.codes(self.report('staged')))

    def test_managed_item_export_does_not_prove_live_record_authority(self):
        self.config['deployment_profile'] = 'coordinate-managed'
        self.config['coverage']['groups'][0]['record'] = {'item': 'task-one'}
        self.save_config()
        self.write('docs/project-harness/harness-checklist.json', json.dumps({'items': [
            {'id': 'task-one', 'plan_path': 'docs/module.md'}]}))
        report = self.report()
        self.assertIn('MANAGED_AUTHORITY_UNVERIFIED', self.codes(report))
        self.assertEqual(report['exit_code'], 2)

    def test_external_manifest_can_mount_fixed_repo_at_different_path(self):
        with tempfile.TemporaryDirectory() as external:
            root = Path(external)
            subprocess.check_call(['git', 'init', '-q', external])
            subprocess.check_call(['git', '-C', external, 'config', 'user.name', 'Test'])
            subprocess.check_call(['git', '-C', external, 'config', 'user.email', 'test@example.invalid'])
            (root / 'plan.md').write_text('# Private plan', encoding='utf-8')
            subprocess.check_call(['git', '-C', external, 'add', '.'])
            subprocess.check_call(['git', '-C', external, 'commit', '-qm', 'fixed private evidence'])
            revision = subprocess.check_output(['git', '-C', external, 'rev-parse', 'HEAD'], text=True).strip()
            blob = subprocess.check_output(['git', '-C', external, 'rev-parse', 'HEAD:plan.md'], text=True).strip()
            locator = str(self.root.parent / 'unavailable-canonical' / 'plan.md')
            self.config['coverage']['groups'][0]['record'] = {'item': 'task-one'}
            self.save_config()
            self.write('docs/project-harness/harness-checklist.json', json.dumps({'items': [
                {'id': 'task-one', 'plan_path': locator}]}))
            self.git('add', '.')
            manifest = {'version': 1, 'records': [{'locator': locator, 'repo': external,
                         'revision': revision, 'path': 'plan.md', 'blob': blob}]}
            report = self.report('staged', external_records=manifest)
            self.assertEqual(report['exit_code'], 0, report)
            self.assertEqual(self.group(report)['record_source']['repo'], str(root.resolve()))

    def test_baseline_missing_origin_object_is_incomplete(self):
        self.config['coverage']['baseline'] = 'docs/baseline.json'
        self.save_config()
        self.write('docs/baseline.json', json.dumps({'version': 1, 'origin': 'f' * 40, 'entries': []}))
        report = self.report()
        self.assertIn('BASELINE_INCOMPLETE', self.codes(report))
        self.assertEqual(report['exit_code'], 2)

    def test_locked_authority_profile_survives_candidate_profile_relaxation(self):
        locked = load_coverage(self.config)
        locked['groups'][0]['record'] = {'item': 'task-one'}
        self.config['deployment_profile'] = 'standalone'
        self.config['coverage']['groups'][0]['record'] = {'item': 'task-one'}
        self.save_config()
        self.write('docs/project-harness/harness-checklist.json', json.dumps({'items': [
            {'id': 'task-one', 'plan_path': 'docs/module.md'}]}))
        report = self.report(policy=locked, authority_profile='coordinate-managed')
        self.assertIn('MANAGED_AUTHORITY_UNVERIFIED', self.codes(report))
        self.assertEqual(report['exit_code'], 2)

    def test_locked_policy_accepts_well_formed_new_group_block_in_shared_record(self):
        locked = load_coverage(self.config)
        self.config['coverage']['groups'].append({'id': 'new-module', 'sources': ['new/**'],
            'record': {'path': 'docs/module.md'}, 'rules': ['record', 'review']})
        self.config['coverage']['source_roots'].append('new/**')
        self.save_config()
        self.write('new/a.py', 'new = 1')
        cov = load_coverage(self.config)
        group = cov['groups'][1]
        proof = self.proof()
        proof['group'] = group['id']
        proof['scope_digest'] = scope_digest(group, cov)
        proof['source_digest'] = GitRepo(self.root).worktree().digest(group['sources'], source_excludes(group, cov, 'docs/module.md'))
        self.put_proof(proof)
        report = self.report(policy=locked)
        self.assertNotIn('REVIEW_INVALID', self.codes(report))
        self.assertEqual(report['exit_code'], 0, report)
        self.assertEqual([g['id'] for g in report['groups']], ['module'])
        self.assertEqual(self.report()['exit_code'], 0)
        proof['unexpected'] = True
        self.put_proof(proof)
        self.assertIn('REVIEW_INVALID', self.codes(self.report()))

    def two_commit_reviewed_branch(self):
        main = self.git('branch', '--show-current')
        self.git('checkout', '-qb', 'feature-two')
        self.write('src/a.py', 'a=2')
        contextual_parent = self.commit('feature first change')
        self.write('src/a.py', 'a=3')
        self.put_proof(self.proof())
        head = self.commit('feature second change with review')
        self.git('checkout', '-q', main)
        return head, contextual_parent

    def test_squash_checkpoint_survives_generic_drift_without_original_head(self):
        head, contextual_parent = self.two_commit_reviewed_branch()
        self.git('merge', '--squash', 'feature-two')
        integrated = self.commit('squashed implementation')
        self.git('branch', '-D', 'feature-two')
        report = self.report()
        self.assertEqual(report['exit_code'], 0, report)
        self.assertEqual(self.group(report)['debt'], 0)
        self.assertEqual(self.group(report)['checkpoint'], integrated)
        self.assertEqual(self.group(report)['checkpoint_evidence']['basis']['parent'], contextual_parent)
        self.assertEqual(self.group(report)['checkpoint_evidence']['parent_role'], 'context')
        self.write('src/a.py', 'a=4')
        self.commit('new small follow-up')
        self.assertEqual(self.group(self.report())['debt'], 1)

    def test_rebased_evidence_binds_integrated_source_after_context_parent_changes(self):
        head, contextual_parent = self.two_commit_reviewed_branch()
        self.write('unrelated.txt', 'advanced integration branch')
        self.commit('advance main before rebase')
        main = self.git('branch', '--show-current')
        self.git('checkout', '-q', 'feature-two')
        self.git('rebase', main)
        self.assertNotEqual(self.git('rev-parse', 'HEAD^'), contextual_parent)
        self.git('checkout', '-q', main)
        self.git('merge', '--ff-only', 'feature-two')
        integrated = self.git('rev-parse', 'HEAD')
        self.git('branch', '-D', 'feature-two')
        report = self.report()
        self.assertEqual(report['exit_code'], 0, report)
        self.assertEqual(self.group(report)['debt'], 0)
        self.assertEqual(self.group(report)['checkpoint'], integrated)

    def test_substantive_refresh_can_keep_same_parent_context(self):
        stable_base = self.git('rev-parse', 'HEAD')
        self.put_proof(self.proof(parent=stable_base))
        self.commit('initial review')
        self.write('src/a.py', 'a=2')
        self.put_proof(self.proof(parent=stable_base, review='Compared changed behavior and new test evidence'))
        self.assertEqual(self.group(self.report())['debt'], 0)
        integrated = self.commit('substantive refresh using same stable base')
        self.assertEqual(self.group(self.report())['checkpoint'], integrated)
        self.assertEqual(self.group(self.report())['debt'], 0)

    def test_external_current_proof_cannot_invent_historical_introduction(self):
        with tempfile.TemporaryDirectory() as external:
            path = Path(external) / 'plan.md'
            self.config['coverage']['groups'][0]['record'] = {'item': 'task-one'}
            self.save_config()
            self.write('docs/project-harness/harness-checklist.json', json.dumps({'items': [
                {'id': 'task-one', 'plan_path': str(path)}]}))
            proof = self.proof()
            proof['item'] = 'task-one'
            path.write_text('```exharness-review\n' + json.dumps(proof) + '\n```\n', encoding='utf-8')
            report = self.report()
            self.assertIn('EXTERNAL_CHECKPOINT_UNVERIFIED', self.codes(report))
            self.assertEqual(report['exit_code'], 2)
            self.write('src/a.py', 'a=2')
            self.commit('source B')
            self.write('src/a.py', 'a = 1\n')
            self.commit('source A restored')
            report = self.report()
            self.assertEqual(self.group(report)['debt'], 2)
            self.assertEqual(report['exit_code'], 2)

    def external_anchor_fixture(self, external):
        path = Path(external) / 'plan.md'
        self.config['coverage']['groups'][0]['record'] = {'item': 'task-one'}
        self.save_config()
        self.write('docs/project-harness/harness-checklist.json', json.dumps({'items': [
            {'id': 'task-one', 'plan_path': str(path)}]}))
        self.commit('external locator')
        return path

    def write_external_anchor(self, path, source_commit):
        proof = self.proof()
        proof['item'] = 'task-one'
        proof['basis']['source_commit'] = source_commit
        path.write_text('```exharness-review\n' + json.dumps(proof) + '\n```\n', encoding='utf-8')

    def test_external_source_anchor_clears_debt_at_exact_commit_only(self):
        with tempfile.TemporaryDirectory() as external:
            path = self.external_anchor_fixture(external)
            source_commit = self.git('rev-parse', 'HEAD')
            self.write_external_anchor(path, source_commit)
            report = self.report()
            self.assertEqual(report['exit_code'], 0, report)
            self.assertEqual(self.group(report)['checkpoint'], source_commit)
            self.assertEqual(self.group(report)['checkpoint_evidence']['authority'], 'exact-source-anchor-statement')
            self.write('src/a.py', 'a=2')
            self.commit('source B')
            self.write('src/a.py', 'a = 1\n')
            self.commit('source A restored')
            report = self.report()
            self.assertEqual(self.group(report)['debt'], 2)
            self.assertEqual(self.group(report)['checkpoint'], source_commit)

    def test_external_anchor_checks_digest_and_keeps_pending_source_debt(self):
        with tempfile.TemporaryDirectory() as external:
            path = self.external_anchor_fixture(external)
            self.write('src/a.py', 'a=2')
            source_commit = self.commit('reviewed source B')
            self.write_external_anchor(path, source_commit)
            report = self.report()
            self.assertEqual(report['exit_code'], 0, report)
            self.assertEqual(self.group(report)['debt'], 0)
            self.write('src/a.py', 'a=3')
            self.assertEqual(self.group(self.report())['debt'], 1)
            self.write_external_anchor(path, source_commit)
            self.assertIn('EXTERNAL_CHECKPOINT_INVALID', self.codes(self.report()))

    def bind_task_plan(self, checklist_name='harness-checklist.json'):
        self.config['coverage']['groups'][0]['record'] = {'item': 'task-one'}
        self.save_config()
        path = 'docs/project-harness/' + checklist_name
        self.write(path, json.dumps({'items': [{'id': 'task-one', 'plan_path': 'docs/module.md'}]}))
        self.commit('bind existing task plan')
        return path

    def review_task_a(self, checklist_name='harness-checklist.json'):
        checklist = self.bind_task_plan(checklist_name)
        proof = self.proof()
        proof['item'] = 'task-one'
        self.put_proof(proof)
        reviewed = self.commit('review task source A')
        return checklist, reviewed

    def move_task_plan(self, checklist):
        self.git('mv', 'docs/module.md', 'docs/moved.md')
        self.write(checklist, json.dumps({'items': [{'id': 'task-one', 'plan_path': 'docs/moved.md'}]}))
        return self.commit('move canonical task plan without changing review')

    def test_task_plan_move_does_not_reset_a_b_a_debt(self):
        checklist, reviewed = self.review_task_a()
        self.write('src/a.py', 'a=2')
        self.commit('source B')
        self.write('src/a.py', 'a = 1\n')
        self.commit('source A restored')
        self.assertEqual(self.group(self.report())['debt'], 2)
        self.move_task_plan(checklist)
        report = self.report()
        self.assertEqual(self.group(report)['debt'], 2, report)
        self.assertEqual(self.group(report)['checkpoint'], reviewed)
        self.assertEqual(self.group(report)['checkpoint_evidence']['path'], 'docs/module.md')
        self.assertNotIn('REVIEW_BINDING_INVALID', self.codes(report))

    def test_moved_stale_task_review_keeps_debt_without_new_binding_error(self):
        checklist, reviewed = self.review_task_a()
        self.write('src/a.py', 'a=2')
        self.commit('source B')
        self.move_task_plan(checklist)
        report = self.report()
        self.assertEqual(self.group(report)['debt'], 1, report)
        self.assertEqual(self.group(report)['checkpoint'], reviewed)
        self.assertNotIn('REVIEW_BINDING_INVALID', self.codes(report))
        self.assertEqual(report['exit_code'], 0)

    def test_task_review_identity_survives_checklist_filename_migration(self):
        checklist, reviewed = self.review_task_a('mvp-checklist.json')
        self.write('src/a.py', 'a=2')
        self.commit('source B')
        self.write('src/a.py', 'a = 1\n')
        self.commit('source A restored')
        self.git('mv', checklist, 'docs/project-harness/harness-checklist.json')
        self.move_task_plan('docs/project-harness/harness-checklist.json')
        report = self.report()
        self.assertEqual(self.group(report)['debt'], 2, report)
        self.assertEqual(self.group(report)['checkpoint'], reviewed)
        self.assertEqual(report['exit_code'], 0)

    def test_history_does_not_read_future_unbound_task_destination(self):
        checklist = self.bind_task_plan()
        proof = self.proof()
        proof['item'] = 'task-one'
        self.write('docs/future.md', '```exharness-review\n' + json.dumps(proof) + '\n```\n')
        self.commit('future file is not canonical task record')
        self.write('src/a.py', 'a=2')
        self.commit('source B')
        self.write(checklist, json.dumps({'items': [{'id': 'task-one', 'plan_path': 'docs/future.md'}]}))
        self.commit('bind previously unbound stale record')
        report = self.report()
        self.assertIn('REVIEW_BINDING_INVALID', self.codes(report))
        self.assertEqual(self.group(report)['checkpoint'], self.anchor)
        self.assertEqual(self.group(report)['debt'], 1)

    def test_bad_historical_item_locator_is_incomplete_after_current_repair(self):
        checklist = self.bind_task_plan()
        self.write(checklist, json.dumps({'items': [{'id': 'task-one', 'plan_path': 'docs/module.md',
                                                   'artifacts': {'plan': 'docs/other.md'}}]}))
        self.commit('ambiguous historical locator')
        self.write(checklist, json.dumps({'items': [{'id': 'task-one', 'plan_path': 'docs/module.md'}]}))
        self.commit('repair current locator')
        report = self.report()
        self.assertIn('HISTORY_INCOMPLETE', self.codes(report))
        self.assertEqual(report['exit_code'], 2)


if __name__ == '__main__':
    unittest.main()
