"""Reconcile the memory-effect diagnostic without making model requests."""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sqlite3
import tarfile
from pathlib import Path

from mc.core import digest, dumps, read_json, write_json
from growth.runtime import RESULTS


OUT = RESULTS / 'memory-effect'


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--final', action='store_true')
    args = parser.parse_args()
    protocol = read_json(OUT / 'protocol.json'); key = digest(protocol)
    db = sqlite3.connect(f'file:{RESULTS / "ledger.sqlite"}?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    all_runs = [dict(x) for x in db.execute(
        "SELECT * FROM runs WHERE phase='memory_effect' AND cell_key LIKE ? ORDER BY started", ('%' + key,))]
    runs = list({r['cell_key']: r for r in all_runs}.values())
    records = []
    for run in all_runs:
        records.extend(dict(x) for x in db.execute('SELECT * FROM records WHERE run_id=?', (run['id'],)))
    checks = []; first_prompts = {}; resets = {}; exports = []
    for run in runs:
        data = json.loads(run['data']); cell = data['cell']
        if run['status'] != 'conclusive':
            continue
        local = [x for x in records if x['run_id'] == run['id']]
        exposed = [json.loads(x['data']) for x in local if x['kind'] == 'exposure']
        intents = [json.loads(x['data']) for x in local if x['kind'] == 'exposure_intent']
        discoveries = [json.loads(x['data']) for x in local if x['kind'] == 'tool_discovery']
        assert len(exposed) == len(intents) == len(discoveries) == len(data['steps'])
        for exp in exposed:
            call = db.execute('SELECT * FROM calls WHERE id=?', (exp['call_id'],)).fetchone()
            packet = json.loads(call['data'])
            assert call['status'] == 'live'
            assert packet['resolved_model'] == protocol['resolved_model']
            assert packet['request_hash'] == exp['request_hash'] == digest(packet['messages'])
            supplied = '\n\n'.join(x['content'] for x in exp['items']) or '(empty)'
            assert packet['messages'][0]['content'] == 'Historical memory, advisory only:\n' + supplied
            if cell['mode'] == 'memory_off':
                assert not exp['items']
        if cell['mode'] == 'memory_off':
            assert all(not x['memory_exposed'] for x in discoveries)
        for discovery in discoveries:
            packet = json.loads(db.execute('SELECT data FROM calls WHERE id=?',
                                           (discovery['call_id'],)).fetchone()[0])
            actual = json.loads(packet['messages'][1]['content'])
            assert actual['historical_memory'] == discovery['memory_exposed']
        first_prompts.setdefault(run['task_id'], set()).add(intents[0]['native_prompt_hash'])
        resets.setdefault(run['task_id'], set()).add(data['loaded_reset_identity'])
        checks.append({'run_id': run['id'], 'verified_decisions': len(exposed),
                       'exposure_and_search_match_actual_sdk': True})
    assert all(len(x) == 1 for x in first_prompts.values()), 'Initial native prompts differ'
    assert all(len(x) == 1 for x in resets.values()), 'Initial loaded states differ'
    expected = protocol['memories']
    for ident, item in expected.items():
        state = read_json(RESULTS / 'memories' / item['source_namespace'] / 'artifact.json')
        assert digest(state) == item['version']
        changed = [dict(x) for x in db.execute(
            "SELECT * FROM records WHERE kind='consolidation' AND json_extract(data,'$.after_version')=?",
            (item['version'],))]
        exports.append({'identity': ident, 'artifact': state, 'source_consolidation_records': changed})
    primary = [r for r in runs if json.loads(r['data'])['cell']['mode'] != 'target_removed']
    counts = {'primary_planned': 32, 'primary_attempted': len(primary),
              'primary_conclusive': sum(r['status'] == 'conclusive' for r in primary),
              'primary_inconclusive': sum(r['status'] == 'inconclusive' for r in primary),
              'primary_running': sum(r['status'] == 'running' for r in primary),
              'primary_missing': 32 - len(primary), 'all_attempts': len(all_runs),
              'conditional_attempts': len(runs) - len(primary)}
    if args.final:
        assert counts['primary_conclusive'] == 32, counts
        assert db.execute("SELECT count(*) FROM records WHERE kind='memory_effect_complete' "
                          "AND json_extract(data,'$.key')=?", (key,)).fetchone()[0]
        lines = ['', '## Tasks', '']
        for task in protocol['tasks']:
            observed = next(json.loads(r['data'])['instruction'] for r in primary if r['task_id'] == task)
            lines.append(f'- `{task}`: {observed}')
        lines += ['', '## Completion and expense', '',
                 '| Method | On successes | Withheld successes | Paired wins/losses/ties | On estimated USD | Withheld estimated USD |',
                 '| --- | --- | --- | --- | --- | --- |']
        for arm in protocol['arms']:
            pairs = []; costs = {}; scores = {}
            for mode in ['memory_on', 'memory_off']:
                group = [r for r in primary if r['arm'] == arm
                         and json.loads(r['data'])['cell']['mode'] == mode]
                scores[mode] = sum(r['success'] for r in group)
                costs[mode] = sum(db.execute('SELECT coalesce(sum(estimate),0) FROM calls WHERE run_id=?',
                                            (r['id'],)).fetchone()[0] for r in group)
            for task in protocol['tasks']:
                for rep in range(2):
                    pair = {json.loads(r['data'])['cell']['mode']: r['success'] for r in primary
                            if r['arm'] == arm and r['task_id'] == task and r['repetition'] == rep}
                    pairs.append(pair['memory_on'] - pair['memory_off'])
            lines.append(f"| {arm} | {scores['memory_on']}/8 | {scores['memory_off']}/8 | "
                         f"{pairs.count(1)}/{pairs.count(-1)}/{pairs.count(0)} | "
                         f"{costs['memory_on']:.6f} | {costs['memory_off']:.6f} |")
        lines += ['', 'Estimates include actual generation, embedding and token-count requests. '
                  'Native lookup remains active even when exposure is withheld, so these are exposure-intervention costs, '
                  'not the expense of a separately optimised no-memory implementation. No additional learning occurred.', '',
                  '## Repeated tool-work difference with ACE', '',
                  'Both ACE roommate-spending attempts passed in both conditions. With memory, the agent used '
                  '20 and 19 API calls (12 and 13 action decisions). With memory withheld it used '
                  '23 and 25 API calls (16 and 17 action decisions). This is a repeated observed reduction '
                  'in tool work on a task the agent already completed without memory. It does not demonstrate '
                  'a completion gain, a cost saving, or the causal contribution of an individual bullet.', '',
                  '## Concrete memory-quality finding', '',
                  'Mem0 item `990603d1-baff-4ebf-a04d-f79899c0d4e2` retained this completion template:', '',
                  '```python',
                  'apis.supervisor.complete_task(answer=f"Followed {followed_artists_count} new artists. Some artists were already followed.")',
                  '```', '',
                  'Native ADD record `72cf11e3276d41ba98e94c6d9496b29b` and consolidation '
                  '`eb05652d8fe94db7a834a61817a62150` link it to failed practice run '
                  '`b7d13352022d491ba2a9712ad95adc46`. It survived into the frozen checkpoint. '
                  'In new memory-on run `915a16fedcd84739a84c62fbde5012db`, this exact item was exposed '
                  'at decisions 1, 4 and 6. The agent later emitted the same completion wording. '
                  'Its application changes passed, but the official answer requirement failed. '
                  'This is source-linked evidence of problematic retained guidance and compatible subsequent behaviour, '
                  'not an isolated causal estimate for that single item.', '',
                  'There is no general freshness or retirement controller in this integration. Native mutation mechanisms '
                  'ran, but did not ensure that failed task behaviour was corrected or retired. The diagnostic froze memory '
                  'throughout, so its new feedback was deliberately not used for further learning.', '',
                  'In normal practice, learning occurs after completed attempts. Mem0 can update/delete facts; ACE can '
                  'merge bullets; Trace2Skill can patch procedure files; GEPA replaces the selected active strategy; '
                  'RecMem removes consolidated raw records and replaces merged episodes. These native operations '
                  'do not supply a shared expiry, tool-version invalidation, or dependable retirement rule. '
                  'Historical evidence remains stored even when an item leaves active memory.', '',
                  'No predeclared item-removal checks were triggered: no method/task pair had two memory-on '
                  'passes and two withheld failures. The isolated-item benefit claim therefore remains unestablished.', '',
                  '## Correct sorting knowledge, incorrect entity scope', '',
                  'In repeated song task `e85d92a_3`, Mem0-on run `7369a4af8b57434da7b7dbc8a0a204e2` '
                  'called `search_songs(query="Jasper Skye", sort_by="-play_count", page_limit=1)` and failed. '
                  'The paired withheld run `395d8cb1f0b34161945204533c6e2805` first resolved the artist, '
                  'then called `search_songs(artist_id=3, sort_by="-play_count", page_limit=1)` and passed. '
                  'A correct sorting fact did not ensure correct entity selection. The observable error was global '
                  'text search instead of filtering by the resolved artist. This does not isolate a particular fact '
                  'as the cause of that decision.', '',
                  '## Run identities', '',
                  '| Method | Task | Repetition | Exposure | Official pass | Run |',
                  '| --- | --- | --- | --- | --- | --- |']
        for r in runs:
            cell = json.loads(r['data'])['cell']
            lines.append('| ' + ' | '.join(map(str, [r['arm'], r['task_id'], r['repetition'],
                          cell['mode'], bool(r['success']), r['id']])) + ' |')
        # The acting driver has finished before this derived report amendment.
        path = OUT / 'REPORT.md'
        original = path.read_text().split('\n## Tasks')[0].split('\n## Completion and expense')[0]
        path.write_text(original + '\n'.join(lines) + '\n')
    write_json(OUT / 'integrity.json', {'protocol_key': key, 'counts': counts,
               'run_checks': checks, 'equal_initial_native_prompts': True, 'equal_loaded_resets': True,
               'unchanged_source_artifacts': True, 'classification': 'not-a-model',
               'analysis_source_sha256': digest(Path(__file__).read_bytes())})
    print(json.dumps(counts))
    if args.final:
        calls = []
        for run in all_runs:
            calls.extend(dict(x) for x in db.execute('SELECT * FROM calls WHERE run_id=?', (run['id'],)))
        # One private raw-evidence member, no per-call files or copied dependency trees.
        payload = {'protocol': protocol, 'runs': all_runs, 'records': records,
                   'calls': calls, 'native_sources': exports}
        lineage_ids = ['72cf11e3276d41ba98e94c6d9496b29b', 'eb05652d8fe94db7a834a61817a62150']
        payload['completion_template_lineage'] = [dict(db.execute('SELECT * FROM records WHERE id=?',
                                                                 (ident,)).fetchone()) for ident in lineage_ids]
        raw = dumps(payload).encode()
        manifest = {'raw_evidence_sha256': digest(raw), 'runs': len(all_runs), 'calls': len(calls),
                    'classification': 'Recorded live evidence plus not-a-model measurements',
                    'privacy': 'Local secure evidence contains raw observations and authentication material; not a public export',
                    'files': {name: digest((OUT / name).read_bytes())
                              for name in ['protocol.json', 'REPORT.md', 'comparison.csv', 'integrity.json']}}
        write_json(OUT / 'evidence-manifest.json', manifest)
        with tarfile.open(OUT / 'evidence.tar.gz', 'w:gz') as tar:
            info = tarfile.TarInfo('evidence.json'); info.size = len(raw); info.mode = 0o600
            tar.addfile(info, io.BytesIO(raw))
            for name in ['protocol.json', 'REPORT.md', 'comparison.csv', 'integrity.json', 'evidence-manifest.json']:
                tar.add(OUT / name, arcname=name)
            for name in ['memory_effect.py', 'memory_effect_analysis.py']:
                tar.add(Path(__file__).parent / name, arcname=name)
        (OUT / 'evidence.tar.gz').chmod(0o600)
        with tarfile.open(OUT / 'evidence.tar.gz', 'r:gz') as tar:
            assert digest(tar.extractfile('evidence.json').read()) == manifest['raw_evidence_sha256']
            for name, checksum in manifest['files'].items():
                assert digest(tar.extractfile(name).read()) == checksum
    db.close()


if __name__ == '__main__':
    main()
