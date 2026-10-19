from __future__ import annotations

import csv
import io
import json
import sqlite3
import tarfile

from mc.core import digest, dumps, read_json, write_json, WORLD
from .runtime import RESULTS, ROOT, ARMS, flatten, mark, source_identity, experience, population


def diagnostics(memory, checkpoint, vertex):
    """Read-only source-addressability probes and explicitly fallible live review."""
    ledger=vertex.ledger;before=memory.export()
    corpus=[]
    for task in population()['practice'][:checkpoint]:
        row=ledger.db.execute('SELECT * FROM runs WHERE phase="practice" AND arm=? AND task_id=? '
                              'AND status="conclusive" ORDER BY started DESC LIMIT 1',(memory.arm,task)).fetchone()
        if row:corpus.append(experience(dict(row),ledger))
    probes=sorted(corpus,key=lambda e:digest('reachability:'+e['run_id']))[:8]
    for exp in probes:
        key=digest([memory.arm,checkpoint,exp['run_id'],'reachability'])
        if any(r['data']['key']==key for r in ledger.records('reachability')):continue
        errors=[s for s in exp['steps'] if any('Execution failed' in o for o in s['outputs'])]
        query=dumps({'task':exp['instruction'],'observed_error':errors[0] if errors else None})
        with vertex.scoped(phase='reachability',arm=memory.arm,checkpoint=checkpoint):
            selected,omitted,tokens=vertex.pack(memory.select(query))
        current_ids={x['id'] for x in flatten(before)}
        targets=sorted(i for i,sources in memory.lineage.items() if exp['run_id'] in sources and i in current_ids)
        selected_ids=[x['id'] for x in selected]
        if memory.arm=='ace':
            import re
            selected_ids+=re.findall(r'^\[([^\]]+)\] helpful=',
                                   '\n'.join(x['content'] for x in selected),flags=re.MULTILINE)
        hits=[i for i in targets if i in selected_ids]
        mark(ledger,'reachability',{'key':key,'checkpoint':checkpoint,'source_run':exp['run_id'],
             'query':query,'target_ids':targets,'hit_ids':hits,'selected':selected,'omitted':omitted,
             'tokens':tokens,'memory_version':memory.version,
             'interpretation':'operation-source addressability, not universal relevance or useful-memory recall'},
             memory.arm,'reachability')
    # Sample changed current items only. Unchanged/stale items are not silently
    # counted as newly consolidated findings. Review labels never gate task scores.
    changes={}
    for r in ledger.records('consolidation'):
        if r['arm']!=memory.arm or (r['data'].get('sequence') or 0)>checkpoint:continue
        delta=r['data']['changes']
        for item in delta['added']+[x['after'] for x in delta['updated']]:
            changes[(item['id'],digest(item['content']))]=(item,r['data']['source_runs'])
    current={(x['id'],digest(x['content'])) for x in flatten(before)}
    candidates=[v for k,v in changes.items() if k in current]
    candidates=sorted(candidates,key=lambda v:digest(['review',checkpoint,v[0]]))[:20]
    for item,sources in candidates:
        key=digest([memory.arm,checkpoint,item,'review'])
        if any(r['data']['key']==key for r in ledger.records('consolidation_review')):continue
        evidence=[e for e in corpus if e['run_id'] in sources]
        with vertex.scoped(phase='review',arm=memory.arm,checkpoint=checkpoint):
            result=vertex.text('Review this learned memory against only supplied observable source evidence. '
                'Return JSON {"assessment":"supported" or "contradicted" or "unsupported" or "ambiguous",'
                '"evidence_refs":["run ID and step"],"lost_conditions":["condition"],'
                '"explanation":"short public evidence-based justification"}. '
                'Do not infer hidden causes or trust a memory just because it exists. '
                'If source ancestry is broad or evidence insufficient, say so.\n'+
                dumps({'memory':item,'source_experience':evidence}),json_mode=True,purpose='consolidation-review')
        try:
            review=json.loads(result)
            if review.get('assessment') not in {'supported','contradicted','unsupported','ambiguous'}:
                raise ValueError('unknown assessment')
        except (ValueError,TypeError):review={'assessment':'invalid-review','raw_output':result}
        mark(ledger,'consolidation_review',{'key':key,'checkpoint':checkpoint,'item':item,
             'memory_version':memory.version,'source_runs':sources,'review':review,
             'interpretation':'live reviewer assessment, not benchmark ground truth'},memory.arm,'review')
    if memory.export()!=before:raise RuntimeError('Read-only diagnostics changed memory')


