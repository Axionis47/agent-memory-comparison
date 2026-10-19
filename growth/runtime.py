from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from pydantic import BaseModel, ConfigDict

from mc import core
from mc.core import Inconclusive, digest, dumps, read_json, write_json, now

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / 'results' / 'growth-v3'
PROTOCOL = ROOT / 'growth-protocol.json'
ARMS = ['baseline', 'mem0', 'ace', 'trace2skill', 'gepa', 'recmem']


def settings():
    return SimpleNamespace(**read_json(PROTOCOL))


def bind():
    """Explicit per-process applicability handoff, without editing pilot source."""
    from mc import provider, memory
    core.protocol = provider.protocol = memory.protocol = settings
    memory.RESULTS = RESULTS


class Cell(BaseModel):
    model_config = ConfigDict(extra='forbid')
    arm: str
    phase: str
    task_id: str
    checkpoint: int = 0
    repetition: int = 0
    mode: str = 'full'
    sequence: int = 0
    candidate: str = ''

    @property
    def key(self):
        return '-'.join(map(str, [self.phase, self.arm, self.checkpoint, self.task_id,
                                 self.repetition, self.mode, self.sequence, self.candidate]))


class Ledger(core.Ledger):
    def __init__(self):
        super().__init__(RESULTS / 'ledger.sqlite')

    def reserve(self, ident, scope, kind, amount, data):
        total=sum(spend_breakdown(self.db).values())
        if total+amount>settings().estimated_cost_guard_usd:
            raise Inconclusive('Project-wide operational estimated-cost guard reached; remaining work is inconclusive')
        # The old provider reserves before dispatch. Keep cohort/prompt identity on
        # all requests, including calls whose provider result is unavailable.
        data = {**data, 'cohort': 'MC02-growth-v3', 'protocol_hash': digest(PROTOCOL.read_bytes())}
        return super().reserve(ident, scope, kind, amount, data)


def spend_breakdown(current=None):
    """One operational allowance covers the pilot and every retained growth cohort."""
    paths=[ROOT/'results/ledger.sqlite',*sorted((ROOT/'results').glob('growth-v*/ledger.sqlite'))]
    out={}
    for path in paths:
        if path==RESULTS/'ledger.sqlite' and current is not None:
            db=current;close=False
        else:
            db=sqlite3.connect(f'file:{path}?mode=ro',uri=True);close=True
        try:
            out[str(path.relative_to(ROOT))]=db.execute(
                'SELECT coalesce(sum(coalesce(estimate,reservation)),0) FROM calls').fetchone()[0]
        finally:
            if close:db.close()
    return out


def old_ledger():
    return sqlite3.connect(f'file:{ROOT / "results/ledger.sqlite"}?mode=ro', uri=True)


def population():
    return read_json(RESULTS / 'population.json')


def select_population():
    p = settings()
    with old_ledger() as db:
        seen = {r[0].split('_')[0] for r in db.execute('SELECT DISTINCT task_id FROM runs')}
    for path in sorted((ROOT/'results').glob('growth-v*/ledger.sqlite')):
        if path.parent==RESULTS:continue
        with sqlite3.connect(f'file:{path}?mode=ro',uri=True) as db:
            seen.update(r[0].split('_')[0] for r in db.execute('SELECT DISTINCT task_id FROM runs'))
    data = core.WORLD / 'data'
    def rank(x):
        return digest(p.seed + ':' + x)
    def groups(split):
        out = {}
        for ident in (data / 'datasets' / f'{split}.txt').read_text().splitlines():
            if ident.split('_')[0] not in seen:
                out.setdefault(ident.split('_')[0], []).append(ident)
        return {g: sorted(ids, key=rank) for g, ids in out.items()}
    def category(ids):
        public = ' '.join(read_json(data/'tasks'/i/'specs.json')['instruction'] for i in ids).lower()
        return 'spotify' if 'spotify' in public else 'venmo' if 'venmo' in public else 'other'
    train, dev = groups('train'), groups('dev')
    music = sorted([g for g,v in train.items() if category(v)=='spotify'], key=rank)[:6]
    other = sorted([g for g,v in train.items() if category(v)!='spotify'], key=rank)[:6]
    if len(music)!=6 or len(other)!=6:
        raise Inconclusive('Insufficient fresh training groups for frozen strata')
    ordered = [x for pair in zip(music, other) for x in pair]
    practice = [train[g][variant] for variant in range(2) for g in ordered]
    selection_groups = []
    for cat in ['spotify','venmo','other']:
        eligible = sorted([g for g,v in dev.items() if category(v)==cat], key=rank)
        if not eligible:
            raise Inconclusive('Insufficient fresh development strata')
        selection_groups.append(eligible[0])
    evaluation_groups = sorted(set(dev)-set(selection_groups), key=rank)
    if len(evaluation_groups)!=8:
        raise Inconclusive('Fresh development population differs from planned eight groups')
    return {'seed':p.seed, 'excluded_scenario_groups':sorted(seen), 'practice':practice,
            'selection_train':[dev[g][0] for g in selection_groups],
            'selection_validation':[dev[g][1] for g in selection_groups],
            'evaluation':[dev[g][0] for g in evaluation_groups],
            'smoke':['34d9492_1','2a163ab_1'],
            'source_revision':read_json(ROOT/'results/freeze.json').get('sources',{}),
            'classification':'not-a-model'}


