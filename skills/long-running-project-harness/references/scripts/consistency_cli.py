#!/usr/bin/env python3
"""Read-only consistency entry points and explicitly confirmed reconciliation."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

from consistency_core import CoverageError, evaluate, load_coverage
from consistency_snapshot import GitRepo, SnapshotError, match_path
from harness_common import active_lease, append_observation_bytes, resolve_item_plan


class CliError(Exception):
    def __init__(self, message, *, code='CHECK_INCOMPLETE', exit_code=2):
        super().__init__(message)
        self.code = code
        self.exit_code = exit_code


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode('utf-8')).hexdigest()


def _finding(code, message, *, severity='incomplete', evidence=None, path=None):
    evidence = evidence or {}
    return {'code': code, 'severity': severity, 'group': None, 'path': path,
            'evidence': evidence, 'fingerprint': _digest([code, path, evidence]),
            'message': message, 'next_action': 'Resolve the reported inputs and rerun the same check.'}


def _finish(report):
    severities = {finding['severity'] for finding in report.get('findings', []) if not finding.get('suppressed')}
    report['exit_code'] = 2 if 'incomplete' in severities else 1 if 'error' in severities else 0
    return report


def _read_json(snapshot, path):
    content = snapshot.read(path)
    if content is None:
        raise CliError(f'Required snapshot file is missing: {path}')
    data = json.loads(content)
    if not isinstance(data, dict):
        raise CliError(f'Expected a JSON object: {path}')
    return data


def _config_path(repo, supplied):
    if supplied:
        path = Path(supplied)
        if path.is_absolute():
            try:
                return path.relative_to(repo.root).as_posix()
            except ValueError:
                raise CliError('The coverage config must belong to the selected repository snapshot.')
        if '..' in path.parts:
            raise CliError('The config path must not contain parent traversal.')
        return path.as_posix()
    # Installed scripts have a rendered project harness root. Source templates
    # remain usable without assuming this repository has adopted coverage.
    rendered = '{{HARNESS_ROOT}}'
    if '{{' not in rendered:
        return _config_path(repo, str(Path(rendered) / 'harness-config.json'))
    installed = Path(__file__).resolve().parent.parent / 'harness-config.json'
    try:
        relative = installed.relative_to(repo.root).as_posix()
    except ValueError:
        relative = ''
    if relative and installed.is_file():
        return relative
    return 'docs/project-harness/harness-config.json'


def _external(args):
    if args.external_records is None:
        return None
    with Path(args.external_records).open('rb') as handle:
        manifest = json.load(handle)
    if not isinstance(manifest, dict):
        raise CliError('External evidence manifest must be a JSON object.')
    return manifest


def _coverage(snapshot, config_path):
    return load_coverage(_read_json(snapshot, config_path))


def _fixed_hex(value, lengths):
    return isinstance(value, str) and len(value) in lengths and all(c in '0123456789abcdef' for c in value)


def _baseline(snapshot, coverage):
    path = coverage.get('baseline')
    if not path:
        return None
    baseline = _read_json(snapshot, path)
    if set(baseline) != {'version', 'origin', 'entries'} or type(baseline['version']) is not int or baseline['version'] != 1:
        raise CoverageError('Invalid baseline schema/version.')
    if not _fixed_hex(baseline['origin'], (40, 64)) or not isinstance(baseline['entries'], list):
        raise CoverageError('Baseline requires a fixed origin and an entries list.')
    seen = set()
    keys = {'fingerprint', 'code', 'group', 'path', 'evidence'}
    for entry in baseline['entries']:
        if not isinstance(entry, dict) or set(entry) != keys:
            raise CoverageError('Each baseline entry must be a complete finding object.')
        fingerprint = entry['fingerprint']
        if not _fixed_hex(fingerprint, (64,)) or fingerprint in seen:
            raise CoverageError('Baseline fingerprints must be unique SHA-256 values.')
        seen.add(fingerprint)
        if (not isinstance(entry['code'], str) or not isinstance(entry['group'], str)
                or not (entry['path'] is None or isinstance(entry['path'], str))
                or not isinstance(entry['evidence'], dict)):
            raise CoverageError('Baseline finding fields have invalid types.')
    return baseline


def _baseline_entry(finding):
    return {key: finding.get(key) for key in ('fingerprint', 'code', 'group', 'path', 'evidence')}


def _ci(repo, args, config_path, external):
    required = ('base', 'head', 'result', 'integration')
    missing = [name for name in required if not getattr(args, name)]
    if missing:
        raise CliError('CI requires explicit trusted inputs: ' + ', '.join('--' + name for name in missing))
    if args.integration == 'unknown':
        raise CliError('The actual integration mode is unknown; provide reproducible integration details.')
    base = repo.snapshot(args.base)
    head = repo.snapshot(args.head)
    result = repo.snapshot(args.result)
    if not base.revision or not head.revision:
        raise CliError('CI base and head must resolve to commits with available history.')
    mode = args.integration
    if mode in ('fast-forward', 'rebase'):
        tip = result.revision or head.revision
        if repo.snapshot(tip).tree != result.tree or not repo.is_ancestor(base.revision, tip):
            raise CliError('The result tree cannot be reproduced from the supplied integration ancestry.')
        repo.first_parent(base.revision, tip)
        if mode == 'fast-forward' and (tip != head.revision or head.tree != result.tree):
            raise CliError('Fast-forward must test the supplied head and its actual ancestry.')
        history_tip = tip
    else:
        if result.revision:
            if repo.parent(result.revision) != base.revision:
                raise CliError('Merge/squash results must identify one actual transition from the trusted base.')
            if mode in ('merge', 'merge-group') and not repo.is_ancestor(head.revision, result.revision):
                raise CliError('The tested merge result does not contain the supplied head.')
            history_tip = result.revision
        else:
            # An explicitly supplied result tree is a single pending transition
            # over the fixed base. The core counts only groups it actually changes.
            history_tip = base.revision
    base_config = _read_json(base, config_path)
    authority = base_config.get('deployment_profile', 'standalone')
    policy = load_coverage(base_config)
    locked = evaluate(repo, result, config_path, policy=policy, history_tip=history_tip,
                      external_records=external, apply_baseline=False,
                      authority_profile=authority)
    candidate = evaluate(repo, result, config_path, history_tip=history_tip,
                         external_records=external, apply_baseline=True)
    findings = []
    candidate_groups = candidate.get('groups', [])
    invalid_groups = {f.get('group') for f in candidate.get('findings', [])
                      if f['severity'] in ('error', 'incomplete') and not f.get('suppressed')}
    newly_covered = {path for group in candidate_groups if group.get('record_digest')
                     and group.get('id') not in invalid_groups
                     for path in group.get('covered_paths', [])}
    locked_findings = [f for f in locked.get('findings', [])
                       if not (f['code'] == 'SOURCE_UNCOVERED' and f.get('path') in newly_covered)]
    # Candidate baseline changes only suppress reproducible old evidence. The
    # candidate evaluation also rejects stale entries, so fix+prune is allowed.
    try:
        candidate_policy = _coverage(result, config_path)
        candidate_baseline = _baseline(result, candidate_policy)
        base_baseline = _baseline(base, policy)
        trusted_entries = {e.get('fingerprint'): e for e in (base_baseline or {}).get('entries', [])}
        proposed_entries = (candidate_baseline or {}).get('entries', [])
        origin = (candidate_baseline or {}).get('origin')
        reproducible = None
        if proposed_entries and (not origin or not repo.is_ancestor(origin, base.revision)):
            findings.append(_finding('BASELINE_UNTRUSTED_ORIGIN',
                'Candidate baseline origin is not a trusted ancestor of the fixed base.', severity='error'))
        else:
            allowed = set()
            for entry in proposed_entries:
                fingerprint = entry.get('fingerprint')
                if fingerprint in trusted_entries and entry == trusted_entries[fingerprint]:
                    allowed.add(fingerprint)
                    continue
                if reproducible is None:
                    base_report = evaluate(repo, base, config_path, history_tip=base.revision,
                                           external_records=external, apply_baseline=False)
                    reproducible = {f['fingerprint']: _baseline_entry(f)
                                    for f in base_report['findings'] if f['code'] == 'REVIEW_DEBT'}
                if reproducible.get(fingerprint) == entry:
                    allowed.add(fingerprint)
                else:
                    findings.append(_finding('BASELINE_EXPANSION',
                        'A candidate baseline entry does not reproduce at the fixed trusted base.',
                        severity='error', evidence={'fingerprint': fingerprint}))
            locked_findings = [f for f in locked_findings
                               if not (f['code'] == 'REVIEW_DEBT' and f['fingerprint'] in allowed)]
    except CoverageError as exc:
        findings.append(_finding('BASELINE_INVALID', str(exc), severity='error'))
    except (CliError, SnapshotError, ValueError, TypeError) as exc:
        findings.append(_finding('BASELINE_CHECK_INCOMPLETE', str(exc)))
    # Keep all errors and incomplete causes while deduplicating identical views.
    unique = {}
    for finding in locked_findings + candidate.get('findings', []) + findings:
        unique.setdefault((finding['fingerprint'], finding['severity']), finding)
    return _finish({'findings': list(unique.values()), 'groups': locked.get('groups', []),
        'candidate_groups': candidate_groups, 'snapshot': candidate.get('snapshot', {}),
        'view': {'kind': 'ci', 'base': base.revision, 'head': head.revision,
                 'result': result.identity, 'integration': mode,
                 'history_tip': history_tip, 'evaluations': ['trusted-base', 'candidate']}}), result


def _scope_view(report, snapshot, changed):
    coverage = report.get('coverage')
    if coverage is None:
        return {'outside_governed_paths': None, 'outside_governed_count': None,
                'excluded_paths': None}
    outside = sorted(path for path in changed if not match_path(path, coverage['source_roots']))
    excluded = sorted(path for path in changed if match_path(path, coverage.get('exclude', [])))
    return {'outside_governed_paths': outside, 'outside_governed_count': len(outside),
            'excluded_paths': excluded}


def _selected(repo, args, config_path, external):
    if args.snapshot == 'ci':
        report, snapshot = _ci(repo, args, config_path, external)
        base = repo.snapshot(report['view']['base'])
        report['view']['physical_worktree'] = str(repo.root)
        # Candidate coverage cannot silently redefine the report of the locked
        # base obligations; show both scope views when policy changes.
        report['coverage'] = _coverage(base, config_path)
        report['view'].update(_scope_view(report, snapshot, base.changed(snapshot)))
        return report, snapshot
    head = repo.head()
    committed = repo.snapshot(head)
    index = repo.index()
    snapshot = index if args.snapshot == 'staged' else repo.worktree()
    if args.snapshot == 'worktree' and repo.index().identity != index.identity:
        raise CliError('The Git index changed across the selected worktree snapshot.')
    if repo.head() != head:
        raise CliError('HEAD changed while selecting the frozen source view.')
    report = evaluate(repo, snapshot, config_path, history_tip=head, external_records=external)
    if repo.index().identity != index.identity:
        raise CliError('The Git index changed while evaluating the frozen source view.')
    if repo.head() != head:
        raise CliError('HEAD changed while evaluating the frozen source view.')
    changed = committed.changed(snapshot)
    report['view'] = {'kind': args.snapshot, 'physical_worktree': str(repo.root), 'head': head,
                      'head_identity': committed.identity, 'index_identity': index.identity,
                      'worktree_identity': snapshot.identity if args.snapshot == 'worktree' else None,
                      'staged_paths': committed.changed(index),
                      'unstaged_paths': index.changed(snapshot) if args.snapshot == 'worktree' else None}
    report['view'].update(_scope_view(report, snapshot, changed))
    return report, snapshot


def _write_output(path, data):
    path = Path(path)
    payload = (json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode('utf-8')
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if path.is_file() and path.read_bytes() == payload:
            return
        raise CliError('Output already exists with different content; choose a new review artifact path.',
                       code='OUTPUT_EXISTS', exit_code=1)
    with os.fdopen(fd, 'wb') as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _make_baseline(repo, args, config_path, external):
    if not args.base or not args.fingerprint or not args.output:
        raise CliError('baseline requires --base, each explicit --fingerprint, and --output; it never accepts all findings.')
    snapshot = repo.snapshot(args.base)
    if not snapshot.revision:
        raise CliError('A baseline requires a trusted commit, not an unanchored tree.')
    report = evaluate(repo, snapshot, config_path, history_tip=snapshot.revision,
                      external_records=external, apply_baseline=False)
    if report['exit_code'] == 2:
        return report
    available = {f['fingerprint']: f for f in report['findings'] if f['code'] == 'REVIEW_DEBT'}
    selected = sorted(set(args.fingerprint))
    unknown = [fingerprint for fingerprint in selected if fingerprint not in available]
    if unknown:
        raise CliError('Selected findings are absent or cannot be baselined: ' + ', '.join(unknown),
                       code='BASELINE_SELECTION_INVALID', exit_code=1)
    baseline = {'version': 1, 'origin': snapshot.revision,
                'entries': [_baseline_entry(available[fingerprint]) for fingerprint in selected]}
    _write_output(args.output, baseline)
    report.update(baseline=baseline, output=str(Path(args.output)), baseline_exported=True,
                  observed_exit_code=report['exit_code'])
    return report


def _item(repo, snapshot, config_path, item_id):
    root = Path(config_path).parent
    candidates = [(root / name).as_posix() for name in ('harness-checklist.json', 'mvp-checklist.json')
                  if snapshot.read((root / name).as_posix()) is not None]
    if len(candidates) != 1:
        raise CliError('Reconcile requires exactly one original task checklist authority.')
    checklist_path = candidates[0]
    checklist = _read_json(snapshot, checklist_path)
    items = [item for item in checklist.get('items', [])
             if isinstance(item, dict) and item.get('id') == item_id]
    if len(items) != 1:
        raise CliError(f'Task {item_id!r} is absent or ambiguous in the selected checklist.')
    item = items[0]
    plan = resolve_item_plan(item, require_exists=False, project=repo.root,
                             harness=repo.root / root)
    try:
        path = plan.relative_to(repo.root).as_posix()
        record = snapshot.read(path)
    except ValueError:
        if snapshot.kind != 'worktree':
            raise CliError('External task records require a verified caller manifest outside the local worktree view.')
        path = str(plan)
        record = plan.read_bytes()
    if record is None:
        raise CliError('The original canonical task record is unavailable.')
    return item, checklist_path, plan, path, record


def _source_token(repo, snapshot, config_path, checklist_path, groups, head):
    # Exclude the record preimage here: our own observation append must permit
    # idempotent reapply, while its separately bound preimage protects edits.
    return _digest({'repo': str(repo.root), 'head': head, 'snapshot': snapshot.kind,
                    'config': hashlib.sha256(snapshot.read(config_path)).hexdigest(),
                    'checklist': hashlib.sha256(snapshot.read(checklist_path)).hexdigest(),
                    'groups': [{key: group.get(key) for key in ('id', 'scope_digest', 'source_digest')}
                               for group in groups]})


def _make_draft(repo, args, config_path, report, snapshot):
    if not args.item:
        raise CliError('reconcile requires an explicit --item.')
    config = _read_json(snapshot, config_path)
    profile = config.get('deployment_profile', 'standalone')
    gaps = {f['code'] for f in report.get('findings', []) if f['severity'] == 'incomplete'}
    if report['exit_code'] == 2 and not (profile == 'coordinate-managed' and gaps == {'MANAGED_AUTHORITY_UNVERIFIED'}):
        return None
    if profile not in ('standalone', 'coordinate-managed'):
        raise CliError('Unknown task authority; an explicit supported deployment profile is required.')
    item, checklist_path, plan, record_path, original = _item(repo, snapshot, config_path, args.item)
    coverage = _coverage(snapshot, config_path)
    ids = {group['id'] for group in coverage['groups'] if group['record'].get('item') == args.item}
    groups = [group for group in report.get('groups', []) if group.get('id') in ids]
    if not groups:
        raise CliError('The selected task has no unambiguous declared coverage group.')
    record_digest = hashlib.sha256(original).hexdigest()
    if any(group.get('record_digest') != record_digest for group in groups):
        raise CliError('The original record differs from the frozen evaluated evidence; regenerate a consistent source view.')
    head = report['view']['head']
    draft = {'version': 1, 'kind': 'exharness-reconcile', 'item': args.item,
             'authority': profile, 'repo': str(repo.root), 'config': config_path,
             'snapshot': args.snapshot, 'head': head,
             'record': {'path': record_path, 'preimage': hashlib.sha256(original).hexdigest()},
             'source_token': _source_token(repo, snapshot, config_path, checklist_path, groups, head),
             'groups': groups, 'findings': [f for f in report['findings'] if f.get('group') in ids],
             'next_action': ('Use the original Coordinate controlled entry point.' if profile == 'coordinate-managed'
                             else 'Review observations, then explicitly apply to the original task record; revalidate affected packet bindings.')}
    draft['id'] = _digest(draft)
    return draft


def _append_block(draft, actor, session):
    observation = {'version': 1, 'id': draft['id'], 'item': draft['item'],
                   'actor': actor, 'session': session, 'source_token': draft['source_token'],
                   'groups': [{key: group.get(key) for key in
                               ('id', 'scope_digest', 'source_digest', 'debt', 'checkpoint')}
                              for group in draft['groups']],
                   'findings': sorted({f['code'] for f in draft['findings']})}
    return ('\n\n```exharness-reconcile\n' + json.dumps(observation, ensure_ascii=False,
            sort_keys=True, indent=2) + '\n```\n').encode('utf-8')


def _apply_draft(repo, args, config_path, external):
    if not (args.confirm and args.actor and args.session and args.item):
        raise CliError('Apply requires --item, --actor, --session and explicit --confirm.')
    if args.snapshot != 'worktree':
        raise CliError('Reconcile writes require a fresh physical worktree snapshot.')
    draft = json.loads(Path(args.apply).read_bytes())
    if not isinstance(draft, dict):
        raise CliError('The draft must be a JSON object.')
    candidate = deepcopy(draft)
    draft_id = candidate.pop('id', None)
    if type(draft.get('version')) is not int or draft['version'] != 1 or draft.get('kind') != 'exharness-reconcile' or _digest(candidate) != draft_id:
        raise CliError('The draft schema or content identity is invalid.')
    if (not isinstance(draft.get('record'), dict) or not isinstance(draft['record'].get('path'), str)
            or not _fixed_hex(draft['record'].get('preimage'), (64,))
            or not isinstance(draft.get('groups'), list) or not draft['groups']
            or not all(isinstance(group, dict) for group in draft['groups'])
            or not isinstance(draft.get('findings'), list)
            or not all(isinstance(f, dict) and isinstance(f.get('code'), str) for f in draft['findings'])):
        raise CliError('The draft observations have invalid field types.')
    report, snapshot = _selected(repo, args, config_path, external)
    fresh = _make_draft(repo, args, config_path, report, snapshot)
    if fresh is None:
        return report
    if fresh['authority'] != 'standalone' or draft.get('authority') != 'standalone':
        raise CliError('Managed authority cannot be mutated locally; hand this draft to the real Coordinate entry point.',
                       code='MANAGED_DRAFT_ONLY', exit_code=1)
    for key in ('repo', 'config', 'item', 'snapshot', 'source_token', 'head'):
        if draft.get(key) != fresh[key]:
            raise CliError(f'Reconcile source changed ({key}); generate a fresh draft.',
                           code='RECONCILE_STALE', exit_code=1)
    if draft.get('record', {}).get('path') != fresh['record']['path']:
        raise CliError('The draft no longer names the original task record.', code='RECONCILE_STALE', exit_code=1)
    item, checklist_path, plan, record_path, original = _item(repo, snapshot, config_path, args.item)
    lease = active_lease(item)
    if not lease or item.get('owner') != args.actor or lease.get('owner') != args.actor or lease.get('session') != args.session:
        raise CliError('Only the current original task lease owner and session may apply observations.',
                       code='RECONCILE_WRITER_REQUIRED', exit_code=1)
    if plan.is_symlink() or not plan.is_file():
        raise CliError('The original task record must be a regular file.')
    block = _append_block(draft, args.actor, args.session)
    preimage = draft['record']['preimage']
    already = original.endswith(block) and hashlib.sha256(original[:-len(block)]).hexdigest() == preimage
    if not already and hashlib.sha256(original).hexdigest() != preimage:
        raise CliError('The original record changed; preserve concurrent edits and regenerate the draft.',
                       code='RECONCILE_PREIMAGE_CHANGED', exit_code=1)
    canonical = deepcopy(fresh)
    canonical['id'] = draft['id']
    canonical_block = _append_block(canonical, args.actor, args.session)
    if (not already and draft != fresh) or block != canonical_block:
        raise CliError('The draft observations do not reproduce from the fresh canonical evidence.',
                       code='RECONCILE_FACTS_CHANGED', exit_code=1)
    block = canonical_block
    lock = Path(tempfile.gettempdir()) / ('exharness-reconcile-' + _digest(str(plan.resolve())) + '.lock')
    try:
        fd = os.open(str(lock), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise CliError('Another reconciliation writer holds the original record lock.',
                       code='RECONCILE_WRITER_BUSY', exit_code=1)
    try:
        os.close(fd)
        # Check source and record again under the bounded writer lock. Never
        # rebuild derived state, mutate the checklist, or emit lifecycle events.
        check_report, current = _selected(repo, args, config_path, external)
        check = _make_draft(repo, args, config_path, check_report, current)
        if check is None or check['source_token'] != draft['source_token'] or plan.read_bytes() != original:
            raise CliError('Source or record changed while applying; regenerate the draft.',
                           code='RECONCILE_STALE', exit_code=1)
        if not already:
            append_observation_bytes(plan, original, block)
    finally:
        lock.unlink()
    return _finish({'findings': report['findings'], 'groups': fresh['groups'],
            'snapshot': report.get('snapshot'), 'view': report.get('view'),
            'reconcile': {'id': draft['id'], 'item': args.item,
                          'applied': not already, 'already_applied': already,
                          'record': record_path, 'binding_revalidation_required': True}})


def _reconcile(repo, args, config_path, external):
    if args.apply:
        return _apply_draft(repo, args, config_path, external)
    report, snapshot = _selected(repo, args, config_path, external)
    draft = _make_draft(repo, args, config_path, report, snapshot)
    if draft is None:
        return report
    if args.output:
        target = Path(args.output).absolute()
        record = Path(draft['record']['path'])
        record = record if record.is_absolute() else repo.root / record
        harness = (repo.root / config_path).parent
        protected = {record.resolve(), (repo.root / config_path).resolve()}
        protected.update((harness / name).resolve() for name in ('harness-checklist.json', 'mvp-checklist.json'))
        if target.resolve() in protected:
            raise CliError('A draft output must not overwrite original task authority.')
        try:
            relative = target.resolve().relative_to(repo.root).as_posix()
        except ValueError:
            relative = None
        coverage = _coverage(snapshot, config_path)
        if relative and match_path(relative, coverage['source_roots']) and not match_path(relative, coverage.get('exclude', [])):
            raise CliError('Draft output must be outside governed source or explicitly excluded as a derived artifact.')
        _write_output(target, draft)
    return _finish({'findings': report['findings'], 'groups': draft['groups'], 'draft': draft,
                    'snapshot': report.get('snapshot'), 'view': report.get('view'),
                    'output': args.output, 'observed_exit_code': report['exit_code']})


def _contract(repo, args, config_path, external):
    report, snapshot = _selected(repo, args, config_path, external)
    report['contract'] = {'version': 1, 'capabilities': ['drift', 'remind', 'baseline', 'reconcile'],
                          'snapshots': ['worktree', 'staged', 'ci'],
                          'config': config_path, 'snapshot': snapshot.identity,
                          'hooks': 'not-inspected', 'required_ci': 'not-inspected',
                          'checker': str(Path(__file__).resolve())}
    return report


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument('action', choices=('drift', 'remind', 'baseline', 'reconcile', 'contract'))
    result.add_argument('--repo', default='.')
    result.add_argument('--config')
    result.add_argument('--snapshot', choices=('worktree', 'staged', 'ci'))
    result.add_argument('--format', choices=('text', 'json'), default='text')
    for name in ('base', 'head', 'result', 'external-records', 'output', 'item', 'apply', 'actor', 'session'):
        result.add_argument('--' + name)
    result.add_argument('--integration', choices=('merge', 'squash', 'fast-forward', 'rebase', 'merge-group', 'unknown'))
    result.add_argument('--fingerprint', action='append')
    result.add_argument('--confirm', action='store_true')
    return result


def _print(report, output_format):
    if output_format == 'json':
        print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
        return
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='backslashreplace')
    print(f"Consistency: exit={report['exit_code']}")
    for finding in report.get('findings', []):
        label = 'suppressed' if finding.get('suppressed') else finding['severity']
        print(f"[{label}] {finding['code']}: {finding['message']}")
        print('  Next: ' + finding.get('next_action', 'Review the reported evidence.'))
    view = report.get('view', {})
    if view:
        print(f"View: {view.get('kind')} worktree={view.get('physical_worktree')} HEAD={view.get('head')}")
        for key in ('staged_paths', 'unstaged_paths', 'outside_governed_paths', 'excluded_paths'):
            if view.get(key) is not None:
                print(key + ': ' + (', '.join(view[key]) or '(none)'))
    for group in report.get('groups', []):
        print(f"Group {group.get('id')}: debt={group.get('debt', 'unknown')} record={group.get('record_path', 'unknown')}")
    if 'draft' in report:
        print(json.dumps(report['draft'], ensure_ascii=False, indent=2, sort_keys=True))
    if 'reconcile' in report:
        print(json.dumps(report['reconcile'], ensure_ascii=False, sort_keys=True))
    if 'contract' in report:
        print(json.dumps(report['contract'], ensure_ascii=False, sort_keys=True))
    if report.get('output'):
        print('Output: ' + report['output'])


def main(argv=None):
    args = parser().parse_args(argv)
    args.snapshot = args.snapshot or ('staged' if args.action == 'remind' else 'worktree')
    try:
        repo = GitRepo(args.repo)
        config_path = _config_path(repo, args.config)
        external = _external(args)
        if args.action == 'baseline':
            report = _make_baseline(repo, args, config_path, external)
        elif args.action == 'reconcile':
            report = _reconcile(repo, args, config_path, external)
        elif args.action == 'contract':
            report = _contract(repo, args, config_path, external)
        else:
            report, _ = _selected(repo, args, config_path, external)
    except CliError as exc:
        report = {'exit_code': exc.exit_code, 'groups': [], 'findings': [
            _finding(exc.code, str(exc), severity='error' if exc.exit_code == 1 else 'incomplete')]}
    except (SnapshotError, CoverageError, OSError, ValueError, TypeError, KeyError) as exc:
        report = {'exit_code': 2, 'groups': [], 'findings': [_finding('CHECK_INCOMPLETE', str(exc))]}
    except SystemExit as exc:
        # Shared locator errors are explicit failures, never permission to write.
        report = {'exit_code': 2, 'groups': [], 'findings': [_finding('TASK_AUTHORITY_INVALID', str(exc))]}
    _print(report, args.format)
    return report['exit_code']


if __name__ == '__main__':
    raise SystemExit(main())