def integrity(ledger):
    from .runtime import evaluation_cells
    planned=[c for cp in [6,12,24] for c in evaluation_cells(cp)]
    latest=[]
    for cell in planned:
        r=ledger.latest(cell)
        latest.append((cell,r))
    pending=ledger.db.execute("SELECT count(*) FROM calls WHERE status IN ('pending','unknown')").fetchone()[0]
    freezes=ledger.records('experiment_freeze')
    source_ok=bool(freezes) and freezes[-1]['data']['source_identity']==source_identity()
    conclusive=[r for _,r in latest if r and r['status']=='conclusive']
    # Explicit dispatch chronology; every SDK request must be serial and settled.
    calls=[dict(r) for r in ledger.db.execute('SELECT * FROM calls ORDER BY started')]
    overlaps=[]
    for a,b in zip(calls,calls[1:]):
        if a['ended'] is not None and a['ended']>b['started']:
            overlaps.append([a['id'],b['id']])
    bad_grades=[]
    for r in conclusive:
        d=json.loads(r['data'])
        if not d.get('grade') or 'final_application_hashes' not in d:bad_grades.append(r['id'])
    result={'classification':'not-a-model','planned':448,'attempted_cells':sum(r is not None for _,r in latest),
        'conclusive_cells':len(conclusive),'inconclusive_cells':sum(r is not None and r['status']=='inconclusive' for _,r in latest),
        'missing_cells':sum(r is None for _,r in latest),'unknown_requests':pending,'serial_overlaps':overlaps,
        'source_unchanged':source_ok,'invalid_grade_records':bad_grades,
        'quality_comparison_complete':len(conclusive)==448,
        'accepted':source_ok and pending==0 and not overlaps and not bad_grades}
    write_json(RESULTS/'integrity.json',result)
    return result,latest


def report(ledger):
    audit,latest=integrity(ledger)
    fields=['checkpoint','arm','mode','planned','attempted','conclusive','successes','inconclusive','missing',
            'wins','losses','ties','unmatched','evaluation_estimate_usd','evaluation_requests','wall_s',
            'entries','content_bytes','tool_queries','calls_without_exposed_definition']
    rows=[]
    for checkpoint in [6,12,24]:
        modes=['full']+(['execution_off','discovery_off'] if checkpoint==24 else [])
        for mode in modes:
            for arm in ARMS if mode=='full' else ARMS[1:]:
                cells=[(c,r) for c,r in latest if c.checkpoint==checkpoint and c.mode==mode and c.arm==arm]
                done=[r for _,r in cells if r and r['status']=='conclusive']
                wins=losses=ties=unmatched=0
                for c,r in cells:
                    ref=next((v for t,v in latest if t.checkpoint==checkpoint and t.task_id==c.task_id
                              and t.repetition==c.repetition and t.mode=='full'
                              and t.arm==('baseline' if mode=='full' else arm)),None)
                    if r and ref and r['status']==ref['status']=='conclusive':
                        wins+=r['success']>ref['success'];losses+=r['success']<ref['success'];ties+=r['success']==ref['success']
                    else:unmatched+=1
                attempts=[dict(r) for r in ledger.db.execute('SELECT * FROM runs WHERE phase="evaluation" AND arm=?',(arm,))
                          if (d:=json.loads(r['data'])).get('cell',{}).get('checkpoint')==checkpoint
                          and d.get('cell',{}).get('mode')==mode]
                run_ids={r['id'] for r in attempts}
                calls=[dict(r) for r in ledger.db.execute('SELECT * FROM calls') if r['run_id'] in run_ids]
                queries=[r for r in ledger.records('tool_discovery') if r['run_id'] in run_ids]
                undocumented=[r for r in ledger.records('tool_call') if r['run_id'] in run_ids
                              and not r['data']['definition_previously_exposed']]
                path=RESULTS/'checkpoints'/str(checkpoint)/f'{arm}.json'
                memory=read_json(path) if path.exists() else {}
                rows.append(dict(zip(fields,[checkpoint,arm,mode,16,sum(r is not None for _,r in cells),len(done),
                    sum(r['success'] for r in done),sum(r is not None and r['status']=='inconclusive' for _,r in cells),
                    sum(r is None for _,r in cells),wins,losses,ties,unmatched,
                    sum(r['estimate'] or 0 for r in calls),len(calls),
                    sum(json.loads(r['data']).get('duration_s',0) for r in attempts),
                    memory.get('entry_count'),memory.get('content_bytes'),len(queries),len(undocumented)])))
    with (RESULTS/'comparison.csv').open('w') as f:
        writer=csv.DictWriter(f,fields);writer.writeheader();writer.writerows(rows)
    lines=['# MC02 memory growth comparison','',
        f"Coverage: {audit['conclusive_cells']}/448 conclusive, {audit['inconclusive_cells']} inconclusive, "
        f"{audit['missing_cells']} missing. Accounting accepted: {audit['accepted']}.",'',
        'Complete-policy differences include native learning trajectories and declared extra learning. '
        'This is not a reproduction of paper scores. No overall improvement follows from incomplete coverage.','',
        '| Practice tasks | Policy | Mode | Success/conclusive | Planned | W/L/T | Unknown / missing |',
        '| --- | --- | --- | --- | --- | --- | --- |']
    for r in rows:
        lines.append(f"| {r['checkpoint']} | {r['arm']} | {r['mode']} | {r['successes']}/{r['conclusive']} | 16 | "
                     f"{r['wins']}/{r['losses']}/{r['ties']} | {r['inconclusive']} / {r['missing']} |")
    lines+=['','## Learning and operational expense','',
            '| Phase | SDK requests | Known estimate USD | Unknown-cost requests |','| --- | --- | --- | --- |']
    for phase,n,cost,unknown in ledger.db.execute('SELECT phase,count(*),sum(estimate),sum(estimate IS NULL) FROM calls GROUP BY phase'):
        lines.append(f'| {phase} | {n} | {cost or 0:.6f} | {unknown} |')
    lines+=['','## Mechanisms and evidence','']
    for kind in ['memory_event','consolidation','consolidation_review','reachability','selection','tool_discovery','tool_call']:
        count=ledger.db.execute('SELECT count(*) FROM records WHERE kind=?',(kind,)).fetchone()[0]
        lines.append(f'- {kind}: {count} recorded events. Counts alone do not establish usefulness.')
    reviews={}
    for r in ledger.records('consolidation_review'):
        key=(r['arm'],r['data']['checkpoint'],r['data']['review']['assessment'])
        reviews[key]=reviews.get(key,0)+1
    lines+=['','Source-bound reviewer assessments (not ground truth):','']
    for (arm,cp,label),count in sorted(reviews.items()):lines.append(f'- {arm}, checkpoint {cp}: {label} = {count}.')
    lines+=['','## Limits and interpretation','',
        'One learning stream and one construction per policy. Model aliases, cloud scheduling, host load, '
        'execution order and instrumentation affect estimates. Requests are serial; no isolated inference-time claim. '
        'Failures remain failures; watchdogs and truncated outputs are inconclusive, and all attempts incur expense.',
        '', 'Reachability uses conservative operation-input ancestry and can overstate semantic relevance. '
        'Whole-artifact exposure is not selective retrieval. A discovered definition is not proof it was useful. '
        'The channel comparisons isolate direct memory exposure to execution or discovery, not all indirect influence '
        'through earlier actions. Consolidation reviews are fallible and do not establish causal superiority.',
        '', 'Official grading occurs after completion, independently of the agent. Evaluation feedback never updates memory. '
        'Native tool calls remain available without catalogue exposure, and their use is recorded.',
        '', 'The primary CSV includes all-attempt evaluation costs. The ledger retains individual actions, requests, '
        'exposure, consolidated versions, source evidence and official grades. Actual invoice remains unknown.']
    (RESULTS/'REPORT.md').write_text('\n'.join(lines)+'\n')
    return audit


