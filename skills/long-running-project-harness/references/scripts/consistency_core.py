#!/usr/bin/env python3
"""Read-only, fixed-snapshot engineering-record consistency rules (v1)."""
from __future__ import annotations

import copy
import contextlib
import io
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re

from consistency_snapshot import GitRepo, SnapshotError, match_path
from harness_common import resolve_item_plan

SEMANTICS = 'exharness-consistency/v1'
SHA = re.compile(r'^[0-9a-f]{40}(?:[0-9a-f]{24})?$')
DIGEST = re.compile(r'^[0-9a-f]{64}$')
IDENTIFIER = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')
PROOF = re.compile(r'^```exharness-review\s*\n(.*?)^```\s*$', re.MULTILINE | re.DOTALL)


class CoverageError(ValueError):
    """The explicitly requested coverage contract cannot be evaluated."""


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


def _object(value, allowed, label, required=()):
    if not isinstance(value, dict):
        raise CoverageError(f'{label} must be an object')
    unknown = set(value) - set(allowed)
    missing = set(required) - set(value)
    if unknown or missing:
        raise CoverageError(f'{label}: unknown fields {sorted(unknown)}; missing fields {sorted(missing)}')


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise CoverageError(f'{label} must be nonempty text')
    return value


def _path(value, label, glob=False):
    _text(value, label)
    path = PurePosixPath(value)
    if '\\' in value or path.is_absolute() or PureWindowsPath(value).anchor or '..' in path.parts or str(path) in ('.', ''):
        raise CoverageError(f'{label} must be a repository-relative POSIX path')
    if not glob and any(c in value for c in '*?['):
        raise CoverageError(f'{label} must name one file')
    return value


def _patterns(value, label, empty=False):
    if not isinstance(value, list) or (not value and not empty):
        raise CoverageError(f'{label} must be a {"possibly empty " if empty else "nonempty "}list')
    for entry in value:
        _path(entry, label, glob=True)
    if len(set(value)) != len(value):
        raise CoverageError(f'{label} contains duplicates')


def _thresholds(value, label, defaults=None):
    _object(value, {'warn_at', 'block_at'}, label)
    result = dict(defaults or {'warn_at': 1, 'block_at': 3})
    result.update(value)
    if any(type(result[key]) is not int or result[key] < 1 for key in result):
        raise CoverageError(f'{label}: thresholds must be positive integers')
    if result['block_at'] < result['warn_at']:
        raise CoverageError(f'{label}: block_at must be at least warn_at')
    return result


def load_coverage(config_dict):
    """Validate only the opt-in coverage section, preserving legacy config keys."""
    if not isinstance(config_dict, dict) or 'coverage' not in config_dict:
        raise CoverageError('coverage is not configured')
    cov = copy.deepcopy(config_dict['coverage'])
    _object(cov, {'version', 'enabled', 'adopted_at', 'source_roots', 'exclude', 'defaults',
                  'groups', 'baseline', 'handoff', 'history_limit'}, 'coverage',
            {'version', 'enabled', 'adopted_at', 'source_roots', 'groups'})
    if type(cov['version']) is not int or cov['version'] != 1:
        raise CoverageError('coverage.version must be 1')
    if type(cov['enabled']) is not bool:
        raise CoverageError('coverage.enabled must be boolean')
    if not cov['enabled']:
        raise CoverageError('coverage is disabled')
    if not isinstance(cov['adopted_at'], str) or not SHA.fullmatch(cov['adopted_at']):
        raise CoverageError('coverage.adopted_at must be a full commit object ID')
    _patterns(cov['source_roots'], 'source_roots')
    cov.setdefault('exclude', [])
    _patterns(cov['exclude'], 'exclude', empty=True)
    cov['defaults'] = _thresholds(cov.get('defaults', {}), 'defaults')
    if 'baseline' in cov:
        _path(cov['baseline'], 'baseline')
    if 'handoff' in cov and type(cov['handoff']) is not bool:
        raise CoverageError('handoff must be boolean')
    cov.setdefault('history_limit', 2000)
    if type(cov['history_limit']) is not int or cov['history_limit'] < 1:
        raise CoverageError('history_limit must be a positive integer')
    groups = cov['groups']
    if not isinstance(groups, list) or not groups:
        raise CoverageError('groups must be a nonempty list')
    identifiers = set()
    for group in groups:
        _object(group, {'id', 'sources', 'record', 'rules', 'policy'}, 'group',
                {'id', 'sources', 'record', 'rules'})
        if not isinstance(group['id'], str) or not IDENTIFIER.fullmatch(group['id']) or group['id'] in identifiers:
            raise CoverageError('group IDs must be safe, unique identifiers')
        identifiers.add(group['id'])
        _patterns(group['sources'], f'{group["id"]}.sources')
        record = group['record']
        _object(record, {'path', 'item'}, 'record')
        if len(record) != 1:
            raise CoverageError('record must declare exactly one path or item')
        if 'path' in record:
            _path(record['path'], 'record.path')
        elif not isinstance(record['item'], str) or not IDENTIFIER.fullmatch(record['item']):
            raise CoverageError('record.item must be a safe item identifier')
        rules = group['rules']
        if not isinstance(rules, list) or not rules or any(r not in ('record', 'review') for r in rules) or len(set(rules)) != len(rules):
            raise CoverageError('rules must be a nonempty unique subset of record/review')
        group['policy'] = _thresholds(group.get('policy', {}), 'group.policy', cov['defaults'])
    if not any('record' in g['rules'] for g in groups):
        raise CoverageError('coverage must execute at least one deterministic record rule')
    return cov


