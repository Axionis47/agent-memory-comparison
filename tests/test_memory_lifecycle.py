"""Software-only metadata checks. No model calls or fabricated model answers.

Active snapshots below are explicit in-memory state fixtures, never promotions
or experiment evidence. All durable writes use pytest's temporary directory.
"""
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pytest

from mc.core import Ledger, digest
from memory_lifecycle import (FrozenGate, Identity, IndexBinding, Metadata, Registry,
                              Rule, TrialPair, ValidationPlan, tool_versions)


CONTENT = 'Metadata-only memory content, not a model answer.'
TOOLS = tool_versions({'phone.search_contacts': {'parameters': {'relationship': 'string'}},
                       'venmo.create_transaction': {'parameters': {'amount': 'number'}}}, 'source-v1')


def identity(name='entry', **updates):
    return Identity(tenant='pilot', owner='owner', arm='mem0', namespace='lifecycle-test',
                    native_id=name, **updates)


def metadata(**updates):
    values = dict(task_families=('contacts',), tools=(TOOLS['phone.search_contacts'],),
                  dependency_coverage='complete', agent_version='agent-v1', model_settings_version='model-v1')
    return Metadata(**{**values, **updates})


@pytest.fixture
def registry(tmp_path):
    ledger = Ledger(tmp_path / 'metadata-only.sqlite')
    yield Registry(ledger, Rule())
    ledger.db.close()


def active_fixture(registry):
    snapshot = registry.freeze()
    for item in snapshot['entries']:
        item['status'] = 'active'
        item['validation_policy'] = registry.rule.version
    snapshot['version'] = digest({k: v for k, v in snapshot.items() if k != 'version'})
    return snapshot


def lookup(gate, **updates):
    context = dict(tenant='pilot', owner='owner', arm='mem0', namespace='lifecycle-test',
                   task_family='contacts', tools=TOOLS, agent_version='agent-v1',
                   model_settings_version='model-v1')
    return gate.select([{'id': 'entry', 'content': CONTENT}], **{**context, **updates})


def test_metadata_changes_make_new_unvalidated_revision_and_old_index_cannot_transfer(registry):
    first, token = registry.propose(identity(), CONTENT, metadata(index_required=True))
    binding = IndexBinding(content_hash=first.content_hash, metadata_hash=first.metadata_hash,
        index_version='index-v1', embedding_version='embedding-v1', dimension=1536, normalizer_version='norm-v1')
    token = registry.bind_index(first, binding, expected_event=token)
    snapshot = active_fixture(registry)
    assert lookup(FrozenGate(snapshot), index_bindings={first.key: binding})[0]
    second, _ = registry.propose(identity(), CONTENT, metadata(index_required=True,
        task_families=('contacts', 'payments')), expected_event=token)
    assert first.content_hash == second.content_hash and first.key != second.key
    assert first.metadata_hash != second.metadata_hash and second.supersedes == first.key
    assert registry.states()[identity().key]['status'] == 'candidate'
    assert not lookup(FrozenGate(registry.freeze()))[0]
    with pytest.raises(ValueError, match='stale'):
        registry.bind_index(second, binding, expected_event=registry.states()[identity().key]['event_id'])
    assert lookup(FrozenGate(snapshot), index_bindings={first.key: binding})[0]


def test_api_invalidation_is_selective_and_propagates_consolidation_dependencies(registry):
    parent, _ = registry.propose(identity('parent'), CONTENT, metadata())
    child, _ = registry.propose(identity('child'), CONTENT, metadata(tools=(), consolidated_from=(parent.key,)))
    other, _ = registry.propose(identity('other'), CONTENT, metadata(tools=(TOOLS['venmo.create_transaction'],)))
    assert child.metadata.tools == parent.metadata.tools
    changed = {**TOOLS, **tool_versions({'phone.search_contacts': {'parameters': {'relationship_filter': 'string'}}}, 'source-v2')}
    assert set(registry.invalidate_tools(changed)) == {parent.key, child.key}
    assert registry.states()[other.identity.key]['status'] == 'candidate'
    assert registry.revision(parent.key) == parent


