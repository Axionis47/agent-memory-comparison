from __future__ import annotations

import argparse
import importlib.metadata
import json
import subprocess
import sys
from pathlib import Path

from mc.core import Inconclusive, digest, read_json, write_json, serial_lock, WORLD
from .runtime import (ROOT, RESULTS, PROTOCOL, ARMS, Cell, Ledger, bind, settings, population,
                      select_population, source_identity, experience, evaluation_cells, mark)


def prepare(ledger):
    path=RESULTS/'population.json'
    if path.exists(): return
    selected=select_population()
    write_json(path,selected)
    # Hash public task inputs without loading reference solutions or evaluation code.
    task_ids=selected['practice']+selected['selection_train']+selected['selection_validation']+selected['evaluation']
    inputs={i:digest((WORLD/'data/tasks'/i/'specs.json').read_bytes()) for i in task_ids}
    distributions={d.metadata['Name']:d.version for d in importlib.metadata.distributions() if d.metadata['Name']}
    original={str(p.relative_to(ROOT)):digest(p.read_bytes()) for p in
              [*sorted((ROOT/'mc').glob('*.py')), ROOT/'protocol.json',ROOT/'results/freeze.json',
               ROOT/'results/REPORT.md',ROOT/'results/comparison.csv']}
    mark(ledger,'preparation',{'population':selected,'inputs':inputs,'distributions':distributions,
         'pilot_preserved_hashes':original,'protocol':read_json(PROTOCOL),
         'applicability_handoff':{'source':'MC01 pinned runtime and measured SDK/ledger/grading utilities',
             'accepted_boundary':'actual final-state verification and serial live provider accounting',
             'excluded':'all MC01 trajectories, memories, outcomes and reference answers'}},phase='preparation')
    print(json.dumps({'practice':selected['practice'],'selection_train':selected['selection_train'],
                      'selection_validation':selected['selection_validation'],'evaluation':selected['evaluation']},indent=2))


def check(ledger):
    xml=RESULTS/'software-checks.xml'
    result=subprocess.run([sys.executable,'-m','pytest','tests','growth/tests','-q',f'--junitxml={xml}'],cwd=ROOT)
    mark(ledger,'software_checks',{'exit_code':result.returncode,'source_identity':source_identity(),
         'xml_hash':digest(xml.read_bytes()) if xml.exists() else None},phase='software')
    if result.returncode:raise Inconclusive('Software checks failed')


def ensure_known_calls(ledger):
    n=ledger.db.execute("SELECT count(*) FROM calls WHERE status IN ('pending','unknown')").fetchone()[0]
    if n:raise Inconclusive(f'{n} unresolved provider requests require reconciliation; no new live dispatch')
    active=ledger.db.execute("SELECT count(*) FROM runs WHERE status='running'").fetchone()[0]
    if active:raise Inconclusive('An interrupted run remains running; reconcile before resuming')


def candidate_solver(vertex, checkpoint, phase='selection'):
    from .memory import Memory
    from .agent import solve
    def run(task,text):
        number=vertex.ledger.db.execute('SELECT count(*) FROM runs WHERE phase=?',(phase,)).fetchone()[0]
        memory=Memory('gepa',vertex,namespace=f'{phase}-candidate')
        memory.state={'arm':'gepa','text':text,'entries':[{'id':'strategy','content':text}] if text else []}
        try:return solve(Cell(arm='gepa',phase=phase,task_id=task,checkpoint=checkpoint,
                              sequence=number,candidate=digest(text)),memory,vertex)
        finally:memory.close()
    return run


def require_conclusive(run):
    if run['status']!='conclusive':
        error=json.loads(run['data']).get('error','unknown boundary')
        raise Inconclusive(f'Acting run is inconclusive: {run["id"]}: {error}')


