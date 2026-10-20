"""Matched, repeated exposure and item-removal checks for three frozen policies.

All tasks, memories and removal rules are frozen before acting outcomes. This is
a known-case diagnostic using one common current actor, not an architecture rank
or a replay of the earlier pilot's different exposure schedule.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
from pathlib import Path

from mc.core import Inconclusive, WORLD, digest, dumps, read_json, serial_lock, write_json
from growth import runtime
from growth.runtime import Cell, Ledger, ROOT, RESULTS, bind, mark, source_identity
from growth.memory import Memory
from growth.agent import solve
from growth.__main__ import require_conclusive, verify
from memory_effect import DiagnosticVertex
from gepa_retention import reconcile_closed_timeout


OUT = RESULTS / 'three-memory-effect'
PHASE = 'three_memory_effect'
ARMS = ['trace2skill', 'gepa', 'recmem']
TASKS = ['530b157_1', '6ea6792_2', '68ee2c9_2']
MODES = ['memory_on', 'memory_off', 'target_removed']
SOURCES = {
    'trace2skill': 'results/memories/trace2skill',
    'recmem': 'results/memories/recmem',
    'gepa': 'results/growth-v3/memories/frozen--3-gepa',
}


def authentication_values(ledger):
    values = set()
    paths = [ROOT / 'results/ledger.sqlite', *sorted((ROOT / 'results').glob('growth-v*/ledger.sqlite'))]
    for path in paths:
        db = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
        try:
            for (raw,) in db.execute('SELECT data FROM runs'):
                data = json.loads(raw)
                values.update(data.get('authentication_values', []))
                values.update(runtime.secrets_from(data.get('steps', [])))
                for step in data.get('steps', []):
                    if re.search(r'print\(\w*password\)', '\n'.join(step['inputs'])):
                        for output in step['outputs']:
                            value = output.strip()
                            if value and '\n' not in value and not value.startswith('Execution '):
                                values.add(value)
        finally:
            db.close()
    return values - {'', 'string', '[AUTH REDACTED]', 'None', 'null', 'True', 'False', '[]', '{}'}


def project(items, secrets):
    """Redact actual auth values, without creating lessons or correcting advice."""
    projected = runtime.redact(items, secrets)
    for item in projected:
        item['content'] = re.sub(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+',
                                 '[AUTH REDACTED]', item['content'])
    return projected


def remove_target(arm, items, target):
    if arm == 'recmem':
        return [x for x in items if not (x['id'] == target['id'] and x.get('layer') == target['layer'])]
    result = []
    for item in items:
        if item['id'] != target['id']:
            result.append(item); continue
        content = item['content']
        if content.count(target['text']) != 1:
            raise Inconclusive('Frozen target span is absent or ambiguous')
        result.append({**item, 'content': content.replace(target['text'], '', 1)})
    return result


class ExposurePolicy:
    def __init__(self, native, mode, target, secrets, key):
        self.native, self.mode, self.target, self.secrets, self.key = native, mode, target, secrets, key
        self.arm = native.arm

    @property
    def version(self):
        return self.native.version

    def export(self):
        return self.native.export()

    def select(self, query):
        raw = self.native.select(query)
        safe = project(raw, self.secrets)
        delivered = ([] if self.mode == 'memory_off' else
                     remove_target(self.arm, safe, self.target) if self.mode == 'target_removed' else safe)
        if any(value in dumps(delivered) for value in self.secrets):
            raise Inconclusive('Authentication value survived the exposure projection')
        mark(self.native.vertex.ledger, 'three_memory_selection', {
            'key': self.key, 'mode': self.mode, 'query': query, 'native_items': raw,
            'projected_items': safe, 'offered_items': delivered, 'target': self.target,
            'native_version': self.version, 'auth_projection_changed': raw != safe,
            'target_present_before_removal': any(
                x['id'] == self.target['id'] and
                (x.get('layer') == self.target['layer'] if self.arm == 'recmem'
                 else self.target['text'] in x['content']) for x in safe),
            'intervention': 'after native retrieval, before common packing; no replacement or backfill',
        }, self.arm, PHASE, self.native.vertex.scope.get('run_id'))
        return delivered


def clone(arm, vertex, entry):
    source = ROOT / SOURCES[arm]
    namespace = 'three-effect-' + arm + '-' + entry['version'][:12]
    destination = RESULTS / 'memories' / namespace
    if not destination.exists():
        shutil.copytree(source, destination, ignore=shutil.ignore_patterns('.lock', 'optimizer-*'))
    native = Memory(arm, vertex, namespace=namespace)
    native.read_only = True
    if digest(native.export()) != entry['version']:
        native.close()
        raise Inconclusive('Reopened native memory differs from source')
    return native


def verify_sources(protocol, ledger):
    verify(ledger)
    if protocol['driver_sha256'] != digest(Path(__file__).read_bytes()):
        raise Inconclusive('Diagnostic driver changed after freeze')
    if protocol['shared_diagnostic_sha256'] != digest((ROOT / 'memory_effect.py').read_bytes()):
        raise Inconclusive('Shared diagnostic provider changed after freeze')
    if protocol['source_identity'] != source_identity():
        raise Inconclusive('Common acting source changed')
    for arm, entry in protocol['memories'].items():
        if digest(read_json(ROOT / SOURCES[arm] / 'artifact.json')) != entry['version']:
            raise Inconclusive('Historical source artifact changed')
    for task, checksum in protocol['task_spec_hashes'].items():
        if digest((WORLD / 'data/tasks' / task / 'specs.json').read_bytes()) != checksum:
            raise Inconclusive('Task input changed')


def prepare(ledger, vertex, secrets):
    path = OUT / 'protocol.json'
    if path.exists():
        protocol = read_json(path); verify_sources(protocol, ledger); return protocol
    memories = {}
    for arm in ARMS:
        state = read_json(ROOT / SOURCES[arm] / 'artifact.json')
        memories[arm] = {'source': SOURCES[arm], 'version': digest(state), 'targets': {}}
        if arm == 'trace2skill':
            text = state['files']['SKILL.md']
            start = text.index('## Best Practices\n'); end = text.index('\n## ', start + 4)
            target = {'id': 'SKILL.md', 'label': 'Best Practices section', 'text': text[start:end]}
            memories[arm]['targets'] = {task: target for task in TASKS}
        elif arm == 'gepa':
            text = state['text']
            start = text.index('2. **Process and Track Changes:**')
            end = text.index('**Applicability Conditions:**', start)
            target = {'id': 'gepa-artifact', 'label': 'tracking changes and subsequent updated-path operations',
                      'text': text[start:end]}
            memories[arm]['targets'] = {task: target for task in TASKS}
    # Actual native retrieval chooses the episode to remove, before new task outcomes.
    entry = memories['recmem']; native = clone('recmem', vertex, entry)
    try:
        for task in TASKS:
            instruction = read_json(WORLD / 'data/tasks' / task / 'specs.json')['instruction']
            query = dumps({'task': instruction, 'latest_action_observation': None})
            with vertex.scoped(arm='recmem', phase='three_memory_probe', task_id=task):
                before = native.export(); selected = native.select(query)
                if native.export() != before:
                    raise Inconclusive('Preparation retrieval mutated memory')
            episode = next((x for x in selected if x.get('layer') == 'episodic'), None)
            if episode is None:
                raise Inconclusive('No native episode available for predeclared removal')
            safe = project([episode], secrets)[0]
            target = {'id': episode['id'], 'layer': 'episodic',
                      'label': 'highest-ranked native episodic result for the initial task query',
                      'text': safe['content'], 'score_at_preparation': episode['score']}
            entry['targets'][task] = target
            mark(ledger, 'three_memory_probe', {'task': task, 'query': query,
                 'native_selected': selected, 'target': target}, 'recmem', 'three_memory_probe')
    finally:
        native.close()
    protocol = {
        'id': 'three-memory-effect-v1', 'arms': ARMS, 'tasks': TASKS,
        'modes': MODES, 'repetitions': 2, 'planned': 54, 'memories': memories,
        'independent_variable': 'Memory exposure: full, withheld, or one predeclared content group removed',
        'removal_schedule': 'All target-removal attempts are planned regardless of on/off outcomes',
        'removal_boundary': 'After native retrieval, before packing, in both discovery and acting channels; no backfill',
        'selection': 'Known tasks selected to test earlier grocery and GEPA examples; exploratory known-case diagnostic',
        'handoff': {'trace2skill_and_recmem': 'Exact original pilot frozen memory artifacts; no reconstruction of lessons',
                    'gepa': 'Persisted nonempty retention-diagnostic candidate 2',
                    'actor': 'One common current growth actor, including step-adaptive retrieval and tool search',
                    'scope': 'New within-policy exposure comparisons; changed acting integration prevents treating this as an exact pilot replay',
                    'histories': 'Learning histories differ across methods; do not rank architectures from these scores'},
        'auth_projection': 'Redact recognised observed authentication values and JWTs after native selection; original stores and vectors remain unchanged',
        'projection_effect': 'Native vectors index original content; redaction changes delivered text only and is recorded; no semantic corrections',
        'source_identity': source_identity(), 'driver_sha256': digest(Path(__file__).read_bytes()),
        'shared_diagnostic_sha256': digest((ROOT / 'memory_effect.py').read_bytes()),
        'task_spec_hashes': {t: digest((WORLD / 'data/tasks' / t / 'specs.json').read_bytes()) for t in TASKS},
        'model_settings': runtime.settings().__dict__,
        'resolved_model': ledger.records('experiment_freeze')[-1]['data']['resolved_model'],
        'learning': 'None; new feedback never updates any memory',
        'limits': 'Two repetitions, known tasks, selected item may be irrelevant, removal may not activate on every retrieval; context length and subsequent trajectories change',
        'recovery': 'Preserve conclusive outcomes; stop on infrastructure/provider failures; resume only missing or inconclusive attempts after reconciliation',
    }
    write_json(path, protocol)
    mark(ledger, 'three_memory_protocol', {'key': digest(protocol), 'protocol': protocol,
         'driver_source': Path(__file__).read_text()}, phase='three_memory_preparation')
    return protocol


def cells(protocol):
    key = digest(protocol); result = []
    for repetition in range(2):
        for index, task in enumerate(TASKS):
            offset = (index + repetition) % 3
            for n, arm in enumerate(ARMS[offset:] + ARMS[:offset]):
                shift = (index + repetition + n) % 3
                modes = MODES[shift:] + MODES[:shift]
                if repetition:
                    modes = modes[::-1]
                result += [Cell(arm=arm, phase=PHASE, task_id=task, checkpoint=-5,
                                repetition=repetition, mode=mode, candidate=key) for mode in modes]
    return result


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--prepare', action='store_true')
    args = parser.parse_args(); bind()
    with serial_lock():
        ledger = Ledger(); vertex = None
        try:
            verify(ledger); reconcile_closed_timeout(ledger)
            secrets = authentication_values(ledger)
            vertex = DiagnosticVertex(ledger)
            vertex.expected_resolved_model = ledger.records('experiment_freeze')[-1]['data']['resolved_model']
            protocol = prepare(ledger, vertex, secrets); key = digest(protocol)
            verify_sources(protocol, ledger)
            if args.prepare:
                print(json.dumps({'key': key, 'planned': 54, 'sources': {
                    arm: v['version'] for arm, v in protocol['memories'].items()}})); return
            for cell in cells(protocol):
                native = clone(cell.arm, vertex, protocol['memories'][cell.arm])
                try:
                    policy = ExposurePolicy(native, cell.mode,
                        protocol['memories'][cell.arm]['targets'][cell.task_id], secrets, key)
                    with vertex.scoped(diagnostic_key=key, exposure_mode=cell.mode):
                        run = solve(cell, policy, vertex)
                    require_conclusive(run)
                    from memory_three_analysis import analyse
                    analyse(final=False)
                finally:
                    native.close()
            verify_sources(protocol, ledger)
            mark(ledger, 'three_memory_complete', {'key': key, 'planned': 54}, phase='three_memory_reporting')
            from memory_three_analysis import analyse
            analyse(final=True)
        finally:
            if vertex is not None:
                vertex.sdk.close()
            ledger.db.close()


if __name__ == '__main__':
    main()
