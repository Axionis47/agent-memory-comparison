"""MC01 operational orchestration around the unchanged frozen experiment code."""
from pathlib import Path
import argparse
import json

from mc.core import ROOT, CACHE, WORLD, Ledger, RESULTS, Inconclusive, digest, evaluation_cells, read_json, serial_lock, tree_identity, write_json


def run(ledger,resume=False):
    import mc.__main__ as frozen_runner
    from mc.provider import Vertex
    frozen=read_json(RESULTS/'freeze.json')
    cells=evaluation_cells(frozen['population'])
    def eligible(cell):
        previous=ledger.latest(cell)
        if previous is None or previous['phase']!='evaluation' or previous['status']=='contaminated':
            return True
        return resume and previous['status']=='inconclusive'
    selected=[cell for cell in cells if eligible(cell)]
    ledger.record('operational_orchestration',{
        'classification':'not-a-model','frozen_identity':frozen['hash'],
        'source':Path(__file__).read_text(),'source_hash':digest(Path(__file__).read_bytes()),
        'selected_cells':[c.model_dump() for c in selected],
        'reason':'Dispatch planned cells individually through the frozen evaluator, continuing past known operational output/watchdog interruptions. Preserve their inconclusive status and every conclusive outcome.'})
    vertex=Vertex(ledger)
    original=frozen_runner.evaluation_cells
    for cell in selected:
        frozen_runner.evaluation_cells=lambda population:[cell]
        try:
            frozen_runner.evaluate(vertex)
        except Inconclusive:
            result=ledger.latest(cell)
            if result is None or result['status']!='inconclusive':raise
            error=json.loads(result['data']).get('error')
            if vertex.blocked or error not in {
                'Generation truncated by operational output allowance',
                'Operational step watchdog or abnormal agent termination'}:raise
            ledger.record('retained_inconclusive',{'cell':cell.model_dump(),'run_id':result['id'],
                'error':error,'classification':'not-a-model','scored_as_failure':False},
                result['id'],cell.arm,'evaluation')
        finally:
            frozen_runner.evaluation_cells=original
    print('All selected planned cells attempted; inconclusive attempts remain excluded.',flush=True)