def scope_digest(group, coverage):
    """Bind the rule semantics and declared scope, independently of timestamps."""
    return _hash({'semantics': SEMANTICS, 'id': group['id'], 'record': group['record'],
                  'sources': sorted(group['sources']), 'rules': sorted(group['rules']),
                  'exclude': sorted(coverage.get('exclude', []))})


def source_excludes(group, coverage, record_path):
    """Exclude proof/baseline bytes and known derived cache from source identity."""
    paths = list(coverage.get('exclude', []))
    paths.extend(g['record']['path'] for g in coverage['groups'] if 'path' in g['record'])
    if record_path and not Path(record_path).is_absolute():
        paths.append(record_path)
    if coverage.get('baseline'):
        paths.append(coverage['baseline'])
    paths.extend(['docs/project-harness/current/**', 'docs/project-harness/harness-state.json'])
    return sorted(set(paths))


def _matches(path, patterns):
    return match_path(path, patterns)


def _finding(code, severity, group, path, evidence, message, next_action, eligible=False):
    body = {'semantics': SEMANTICS, 'code': code, 'group': group,
            'path': path, 'evidence': evidence}
    return dict(body, severity=severity, fingerprint=_hash(body), message=message,
                next_action=next_action, baseline_eligible=eligible)


def _read(snapshot, path):
    entry = snapshot.entries.get(path)
    if entry is not None and (entry.mode == '120000' or entry.mode == '160000' or entry.kind == 'commit'):
        raise CoverageError(f'{path}: required record must be a regular file, not a link or gitlink')
    return snapshot.read(path)


def _json(snapshot, path):
    body = _read(snapshot, path)
    if body is None:
        raise FileNotFoundError(path)
    return json.loads(body.decode('utf-8'))


def _record_locator(repo, snapshot, config_path, group, *, missing_ok=False):
    record = group['record']
    if 'path' in record:
        return record['path'], None
    harness = str(PurePosixPath(config_path).parent)
    candidates = [f'{harness}/harness-checklist.json', f'{harness}/mvp-checklist.json']
    present = [p for p in candidates if p in snapshot.entries]
    if not present and missing_ok:
        return None, None
    if len(present) != 1:
        code = 'CHECKLIST_AMBIGUOUS' if present else 'CHECKLIST_MISSING'
        raise RecordError(code, f'Exactly one checklist is required; candidates: {present}')
    checklist = _json(snapshot, present[0])
    if not isinstance(checklist, dict) or not isinstance(checklist.get('items'), list):
        raise RecordError('RECORD_LOCATOR_INVALID', 'Checklist has no items list')
    if any(not isinstance(item, dict) or not isinstance(item.get('id'), str) for item in checklist['items']):
        raise RecordError('RECORD_LOCATOR_INVALID', 'Checklist contains malformed item identities')
    items = [item for item in checklist['items'] if item.get('id') == record['item']]
    if not items and missing_ok:
        return None, None
    if len(items) != 1:
        raise RecordError('RECORD_LOCATOR_INVALID', f'Expected one matching item; found {len(items)}')
    item = items[0]
    for raw in (item.get('plan_path'), (item.get('artifacts') or {}).get('plan') if isinstance(item.get('artifacts'), dict) else None):
        if isinstance(raw, str) and PureWindowsPath(raw).anchor and not Path(raw).is_absolute():
            raise RecordError('RECORD_LOCATOR_INVALID', 'Foreign anchored plan locator cannot be interpreted on this host')
    captured = io.StringIO()
    try:
        with contextlib.redirect_stderr(captured):
            locator = resolve_item_plan(item, require_exists=False, project=repo.root,
                                        harness=repo.root / PurePosixPath(config_path).parent)
    except SystemExit as exc:
        raise RecordError('RECORD_LOCATOR_INVALID', captured.getvalue().strip()) from exc
    try:
        return locator.relative_to(repo.root).as_posix(), item
    except ValueError:
        return str(locator), item


