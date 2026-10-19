"""A labelled GEPA retention diagnostic using existing real upstream tasks.

Never changes the frozen comparison, supplies an authored lesson, or changes GEPA
acceptance. Train/validation deliberately overlap: this demonstrates retention
on known cases and cannot establish generalisation or benchmark performance.
Version 3 ranks official completion first and actual API-call count second.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from mc.core import Inconclusive, digest, serial_lock
from growth import runtime
from growth.runtime import Cell, Ledger, bind, mark, source_identity
from growth.agent import solve
from growth.memory import Memory
from growth.provider import Vertex
from growth.__main__ import ensure_known_calls, require_conclusive


TASKS=['6ea6792_2','68ee2c9_2']
SOURCE_RUNS=['a32080bc39e94372be36fb59c8f527af','225743a9256d4bc3afa202b3762e9bd3']
TARGET=32
CHECKPOINT=-3
PHASE='retention_v3_selection'


def source_bound_experience(run, ledger):
    """Redact standalone password observations as well as structured secrets.

    Only the diagnostic process uses this explicit provider/task adaptation.
    The frozen worker and its existing learning copies are never rewritten.
    """
    exp=ORIGINAL_EXPERIENCE(run,ledger)
    raw=json.loads(run['data']);secrets=set(raw.get('authentication_values',[]))
    for step in raw['steps']:
        if re.search(r'print\(\w*password\)', '\n'.join(step['inputs'])):
            for output in step['outputs']:
                value=output.strip()
                if value and '\n' not in value and not value.startswith('Execution '):
                    secrets.add(value)
    exp=runtime.redact(exp,secrets)
    exp['feedback']['observed_api_calls']=raw.get('api_calls')
    exp['feedback']['diagnostic_objective']='Complete the official task correctly, then reduce actual AppWorld API calls.'
    exp['feedback']['diagnostic_metric']='success * (1 + 1 / (2 * (1 + observed_api_calls))); failure remains zero.'
    return exp


ORIGINAL_EXPERIENCE=runtime.experience


def reconcile_closed_timeout(ledger):
    """Keep the old response/cost unknown; never repeat its task action."""
    ident='dbbaf016c40e4be89df919fdb950cfd9'
    unknown=list(ledger.db.execute("SELECT * FROM calls WHERE status IN ('pending','unknown')"))
    if not unknown:
        ensure_known_calls(ledger);return
    if len(unknown)!=1 or unknown[0]['id']!=ident or unknown[0]['status']!='unknown':
        raise Inconclusive('Unexpected unsettled provider request requires separate reconciliation')
    call=unknown[0];packet=json.loads(call['data'])
    run=ledger.db.execute('SELECT * FROM runs WHERE id=?',(call['run_id'],)).fetchone()
    if (packet.get('error_type')!='ReadTimeout' or run['status']!='inconclusive'
            or call['ended'] is None or time.time()-call['ended']<120):
        raise Inconclusive('Prior timeout is not a closed, aged-out inconclusive attempt')
    data=json.loads(run['data'])
    intents=ledger.records('exposure_intent',run['id'])
    intent=next((x['data'] for x in intents if x['data']['request_hash']==packet['request_hash']),None)
    if not intent or any(s['number']>=intent['decision'] for s in data['steps']):
        raise Inconclusive('Cannot establish the action boundary after the timed-out request')
    if ledger.db.execute("SELECT count(*) FROM runs WHERE status='running'").fetchone()[0]:
        raise Inconclusive('Another task attempt remains active')
    mark(ledger,'closed_timeout_disposition',{'call_id':ident,'run_id':run['id'],
         'response':'unknown; not recovered or replayed','cost':'unknown; reservation retained',
         'observed_steps':len(data['steps']),'unexecuted_decision':intent['decision'],
         'recovery':'New isolated diagnostic from a fresh world; prior task attempt is never resumed',
         'transport':'Prior worker exited; exclusive project lock acquired; SDK timeout elapsed',
         'provider':'Availability must be established by the next real diagnostic request; stop on failure'},
         arm='gepa',phase='retention_preparation')


def main():
    bind()
    with serial_lock():
        ledger=Ledger()
        import gepa
        native_optimize=gepa.optimize
        try:
            reconcile_closed_timeout(ledger)
            practice=list(ledger.db.execute('SELECT * FROM runs WHERE arm="gepa" '
                                           'AND phase="practice" AND status="conclusive" ORDER BY started'))
            protocol={'id':'GEPA-retention-diagnostic-v3','tasks':TASKS,
                      'source_runs':SOURCE_RUNS,'train':TASKS,'validation':TASKS,
                      'follow_up':TASKS,'metric_target':TARGET,
                      'objective':'Official task completion first, fewer observed AppWorld API calls second',
                      'metric':'success * (1 + 1 / (N * (1 + actual_api_calls))), N=2; failed task score is 0',
                      'quality_priority':'With at least one API call per completed task, total efficiency bonus is at most 0.5; one additional passed task always outweighs it.',
                      'native_stop':'Accepted nonempty candidate passes both selection tasks and beats seed metric, or actual metric target',
                      'selection':'Same observed Venmo and file cases; pass-only diagnostics retained no update; not held-out evidence',
                      'follow_up_controls':'Each task once with frozen strategy and once with empty strategy; alternate order',
                      'seed_strategy':'','native_acceptance':'unchanged strict improvement',
                      'normalisation':'structured-secret plus standalone password observation redaction',
                      'prior_timeout':'closed unknown response, retained reservation, no old action retry',
                      'practice_source_runs':[row['id'] for row in practice],
                      'configured_source_identity':source_identity(),
                      'diagnostic_source_hash':digest(Path(__file__).read_bytes())}
            key=digest(protocol)
            prior=[r for r in ledger.records('retention_diagnostic_complete') if r['data']['key']==key]
            if prior:
                print(json.dumps(prior[-1]['data'],indent=2));return
            if any(r['data']['key']==key for r in ledger.records('retention_diagnostic_started')):
                raise Inconclusive('Existing partial diagnostic requires reconciliation, not automatic replay')
            sources=[ledger.db.execute('SELECT * FROM runs WHERE id=?',(ident,)).fetchone()
                     for ident in SOURCE_RUNS]
            if any(not row or row['status']!='conclusive' or row['success']!=0 or row['arm']!='gepa'
                   for row in sources):
                raise Inconclusive('Expected actual GEPA source failures are absent')
            mark(ledger,'retention_diagnostic_started',{'key':key,'protocol':protocol,
                 'source':Path(__file__).read_text()},arm='gepa',phase='retention_preparation')
            runtime.experience=source_bound_experience
            def diagnostic_optimize(**kwargs):
                adapter=kwargs['adapter'];evaluate=adapter.evaluate
                def measured_evaluate(batch,candidate,capture_traces=False):
                    result=evaluate(batch,candidate,capture_traces)
                    scores=[]
                    for ident in result.outputs:
                        run=ledger.db.execute('SELECT * FROM runs WHERE id=?',(ident,)).fetchone()
                        data=json.loads(run['data']);count=data['api_calls']
                        if not isinstance(count,int) or count<1:
                            raise Inconclusive('Completed task lacks actual API-call accounting')
                        score=float(run['success'])*(1+1/(len(TASKS)*(1+count)))
                        scores.append(score)
                        mark(ledger,'retention_metric',{'run_id':ident,'official_success':bool(run['success']),
                             'actual_api_calls':count,'metric_score':score,'formula':protocol['metric'],
                             'native_binary_event':'gepa_candidate_evaluation retains official binary outcomes; this record is the metric supplied to GEPA'},
                             arm='gepa',phase='retention_learning')
                    result.scores=scores
                    return result
                adapter.evaluate=measured_evaluate
                def completed_improvement(state):
                    seed=state.program_full_scores_val_set[0]
                    return any(index>0 and state.program_candidates[index]['strategy'] and
                               len(scores)==len(TASKS) and all(v>1 for v in scores.values()) and
                               sum(scores.values())/len(scores)>seed
                               for index,scores in enumerate(state.prog_candidate_val_subscores))
                return native_optimize(**kwargs,stop_callbacks=[completed_improvement],perfect_score=2.0)
            gepa.optimize=diagnostic_optimize
            vertex=Vertex(ledger)
            namespace='retention-diagnostic-'+key[:12]
            memory=Memory('gepa',vertex,namespace=namespace)
            if memory.state.get('text'):
                raise Inconclusive('Diagnostic must start with an actually empty native seed')
            unique_sources={row['id']:row for row in [*practice,*sources]}
            corpus=[source_bound_experience(dict(row),ledger) for row in unique_sources.values()]
            def candidate(task,text):
                number=ledger.db.execute('SELECT count(*) FROM runs WHERE phase=?',(PHASE,)).fetchone()[0]
                selected=Memory('gepa',vertex,namespace=namespace+'-candidate')
                selected.state={'arm':'gepa','text':text,
                                'entries':[{'id':'strategy','content':text}] if text else []}
                try:
                    result=solve(Cell(arm='gepa',phase=PHASE,task_id=task,
                                 checkpoint=CHECKPOINT,sequence=number,candidate=digest(text)),selected,vertex)
                    require_conclusive(result)
                    return result
                finally:selected.close()
            try:
                with vertex.scoped(arm='gepa',phase='retention_learning',diagnostic_key=key):
                    memory.optimize(corpus,CHECKPOINT,candidate,
                                    selection_population={'selection_train':TASKS,
                                                          'selection_validation':TASKS},metric_target=TARGET)
                artifact=memory.export();text=artifact.get('text','')
                memory.close();reopened=Memory('gepa',vertex,namespace=namespace)
                try:
                    if reopened.export()!=artifact:
                        raise Inconclusive('Native retained strategy changed after reopening')
                    checkpoint=reopened.checkpoint(CHECKPOINT)
                    reopened.read_only=True
                    follow_ups=[];controls=[]
                    if text:
                        for sequence,task in enumerate(protocol['follow_up'],1):
                            order=['memory','control'] if sequence%2 else ['control','memory']
                            for channel in order:
                                if channel=='memory':
                                    result=solve(Cell(arm='gepa',phase='retention_exposure',task_id=task,
                                                     checkpoint=CHECKPOINT,sequence=sequence,candidate=digest(text)),reopened,vertex)
                                    require_conclusive(result);follow_ups.append(result)
                                else:
                                    empty=Memory('gepa',vertex,namespace=namespace+'-empty-control')
                                    empty.read_only=True
                                    try:
                                        result=solve(Cell(arm='gepa',phase='retention_v3_control',task_id=task,
                                                         checkpoint=CHECKPOINT,sequence=sequence,candidate=digest('')),empty,vertex)
                                        require_conclusive(result);controls.append(result)
                                    finally:empty.close()
                    mark(ledger,'retention_diagnostic_complete',{'key':key,'protocol':protocol,
                         'retained':bool(text),'instruction':text,'memory_version':checkpoint['version'],
                         'follow_up_runs':[r['id'] for r in follow_ups],
                         'follow_up_outcomes':[bool(r['success']) for r in follow_ups],
                         'control_runs':[r['id'] for r in controls],
                         'control_outcomes':[bool(r['success']) for r in controls],
                         'scope':'known-case retention demonstration; train equals validation; not generalisation'},
                         arm='gepa',phase='retention_reporting')
                    print(json.dumps({'retained':bool(text),'follow_up_outcomes':
                                      [bool(r['success']) for r in follow_ups]},indent=2))
                finally:reopened.close()
            finally:memory.close()
        finally:
            gepa.optimize=native_optimize
            runtime.experience=ORIGINAL_EXPERIENCE
            ledger.db.close()


if __name__=='__main__':main()
