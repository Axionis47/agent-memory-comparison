from __future__ import annotations

import argparse
import importlib.metadata
import json
import subprocess
import sys
import uuid
from pathlib import Path

from .core import (CACHE, WORLD, ROOT, RESULTS, VENDOR, Cell, Inconclusive, Ledger,
                   choose_population, digest, dumps, evaluation_cells, protocol,
                   read_json, serial_lock, tree_identity, write_json, monotonic)


def identity():
    code = {str(p.relative_to(ROOT)):digest(p.read_bytes()) for p in sorted((ROOT/'mc').glob('*.py'))}
    for name in ['protocol.json', 'requirements.lock', 'EXPERIMENT.md']:
        p=ROOT/name
        if p.exists(): code[name]=digest(p.read_bytes())
    packages = {d.metadata['Name']:d.version for d in importlib.metadata.distributions()}
    sources = {}
    for name in ['appworld','ace','trace2skill','recmem']:
        path=VENDOR/name
        sources[name]={'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=path,text=True).strip()}
    agent=VENDOR/'appworld/experiments/code/simplified/agent.py'
    sources['appworld']['injected_agent_hash']=digest(agent.read_bytes())
    return {'code':code,'packages':packages,'sources':sources,'protocol':protocol().model_dump()}


def prepare(ledger):
    from appworld import load_task_ids
    from appworld.task import task_id_to_generator_id
    pop=choose_population(load_task_ids('train'),load_task_ids('dev'),task_id_to_generator_id)
    path=CACHE/'population.json'
    if path.exists() and read_json(path)!=pop:
        raise ValueError('Existing population differs; refuse replacement')
    write_json(path,pop)
    inputs={task:tree_identity(WORLD/'data/tasks'/task)
            for ids in pop.values() for task in ids}
    manifest={'population':pop,'inputs':inputs,'identity':identity()}
    write_json(CACHE/'preparation.json',manifest)
    ledger.record('preparation',manifest)
    print(dumps(pop),flush=True)


def require_smoke():
    p=RESULTS/'smoke.json'
    if not p.exists() or not read_json(p)['accepted']:
        raise Inconclusive('Baseline/ACE integration smoke is not accepted')


def smoke(vertex):
    from .memory import MemoryPolicy
    from .agent import solve
    pop=read_json(CACHE/'population.json')
    base=MemoryPolicy('baseline',vertex,'smoke-baseline')
    first=solve(Cell(arm='baseline',phase='smoke',task_id=pop['smoke'][0]),base,vertex)
    if first['status']!='conclusive':
        raise Inconclusive('Baseline smoke did not reach an official grade')
    data=json.loads(first['data'])
    corpus=[{'run_id':first['id'],'instruction':data['instruction'],'steps':data['steps'],
             'feedback':data['grade'],'task_id':first['task_id']}]
    ace=MemoryPolicy('ace',vertex,'smoke-ace')
    if not ace.path.exists():
        with vertex.scoped(phase='smoke',arm='ace',run_id=None):
            ace.learn(corpus)
    if not ace.state.get('entries'):
        raise Inconclusive('ACE produced no actual playbook entry in smoke')
    ace.freeze()
    second=solve(Cell(arm='ace',phase='smoke',task_id=pop['smoke'][1]),ace,vertex)
    exposures=vertex.ledger.records('exposure',second['id'])
    accepted=second['status']=='conclusive' and any(r['data']['items'] for r in exposures)
    write_json(RESULTS/'smoke.json',{'accepted':accepted,'baseline_run':first['id'],
               'ace_run':second['id'],'ace_version':ace.version,'exposure_count':len(exposures)})
    ace.close()
    if not accepted:
        raise Inconclusive('ACE smoke did not establish graded execution with actual memory exposure')


def train(vertex):
    require_smoke()
    from .memory import MemoryPolicy
    from .agent import solve,experiences
    base=MemoryPolicy('baseline',vertex)
    for task in read_json(CACHE/'population.json')['train']:
        result=solve(Cell(arm='baseline',phase='train',task_id=task),base,vertex)
        if result['status']!='conclusive':
            raise Inconclusive('Shared training trajectory inconclusive; stop live collection')
    corpus=experiences(vertex.ledger)
    write_json(RESULTS/'corpus.json',{'sha256':digest(corpus),'experiences':corpus})


def learn(vertex,only=None):
    require_smoke()
    from .memory import MemoryPolicy
    from .agent import solve,experiences
    corpus=experiences(vertex.ledger)
    for arm in ([only] if only else protocol().arms):
        mem=MemoryPolicy(arm,vertex)
        if mem.path.exists():
            receipts=[r['data'] for r in vertex.ledger.records('construction_complete') if r['arm']==arm]
            if not any(r['version']==mem.version and r['corpus_hash']==digest(corpus) for r in receipts):
                raise Inconclusive(f'{arm} artifact lacks a matching completed construction receipt')
            print(f'{arm}: existing artifact retained',flush=True)
            mem.close()
            continue
        def selection(task,instruction):
            candidate=MemoryPolicy('gepa',vertex,'gepa-candidate')
            candidate.state={'arm':'gepa','text':instruction,'entries':[]}
            n=vertex.ledger.db.execute("SELECT count(*) FROM runs WHERE phase='selection'").fetchone()[0]
            return solve(Cell(arm='gepa',phase='selection',task_id=task,repetition=n),candidate,vertex)
        print(f'Constructing {arm} from {len(corpus)} shared trajectories',flush=True)
        started=monotonic()
        start_calls=vertex.ledger.db.execute('SELECT count(*) FROM calls').fetchone()[0]
        try:
            with vertex.scoped(arm=arm,phase='learning',run_id=None):
                with vertex.tracer.start_as_current_span('memory.learn',attributes={'arm':arm}):
                    mem.learn(corpus,selection)
            errors=vertex.ledger.db.execute("SELECT count(*) FROM calls WHERE status!='live' AND rowid>?",
                                             (start_calls,)).fetchone()[0]
            if errors:
                raise Inconclusive('Constructor concealed a supporting model request failure')
            vertex.ledger.record('construction_complete',{'arm':arm,'corpus_hash':digest(corpus),
                                  'version':mem.version,'duration_s':monotonic()-started},arm=arm,phase='learning')
        except Exception as exc:
            vertex.ledger.record('construction_error',{'arm':arm,'type':type(exc).__name__,
                                  'message':str(exc)[:1500]},arm=arm,phase='learning')
            raise
        finally:
            mem.close()


def freeze(vertex):
    from .memory import MemoryPolicy
    require_smoke()
    checks=read_json(RESULTS/'software-checks.json')
    if not checks['passed'] or checks['code_hash']!=digest(identity()['code']):
        raise Inconclusive('Current software checks must pass before freezing')
    frozen={}
    for arm in protocol().arms:
        mem=MemoryPolicy(arm,vertex)
        receipts=[r['data'] for r in vertex.ledger.records('construction_complete') if r['arm']==arm]
        if not any(r['version']==mem.version for r in receipts):
            raise Inconclusive(f'{arm} construction has not completed')
        try: frozen[arm]=mem.freeze()
        finally: mem.close()
    preparation=read_json(CACHE/'preparation.json')
    for task,expected in preparation['inputs'].items():
        if tree_identity(WORLD/'data/tasks'/task)!=expected:
            raise Inconclusive(f'Upstream input changed: {task}')
    versions=[json.loads(r['data']).get('resolved_model') for r in vertex.ledger.db.execute(
        "SELECT data FROM calls WHERE kind='generation' AND status='live' ORDER BY started")]
    manifest={'identity':identity(),'population':read_json(CACHE/'population.json'),'memories':frozen,
              'inputs':preparation['inputs'],'resolved_model':versions[-1] if versions else None}
    manifest['hash']=digest(manifest)
    path=RESULTS/'freeze.json'
    if path.exists() and read_json(path)!=manifest:
        raise ValueError('Frozen comparison cannot be replaced')
    write_json(path,manifest)
    vertex.ledger.record('freeze',manifest)


def rebuild_index(vertex):
    from .memory import MemoryPolicy
    if (RESULTS/'freeze.json').exists():
        raise Inconclusive('Index recovery is only permitted before evaluation freeze')
    mem=MemoryPolicy('mem0',vertex)
    native=mem._mem0()
    try:
        existing={x['id']:x for x in mem.export()['entries']}
        for n,entry in enumerate(mem.state['entries']):
            if entry['id'] in existing:
                if existing[entry['id']]!=entry:
                    raise Inconclusive('Existing recovered fact differs from canonical artifact')
                continue
            with vertex.scoped(phase='learning',arm='mem0',run_id=None,
                               recovery='derived-vector-index',memory_id=entry['id']):
                vector=vertex.embed([entry['memory']])[0]
            payload={**entry.get('metadata',{}),'data':entry['memory'],
                **{k:entry[k] for k in ['hash','created_at','updated_at','user_id','agent_id','run_id'] if k in entry}}
            native.vector_store.insert(vectors=[vector],ids=[entry['id']],payloads=[payload])
            vertex.ledger.record('index_rebuild_point',{'memory_id':entry['id'],
                'artifact_version':mem.version,'vector_hash':digest(vector)},arm='mem0',phase='learning')
            if (n+1)%25==0: print(f'Index recovery {n+1}/{len(mem.state["entries"])}',flush=True)
        if mem.export()!=mem.state:
            raise Inconclusive('Recovered index does not reproduce canonical facts')
        vertex.ledger.record('index_recovery_complete',{'version':mem.version,
            'entries':len(mem.state['entries']),'classification':'not-a-model'},arm='mem0',phase='learning')
        print('Mem0 index rebuilt from unchanged saved facts using fresh embeddings.',flush=True)
    finally: mem.close()


def evaluate(vertex):
    from .memory import MemoryPolicy
    from .agent import solve
    frozen=read_json(RESULTS/'freeze.json')
    if identity()!=frozen['identity']:
        raise Inconclusive('Code, dependency or protocol changed after freeze')
    for task,expected in frozen['inputs'].items():
        if tree_identity(WORLD/'data/tasks'/task)!=expected:
            raise Inconclusive(f'Frozen upstream input changed: {task}')
    vertex.expected_resolved_model=frozen['resolved_model']
    for cell in evaluation_cells(frozen['population']):
        mem=MemoryPolicy(cell.arm,vertex)
        try:
            if mem.version!=frozen['memories'][cell.arm]['version'] or mem.export()!=mem.state:
                raise Inconclusive('Frozen memory identity mismatch')
            result=solve(cell,mem,vertex)
            if result['status']!='conclusive':
                raise Inconclusive('Evaluation interrupted; no provider or behavioral fallback')
        finally: mem.close()


def main():
    parser=argparse.ArgumentParser(description='MC01: actual AppWorld agent, interchangeable memories')
    parser.add_argument('command',choices=['prepare','check','readiness','smoke','train','learn','rebuild-index','freeze','evaluate','audit','report','bundle'])
    parser.add_argument('--arm',choices=protocol().arms)
    args=parser.parse_args()
    ledger=Ledger()
    with serial_lock():
        try:
            if args.command=='audit':
                from .audit import audit
                return audit(ledger)
            if args.command=='prepare': return prepare(ledger)
            if args.command=='check':
                import xml.etree.ElementTree as ET
                result=subprocess.run([sys.executable,'-m','pytest','tests','-q','--junitxml=.cache/software.xml'],cwd=ROOT)
                suites=ET.parse(CACHE/'software.xml').getroot()
                totals={key:sum(int(s.get(key,'0')) for s in suites.iter('testsuite'))
                        for key in ['tests','failures','errors','skipped']}
                write_json(RESULTS/'software-checks.json',{'passed':result.returncode==0,'exit_code':result.returncode,
                    'classification':'not-a-model','command':'python -m pytest tests -q',
                    'counts':totals,'code_hash':digest(identity()['code'])})
                if result.returncode: raise RuntimeError('Software checks failed')
                return
            if args.command in ['report','bundle']:
                from .report import report,bundle
                report(ledger)
                if args.command=='bundle': bundle(ledger)
                return
            from .provider import Vertex
            vertex=Vertex(ledger)
            if args.command=='readiness':
                r=vertex.text('Return {"ready":true}',json_mode=True,purpose='excluded-readiness')
                assert json.loads(r)['ready'] is True
                assert len(vertex.embed(['API documentation and application actions'])[0])==protocol().embedding_dimension
                ledger.record('readiness',{'accepted':True,'model':protocol().model})
                print('Fresh Vertex generation and embedding readiness accepted.',flush=True)
            elif args.command=='smoke': smoke(vertex)
            elif args.command=='train': train(vertex)
            elif args.command=='learn': learn(vertex,args.arm)
            elif args.command=='rebuild-index': rebuild_index(vertex)
            elif args.command=='freeze': freeze(vertex)
            elif args.command=='evaluate': evaluate(vertex)
        except Exception as exc:
            ledger.record('command_error',{'command':args.command,'type':type(exc).__name__,'error':str(exc)[:1500]})
            print(f'{args.command} stopped: {type(exc).__name__}: {exc}',file=sys.stderr,flush=True)
            raise


if __name__=='__main__': main()