class RecordError(CoverageError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _record_bytes(repo, snapshot, locator, config, external_records):
    if not Path(locator).is_absolute() and not PureWindowsPath(locator).anchor:
        return _read(snapshot, locator), {'kind': snapshot.kind, 'revision': snapshot.revision,
                                         'path': locator}
    if external_records is not None:
        _object(external_records, {'version', 'records'}, 'external_records', {'version', 'records'})
        if type(external_records['version']) is not int or external_records['version'] != 1 or not isinstance(external_records['records'], list):
            raise SnapshotError('invalid caller external record manifest')
        matches = [r for r in external_records['records'] if isinstance(r, dict) and r.get('locator') == locator]
        if len(matches) != 1:
            raise SnapshotError(f'no unique caller-fixed external record for {locator}')
        record = matches[0]
        _object(record, {'locator', 'repo', 'revision', 'path', 'blob'}, 'external record',
                {'locator', 'repo', 'revision', 'path', 'blob'})
        _path(record['path'], 'external record.path')
        if not isinstance(record['revision'], str) or not SHA.fullmatch(record['revision']):
            raise SnapshotError('external record revision must be a fixed commit')
        external_repo = GitRepo(record['repo'])
        if Path(record['repo']).resolve() != external_repo.root.resolve():
            raise SnapshotError('external repo must identify its exact checkout root')
        # The trusted caller maps a canonical locator to an approved checkout;
        # CI mounts need not reproduce another host's absolute artifact path.
        fixed = external_repo.snapshot(record['revision'])
        entry = fixed.entries.get(record['path'])
        if entry is None or entry.oid != record['blob']:
            raise SnapshotError('caller record blob does not match fixed revision/path')
        body = _read(fixed, record['path'])
        return body, {'kind': 'caller-fixed', 'locator': locator, 'repo': str(external_repo.root),
                      'revision': fixed.revision, 'path': record['path'], 'blob': entry.oid}
    if snapshot.kind != 'worktree' or config.get('deployment_profile') == 'coordinate-managed':
        raise SnapshotError(f'external record requires caller-fixed repository evidence: {locator}')
    path = Path(locator)
    if path.is_symlink():
        raise CoverageError('external canonical record must not be a symlink')
    # Local diagnostics preserve Standalone external locators and label their source.
    body = path.read_bytes()
    try:
        external_repo = GitRepo(path.parent)
    except SnapshotError:
        if path.read_bytes() != body:
            raise SnapshotError('external record changed while being read')
        return body, {'kind': 'external-file', 'path': str(path), 'sha256': hashlib.sha256(body).hexdigest()}
    fixed = external_repo.worktree()
    relative = path.relative_to(external_repo.root).as_posix()
    frozen = _read(fixed, relative)
    if frozen != body:
        raise SnapshotError('external record changed while fixing its snapshot')
    return frozen, {'kind': 'external-worktree', 'repo': str(external_repo.root),
                     'revision': external_repo.head(), 'path': relative, 'snapshot': fixed.identity}


def _proofs(body, coverage):
    try:
        text = body.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise CoverageError(f'record must be UTF-8: {exc}') from exc
    starts = re.findall(r'^```exharness-review(?:\s|$)', text, re.MULTILINE)
    blocks = list(PROOF.finditer(text))
    if len(starts) != len(blocks):
        raise CoverageError('review block has an unclosed or malformed fence')
    values = []
    groups = {g['id']: g for g in coverage['groups']}
    for block in blocks:
        try:
            value = json.loads(block.group(1))
        except (ValueError, TypeError) as exc:
            raise CoverageError(f'review block JSON is invalid: {exc}') from exc
        _object(value, {'version', 'group', 'rule', 'scope_digest', 'source_digest', 'decision',
                        'actor', 'reason', 'basis', 'item', 'date', 'time'}, 'review',
                {'version', 'group', 'rule', 'scope_digest', 'source_digest', 'decision', 'actor', 'reason', 'basis'})
        if type(value['version']) is not int or value['version'] != 1 or value['rule'] != 'review/v1':
            raise CoverageError('unknown review rule/version')
        if not isinstance(value['group'], str) or value['group'] not in groups:
            raise CoverageError('review references an unknown group')
        if any(not isinstance(value[k], str) or not DIGEST.fullmatch(value[k]) for k in ('scope_digest', 'source_digest')):
            raise CoverageError('review digest must be SHA-256')
        if value['decision'] not in ('updated', 'reviewed-no-doc-change'):
            raise CoverageError('unknown review decision')
        _text(value['actor'], 'review.actor')
        _text(value['reason'], 'review.reason')
        basis = value['basis']
        _object(basis, {'parent', 'review', 'source_commit'}, 'review.basis', {'parent', 'review'})
        if not isinstance(basis['parent'], str) or not SHA.fullmatch(basis['parent']):
            raise CoverageError('review basis.parent must be a fixed commit')
        _text(basis['review'], 'review.basis.review')
        if 'source_commit' in basis and (not isinstance(basis['source_commit'], str) or not SHA.fullmatch(basis['source_commit'])):
            raise CoverageError('review basis.source_commit must be a fixed source commit')
        expected = groups[value['group']]['record'].get('item')
        if ('item' in value and value['item'] != expected) or (expected and value.get('item') != expected):
            raise CoverageError('review item must match canonical record item')
        values.append(value)
    return values


def _proof_identity(proof):
    return _hash({key: value for key, value in proof.items() if key not in ('date', 'time')})


def _historical_proofs(snapshot, locator, coverage, group_id):
    try:
        body = _read(snapshot, locator)
        if body is None:
            return []
        return [p for p in _proofs(body, coverage) if p['group'] == group_id]
    except CoverageError:
        # Invalid historical evidence never signs off a change; corrected current
        # evidence remains usable without rewriting already-published history.
        return []


def _review_basis(proof):
    return ' '.join(proof['basis']['review'].split())


def _checkpoint_evidence(snapshot, locator, proof):
    entry = snapshot.entries.get(locator)
    return {'revision': snapshot.revision, 'snapshot': snapshot.identity, 'path': locator,
            'record_blob': entry.oid if entry is not None else None,
            'proof': _proof_identity(proof), 'basis': dict(proof['basis']),
            'parent_role': 'context'}


def _entry(entry):
    return {'mode': entry.mode, 'oid': entry.oid, 'kind': entry.kind}


def _result(snapshot, findings, groups, coverage=None):
    severity = {f['severity'] for f in findings if not f.get('suppressed')}
    return {'version': 1, 'semantics': SEMANTICS, 'snapshot': {'identity': snapshot.identity,
             'kind': snapshot.kind, 'revision': snapshot.revision, 'tree': snapshot.tree},
            'coverage': coverage, 'groups': groups, 'findings': findings,
            'exit_code': 2 if 'incomplete' in severity else 1 if 'error' in severity else 0}


def evaluate(repo, snapshot, config_path, *, policy=None, history_tip=None,
             external_records=None, apply_baseline=True, authority_profile=None):
    """Evaluate one immutable source/config/record view; never write or fetch.

    authority_profile locks the trusted caller's deployment authority in CI.
    Checkpoints use the selected record's proven introduction and content.
    """
    findings, reports = [], []
    def add(code, severity, group=None, path=None, evidence=None, message='', action='Refresh the formal record and rerun.', eligible=False):
        finding = _finding(code, severity, group, path, evidence or {}, message, action, eligible)
        findings.append(finding)
        return finding
    try:
        config_path = str(config_path)
        if Path(config_path).is_absolute():
            config_path = Path(config_path).relative_to(repo.root).as_posix()
        _path(config_path, 'config_path')
        config = _json(snapshot, config_path)
        try:
            candidate = load_coverage(config)
        except CoverageError as exc:
            if 'coverage' not in config:
                add('CONFIG_MISSING', 'incomplete', path=config_path, message=str(exc))
            elif isinstance(config.get('coverage'), dict) and config['coverage'].get('enabled') is False:
                add('CONFIG_DISABLED', 'incomplete', path=config_path, message=str(exc))
            else:
                add('CONFIG_INVALID', 'error', path=config_path, message=str(exc))
            return _result(snapshot, findings, reports)
        cov = load_coverage({'coverage': policy}) if policy is not None else candidate
        profile = config.get('deployment_profile', 'standalone') if authority_profile is None else authority_profile
        if profile not in ('standalone', 'coordinate-managed'):
            raise CoverageError('deployment authority profile must be standalone or coordinate-managed')
        config = dict(config, deployment_profile=profile)
        # Candidate schema is validated first. Additions may share one formal
        # document with locked groups without changing those groups' duties.
        proof_cov = dict(cov)
        locked_ids = {group['id'] for group in cov['groups']}
        proof_cov['groups'] = cov['groups'] + [group for group in candidate['groups'] if group['id'] not in locked_ids]
    except (CoverageError, ValueError, TypeError, KeyError, FileNotFoundError, SnapshotError, OSError) as exc:
        add('CONFIG_UNREADABLE', 'incomplete', path=str(config_path), message=str(exc))
        return _result(snapshot, findings, reports)
    tip = history_tip or snapshot.revision or repo.head()
    try:
        anchor = repo.snapshot(cov['adopted_at'])
        if anchor.revision != cov['adopted_at']:
            raise SnapshotError('adopted_at must identify a commit, not a tree')
        commits = repo.first_parent(cov['adopted_at'], tip, limit=cov['history_limit'])
        history = [(cov['adopted_at'], anchor)] + [(commit, repo.snapshot(commit)) for commit in commits]
    except (SnapshotError, ValueError, OSError) as exc:
        add('HISTORY_INCOMPLETE', 'incomplete', evidence={'adopted_at': cov['adopted_at'], 'tip': tip}, message=str(exc),
            action='Provide complete first-parent history from the reviewed adoption anchor.')
        history = None
    covered = set()
    for group in cov['groups']:
        gid = group['id']
        paths = sorted(path for path in snapshot.entries if _matches(path, group['sources']) and not _matches(path, cov['exclude']))
        covered.update(paths)
        report = {'id': gid, 'scope_digest': scope_digest(group, cov), 'record_path': None,
                  'record_digest': None, 'source_digest': None, 'covered_paths': paths,
                  'item': group['record'].get('item'), 'debt': None, 'checkpoint': None,
                  'history_changes': [], 'pending': False, 'review_valid': False, 'checkpoint_evidence': None}
        reports.append(report)
        try:
            locator, item = _record_locator(repo, snapshot, config_path, group)
            report['record_path'] = locator
            if group['record'].get('item') and config.get('deployment_profile') == 'coordinate-managed':
                add('MANAGED_AUTHORITY_UNVERIFIED', 'incomplete', gid, locator,
                    {'item': group['record']['item']},
                    'A local checklist or fixed file export does not prove the current Coordinate task authority.',
                    action='Provide an existing trusted Coordinate receipt/entry point, or retain this explicit coverage gap.')
            if any(_matches(locator, g['sources']) and not _matches(locator, cov['exclude']) for g in cov['groups']):
                add('SOURCE_RECORD_CONFLICT', 'error', gid, locator, message='Formal record overlaps declared source; split the scope explicitly.')
            excludes = source_excludes(group, cov, locator)
            report['source_digest'] = snapshot.digest(group['sources'], exclude=excludes)
            body, record_source = _record_bytes(repo, snapshot, locator, config, external_records)
            report['record_source'] = record_source
            if body is None:
                add('RECORD_MISSING', 'error', gid, locator, message='Formal record is absent from the selected snapshot.')
                continue
            report['record_digest'] = hashlib.sha256(body).hexdigest()
            current_proofs = [p for p in _proofs(body, proof_cov) if p['group'] == gid]
        except RecordError as exc:
            add(exc.code, 'error', gid, message=str(exc))
            continue
        except CoverageError as exc:
            code = 'RECORD_TYPE' if 'regular file' in str(exc) or 'symlink' in str(exc) else 'REVIEW_INVALID'
            add(code, 'error', gid, report['record_path'], message=str(exc))
            continue
        except (SnapshotError, ValueError, TypeError, FileNotFoundError, OSError) as exc:
            add('RECORD_UNAVAILABLE', 'incomplete', gid, report['record_path'], message=str(exc))
            continue
        if history is None or 'review' not in group['rules']:
            continue
        checkpoint, debt, changes, seen, prior_basis = cov['adopted_at'], 0, [], set(), None
        proof_status = {}
        external = Path(locator).is_absolute() or bool(PureWindowsPath(locator).anchor)
        previous_digest = None
        try:
            for commit, historical in history:
                digest = historical.digest(group['sources'], exclude=excludes)
                if previous_digest is not None and previous_digest != digest:
                    debt += 1
                    changes.append(commit)
                previous_digest = digest
                historical_locator = locator
                if group['record'].get('item'):
                    historical_locator, _ = _record_locator(repo, historical, config_path, group, missing_ok=True)
                # Only the locator bound to this same item in this historical
                # snapshot can establish an introduction. A move cannot make an
                # unchanged block new or retroactively bind a future path.
                if historical_locator is None:
                    proofs = []
                elif Path(historical_locator).is_absolute() or PureWindowsPath(historical_locator).anchor:
                    if not external:
                        raise SnapshotError(f'Historical external task record is unavailable: {historical_locator}')
                    proofs = []
                else:
                    if group['record'].get('item') and _read(historical, historical_locator) is None:
                        raise SnapshotError(f'Historical bound task record is missing: {historical_locator}')
                    proofs = _historical_proofs(historical, historical_locator, proof_cov, gid)
                for proof in proofs:
                    identity = _proof_identity(proof)
                    introduced = identity not in seen
                    seen.add(identity)
                    valid = (proof['scope_digest'] == report['scope_digest'] and proof['source_digest'] == digest)
                    refreshed = prior_basis is None or _review_basis(proof) != prior_basis
                    if introduced and proof['scope_digest'] == report['scope_digest']:
                        proof_status[identity] = (None if valid and refreshed else 'REVIEW_REFRESH_INVALID' if valid
                                                  else 'REVIEW_BINDING_INVALID')
                    if introduced and valid and refreshed:
                        checkpoint, debt, changes, prior_basis = commit, 0, [], _review_basis(proof)
                        report['checkpoint_evidence'] = _checkpoint_evidence(historical, historical_locator, proof)
            report['pending'] = previous_digest != report['source_digest']
            if report['pending']:
                debt += 1
                changes.append('pending:' + report['source_digest'])
            if external:
                history_index = {commit: index for index, (commit, _) in enumerate(history)}
                anchors = []
                for proof in current_proofs:
                    source_commit = proof['basis'].get('source_commit')
                    if source_commit is None:
                        add('EXTERNAL_CHECKPOINT_UNVERIFIED', 'incomplete', gid, locator,
                            {'record_source': record_source, 'proof': _proof_identity(proof)},
                            'External review needs an exact governed source commit anchor.',
                            action='Declare basis.source_commit at the reviewed committed source; pending source remains debt.')
                        continue
                    try:
                        source_snapshot = repo.snapshot(source_commit)
                    except SnapshotError as exc:
                        add('EXTERNAL_CHECKPOINT_UNVERIFIED', 'incomplete', gid, locator,
                            {'source_commit': source_commit}, str(exc))
                        continue
                    if (source_commit not in history_index or source_snapshot.revision != source_commit or
                        proof['scope_digest'] != report['scope_digest'] or
                        source_snapshot.digest(group['sources'], exclude=excludes) != proof['source_digest']):
                        add('EXTERNAL_CHECKPOINT_INVALID', 'error', gid, locator,
                            {'source_commit': source_commit, 'proof': _proof_identity(proof)},
                            'External anchor must bind this scope and exact source on the selected first-parent history after adoption.')
                        continue
                    anchors.append((history_index[source_commit], proof, source_snapshot))
                for index, proof, source_snapshot in sorted(anchors, key=lambda value: value[0]):
                    if prior_basis is not None and _review_basis(proof) == prior_basis:
                        add('REVIEW_REFRESH_INVALID', 'error', gid, locator, {'proof': _proof_identity(proof)},
                            'Refreshing an external anchor requires a substantive change to its review basis.')
                        continue
                    checkpoint, prior_basis = source_snapshot.revision, _review_basis(proof)
                    changes = [change for change in changes if change.startswith('pending:') or history_index[change] > index]
                    debt = len(changes)
                    report['checkpoint_evidence'] = {
                        'authority': 'exact-source-anchor-statement', 'revision': checkpoint,
                        'source_snapshot': source_snapshot.identity, 'path': locator,
                        'record_source': record_source, 'record_sha256': report['record_digest'],
                        'proof': _proof_identity(proof), 'basis': dict(proof['basis']), 'parent_role': 'context'}
            # New evidence in an index/worktree/result tree may acknowledge that exact candidate.
            for proof in current_proofs if not external else []:
                identity = _proof_identity(proof)
                if identity in seen:
                    if proof_status.get(identity):
                        add(proof_status[identity], 'error', gid, locator, {'proof': identity},
                            'The active review block was not validly introduced or refreshed at its source checkpoint.')
                    continue
                valid = (proof['scope_digest'] == report['scope_digest'] and
                         proof['source_digest'] == report['source_digest'])
                refreshed = prior_basis is None or _review_basis(proof) != prior_basis
                if valid and refreshed:
                    checkpoint, debt, changes, prior_basis = 'pending:' + identity, 0, [], _review_basis(proof)
                    report['review_valid'] = True
                    report['checkpoint_evidence'] = _checkpoint_evidence(snapshot, locator, proof)
                elif valid:
                    add('REVIEW_REFRESH_INVALID', 'error', gid, locator, {'proof': identity},
                        'Refreshing a checkpoint requires a substantive change to its review basis.')
                else:
                    add('REVIEW_BINDING_INVALID', 'error', gid, locator, {'proof': identity, 'source_digest': report['source_digest']},
                        'New review evidence does not bind the selected source and scope.')
            report.update(debt=debt, checkpoint=checkpoint, history_changes=changes)
            if report['checkpoint_evidence'] is not None and debt == 0:
                report['review_valid'] = True
            limits = group['policy']
            if debt >= limits['warn_at']:
                add('REVIEW_DEBT', 'error' if debt >= limits['block_at'] else 'warning', gid, locator,
                    {'scope_digest': report['scope_digest'], 'source_digest': report['source_digest'],
                     'checkpoint': checkpoint, 'changes': changes, 'debt': debt, 'policy': limits},
                    f'{debt} source changes have accumulated since the last scoped review.', eligible=True)
        except (SnapshotError, CoverageError, ValueError, TypeError, OSError) as exc:
            add('HISTORY_INCOMPLETE', 'incomplete', gid, locator,
                {'adopted_at': cov['adopted_at'], 'tip': tip}, str(exc))
    for path, entry in sorted(snapshot.entries.items()):
        if _matches(path, cov['source_roots']) and not _matches(path, cov['exclude']) and path not in covered:
            add('SOURCE_UNCOVERED', 'error', path=path, evidence={'path': path, 'entry': _entry(entry)},
                message='Source under a governed root has no coverage group.', action='Add an explicit source-to-record binding.')
    if cov.get('handoff', True):
        _handoffs(repo, snapshot, cov, config_path, config, external_records, add)
    if apply_baseline and candidate.get('baseline'):
        _baseline(repo, snapshot, config_path, cov, candidate['baseline'], tip, findings, add, external_records)
    result = _result(snapshot, findings, reports, cov)
    result['authority_profile'] = profile
    return result


def _handoffs(repo, snapshot, coverage, config_path, config, external_records, add):
    from consistency_handoff import snapshot_problems
    harness = str(PurePosixPath(config_path).parent)
    present = [f'{harness}/{name}' for name in ('harness-checklist.json', 'mvp-checklist.json')
               if f'{harness}/{name}' in snapshot.entries]
    if not present:
        return
    if len(present) != 1:
        add('CHECKLIST_AMBIGUOUS', 'error', evidence={'candidates': present},
            message='Pending handoff authority cannot be selected from two checklists.')
        return
    try:
        checklist = _json(snapshot, present[0])
        if not isinstance(checklist, dict) or not isinstance(checklist.get('items'), list):
            raise CoverageError('Checklist must contain an items list')
        def record(item):
            locator, _ = _record_locator(repo, snapshot, config_path, {'record': {'item': item['id']}})
            data, _ = _record_bytes(repo, snapshot, locator, config, external_records)
            if data is None:
                raise CoverageError('Canonical plan is absent from the selected snapshot')
            return locator, data
        def artifact(path):
            return _record_bytes(repo, snapshot, path, config, external_records)[0]
        for code, severity, item, path, message in snapshot_problems(snapshot, checklist, coverage, harness, record, artifact):
            add(code, severity, item, path, {'item': item, 'snapshot': snapshot.identity}, message,
                action='Refresh this task handoff from the current canonical plan and source, or decline it.')
    except (CoverageError, SnapshotError, ValueError, TypeError, KeyError, OSError, SystemExit) as exc:
        add('handoff-unavailable', 'incomplete', path=present[0], message=str(exc),
            action='Restore the required handoff/checklist evidence and rerun.')


def _baseline(repo, snapshot, config_path, coverage, path, tip, findings, add, external_records):
    try:
        baseline = _json(snapshot, path)
        _object(baseline, {'version', 'origin', 'entries'}, 'baseline', {'version', 'origin', 'entries'})
        if type(baseline['version']) is not int or baseline['version'] != 1:
            raise CoverageError('baseline version must be 1')
        if not isinstance(baseline['origin'], str) or not SHA.fullmatch(baseline['origin']):
            raise CoverageError('baseline origin must be a fixed commit')
        if not repo.is_ancestor(baseline['origin'], tip):
            raise CoverageError('baseline origin is not an ancestor of selected history')
        if not isinstance(baseline['entries'], list):
            raise CoverageError('baseline entries must be a list')
        origin_snapshot = repo.snapshot(baseline['origin'])
        origin_report = evaluate(repo, origin_snapshot, config_path, policy=coverage,
                                 history_tip=baseline['origin'], external_records=external_records, apply_baseline=False)
        if origin_report['exit_code'] == 2:
            add('BASELINE_INCOMPLETE', 'incomplete', path=path, evidence={'origin': baseline['origin']},
                message='Baseline origin cannot be fully evaluated with the required evidence.')
            return
        origin_findings = {f['fingerprint']: f for f in origin_report['findings'] if f['baseline_eligible']}
        active = {f['fingerprint']: f for f in findings}
        seen = set()
        for entry in baseline['entries']:
            _object(entry, {'fingerprint', 'code', 'group', 'path', 'evidence'}, 'baseline entry',
                    {'fingerprint', 'code', 'group', 'path', 'evidence'})
            fingerprint = entry['fingerprint']
            if not isinstance(fingerprint, str) or not DIGEST.fullmatch(fingerprint) or fingerprint in seen:
                raise CoverageError('baseline fingerprints must be unique SHA-256 values')
            seen.add(fingerprint)
            finding = active.get(fingerprint)
            old = origin_findings.get(fingerprint)
            if old is None or any(entry[k] != old[k] for k in entry):
                add('BASELINE_INVALID', 'error', path=path, evidence={'fingerprint': fingerprint},
                    message='Baseline entry does not reproduce at its claimed origin.')
            elif not finding:
                add('BASELINE_STALE', 'error', path=path, evidence={'fingerprint': fingerprint},
                    message='Baseline entry no longer matches an active finding; remove it before it can hide a recurrence.')
            elif not finding['baseline_eligible'] or any(entry[k] != finding[k] for k in entry):
                add('BASELINE_INVALID', 'error', path=path, evidence={'fingerprint': fingerprint},
                    message='Baseline entry is not an exact suppressible old finding.')
            else:
                finding['suppressed'] = True
                finding['baseline_origin'] = baseline['origin']
    except SnapshotError as exc:
        add('BASELINE_INCOMPLETE', 'incomplete', path=path, message=str(exc))
    except (CoverageError, ValueError, TypeError, FileNotFoundError, OSError) as exc:
        add('BASELINE_INVALID', 'error', path=path, message=str(exc))
