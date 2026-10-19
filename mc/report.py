from __future__ import annotations

import csv
import json
import re
import sqlite3
import tarfile
from pathlib import Path

from .core import CACHE, WORLD, RESULTS, ROOT, digest, dumps, protocol, read_json, write_json


def observable_break(data):
    """Locate an observed boundary, without inferring a hidden failure cause."""
    for i,step in enumerate(data['steps']):
        inputs=step['inputs']
        if inputs and not any(str(x).strip() for x in inputs):
            return {'boundary':'empty_executable_action','step':step['number'],
                    'later_actions':len(data['steps'])-i-1}
        if any(re.search(r'Execution failed|Traceback|Response status code is [45]\d\d',str(x))
               for x in step['outputs']):
            return {'boundary':'tool_execution_error','step':step['number'],
                    'later_actions':len(data['steps'])-i-1}
    return {'boundary':'official_grade_failure' if data.get('grade',{}).get('success') is False
            else 'no_break_observed','step':None,'later_actions':0}


def format_diagnostic(call):
    data=call['data']
    if call['kind']!='generation' or call['status']!='live' or not data.get('json_mode'):
        return None
    try:
        parsed=json.loads(data['output'])
    except (ValueError,KeyError):
        return 'invalid JSON output'
    if data.get('purpose')=='mem0-learning':
        extraction=any('Extract reusable factual observations' in m.get('content','')
                       for m in data['messages'])
        key='facts' if extraction else 'memory'
        if not isinstance(parsed,dict) or not isinstance(parsed.get(key),list):
            return f'Mem0 native {key} array missing'
        if extraction and any(not isinstance(x,str) for x in parsed[key]):
            return 'Mem0 fact is not a string'
    return None


def scorecard(rows,arms,planned=12):
    latest={}
    for r in sorted(rows,key=lambda x:x['started']):
        latest[(r['arm'],r['task_id'],r['repetition'])]=r
    out=[]
    for arm in arms:
        r=[v for k,v in latest.items() if k[0]==arm]
        conclusive=[x for x in r if x['status']=='conclusive']
        wins=losses=ties=matched=0
        for x in conclusive:
            base=latest.get(('baseline',x['task_id'],x['repetition']))
            if base and base['status']=='conclusive':
                matched+=1
                wins+=x['success']>base['success']
                losses+=x['success']<base['success']
                ties+=x['success']==base['success']
        tasks={}
        for x in conclusive: tasks.setdefault(x['task_id'],[]).append(x['success'])
        repeated=[v for v in tasks.values() if len(v)==2]
        out.append({'arm':arm,'planned':planned,'attempted':len(r),'conclusive':len(conclusive),
            'total_attempts':sum(x['arm']==arm for x in rows),
            'prior_inconclusive_attempts':sum(x['arm']==arm and x['status']=='inconclusive' and
                latest[(x['arm'],x['task_id'],x['repetition'])] is not x for x in rows),
            'successes':sum(x['success'] for x in conclusive),
            'inconclusive':sum(x['status']=='inconclusive' for x in r),
            'unresolved':sum(x['status']=='running' for x in r),'missing':planned-len(r),
            'wins':wins,'losses':losses,'ties':ties,'paired':matched,'unmatched':planned-matched,
            'repeat_tasks':len(repeated),'repeat_agreement':sum(v[0]==v[1] for v in repeated),
            'zero_success_tasks':sum(sum(v)==0 for v in repeated),
            'one_success_tasks':sum(sum(v)==1 for v in repeated),
            'two_success_tasks':sum(sum(v)==2 for v in repeated)})
    return out