def smoke(ledger,vertex):
    from .memory import Memory
    from .agent import solve
    if ledger.records('smoke_gate'):
        print('Existing smoke gate retained; use a new cohort for changed smoke protocol.')
        return
    ensure_known_calls(ledger)
    signature=digest(source_identity())[:12]
    for arm in ARMS:
        memory=Memory(arm,vertex,namespace=f'smoke-{arm}-{signature}')
        corpus=[]
        try:
            for sequence,task in enumerate(population()['smoke'],1):
                run=solve(Cell(arm=arm,phase='smoke',task_id=task,sequence=sequence,candidate=signature),memory,vertex)
                require_conclusive(run);exp=experience(run,ledger);corpus.append(exp)
                memory.observe(exp,sequence)
            with vertex.scoped(arm=arm,phase='smoke_learning'):
                if arm=='trace2skill':memory.evolve_skill(corpus,2)
                if arm=='gepa':
                    memory.optimize(corpus,2,candidate_solver(vertex,2,'smoke_selection'),
                        selection_population={'selection_train':[population()['smoke'][0]],
                                              'selection_validation':[population()['smoke'][1]]},metric_target=8)
            before=memory.export();memory.close();memory.native=None
            if memory.export()!=before:raise Inconclusive('Native smoke memory changed after reopening')
            # An actual subsequent action decision receives the learned memory.
            run=solve(Cell(arm=arm,phase='smoke_exposure',task_id=population()['smoke'][0],sequence=3,candidate=signature),memory,vertex)
            require_conclusive(run)
            mark(ledger,'smoke_policy',{'arm':arm,'version':memory.version,
                 'exposure_run':run['id'],'entries':len(__import__('growth.runtime',fromlist=['flatten']).flatten(before)),
                 'empty_memory_allowed':True},arm,'smoke')
        finally:memory.close()
    mark(ledger,'smoke_gate',{'passed':True,'source_identity':source_identity(),
         'note':'Actual actions, official grades, native learning paths, persistence and subsequent exposure; '
                'no task success or native mutation manufactured'},phase='smoke')


def freeze(ledger):
    previous=ledger.records('experiment_freeze')
    if previous:
        verify(ledger);return
    checks=ledger.records('software_checks');gates=ledger.records('smoke_gate')
    if not checks or checks[-1]['data']['exit_code'] or checks[-1]['data']['source_identity']!=source_identity():
        raise Inconclusive('Current software checks must pass before freezing')
    if not gates or gates[-1]['data']['source_identity']!=source_identity():
        raise Inconclusive('Current live integration gate required')
    ensure_known_calls(ledger)
    models={json.loads(r[0]).get('resolved_model') for r in ledger.db.execute(
        "SELECT data FROM calls WHERE kind='generation' AND status='live'")}
    models.discard(None)
    if len(models)!=1:raise Inconclusive('Live reported generation model identity is not unique')
    data={'source_identity':source_identity(),'population_hash':digest(population()),'resolved_model':models.pop(),
          'planned_evaluations':448,'protocol':read_json(PROTOCOL)}
    mark(ledger,'experiment_freeze',data,phase='freeze');write_json(RESULTS/'freeze.json',data)


def verify(ledger):
    freezes=ledger.records('experiment_freeze')
    if not freezes:raise Inconclusive('Freeze the study before practice/evaluation')
    if freezes[-1]['data']['source_identity']!=source_identity():raise Inconclusive('Frozen source changed')
    if freezes[-1]['data']['population_hash']!=digest(population()):raise Inconclusive('Frozen population changed')
    initial=ledger.records('preparation')[0]['data']
    for name,checksum in initial['pilot_preserved_hashes'].items():
        if digest((ROOT/name).read_bytes())!=checksum:raise Inconclusive('Original pilot evidence/source changed')
    for ident,checksum in initial['inputs'].items():
        if digest((WORLD/'data/tasks'/ident/'specs.json').read_bytes())!=checksum:
            raise Inconclusive('Upstream public task input changed')


