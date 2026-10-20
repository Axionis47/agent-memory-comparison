"""Metadata checks on actual stored artifacts, not live-model evidence."""
from memory_three_effect import (ARMS, TASKS, SOURCES, ROOT, cells, project,
                                 remove_target, authentication_values)
from mc.core import read_json


def test_planned_pairs_are_complete_unique_and_rotated():
    planned = cells({'test': 'metadata-only'})
    assert len(planned) == len({c.key for c in planned}) == 54
    for arm in ARMS:
        for task in TASKS:
            for mode in ['memory_on', 'memory_off', 'target_removed']:
                assert {c.repetition for c in planned if c.arm == arm and c.task_id == task
                        and c.mode == mode} == {0, 1}


def test_native_skill_and_strategy_removals_preserve_other_content():
    for arm, start_marker, end_marker, identity in [
        ('trace2skill', '## Best Practices\n', '\n## ', 'SKILL.md'),
        ('gepa', '2. **Process and Track Changes:**', '**Applicability Conditions:**', 'gepa-artifact'),
    ]:
        state = read_json(ROOT / SOURCES[arm] / 'artifact.json')
        text = state['files']['SKILL.md'] if arm == 'trace2skill' else state['text']
        start = text.index(start_marker); end = text.index(end_marker, start + len(start_marker))
        target = {'id': identity, 'text': text[start:end]}
        actual = remove_target(arm, [{'id': identity, 'content': text}], target)
        assert actual == [{'id': identity, 'content': text[:start] + text[end:]}]
        assert state == read_json(ROOT / SOURCES[arm] / 'artifact.json')


def test_projection_removes_observed_auth_and_episode_removal_is_scoped():
    state = read_json(ROOT / SOURCES['recmem'] / 'artifact.json')
    items = [{'id': str(p['id']), 'layer': layer, 'content': p['payload']['text']}
             for layer, points in state['layers'].items() for p in points]
    secrets = authentication_values(None)
    assert any(secret in x['content'] for x in items for secret in secrets)
    safe = project(items, secrets)
    assert [x['id'] for x in safe] == [x['id'] for x in items]
    assert not any(secret in x['content'] for x in safe for secret in secrets)
    episode = next(x for x in safe if x['layer'] == 'episodic')
    target = {'id': episode['id'], 'layer': episode['layer']}
    reduced = remove_target('recmem', safe, target)
    assert len(reduced) == len(safe) - 1
    assert all(x in safe for x in reduced)
    assert all(x['id'] != episode['id'] or x['layer'] != 'episodic' for x in reduced)