def report(ledger):
    p=protocol()
    rows=[dict(x) for x in ledger.db.execute("SELECT * FROM runs WHERE phase='evaluation'")]
    table=scorecard(rows,p.arms,p.evaluation_tasks*p.repetitions)
    calls=[dict(x) for x in ledger.db.execute('SELECT * FROM calls')]
    for c in calls: c['data']=json.loads(c['data'])
    for row in table:
        arm=row['arm']
        for group,phases in [('learning',{'learning','selection'}),('execution',{'evaluation'})]:
            selected=[c for c in calls if c['arm']==arm and c['phase'] in phases]
            for kind in ['generation','embedding','token_count']:
                row[f'{group}_{kind}_calls']=sum(c['kind']==kind for c in selected)
                row[f'{group}_{kind}_s']=sum(c['data'].get('duration_s',0) for c in selected if c['kind']==kind)
            row[f'{group}_known_estimate_usd']=sum(c['estimate'] or 0 for c in selected)
            row[f'{group}_unknown_cost_calls']=sum(c['estimate'] is None for c in selected)
            row[f'{group}_reserved_unknown_usd']=sum(c['reservation'] for c in selected if c['estimate'] is None)
            generation=[c for c in selected if c['kind']=='generation' and c['status']!='not-dispatched']
            row[f'{group}_input_tokens']=sum(c['data']['usage']['prompt_token_count'] for c in generation) if all(c['data'].get('usage',{}).get('prompt_token_count') is not None for c in generation) else None
            row[f'{group}_output_tokens']=sum(c['data']['usage']['candidates_token_count'] for c in generation) if all(c['data'].get('usage',{}).get('candidates_token_count') is not None for c in generation) else None
            emb=[c for c in selected if c['kind']=='embedding']
            row[f'{group}_embedding_tokens']=sum(c['data']['input_tokens'] for c in emb) if all(c['data'].get('input_tokens') is not None for c in emb) else None
            row[f'{group}_embedding_truncated_inputs']=sum(bool(s and s.get('truncated'))
                for c in emb for s in c['data'].get('statistics',[]))
            row[f'{group}_request_s']=sum(c['data'].get('duration_s',0) for c in selected)
        own=[json.loads(x['data']) for x in rows if x['arm']==arm and x['status']=='conclusive']
        row['end_to_end_s']=sum(x['duration_s'] for x in own) if own else None
        row['tool_s']=sum(x['tool_s'] for x in own) if own else None
        row['grading_s']=sum(x.get('grading_s',0) for x in own) if own else None
        row['api_calls']=sum(x['api_calls'] for x in own) if own else None
        breaks=[observable_break(x) for x in own]
        row['runs_with_observed_tool_error']=sum(x['boundary']=='tool_execution_error' for x in breaks)
        row['runs_with_empty_executable_action']=sum(x['boundary']=='empty_executable_action' for x in breaks)
        row['actions_after_first_observed_error']=sum(x['later_actions'] for x in breaks)
        selection=[r['data'] for r in ledger.records('selection') if r['arm']==arm and r['phase']=='evaluation']
        row['memory_lookup_s']=sum(x['duration_s'] for x in selection) if selection else None
        token_by_run={r['run_id']:r['data']['tokens'] for r in ledger.records('selection')
                      if r['arm']==arm and r['phase']=='evaluation'}
        exposures=[r for r in ledger.records('exposure') if r['arm']==arm and r['phase']=='evaluation']
        row['memory_tokens_selected']=sum(x['tokens'] for x in selection) if selection else None
        row['memory_tokens_delivered']=sum(token_by_run[x['run_id']] for x in exposures) if exposures else None
        frozen=RESULTS/'memories'/arm/'frozen.json'
        f=read_json(frozen) if frozen.exists() else {}
        row['memory_entries']=f.get('entry_count')
        row['memory_export_bytes']=f.get('bytes')
        row['memory_content_bytes']=f.get('content_bytes')
        row['memory_working_directory_bytes']=f.get('storage_bytes')
        row['memory_event_count']=sum(r['arm']==arm and r['phase']=='learning' for r in ledger.records('memory_event'))
        row['format_error_calls']=sum(c['arm']==arm and c['phase'] in {'learning','selection','evaluation'}
            and format_diagnostic(c) is not None for c in calls)
        row['index_recovery_embedding_calls']=sum(c['arm']==arm and c['phase']=='learning' and c['kind']=='embedding' and
            c['data'].get('scope',{}).get('recovery')=='derived-vector-index' for c in calls)
        construction=[r['data'] for r in ledger.records('construction_complete') if r['arm']==arm and r['phase']=='learning']
        row['construction_wall_s']=sum(r['duration_s'] for r in construction) if construction else None
    RESULTS.mkdir(exist_ok=True)
    with (RESULTS/'comparison.csv').open('w',newline='') as file:
        w=csv.DictWriter(file,fieldnames=list(table[0])); w.writeheader(); w.writerows(table)
    measures={
        'completion':'official grades and runs', 'paired_benefit':'joined conclusive task/repetition IDs',
        'repeatability':'two conclusive attempts per task', 'learning_cost':'generation/embedding call ledger',
        'execution_cost':'evaluation call ledger', 'timing':'OS clocks and OpenTelemetry spans',
        'memory_footprint':'frozen exports and selected token counts', 'exposure':'selection and exposure records',
        'mechanism_execution':'native proposals/deltas/frontier/recurrence events',
        'errors_recovery':'native action/observation and error records', 'coverage':'all 72 planned cells'}
    checks=read_json(RESULTS/'software-checks.json') if (RESULTS/'software-checks.json').exists() else None
    live_count=sum(x['conclusive'] for x in table)
    lines=['# MC01 measured comparison','',f'Conclusive evaluation runs: {live_count}/72. ',
           'This is a small AppWorld development pilot. Actual invoice and provider backend timing remain unknown.','',
           '| Configuration | Success/conclusive | Planned | Missing | Inconclusive | W/L/T vs baseline |',
           '| --- | --- | --- | --- | --- | --- |']
    for x in table:
        lines.append(f"| {x['arm']} | {x['successes']}/{x['conclusive']} | {x['planned']} | {x['missing']} | {x['inconclusive']} | {x['wins']}/{x['losses']}/{x['ties']} |")
    lines+=['',f"Current-cell coverage above uses the latest eligible attempt. Total evaluation attempts: {sum(x['total_attempts'] for x in table)}; earlier inconclusive attempts: {sum(x['prior_inconclusive_attempts'] for x in table)}. Their requests, costs and original records remain retained."]
    lines+=['','## Expense, time and retained knowledge','',
        'Known cost estimates include the actual recorded learning attempts and recovery requests. Shared trace generation and excluded integration work are separate below. Times are measured boundary totals, not isolated model inference time.','',
        '| Configuration | Learning estimate USD | Evaluation estimate USD | Evaluation wall seconds | API calls | Entries | Content bytes | Delivered memory tokens |',
        '| --- | --- | --- | --- | --- | --- | --- | --- |']
    for x in table:
        lines.append(f"| {x['arm']} | {x['learning_known_estimate_usd']:.6f} | {x['execution_known_estimate_usd']:.6f} | {round(x['end_to_end_s'],2) if x['end_to_end_s'] is not None else 'unknown'} | {x['api_calls']} | {x['memory_entries']} | {x['memory_content_bytes']} | {x['memory_tokens_delivered']} |")
    lines+=['','## Repeatability','',
        '| Configuration | Agreeing task pairs | Tasks with 0 / 1 / 2 successes |',
        '| --- | --- | --- |']
    for x in table:
        lines.append(f"| {x['arm']} | {x['repeat_agreement']}/{x['repeat_tasks']} | {x['zero_success_tasks']} / {x['one_success_tasks']} / {x['two_success_tasks']} |")
    lines+=['','## Mechanisms that actually executed','']
    from collections import Counter
    events=ledger.records('memory_event')
    for arm in p.arms:
        operations=Counter(r['data']['operation'] for r in events if r['arm']==arm and r['phase']=='learning')
        lines.append(f"- {arm}: "+(', '.join(f'{k}={v}' for k,v in sorted(operations.items())) or 'no learning operations')+'.')
    arrivals=[r['data'] for r in events if r['arm']=='mem0' and r['phase']=='learning' and r['data']['operation']=='mem0_add']
    mutations=Counter(x.get('event','unknown') for r in arrivals for x in r['result'].get('results',[]))
    lines.append('- Mem0 returned mutation events: '+(', '.join(f'{k}={v}' for k,v in sorted(mutations.items())) or 'none')+
        f"; arrivals returning no mutation: {sum(not r['result'].get('results') for r in arrivals)}. A no-mutation return is not assumed to prove a successful native NONE decision.")
    gates=[r['data'] for r in events if r['arm']=='recmem' and r['phase']=='learning' and r['data']['operation']=='recurrence_gate']
    merges=[r['data'] for r in events if r['arm']=='recmem' and r['phase']=='learning' and r['data']['operation']=='episode_merge_decision']
    lines.append(f"- RecMem observed recurrence gates: {sum(g['relevant_count']>=g['required_count'] for g in gates)}/{len(gates)} met the native threshold; episode merges selected: {sum(bool(m['merged']) for m in merges)}/{len(merges)}. Invocation counts describe attempted mechanisms; before/after state records show their actual effects.")
    gepa_path=RESULTS/'memories/gepa/artifact.json'
    if gepa_path.exists() and not read_json(gepa_path).get('text'):
        lines.append('- GEPA retained its empty seed strategy after actual candidate testing. Its historical memory slot is identical to the baseline. Outcome differences between these two arms describe run variation and cannot establish benefit from learned instructions. Candidate testing still incurs learning expense.')
    verified=[r for r in ledger.records('saved_state_verification') if r['phase']=='evaluation']
    lines.append(f'\nSaved final states independently matched the actual completed application databases for {len(verified)} evaluation runs. The unchanged official evaluator runs in a fresh process; grading time is separately recorded in comparison.csv.')
    lines+=['','## What was actually measured','']
    for name,source in measures.items():
        exists={
            'completion':bool(live_count), 'paired_benefit':any(x['paired'] for x in table),
            'repeatability':any(x['repeat_tasks'] for x in table),
            'learning_cost':any(c['phase'] in ['learning','selection'] for c in calls),
            'execution_cost':any(c['phase']=='evaluation' for c in calls),
            'timing':any(c['phase']=='evaluation' for c in calls),
            'memory_footprint':any(x['memory_export_bytes'] is not None for x in table),
            'exposure':any(r['phase']=='evaluation' for r in ledger.records('exposure')),
            'mechanism_execution':bool(ledger.records('memory_event')),
            'errors_recovery':any(r['phase']=='evaluation' for r in ledger.records('action_observation')),
            'coverage':True}[name]
        status='live-measured (see per-arm coverage)' if exists else ('software-verified' if checks and checks.get('passed') else 'instrumented')
        lines.append(f'- {name}: {status}; collection: {source}. Coverage is shown in comparison.csv.')
    lines+=['','## Accounting and limitations','',
        f"Completed fresh API requests: {sum(c['status']=='live' for c in calls)}. Unsettled/unknown requests: {sum(c['status'] in {'pending','unknown'} for c in calls)}. Confirmed pre-dispatch rejections: {sum(c['status']=='not-dispatched' for c in calls)}.",
        f"Known usage estimate: ${sum(c['estimate'] or 0 for c in calls):.6f}. Retained unknown reservations: ${sum(c['reservation'] for c in calls if c['estimate'] is None):.6f}.",
        'Readiness and smoke are excluded from quality comparisons. Shared training traces are a separate common expense. GEPA selection is learning expense. Costs with missing usage remain unknown.',
        'Memory lookup includes embedding/count requests; do not add overlapping request and lookup times. Host load, provider scheduling/cold starts and alias revisions can affect observed latency. No isolated inference timing is claimed.',
        'Request and cost totals include recorded integration attempts. Construction wall time covers completed attempts; these are measured project costs, not isolated algorithmic cost estimates. Token-count requests are measurement/packing overhead and are shown separately.',
        'Only six evaluation tasks and two attempts are planned. There is one memory construction per method, no construction-variance estimate and no statistical superiority claim. Baseline wins and conclusive failures are retained.',
        'Exposure is observable delivery, not proof that a particular memory caused success. Failure attribution is limited to observable boundaries. Grader or instrumentation errors contaminate the affected comparison.',
        'The independent variable is the complete adapted policy, including learning, retrieval and context selection. This comparison cannot isolate an individual internal mechanism or vector store as the cause. Embedding-provider truncation statistics are recorded; an unreported resolved embedding version remains unknown.',
        'Unknown and missing cells prevent a complete ranking. No architecture benefit is established by missing evaluations.']
    lines+=['','## Shared and excluded work','']
    for phase in ['readiness','smoke','train']:
        cs=[c for c in calls if c['phase']==phase]
        lines.append(f"- {phase}: {len(cs)} requests; known estimate ${sum(c['estimate'] or 0 for c in cs):.6f}; {sum(c['estimate'] is None for c in cs)} unknown-cost requests.")
    invalid=[c for c in calls if (c['phase'] or '').startswith('invalidated-v1-')]
    invalid_runs=ledger.db.execute("SELECT count(*) FROM runs WHERE status='contaminated'").fetchone()[0]
    lines.append(f'- Contaminated v1 integration cohort, excluded: {invalid_runs} runs, {len(invalid)} requests, known estimate ${sum(c["estimate"] or 0 for c in invalid):.6f}. SQLAlchemy 2.1.5 produced inconsistent native database/grading metadata identities. All original actions, source identities, grades and artifacts remain retained. Protocol v2 rebuilt the common traces and every memory with SQLAlchemy 2.0.44 and saved-state verification; no v1 outcome enters the primary comparison.')
    errors=ledger.records('construction_error')+ledger.records('command_error')
    if errors:
        lines+=['','## Recorded interruptions','']
        for e in errors[-8:]:
            d=e['data'];lines.append(f"- {d.get('command',d.get('arm','unknown'))}: {d.get('type')}: {d.get('error',d.get('message','unknown'))}")
    diagnostics=[(c['id'],c['arm'],c['phase'],format_diagnostic(c)) for c in calls
                 if c['phase'] in {'learning','selection','evaluation'} and format_diagnostic(c)]
    if diagnostics:
        lines+=['','## Observable format rejections','',
                'These are deterministic checks of actual saved model output. They are distinct from official task grades. Native rejection/no-change behavior is retained.']
        lines.extend(f'- Call {ident} ({arm}, {phase}): {reason}.' for ident,arm,phase,reason in diagnostics)
    lines+=['','## Follow actual agent work','']
    for arm in p.arms:
        own=next((r for r in sorted(rows,key=lambda x:x['started']) if r['arm']==arm and r['status']=='conclusive'),None)
        if not own: continue
        data=json.loads(own['data'])
        selected=ledger.records('selection',own['id'])
        items=selected[0]['data']['items'] if selected else []
        lines+=[f"- {arm}: task `{own['task_id']}`, repetition {own['repetition']}, official success {bool(own['success'])}; {len(data['steps'])} execution steps and {data['api_calls']} actual API calls. Run `{own['id']}` links the exact requests, observations and grade. Selected IDs: {', '.join(str(x['id']) for x in items) or '(none)'}. Native trace: `{data['native_output']}`."]
        lines.append('  Task instruction: '+data['instruction'].replace('\n',' '))
        broken=observable_break(data)
        lines.append(f"  First observable boundary: {broken['boundary']}, step {broken['step']}; later execution actions: {broken['later_actions']}. This records continuation after an error, not a proven causal recovery. Hidden causes remain unknown.")
    if live_count==72:
        most=max(x['successes'] for x in table)
        best=', '.join(x['arm'] for x in table if x['successes']==most)
        lines+=['','## Conditional result','',f"Highest observed completion: {best}, {most}/12. Compare paired outcomes and learning overhead before adoption; this finite pilot does not establish a universal winner."]
        baseline=next(x for x in table if x['arm']=='baseline')
        improved=[x for x in table if x['arm']!='baseline' and x['memory_content_bytes'] and
                  x['successes']>baseline['successes']]
        if not improved:
            lines.append('For this task mix and model, retain the baseline as the default: no nonempty learned policy improved observed completion, and the baseline requires no cross-task memory construction. This pilot supplies no observed gain that pays for adding retained knowledge. Larger or different task populations may change that choice.')
        else:
            best_nonempty=max(x['successes'] for x in improved)
            candidates=[x for x in improved if x['successes']==best_nonempty]
            choice=min(candidates,key=lambda x:x['learning_known_estimate_usd']+x['execution_known_estimate_usd'])
            lines.append(f"For a follow-up on similar tasks, prioritize {choice['arm']}: among nonempty learned policies that improved observed completion over baseline, it ties the highest completion with the lowest known learning-plus-evaluation estimate among those tied methods. This is a conditional pilot choice; paired outcomes, extra selection experience and the single construction per policy limit generalization.")
    else:
        lines+=['','## Current conclusion','','Comparison incomplete. No overall winner or memory benefit is established.']
    (RESULTS/'REPORT.md').write_text('\n'.join(lines)+'\n')
    print(f'Report: {RESULTS / "REPORT.md"}',flush=True)