def run(ledger,vertex,resume=False):
    from .memory import Memory
    from .agent import solve
    from .measure import diagnostics,report
    verify(ledger);ensure_known_calls(ledger)
    vertex.expected_resolved_model=ledger.records('experiment_freeze')[-1]['data']['resolved_model']
    previous=0
    for checkpoint in settings().checkpoints:
        finished=[r for r in ledger.records('checkpoint_complete') if r['data']['checkpoint']==checkpoint]
        if not finished:
            for sequence in range(previous+1,checkpoint+1):
                task=population()['practice'][sequence-1]
                offset=(sequence-1)%len(ARMS)
                for arm in ARMS[offset:]+ARMS[:offset]:
                    memory=Memory(arm,vertex)
                    try:
                        cell=Cell(arm=arm,phase='practice',task_id=task,sequence=sequence)
                        result=solve(cell,memory,vertex);require_conclusive(result)
                        exp=experience(result,ledger);memory.observe(exp,sequence)
                        if arm=='ace':
                            checked=solve(Cell(arm=arm,phase='post_update',task_id=task,sequence=sequence),memory,vertex)
                            require_conclusive(checked)
                        if arm=='trace2skill' and sequence%6==0:
                            corpus=practice_corpus(ledger,arm,sequence-6,sequence)
                            with vertex.scoped(arm=arm,phase='learning',sequence=sequence):memory.evolve_skill(corpus,sequence)
                    finally:memory.close()
            for arm in ARMS:
                memory=Memory(arm,vertex)
                try:
                    if arm=='gepa':
                        with vertex.scoped(arm=arm,phase='learning',checkpoint=checkpoint):
                            memory.optimize(practice_corpus(ledger,arm,0,checkpoint),checkpoint,candidate_solver(vertex,checkpoint))
                    memory.checkpoint(checkpoint)
                finally:memory.close()
            mark(ledger,'checkpoint_complete',{'checkpoint':checkpoint},phase='freeze')
        # Frozen native stores are versioned separately from the mutable practice stores.
        for cell in evaluation_cells(checkpoint):
            prior=ledger.latest(cell)
            if prior and (prior['status']=='conclusive' or not resume):continue
            memory=Memory(cell.arm,vertex,namespace=f'frozen-{checkpoint}-{cell.arm}');memory.read_only=True
            try:
                expected=read_json(RESULTS/'checkpoints'/str(checkpoint)/f'{cell.arm}.json')
                if memory.version!=expected['version'] or memory.export()!=expected['artifact']:
                    raise Inconclusive('Frozen native checkpoint identity differs')
                result=solve(cell,memory,vertex)
                if result['status']!='conclusive':
                    data=json.loads(result['data'])
                    if not any(t in data.get('error','') for t in ['truncated','watchdog']):require_conclusive(result)
                ensure_known_calls(ledger)
            finally:memory.close()
        for arm in ARMS[1:]:
            memory=Memory(arm,vertex,namespace=f'frozen-{checkpoint}-{arm}');memory.read_only=True
            try:diagnostics(memory,checkpoint,vertex)
            finally:memory.close()
        report(ledger)
        previous=checkpoint


def practice_corpus(ledger,arm,start,end):
    out=[]
    for sequence,task in enumerate(population()['practice'][start:end],start+1):
        cell=Cell(arm=arm,phase='practice',task_id=task,sequence=sequence)
        result=ledger.latest(cell)
        if not result:raise Inconclusive('Missing practice trajectory')
        out.append(experience(result,ledger))
    return out


def status(ledger):
    print(json.dumps({'runs':[dict(r) for r in ledger.db.execute(
        'SELECT phase,arm,status,count(*) AS count,sum(success) AS successes FROM runs GROUP BY phase,arm,status')],
        'calls':[dict(r) for r in ledger.db.execute('SELECT phase,status,count(*) AS count,sum(estimate) AS known_usd FROM calls GROUP BY phase,status')],
        'checkpoints':[r['data']['checkpoint'] for r in ledger.records('checkpoint_complete')]},indent=2))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['prepare','check','smoke','freeze','run','status','report','bundle'])
    parser.add_argument('--resume-inconclusive',action='store_true');args=parser.parse_args()
    bind();RESULTS.mkdir(parents=True,exist_ok=True)
    with serial_lock():
        ledger=Ledger()
        try:
            mark(ledger,'command_source',{'command':args.command,'source_identity':source_identity(),
                 'source':{str(p.relative_to(ROOT)):p.read_text() for p in (ROOT/'growth').rglob('*.py')}},phase='operations')
            if args.command=='prepare':prepare(ledger)
            elif args.command=='check':check(ledger)
            elif args.command=='freeze':freeze(ledger)
            elif args.command in {'smoke','run'}:
                from .provider import Vertex
                ensure_known_calls(ledger);vertex=Vertex(ledger)
                if args.command=='smoke':smoke(ledger,vertex)
                else:run(ledger,vertex,args.resume_inconclusive)
            elif args.command=='status':status(ledger)
            elif args.command in {'report','bundle'}:
                from .measure import report,bundle
                print(json.dumps(report(ledger),indent=2))
                if args.command=='bundle':bundle(ledger)
        except Exception as exc:
            mark(ledger,'command_error',{'command':args.command,'type':type(exc).__name__,
                 'message':str(exc)[:2000]},phase='operations')
            print(f'{type(exc).__name__}: {exc}',file=sys.stderr)
            raise
        finally:ledger.db.close()


if __name__=='__main__':main()