def test_behavior_change_without_schema_change_is_incompatible_and_unknown_ancestry_stays_unknown(registry):
    revision, _ = registry.propose(identity(), CONTENT, metadata(dependency_coverage='unknown'))
    child, _ = registry.propose(identity('child'), CONTENT, metadata(consolidated_from=(revision.key,)))
    assert child.metadata.dependency_coverage == 'unknown'
    changed = tool_versions({'phone.search_contacts': {'parameters': {'relationship': 'string'}}}, 'source-v2')
    assert TOOLS['phone.search_contacts'].definition_hash == changed['phone.search_contacts'].definition_hash
    assert len(registry.invalidate_tools({**TOOLS, **changed})) == 2


def test_scope_content_model_and_current_api_versions_are_checked_at_lookup(registry):
    registry.propose(identity(), CONTENT, metadata())
    gate = FrozenGate(active_fixture(registry))
    assert lookup(gate)[0]
    assert not lookup(gate, owner='another-owner')[0]
    assert not lookup(gate, task_family='payments')[0]
    assert not lookup(gate, tools={})[0]
    assert not lookup(gate, agent_version='agent-v2')[0]
    assert not lookup(gate, model_settings_version='model-v2')[0]
    selected, decisions = gate.select([{'id': 'entry', 'content': CONTENT + 'changed'}],
        tenant='pilot', owner='owner', arm='mem0', namespace='lifecycle-test', task_family='contacts',
        tools=TOOLS, agent_version='agent-v1', model_settings_version='model-v1')
    assert not selected and 'content-changed' in decisions[0]['reasons']
    with pytest.raises(TypeError):
        gate.entries[identity().key]['status'] = 'active'


def test_missing_stale_or_differently_embedded_index_is_blocked(registry):
    revision, token = registry.propose(identity(), CONTENT, metadata(index_required=True))
    gate = FrozenGate(active_fixture(registry))
    assert 'index-unverified-or-stale' in lookup(gate)[1][0]['reasons']
    binding = IndexBinding(content_hash=revision.content_hash, metadata_hash=revision.metadata_hash,
        index_version='index-v1', embedding_version='embedding-v1', dimension=1536, normalizer_version='norm-v1')
    registry.bind_index(revision, binding, expected_event=token)
    gate = FrozenGate(active_fixture(registry))
    assert lookup(gate, index_bindings={revision.key: binding})[0]
    assert not lookup(gate, index_bindings={revision.key: binding.model_copy(update={'embedding_version': 'v2'})})[0]


def test_retirement_is_terminal_but_new_revision_is_a_candidate(registry):
    revision, token = registry.propose(identity(), CONTENT, metadata())
    token = registry.hold(revision, 'retired', 'Source was contradicted', expected_event=token,
                          evidence={'review': 'metadata-only review reference'})
    with pytest.raises(ValueError, match='terminal'):
        registry.hold(revision, 'quarantined', 'Undo retirement', expected_event=token)
    next_revision, _ = registry.propose(identity(), CONTENT + ' revised', metadata(), expected_event=token)
    assert next_revision.supersedes == revision.key
    assert registry.states()[identity().key]['status'] == 'candidate'


def test_stale_writer_cannot_overwrite_or_bind_an_obsolete_revision(registry):
    revision, token = registry.propose(identity(), CONTENT, metadata())
    second = Registry(Ledger(Path(registry.db.execute('PRAGMA database_list').fetchone()[2])), Rule())
    try:
        registry.hold(revision, 'quarantined', 'API changed', expected_event=token)
        with pytest.raises(ValueError, match='stale'):
            second.propose(identity(), CONTENT + ' revised', metadata(), expected_event=token)
        assert len(registry.events()) == 2
        assert second.states()[identity().key]['status'] == 'quarantined'
    finally:
        second.db.close()


def plan_for(registry, revision, **updates):
    values = dict(revision=revision.key, policy_version=registry.rule.version,
        base_snapshot=registry.freeze()['version'], evaluation_groups=('heldout',), pairs=tuple(
            TrialPair(task_id=f'{group}_1', task_family='contacts', repetition=rep,
                      with_candidate=f'on-{group}-{rep}', without_candidate=f'off-{group}-{rep}')
            for group in ['select-a', 'select-b'] for rep in [0, 1]))
    return ValidationPlan(**{**values, **updates})