def bundle(ledger):
    ledger.db.execute('PRAGMA wal_checkpoint(FULL)')
    snapshot=RESULTS/'ledger-snapshot.sqlite'
    with sqlite3.connect(snapshot) as target:ledger.db.backup(target)
    members={}
    output=RESULTS/'evidence.tar.gz'
    with tarfile.open(output,'w:gz') as tar:
        paths=[p for p in RESULTS.rglob('*') if p.is_file() and p.name not in {
            'evidence.tar.gz','evidence-manifest.json','ledger.sqlite','ledger.sqlite-wal','ledger.sqlite-shm','.lock'}]
        from .runtime import settings
        validator=ROOT/settings().structural_validator['path']
        paths+=list((ROOT/'growth').rglob('*.py'))+[ROOT/'growth-protocol.json',ROOT/'requirements.lock',
                                                validator,validator.parent/'license.txt']
        for path in paths:
            name=str(path.relative_to(ROOT));members[name]=digest(path.read_bytes());tar.add(path,arcname=name)
        for row in ledger.db.execute('SELECT id,data FROM runs'):
            directory=WORLD/'experiments/outputs/MC02'/row['id']
            if directory.exists():
                for path in directory.rglob('*'):
                    if path.is_file():
                        name='native/'+str(path.relative_to(WORLD/'experiments/outputs/MC02'))
                        members[name]=digest(path.read_bytes());tar.add(path,arcname=name)
        encoded=(json.dumps(members,sort_keys=True,indent=2)+'\n').encode()
        info=tarfile.TarInfo('evidence-manifest.json');info.size=len(encoded);tar.addfile(info,io.BytesIO(encoded))
    write_json(RESULTS/'evidence-manifest.json',{'members':members,'archive_sha256':digest(output.read_bytes())})
    snapshot.unlink()
