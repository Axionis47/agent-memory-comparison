"""Read-only accounting, exposure reconciliation and trace export for 54 checks."""
from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
import tarfile
from pathlib import Path

from mc.core import digest, dumps, read_json, write_json
from growth.runtime import RESULTS, ROOT


OUT = RESULTS / 'three-memory-effect'
PHASE = 'three_memory_effect'


def analyse(final=False):
    from memory_three_effect import project, remove_target, authentication_values
    protocol = read_json(OUT / 'protocol.json'); key = digest(protocol)
    db = sqlite3.connect(f'file:{RESULTS / "ledger.sqlite"}?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    attempts = [dict(x) for x in db.execute(
        'SELECT * FROM runs WHERE phase=? AND cell_key LIKE ? ORDER BY started', (PHASE, '%' + key))]
    runs = list({x['cell_key']: x for x in attempts}.values())
    secrets = authentication_values(None)
    raw_records, raw_calls, checks, rows = [], [], [], []
    resets, prompts, catalogues, contexts = {}, {}, set(), {}
    for run in attempts:
        raw_records += [dict(x) for x in db.execute('SELECT * FROM records WHERE run_id=? ORDER BY created', (run['id'],))]
        raw_calls += [dict(x) for x in db.execute('SELECT * FROM calls WHERE run_id=? ORDER BY started', (run['id'],))]
    for run in runs:
        data = json.loads(run['data']); cell = data['cell']; arm = run['arm']; task = run['task_id']
        events = [x for x in raw_records if x['run_id'] == run['id']]
        def records(kind):
            return [json.loads(x['data']) for x in events if x['kind'] == kind]
        selections = records('three_memory_selection'); exposures = records('exposure')
        packed = records('selection')
        api_events = records('tool_call')
        intents = records('exposure_intent'); discoveries = records('tool_discovery')
        calls = [x for x in raw_calls if x['run_id'] == run['id']]
        target = protocol['memories'][arm]['targets'][task]
        if run['status'] == 'conclusive':
            assert len(selections) == len(exposures) == len(intents) == len(discoveries) == len(data['steps'])
            for selected, exposure, discovery in zip(selections, exposures, discoveries):
                safe = project(selected['native_items'], secrets)
                assert safe == selected['projected_items']
                offered = ([] if cell['mode'] == 'memory_off' else
                           remove_target(arm, safe, target) if cell['mode'] == 'target_removed' else safe)
                assert offered == selected['offered_items']
                assert all(x in offered for x in exposure['items'])
                packet = json.loads(next(c['data'] for c in calls if c['id'] == exposure['call_id']))
                assert packet['classification'] == 'live' and packet['resolved_model'] == protocol['resolved_model']
                assert packet['request_hash'] == exposure['request_hash'] == digest(packet['messages'])
                content = '\n\n'.join(x['content'] for x in exposure['items']) or '(empty)'
                assert packet['messages'][0]['content'] == 'Historical memory, advisory only:\n' + content
                search = json.loads(next(c['data'] for c in calls if c['id'] == discovery['call_id']))
                assert json.loads(search['messages'][1]['content'])['historical_memory'] == discovery['memory_exposed']
                assert discovery['memory_exposed'] == exposure['items']
                assert not any(s in content for s in secrets)
                if cell['mode'] == 'memory_off':
                    assert not exposure['items'] and not discovery['memory_exposed']
                if cell['mode'] == 'target_removed':
                    for item in exposure['items']:
                        assert not (item['id'] == target['id'] and
                                    (item.get('layer') == target['layer'] if arm == 'recmem'
                                     else target['text'] in item['content']))
                catalogues.add(discovery['catalogue_version'])
                for item in exposure['items']:
                    contexts.setdefault(digest(item['content']), {'id': item['id'], 'content': item['content']})
            resets.setdefault(task, set()).add(data['loaded_reset_identity'])
            prompts.setdefault(task, set()).add(intents[0]['native_prompt_hash'])
            checks.append({'run': run['id'], 'verified_decisions': len(exposures),
                           'actual_sdk_exposure_checked': True, 'removal_and_auth_projection_checked': True})
        target_exposures = sum(any(x['id'] == target['id'] and
            (x.get('layer') == target['layer'] if arm == 'recmem' else target['text'] in x['content'])
            for x in event['items']) for event in exposures)
        error_step = next((s['number'] for s in data.get('steps', []) if any(re.search(
            r'(?m)^Execution failed|Traceback \(most recent|(?:TypeError|ValueError|NameError|HTTPException):',
            out) for out in s['outputs'])), None)
        operational_boundaries = [
            {'decision': step['number'], 'boundary': 'AppWorld per-execution request guard',
             'observation': line}
            for step in data.get('steps', []) for output in step['outputs'] for line in output.splitlines()
            if 'Number of requests exceeded the limit of ' in line]
        rows.append({'arm': arm, 'task': task, 'repetition': run['repetition'], 'mode': cell['mode'],
                     'run_id': run['id'], 'status': run['status'], 'success': run['success'],
                     'comparison_eligible': run['status'] == 'conclusive' and not operational_boundaries,
                     'operational_boundaries': json.dumps(operational_boundaries),
                     'api_calls': data.get('api_calls'), 'action_decisions': len(exposures),
                     'generation_requests': sum(c['kind'] == 'generation' for c in calls),
                     'embedding_requests': sum(c['kind'] == 'embedding' for c in calls),
                     'known_estimated_usd': sum(c['estimate'] or 0 for c in calls),
                     'unknown_requests': sum(c['status'] in {'pending', 'unknown'} for c in calls),
                     'seconds': data.get('duration_s'), 'first_observed_execution_error_step': error_step,
                     'native_target_selected_decisions': sum(s['target_present_before_removal'] for s in selections),
                     'target_actually_exposed_decisions': target_exposures,
                     'memory_omitted_items': sum(len(x['omitted']) for x in packed),
                     'memory_selected_tokens_total': sum(x['tokens'] for x in packed),
                     'payment_amounts': json.dumps([x['call']['data'].get('amount') for x in api_events
                         if x['identity'] == 'venmo.create_transaction']),
                     'text_message_queries': json.dumps([x['call']['data'].get('query') for x in api_events
                         if x['identity'] == 'phone.search_text_messages']),
                     'contact_relationships': json.dumps(sorted({str(x['call']['data'].get('relationship')) for x in api_events
                         if x['identity'] == 'phone.search_contacts'})),
                     'deny_request_api_calls': sum(x['identity'] == 'venmo.deny_payment_request' for x in api_events),
                     'memory_version': data['memory_version'], 'reset': data.get('loaded_reset_identity')})
    assert all(len(x) == 1 for x in resets.values())
    assert all(len(x) == 1 for x in prompts.values())
    assert len(catalogues) <= 1
    for arm, memory in protocol['memories'].items():
        assert digest(read_json(ROOT / memory['source'] / 'artifact.json')) == memory['version']
    counts = {'planned': 54, 'attempted': len(runs), 'conclusive': sum(r['status'] == 'conclusive' for r in runs),
              'missing': 54 - len(runs), 'inconclusive': sum(r['status'] == 'inconclusive' for r in runs),
              'running': sum(r['status'] == 'running' for r in runs), 'all_attempts': len(attempts)}
    counts['completion_comparison_eligible'] = sum(r['comparison_eligible'] for r in rows)
    counts['operationally_inconclusive'] = sum(bool(json.loads(r['operational_boundaries'])) for r in rows)
    if final:
        assert counts['conclusive'] == 54 and counts['missing'] == counts['inconclusive'] == counts['running'] == 0
        assert db.execute("SELECT count(*) FROM records WHERE kind='three_memory_complete' "
                          "AND json_extract(data,'$.key')=?", (key,)).fetchone()[0]
    report = ['# Trace2Skill, GEPA and RecMem: repeated exposure and removal checks', '',
              'One current AppWorld acting integration, three common upstream tasks, two fresh-world repetitions per '
              'condition. Full, withheld and specific-item removal conditions were all registered before new outcomes. '
              'Learning histories differ; this is a within-policy diagnostic, not an architecture ranking.', '',
              f'Coverage: {counts}. Raw official grades remain unchanged. Operationally affected attempts '
              'remain in traces and expense totals but are excluded from completion comparisons. '
              'The request-guard check is applied to every attempt regardless of grade.', '',
              '| Method | Task | Full memory | Withheld | Target removed | Excluded full/off/removed | Removal opportunities |',
              '| --- | --- | --- | --- | --- | --- | --- |']
    for arm in protocol['arms']:
        for task in protocol['tasks']:
            group = [r for r in rows if r['arm'] == arm and r['task'] == task]
            values = []
            for mode in protocol['modes']:
                done = [r for r in group if r['mode'] == mode and r['comparison_eligible']]
                values.append(f"{sum(r['success'] for r in done)}/{len(done)}")
            excluded = '/'.join(str(sum(not r['comparison_eligible'] for r in group if r['mode'] == mode))
                                for mode in protocol['modes'])
            opportunities = sum(r['native_target_selected_decisions'] for r in group if r['mode'] == 'target_removed')
            report.append('| ' + ' | '.join([arm, task, *values, excluded, str(opportunities)]) + ' |')
    report += ['', 'Each task/condition has two planned attempts. Fractions use eligible completion '
               'comparisons. Excluded attempts are operationally inconclusive, not invented task failures.', '']
    report += ['', '## Paired outcomes', '',
               'Wins/losses/ties below compare full memory with the named condition on the same task and repetition.', '',
               '| Method | Task | Full vs withheld W/L/T | Full vs removal W/L/T | Unmatched off/removal | Full target exposure decisions |',
               '| --- | --- | --- | --- | --- | --- |']
    for arm in protocol['arms']:
        for task in protocol['tasks']:
            group = [r for r in rows if r['arm'] == arm and r['task'] == task]
            values, unmatched = [], []
            for other in ['memory_off', 'target_removed']:
                differences = []
                for repetition in range(2):
                    pair = {r['mode']: r for r in group if r['repetition'] == repetition and r['comparison_eligible']}
                    if 'memory_on' in pair and other in pair:
                        differences.append(pair['memory_on']['success'] - pair[other]['success'])
                values.append('/'.join(str(differences.count(x)) for x in [1, -1, 0]))
                unmatched.append(str(2 - len(differences)))
            exposed = sum(r['target_actually_exposed_decisions'] for r in group if r['mode'] == 'memory_on')
            report.append('| ' + ' | '.join([arm, task, *values, '/'.join(unmatched), str(exposed)]) + ' |')
    affected = [r for r in rows if json.loads(r['operational_boundaries'])]
    if affected:
        report += ['', '## Operational exclusions', '',
                   'An official grade after a recovered request-limit error is preserved as an official '
                   'observation. It cannot establish completion quality without that operational bound. '
                   'No limit was increased, no failure erased and no conclusive attempt selectively rerun.', '']
        for row in affected:
            report.append(f"- `{row['run_id']}` ({row['arm']}, {row['task']}, {row['mode']}, repetition "
                          f"{row['repetition']}): official success `{row['success']}`; "
                          f"{row['operational_boundaries']}. Excluded from paired completion estimates.")
    if final:
        report += ['', '## What changed in concrete attempts', '',
                   'These examples describe recorded actions and outcomes. They do not infer hidden reasoning. '
                   'The tables above include both repetitions, including contrary outcomes.', '']
        examples = [
            ('trace2skill', '530b157_1',
             'Across both grocery repetitions, full memory failed twice and withheld memory failed '
             'twice, while removing Best Practices passed twice. Both passing attempts searched '
             'messages for "how much was yesterday\'s grocery?" and paid 54. The four failing '
             'attempts paid 25. The removed section gives generic advice about variables, API '
             'parameters and response inspection; it does not contain a grocery procedure. This '
             'is a repeated response to a content-group intervention, not evidence that generic '
             'best practices are always harmful or that the remaining skill taught the exact query.'),
            ('trace2skill', '68ee2c9_2',
             'In the first file-task repetition, full and section-removed memory passed. The withheld '
             'attempt failed the official file-renaming requirement, but also hit AppWorld\'s 1,000-request '
             'guard during a loop that kept renaming the first remaining file. It is operationally '
             'inconclusive for completion comparison, despite the later official grade. Its 1,157 '
             'recorded API calls remain charged. The second withheld attempt passed. There is no '
             'clean paired completion win here. The passing full-memory attempts used separate rename '
             'and move phases, but the remaining skill does not explicitly teach this file workflow.'),
            ('gepa', '6ea6792_2',
             'In the first payment-request repetition, full memory failed after issuing denials for '
             'every pending request without a phone-contact lookup. Both withheld and target-removed '
             'attempts looked up friend and roommate relationships and passed. The removed group '
             'contains tracking instructions and a prohibition on re-querying. This is a plausible '
             'scope mismatch for a strategy learned on file operations, not proof that one sentence '
             'caused the error or that GEPA generally harms payment tasks.'),
            ('recmem', '530b157_1',
             'In the first grocery repetition, full and target-removed memory both paid 25 and failed '
             'the amount requirement. Withheld memory paid 54 and passed. The removed point concerns '
             'an earlier coworker payment-request task, not this grocery debt. Its removal did not '
             'repair that first failure. The wrong 25 also appears in the current conversation, so '
             'the trace does not establish copying an amount from memory.'),
        ]
        for arm, task, explanation in examples:
            report += [f'### {arm}: {task}', '', explanation, '',
                       'First-repetition trace identities:', '']
            for row in rows:
                if row['arm'] == arm and row['task'] == task and row['repetition'] == 0:
                    report.append(f"- {row['mode']}: `{row['run_id']}`, official success `{row['success']}`.")
            report.append('')
        report += ['## Why more elapsed time is not the diagnosis', '',
                   'Earlier construction and practice produced persistent changed memories. In this '
                   'diagnostic those stores are frozen: repeating a task does not trigger further '
                   'consolidation. The unfinished growth study has not established whether a larger '
                   'and more varied practice history improves these policies.', '',
                   'Native consolidation reorganises or summarises experience; it does not certify '
                   'that a lesson is correct, applies to this task, or remains current. Retrieval '
                   'similarity is not a task-applicability check. Whole-skill or whole-strategy '
                   'exposure can also introduce irrelevant guidance. An action model still has to '
                   'select the right live evidence and execute valid actions.', '',
                   'Our integration owns experience formatting, credential projection, retrieval '
                   'queries, exposure scheduling and the shared discovery boundary. Historical input '
                   'defects and the current actor adaptation are disclosed below. The released '
                   'learning mechanisms own their native mutations. These data do not isolate '
                   'architecture-wide weaknesses from every integration choice. No dependable '
                   'general freshness or failed-guidance retirement controller was implemented. '
                   'Diagnostic item withholding is not autonomous retirement.', '']
        rec_layers = read_json(ROOT / protocol['memories']['recmem']['source'] / 'artifact.json')['layers']
        report += ['The frozen pilot RecMem store used here contains ' + ', '.join(
            f'{len(values)} {layer} items' for layer, values in rec_layers.items()) +
            '. This shows retained episodic and semantic content already exists; it does not '
            'certify the correctness or usefulness of those items. Recurrence counts incoming '
            'pieces of experience, not necessarily independent successful tasks.', '']
        from collections import Counter
        native_patterns = Counter()
        for event in raw_records:
            if event['arm'] == 'recmem' and event['kind'] == 'three_memory_selection':
                selected = json.loads(event['data'])['native_items']
                native_patterns[tuple(sorted(Counter(x.get('layer', 'unspecified') for x in selected).items()))] += 1
        report += ['Actual RecMem native lookup result sizes before removal and packing: ' + '; '.join(
            ', '.join(f'{count} {layer}' for layer, count in pattern) + f' on {number} lookups'
            for pattern, number in native_patterns.items()) +
            '. Similarity-ranked results are not guaranteed to concern the current application or goal.', '']
    report += ['', '## Frozen tasks', '']
    for task in protocol['tasks']:
        candidates = [json.loads(r['data']).get('instruction') for r in runs if r['task_id'] == task]
        instruction = next((s for s in candidates if s), '(not yet attempted)')
        report.append(f'- `{task}`: {instruction}')
    report += ['', '## Executed money-task actions', '',
               'Values come from actual API-call arguments, not inferred model intent. Each entry is a separate '
               'fresh-world attempt. Missing contact lookup does not by itself prove the first broken contract.', '',
               '| Method | Task | Repetition | Condition | Payment amount arguments | Contact relationships queried | Denial API calls | Pass |',
               '| --- | --- | --- | --- | --- | --- | --- | --- |']
    for row in rows:
        if row['task'] in {'530b157_1', '6ea6792_2'} and row['status'] == 'conclusive':
            report.append('| ' + ' | '.join(map(str, [row['arm'], row['task'], row['repetition'], row['mode'],
                          row['payment_amounts'], row['contact_relationships'], row['deny_request_api_calls'],
                          bool(row['success'])])) + ' |')
    report += ['', '## Exact removal targets', '',
               'Trace2Skill removal withholds the learned Best Practices section, retaining the remaining skill. '
               'GEPA removal withholds strategy steps 2 and 3 about updated identifiers/paths, retaining initial '
               'listing and applicability conditions. RecMem removal withholds the single episodic point ranked '
               'first by native retrieval for the initial task query. Native retrieval continues, and no replacement '
               'item is backfilled. A selected target is not assumed relevant or useful.', '']
    for arm, memory in protocol['memories'].items():
        seen = set()
        for task, target in memory['targets'].items():
            identity = digest(target)
            if identity in seen:
                continue
            seen.add(identity)
            report += [f"### {arm}: {target['label']}", '',
                       f"Source version: `{memory['version']}`. Item: `{target['id']}`. Task: `{task}`.", '',
                       '````text', target['text'], '````', '']
    report += ['## Expense and interpretation', '',
               '| Method | Condition | Eligible successes/conclusive | Excluded | API calls (all attempts) | Generation | Embedding | Known estimated USD |',
               '| --- | --- | --- | --- | --- | --- | --- | --- |']
    for arm in protocol['arms']:
        for mode in protocol['modes']:
            group = [r for r in rows if r['arm'] == arm and r['mode'] == mode and r['status'] == 'conclusive']
            eligible = [r for r in group if r['comparison_eligible']]
            report.append('| ' + ' | '.join(map(str, [arm, mode,
                f"{sum(r['success'] for r in eligible)}/{len(eligible)}", len(group) - len(eligible),
                sum(r['api_calls'] or 0 for r in group),
                sum(r['generation_requests'] for r in group), sum(r['embedding_requests'] for r in group),
                f"{sum(r['known_estimated_usd'] for r in group):.6f}"])) + ' |')
    probe_calls = [dict(x) for x in db.execute("SELECT * FROM calls WHERE phase='three_memory_probe'")]
    if final:
        assert all(c['status'] == 'live' for c in raw_calls + probe_calls)
        assert all(json.loads(c['data'])['classification'] == 'live'
                   for c in raw_calls + probe_calls if c['kind'] in {'generation', 'embedding'})
    report += ['', f'Pre-outcome target selection: {len(probe_calls)} provider requests; known estimated USD '
               f"{sum(c['estimate'] or 0 for c in probe_calls):.6f}. No additional learning. "
               'Native retrieval also runs in the withheld condition, so costs measure this exposure intervention, '
               'not an optimised memory-free implementation. Provider estimates are not invoices.', '',
               'Full-memory pass plus withheld failure is an observed paired difference. A repeated loss after '
               'target removal supports a contribution by the removed content group only if that content was '
               'actually exposed in the full condition and the removal intervention activated. Two repetitions '
               'do not establish statistical superiority. If both full and withheld pass, removal failure alone '
               'does not establish that memory was necessary.', '',
               'Each exposure intervention changes memory supplied to both tool-search generation and action '
               'generation. It does not identify which of those two channels caused a downstream difference.', '',
               'Withheld conditions use the same empty-memory acting and discovery interface across policy '
               'labels. Differences among their outcomes are repeated-control variation, not evidence of '
               'different architecture quality. Two repetitions per task and condition are insufficient '
               'to distinguish small effects from that variation reliably.', '',
               'The Trace2Skill/RecMem sources are original pilot memories, while the common actor now retrieves '
               'at each step and adds tool search. These outcomes are not exact reproductions of pilot scores. '
               'Original memory input defects remain disclosed. Recognised credential text in RecMem is redacted '
               'only at delivery; original frozen vectors and stores remain unchanged. No lessons are corrected '
               'or authored. Native retrieval still indexes the original text.', '',
               'Known-case selection, different learning histories, context-length changes, redundant guidance, '
               'inactive removals, model variation, provider aliases, execution order, host load, cold starts, '
               'missingness, grading defects and instrumentation overhead limit inference. Supporting failures '
               'are inconclusive. No repeat-until-pass or evaluation learning is allowed.', '',
               'One owned integration limitation is concrete: the shared actor serialises the previous '
               'step including its measured duration_s into retrieval and tool-search context. Therefore '
               'request strings can differ between repetitions even when the preceding action and result '
               'match. This is unnecessary timing noise and another reason not to attribute every '
               'changed action solely to memory content. The frozen actor was not edited mid-comparison.', '',
               'Consolidation happened during earlier practice/construction. These repeated attempts freeze memory '
               'and deliberately exclude their feedback from learning. They test existing retained knowledge, '
               'not improvement from additional practice or long-term growth. Native consolidation does not '
               'guarantee correctness, applicability or retirement of failed guidance.', '',
               '## Implementation trade-offs', '',
               '| Policy | Useful property observed | Limitation exposed |',
               '| --- | --- | --- |',
               '| Trace2Skill | One inspectable skill allows an exact section-removal intervention. '
               '| Whole-skill exposure mixes generic and domain-specific guidance. Removing the generic '
               'section changed grocery outcomes, but does not explain why the remaining context worked. |',
               '| GEPA | A native-selected, persisted strategy can be exposed and partially withheld exactly. '
               '| Candidate testing adds learning expense. A strategy selected on known cases can be '
               'inapplicable elsewhere; retained instructions are not a guarantee of better task completion. |',
               '| RecMem | Layered native retrieval provides identifiable episodes and semantic items. '
               '| The highest-ranked episode can concern a different task or application. Repeated '
               'retrieval adds embedding expense; recurrence and consolidation do not certify relevance. |', '',
               'These are properties of the tested integrations and frozen artifacts. They are not rankings '
               'of published architectures. The earlier [Mem0 and ACE repeated checks](../memory-effect/REPORT.md) '
               'use different tasks and a separate protocol; their outcomes must not be pooled into this table.', '',
               '## Traces and failures', '',
               '[TRACES.md](TRACES.md) contains every attempted action, actual delivered-memory references, '
               'observed execution errors and official failed requirement descriptions. Exact delivered content '
               'and authentication-redacted observations are deduplicated in its appendices. Raw observations, model requests and source artifacts are '
               'preserved in the local private evidence bundle. No hidden model reasoning is included.']
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'REPORT.md').write_text('\n'.join(report) + '\n')
    stream = io.StringIO()
    if rows:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    (OUT / 'comparison.csv').write_text(stream.getvalue())
    write_json(OUT / 'summary.json', {'protocol_key': key, 'counts': counts, 'runs': rows})
    write_json(OUT / 'integrity.json', {'counts': counts, 'checks': checks, 'verified_decisions': sum(x['verified_decisions'] for x in checks),
        'equal_resets': True, 'equal_initial_native_prompts': True, 'equal_catalogue': True,
        'source_artifacts_unchanged': True, 'analysis_source_sha256': digest(Path(__file__).read_bytes())})
    if final:
        observations = {}
        traces = ['# Actual actions, memory exposures and failures', '',
                  'Authentication values are redacted. Code and observations come from recorded live attempts. '
                  'Memory content and complete observations are deduplicated in the appendices. '
                  'These references do not truncate what the acting model received.', '']
        for run in attempts:
            data = json.loads(run['data']); cell = data['cell']
            comparison = next((r for r in rows if r['run_id'] == run['id']), None)
            events = [json.loads(x['data']) for x in raw_records if x['run_id'] == run['id'] and x['kind'] == 'exposure']
            discoveries = [json.loads(x['data']) for x in raw_records if x['run_id'] == run['id'] and x['kind'] == 'tool_discovery']
            traces += [f"## {run['arm']} / {run['task_id']} / {cell['mode']} / repetition {run['repetition']}", '',
                       f"Run `{run['id']}`. Status `{run['status']}`. Official success `{run['success']}`. "
                       f"Frozen memory `{data['memory_version']}`.", '']
            if comparison:
                traces += [f"Completion-comparison eligible: `{comparison['comparison_eligible']}`. "
                           f"Operational boundary observations: `{comparison['operational_boundaries']}`.", '']
            for step in data.get('steps', []):
                n = step['number']; exp = next((x for x in events if x['decision'] == n), None)
                discovery = next((x for x in discoveries if x['decision'] == n), None)
                traces += [f'### Decision {n}', '']
                if exp:
                    refs = [f"`{x['id']}` (content `{digest(x['content'])}`)" for x in exp['items']]
                    traces += ['Memory delivered: ' + (', '.join(refs) or '(empty)') + '.',
                               f"Actual SDK request: `{exp['call_id']}`."]
                if discovery:
                    traces += ['Tool query: `' + str(discovery['query']) + '`. Definitions: ' +
                               ', '.join('`' + x['id'] + '`' for x in discovery['items']) + '.']
                safe = runtime_redact(step, secrets)
                traces += ['', '````python', '\n\n'.join(safe['inputs']), '````', '']
                refs = []
                for output in safe['outputs']:
                    output_hash = digest(output)
                    observations.setdefault(output_hash, output)
                    refs.append('`' + output_hash + '`')
                traces += ['Observed outputs: ' + ', '.join(refs) + '.', '']
                for output in safe['outputs']:
                    if re.search(r'(?m)^Execution failed|Traceback \(most recent|(?:TypeError|ValueError|NameError|HTTPException):', output):
                        traces += ['Observed error:', '', '````text', output, '````', '']
            failures = data.get('grade', {}).get('failures', [])
            traces += ['Official failed requirements:', ''] + (['- ' + x['requirement'] for x in failures] or ['- None.']) + ['']
        traces += ['# Exact delivered-memory appendix', '']
        for content_hash, item in contexts.items():
            traces += [f"## {item['id']} / {content_hash}", '', '````text', item['content'], '````', '']
        traces += ['# Complete observations (authentication redacted)', '']
        for output_hash, output in observations.items():
            traces += [f'## {output_hash}', '', '````text', output, '````', '']
        (OUT / 'TRACES.md').write_text('\n'.join(traces) + '\n')
        raw = dumps({'protocol': protocol, 'runs': attempts, 'records': raw_records, 'calls': raw_calls,
                     'preparation_calls': probe_calls,
                     'sources': {a: read_json(ROOT / m['source'] / 'artifact.json') for a, m in protocol['memories'].items()}}).encode()
        names = ['protocol.json', 'REPORT.md', 'TRACES.md', 'comparison.csv', 'integrity.json', 'summary.json']
        manifest = {'raw_sha256': digest(raw), 'files': {n: digest((OUT / n).read_bytes()) for n in names},
                    'privacy': 'Local raw evidence includes authentication material; not a public export',
                    'attempts': len(attempts), 'calls': len(raw_calls)}
        write_json(OUT / 'evidence-manifest.json', manifest)
        with tarfile.open(OUT / 'evidence.tar.gz', 'w:gz') as tar:
            info = tarfile.TarInfo('evidence.json'); info.size = len(raw); info.mode = 0o600
            tar.addfile(info, io.BytesIO(raw))
            for name in names + ['evidence-manifest.json']:
                tar.add(OUT / name, arcname=name)
            for name in ['memory_three_effect.py', 'memory_three_analysis.py']:
                tar.add(ROOT / name, arcname=name)
        (OUT / 'evidence.tar.gz').chmod(0o600)
        with tarfile.open(OUT / 'evidence.tar.gz') as tar:
            assert digest(tar.extractfile('evidence.json').read()) == manifest['raw_sha256']
            for name, checksum in manifest['files'].items():
                assert digest(tar.extractfile(name).read()) == checksum
    db.close()
    return counts


def runtime_redact(value, secrets):
    from growth.runtime import redact
    return redact(value, secrets)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(); parser.add_argument('--final', action='store_true')
    args = parser.parse_args(); print(json.dumps(analyse(final=args.final)))
