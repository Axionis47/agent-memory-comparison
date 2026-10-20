"""Read-only, paired memory-exposure diagnostic on existing AppWorld cases.

Reuses the frozen actor and native search. No authored lessons, model substitutes,
learning, task edits, or changes to the original experimental populations.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import shutil
import tarfile
from pathlib import Path

from mc.core import Inconclusive, WORLD, digest, read_json, serial_lock, write_json
from growth import runtime
from growth.runtime import Cell, Ledger, ROOT, RESULTS, bind, mark, source_identity
from growth.memory import Memory
from growth.agent import solve
from growth.provider import Vertex
from growth.__main__ import ensure_known_calls, require_conclusive, verify
from gepa_retention import reconcile_closed_timeout


OUT = RESULTS / 'memory-effect'
TASKS = ['34d9492_1', 'e85d92a_3', 'd0b1f43_1', 'aa8502b_1']
ARMS = ['mem0', 'ace']
SOURCE = {
    (arm, task): ('smoke-' + arm + '-15bc2e0e56d9' if task == TASKS[0]
                  else 'frozen-6-' + arm)
    for arm in ARMS for task in TASKS
}
ACE_TARGETS = {
    TASKS[0]: ['sai-00001', 'sai-00002', 'err-00003', 'ph-00004'],
    TASKS[1]: ['sai-00002', 'sai-00005', 'err-00001'],
    TASKS[2]: ['sai-00004', 'sai-00006'],
    TASKS[3]: ['sai-00007'],
}
MEM0_PATTERNS = {
    TASKS[0]: r'file_system\.(?:move_file|show_file|create_directory)|created_at',
    TASKS[1]: r'search_songs|play_count|search_artists',
    TASKS[2]: r'search_contacts|show_transactions|roommate',
    TASKS[3]: r'follow_artist|followed_artist|liked_song|song_library',
}


class ExposurePolicy:
    """An exposure intervention, not a replacement memory algorithm."""
    def __init__(self, native, mode, target_ids, key):
        self.native, self.mode, self.target_ids, self.key = native, mode, set(target_ids), key
        self.arm = native.arm

    @property
    def version(self):
        return self.native.version

    def export(self):
        return self.native.export()

    def select(self, query):
        original = self.native.select(query)
        delivered = original
        if self.mode == 'memory_off':
            delivered = []
        elif self.mode == 'target_removed':
            if self.arm == 'mem0':
                delivered = [x for x in original if x['id'] not in self.target_ids]
            else:
                delivered = [{**x, 'content': '\n'.join(
                    line for line in x['content'].split('\n')
                    if not any(line.startswith('[' + ident + ']') for ident in self.target_ids))}
                    for x in original]
        mark(self.native.vertex.ledger, 'memory_effect_native_selection', {
            'key': self.key, 'mode': self.mode, 'query': query,
            'native_items': original, 'exposed_items': delivered,
            'removed_target_ids': sorted(self.target_ids) if self.mode == 'target_removed' else [],
            'native_version': self.version,
        }, self.arm, 'memory_effect', self.native.vertex.scope.get('run_id'))
        return delivered


class DiagnosticVertex(Vertex):
    def generate(self, *args, **kwargs):
        result = super().generate(*args, **kwargs)
        if result['resolved_model'] != self.expected_resolved_model:
            self.ledger.settle(result['call_id'], 'inconclusive', None, result)
            raise Inconclusive('Resolved model differs from diagnostic frozen identity')
        return result


def make_protocol(ledger):
    memories = {}
    for arm in ARMS:
        for task in TASKS:
            folder = RESULTS / 'memories' / SOURCE[arm, task]
            artifact = read_json(folder / 'artifact.json')
            if arm == 'ace':
                targets = ACE_TARGETS[task]
                if any('[' + ident + ']' not in artifact['text'] for ident in targets):
                    raise Inconclusive('Predeclared ACE target missing from source')
            else:
                targets = [x['id'] for x in artifact['entries']
                           if re.search(MEM0_PATTERNS[task], x['memory'], re.I)]
                if not targets:
                    raise Inconclusive('No native Mem0 entries match predeclared target')
            memories[arm + ':' + task] = {
                'source_namespace': SOURCE[arm, task], 'version': digest(artifact),
                'target_ids': targets,
                'target_selection': (ACE_TARGETS[task] if arm == 'ace' else MEM0_PATTERNS[task]),
            }
    return {
        'id': 'memory-effect-v1', 'tasks': TASKS, 'arms': ARMS, 'repetitions': 2,
        'primary_modes': ['memory_on', 'memory_off'], 'planned_primary_cells': 32,
        'independent_variable': 'Exposure of the same frozen native memory to both acting and tool-search models',
        'off_boundary': 'Native retrieval still runs and is measured; its content is withheld from both channels',
        'target_rule': 'After all primary cells, run target_removed twice only for arm/task pairs with two on passes and two off failures',
        'target_intervention': 'Remove only predeclared existing entries/bullets after native selection; do not regenerate, replace or backfill',
        'target_interpretation': 'A repeated loss after removal supports a contribution of the removed set; content length and downstream trajectories also change',
        'selection': 'Known cases chosen before new outcomes from prior documented memory/action examples; diagnostic, not held-out generalisation',
        'memories': memories,
        'task_spec_hashes': {t: digest((WORLD / 'data/tasks' / t / 'specs.json').read_bytes()) for t in TASKS},
        'source_identity': source_identity(),
        'driver_sha256': digest(Path(__file__).read_bytes()),
        'model_settings': runtime.settings().__dict__,
        'resolved_model': ledger.records('experiment_freeze')[-1]['data']['resolved_model'],
        'learning': 'None; evaluation feedback never enters native memory',
        'recovery': 'Stop on provider or supporting failure; never rerun conclusive diagnostic cells',
        'limitations': ['two repetitions', 'known cases', 'historical memory construction and input defects remain disclosed',
                        'no architecture-wide or statistical superiority claim', 'model alias, execution order, provider and host timing variation'],
    }


def check_sources(protocol, ledger):
    verify(ledger)
    for task, expected in protocol['task_spec_hashes'].items():
        if digest((WORLD / 'data/tasks' / task / 'specs.json').read_bytes()) != expected:
            raise Inconclusive('Task input changed')
    # Secure evidence is used only to recognise authentication values, not answers.
    secrets = set()
    for row in ledger.db.execute('SELECT data FROM runs'):
        data = json.loads(row[0]); secrets.update(data.get('authentication_values', []))
        for step in data.get('steps', []):
            if re.search(r'print\(\w*password\)', '\n'.join(step['inputs'])):
                for output in step['outputs']:
                    value = output.strip()
                    if value and '\n' not in value and not value.startswith('Execution '):
                        secrets.add(value)
    secrets -= {'', 'string', '[AUTH REDACTED]'}
    for item in protocol['memories'].values():
        artifact = read_json(RESULTS / 'memories' / item['source_namespace'] / 'artifact.json')
        if digest(artifact) != item['version']:
            raise Inconclusive('Native source memory changed')
        if any(secret in json.dumps(artifact) for secret in secrets):
            raise Inconclusive('Stored memory contains a recognised authentication value')


def cells(protocol, key):
    out = []
    for rep in range(2):
        for index, task in enumerate(TASKS):
            arms = ARMS if (rep + index) % 2 == 0 else ARMS[::-1]
            for arm in arms:
                modes = ['memory_on', 'memory_off'] if (rep + index) % 2 == 0 else ['memory_off', 'memory_on']
                out.extend(Cell(arm=arm, phase='memory_effect', task_id=task,
                                checkpoint=-4, repetition=rep, mode=mode, candidate=key) for mode in modes)
    return out


def execute(cell, vertex, protocol, key):
    item = protocol['memories'][cell.arm + ':' + cell.task_id]
    source = RESULTS / 'memories' / item['source_namespace']
    namespace = 'effect-' + key[:12] + '-' + item['source_namespace']
    dest = RESULTS / 'memories' / namespace
    if not dest.exists():
        shutil.copytree(source, dest, ignore=shutil.ignore_patterns('.lock', 'optimizer-*'))
    native = Memory(cell.arm, vertex, namespace=namespace)
    native.read_only = True
    try:
        if digest(native.export()) != item['version']:
            raise Inconclusive('Native reopened memory differs from frozen source')
        policy = ExposurePolicy(native, cell.mode, item['target_ids'], key)
        with vertex.scoped(diagnostic_key=key, exposure_mode=cell.mode):
            result = solve(cell, policy, vertex)
        require_conclusive(result)
        return result
    finally:
        native.close()


def report(ledger, protocol, key):
    runs = [dict(r) for r in ledger.db.execute(
        "SELECT * FROM runs WHERE phase='memory_effect' AND cell_key LIKE ? ORDER BY started", ('%' + key,))]
    latest = {r['cell_key']: r for r in runs}
    rows = []
    text = ['# Mem0 and ACE: matched memory exposure diagnostic', '',
            'These are new live attempts on known upstream cases. Memory stays frozen. '
            'Only exposure changes within each paired comparison. Native retrieval still runs in the withheld condition.', '',
            '| Method | Task | Memory on | Memory withheld | Target removed |',
            '| --- | --- | --- | --- | --- |']
    for arm in ARMS:
        for task in TASKS:
            summaries = []
            for mode in ['memory_on', 'memory_off', 'target_removed']:
                group = [r for r in latest.values() if r['arm'] == arm and r['task_id'] == task
                         and json.loads(r['data'])['cell']['mode'] == mode]
                conclusive = [r for r in group if r['status'] == 'conclusive']
                summaries.append(f"{sum(r['success'] for r in conclusive)}/{len(conclusive)}")
                for r in group:
                    data = json.loads(r['data'])
                    calls = list(ledger.db.execute('SELECT * FROM calls WHERE run_id=?', (r['id'],)))
                    rows.append({'arm': arm, 'task': task, 'mode': mode, 'repetition': r['repetition'],
                                 'run_id': r['id'], 'status': r['status'], 'success': r['success'],
                                 'api_calls': data.get('api_calls'), 'seconds': data.get('duration_s'),
                                 'known_estimated_usd': sum(x['estimate'] or 0 for x in calls),
                                 'unknown_requests': sum(x['status'] in {'pending', 'unknown'} for x in calls),
                                 'memory_version': data['memory_version'],
                                 'loaded_reset_identity': data.get('loaded_reset_identity')})
            text.append('| ' + ' | '.join([arm, task, *summaries]) + ' |')
    planned = cells(protocol, key)
    n = sum(r['status'] == 'conclusive' for r in latest.values())
    text += ['', f'Primary cells planned: {len(planned)}. All attempted cells: {len(runs)}. '
             f'Latest conclusive cells including conditional removals: {n}.', '',
             'All conclusive failures remain included. A stored or exposed memory is not evidence of benefit. '
             'A memory-on pass and withheld failure is a paired outcome difference. '
             'Repeated deterioration after removing the predeclared item set supports that set contributing, '
             'without isolating individual sentences or eliminating context-length effects.', '',
             'Task selection used prior outcomes. These are known-case diagnostics, not independent held-out estimates. '
             'Earlier input-normalisation defects remain disclosed; the reused artifacts were checked for recognised '
             'authentication values but that does not certify their factual correctness. Provider and host timing, '
             'execution order, model aliases, instrumentation and two repetitions limit attribution.']
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'REPORT.md').write_text('\n'.join(text) + '\n')
    stream = io.StringIO()
    if rows:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    (OUT / 'comparison.csv').write_text(stream.getvalue())
    write_json(OUT / 'summary.json', {'key': key, 'protocol': protocol, 'runs': rows})
    return rows


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--report', action='store_true'); args = parser.parse_args()
    bind()
    with serial_lock():
        ledger = Ledger()
        try:
            path = OUT / 'protocol.json'
            protocol = read_json(path) if path.exists() else make_protocol(ledger)
            key = digest(protocol)
            if protocol['driver_sha256'] != digest(Path(__file__).read_bytes()):
                raise Inconclusive('Diagnostic driver changed after freeze')
            check_sources(protocol, ledger)
            if not path.exists():
                write_json(path, protocol)
                mark(ledger, 'memory_effect_protocol', {'key': key, 'protocol': protocol,
                     'source': Path(__file__).read_text()}, phase='memory_effect_preparation')
            if args.prepare:
                print(json.dumps({'key': key, 'planned': 32, 'targets': {
                    k: len(v['target_ids']) for k, v in protocol['memories'].items()}})); return
            if args.report:
                print(json.dumps(report(ledger, protocol, key))); return
            reconcile_closed_timeout(ledger)
            vertex = DiagnosticVertex(ledger)
            vertex.expected_resolved_model = protocol['resolved_model']
            try:
                for cell in cells(protocol, key):
                    execute(cell, vertex, protocol, key)
                    report(ledger, protocol, key)
                for arm in ARMS:
                    for task in TASKS:
                        results = {mode: [ledger.latest(Cell(arm=arm, phase='memory_effect', task_id=task,
                                    checkpoint=-4, repetition=rep, mode=mode, candidate=key))
                                    for rep in range(2)] for mode in ['memory_on', 'memory_off']}
                        if (all(r and r['success'] == 1 for r in results['memory_on'])
                                and all(r and r['success'] == 0 for r in results['memory_off'])):
                            for rep in range(2):
                                execute(Cell(arm=arm, phase='memory_effect', task_id=task, checkpoint=-4,
                                             repetition=rep, mode='target_removed', candidate=key), vertex, protocol, key)
                                report(ledger, protocol, key)
                check_sources(protocol, ledger)
                mark(ledger, 'memory_effect_complete', {'key': key, 'primary_cells': 32}, phase='memory_effect_reporting')
            finally:
                report(ledger, protocol, key)
                vertex.sdk.close()
        finally:
            ledger.db.close()


if __name__ == '__main__':
    main()