def evaluation_cells(checkpoint):
    out=[]
    for repetition in range(2):
        for index, task in enumerate(population()['evaluation']):
            offset=(repetition+index+checkpoint//6)%len(ARMS)
            for arm in ARMS[offset:]+ARMS[:offset]:
                out.append(Cell(arm=arm,phase='evaluation',task_id=task,
                                checkpoint=checkpoint,repetition=repetition))
    if checkpoint==24:
        for mode in ['execution_off','discovery_off']:
            for repetition in range(2):
                for index, task in enumerate(population()['evaluation']):
                    arms=ARMS[1:];offset=(index+repetition)%len(arms)
                    for arm in arms[offset:]+arms[:offset]:
                        out.append(Cell(arm=arm,phase='evaluation',task_id=task,checkpoint=24,
                                        repetition=repetition,mode=mode))
    return out


def source_identity():
    paths=[PROTOCOL, ROOT/'requirements.lock', ROOT/'EXPERIMENT.md']
    validator=ROOT/settings().structural_validator['path']
    if digest(validator.read_bytes())!=settings().structural_validator['sha256']:
        raise Inconclusive('Pinned skill structural validator changed')
    paths.append(validator)
    paths+=sorted((ROOT/'growth').rglob('*.py'))
    paths+=sorted((ROOT/'mc').glob('*.py'))
    return {str(p.relative_to(ROOT)):digest(p.read_bytes()) for p in paths}


def secrets_from(value):
    """Find authentication values in actual observations, never task answers."""
    values=set()
    def visit(x):
        if isinstance(x,dict):
            for key,val in x.items():
                if key in {'password','access_token','refresh_token','authorization'} and isinstance(val,str) and val not in {'string','[AUTH REDACTED]',''}:
                    values.add(val)
                visit(val)
        elif isinstance(x,list):
            for v in x: visit(v)
        elif isinstance(x,str):
            try: visit(json.loads(x))
            except (ValueError,TypeError): pass
            values.update(re.findall(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+',x))
    visit(value)
    return values


def redact(value, secrets):
    if isinstance(value,dict):
        return {k:('[AUTH REDACTED]' if k.lower() in {'password','access_token','refresh_token','authorization'}
                    else redact(v,secrets)) for k,v in value.items()}
    if isinstance(value,list): return [redact(v,secrets) for v in value]
    if isinstance(value,str):
        for secret in sorted(secrets,key=len,reverse=True):
            if secret: value=value.replace(secret,'[AUTH REDACTED]')
        return value
    return value


def experience(run, ledger):
    data=json.loads(run['data'])
    if run['status']!='conclusive':
        raise Inconclusive('Only conclusive practice experience may advance learning')
    grade=data['grade']
    feedback={'success':grade['success'],
              'passed_requirements':[x['requirement'] for x in grade['passes']],
              'failed_requirements':[x['requirement'] for x in grade['failures']]}
    result={'run_id':run['id'],'task_id':run['task_id'],'instruction':data['instruction'],
            'application_datetime':data['task_datetime'],
            'time_basis':'AppWorld simulated local time; host timestamps remain in the raw ledger',
            'steps':[{**s,'application_datetime':data['task_datetime']} for s in data['steps']],
            'answer':data.get('completion_answer'), 'feedback':feedback,
            'exposed_ids':data.get('exposed_memory_ids',[])}
    return redact(result,secrets_from(result)|set(data.get('authentication_values',[])))


def experience_units(exp):
    common={'source_run':exp['run_id'],'application_datetime':exp['application_datetime']}
    yield {**common,'kind':'task_start','task_id':exp['task_id'],'instruction':exp['instruction']}
    for step in exp['steps']:
        yield {**common,'kind':'action_observation',**step}
    yield {**common,'kind':'task_feedback','feedback':exp['feedback']}


def flatten(state):
    if 'layers' in state:
        return [{'id':str(x['id']),'content':x['payload'].get('text',''), 'layer':layer}
                for layer,entries in state['layers'].items() for x in entries]
    if state.get('files'):
        return [{'id':key,'content':value} for key,value in state['files'].items()]
    if state.get('entries'):
        return [{'id':str(x['id']),'content':x.get('memory',x.get('content',''))}
                for x in state['entries']]
    return []


def change_set(before, after):
    a={x['id']:x for x in flatten(before)}; b={x['id']:x for x in flatten(after)}
    return {'added':[b[i] for i in b.keys()-a.keys()],
            'removed':[a[i] for i in a.keys()-b.keys()],
            'updated':[{'before':a[i],'after':b[i]} for i in a.keys()&b.keys() if a[i]!=b[i]]}


def mark(ledger, kind, data, arm=None, phase=None, run_id=None):
    return ledger.record(kind,{'classification':'not-a-model',**data},run_id,arm,phase)
