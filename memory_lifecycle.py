"""Opt-in memory lifecycle policy for a new cohort, never an old-run rewrite.

SQLite records are authoritative. Native stores and indexes remain owned by their
released implementations. This module makes no generation or embedding calls.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import uuid
from types import MappingProxyType
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mc.core import digest, dumps, now


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class ToolVersion(Contract):
    api: str = Field(min_length=1)
    definition_hash: str = Field(min_length=1)
    behavior_revision: str = Field(min_length=1)


def tool_versions(definitions: dict, behavior_revision: str) -> dict[str, ToolVersion]:
    """Use pinned upstream revision when no per-API behavior version exists."""
    return {api: ToolVersion(api=api, definition_hash=digest(definition),
                             behavior_revision=behavior_revision)
            for api, definition in definitions.items()}


class Identity(Contract):
    tenant: str = Field(min_length=1)
    owner: str = Field(min_length=1)
    arm: str = Field(min_length=1)
    namespace: str = Field(min_length=1)
    native_id: str = Field(min_length=1)
    layer: str = ''

    @property
    def key(self):
        return digest(self.model_dump())


class Metadata(Contract):
    schema_version: Literal[1] = 1
    task_families: tuple[str, ...] = Field(min_length=1)
    tools: tuple[ToolVersion, ...] = ()
    dependency_coverage: Literal['complete', 'unknown'] = 'unknown'
    source_runs: tuple[str, ...] = ()
    consolidated_from: tuple[str, ...] = ()
    agent_version: str = Field(min_length=1)
    model_settings_version: str = Field(min_length=1)
    index_required: bool = False
    expires_at: datetime | None = None

    @model_validator(mode='after')
    def coherent(self):
        if len({x.api for x in self.tools}) != len(self.tools):
            raise ValueError('Duplicate API dependencies')
        if any(not x or x == '*' for x in self.task_families):
            raise ValueError('Explicit public task-family scopes are required')
        if self.expires_at is not None and self.expires_at.tzinfo is None:
            raise ValueError('Expiry requires a timezone')
        return self


class Revision(Contract):
    schema_version: Literal[1] = 1
    identity: Identity
    content_hash: str
    metadata: Metadata
    supersedes: str | None = None

    @property
    def key(self):
        return digest(self.model_dump(mode='json'))

    @property
    def metadata_hash(self):
        return digest(self.metadata.model_dump(mode='json'))


class IndexBinding(Contract):
    schema_version: Literal[1] = 1
    content_hash: str
    metadata_hash: str
    index_version: str = Field(min_length=1)
    embedding_version: str = Field(min_length=1)
    dimension: int = Field(gt=0)
    normalizer_version: str = Field(min_length=1)


class Rule(Contract):
    schema_version: Literal[1] = 1
    min_pairs: int = Field(default=4, ge=1)
    min_scenario_groups: int = Field(default=2, ge=1)
    min_wins: int = Field(default=2, ge=1)
    max_losses: int = Field(default=0, ge=0)

    @property
    def version(self):
        return digest(self.model_dump())

    def accepts(self, families):
        return bool(families) and all(
            f['pairs'] >= self.min_pairs and len(f['groups']) >= self.min_scenario_groups and
            f['wins'] >= self.min_wins and f['losses'] <= self.max_losses for f in families.values())


class TrialPair(Contract):
    task_id: str
    task_family: str = Field(min_length=1)
    repetition: int = Field(ge=0)
    with_candidate: str
    without_candidate: str


class ValidationPlan(Contract):
    schema_version: Literal[1] = 1
    revision: str
    policy_version: str
    base_snapshot: str
    pairs: tuple[TrialPair, ...] = Field(min_length=1)
    evaluation_groups: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode='after')
    def separate(self):
        keys = [k for p in self.pairs for k in (p.with_candidate, p.without_candidate)]
        if len(keys) != len(set(keys)):
            raise ValueError('Every planned attempt needs a distinct cell identity')
        if len({(p.task_id, p.repetition) for p in self.pairs}) != len(self.pairs):
            raise ValueError('Duplicate task/repetition pairs')
        if {p.task_id.split('_')[0] for p in self.pairs} & set(self.evaluation_groups):
            raise ValueError('Evaluation groups cannot supply promotion evidence')
        return self

    @property
    def key(self):
        return digest(self.model_dump(mode='json'))


class Registry:
    """Append lifecycle events to the existing ledger, with optimistic concurrency."""
    def __init__(self, ledger, rule: Rule):
        self.ledger, self.db, self.rule = ledger, ledger.db, rule

    def events(self):
        rows = self.db.execute("SELECT id,data FROM records WHERE kind='memory_lifecycle' ORDER BY rowid")
        out = []
        for ident, raw in rows:
            event = json.loads(raw)
            if event.get('schema_version') != 1:
                raise ValueError('Unsupported lifecycle schema; explicit migration required')
            if event.get('action') not in {'propose', 'index', 'status', 'plan', 'review'}:
                raise ValueError('Unknown lifecycle event')
            out.append((ident, event))
        return out

    def states(self):
        states = {}
        for ident, event in self.events():
            logical = event.get('logical_id')
            if not logical:
                continue
            old = states.get(logical)
            if event['previous_event'] != (old['event_id'] if old else None):
                raise ValueError('Broken lifecycle event chain')
            if event['action'] == 'propose':
                revision = Revision.model_validate(event['revision'])
                if revision.identity.key != logical:
                    raise ValueError('Logical identity mismatch')
                if revision.supersedes != (old['revision'].key if old else None):
                    raise ValueError('Broken revision ancestry')
                state = {'revision': revision, 'status': 'candidate', 'index': None, 'validation_policy': None}
            else:
                if old is None or old['revision'].key != event['revision_id']:
                    raise ValueError('Stale lifecycle revision')
                state = {**old}
                if event['action'] == 'index':
                    binding = IndexBinding.model_validate(event['binding'])
                    if (binding.content_hash, binding.metadata_hash) != (old['revision'].content_hash, old['revision'].metadata_hash):
                        raise ValueError('Persisted index has stale metadata')
                    state['index'] = binding
                elif event['action'] == 'status':
                    if event['status'] not in {'active', 'quarantined', 'retired'}:
                        raise ValueError('Unknown lifecycle status')
                    state['status'] = event['status']
                    if event['status'] == 'active':
                        if not event.get('evidence', {}).get('accepted'):
                            raise ValueError('Active revision lacks accepted selection evidence')
                        state['validation_policy'] = event['evidence']['policy_version']
            states[logical] = {**state, 'event_id': ident}
        return states

    def revision(self, version):
        for _, event in self.events():
            if event['action'] == 'propose':
                revision = Revision.model_validate(event['revision'])
                if revision.key == version:
                    return revision
        raise KeyError(version)

    def _append(self, event, expected_event=None):
        if self.db.in_transaction:
            raise ValueError('Lifecycle writes require a clean transaction boundary')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            logical = event.get('logical_id')
            if logical:
                state = self.states().get(logical)
                if (state['event_id'] if state else None) != expected_event:
                    raise ValueError('Concurrent or stale lifecycle write')
                if event['action'] != 'propose' and (state is None or event['revision_id'] != state['revision'].key):
                    raise ValueError('Cannot update an obsolete revision')
                event = {**event, 'previous_event': expected_event}
            if event['action'] == 'plan':
                if any(e['action'] == 'plan' and e['plan_id'] == event['plan_id'] for _, e in self.events()):
                    raise ValueError('Selection plan already exists')
                for pair in event['plan']['pairs']:
                    for key in (pair['with_candidate'], pair['without_candidate']):
                        if self.db.execute('SELECT 1 FROM runs WHERE cell_key=?', (key,)).fetchone():
                            raise ValueError('Cannot register selection after an attempt starts')
            ident = uuid.uuid4().hex
            self.db.execute('INSERT INTO records VALUES (?,?,?,?,?,?,?)',
                (ident, 'memory_lifecycle', None, None, 'lifecycle', now(),
                 dumps({'schema_version': 1, 'classification': 'not-a-model', **event})))
            self.db.commit()
            return ident
        except BaseException:
            self.db.rollback()
            raise

    def propose(self, identity: Identity, content: str, metadata: Metadata, *, expected_event=None):
        old = self.states().get(identity.key)
        tools = {x.api: x for x in metadata.tools}
        coverage = metadata.dependency_coverage
        sources = set(metadata.source_runs)
        for parent_id in metadata.consolidated_from:
            parent = self.revision(parent_id)
            if (parent.identity.tenant, parent.identity.owner, parent.identity.arm, parent.identity.namespace) != (
                    identity.tenant, identity.owner, identity.arm, identity.namespace):
                raise ValueError('Cross-owner or cross-policy consolidation ancestry')
            if parent.metadata.dependency_coverage == 'unknown':
                coverage = 'unknown'
            sources.update(parent.metadata.source_runs)
            for tool in parent.metadata.tools:
                if tool.api in tools and tools[tool.api] != tool:
                    raise ValueError('Consolidation mixes incompatible API versions')
                tools[tool.api] = tool
        metadata = metadata.model_copy(update={'tools': tuple(tools[k] for k in sorted(tools)),
                                               'dependency_coverage': coverage,
                                               'source_runs': tuple(sorted(sources))})
        revision = Revision(identity=identity, content_hash=digest(content.encode()), metadata=metadata,
                            supersedes=old['revision'].key if old else None)
        token = self._append({'action': 'propose', 'logical_id': identity.key,
                              'revision': revision.model_dump(mode='json')}, expected_event)
        return revision, token

    def bind_index(self, revision: Revision, binding: IndexBinding, *, expected_event):
        if (binding.content_hash, binding.metadata_hash) != (revision.content_hash, revision.metadata_hash):
            raise ValueError('Index is stale for content or metadata')
        return self._append({'action': 'index', 'logical_id': revision.identity.key,
            'revision_id': revision.key, 'binding': binding.model_dump()}, expected_event)

    def hold(self, revision: Revision, status: Literal['quarantined', 'retired'], reason: str,
             *, expected_event, evidence=None):
        if status not in {'quarantined', 'retired'} or not reason:
            raise ValueError('Explicit quarantine or retirement reason required')
        state = self.states()[revision.identity.key]
        if state['status'] == 'retired':
            raise ValueError('Retirement is terminal for this revision')
        if status == 'retired' and not evidence:
            raise ValueError('Retirement requires evidence or an explicit owner-decision record')
        return self._append({'action': 'status', 'logical_id': revision.identity.key,
            'revision_id': revision.key, 'status': status, 'reason': reason,
            'evidence': evidence}, expected_event)

    def invalidate_tools(self, current: dict[str, ToolVersion]):
        affected = []
        for state in self.states().values():
            revision = state['revision']
            changed = [x.api for x in revision.metadata.tools if current.get(x.api) != x]
            if changed and state['status'] not in {'retired', 'quarantined'}:
                self.hold(revision, 'quarantined', 'API contract changed or removed: ' + ', '.join(changed),
                          expected_event=state['event_id'], evidence={'tool_changes': [
                              {'before': t.model_dump(), 'after': current[t.api].model_dump() if t.api in current else None}
                              for t in revision.metadata.tools if t.api in changed]})
                affected.append(revision.key)
        return affected

    def invalidate_policy(self):
        affected = []
        for state in self.states().values():
            if state['status'] == 'active' and state['validation_policy'] != self.rule.version:
                revision = state['revision']
                self.hold(revision, 'quarantined', 'Promotion policy changed; new selection evidence required',
                          expected_event=state['event_id'], evidence={'previous_policy': state['validation_policy'],
                                                                    'current_policy': self.rule.version})
                affected.append(revision.key)
        return affected

    def plan(self, plan: ValidationPlan):
        if plan.policy_version != self.rule.version:
            raise ValueError('Selection plan uses another gate policy')
        state = next((s for s in self.states().values() if s['revision'].key == plan.revision), None)
        if state is None or state['status'] not in {'candidate', 'quarantined'}:
            raise ValueError('Selection must target the current unvalidated revision')
        if set(state['revision'].metadata.task_families) != {p.task_family for p in plan.pairs}:
            raise ValueError('Selection must cover every declared task-family scope')
        for family in state['revision'].metadata.task_families:
            pairs = [p for p in plan.pairs if p.task_family == family]
            if len(pairs) < self.rule.min_pairs or len({p.task_id.split('_')[0] for p in pairs}) < self.rule.min_scenario_groups:
                raise ValueError('Planned selection coverage is below the frozen rule')
        if self.freeze()['version'] != plan.base_snapshot:
            raise ValueError('Selection plan must pin the current lifecycle snapshot')
        for pair in plan.pairs:
            for key in (pair.with_candidate, pair.without_candidate):
                if self.db.execute('SELECT 1 FROM runs WHERE cell_key=?', (key,)).fetchone():
                    raise ValueError('Cannot register selection after seeing its outcomes')
        if any(e['action'] == 'plan' and e['plan_id'] == plan.key for _, e in self.events()):
            raise ValueError('Selection plan already exists')
        return self._append({'action': 'plan', 'plan_id': plan.key,
                             'plan': plan.model_dump(mode='json'), 'policy': self.rule.model_dump()})

    def promote(self, plan_id, *, tools, agent_version, model_settings_version, expected_event):
        """Accept only complete preregistered, live, revision-specific selection pairs."""
        registered = next(((ident, e) for ident, e in self.events()
                           if e['action'] == 'plan' and e['plan_id'] == plan_id), None)
        if registered is None:
            raise ValueError('Missing preregistered selection plan')
        plan = ValidationPlan.model_validate(registered[1]['plan'])
        if plan.policy_version != self.rule.version:
            raise ValueError('Gate policy changed since selection was planned')
        if self.freeze()['version'] != plan.base_snapshot:
            raise ValueError('Lifecycle snapshot changed since selection was planned')
        revision = self.revision(plan.revision)
        state = self.states()[revision.identity.key]
        if state['revision'].key != revision.key or state['status'] not in {'candidate', 'quarantined'}:
            raise ValueError('Evidence does not target the current unvalidated revision')
        metadata = revision.metadata
        if set(metadata.task_families) != {p.task_family for p in plan.pairs}:
            raise ValueError('Every promoted task-family scope needs its own selection evidence')
        if metadata.dependency_coverage != 'complete' or not metadata.source_runs:
            raise ValueError('Promotion requires known dependencies and source experience')
        if agent_version != metadata.agent_version or model_settings_version != metadata.model_settings_version:
            raise ValueError('Agent/model compatibility changed')
        if any(tools.get(t.api) != t for t in metadata.tools):
            raise ValueError('API contract changed before promotion')
        if metadata.expires_at is not None and datetime.now(timezone.utc) >= metadata.expires_at:
            raise ValueError('Expired candidate requires a new revision')
        if metadata.index_required and state['index'] is None:
            raise ValueError('Missing versioned retrieval index')
        source_groups = set()
        for source in metadata.source_runs:
            row = self.db.execute('SELECT phase,status,task_id FROM runs WHERE id=?', (source,)).fetchone()
            if row is None or row[0] not in {'train', 'practice', 'native_selection'} or row[1] != 'conclusive':
                raise ValueError('Source must be conclusive learning experience, never evaluation feedback')
            source_groups.add(row[2].split('_')[0])
            source_calls = self.db.execute("SELECT kind,status,data FROM calls WHERE run_id=?",
                                           (source,)).fetchall()
            if (not any(k == 'generation' for k, _, _ in source_calls) or
                any(s != 'live' for _, s, _ in source_calls) or
                any(json.loads(d).get('classification') != 'live' for k, _, d in source_calls
                    if k in {'generation', 'embedding'}) or
                any(not json.loads(d).get('output') for k, _, d in source_calls if k == 'generation')):
                raise ValueError('Source experience lacks live generation evidence')
        if source_groups & ({p.task_id.split('_')[0] for p in plan.pairs} | set(plan.evaluation_groups)):
            raise ValueError('Learning, promotion selection and evaluation groups must be separate')
        registered_at = self.db.execute('SELECT created FROM records WHERE id=?', (registered[0],)).fetchone()[0]
        wins = losses = ties = 0
        proof = []
        by_family = {}
        model_versions = set()
        for pair in plan.pairs:
            observed = []
            for condition, key in [('with_candidate', pair.with_candidate),
                                    ('without_candidate', pair.without_candidate)]:
                run = self.db.execute('SELECT * FROM runs WHERE cell_key=? ORDER BY started DESC LIMIT 1',
                                      (key,)).fetchone()
                if run is None:
                    raise ValueError('Missing planned selection attempt')
                run = dict(zip([x[1] for x in self.db.execute('PRAGMA table_info(runs)')], tuple(run)))
                data = json.loads(run['data'])
                if (run['phase'] != 'lifecycle_selection' or run['status'] != 'conclusive' or
                    run['task_id'] != pair.task_id or run['repetition'] != pair.repetition or
                    run['arm'] != revision.identity.arm or run['started'] < registered_at):
                    raise ValueError('Ineligible selection attempt or wrong task identity')
                binding = {'plan_id': plan_id, 'revision': revision.key, 'condition': condition,
                           'base_snapshot': plan.base_snapshot, 'policy_version': self.rule.version,
                           'task_family': pair.task_family}
                if data.get('gate_validation') != binding:
                    raise ValueError('Attempt is not bound to this candidate and frozen plan')
                if data.get('grade', {}).get('success') != bool(run['success']):
                    raise ValueError('Official grade disagrees with recorded outcome')
                if not data.get('steps'):
                    raise ValueError('Missing actual acting trajectory')
                if any('Number of requests exceeded the limit of ' in output
                       for step in data.get('steps', []) for output in step['outputs']):
                    raise ValueError('Operational request guard makes selection inconclusive')
                calls = [dict(zip([x[1] for x in self.db.execute('PRAGMA table_info(calls)')], tuple(r)))
                         for r in self.db.execute('SELECT * FROM calls WHERE run_id=?', (run['id'],))]
                if not calls or any(c['status'] != 'live' for c in calls):
                    raise ValueError('Unknown or non-live selection requests')
                packets = {c['id']: json.loads(c['data']) for c in calls}
                for call in calls:
                    packet = packets[call['id']]
                    if call['kind'] in {'generation', 'embedding'} and packet.get('classification') != 'live':
                        raise ValueError('Replayed or substituted output cannot promote memory')
                    if call['kind'] == 'generation':
                        if not packet.get('resolved_model') or not packet.get('model') or not packet.get('output'):
                            raise ValueError('Missing actual model identity or output')
                        if packet.get('finish_reasons') != ['STOP']:
                            raise ValueError('Non-conclusive generation finish reason')
                        model_versions.add(tuple(dumps(packet.get(k)) for k in
                            ['model', 'resolved_model', 'temperature', 'thinking_budget', 'max_output_tokens']))
                events = [(kind, json.loads(raw)) for kind, raw in self.db.execute(
                    'SELECT kind,data FROM records WHERE run_id=? ORDER BY rowid', (run['id'],))]
                exposures = [e for kind, e in events if kind == 'exposure']
                intents = [e for kind, e in events if kind == 'exposure_intent']
                saved = [e for kind, e in events if kind == 'saved_state_verification']
                if (not exposures or not intents or len(exposures) != len(intents) or
                    len(exposures) != len(data['steps']) or not saved or
                    not data.get('final_application_hashes') or
                    saved[-1].get('application_hashes') != data.get('final_application_hashes')):
                    raise ValueError('Missing actual exposure or saved-world verification')
                for exposure in exposures:
                    packet = packets.get(exposure['call_id'], {})
                    messages = packet.get('messages')
                    if not messages or digest(messages) != exposure['request_hash'] or digest(messages) != packet.get('request_hash'):
                        raise ValueError('Unverified SDK exposure')
                    text = '\n\n'.join(x['content'] for x in exposure['items']) or '(empty)'
                    if messages[0]['content'] != 'Historical memory, advisory only:\n' + text:
                        raise ValueError('Actual delivered memory differs from exposure')
                    for item in exposure['items']:
                        if item.get('lifecycle_revision') == revision.key:
                            if condition == 'without_candidate' or digest(item['content'].encode()) != revision.content_hash:
                                raise ValueError('Candidate absent-control leak or content mismatch')
                initial = exposures[0]['items']
                has_candidate = any(x.get('lifecycle_revision') == revision.key for x in initial)
                if has_candidate != (condition == 'with_candidate'):
                    raise ValueError('Candidate intervention did not activate at the controlled boundary')
                observed.append({'run': run, 'data': data, 'items': initial, 'prompt': intents[0]['native_prompt_hash']})
            on, off = observed
            if (not on['data'].get('loaded_reset_identity') or
                on['data']['loaded_reset_identity'] != off['data'].get('loaded_reset_identity') or on['prompt'] != off['prompt']):
                raise ValueError('Paired reset or native prompt mismatch')
            other = lambda items: [(x['id'], x.get('layer', ''), x['content'], x.get('lifecycle_revision'))
                                   for x in items if x.get('lifecycle_revision') != revision.key]
            if other(on['items']) != other(off['items']):
                raise ValueError('Other initial memory changed alongside the candidate')
            difference = on['run']['success'] - off['run']['success']
            wins += difference > 0; losses += difference < 0; ties += difference == 0
            proof.append((on['run']['id'], off['run']['id']))
            family = by_family.setdefault(pair.task_family, {'pairs': 0, 'wins': 0, 'losses': 0, 'groups': set()})
            family['pairs'] += 1; family['wins'] += difference > 0; family['losses'] += difference < 0
            family['groups'].add(pair.task_id.split('_')[0])
        if len(model_versions) != 1:
            raise ValueError('Selection model/settings changed across attempts')
        groups = len({p.task_id.split('_')[0] for p in plan.pairs})
        accepted = self.rule.accepts(by_family)
        summary = {'plan_id': plan_id, 'pairs': proof, 'wins': wins, 'losses': losses, 'ties': ties,
                   'scenario_groups': groups, 'accepted': accepted, 'policy_version': self.rule.version,
                   'by_family': {k: {**f, 'groups': sorted(f['groups'])} for k, f in by_family.items()}}
        if not accepted:
            self._append({'action': 'review', 'revision_id': revision.key, 'evidence': summary})
            return summary
        self._append({'action': 'status', 'logical_id': revision.identity.key, 'revision_id': revision.key,
                      'status': 'active', 'reason': 'Preregistered selection criterion met',
                      'evidence': summary}, expected_event)
        return summary

    def freeze(self):
        entries = []
        for logical, state in sorted(self.states().items()):
            entries.append({'logical_id': logical, 'revision': state['revision'].model_dump(mode='json'),
                'status': state['status'], 'event_id': state['event_id'],
                'validation_policy': state['validation_policy'],
                'index': state['index'].model_dump() if state['index'] else None})
        body = {'schema_version': 1, 'policy': self.rule.model_dump(), 'entries': entries}
        return {**body, 'version': digest(body)}


class FrozenGate:
    """Filter native results without reranking or filling rejected positions."""
    def __init__(self, snapshot, *, validation_plan: ValidationPlan | None = None, include_candidate=False):
        body = {k: v for k, v in snapshot.items() if k != 'version'}
        if body.get('schema_version') != 1 or digest(body) != snapshot['version']:
            raise ValueError('Unknown or changed lifecycle snapshot')
        if include_candidate and validation_plan is None:
            raise ValueError('Candidate exposure needs a registered selection plan')
        if validation_plan is not None and (validation_plan.base_snapshot != snapshot['version'] or
                validation_plan.policy_version != Rule.model_validate(body['policy']).version):
            raise ValueError('Selection trial uses another frozen snapshot or policy')
        self.version = snapshot['version']
        self.policy_version = Rule.model_validate(body['policy']).version
        self._snapshot = json.loads(dumps(snapshot))
        self.validation_plan, self.include_candidate = validation_plan, include_candidate
        self.entries = MappingProxyType({x['logical_id']: MappingProxyType({**x, 'revision': Revision.model_validate(x['revision']),
                         'index': IndexBinding.model_validate(x['index']) if x['index'] else None}
                        ) for x in body['entries']})

    def select(self, items, *, tenant, owner, arm, namespace, task_family, tools,
               agent_version, model_settings_version, index_bindings=None, at=None, phase='evaluation'):
        if self.validation_plan is not None and phase != 'lifecycle_selection':
            raise ValueError('Candidate trial context cannot enter evaluation or practice')
        at = at or datetime.now(timezone.utc)
        if at.tzinfo is None:
            raise ValueError('Lookup time requires a timezone')
        allowed, decisions = [], []
        for item in items:
            identity = Identity(tenant=tenant, owner=owner, arm=arm, namespace=namespace,
                                native_id=item['id'], layer=item.get('layer', ''))
            state = self.entries.get(identity.key)
            reasons = []
            if state is None:
                reasons.append('unregistered')
            else:
                revision = state['revision']; metadata = revision.metadata
                trial = (self.include_candidate and self.validation_plan is not None and
                         self.validation_plan.revision == revision.key and state['status'] in {'candidate', 'quarantined'})
                if state['status'] != 'active' and not trial: reasons.append('not-active')
                if state['status'] == 'active' and state['validation_policy'] != self.policy_version:
                    reasons.append('gate-policy-changed')
                if digest(item['content'].encode()) != revision.content_hash: reasons.append('content-changed')
                if task_family not in metadata.task_families: reasons.append('out-of-scope')
                if metadata.dependency_coverage != 'complete': reasons.append('unknown-dependencies')
                if any(tools.get(t.api) != t for t in metadata.tools): reasons.append('api-version-changed')
                if agent_version != metadata.agent_version: reasons.append('agent-version-changed')
                if model_settings_version != metadata.model_settings_version: reasons.append('model-version-changed')
                if metadata.expires_at is not None and at >= metadata.expires_at: reasons.append('expired')
                binding = state['index']
                if metadata.index_required and (binding is None or
                    (binding.content_hash, binding.metadata_hash) != (revision.content_hash, revision.metadata_hash) or
                    (index_bindings or {}).get(revision.key) != binding):
                    reasons.append('index-unverified-or-stale')
            decisions.append({'id': item['id'], 'layer': item.get('layer', ''),
                              'revision': state['revision'].key if state else None,
                              'accepted': not reasons, 'reasons': reasons})
            if not reasons:
                allowed.append({**item, 'lifecycle_revision': state['revision'].key,
                                'lifecycle_snapshot': self.version})
        return allowed, decisions


class GatedMemory:
    """Opt-in read-only wrapper using the existing select/export agent interface."""
    def __init__(self, native, gate: FrozenGate, context):
        self.native, self.gate, self.context = native, gate, context
        self.arm = native.arm

    @property
    def version(self):
        return digest({'native': self.native.version, 'lifecycle': self.gate.version,
                       'trial': self.gate.validation_plan.key if self.gate.validation_plan else None,
                       'include_candidate': self.gate.include_candidate})

    def export(self):
        return {'native': self.native.export(), 'lifecycle': json.loads(dumps(self.gate._snapshot)),
                'version': self.version}

    def select(self, query):
        items = self.native.select(query)
        scope = self.native.vertex.scope
        context = dict(self.context())
        if context.get('phase', scope.get('phase')) != scope.get('phase'):
            raise ValueError('Lookup phase disagrees with actual run scope')
        context['phase'] = scope.get('phase', 'evaluation')
        selected, decisions = self.gate.select(items, **context)
        self.native.vertex.ledger.record('memory_lifecycle_lookup', {
            'classification': 'not-a-model', 'query': query, 'snapshot': self.gate.version,
            'native_version': self.native.version, 'offered': items, 'selected': selected,
            'decisions': decisions}, scope.get('run_id'), self.arm, scope.get('phase'))
        return selected

    def observe(self, *args, **kwargs):
        raise ValueError('Frozen lifecycle memory cannot learn')