def bundle(ledger):
    # Consistent SQLite backup, with one canonical compressed copy of native evidence.
    snapshot=CACHE/'ledger-bundle.sqlite'
    backup=sqlite3.connect(snapshot)
    ledger.db.backup(backup); backup.close()
    files={'ledger.sqlite':snapshot}
    for name in ['protocol.json','EXPERIMENT.md','FIDELITY.md','requirements.lock']:
        p=ROOT/name
        if p.exists(): files[name]=p
    for p in list((ROOT/'mc').glob('*.py'))+list((ROOT/'tests').glob('*.py')):
        files[str(Path('source')/p.relative_to(ROOT))]=p
    for name in ['bootstrap.py','README.md','DOCUMENTATION.md','CONTEXT.md']:
        p=ROOT/name
        if p.exists(): files[str(Path('source')/name)]=p
    if (CACHE/'preparation.json').exists(): files['dataset-manifest.json']=CACHE/'preparation.json'
    for base,prefix in [(RESULTS/'memories','memories'),(WORLD/'experiments/outputs/MC01','native')]:
        if base.exists():
            for p in base.rglob('*'):
                if p.is_file() and not p.is_symlink() and p.name!='.lock':
                    files[str(Path(prefix)/p.relative_to(base))]=p
    for name in ['comparison.csv','REPORT.md','freeze.json','smoke.json','corpus.json','software-checks.json','integrity.json']:
        p=RESULTS/name
        if p.exists(): files[name]=p
    manifest={name:digest(path.read_bytes()) for name,path in files.items()}
    write_json(RESULTS/'evidence-manifest.json',manifest)
    with tarfile.open(RESULTS/'evidence.tar.gz','w:gz') as archive:
        for name,path in files.items(): archive.add(path,arcname=name,recursive=False)
        archive.add(RESULTS/'evidence-manifest.json',arcname='manifest.json')
    snapshot.unlink()
