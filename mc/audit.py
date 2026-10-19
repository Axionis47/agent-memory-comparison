"""Reconcile this pilot's planned cells with its observable evidence."""
import json

from .core import RESULTS, Ledger, Inconclusive, digest, evaluation_cells, read_json, write_json


def audit(ledger):
    from .__main__ import identity
    from .memory import MemoryPolicy
    from appworld import AppWorld
    frozen=read_json(RESULTS/'freeze.json')
    assert identity()==frozen['identity'], 'Frozen runtime changed'
    corpus=read_json(RESULTS/'corpus.json')
    assert corpus['sha256']==digest(corpus['experiences'])
    receipts=[r for r in ledger.records('construction_complete') if r['phase']=='learning']
    for arm,memory in frozen['memories'].items():
        assert any(r['arm']==arm and r['data']['version']==memory['version'] and
            r['data']['corpus_hash']==corpus['sha256'] for r in receipts)
    rows=[ledger.latest(cell) for cell in evaluation_cells(frozen['population'])]
    if any(r is None or r['status']!='conclusive' for r in rows):
        raise Inconclusive('Every planned cell needs a conclusive accepted attempt before final audit')
    resets={task:set() for task in frozen['population']['evaluation']}
    generation_ids=[]
    exposure_count=0
    for r in rows:
        data=json.loads(r['data'])
        assert r['success']==data['grade']['success']
        assert data['memory_version']==frozen['memories'][r['arm']]['version']
        resets[r['task_id']].add(data['loaded_reset_identity'])
        assert data['api_calls']==len(AppWorld.parse_api_calls_log(
            experiment_name=data['experiment_name'],task_id=r['task_id']))
        checks=ledger.records('saved_state_verification',r['id'])
        assert len(checks)==1 and checks[0]['data']['application_hashes']==data['final_application_hashes']
        assert checks[0]['data']['grade']==data['grade']
        selected=ledger.records('selection',r['id'])
        assert len(selected)==1 and selected[0]['data']['memory_version']==data['memory_version']
        text='\n\n'.join(x['content'] for x in selected[0]['data']['items']) or '(empty)'
        exposures=ledger.records('exposure',r['id'])
        calls=[dict(c) for c in ledger.db.execute('SELECT * FROM calls WHERE run_id=?',(r['id'],))]
        assert all(c['status']=='live' for c in calls)
        generations={c['id']:json.loads(c['data']) for c in calls if c['kind']=='generation'}
        assert {e['data']['call_id'] for e in exposures}==set(generations)
        assert len(exposures)==len(generations)
        for e in exposures:
            packet=generations[e['data']['call_id']]
            assert packet['classification']=='live'
            assert packet['messages'][0]['content']=='Historical memory, advisory only:\n'+text
            assert e['data']['items']==selected[0]['data']['items']
            assert packet['resolved_model']==frozen['resolved_model']
            if packet.get('response_id'):generation_ids.append(packet['response_id'])
        exposure_count+=len(exposures)
    assert all(len(values)==1 for values in resets.values()), 'World resets differ'
    assert len(generation_ids)==len(set(generation_ids)), 'Duplicate provider response identity'
    calls=list(ledger.db.execute("SELECT * FROM calls WHERE phase='evaluation' ORDER BY started"))
    assert all(c['status']=='live' and c['ended'] is not None for c in calls)
    assert all(a['ended']<=b['started'] for a,b in zip(calls,calls[1:])), 'Overlapping requests'
    traced={r['data']['attributes'].get('call_id') for r in ledger.records('span')}
    assert all(c['id'] in traced for c in calls if c['kind'] in {'generation','embedding'})
    for arm in frozen['memories']:
        memory=MemoryPolicy(arm,None)
        try: assert memory.version==frozen['memories'][arm]['version'] and memory.export()==memory.state
        finally: memory.close()
    result={'accepted':True,'classification':'not-a-model','frozen_identity':frozen['hash'],
        'planned_and_conclusive':len(rows),'unique_reset_identities_per_task':{k:len(v) for k,v in resets.items()},
        'shared_training_corpus_sha256':corpus['sha256'],'matched_construction_receipts':len(frozen['memories']),
        'verified_saved_final_states':len(rows),'verified_context_exposures':exposure_count,
        'serial_accounted_evaluation_requests':len(calls),'distinct_provider_generation_responses':len(generation_ids),
        'read_only_memory_artifacts':len(frozen['memories']),
        'excluded_contaminated_runs':ledger.db.execute("SELECT count(*) FROM runs WHERE status='contaminated'").fetchone()[0]}
    ledger.record('integrity_audit',result)
    write_json(RESULTS/'integrity.json',result)
    print(json.dumps(result),flush=True)
