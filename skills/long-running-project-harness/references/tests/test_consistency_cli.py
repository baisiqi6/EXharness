from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
CLI = SCRIPTS / 'consistency_cli.py'
CONFIG = 'docs/project-harness/harness-config.json'
RECORD = 'docs/project-harness/tasks/task-1/plan.md'
CHECKLIST = 'docs/project-harness/harness-checklist.json'


class ConsistencyCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / '项目 with spaces'
        self.repo.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.write('src/code.py', 'value = 0\n')
        self.write(RECORD, '# Task 1\n\nOriginal plan.\n')
        self.write('other.md', 'Other task.\n')
        self.adopted = self.commit('initial')
        self.config = {'deployment_profile': 'standalone', 'coverage': {
            'version': 1, 'enabled': True, 'adopted_at': self.adopted,
            'source_roots': ['src/**'], 'exclude': [],
            'defaults': {'warn_at': 1, 'block_at': 3},
            'groups': [{'id': 'main', 'sources': ['src/code.py'],
                        'record': {'item': 'task-1'}, 'rules': ['record', 'review']}],
        }}
        self.item = {'id': 'task-1', 'status': 'doing', 'owner': 'worker',
                     'plan_path': RECORD, 'lease': {'owner': 'worker', 'session': 'session-1',
                     'expires_at': '2099-01-01T00:00:00Z'}}
        self.checklist = {'items': [self.item, {'id': 'task-2', 'plan_path': 'other.md'}]}
        self.write_json(CONFIG, self.config)
        self.write_json(CHECKLIST, self.checklist)
        self.base = self.commit('adopt coverage')

    def git(self, *args):
        result = subprocess.run(['git', '-C', str(self.repo), *args],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def write(self, path, body):
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding='utf-8')
        return target

    def write_json(self, path, value):
        return self.write(path, json.dumps(value, ensure_ascii=False) + '\n')

    def commit(self, message):
        self.git('add', '.')
        self.git('commit', '-qm', message)
        return self.git('rev-parse', 'HEAD')

    def cli(self, action='drift', *args):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
        return subprocess.run([sys.executable, str(CLI), action,
                               '--repo', str(self.repo), '--config', CONFIG,
                               '--format', 'json', *args], text=True,
                              capture_output=True, env=env)

    def report(self, action='drift', *args):
        result = self.cli(action, *args)
        try:
            report = json.loads(result.stdout)
        except json.JSONDecodeError:
            self.fail(f'Expected JSON report, got {result.returncode}: {result.stdout} {result.stderr}')
        self.assertEqual(report['exit_code'], result.returncode)
        return report

    def codes(self, report):
        return {finding['code'] for finding in report['findings']}

    def test_json_report_preserves_unicode_paths_on_ascii_pipe(self):
        result = subprocess.run([sys.executable, str(CLI), 'drift', '--repo', str(self.repo),
            '--config', CONFIG, '--format', 'json'], capture_output=True,
            env=dict(os.environ, PYTHONIOENCODING='ascii', PYTHONDONTWRITEBYTECODE='1'))
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report['view']['physical_worktree'], str(self.repo.resolve()))

    def test_text_report_falls_back_safely_on_ascii_pipe(self):
        result = subprocess.run([sys.executable, str(CLI), 'drift', '--repo', str(self.repo),
            '--config', CONFIG, '--format', 'text'], capture_output=True,
            env=dict(os.environ, PYTHONIOENCODING='ascii', PYTHONDONTWRITEBYTECODE='1'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b'View:', result.stdout)
        result.stdout.decode('ascii')

    def ci_args(self, result, integration='fast-forward'):
        return ('--snapshot', 'ci', '--base', self.base, '--head', result,
                '--result', result, '--integration', integration)

    def draft(self, expected=0):
        target = self.repo / 'draft.json'
        report = self.report('reconcile', '--item', 'task-1', '--output', str(target))
        self.assertEqual(report['exit_code'], expected, report)
        return target, json.loads(target.read_text())

    def apply(self, draft, *extra):
        return self.report('reconcile', '--item', 'task-1', '--apply', str(draft),
                           '--actor', 'worker', '--session', 'session-1', '--confirm', *extra)

    def test_four_entries_report_without_writing_runtime_state(self):
        before = self.git('status', '--porcelain')
        for action in ('drift', 'remind'):
            report = self.report(action)
            self.assertEqual(report['exit_code'], 0, report)
        self.assertEqual(self.git('status', '--porcelain'), before)
        self.assertFalse((self.repo / 'docs/project-harness/harness-state.json').exists())

    def test_staged_config_does_not_borrow_unstaged_repair(self):
        self.config['coverage']['enabled'] = False
        self.write_json(CONFIG, self.config)
        self.git('add', CONFIG)
        self.config['coverage']['enabled'] = True
        self.write_json(CONFIG, self.config)
        self.assertNotEqual(self.report('remind')['exit_code'], 0)
        self.assertEqual(self.report('drift')['exit_code'], 0)

    def test_ci_requires_all_trusted_inputs_and_explicit_integration(self):
        report = self.report('remind', '--snapshot', 'ci', '--base', self.base)
        self.assertEqual(report['exit_code'], 2)
        report = self.report('remind', *self.ci_args(self.base, 'unknown'))
        self.assertEqual(report['exit_code'], 2)

    def test_ci_rule_deletion_cannot_erase_business_debt(self):
        self.config['coverage']['groups'][0]['policy'] = {'warn_at': 1, 'block_at': 1}
        self.write_json(CONFIG, self.config)
        self.base = self.commit('strict policy')
        self.write('src/code.py', 'value = 1\n')
        self.config['coverage']['groups'] = []
        self.write_json(CONFIG, self.config)
        tip = self.commit('delete obligations with source change')
        self.assertNotEqual(self.report('remind', *self.ci_args(tip))['exit_code'], 0)

    def test_ci_threshold_relaxation_keeps_base_obligation(self):
        self.config['coverage']['groups'][0]['policy'] = {'warn_at': 1, 'block_at': 1}
        self.write_json(CONFIG, self.config)
        self.base = self.commit('strict policy')
        self.write('src/code.py', 'value = 1\n')
        self.config['coverage']['groups'][0]['policy']['block_at'] = 10
        self.write_json(CONFIG, self.config)
        tip = self.commit('relax threshold')
        self.assertEqual(self.report('remind', *self.ci_args(tip))['exit_code'], 1)

    def test_ci_new_path_and_valid_new_coverage_can_arrive_together(self):
        self.write('src/new.py', 'new_value = 1\n')
        self.config['coverage']['groups'].append({'id': 'new', 'sources': ['src/new.py'],
            'record': {'path': 'other.md'}, 'rules': ['record']})
        self.write_json(CONFIG, self.config)
        tip = self.commit('new code with binding')
        report = self.report('remind', *self.ci_args(tip))
        self.assertEqual(report['exit_code'], 0, report)

    def test_ci_existing_unowned_source_can_gain_valid_coverage(self):
        self.write('src/unowned.py', 'value = 2\n')
        self.base = self.commit('existing governed source without ownership')
        self.config['coverage']['groups'].append({'id': 'unowned', 'sources': ['src/unowned.py'],
            'record': {'path': 'other.md'}, 'rules': ['record']})
        self.write_json(CONFIG, self.config)
        tip = self.commit('bind existing source to its formal record')
        report = self.report('remind', *self.ci_args(tip))
        self.assertEqual(report['exit_code'], 0, report)
        self.assertNotIn('SOURCE_UNCOVERED', self.codes(report))

    def test_ci_existing_unowned_source_still_blocks_incomplete_binding(self):
        self.write('src/unowned.py', 'value = 2\n')
        self.base = self.commit('existing governed source without ownership')
        self.checklist['items'][1]['plan_path'] = str(Path(self.tmp.name) / 'unavailable-plan.md')
        self.write_json(CHECKLIST, self.checklist)
        self.config['coverage']['groups'].append({'id': 'unowned', 'sources': ['src/unowned.py'],
            'record': {'item': 'task-2'}, 'rules': ['record']})
        self.write_json(CONFIG, self.config)
        tip = self.commit('candidate binding lacks required external evidence')
        report = self.report('remind', *self.ci_args(tip))
        self.assertEqual(report['exit_code'], 2, report)
        self.assertIn('SOURCE_UNCOVERED', self.codes(report))
        self.assertIn('RECORD_UNAVAILABLE', self.codes(report))

    def test_ci_fast_forward_counts_real_result_history(self):
        for value in (1, 2, 3):
            self.write('src/code.py', f'value = {value}\n')
            tip = self.commit(f'change {value}')
        report = self.report('remind', *self.ci_args(tip))
        self.assertEqual(report['exit_code'], 1, report)
        self.assertEqual(report['groups'][0]['debt'], 3)

    def test_baseline_requires_explicit_selection_and_output(self):
        report = self.report('baseline', '--base', self.base)
        self.assertEqual(report['exit_code'], 2)
        self.assertFalse((self.repo / 'baseline.json').exists())

    def test_baseline_exports_only_selected_reproducible_old_debt(self):
        self.write('src/code.py', 'value = 1\n')
        tip = self.commit('old debt')
        findings = self.report('drift')['findings']
        debt = next(f for f in findings if f['code'] == 'REVIEW_DEBT')
        output = self.repo / 'baseline.json'
        report = self.report('baseline', '--base', tip, '--fingerprint', debt['fingerprint'],
                             '--output', str(output))
        self.assertEqual(report['exit_code'], 0, report)
        baseline = json.loads(output.read_text())
        self.assertEqual(baseline['origin'], tip)
        self.assertEqual([e['fingerprint'] for e in baseline['entries']], [debt['fingerprint']])
        self.assertFalse((self.repo / 'docs/project-harness/harness-state.json').exists())

    def test_reconcile_draft_is_task_scoped_and_readonly(self):
        original = (self.repo / RECORD).read_bytes()
        path, draft = self.draft()
        self.assertEqual(draft['item'], 'task-1')
        self.assertEqual(draft['record']['path'], RECORD)
        self.assertEqual([g['id'] for g in draft['groups']], ['main'])
        self.assertEqual((self.repo / RECORD).read_bytes(), original)
        self.assertNotIn('done', draft.get('proposed_status', {}))
        self.assertFalse((self.repo / 'docs/project-harness/events.jsonl').exists())

    def test_reconcile_apply_requires_confirmation_and_lease_identity(self):
        path, _ = self.draft()
        before = (self.repo / RECORD).read_bytes()
        result = self.report('reconcile', '--item', 'task-1', '--apply', str(path),
                             '--actor', 'worker', '--session', 'session-1')
        self.assertEqual(result['exit_code'], 2)
        result = self.report('reconcile', '--item', 'task-1', '--apply', str(path),
                             '--actor', 'other', '--session', 'session-1', '--confirm')
        self.assertNotEqual(result['exit_code'], 0)
        self.assertEqual((self.repo / RECORD).read_bytes(), before)

    def test_reconcile_apply_is_idempotent_and_never_changes_lifecycle(self):
        path, _ = self.draft()
        checklist_before = (self.repo / CHECKLIST).read_bytes()
        report = self.apply(path)
        self.assertEqual(report['exit_code'], 0, report)
        once = (self.repo / RECORD).read_bytes()
        self.assertIn(b'exharness-reconcile', once)
        again = self.apply(path)
        self.assertEqual(again['exit_code'], 0, again)
        self.assertEqual((self.repo / RECORD).read_bytes(), once)
        self.assertEqual((self.repo / CHECKLIST).read_bytes(), checklist_before)
        self.assertFalse((self.repo / 'docs/project-harness/events.jsonl').exists())

    def test_reconcile_rejects_concurrent_record_edits(self):
        path, _ = self.draft()
        changed = self.write(RECORD, 'Concurrent owner update.\n').read_bytes()
        self.assertNotEqual(self.apply(path)['exit_code'], 0)
        self.assertEqual((self.repo / RECORD).read_bytes(), changed)

    def test_reconcile_rejects_changed_frozen_source(self):
        path, _ = self.draft()
        original = (self.repo / RECORD).read_bytes()
        self.write('src/code.py', 'value = 99\n')
        self.assertNotEqual(self.apply(path)['exit_code'], 0)
        self.assertEqual((self.repo / RECORD).read_bytes(), original)

    def test_managed_reconcile_never_uses_local_authority(self):
        self.config['deployment_profile'] = 'coordinate-managed'
        self.write_json(CONFIG, self.config)
        path, draft = self.draft(expected=2)
        self.assertEqual(draft['authority'], 'coordinate-managed')
        before = (self.repo / RECORD).read_bytes()
        report = self.apply(path)
        self.assertNotEqual(report['exit_code'], 0)
        self.assertEqual((self.repo / RECORD).read_bytes(), before)
        self.assertFalse((self.repo / 'docs/project-harness/events.jsonl').exists())

    def test_ci_retains_suppressed_old_debt_without_blocking(self):
        self.config['coverage']['groups'][0]['policy'] = {'warn_at': 1, 'block_at': 1}
        self.write_json(CONFIG, self.config)
        self.commit('strict policy')
        self.write('src/code.py', 'value = 1\n')
        origin = self.commit('old debt')
        debt = next(f for f in self.report()['findings'] if f['code'] == 'REVIEW_DEBT')
        output = self.repo / 'baseline.json'
        self.assertEqual(self.report('baseline', '--base', origin, '--fingerprint', debt['fingerprint'],
                         '--output', str(output))['exit_code'], 1)
        self.config['coverage']['baseline'] = 'baseline.json'
        self.write_json(CONFIG, self.config)
        self.base = self.commit('adopt reviewed old debt baseline')
        report = self.report('remind', *self.ci_args(self.base))
        self.assertEqual(report['exit_code'], 0, report)
        self.assertTrue(any(f.get('suppressed') for f in report['findings']))

    def test_ci_candidate_cannot_baseline_same_pr_business_change(self):
        self.config['coverage']['groups'][0]['policy'] = {'warn_at': 1, 'block_at': 1}
        self.write_json(CONFIG, self.config)
        self.base = self.commit('strict policy')
        self.write('src/code.py', 'value = 1\n')
        origin = self.commit('new business debt')
        debt = next(f for f in self.report()['findings'] if f['code'] == 'REVIEW_DEBT')
        output = self.repo / 'baseline.json'
        self.assertEqual(self.report('baseline', '--base', origin, '--fingerprint', debt['fingerprint'],
                         '--output', str(output))['exit_code'], 1)
        self.config['coverage']['baseline'] = 'baseline.json'
        self.write_json(CONFIG, self.config)
        tip = self.commit('attempt concurrent baseline')
        report = self.report('remind', *self.ci_args(tip))
        self.assertEqual(report['exit_code'], 1, report)

    def test_ci_missing_new_group_record_still_blocks(self):
        self.write('src/new.py', 'value = 2\n')
        self.config['coverage']['groups'].append({'id': 'new', 'sources': ['src/new.py'],
            'record': {'path': 'missing.md'}, 'rules': ['record']})
        self.write_json(CONFIG, self.config)
        tip = self.commit('invalid new binding')
        self.assertEqual(self.report('remind', *self.ci_args(tip))['exit_code'], 1)

    def test_ci_merge_counts_one_actual_result_transition(self):
        branch = self.git('branch', '--show-current')
        self.git('checkout', '-qb', 'feature')
        for value in (1, 2, 3):
            self.write('src/code.py', f'value = {value}\n')
            head = self.commit(f'feature {value}')
        self.git('checkout', '-q', branch)
        self.git('merge', '--no-ff', '-qm', 'integrate feature', head)
        result = self.git('rev-parse', 'HEAD')
        report = self.report('remind', '--snapshot', 'ci', '--base', self.base,
                             '--head', head, '--result', result, '--integration', 'merge')
        self.assertEqual(report['exit_code'], 0, report)
        self.assertEqual(report['groups'][0]['debt'], 1)

    def test_reconcile_draft_output_cannot_replace_checklist(self):
        original = (self.repo / CHECKLIST).read_bytes()
        report = self.report('reconcile', '--item', 'task-1', '--output', str(self.repo / CHECKLIST))
        self.assertEqual(report['exit_code'], 2)
        self.assertEqual((self.repo / CHECKLIST).read_bytes(), original)

    def test_reconcile_source_overlapping_temporary_lock_can_apply(self):
        self.config['coverage']['source_roots'] = ['src/**', 'docs/project-harness/tasks/**']
        self.config['coverage']['groups'][0]['sources'].append('docs/project-harness/tasks/**')
        self.config['coverage']['exclude'] = [RECORD]
        self.write_json(CONFIG, self.config)
        self.write('docs/project-harness/tasks/task-1/helper.py', 'helper = 1\n')
        path, _ = self.draft()
        self.assertEqual(self.apply(path)['exit_code'], 0)

    def append_review(self, group_id='main'):
        group = next(g for g in self.report()['groups'] if g['id'] == group_id)
        proof = {'version': 1, 'group': group_id, 'rule': 'review/v1',
                 'scope_digest': group['scope_digest'], 'source_digest': group['source_digest'],
                 'decision': 'reviewed-no-doc-change', 'actor': 'reviewer',
                 'reason': 'The changed value preserves the documented interface.',
                 'basis': {'parent': self.git('rev-parse', 'HEAD'),
                           'review': 'Checked changed source and existing acceptance criteria.'},
                 'item': 'task-1'}
        self.write(RECORD, (self.repo / RECORD).read_text() +
                   '\n```exharness-review\n' + json.dumps(proof) + '\n```\n')

    def test_ci_fix_and_prune_old_baseline_together(self):
        self.config['coverage']['groups'][0]['policy'] = {'warn_at': 1, 'block_at': 1}
        self.write_json(CONFIG, self.config)
        self.commit('strict policy')
        self.write('src/code.py', 'value = 1\n')
        origin = self.commit('old debt')
        debt = next(f for f in self.report()['findings'] if f['code'] == 'REVIEW_DEBT')
        output = self.repo / 'baseline.json'
        self.assertEqual(self.report('baseline', '--base', origin, '--fingerprint', debt['fingerprint'],
                         '--output', str(output))['exit_code'], 1)
        self.config['coverage']['baseline'] = 'baseline.json'
        self.write_json(CONFIG, self.config)
        self.base = self.commit('adopt old baseline')
        self.write('src/code.py', 'value = 2\n')
        self.append_review()
        self.config['coverage'].pop('baseline')
        self.write_json(CONFIG, self.config)
        output.unlink()
        tip = self.commit('review latest source and prune baseline')
        report = self.report('remind', *self.ci_args(tip))
        self.assertEqual(report['exit_code'], 0, report)

    def test_ci_merge_preserves_proven_review_from_pr_head(self):
        self.config['coverage']['groups'][0]['policy'] = {'warn_at': 1, 'block_at': 1}
        self.write_json(CONFIG, self.config)
        self.base = self.commit('strict policy')
        branch = self.git('branch', '--show-current')
        self.git('checkout', '-qb', 'feature')
        self.write('src/code.py', 'value = 1\n')
        self.commit('unreviewed source')
        self.write('src/code.py', 'value = 2\n')
        self.append_review()
        head = self.commit('source and scoped review')
        self.git('checkout', '-q', branch)
        self.git('merge', '--no-ff', '-qm', 'integrate reviewed feature', head)
        result = self.git('rev-parse', 'HEAD')
        report = self.report('remind', '--snapshot', 'ci', '--base', self.base,
                             '--head', head, '--result', result, '--integration', 'merge')
        self.assertEqual(report['exit_code'], 0, report)
        self.assertEqual(report['groups'][0]['debt'], 0)

    def test_reconcile_rechecks_idempotent_source_after_previous_apply(self):
        path, _ = self.draft()
        self.assertEqual(self.apply(path)['exit_code'], 0)
        once = (self.repo / RECORD).read_bytes()
        self.write('src/code.py', 'value = 42\n')
        self.assertEqual(self.apply(path)['exit_code'], 1)
        self.assertEqual((self.repo / RECORD).read_bytes(), once)

    def test_reconcile_draft_cannot_choose_another_tasks_record(self):
        path, draft = self.draft()
        draft['record']['path'] = 'other.md'
        # Even a self-consistent edited draft cannot choose a new authority.
        import hashlib
        payload = dict(draft)
        payload.pop('id')
        draft['id'] = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False).encode()).hexdigest()
        path.write_text(json.dumps(draft))
        before = (self.repo / 'other.md').read_bytes()
        self.assertEqual(self.apply(path)['exit_code'], 1)
        self.assertEqual((self.repo / 'other.md').read_bytes(), before)

    def test_external_reconcile_draft_rejects_live_record_different_from_fixed_evidence(self):
        external = Path(self.tmp.name) / 'private-records'
        external.mkdir()
        def external_git(*args):
            result = subprocess.run(['git', '-C', str(external), *args], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout.strip()
        external_git('init', '-q')
        external_git('config', 'user.name', 'Fixture')
        external_git('config', 'user.email', 'fixture@example.invalid')
        plan = external / 'plan.md'
        plan.write_text('Trusted frozen plan.\n')
        external_git('add', '.')
        external_git('commit', '-qm', 'fixed evidence')
        revision = external_git('rev-parse', 'HEAD')
        blob = external_git('rev-parse', 'HEAD:plan.md')
        self.item['plan_path'] = str(plan)
        self.write_json(CHECKLIST, self.checklist)
        manifest = self.write_json('manifest.json', {'version': 1, 'records': [
            {'locator': str(plan), 'repo': str(external), 'revision': revision, 'path': 'plan.md', 'blob': blob}]})
        plan.write_text('New live plan differs from fixed evidence.\n')
        output = self.repo / 'draft.json'
        report = self.report('reconcile', '--item', 'task-1', '--external-records', str(manifest),
                             '--output', str(output))
        self.assertEqual(report['exit_code'], 2)
        self.assertFalse(output.exists())

    def test_managed_draft_does_not_hide_unrelated_missing_evidence(self):
        self.config['deployment_profile'] = 'coordinate-managed'
        self.item['plan_path'] = str(Path(self.tmp.name) / 'absent-private-plan.md')
        self.write_json(CONFIG, self.config)
        self.write_json(CHECKLIST, self.checklist)
        output = self.repo / 'draft.json'
        report = self.report('reconcile', '--item', 'task-1', '--output', str(output))
        self.assertEqual(report['exit_code'], 2)
        self.assertNotIn('draft', report)
        self.assertFalse(output.exists())

    def test_worktree_view_separates_head_index_and_unstaged_paths(self):
        self.write('src/code.py', 'value = 1\n')
        self.git('add', 'src/code.py')
        self.write('src/new.py', 'new_value = 2\n')
        self.write('notes.txt', 'Outside declared source.\n')
        report = self.report('drift')
        view = report.get('view', {})
        self.assertEqual(view.get('head'), self.base)
        self.assertEqual(view.get('physical_worktree'), str(self.repo.resolve()))
        self.assertEqual(view.get('staged_paths'), ['src/code.py'])
        self.assertEqual(view.get('unstaged_paths'), ['notes.txt', 'src/new.py'])
        self.assertEqual(view.get('outside_governed_paths'), ['notes.txt'])
        self.assertNotEqual(view.get('index_identity'), view.get('worktree_identity'))

    def test_staged_view_binds_head_and_index_without_claiming_unstaged_read(self):
        self.write('src/code.py', 'value = 1\n')
        self.git('add', 'src/code.py')
        self.write('notes.txt', 'Not part of staged snapshot.\n')
        view = self.report('remind').get('view', {})
        self.assertEqual(view.get('head'), self.base)
        self.assertEqual(view.get('staged_paths'), ['src/code.py'])
        self.assertIsNone(view.get('unstaged_paths'))
        self.assertEqual(view.get('outside_governed_paths'), [])

    def test_view_identifies_selected_physical_worktree(self):
        other = Path(self.tmp.name) / '另一个 worktree'
        self.git('worktree', 'add', '-qb', 'other-task', str(other))
        self.write('notes.txt', 'Changes belong only to the original worktree.\n')
        view = self.report('drift', '--repo', str(other)).get('view', {})
        self.assertEqual(view.get('physical_worktree'), str(other.resolve()))
        self.assertEqual(view.get('unstaged_paths'), [])

    def test_ci_cannot_flip_managed_authority_to_standalone(self):
        self.config['deployment_profile'] = 'coordinate-managed'
        self.write_json(CONFIG, self.config)
        self.base = self.commit('managed authority')
        self.config['deployment_profile'] = 'standalone'
        self.write_json(CONFIG, self.config)
        self.write('src/code.py', 'value = 1\n')
        tip = self.commit('attempt authority downgrade')
        report = self.report('remind', *self.ci_args(tip))
        self.assertEqual(report['exit_code'], 2, report)
        self.assertIn('MANAGED_AUTHORITY_UNVERIFIED', self.codes(report))

    def test_ci_malformed_candidate_baseline_stays_structured(self):
        self.config['coverage']['baseline'] = 'baseline.json'
        self.write_json(CONFIG, self.config)
        self.write_json('baseline.json', {'version': 1, 'origin': self.base, 'entries': ['bad']})
        tip = self.commit('malformed candidate baseline')
        report = self.report('remind', *self.ci_args(tip))
        self.assertNotEqual(report['exit_code'], 0)
        self.assertIn('BASELINE_INVALID', self.codes(report))

    def test_ci_malformed_trusted_baseline_stays_structured(self):
        self.config['coverage']['baseline'] = 'baseline.json'
        self.write_json(CONFIG, self.config)
        self.write_json('baseline.json', {'version': 1, 'origin': self.base, 'entries': ['bad']})
        self.base = self.commit('malformed trusted baseline')
        report = self.report('remind', *self.ci_args(self.base))
        self.assertNotEqual(report['exit_code'], 0)
        self.assertIn('BASELINE_INVALID', self.codes(report))

    def test_rehashed_draft_cannot_forge_observed_debt(self):
        import hashlib
        path, draft = self.draft()
        draft['groups'][0]['debt'] = 99
        payload = dict(draft)
        payload.pop('id')
        draft['id'] = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False).encode()).hexdigest()
        path.write_text(json.dumps(draft))
        original = (self.repo / RECORD).read_bytes()
        report = self.apply(path)
        self.assertEqual(report['exit_code'], 1, report)
        self.assertEqual((self.repo / RECORD).read_bytes(), original)

    def test_rehashed_draft_cannot_forge_observed_findings(self):
        import hashlib
        path, draft = self.draft()
        draft['findings'] = [{'code': 'FAKE_APPROVED', 'severity': 'warning'}]
        payload = dict(draft)
        payload.pop('id')
        draft['id'] = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False).encode()).hexdigest()
        path.write_text(json.dumps(draft))
        original = (self.repo / RECORD).read_bytes()
        report = self.apply(path)
        self.assertEqual(report['exit_code'], 1, report)
        self.assertEqual((self.repo / RECORD).read_bytes(), original)

    def test_item_uses_posix_snapshot_keys_on_windows(self):
        from pathlib import PureWindowsPath
        from unittest import mock
        sys.path.insert(0, str(SCRIPTS))
        try:
            import consistency_cli
            from consistency_snapshot import GitRepo
        finally:
            sys.path.remove(str(SCRIPTS))
        repo = GitRepo(self.repo)
        snapshot = repo.worktree()
        # Emulate only native Windows path spelling; all snapshot bytes are real.
        with mock.patch.object(consistency_cli, 'Path', PureWindowsPath), mock.patch.object(
                consistency_cli, 'resolve_item_plan', return_value=repo.root / RECORD):
            item, checklist, _, record, _ = consistency_cli._item(repo, snapshot, CONFIG, 'task-1')
        self.assertEqual(item['id'], 'task-1')
        self.assertEqual(checklist, CHECKLIST)
        self.assertEqual(record, RECORD)

    def test_baseline_export_preserves_unrelated_blocking_findings(self):
        self.write('src/code.py', 'value = 1\n')
        self.write('src/uncovered.py', 'value = 2\n')
        origin = self.commit('debt plus unrelated structural error')
        debt = next(f for f in self.report()['findings'] if f['code'] == 'REVIEW_DEBT')
        output = self.repo / 'baseline.json'
        report = self.report('baseline', '--base', origin, '--fingerprint', debt['fingerprint'],
                             '--output', str(output))
        self.assertEqual(report['exit_code'], 1, report)
        self.assertEqual(report['observed_exit_code'], 1)
        self.assertIn('SOURCE_UNCOVERED', self.codes(report))
        self.assertTrue(output.is_file())

    def test_additive_group_with_own_review_can_share_existing_plan(self):
        self.config['coverage']['groups'].append({'id': 'new', 'sources': ['src/new.py'],
            'record': {'item': 'task-1'}, 'rules': ['record', 'review'],
            'policy': {'warn_at': 1, 'block_at': 1}})
        self.write_json(CONFIG, self.config)
        self.write('src/new.py', 'new_value = 2\n')
        self.append_review('new')
        tip = self.commit('add new reviewed scope in shared formal record')
        report = self.report('remind', *self.ci_args(tip))
        self.assertEqual(report['exit_code'], 0, report)

    def test_squash_checkpoint_survives_without_original_branch(self):
        branch = self.git('branch', '--show-current')
        self.git('checkout', '-qb', 'temporary-feature')
        self.write('src/code.py', 'value = 1\n')
        self.commit('feature first source transition')
        self.write('src/code.py', 'value = 2\n')
        self.append_review()
        self.commit('feature source and review')
        self.git('checkout', '-q', branch)
        self.git('merge', '--squash', 'temporary-feature')
        self.git('commit', '-qm', 'squashed integration')
        self.git('branch', '-D', 'temporary-feature')
        report = self.report('drift')
        self.assertEqual(report['exit_code'], 0, report)
        self.assertEqual(report['groups'][0]['debt'], 0)

    def test_reconcile_output_cannot_replace_another_tasks_canonical_plan(self):
        other = self.repo / 'other.md'
        original = other.read_bytes()
        report = self.report('reconcile', '--item', 'task-1', '--output', str(other))
        self.assertEqual(report['exit_code'], 1, report)
        self.assertIn('OUTPUT_EXISTS', self.codes(report))
        self.assertEqual(other.read_bytes(), original)

    def test_managed_draft_output_cannot_replace_another_canonical_plan(self):
        self.config['deployment_profile'] = 'coordinate-managed'
        self.write_json(CONFIG, self.config)
        other = self.repo / 'other.md'
        original = other.read_bytes()
        report = self.report('reconcile', '--item', 'task-1', '--output', str(other))
        self.assertNotEqual(report['exit_code'], 0)
        self.assertIn('OUTPUT_EXISTS', self.codes(report))
        self.assertEqual(other.read_bytes(), original)

    def test_baseline_output_cannot_replace_original_document(self):
        self.write('src/code.py', 'value = 1\n')
        origin = self.commit('review debt')
        debt = next(f for f in self.report()['findings'] if f['code'] == 'REVIEW_DEBT')
        original = (self.repo / RECORD).read_bytes()
        report = self.report('baseline', '--base', origin, '--fingerprint', debt['fingerprint'],
                             '--output', str(self.repo / RECORD))
        self.assertEqual(report['exit_code'], 1, report)
        self.assertIn('OUTPUT_EXISTS', self.codes(report))
        self.assertEqual((self.repo / RECORD).read_bytes(), original)

    def test_repeated_identical_draft_output_is_noop(self):
        path, _ = self.draft()
        original = path.read_bytes()
        modified = path.stat().st_mtime_ns
        report = self.report('reconcile', '--item', 'task-1', '--output', str(path))
        self.assertEqual(report['exit_code'], 0, report)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(path.stat().st_mtime_ns, modified)

    def test_repeated_identical_baseline_output_is_noop(self):
        self.write('src/code.py', 'value = 1\n')
        origin = self.commit('review debt')
        debt = next(f for f in self.report()['findings'] if f['code'] == 'REVIEW_DEBT')
        output = self.repo / 'baseline-proposal.json'
        args = ('--base', origin, '--fingerprint', debt['fingerprint'], '--output', str(output))
        self.assertEqual(self.report('baseline', *args)['exit_code'], 0)
        original = output.read_bytes()
        modified = output.stat().st_mtime_ns
        self.assertEqual(self.report('baseline', *args)['exit_code'], 0)
        self.assertEqual(output.read_bytes(), original)
        self.assertEqual(output.stat().st_mtime_ns, modified)

    def test_contract_reports_capability_without_enabling_hooks(self):
        report = self.report('contract')
        self.assertEqual(report['exit_code'], 0)
        self.assertEqual(report['contract']['version'], 1)
        self.assertEqual(report['contract']['hooks'], 'not-inspected')
        self.assertEqual(report['contract']['required_ci'], 'not-inspected')


if __name__ == '__main__':
    unittest.main()