def test_no_posthoc_plan_or_evaluation_group_leakage(registry):
    revision, _ = registry.propose(identity(), CONTENT, metadata())
    plan = plan_for(registry, revision)
    with pytest.raises(ValueError, match='Evaluation'):
        plan_for(registry, revision, evaluation_groups=('select-a',))
    registry.db.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?)',
        ('metadata-only', plan.pairs[0].with_candidate, 'mem0', 'lifecycle_selection', 'select-a_1',
         0, 'inconclusive', None, 0, 0, '{}'))
    registry.db.commit()
    with pytest.raises(ValueError, match='after'):
        registry.plan(plan)


def test_candidates_only_enter_preregistered_selection_context(registry):
    revision, _ = registry.propose(identity(), CONTENT, metadata())
    snapshot = registry.freeze(); plan = plan_for(registry, revision)
    registry.plan(plan)
    assert not lookup(FrozenGate(snapshot))[0]
    with pytest.raises(ValueError, match='plan'):
        FrozenGate(snapshot, include_candidate=True)
    gate = FrozenGate(snapshot, validation_plan=plan, include_candidate=True)
    with pytest.raises(ValueError, match='evaluation'):
        lookup(gate)
    assert lookup(gate, phase='lifecycle_selection')[0]
    assert not lookup(FrozenGate(snapshot, validation_plan=plan), phase='lifecycle_selection')[0]
    with pytest.raises(ValueError, match='dependencies and source'):
        registry.promote(plan.key, tools=TOOLS, agent_version='agent-v1', model_settings_version='model-v1',
                         expected_event=registry.states()[identity().key]['event_id'])


def test_rule_is_scope_specific_and_does_not_treat_ties_as_benefit():
    rule = Rule()
    supported = dict(pairs=4, groups={'a', 'b'}, wins=2, losses=0)
    assert rule.accepts({'contacts': supported})
    assert not rule.accepts({})
    assert not rule.accepts({'contacts': supported, 'payments': {**supported, 'wins': 0}})
    assert not rule.accepts({'contacts': {**supported, 'losses': 1}})
    assert not rule.accepts({'contacts': {**supported, 'groups': {'a'}}})


def test_policy_change_and_unknown_schema_do_not_silently_reuse_acceptance(registry):
    registry.propose(identity(), CONTENT, metadata())
    snapshot = active_fixture(registry)
    snapshot['policy'] = Rule(min_wins=3).model_dump()
    snapshot['version'] = digest({k: v for k, v in snapshot.items() if k != 'version'})
    assert 'gate-policy-changed' in lookup(FrozenGate(snapshot))[1][0]['reasons']
    registry.ledger.record('memory_lifecycle', {'schema_version': 2})
    with pytest.raises(ValueError, match='migration'):
        registry.freeze()


def test_expiry_and_snapshot_tampering_are_rejected(registry):
    registry.propose(identity(), CONTENT, metadata(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
    snapshot = active_fixture(registry)
    assert 'expired' in lookup(FrozenGate(snapshot))[1][0]['reasons']
    snapshot['entries'][0]['status'] = 'retired'
    with pytest.raises(ValueError, match='changed'):
        FrozenGate(snapshot)


def test_index_change_after_selection_plan_requires_new_validation(registry):
    revision, token = registry.propose(identity(), CONTENT, metadata())
    plan = plan_for(registry, revision); registry.plan(plan)
    registry.bind_index(revision, IndexBinding(content_hash=revision.content_hash,
        metadata_hash=revision.metadata_hash, index_version='index-v2', embedding_version='embedding-v2',
        dimension=1536, normalizer_version='normalizer-v2'), expected_event=token)
    with pytest.raises(ValueError, match='snapshot changed'):
        registry.promote(plan.key, tools=TOOLS, agent_version='agent-v1', model_settings_version='model-v1',
                         expected_event=registry.states()[identity().key]['event_id'])