def finish(ledger):
    """Audit accepted runs and preserve inconclusive coverage without scoring it."""
    from collections import Counter
    import csv
    import io
    import tarfile
    from mc.__main__ import identity
    from mc.memory import MemoryPolicy, experience_units
    from mc.report import report, bundle
    from appworld import AppWorld
    frozen=read_json(RESULTS/'freeze.json')
    assert identity()==frozen['identity'], 'Frozen experiment source or dependencies changed'
    for task,expected in frozen['inputs'].items():
        assert tree_identity(WORLD/'data/tasks'/task)==expected
    corpus=read_json(RESULTS/'corpus.json')
    assert digest(corpus['experiences'])==corpus['sha256']
    units={digest(u) for u in experience_units(corpus['experiences'])}
    events=[r for r in ledger.records('memory_event') if r['phase']=='learning']
    for arm,operation in [('mem0','mem0_add'),('recmem','recmem_arrival')]:
        actual=[r['data']['unit_hash'] for r in events if r['arm']==arm and r['data']['operation']==operation]
        assert len(actual)==len(units) and set(actual)==units
    latest=[ledger.latest(c) for c in evaluation_cells(frozen['population'])]
    missing=[i for i,r in enumerate(latest) if r is None or r['phase']!='evaluation']
    if missing:raise Inconclusive(f'{len(missing)} planned cells have not been attempted')
    assert all(r['status'] in {'conclusive','inconclusive'} for r in latest)
    rows=[dict(r) for r in ledger.db.execute("SELECT * FROM runs WHERE phase='evaluation' ORDER BY started")]
    calls=[dict(c) for c in ledger.db.execute("SELECT * FROM calls WHERE phase='evaluation' ORDER BY started")]
    assert all(c['status']!='pending' and c['ended'] is not None for c in calls)
    assert all(a['ended']<=b['started'] for a,b in zip(calls,calls[1:])), 'Requests overlapped'
    traced={r['data']['attributes'].get('call_id') for r in ledger.records('span')}
    assert all(c['id'] in traced for c in calls if c['kind'] in {'generation','embedding'})
    ledger.record('reconciliation_source',{'classification':'not-a-model',
        'source':Path(__file__).read_text(),'source_hash':digest(Path(__file__).read_bytes()),
        'frozen_identity':frozen['hash'],'purpose':'Reconcile all planned cells, including unknown outcomes. The frozen strict audit requires every cell to have a usable grade; this coverage audit never converts an inconclusive outcome into a grade.'})
    resets={task:set() for task in frozen['population']['evaluation']}
    prompts={task:set() for task in frozen['population']['evaluation']}
    recmem=read_json(RESULTS/'memories/recmem/artifact.json')
    logical_by_run={};ambiguous_points=0
    receipts=[r for r in ledger.records('construction_complete') if r['phase']=='learning']
    for arm,metadata in frozen['memories'].items():
        assert any(r['arm']==arm and r['data']['version']==metadata['version'] and
            r['data']['corpus_hash']==corpus['sha256'] for r in receipts)
        memory=MemoryPolicy(arm,None)
        try:assert memory.version==metadata['version'] and memory.export()==memory.state
        finally:memory.close()
    responses=[];confirmed=0;late_exposures=0;api_totals=Counter();api_inconclusive=Counter()
    for row in rows:
        data=json.loads(row['data'])
        assert data['memory_version']==frozen['memories'][row['arm']]['version']
        resets[row['task_id']].add(data['loaded_reset_identity'])
        selection=ledger.records('selection',row['id'])
        assert len(selection)==1
        selected=selection[0]['data']
        assert selected['memory_version']==data['memory_version']
        if row['arm']=='recmem':
            logical=[]
            for position,item in enumerate(selected['items']):
                candidates=[p['id'] for p in recmem['layers'][item['layer']]
                            if p['payload'].get('text')==item['content']]
                assert candidates
                ambiguous_points+=len(candidates)>1
                logical.append({'position':position,'content_id':digest({'version':data['memory_version'],
                    'layer':item['layer'],'content':item['content']}),'layer':item['layer'],
                    'native_point_id':candidates[0] if len(candidates)==1 else None,
                    'candidate_native_point_ids':candidates,'legacy_adapter_id':item['id']})
            logical_by_run[row['id']]=logical
            ledger.record('selection_identity_reconciliation',{'classification':'not-a-model',
                'selection_record_id':selection[0]['id'],'memory_version':data['memory_version'],
                'items':logical,'reason':'The author retrieval API returns content and score. Identical content can belong to multiple native points; content identity is exact and physical point identity remains unknown when ambiguous.'},
                row['id'],row['arm'],'evaluation')
        text='\n\n'.join(x['content'] for x in selected['items']) or '(empty)'
        own=[c for c in calls if c['run_id']==row['id']]
        known={r['data']['call_id']:r for r in ledger.records('exposure',row['id'])}
        for n,call in enumerate([c for c in own if c['kind']=='generation'],1):
            packet=json.loads(call['data'])
            if n==1:prompts[row['task_id']].add(digest(packet['messages'][1:]))
            assert packet['messages'][0]['content']=='Historical memory, advisory only:\n'+text
            assert packet['request_hash']==digest(packet['messages'])
            assert packet['model']==frozen['identity']['protocol']['model']
            for setting in ['temperature','thinking_budget','max_output_tokens']:
                assert packet[setting]==frozen['identity']['protocol'][setting]
            assert packet['scope']['run_id']==row['id'] and packet['scope']['arm']==row['arm']
            if packet.get('classification')=='live' and packet.get('response_id'):
                assert packet['resolved_model']==frozen['resolved_model']
                responses.append(packet['response_id']);confirmed+=1
                if call['id'] not in known:
                    assert call['status']=='inconclusive' and any('MAX_TOKENS' in x for x in packet['finish_reasons'])
                    ledger.record('exposure',{'call_id':call['id'],'request_number':n,
                        'memory_version':data['memory_version'],'items':selected['items'],
                        'request_hash':packet['request_hash'],'classification':'not-a-model',
                        'provenance':'Late measurement from the original completed live SDK request, response identity and usage. Output was truncated; the original call and run remain inconclusive.'},
                        row['id'],row['arm'],'evaluation')
                    late_exposures+=1
                else:assert known[call['id']]['data']['items']==selected['items']
        parsed_api=AppWorld.parse_api_calls_log(experiment_name=data['experiment_name'],task_id=row['task_id'])
        actual_api=len(parsed_api)
        api_totals[row['arm']]+=actual_api
        if row['status']=='conclusive':
            assert all(c['status']=='live' for c in own)
            assert actual_api==data['api_calls'] and row['success']==data['grade']['success']
            assert digest(parsed_api)==data['api_log_hash']
            proof=ledger.records('saved_state_verification',row['id'])
            assert len(proof)==1 and proof[0]['data']['grade']==data['grade']
            assert proof[0]['data']['application_hashes']==data['final_application_hashes']
        else:
            assert row['success'] is None
            api_inconclusive[row['arm']]+=actual_api
        ledger.record('attempt_reconciliation',{'classification':'not-a-model','run_id':row['id'],
            'status':row['status'],'actual_api_calls':actual_api,'accounted_requests':len(own),
            'memory_version':data['memory_version']},row['id'],row['arm'],'evaluation')
    assert all(len(x)==1 for x in resets.values()) and len(responses)==len(set(responses))
    assert all(len(x)==1 for x in prompts.values()), 'Initial native prompts differ beyond memory'
    late_total=sum(bool(r['data'].get('provenance')) for r in ledger.records('exposure')
                   if r['phase']=='evaluation')
    conclusive=sum(r['status']=='conclusive' for r in latest)
    result={'accepted':True,'classification':'not-a-model','quality_comparison_complete':conclusive==72,
        'frozen_identity':frozen['hash'],'planned':72,'attempted_cells':len(latest),'attempts':len(rows),
        'conclusive_cells':conclusive,'inconclusive_cells':72-conclusive,'missing_cells':0,
        'matched_construction_receipts':6,'shared_training_corpus_sha256':corpus['sha256'],
        'unique_reset_identities_per_task':{k:len(v) for k,v in resets.items()},
        'initial_native_prompt_identities_per_task':{k:len(v) for k,v in prompts.items()},
        'confirmed_generation_requests':confirmed,'late_exposure_measurements':late_total,
        'late_exposure_measurements_added_this_pass':late_exposures,
        'serial_accounted_evaluation_requests':len(calls),
        'unknown_requests':sum(c['status']=='unknown' for c in calls),
        'read_only_memory_artifacts':6,'excluded_contaminated_runs':30}
    result['recmem_exposure_positions_with_ambiguous_physical_point_ids']=ambiguous_points
    protected=CACHE/'protected-check.json'
    if protected.exists():
        verification=read_json(protected)
        assert verification['unchanged']
        result['protected_files_verified']=verification['protected_files']
        result['protected_collections_unchanged']=True
    ledger.record('coverage_integrity_audit',result);write_json(RESULTS/'integrity.json',result)
    report(ledger)
    path=RESULTS/'comparison.csv'
    with path.open(newline='') as stream:table=list(csv.DictReader(stream))
    first={}
    for attempt in rows:first.setdefault(attempt['cell_key'],attempt)
    for row in table:
        row['all_attempt_api_calls']=api_totals[row['arm']]
        row['inconclusive_attempt_api_calls']=api_inconclusive[row['arm']]
        own=[json.loads(r['data']) for r in rows if r['arm']==row['arm']]
        row['all_attempt_wall_s']=sum(d['duration_s'] for d in own)
        row['all_attempt_tool_s']=sum(d['tool_s'] for d in own)
        row['inconclusive_attempt_wall_s']=sum(json.loads(r['data'])['duration_s'] for r in rows
            if r['arm']==row['arm'] and r['status']=='inconclusive')
        row['minimum_successes_in_planned_cells']=int(row['successes'])
        row['maximum_successes_in_planned_cells']=int(row['successes'])+int(row['inconclusive'])+int(row['missing'])
        initial=[r for r in first.values() if r['arm']==row['arm']]
        row['first_attempt_conclusive']=sum(r['status']=='conclusive' for r in initial)
        row['first_attempt_successes']=sum(r['success'] or 0 for r in initial)
        row['first_attempt_inconclusive']=sum(r['status']=='inconclusive' for r in initial)
    with path.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(table[0]));writer.writeheader();writer.writerows(table)
    report_path=RESULTS/'REPORT.md'
    rendered=report_path.read_text().replace('Evaluation wall seconds','Graded-run wall seconds')
    rendered=rendered.replace('Completed fresh API requests:','Requests settled with live status:')
    rendered=rendered.replace('No overall winner or memory benefit is established.',
                              'No overall winner or general memory benefit is established.')
    example=next((r for r in rows if r['arm']=='recmem' and r['status']=='conclusive'),None)
    if example:
        display=', '.join(x['content_id'] for x in logical_by_run[example['id']])
        rendered='\n'.join(line.split('Selected IDs:')[0]+'Selected logical content IDs: '+display+
            '. Native trace:'+line.split('. Native trace:',1)[1]
            if line.startswith('- recmem:') and 'Selected IDs:' in line else line
            for line in rendered.splitlines())+'\n'
    report_path.write_text(rendered)
    with (RESULTS/'REPORT.md').open('a') as stream:
        stream.write(f'\n## Operational reconciliation\n\nAll 72 planned cells were attempted: {conclusive} have accepted official grades and {72-conclusive} remain inconclusive. There were {len(rows)} actual evaluation attempts. Frozen experiment code, tasks, settings and all six memory versions still match. The coverage integrity audit accepts the accounting; it does not turn unknown outcomes into task failures or establish a complete quality comparison.\n\n')
        stream.write(f'{late_total} missing exposure measurements were reconstructed from the original SDK requests, completed response identities and usage. No output was replayed and no call/run status was changed. Delivered-token totals include these confirmed inputs. API-call columns distinguish accepted-run counts from all attempts.\n\n')
        stream.write('Operational truncation can depend on the memory policy, so missingness may be informative. Compare planned coverage alongside successes/conclusive, and do not rank policies from their conclusive percentages alone. The exact dispatch and reconciliation source is in source/pilot.py and versioned ledger records.\n')
        stream.write(f'The {late_total} truncated generation responses also completed at the provider and contain actual usage, but retain inconclusive call/run status. They are included in request accounting and costs, without becoming task grades.\n')
        stream.write('The planned order was rotated, and interruptions/resumption changed the actual execution order. Every request is serial and timestamped, but host load, cloud scheduling, connection reuse and order can confound timing. No isolated inference-speed claim is made. Planned-success bounds in the CSV range from known successes to known successes plus unknown cells; they are logical bounds, not imputed scores or confidence intervals.\n')
        stream.write('The original wall/tool/API columns aggregate graded runs. Additional all-attempt and inconclusive-attempt columns expose the operational work outside that population. Request/token/cost totals include all actual evaluation attempts.\n')
        stream.write(f'\nRecMem exposure identity correction: {ambiguous_points} selected positions match multiple stored points with identical text. The legacy adapter selected the first matching UUID; that is not proof of which physical point was returned. Versioned content identities, positions and all candidate native point IDs are recorded in selection_identity_reconciliation. Exact content exposure remains known; ambiguous physical identities remain unknown.\n')
        stream.write('\n## First-attempt coverage\n\nThe primary table uses the latest eligible accepted attempt, as specified by the resumption policy. This table exposes the initial attempts separately; an unknown initial outcome is never imputed as success or failure.\n\n| Configuration | Initial successes / conclusive | Planned | Initial inconclusive |\n| --- | --- | --- | --- |\n')
        for r in table:
            stream.write(f"| {r['arm']} | {r['first_attempt_successes']}/{r['first_attempt_conclusive']} | 12 | {r['first_attempt_inconclusive']} |\n")
        arms=list(frozen['memories'])
        stream.write('\n## Same tasks, different memory policies\n\nEvery task below is upstream-authored. Each cell is successes/conclusive, with two planned attempts; a question mark marks an unknown outcome.\n\n| Upstream task | '+ ' | '.join(arms)+' |\n| --- | '+ ' | '.join('---' for _ in arms)+' |\n')
        for task in frozen['population']['evaluation']:
            values=[]
            for arm in arms:
                pair=[r for r in latest if r['arm']==arm and r['task_id']==task]
                successes=sum(r['success'] or 0 for r in pair)
                grades=sum(r['status']=='conclusive' for r in pair)
                values.append(f'{successes}/{grades}'+(' + ?' if grades<2 else ''))
            stream.write('| '+task+' | '+' | '.join(values)+' |\n')
        stream.write('\nTask instructions:\n\n')
        for task in frozen['population']['evaluation']:
            instruction=json.loads(next(r for r in rows if r['task_id']==task)['data'])['instruction']
            stream.write('- '+task+': '+instruction.replace('\n',' ')+'\n')
        stream.write('\n## Official requirements that failed\n\nThese are the evaluator\'s observed failed contracts, not inferred hidden causes. Counts can exceed task failures because one task can fail several checks.\n\n')
        for arm in frozen['memories']:
            failures=Counter(f['requirement'] for r in latest if r['arm']==arm and r['status']=='conclusive'
                for f in json.loads(r['data'])['grade']['failures'])
            stream.write('- '+arm+': '+('; '.join(f'{name.replace(chr(10)," ")} ({count})'
                for name,count in failures.most_common(3)) or 'no failed requirements')+'.\n')
        incomplete=[r for r in latest if r['status']=='inconclusive']
        if incomplete:
            stream.write('\n## Cells with unknown task outcomes\n\n')
            for r in incomplete:
                stream.write(f"- {r['arm']}, {r['task_id']}, repetition {r['repetition']}: {json.loads(r['data']).get('error','unknown cause')}. Run {r['id']}. Excluded from task-completion comparisons.\n")
        complete=[r for r in table if int(r['conclusive'])==12]
        if complete:
            highest=max(int(r['successes']) for r in complete)
            tied=[r for r in complete if int(r['successes'])==highest]
            least=min(tied,key=lambda r:float(r['learning_known_estimate_usd'])+float(r['execution_known_estimate_usd']))
            stream.write(f"\n## Conditional choice for this pilot\n\nAmong fully graded configurations, {', '.join(r['arm'] for r in tied)} have the highest observed count, {highest}/12; {least['arm']} has the lowest known policy expense among them. ")
        skill=next(r for r in table if r['arm']=='trace2skill')
        stream.write(f"Trace2Skill has {skill['successes']} known successes, {skill['wins']} paired wins, {skill['losses']} paired losses and {skill['unmatched']} unmatched outcomes. Its initial attempts supplied {skill['first_attempt_successes']} successes across {skill['first_attempt_conclusive']} conclusive cells and {skill['first_attempt_inconclusive']} unknowns. Interpret the observed gains alongside generation reliability and resumption cost. This small, single-construction pilot does not establish statistical superiority or reproduce paper scores.\n")
    bundle(ledger)
    # Add this separately versioned orchestration/derivation source to the one bundle.
    archive_path=RESULTS/'evidence.tar.gz';temporary=CACHE/'evidence-working.tar.gz'
    manifest=read_json(RESULTS/'evidence-manifest.json')
    manifest['source/pilot.py']=digest(Path(__file__).read_bytes())
    write_json(RESULTS/'evidence-manifest.json',manifest)
    with tarfile.open(archive_path,'r:gz') as original,tarfile.open(temporary,'w:gz') as final:
        for member in original:
            if member.name!='manifest.json':final.addfile(member,original.extractfile(member))
        final.add(Path(__file__),arcname='source/pilot.py',recursive=False)
        payload=json.dumps(manifest,indent=2).encode()+b'\n'
        info=tarfile.TarInfo('manifest.json');info.size=len(payload);final.addfile(info,io.BytesIO(payload))
    temporary.replace(archive_path)
    print(json.dumps(result),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['run','finish'])
    parser.add_argument('--resume-inconclusive',action='store_true')
    args=parser.parse_args()
    ledger=Ledger()
    with serial_lock():
        if args.command=='run':run(ledger,args.resume_inconclusive)
        else:finish(ledger)


if __name__=='__main__':main()
