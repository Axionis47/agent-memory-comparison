"""Independent postprocessing for MC02. Never dispatches or replays a model call."""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import subprocess
import importlib.metadata
import sqlite3
import csv
from pathlib import Path

from mc.core import digest, dumps, read_json, write_json, serial_lock, tree_identity, WORLD
from growth.runtime import ROOT, RESULTS, ARMS, Ledger, bind, source_identity, evaluation_cells, mark, population, experience
from growth.measure import report, bundle


def protected():
    from concurrent.futures import ThreadPoolExecutor
    baseline=Path(os.environ['MC_PROTECTED_BASELINE'])
    expected=read_json(baseline)
    items=[(n,v) for entries in expected.values() for n,v in entries.items()]
    def compare(item):
        name,metadata=item;path=ROOT.parent/name
        if 'symlink' in metadata:
            return None if path.is_symlink() and os.readlink(path)==metadata['symlink'] else name
        if not path.is_file():return name
        with path.open('rb') as f:
            return None if hashlib.file_digest(f,'sha256').hexdigest()==metadata['sha256'] else name
    with ThreadPoolExecutor(max_workers=8) as pool:errors=[x for x in pool.map(compare,items) if x]
    for collection,entries in expected.items():
        present={str(p.relative_to(ROOT.parent)) for p in (ROOT.parent/collection).rglob('*') if p.is_file() or p.is_symlink()}
        errors.extend(sorted(present-set(entries)))
    return {'files':len(items),'unchanged':not errors,'differences':errors,'baseline_sha256':digest(baseline.read_bytes())}


def prepare_boundaries(ledger):
    if ledger.records('frozen_input_boundaries'):return
    if ledger.db.execute("SELECT count(*) FROM runs WHERE phase IN ('practice','evaluation','selection')").fetchone()[0]:
        raise RuntimeError('Input-state identities must be captured before the new measured cohort')
    p=population();ids=p['practice']+p['selection_train']+p['selection_validation']+p['evaluation']
    if not ledger.records('smoke_gate'):raise RuntimeError('Complete the live gate before final boundary checks')
    from growth.memory import Memory
    signature=digest(source_identity())[:12]
    native_versions={}
    for arm in ARMS:
        # No model/provider substitution: this checks real saved stores only.
        memory=Memory(arm,None,namespace=f'smoke-{arm}-{signature}')
        try:packet=memory.checkpoint(0)
        finally:memory.close()
        reopened=Memory(arm,None,namespace=packet['native_namespace']);reopened.read_only=True
        try:
            if reopened.export()!=packet['artifact'] or reopened.version!=packet['version']:
                raise RuntimeError(f'{arm}: native checkpoint clone differs from actual smoke memory')
            native_versions[arm]=packet['version']
        finally:reopened.close()
    from growth.tools import Catalogue
    catalogue=Catalogue();catalogue_version=catalogue.version;catalogue.db.close()
    mark(ledger,'frozen_input_boundaries',{'task_database_identities':{
        task:digest(tree_identity(WORLD/'data/tasks'/task/'dbs')) for task in ids},
        'catalogue_version':catalogue_version,'protected':protected(),
        'native_clone_reopen_verified':native_versions,
        'protocol_document_hash':digest((ROOT/'growth/EXPERIMENT.md').read_bytes()),
        'protocol_document':(ROOT/'growth/EXPERIMENT.md').read_text(),
        'postprocessing_source':Path(__file__).read_text()},phase='freeze')
    for path in sorted((ROOT/'results').glob('growth-v*/ledger.sqlite')):
        if path.parent==RESULTS:continue
        with sqlite3.connect(f'file:{path}?mode=ro',uri=True) as previous:
            n,cost,unknown=previous.execute('SELECT count(*),coalesce(sum(estimate),0),sum(estimate IS NULL) FROM calls').fetchone()
            evaluations=previous.execute("SELECT count(*) FROM runs WHERE phase='evaluation'").fetchone()[0]
            mark(ledger,'excluded_cohort',{'path':str(path.relative_to(ROOT)),'requests':n,
                'known_estimate_usd':cost,'unknown_cost_requests':unknown or 0,'evaluation_attempts':evaluations,
                'reason':'Retained pre-evaluation integration evidence, not current quality outcomes'},phase='preparation')


def recognized_definitions(text):
    """Extract actual supplied schema objects, not names guessed from prose."""
    decoder=json.JSONDecoder();found={}
    for position,char in enumerate(text):
        if char!='{':continue
        try:value,_=decoder.raw_decode(text[position:])
        except ValueError:continue
        if isinstance(value,dict) and {'app_name','api_name','parameters'}<=value.keys():
            identity=str(value['app_name'])+'.'+str(value['api_name'])
            found[identity]={'identity':identity,'content':value,'content_hash':digest(value)}
    return found


def actual_tool_exposure(ledger,run_id,first_action):
    """Source-derived correction leaves original online counters untouched."""
    known=recognized_definitions('\n'.join(m['content'] for m in first_action['messages'][2:]))
    initial=sorted(known)
    searches={r['data']['decision']:r['data'] for r in ledger.records('tool_discovery',run_id)}
    actions={r['data']['number']:r['data'] for r in ledger.records('action_observation',run_id)}
    calls=collections.defaultdict(list)
    for r in ledger.records('tool_call',run_id):calls[r['data']['decision']].append(r)
    without=[];unknown=[];counts=0
    for decision in sorted(actions):
        for definition in searches.get(decision,{}).get('items',[]):
            known[definition['id']]={'identity':definition['id'],'content_hash':digest(definition['content'])}
        for call in calls[decision]:
            counts+=1;identity=call['data']['identity']
            if identity is None:unknown.append(call['id'])
            elif identity not in known:without.append(call['id'])
        # Only definitions actually present in returned observations become
        # model-visible next step. A failed documentation request grants nothing.
        for output in actions[decision]['outputs']:known.update(recognized_definitions(output))
    result={'initial_demonstrated_definitions':initial,'initial_sdk_call_id':first_action.get('call_id'),
            'initial_request_hash':first_action.get('request_hash'),'total_calls':counts,
            'calls_without_recognized_prior_schema':without,'unresolved_call_identities':unknown,
            'recognized_schema_ids':sorted(known),
            'definition':'Recognized JSON schemas in actual initial prompt, catalogue results and prior observations. '
                         'Absence is not proof of a wrong tool or absence of pretraining knowledge.'}
    mark(ledger,'tool_exposure_reconciliation',result,run_id=run_id,phase='postprocessing')
    return result


def audited_integration_traces(ledger):
    """Engineering diagnosis from excluded evidence, never new learning input."""
    old_path=ROOT/'results/growth-v2/ledger.sqlite'
    if not old_path.exists():return []
    old=object.__new__(Ledger)
    old.db=sqlite3.connect(f'file:{old_path}?mode=ro',uri=True);old.db.row_factory=sqlite3.Row
    lines=['', '## Integration ownership and actual traces', '',
           'The following traces belong to excluded growth-v2. They diagnose adapters and the common '
           'agent, and are not current-cohort task-quality evidence. No historical memory is restored '
           'into the current policy stores.', '',
           '| Component | Attribution supported by the audit | Repair or interpretation |',
           '| --- | --- | --- |',
           '| Common tool search | Owned query contract allowed a runaway synonym list with empty memory. | Schema-constrained keyword array, joined into one query for every policy. |',
           '| Mem0 | Owned extraction inputs mixed harness metadata with learnable observations. | Require observed experience; reject bare feedback; exclude request-only metadata; retain native extraction and reconciliation. |',
           '| ACE | Owned counter handling could reuse removed bullet identities. The observed bad actions do not prove this caused task failure. | Persist native next_global_id across consolidation. Agent failures remain separately diagnosed. |',
           '| Trace2Skill | Released source references an absent validator. This integration previously disclosed a skip. | Connect a pinned structural validator through that hook; measure its real outcome. Structure is not behavior. |',
           '| GEPA | Owned task adaptation used a default proposal prompt that asks for niche task facts. | Use the documented reflection template for reusable cross-task strategy; preserve native candidate testing and acceptance. |',
           '| RecMem | Owned timestamp adaptation supplied host dates inside a simulated world. | Supply simulated application time consistently to learning; retain real measurement timestamps in raw evidence. |']
    try:
        query_row=old.db.execute('SELECT * FROM calls WHERE id=?',('db21d548c51c476a8375f84456e11f17',)).fetchone()
        if query_row:
            d=json.loads(query_row['data']);input_data=json.loads(d['messages'][-1]['content'])
            lines+=['', '### Common discovery failure, labelled Trace2Skill in the run', '',
                    f'Call `{query_row["id"]}`; delivered historical memory: `{input_data["historical_memory"]}`. '
                    'Its output began:', '', '```text',d['output'][:280], '```', '',
                    'The output repeated query synonyms until MAX_TOKENS. The empty memory makes an '
                    'attribution to skill content unsupported. The raw request, response and cost remain in '
                    f'[the excluded ledger]({old_path}).']
        lines+=['', '### ACE: actual actions before and after learning', '']
        for phase in ['practice','post_update']:
            r=old.db.execute('SELECT * FROM runs WHERE arm="ace" AND phase=? ORDER BY started LIMIT 1',(phase,)).fetchone()
            if not r:continue
            e=experience(dict(r),old);d=json.loads(r['data'])
            native=Path(d['native_output'])/'tasks'/r['task_id']/'logs/environment_io.md'
            lines += [f'- {phase}, run `{r["id"]}`, official success `{bool(r["success"])}`: '
                      f'[actual executed actions and observations]({native}).']
            errors=[s for s in e['steps'] if any('Execution failed' in output for output in s['outputs'])]
            if errors:
                first=errors[0]
                lines+=['', f'First observed execution error, step {first["number"]}:', '',
                        '```python','\n'.join(first['inputs']), '```', '', '```text',
                        '\n'.join(first['outputs']), '```', '']
            if not r['success']:
                lines+=['Failed official requirement descriptions: '+json.dumps(e['feedback']['failed_requirements'])+'.', '']
        lines+=['The first attempt recovered from a parameter error and passed. The post-update attempt '
                'failed date parsing, later used a placeholder credential and finished with unmet song '
                'requirements. The unchanged upstream few-shot prompt itself contains `fake_access_token`. '
                'This is an observed common-agent/model failure; the pair does not establish that ACE '
                'caused the regression or that its memory architecture is intrinsically defective.', '',
                f'[Pinned upstream example prompt]({ROOT / ".cache/vendor/appworld/experiments/prompts/react_code_agent/instructions.txt"}).']
        for row in old.records('memory_event'):
            d=row['data']
            if row['arm']=='gepa' and d.get('operation')=='gepa_frontier':
                lines+=['', '### GEPA candidate and acceptance', '',
                        f'Native metric calls: `{d["total_metric_calls"]}`; validation aggregate scores: '
                        f'`{d["val_aggregate_scores"]}`; selected candidate index: `{d["best_idx"]}`.', '',
                        'The proposed candidate began:', '', '```text',
                        d['candidates'][-1]['strategy'][:450], '```', '',
                        'The empty seed tied this candidate and remained selected. The task-specific '
                        'proposal reflects the mismatched default template; it is not evidence that '
                        'GEPA cannot learn reusable instructions.']
        skill=ROOT/'results/growth-v2/checkpoints/0/trace2skill.json'
        if skill.exists():
            packet=read_json(skill)
            lines+=['', '### Trace2Skill: actual saved skill', '',
                    f'Frozen smoke version `{packet["version"]}`; [complete exported skill]({skill}).', '',
                    '````markdown',packet['artifact']['text'], '````', '',
                    'This was an actual native patch/evolution. The earlier missing quick validator '
                    'limits the validation claim; it does not show that procedures cannot transfer.']
        recmem=ROOT/'results/growth-v2/checkpoints/0/recmem.json'
        if recmem.exists():
            packet=read_json(recmem);layers=packet['artifact']['layers']
            raw=layers['raw'][0]
            raw_source=json.loads(raw['payload']['text'].split('[Message]: ',1)[1])['source_run']
            row=old.db.execute('SELECT data FROM runs WHERE id=?',(raw_source,)).fetchone()
            application_time=json.loads(row['data'])['task_datetime']
            lines+=['', '### RecMem: actual layers and timestamp mismatch', '',
                    f'[Complete raw, episodic and semantic snapshot]({recmem}); version `{packet["version"]}`.', '',
                    f'Raw item `{raw["id"]}` carries native timestamp `{raw["payload"]["timestamp"]}`. '
                    f'The actual source run `{raw_source}` used world time `{application_time}`. The adapter supplied the host '
                    'timestamp to native memory, making temporal interpretation ambiguous.', '',
                    'Actual episodic excerpt:', '', '```text',layers['episodic'][0]['payload']['text'][:500],
                    '```', '',
                    'Recurrence and all three native layers executed. Counting arrivals rather than '
                    'independent tasks is native behavior, whereas mixing the two clocks was our adapter error.']
    finally:old.db.close()
    probes=ledger.records('repair_probe')
    if probes:
        lines+=['', '### Fresh verification of repaired boundaries', '']
        for row in probes:
            d=row['data']
            if d['boundary']=='tool-discovery':
                lines.append(f'- Live call `{d["fresh_call"]}` on the recorded failing input returned '
                             f'`{json.dumps(d["terms"])}`, {d["output_characters"]} output characters.')
            elif d['boundary']=='mem0-input-provenance':
                lines.append('- The recorded bare grading packet was rejected before extraction: '
                             f'{d["reason"]}. This is a software input check with zero new model requests.')
            elif d['boundary']=='mem0-bare-feedback':
                lines.append(f'- Live call `{d["fresh_call"]}` stopped repeating but still produced '
                             'harness-metadata facts. It is retained as a failed integration probe, '
                             'which motivated enforcing input provenance instead of trusting prompt wording alone.')
    proposals=[]
    for row in ledger.db.execute("SELECT id,data FROM calls WHERE arm='gepa' AND kind='generation' ORDER BY started"):
        data=json.loads(row['data'])
        if data.get('purpose')=='gepa-reflection' and data.get('output'):proposals.append((row['id'],data))
    if proposals:
        identity,data=proposals[0]
        lines+=['', '### GEPA with the repaired cross-task objective', '',
                f'Actual fresh proposal call `{identity}` produced this excerpt:', '',
                '````text',data['output'][:1200], '````', '',
                'The complete proposal is retained in the current ledger and tested by the native optimizer; '
                'it is not hand-edited into a preferred strategy.']
        frontiers=[r['data'] for r in ledger.records('memory_event')
                   if r['arm']=='gepa' and r['data'].get('operation')=='gepa_frontier']
        if frontiers:
            f=frontiers[-1]
            lines += [f'Native result: {f["total_metric_calls"]} metric calls; accepted-candidate validation '
                      f'scores `{f["val_aggregate_scores"]}`; selected index `{f["best_idx"]}`; '
                      f'selected strategy empty `{not f["candidates"][f["best_idx"]]["strategy"]}`. '
                      'Rejected proposals remain in their actual evaluation events and SDK calls.']
    lines+=['', '### Pros and cons to assess after fixing the adapters', '',
            'These are properties of the implemented mechanisms and costs to measure, not a ranking '
            'or established claims about every implementation of each architecture.', '',
            '| Policy | Useful mechanism already observed | Cost or risk to measure in corrected runs |',
            '| --- | --- | --- |',
            '| Mem0 | Individually retrievable facts and explicit native updates. | Extraction/reconciliation expense, duplicate or unsupported claims, and whether retrieval selects the relevant facts. |',
            '| ACE | Readable playbook, exposure counters and similarity-based merging. | Reflection/curation/embedding expense, whole-playbook context growth, and conditions lost in merges. |',
            '| Trace2Skill | Actual trajectories produce editable procedure patches, including concrete date-parsing code. | Delayed batch learning, patch/generalization errors, context footprint, and behavioral correctness beyond structural validation. |',
            '| GEPA | Actual candidate rollouts can reject changes that do not improve the chosen metric. | Extra optimizer rollouts, selection-set overfitting, and cases where no accepted strategy justifies that expense. |',
            '| RecMem | Native raw, episodic and semantic layers consolidate recurring experience. | Embedding/merging/refinement expense, task-specific detail retention, and whether recurrence preserves useful conditions and retrieval reachability. |',
            '| Baseline | Same acting loop and discovery stage with no retained guidance. | Repeated discovery and repeated errors, compared with the memory policies\' added expense and advice. |']
    policies={r['arm']:r['data'] for r in ledger.records('smoke_policy')}
    lines+=['', '### Current corrected-cohort live verification', '',
            '| Policy | Acting, native learning/persistence and subsequent exposure | Saved entries at smoke gate | Actual current evidence |',
            '| --- | --- | --- | --- |']
    for arm in ARMS:
        p=policies.get(arm)
        links='Pending'
        if p:
            run=ledger.db.execute('SELECT * FROM runs WHERE id=?',(p['exposure_run'],)).fetchone()
            data=json.loads(run['data']);signature=data['cell']['candidate']
            artifact=RESULTS/'memories'/f'smoke-{arm}-{signature}'/'artifact.json'
            trace=Path(data['native_output'])/'tasks'/run['task_id']/'logs/environment_io.md'
            links=f'[Executed actions]({trace}), [saved memory]({artifact})'
        lines.append(f'| {arm} | '+('Completed' if p else 'Running or pending')+
                     f' | {p["entries"] if p else "Not established"} | {links} |')
    validation=[r['data'] for r in ledger.records('memory_event')
                if r['arm']=='trace2skill' and r['data'].get('operation')=='skill_structure_validation']
    if validation:
        latest=validation[-1]
        lines+=['', f'Trace2Skill native-hook structural validation recorded `{latest["valid"]}`: '
                f'{latest["message"]} Validator SHA-256 `{latest["validator_hash"]}`. '
                'This was an actual subprocess result, not a generated or simulated validation response.']
    lines+=['', 'A completed integration check does not establish that every stored claim is correct '
            'or that memory improves held-out performance. Empty accepted memory remains a valid outcome. '
            'Entry counts describe different units, such as facts, bullets, files and episodes; '
            'compare bytes, delivered tokens and outcomes rather than treating entry counts as equivalent knowledge.']
    return lines


def implementation_findings(ledger,record=True):
    """Describe measured mechanism behavior separately from task-quality claims."""
    gates=ledger.records('smoke_gate')
    if not gates:
        return ['', '## Implementation findings', '',
                'Live integration is incomplete. No six-policy mechanism conclusion is established.']
    cutoff=gates[-1]['created']
    events=[r for r in ledger.records('memory_event') if r['created']<=cutoff]
    packets={arm:read_json(RESULTS/'checkpoints/0'/f'{arm}.json') for arm in ARMS}
    counts=collections.Counter((r['arm'],r['data'].get('operation')) for r in events)
    mem0_ops=collections.Counter()
    for row in ledger.records('arrival_complete'):
        if row['arm']!='mem0' or row['created']>cutoff:continue
        result=row['data'].get('result') or {}
        for item in result.get('results',[]):mem0_ops[item.get('event','unknown')]+=1
    ace=[r['data'] for r in ledger.records('ace_similarity_groups') if r['created']<=cutoff]
    grouped=sum(len(r['groups']) for r in ace)
    frontiers=[r['data'] for r in events if r['arm']=='gepa' and r['data'].get('operation')=='gepa_frontier']
    strategy_empty=not packets['gepa']['artifact'].get('text')
    validations=[r for r in events if r['arm']=='trace2skill' and r['data'].get('operation')=='skill_structure_validation']
    layers=packets['recmem']['artifact'].get('layers',{})
    mechanism_rows=[
        ('Baseline', 'No retained cross-task entries.',
         'Simple control with no learning expense or persistent advice to corrupt.',
         'Must rediscover procedures and tool details; compare repeated discovery expense.'),
        ('Mem0', f"{packets['mem0']['entry_count']} facts; {dict(mem0_ops)} native mutations.",
         'Separately addressable facts and native reconciliation are observable.',
         'Fact count alone does not establish relevance or truth; review support and retrieval expense. '
         'An earlier cohort persisted a mistaken inference, documented separately.'),
        ('ACE', f"{packets['ace']['entry_count']} bullets; {len(ace)} analyser invocations, {grouped} similar groups.",
         'Compact readable lessons with exposure-linked feedback counters.',
         'Grouping and counters are observable; useful information preservation and task benefit require '
         'separate evidence. Do not attribute every acting failure to the playbook.'),
        ('Trace2Skill', f"{counts[('trace2skill','skill_evolution')]} native evolution; "
         f"{packets['trace2skill']['entry_count']} current procedure artifact.",
         'Actual trajectories became an editable procedure document.',
         f'{len(validations)} actual structural validation calls. Structural validity does not establish '
         'procedure correctness or transfer; API reminders may be less reusable than executable procedures.'),
        ('GEPA', f"{counts[('gepa','gepa_candidate_evaluation')]} actual candidate rollouts; "
         f"{packets['gepa']['entry_count']} retained strategy entries.",
         'Candidate acceptance is tested rather than accepting every generated lesson.',
         f'Selected strategy empty: {strategy_empty}; native validation scores: '
         f'{frontiers[-1].get("val_aggregate_scores") if frontiers else "unavailable"}. '
         'Rollout expense and accepted improvement must both be reported; an empty seed can be legitimate.'),
        ('RecMem', f"{counts[('recmem','_consolidate_memory')]} native consolidations; "
         + ', '.join(f'{name}: {len(items)}' for name,items in layers.items()) + '.',
         'Raw, episodic and semantic layers and recurrence-triggered consolidation actually activated.',
         'Recurrence counts arrivals rather than independent tasks. Episodes can retain task-specific '
         'details; review generalization. The host/application timestamp mismatch was an integration defect '
         'corrected in this cohort, not an inherent property of recurrence.')]
    lines=['', '## Implementation findings and conditional trade-offs', '',
           'The purpose is to explain implementation choices, not declare a winner. '
           'These are adapted implementations. Their failures do not establish intrinsic weaknesses '
           'of the memory architectures. Integration ownership must be resolved first. '
           'The following evidence comes from two discarded training-only smoke tasks per policy, '
           'plus explicitly separate candidate and exposure runs. It proves observed mechanism execution '
           'and exposes failure modes; it does not establish held-out improvement or growth behavior.', '',
           '| Policy | Observed mechanism evidence | Advantage to assess | Observed limitation or open trade-off |',
           '| --- | --- | --- | --- |']
    lines += ['| '+' | '.join(row)+' |' for row in mechanism_rows]
    dispositions=ledger.records('cohort_disposition')
    if dispositions:
        lines += ['', '### Integration audit and cohort disposition', '',
                  dispositions[-1]['data']['reason'], '',
                  'The interrupted Trace2Skill-labelled practice call was a common tool-search request '
                  'with empty historical memory, not a skill-learning failure. The GEPA default proposer '
                  'asks for niche task facts, conflicting with our reusable-strategy adaptation. '
                  'RecMem received real observation timestamps alongside simulated application dates. '
                  'Correct these adapters in a separately versioned cohort. Preserve all original traces '
                  'and expense; no completed task outcome is rerun or relabelled to make a policy win.']
    # A source-bound counterexample, never a handwritten change to the memory.
    target='The file_system API does not provide a way to retrieve file creation dates.'
    wrong=[item for item in packets['mem0']['artifact'].get('entries',[]) if item.get('memory')==target]
    catalogue=read_json(WORLD/'data/api_docs/standard/file_system.json')
    schema=catalogue['show_file']['response_schemas']['success']
    if wrong and 'created_at' in schema:
        evidence={'classification':'not-a-model','kind':'source-bound implementation review',
            'assessment':'contradicted by current public API schema','memory_items':wrong,
            'memory_version':packets['mem0']['version'],'api_identity':'file_system.show_file',
            'public_schema':catalogue['show_file'],'public_schema_hash':digest(catalogue['show_file']),
            'limit':'Not an official task grade or a representative memory-error rate; memory remains unchanged.'}
        if record:mark(ledger,'implementation_review',evidence,'mem0','postprocessing')
        lines += ['', '### Mem0 repetition repair and remaining factual risk', '',
                  'The earlier excluded cohort supplied a standalone grade with no supporting API observations. '
                  'Its extractor copied formatting instructions into purported facts and repeated them until '
                  'the output limit. This identifies the first observable failure boundary, not a proven '
                  'internal model cause. The repair supplies the actual instruction, actions, observations '
                  'and completion answer with feedback. It retains the output setting and native extraction/reconciliation.', '',
                  f'The repaired smoke completed its learning arrivals and retained item `{wrong[0]["id"]}`: '
                  f'“{target}” The pinned public `file_system.show_file` success schema includes `created_at`, '
                  'so the broad negative claim is contradicted. Successful parsing therefore does not mean '
                  'correct learning. This original memory is retained unchanged, with source-run lineage; '
                  'no manual correction is fed to the acting agent.']
    lines += ['', 'Conditional choices require matching evidence: choose facts when selective lookup and '
              'revision work at acceptable cost; playbooks when compact guidance stays supported; skills '
              'when procedures transfer and validate; optimized instructions when candidate gains justify '
              'rollout expense; layered recurrence when consolidation preserves conditions and source reachability. '
              'Keep the baseline when retained context adds expense or errors without a useful observed benefit. '
              'Checkpoint outcomes, fidelity reviews, retrieval traces, discovery exposures and expense qualify '
              'these choices. An empty strategy or inactive merge is reported explicitly, without inventing learning.']
    return lines


def retained_case_actions(ledger,result,packet):
    """Verify matched boundaries and quote observable actions, without secrets."""
    pairs=collections.defaultdict(dict)
    signatures={}
    for ident in result['follow_up_runs']+result['control_runs']:
        run=dict(ledger.db.execute('SELECT * FROM runs WHERE id=?',(ident,)).fetchone())
        data=json.loads(run['data'])
        control=ident in result['control_runs']
        intents=ledger.records('exposure_intent',ident)
        first=min(intents,key=lambda r:r['data']['decision'])['data']
        signatures[ident]=(data['reset_identity'],data['loaded_reset_identity'],
                           data['catalogue_version'],data['executed_source_identity'],first['native_prompt_hash'])
        generations=[json.loads(r['data']) for r in ledger.db.execute(
            'SELECT data FROM calls WHERE run_id=? AND kind="generation" ORDER BY started',(ident,))]
        settings={tuple(d.get(k) for k in ['provider','requested_model','resolved_model','temperature',
                                          'thinking_budget','max_output_tokens']) for d in generations}
        if len(settings)!=1:raise RuntimeError('Diagnostic model settings changed within run')
        signatures[ident]+= (settings,)
        if not control and data['memory_version']!=packet['version']:
            raise RuntimeError('Diagnostic follow-up did not use frozen memory version')
        pairs[run['task_id']][control]=(run,data)
    for pair in pairs.values():
        if set(pair)!={True,False}:raise RuntimeError('Missing diagnostic paired control')
        if signatures[pair[True][0]['id']]!=signatures[pair[False][0]['id']]:
            raise RuntimeError('Diagnostic paired reset, catalogue, prompt, source or model settings differ')
    lines=['', 'Paired source and loaded-state identities, initial upstream prompt hashes, tool '
           'catalogue versions, executed source and generation settings match. The selected '
           'native store was closed, reopened, checked against its export, then frozen before '
           'these attempts. Control exposure records contain no retained memory.','',
           '#### Three concrete applications in the file task','',
           'The saved instruction describes a procedure. In the subsequent file task, '
           'three observable actions match that procedure:']
    if '68ee2c9_2' in pairs:
        run,data=pairs['68ee2c9_2'][False]
        exp=experience(run,ledger)
        targets=[(8,'Capture each original path and creation year before mutation',
                  ['files_to_process','creation_year','original_path','new_path']),
                 (10,'Track the actual path returned by the rename operation',
                  ['renamed_files_info','rename_result','original_path','new_path','creation_year']),
                 (13,'Use the updated path for the later move while keeping the original creation year',
                  ['renamed_files_info','creation_year','new_path','source_file_path','destination_file_path'])]
        for number,title,terms in targets:
            step=next(x for x in exp['steps'] if x['number']==number)
            selected=[line for line in '\n'.join(step['inputs']).splitlines() if any(t in line for t in terms)]
            if not selected:raise RuntimeError('Missing reported file-procedure action')
            lines+=['',f'{title} (decision {number}), selected actual lines (noncontiguous excerpts, not a standalone program):', '', '```python',
                    '\n'.join(selected),'```']
        trace=Path(data['native_output'])/'tasks'/run['task_id']/'logs/environment_io.md'
        lines+=['',f'[Full file-task execution]({trace}). Both contexts passed with '
                f'{data["api_calls"]} API calls. These matches demonstrate instruction exposure '
                'and compatible execution, not necessity or an observed call-count saving.']
    if '6ea6792_2' in pairs:
        memory,control=pairs['6ea6792_2'][False],pairs['6ea6792_2'][True]
        counts=[];searches=[]
        for run,data in [memory,control]:
            counts.append(collections.Counter(r['data']['identity'] for r in ledger.records('tool_call',run['id'])))
            searches.append(min(ledger.records('tool_discovery',run['id']),key=lambda r:r['data']['decision'])['data'])
        if not(counts[0]['phone.search_contacts'] and counts[1]['venmo.search_friends']):
            raise RuntimeError('Reported Venmo discovery paths absent from actual calls')
        if searches[0]['query']!=searches[1]['query'] or searches[0]['items']!=searches[1]['items']:
            raise RuntimeError('Reported identical first tool searches differ')
        lines+=['', '#### Venmo: different relationship discovery, with additional expense','',
                f'The frozen-instruction attempt made {counts[0]["phone.search_contacts"]} '
                'phone-contact searches for friends and roommates and passed. The empty-memory '
                f'attempt made {counts[1]["venmo.search_friends"]} Venmo-friend searches, '
                'did not query phone contacts, and failed the official scope requirements. '
                f'Total API calls were {memory[1]["api_calls"]} with memory and '
                f'{control[1]["api_calls"]} without it.','',
                'Both first tool searches supplied the same query and definitions. The retained '
                'instruction does not explicitly name phone contacts or roommates. The observed '
                'pair therefore supports a behaviour-and-outcome difference, without proving '
                'that this generic instruction caused the relationship lookup or improved '
                'initial tool discovery. Model variability and this single pair limit attribution.']
    learning=[dict(r) for r in ledger.db.execute(
        'SELECT * FROM calls WHERE phase IN ("retention_learning","retention_v3_selection")')]
    # Scope to this diagnostic rather than charging earlier unsuccessful attempts here.
    learning=[r for r in learning if json.loads(r['data']).get('scope',{}).get('diagnostic_key')==result['key']
              or (r['run_id'] and json.loads(ledger.db.execute('SELECT data FROM runs WHERE id=?',
                  (r['run_id'],)).fetchone()[0])['cell']['phase']=='retention_v3_selection')]
    lines+=['',f'V3 construction and candidate testing recorded {len(learning)} measured SDK requests '
            f'and a known estimate of ${sum(r["estimate"] or 0 for r in learning):.6f}. '
            f'Unknown-cost requests in this scope: {sum(r["estimate"] is None for r in learning)}. '
            'Earlier empty-result diagnostics remain charged separately in the ledger.']
    return lines


def gepa_retention_evidence(ledger):
    """Report selected native strategies, never promote a tested proposal ourselves."""
    lines=['', '## GEPA retained instructions', '']
    diagnostics=ledger.records('retention_diagnostic_started')
    completed=ledger.records('retention_diagnostic_complete')
    for result in completed:
        d=result['data']
        if not d['retained']:
            reason=('the native optimiser selected no nonempty strategy under its declared metric'
                    if d['protocol'].get('metric') else
                    'its empty seed already passed the selection cases, and the declared native '
                    'score-threshold stop ended that pass/fail-only diagnostic')
            lines += [f'Diagnostic `{d["protocol"]["id"]}` retained no instruction: '
                      +reason+'. This outcome remains in the ledger.','']
    accepted_saved=0
    directory=RESULTS/'memories/gepa/optimizer-6'
    candidates_path=directory/'candidates.json';history_path=directory/'run_log.json'
    if candidates_path.exists() and history_path.exists():
        candidates=read_json(candidates_path);history=read_json(history_path)
        for entry in history:
            index=entry.get('new_program_idx',0)
            if not index or index>=len(candidates):continue
            strategy=candidates[index]['strategy']
            if not strategy:continue
            accepted_saved+=1
            scores=entry.get('subsample_scores',[]);new_scores=entry.get('new_subsample_scores',[])
            if not scores or sum(new_scores)<=sum(scores):
                raise RuntimeError('Reported native GEPA acceptance lacks strict score improvement')
            instruction_hash=digest(strategy)
            matching=[]
            for row in ledger.db.execute('SELECT * FROM runs WHERE arm="gepa" AND phase="selection" ORDER BY started'):
                run=dict(row);data=json.loads(run['data'])
                if data['cell']['candidate']!=instruction_hash or run['status']!='conclusive':continue
                exposures=[r for r in ledger.records('exposure',run['id'])
                           if any(item['content']==strategy for item in r['data']['items'])]
                if not exposures:raise RuntimeError('Accepted GEPA candidate lacks actual exposure')
                call=ledger.db.execute('SELECT status,data FROM calls WHERE id=?',
                                       (exposures[0]['data']['call_id'],)).fetchone()
                if call['status']!='live' or strategy not in json.loads(call['data'])['messages'][0]['content']:
                    raise RuntimeError('Accepted GEPA candidate missing from live SDK request')
                trace=Path(data['native_output'])/'tasks'/run['task_id']/'logs/environment_io.md'
                if not trace.exists():raise RuntimeError('Missing accepted-candidate task trace')
                matching.append((run,trace,exposures[0]))
            lines += [f'### Instruction accepted and saved as native candidate {index}', '',
                      'Actual instruction:', '', '```text',strategy,'```','',
                      f'Native acceptance compared training scores `{scores}` with `{new_scores}` '
                      f'and added candidate {index} without changing its acceptance rule. '
                      f'The instruction is persisted in [native candidates]({candidates_path}) '
                      f'and [acceptance history]({history_path}), canonical JSON content SHA-256 `{instruction_hash}`. '
                      'This is an accepted, saved optimisation candidate, rather than a rejected '
                      'proposal. It is distinct from the final strategy selected for the acting agent.']
            examples=matching[:4]+(matching[-1:] if len(matching)>4 else [])
            for run,trace,exposure in examples:
                lines+=['',f'Task: {json.loads(run["data"])["instruction"]} '
                        f'Official result: **{"pass" if run["success"] else "fail"}**. '
                        f'[Executed actions]({trace}); actual action request '
                        f'`{exposure["data"]["call_id"]}` contains the accepted instruction.']
            reused=[entry['i']+1 for entry in history if entry.get('selected_program_candidate')==index]
            if reused:
                lines+=['',f'The native optimiser later selected this saved candidate as its '
                        f'parent strategy in iteration(s) {reused}. This is reuse of a retained '
                        'instruction, not simply a proposal being tried for the first time. '
                        'Repeating tasks here is part of the declared native optimisation, not selective rerunning '
                        'of held-out failures.']
                if index==1:
                    repeated=ledger.db.execute('SELECT * FROM runs WHERE id=?',
                                               ('5bc43a19c8ef41db8fb8509baeb90514',)).fetchone()
                    if repeated and repeated['status']=='conclusive':
                        exp=experience(dict(repeated),ledger)
                        step=next(s for s in exp['steps'] if s['number']==3)
                        excerpt=[line for line in '\n'.join(step['inputs']).splitlines()
                                 if 'show_account_passwords()' in line or
                                    "file_system_access_token = file_system_login_result['access_token']" in line]
                        lines+=['', 'In the later file-task attempt, step 3 retrieved credentials '
                                'before authentication and stored the returned token. Selected '
                                'actual lines:', '', '```text','\n'.join(excerpt),'```','',
                                f'That attempt officially {"passed" if repeated["success"] else "failed"}. '
                                'This action matches the retained authentication advice; it '
                                'does not establish that the advice caused the full task outcome.']
                        raw=json.loads(repeated['data'])
                        repeated_trace=Path(raw['native_output'])/'tasks'/repeated['task_id']/'logs/environment_io.md'
                        lines += [f'[Later file-task reuse and actual actions]({repeated_trace}).']
            if index==1:
                lines += ['', 'In this acceptance, the empty-strategy file attempt referenced '
                          'an undefined passwords variable, then recovered, but later used '
                          'os.path.expanduser and produced a host path that did not match the '
                          'simulated file system. The candidate attempt fetched credentials '
                          'first, used application paths and passed. The learned advice '
                          'concerns authentication, so it does not explain every changed '
                          'action or prove that it fixed the file-move failure.', '',
                          'The empty strategy had also passed an earlier training attempt '
                          'on this same file task. Native acceptance here depends on its '
                          'paired training attempts, not a demonstrated stable advantage. '
                          'On the separate validation variants, this candidate passed the '
                          'Spotify and file tasks but failed the Venmo task. The seed passed '
                          'Spotify and Venmo but failed the file task. Both scored 2/3, so '
                          'keeping this candidate on the native frontier does not by itself '
                          'make it the final selected strategy.']
    earlier_lines=lines[3:];lines=lines[:3]
    frontiers=[r for r in ledger.records('memory_event')
               if r['arm']=='gepa' and r['data'].get('operation')=='gepa_frontier']
    retained=[]
    for record in frontiers:
        state=record['data'];index=state['best_idx']
        strategy=state['candidates'][index]['strategy']
        if strategy:retained.append((record,strategy))
    if not retained:
        if accepted_saved:
            errors=ledger.records('run_error')
            blocked=bool(errors and 'ReadTimeout' in errors[-1]['data'].get('message','')
                         and ledger.db.execute("SELECT count(*) FROM calls WHERE status='unknown'").fetchone()[0])
            return lines+earlier_lines+['', 'The native optimiser has accepted, saved and reused a nonempty '
                          'instruction during learning. Selection of the final strategy for '
                          'the acting agent '+('did not finish because a subsequent Vertex '
                          'request timed out. The worker stopped and the unknown request '
                          'remains unsettled; it was not retried.' if blocked else 'is still pending.')+
                          ' Candidate retention and reuse '
                          'are established; final frozen-agent memory and held-out benefit '
                          'are separate claims.']
        return lines+earlier_lines+['No completed native optimisation has selected a nonempty strategy yet. '
                      'The passing proposal tests elsewhere in this report are not retained '
                      'learning. The required example remains open: native selection, persisted '
                      'instruction, later exposure and an independently graded task attempt.']
    for record,strategy in retained:
        state=record['data'];directory=Path(state['run_dir'])
        checkpoint=int(directory.name.removeprefix('optimizer-'))
        path=RESULTS/'checkpoints'/str(checkpoint)/'gepa.json'
        if not path.exists():
            lines+=['A nonempty strategy was selected by the native optimiser; its immutable '
                    'checkpoint is not yet available. Do not count subsequent use until '
                    'persistence and actual exposure are verified.']
            continue
        packet=read_json(path)
        if packet['artifact'].get('text')!=strategy:
            raise RuntimeError('Selected GEPA instruction differs from immutable checkpoint')
        label=(f'Instruction retained after {checkpoint} practice tasks' if checkpoint>=0
               else 'Instruction retained in the known-case diagnostic')
        lines += [f'### {label}','']
        if checkpoint<0:
            matching_start=next((r['data'] for r in diagnostics if
                                 directory.parent.name=='retention-diagnostic-'+r['data']['key'][:12]),None)
            protocol=matching_start['protocol'] if matching_start else {}
            lines += ['This separate diagnostic deliberately trains and selects on the same '
                      'known upstream cases. It demonstrates native '
                      'instruction retention, not generalisation or held-out improvement. '
                      'GEPA starts with an empty strategy, uses actual task attempts and '
                      'official grading, and retains its native strict-improvement rule. '
                      'No lesson is inserted by the report author.','',
                      f'Declared objective: {protocol.get("objective","recorded in the diagnostic ledger")}. '
                      f'Training and selection task IDs: {protocol.get("train",[])}. '
                      f'Native stopping condition: {protocol.get("native_stop","recorded in source")}.','']
            if protocol.get('metric'):
                lines += [f'The diagnostic selection metric is `{protocol["metric"]}`. '
                          'These numbers are optimisation scores, not pass percentages. '
                          'Official pass/fail remains separate. For two completed tasks, '
                          'the total call-count bonus is at most 0.5, so one additional '
                          'passed task always outweighs any efficiency bonus. This '
                          'objective change applies only to the diagnostic; the frozen '
                          'comparison keeps its original task-completion metric.','']
        lines += [
                  'Actual selected and persisted instruction (line-break escapes displayed as paragraph breaks; saved bytes are unchanged):', '',
                  '```text',strategy.replace(r'\n','\n'),'```','',
                  f'Native selected candidate index: {state["best_idx"]}. '
                  f'Validation mean scores by retained candidate: {state["val_aggregate_scores"]}. '
                  f'Actual candidate-testing task attempts: {state["total_metric_calls"]}. '
                  f'[Immutable memory export]({path}), version `{packet["version"]}`. '
                  f'[Native candidate history]({directory / "candidates.json"}).']
        later=[]
        for row in ledger.db.execute('SELECT * FROM runs WHERE arm="gepa" AND started>? ORDER BY started',
                                      (record['created'],)):
            run=dict(row)
            if run['status']!='conclusive':continue
            exposures=[r for r in ledger.records('exposure',run['id'])
                       if any(i['content']==strategy for i in r['data']['items'])]
            if not exposures:continue
            call=ledger.db.execute('SELECT status,data FROM calls WHERE id=?',
                                   (exposures[0]['data']['call_id'],)).fetchone()
            if not call or call['status']!='live':raise RuntimeError('Retained strategy exposure is not live')
            request=json.loads(call['data'])
            if strategy not in request['messages'][0]['content']:
                raise RuntimeError('Retained GEPA strategy absent from actual model input')
            data=json.loads(run['data']);trace=Path(data['native_output'])/'tasks'/run['task_id']/'logs/environment_io.md'
            if not trace.exists():raise RuntimeError('Missing GEPA post-retention task trace')
            later.append((run,trace,exposures[0]))
        if not later:
            lines+=['', 'Persistence is verified. A later completed task receiving this exact '
                    'instruction is still pending.']
        for run,trace,exposure in later[:3]:
            lines+=['',f'Subsequent task: {json.loads(run["data"])["instruction"]} '
                    f'Official outcome: **{"pass" if run["success"] else "fail"}**. '
                    f'[Actual actions and observations]({trace}); live action request '
                    f'`{exposure["data"]["call_id"]}` contains the retained instruction. '
                    'This verifies retention and use as supplied context. Inspect the '
                    'corresponding actions and memory-withheld comparison before claiming '
                    'that the instruction caused success.']
        if checkpoint<0 and later:
            result=next((r['data'] for r in completed if r['data']['memory_version']==packet['version']),None)
            if result and result.get('control_runs'):
                lines += ['', '#### Frozen instruction and empty-memory controls','',
                          'Each task starts from the same application state. These repeated '
                          'known cases are qualitative controls, not a held-out benchmark. '
                          'AppWorld API calls include documentation and application calls; '
                          'generation requests and estimated provider expense are reported '
                          'separately. Training and selection expense is additional.','',
                          '| Task | Context | Official result | AppWorld API calls | Generation requests | Known estimated USD |',
                          '| --- | --- | --- | --- | --- | --- |']
                ids=result['follow_up_runs']+result['control_runs']
                for ident in sorted(ids,key=lambda i:ledger.db.execute('SELECT started FROM runs WHERE id=?',(i,)).fetchone()[0]):
                    run=ledger.db.execute('SELECT * FROM runs WHERE id=?',(ident,)).fetchone()
                    data=json.loads(run['data']);control=ident in result['control_runs']
                    if control:
                        if any(r['data']['items'] for r in ledger.records('exposure',ident)):
                            raise RuntimeError('Empty-memory control received retained memory')
                        if any(r['data']['memory_exposed'] for r in ledger.records('tool_discovery',ident)):
                            raise RuntimeError('Empty-memory control guided tool search with memory')
                    calls=list(ledger.db.execute('SELECT * FROM calls WHERE run_id=?',(ident,)))
                    cost=(f'{sum(c["estimate"] or 0 for c in calls):.6f}' if all(c['estimate'] is not None for c in calls) else 'unknown')
                    trace=Path(data['native_output'])/'tasks'/run['task_id']/'logs/environment_io.md'
                    lines.append(f'| [{run["task_id"]}]({trace}) | '+('Empty memory' if control else 'Frozen selected instruction')+
                                 f' | {"pass" if run["success"] else "fail"} | {data["api_calls"]} | '
                                 f'{sum(c["kind"]=="generation" for c in calls)} | {cost} |')
                lines+=retained_case_actions(ledger,result,packet)
    return lines+['', '### Earlier retention attempts and main optimiser history', '']+earlier_lines


def learning_input_audit(ledger):
    """Inspect existing learning copies without printing credential values."""
    import re
    findings=[]
    for row in ledger.db.execute('SELECT * FROM runs WHERE status="conclusive" '
                                 'AND phase IN ("practice","smoke") ORDER BY started'):
        exp=experience(dict(row),ledger)
        for step in exp['steps']:
            if not re.search(r'print\(\w*password\)', '\n'.join(step['inputs'])):continue
            if any(value.strip() and value.strip()!='[AUTH REDACTED]' and '\n' not in value.strip()
                   for value in step['outputs']):
                findings.append({'arm':row['arm'],'run_id':row['id'],'step':step['number']})
    return {'accepted':not findings,'standalone_password_observations':findings,
            'scope':'Source-derived audit of simple print(password_variable) observations only. '
                    'No credential values included; absence of findings is not a complete secret scan.'}


def task_examples(ledger):
    """Source-linked qualitative cases, never a causal-use or benchmark grader."""
    specs=[
        ('Mem0','Recall the song-ranking API','30a65c9c7b604658aadb67828054cc71',
         'search_songs can search for songs by query and sort',4,['search_songs('],
         'A fact learned after the earlier album task described sorting songs by play count. '
         'The later artist question used artist_id and descending play count, requesting one song. '
         'This is transfer between two practice tasks. Current documentation was also supplied, so '
         'the trace does not identify memory as the unique source of the choice.'),
        ('Mem0','Recall exact file-move arguments','bcb4acf0042b4939942983bc796620ac',
         "API requires 'source_file_path'",11,['move_file('],
         'The retrieved fact names the actual source and destination parameters. The agent used '
         'those names to move the photos, retaining the original file names. This repeats a '
         'previously practised task from a fresh world; it does not demonstrate transfer to an unseen task.'),
        ('Mem0','Find the transaction tool for a new question','8cf966da93b34b1bafe7898ea19c9d27',
         '"show_transactions" function',10,['show_transactions(','direction=','min_created_at=','page_index='],
         'A fact extracted from the earlier payment-request task identifies show_transactions. '
         'For the later spending question, the agent retrieved current roommates, queried sent '
         'transactions from January onward, paginated and summed amounts. This illustrates tool '
         'recall across tasks, with additional current documentation and two failed phone-login '
         'attempts; it is not evidence that memory alone supplied the procedure.'),
        ('ACE','Look up an entity ID before ranking its songs','397da6627b474d6687edc108fe84ffad',
         'first perform a search to identify the entity and obtain its unique identifier',8,['search_songs('],
         'After reflecting on the first attempt at this artist question, ACE added an explicit '
         'ID-first lesson. The planned fresh-world check used the artist ID to request songs '
         'sorted by play count and passed. The preceding attempt also passed; this demonstrates '
         'a relevant learned procedure during execution, not an outcome improvement.'),
        ('ACE','Join phone relationships with payment data','08cc00f347674ca8ac3fcbbe3bcc80f4',
         'filtering data based on relationships or categories defined in another application',12,
         ['for roommate in roommates:','show_transactions(','direction=','min_created_at='],
         'The playbook retained a cross-application lesson from the earlier payment-request task. '
         'The later spending task fetched current phone contacts and used their emails to filter '
         'Venmo transactions. This is a reusable workflow across different practice tasks. '
         'The subsequent ACE post-update check of this spending task failed, so the successful '
         'execution is not a reliability guarantee.'),
        ('ACE','Keep the fallback photo category explicit','66824006f18444cab591ef966e7e1992',
         'When classifying items based on conditions',9,
         ["destination_vacation =",'if created_at.year','if created_at.month','elif created_at.month'],
         'ACE learned classification advice after an unsuccessful first photo attempt. In the '
         'later check, the agent set Amsterdam as the default and overrode it only for February '
         'or March of the current year. The first attempt failed and this check passed. '
         'The playbook advice is broader than the exact code, and changed model output also '
         'explains a possible difference. This repeated task is not held-out evidence.'),
        ('Trace2Skill','Read creation dates from file metadata','a041e1dfb5c046958e1ba2388c4cdf87',
         'Get metadata for a file, including',7,['show_file('],
         'The generated skill names show_file as the source of creation timestamps. The agent '
         'collected that metadata before categorising photos. The stored API examples are schematic; '
         'current API definitions supply the actual argument contract.'),
        ('Trace2Skill','Convert timestamps before comparing dates','a041e1dfb5c046958e1ba2388c4cdf87',
         'The `created_at` field from `show_file` is a string',8,
         ['fromisoformat','if created_at.year','if created_at.month','elif created_at.month'],
         'The learned skill explicitly says to convert timestamp strings to datetime objects. '
         'The later code performs that conversion and checks both year and month, keeping '
         'photos from other years out of the current-year February and March categories.'),
        ('Trace2Skill','Carry out the file-move procedure','a041e1dfb5c046958e1ba2388c4cdf87',
         'create_directory(path)',10,['for file_path in','file_name =','destination_path =','move_file('],
         'The skill lists directory creation and file moves. The agent created the destinations '
         'at step 9 and then moved each classified file at step 10 while keeping its name. '
         'These three Trace2Skill cases are three behaviours within one successful repeated '
         'task, not three independent transfer successes. Structural validation of the skill '
         'checks its format, not the correctness of its procedures.'),
        ('GEPA','Test a complete file-organisation instruction','0145d77a0329485d95c85cc6399cada4',
         'If the task involves organizing files based on their creation date',10,
         ['fromisoformat','create_directory(','move_file('],
         'GEPA proposed a sequence covering the current year, metadata, date parsing, directory '
         'creation and moves. A native candidate test received it and executed the corresponding '
         'sequence; the task passed after 13 action decisions. The attempt also contained '
         'authentication errors and recovery. The optimiser did not retain this candidate.'),
        ('GEPA','Test a more explicit timestamp-parsing instruction','00b401b0511d4573a3e42d336574d09a',
         'Parse this timestamp into a datetime object using `datetime.fromisoformat`',5,
         ['fromisoformat','if created_at.year','create_directory(','move_file('],
         'Another native proposal explicitly named fromisoformat. The candidate test retrieved '
         'the current year, parsed creation times, chose destinations and moved files, passing '
         'in six action decisions. Empty-strategy candidate tests also passed this task. '
         'The different action count is descriptive, not a measured instruction effect.'),
        ('GEPA','Reject advice that failed its candidate test','15378a25ce7b4856be933368a897fde1',
         'Unexpected parameter',None,[],
         'GEPA proposed reviewing API documentation after an unexpected-parameter error. '
         'The candidate task attempt failed. The native optimiser retained the empty seed. '
         'Candidate rejection is functioning, but this is a negative case, not a successful '
         'memory-assisted task. There is still no accepted-strategy transfer example.'),
        ('RecMem','Recover a consolidated photo procedure','ddf04a52bfb948f0982f52b3d3dc799d',
         'the user initiated a task to organize vacation photos',8,
         ['fromisoformat','if created_at.year','elif created_at.year','move_file('],
         'RecMem retrieved an episode describing the earlier photo workflow and its categories. '
         'The later check read current files, parsed their timestamps and moved them correctly. '
         'This is a repeated task. The same episode also appended unrelated Venmo feedback, '
         'showing that active consolidation can blur task boundaries even when execution passes.'),
        ('RecMem','Reuse a relationship-lookup workflow across tasks','be731037d5384d3187b5edb4164fa97e',
         "search for contacts with 'friend' and 'roommate' relationships",9,
         ["relationship='roommate'",'page_index='],
         'The retrieved episode describes using phone contacts to identify friends and roommates '
         'for an earlier payment-request task. For the new spending question, the agent queried '
         'the current phone contacts again instead of treating old contact names as current truth, '
         'then filtered and summed current Venmo transactions at step 12. This is a plausible '
         'workflow transfer; the memory-withheld comparison is still absent.'),
        ('RecMem','Complete an artist-following task despite unrelated retrieval','a39172ec290d4f62bc24b83b9bea0518',
         'the user requested to play the most listened-to song',7,['for artist_id in','follow_artist('],
         'The agent completed the liked-song artist-following task, but the retrieved episode '
         'describes an earlier album-playing failure rather than the needed follow operation. '
         'This is a deliberate counterexample to counting every successful memory-enabled task '
         'as memory help. Current documentation and observations supplied the follow operation; '
         'a useful contribution from that episode is not established.'),
    ]
    lines=['', '## Concrete task examples for the five memory architectures', '',
        'The question is whether learned knowledge changes useful work: earlier experience, '
        'saved knowledge, actual exposure, observable action and an official task result. '
        'The cases below are a purposive qualitative sample from the corrected cohort, not '
        'an independent benchmark score. All cited model requests are fresh live calls. '
        'No new model requests, tasks or reference answers were created for this analysis.', '',
        '**Evidence strength:** action alignment means a learned item was actually delivered '
        'before a corresponding action. It does not establish that the action required that '
        'item. A memory contribution needs the matched comparison with memory withheld. '
        'The frozen comparison has no held-out results yet. The separate known-case GEPA '
        'retention section above supplies matched controls. Earlier GEPA narratives below '
        'describe candidate tests; final selected memory is documented above. Trace2Skill '
        'examples currently cover one task at three different steps.', '',
        '### What differs and which situations each mechanism fits', '',
        '| Architecture | Knowledge and learning | How it reaches the agent | Conditional fit and trade-off |',
        '| --- | --- | --- | --- |',
        f'| [Mem0 integration]({ROOT / "growth/memory.py"}:178) | Individually extracted facts, with native additions, revisions and deletions. | Search on the task and latest result before every decision. | A useful candidate for small API facts and changing details. Fact-level selection is visible, but extraction can create false claims and retrieval adds embedding calls. |',
        f'| [ACE integration]({ROOT / "growth/memory.py"}:193) | Lessons in a playbook, with reflection, curation, usage counters and similarity merging. | Whole playbook, packed within the shared context allowance. | A useful candidate for cross-application workflows and recurring mistakes. Readable lessons are easy to inspect; broad advice can be irrelevant or fail to prevent another mistake. |',
        f'| [Trace2Skill integration]({ROOT / "growth/memory.py"}:247) | Procedure files revised from batches of actual trajectories. | Whole skill files, packed as complete items. | A useful candidate for repeatable multistep procedures such as metadata, classification and moves. Learning is delayed until a practice block ends, and structural validity does not prove executable correctness. |',
        f'| [GEPA integration]({ROOT / "growth/memory.py"}:302) | Instructions proposed and tested through extra task attempts; only native accepted candidates persist. | Whole accepted strategy, or no extra strategy when empty. | A useful candidate when strategy changes have a measurable selection signal. Testing can reject bad advice, but costs additional attempts and can retain nothing when the seed already passes. |',
        f'| [RecMem integration]({ROOT / "growth/memory.py"}:99) | Raw observations, consolidated episodes and semantic memories with recurrence gates. | Native search across all three layers. | A useful candidate when a relevant earlier workflow and its surrounding experience matter. Episodes preserve context, but can mix tasks, retain stale details and retrieve substantial irrelevant material. |', '',
        'These are conditional engineering choices from the observed mechanisms. The present '
        'cases do not establish which architecture achieves better task completion in any '
        'task category. The frozen integration and its adaptations are specified in '
        f'[the protocol]({ROOT / "growth/EXPERIMENT.md"}); native entry points are linked in '
        f'[the memory adapter]({ROOT / "growth/memory.py"}).']
    # The report includes exact delivered item content hashes and request identities.
    # Short excerpts are quotations, never replacements applied to native memory.
    changes=ledger.records('consolidation')
    rendered=collections.Counter();identities=[]
    for arm,title,rid,needle,step_number,code_terms,interpretation in specs:
        row=ledger.db.execute('SELECT * FROM runs WHERE id=?',(rid,)).fetchone()
        if not row or row['status']!='conclusive':continue
        run=dict(row);exp=experience(run,ledger);data=json.loads(run['data'])
        exposures=ledger.records('exposure',rid)
        eligible=[]
        for record in exposures:
            if step_number and record['data']['decision']>step_number:continue
            for item in record['data']['items']:
                if needle in item['content']:
                    eligible.append((record,item));break
        if not eligible:raise RuntimeError(f'Case has no prior measured memory exposure: {arm} {title}')
        exposure,item=eligible[-1] if step_number else eligible[0]
        call=ledger.db.execute('SELECT status,data FROM calls WHERE id=?',(exposure['data']['call_id'],)).fetchone()
        if not call or call['status']!='live':raise RuntimeError('Case exposure is not a live action request')
        request=json.loads(call['data'])
        if item['content'] not in request['messages'][0]['content']:
            raise RuntimeError('Case memory is absent from actual SDK request')
        if step_number:
            step=next(s for s in exp['steps'] if s['number']==step_number)
            code='\n'.join(step['inputs'])
            excerpts=[line for line in code.splitlines() if any(term in line for term in code_terms)]
            if not excerpts:raise RuntimeError('No matching executed action for case')
        else:excerpts=[]
        quote_lines=[line for line in item['content'].splitlines() if needle in line]
        full_quote=quote_lines[0] if quote_lines else item['content']
        start=max(0,full_quote.index(needle)-100)
        quote=(' [...] ' if start else '')+full_quote[start:start+650]
        if len(full_quote)>start+650:quote+=' [...]'
        ancestry=[]
        for change in changes:
            if change['arm']!=run['arm'] or change['created']>exposure['created']:continue
            delta=change['data']['changes']
            for changed in delta['added']+[v['after'] for v in delta['updated']]:
                if (needle in changed['content'] and
                    (changed['id']==item['id'] or arm=='ACE')):
                    ancestry=change['data']['source_runs'];break
        native=Path(data['native_output'])/'tasks'/run['task_id']/'logs/environment_io.md'
        if not native.is_file():raise RuntimeError(f'Missing case trace: {native}')
        if rendered[arm]==0:lines+=['',f'### {arm} task examples','']
        rendered[arm]+=1
        lines += ['',f'#### {title}', '', f'Task: {exp["instruction"]}', '',
                  'Actual supplied knowledge excerpt:', '', '> '+quote.replace('\n','\n> '), '']
        if excerpts:
            lines += [f'Selected executed lines from step {step_number} '
                      '(noncontiguous excerpts, not a standalone program):', '', '```text',
                      '\n'.join(excerpts),'```','']
        lines += [f'Official task result: **{"pass" if run["success"] else "fail"}**. '
                  +interpretation, '']
        if step_number and exposure['data']['decision']!=step_number:
            lines += [f'The quoted item was last supplied at decision {exposure["data"]["decision"]} '
                      f'before this action, and was absent from the request generating step {step_number}. '
                      'Earlier exposure and current documentation both remain possible influences.','']
        lines += [f'[Executed actions and observations]({native}).']
        if arm=='GEPA':
            proposal=None
            for candidate in ledger.db.execute('SELECT id,data FROM calls WHERE arm="gepa" '
                                               'AND started<? ORDER BY started DESC',(exposure['created'],)):
                packet=json.loads(candidate['data'])
                if packet.get('purpose')=='gepa-reflection' and item['content'] in packet.get('output',''):
                    proposal=candidate['id'];break
            if not proposal:raise RuntimeError('GEPA case lacks its actual model-generated proposal')
            lines += [f'The instruction was generated by proposal request `{proposal}` in the '
                      'ledger, not written by the report author. Its request retains the '
                      'actual candidate-test feedback supplied to the proposer.']
        identities.append((arm,title,rid,exposure['data']['call_id'],item['id'],digest(item['content'])))
        if ancestry:
            refs=[]
            for source in ancestry:
                source_row=ledger.db.execute('SELECT task_id,data FROM runs WHERE id=?',(source,)).fetchone()
                if not source_row:continue
                source_data=json.loads(source_row['data'])
                source_path=Path(source_data['native_output'])/'tasks'/source_row['task_id']/'logs/environment_io.md'
                refs.append(f'[{source_row["task_id"]}]({source_path})')
            if refs:lines+=['Earlier operation-input sources: '+', '.join(refs)+'. '
                           'This ancestry is conservative, not proof that every sentence is supported by every source.']
    lines+=['', '### Cost of the same preliminary photo task', '',
            'Each row is one fresh-world preliminary check on the same photo task. All passed. '
            'These checks repeat practice and do not measure held-out quality. Learning expense '
            'is excluded from this execution table. Generation counts include the common tool-search '
            'request and the action request at every decision. Token-count calls are separate SDK '
            'requests, not agent decisions. Prices are the frozen estimates, not an invoice.', '',
            '| Configuration | Action decisions | Generation requests | Embedding requests | Token-count requests | Estimated execution USD | Task seconds |',
            '| --- | --- | --- | --- | --- | --- | --- |']
    for arm in ARMS:
        row=ledger.db.execute('SELECT * FROM runs WHERE phase="smoke_exposure" AND arm=? ORDER BY started LIMIT 1',(arm,)).fetchone()
        if not row:continue
        data=json.loads(row['data']);calls=[dict(r) for r in ledger.db.execute('SELECT * FROM calls WHERE run_id=?',(row['id'],))]
        counts=collections.Counter(c['kind'] for c in calls)
        cost=(f'{sum(c["estimate"] or 0 for c in calls):.6f}' if all(c['estimate'] is not None for c in calls) else 'unknown')
        lines.append(f'| {arm} | {len(data["steps"])} | {counts["generation"]} | {counts["embedding"]} | '
                     f'{counts["token_count"]} | {cost} | {data["duration_s"]:.3f} |')
    lines += ['', 'ACE was faster than the baseline in this one check while using more generation '
              'requests; other policies took more decisions or supplied more context. These are '
              'single observations with different model outputs, provider timing, order and '
              'instrumentation overhead. They do not establish a speed ranking. GEPA supplied '
              'an empty accepted strategy in this table, despite its separately recorded candidate '
              'testing expense.', '',
              '### What these cases establish', '',
              'Mem0 exposes reusable facts, ACE exposes workflow lessons, Trace2Skill exposes '
              'procedural guidance, GEPA executes and scores proposed instructions, and RecMem '
              'retrieves consolidated experience. Relevant advice and corresponding actions '
              'are observable in several passing tasks. A baseline also completes the photo task; '
              'the examples cannot establish that memory was necessary.', '',
              'The remaining contribution claim is task-specific: with the same task, world, '
              'memory version and settings, what changes when memory is withheld from execution '
              'or tool search? The frozen comparisons would provide that test on held-out cases; '
              'the GEPA diagnostic above supplies two known-case pairs. A failed candidate, '
              'irrelevant retrieval, merged task boundaries or an empty retained strategy stays '
              'part of the explanation. There are not yet two or three demonstrated beneficial '
              'memory effects for every architecture.', '',
              '### Learning input qualification', '']
    audit=learning_input_audit(ledger)
    if not audit['accepted']:
        affected=collections.Counter(x['arm'] for x in audit['standalone_password_observations'])
        lines += [f'The source audit found {len(audit["standalone_password_observations"])} '
                  'standalone password-print observations that remain unredacted in the '
                  'learning-copy builder, across '+', '.join(f'{arm}: {count}' for arm,count in sorted(affected.items()))+'. '
                  'These are simulated AppWorld credentials, not provider credentials. Their '
                  'values are omitted here. The owned redaction routine recognises structured '
                  'password fields and tokens but misses some plain-text password observations. '
                  'This violates the declared learning-input normalisation contract and was '
                  'not covered by the earlier integration gate. It is an integration defect, '
                  'not an architectural memory weakness. Existing actions, saved memories and '
                  'official outcomes remain observable; a protocol-conformant quality '
                  'comparison cannot be certified from this cohort without resolving its '
                  'input disposition. Repair requires versioning and cannot silently rewrite '
                  'the frozen inputs or erase these attempts.']
    lines += ['', '### Evidence identities', '',
              f'These {len(identities)} case narratives cover '
              f'{len({row[2] for row in identities})} task attempts across '
              f'{len({ledger.db.execute("SELECT task_id FROM runs WHERE id=?",(row[2],)).fetchone()[0] for row in identities})} '
              'distinct upstream tasks. They deliberately include repeated tasks and '
              'multiple behaviours within a task; they are not 15 independent successes.', '',
              f'The [measurement ledger]({RESULTS / "ledger.sqlite"}) retains the full selected '
              'items, exact SDK requests, learning mutations and official grades. The table '
              'identifies the specific delivered item and request for each narrative. The '
              'hash covers the full item, including content omitted from the short quotation, '
              'using the project SHA-256 digest of its canonical JSON string encoding.', '',
              '| Architecture and example | Task attempt | Action request | Item | Content SHA-256 |',
              '| --- | --- | --- | --- | --- |']
    for arm,title,rid,call_id,item_id,content_hash in identities:
        lines.append(f'| {arm}: {title} | `{rid}` | `{call_id}` | `{item_id}` | `{content_hash}` |')
    return lines


def reconcile(ledger):
    source=Path(__file__).read_text()
    mark(ledger,'postprocessing_source',{'source':source,'hash':digest(source)},phase='postprocessing')
    audit=report(ledger)
    comparison_text=(RESULTS/'REPORT.md').read_text().splitlines()[1:]
    freeze=ledger.records('experiment_freeze')
    frozen=freeze[-1]['data']['source_identity'] if freeze else None
    runs={r['id']:dict(r) for r in ledger.db.execute('SELECT * FROM runs')}
    calls=[dict(r) for r in ledger.db.execute('SELECT * FROM calls ORDER BY started')]
    resets=collections.defaultdict(set);prompts=collections.defaultdict(set)
    exposure_errors=[];version_errors=[];grade_errors=[];input_errors=[]
    boundary=ledger.records('frozen_input_boundaries')
    boundary=boundary[-1]['data'] if boundary else None
    if boundary and boundary['protocol_document_hash']!=digest((ROOT/'growth/EXPERIMENT.md').read_bytes()):
        input_errors.append('Canonical growth protocol document changed')
    response_ids=[];first_actions={}
    for call in calls:
        d=json.loads(call['data'])
        if call['kind']=='generation' and d.get('response_id'):response_ids.append(d['response_id'])
        if d.get('purpose')=='agent-action' and call['phase']=='evaluation':
            if call['run_id'] not in first_actions:first_actions[call['run_id']]=d
            intent=[r['data'] for r in ledger.records('exposure_intent',call['run_id'])
                    if r['data']['request_hash']==d.get('request_hash')]
            if len(intent)!=1:exposure_errors.append(call['id'])
            if intent and intent[0]['decision']==1:
                prompts[runs[call['run_id']]['task_id']].add(intent[0]['native_prompt_hash'])
        if d.get('purpose')=='tool-search-query' and call['phase']=='evaluation':
            mode=json.loads(runs[call['run_id']]['data'])['cell']['mode']
            delivered=json.loads(d['messages'][-1]['content'])['historical_memory']
            if mode=='discovery_off' and delivered:exposure_errors.append(call['id'])
    for run in runs.values():
        if run['phase']!='evaluation':continue
        d=json.loads(run['data']);cell=d['cell']
        if not boundary or d.get('reset_identity')!=boundary['task_database_identities'].get(run['task_id']):
            input_errors.append(run['id']+': initial database')
        if boundary and d.get('catalogue_version')!=boundary['catalogue_version']:
            input_errors.append(run['id']+': tool catalogue')
        if d.get('executed_source_identity')!=frozen:version_errors.append(run['id'])
        if d.get('loaded_reset_identity'):resets[run['task_id']].add(d['loaded_reset_identity'])
        checkpoint=RESULTS/'checkpoints'/str(cell['checkpoint'])/f'{run["arm"]}.json'
        if checkpoint.exists() and d['memory_version']!=read_json(checkpoint)['version']:
            version_errors.append(run['id'])
        if run['status']=='conclusive':
            checks=ledger.records('saved_state_verification',run['id'])
            if len(checks)!=1 or checks[0]['data']['application_hashes']!=d['final_application_hashes']:
                grade_errors.append(run['id'])
        if cell['mode']=='execution_off':
            if any(r['data']['items'] for r in ledger.records('exposure_intent',run['id'])):
                exposure_errors.append(run['id'])
    tool_exposure={run_id:actual_tool_exposure(ledger,run_id,call) for run_id,call in first_actions.items()}
    # Correct the derived CSV using full initial-template and successful-return
    # exposure, retaining the original online measurements in the ledger.
    csv_path=RESULTS/'comparison.csv'
    with csv_path.open() as f:
        reader=csv.DictReader(f);csv_fields=list(reader.fieldnames);csv_rows=list(reader)
    old_name='calls_without_exposed_definition';new_name='calls_without_recognized_prior_schema'
    csv_fields=[new_name if x==old_name else x for x in csv_fields]
    for row in csv_rows:
        related=[ident for ident,run in runs.items() if run['phase']=='evaluation' and run['arm']==row['arm']
                 and (cell:=json.loads(run['data'])['cell'])['checkpoint']==int(row['checkpoint'])
                 and cell['mode']==row['mode']]
        row.pop(old_name,None)
        row[new_name]=sum(len(tool_exposure[i]['calls_without_recognized_prior_schema'])
                          for i in related if i in tool_exposure)
    with csv_path.open('w') as f:
        writer=csv.DictWriter(f,csv_fields);writer.writeheader();writer.writerows(csv_rows)
    protection=protected()
    reference=read_json(ROOT/'results/freeze.json')['identity']
    dependency_errors=[];upstream_errors=[]
    for name,version in reference['packages'].items():
        try:
            if importlib.metadata.version(name)!=version:dependency_errors.append(name)
        except importlib.metadata.PackageNotFoundError:dependency_errors.append(name)
    for name,identity in reference['sources'].items():
        directory=ROOT/'.cache/vendor'/name
        actual=subprocess.check_output(['git','rev-parse','HEAD'],cwd=directory,text=True).strip()
        if actual!=identity['commit']:upstream_errors.append(name+': commit')
        changed=subprocess.check_output(['git','-c','filter.lfs.process=','-c','filter.lfs.required=false',
            'diff','--name-only','HEAD','--','*.py'],cwd=directory,text=True).splitlines()
        expected=['experiments/code/simplified/agent.py'] if name=='appworld' else []
        if sorted(changed)!=expected:upstream_errors.append(name+': modified source')
    injected=ROOT/'.cache/vendor/appworld/experiments/code/simplified/agent.py'
    if digest(injected.read_bytes())!=reference['sources']['appworld']['injected_agent_hash']:
        upstream_errors.append('AppWorld injected constructor differs')
    strict={'classification':'not-a-model','reset_versions_per_task':{k:len(v) for k,v in resets.items()},
            'initial_prompt_versions_per_task':{k:len(v) for k,v in prompts.items()},
            'exposure_errors':exposure_errors,'source_or_memory_version_errors':version_errors,
            'saved_state_grade_errors':grade_errors,'duplicate_provider_response_ids':len(response_ids)-len(set(response_ids)),
            'protected':protection,'dependency_errors':dependency_errors,'upstream_errors':upstream_errors,
            'input_errors':input_errors,'premeasurement_input_boundaries_present':boundary is not None,
            'postprocessor_hash':digest(source),'learning_input_audit':learning_input_audit(ledger)}
    strict['accepted']=(audit['accepted'] and not exposure_errors and not version_errors and not grade_errors
        and all(len(v)==1 for v in resets.values()) and all(len(v)==1 for v in prompts.values())
        and strict['duplicate_provider_response_ids']==0 and protection['unchanged']
        and not dependency_errors and not upstream_errors and not input_errors and boundary is not None
        and strict['learning_input_audit']['accepted'])
    write_json(RESULTS/'strict-integrity.json',strict)
    mark(ledger,'strict_integrity',strict,phase='postprocessing')
    lines=audited_integration_traces(ledger)+implementation_findings(ledger)+['','## Independent reconciliation','',
           f"Accounting and boundary checks accepted: {strict['accepted']}. "
           f"Quality coverage complete: {audit['quality_comparison_complete']}.",
           f"Protected files/links checked: {protection['files']}; unchanged: {protection['unchanged']}.",
           '', '## Repeatability and first-attempt coverage','',
           '| Checkpoint | Policy | Initial success/conclusive | Initial unknown | Latest agreeing task pairs |',
           '| --- | --- | --- | --- | --- |']
    for cp in [6,12,24]:
        for arm in ARMS:
            initial=[];latest=[]
            for cell in evaluation_cells(cp):
                if cell.arm!=arm or cell.mode!='full':continue
                attempts=[r for r in runs.values() if r['cell_key']==cell.key]
                if attempts:
                    attempts.sort(key=lambda r:r['started']);initial.append(attempts[0]);latest.append(attempts[-1])
            conclusive=[r for r in initial if r['status']=='conclusive']
            groups=collections.defaultdict(list)
            for r in latest:
                if r['status']=='conclusive':groups[r['task_id']].append(r['success'])
            pairs=[v for v in groups.values() if len(v)==2]
            lines.append(f'| {cp} | {arm} | {sum(r["success"] for r in conclusive)}/{len(conclusive)} | '
                         f'{sum(r["status"]!="conclusive" for r in initial)} | '
                         f'{sum(v[0]==v[1] for v in pairs)}/{len(pairs)} |')
    lines+=['', 'Full-mode W/L/T compares against baseline at the same checkpoint. '
            'Exposure-removal W/L/T compares against the same policy in full mode; a removal win means '
            'withholding that channel improved the observed task outcome. These are paired observations, '
            'not statistical superiority estimates.']
    lines+=['', 'Tool-exposure reconciliation includes actual schema objects in the fixed upstream '
            'demonstrations and successful documentation observations. Merely requesting a document '
            'does not count as receiving it. The CSV reports calls without a recognized prior schema, '
            'not necessarily incorrect or guessed calls; unrecognized prose is not treated as a full schema. '
            'Original online counters remain in the ledger alongside the source-derived reconciliation.']
    lines+=['','## Learning expense by policy','',
            '| Policy | Main learning requests | Known estimate USD | Discarded smoke requests | Smoke estimate USD |',
            '| --- | --- | --- | --- | --- |']
    for arm in ARMS:
        learning=[];smoke=[]
        for call in calls:
            if call['arm']!=arm:continue
            d=json.loads(call['data']);scope=d.get('scope',{})
            source_run=scope.get('source_run')
            from_smoke='smoke' in (call['phase'] or '') or 'smoke' in runs.get(source_run,{}).get('phase','')
            if from_smoke:smoke.append(call)
            elif call['phase'] in {'learning','selection','post_update','practice'}:learning.append(call)
        lines.append(f'| {arm} | {len(learning)} | {sum(c["estimate"] or 0 for c in learning):.6f} | '
                     f'{len(smoke)} | {sum(c["estimate"] or 0 for c in smoke):.6f} |')
    excluded=ledger.records('excluded_cohort')
    if excluded:
        lines+=['','## Excluded integration cohorts','']
        for row in excluded:
            d=row['data'];lines.append(f'- {d["path"]}: {d["requests"]} SDK requests, '
                f'known estimate ${d["known_estimate_usd"]:.6f}, {d["evaluation_attempts"]} evaluation attempts. '
                'Retained and excluded from this cohort\'s quality results.')
    lines+=['','## Trace index','']
    for cp in [6,12,24]:
        for arm in ARMS:
            eligible=[r for r in runs.values() if r['phase']=='evaluation' and r['arm']==arm
                      and json.loads(r['data'])['cell']['checkpoint']==cp
                      and json.loads(r['data'])['cell']['mode']=='full' and r['status']=='conclusive']
            if eligible:
                r=sorted(eligible,key=lambda r:r['started'])[0];d=json.loads(r['data'])
                trace=Path(d['native_output'])/'tasks'/r['task_id']/'logs/environment_io.md'
                lines.append(f'- {arm}, checkpoint {cp}, task {r["task_id"]}: '
                             f'official success {bool(r["success"])}; [actual actions and observations]({trace}). '
                             f'Run `{r["id"]}` links SDK inputs, selected memory and tool definitions in the ledger.')
    opening=['# Memory architecture task examples and tradeoffs', '',
             'Updated 2026-10-19. GEPA selected, saved, reopened and froze a nonempty '
             'instruction in a separate known-case diagnostic. Two later task attempts '
             'received that instruction and passed. The linked cases explain actual memory and '
             'actions across all five policies. They do not establish a quality ranking. '
             'The broader comparison is incomplete; its coverage, unknown requests and '
             'owned learning-input defect are recorded below.', '',
             f'Postprocessor source SHA-256: `{digest(source)}`.']
    content=(opening+gepa_retention_evidence(ledger)+task_examples(ledger)+
             ['', '## Planned comparison coverage and expense', '']+comparison_text+lines)
    (RESULTS/'REPORT.md').write_text('\n'.join(content)+'\n')
    return {'accounting':audit,'boundaries':strict}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--bundle',action='store_true')
    parser.add_argument('--prepare-boundaries',action='store_true')
    parser.add_argument('--implementation-preview',action='store_true')
    parser.add_argument('--status',action='store_true');args=parser.parse_args()
    if args.implementation_preview:
        # Read only while the serial live worker continues. This is an interim
        # derivation in the same report, superseded by full reconciliation.
        ledger=object.__new__(Ledger)
        ledger.db=sqlite3.connect(f'file:{RESULTS / "ledger.sqlite"}?mode=ro',uri=True)
        ledger.db.row_factory=sqlite3.Row
        try:
            ledger.db.execute('BEGIN')
            rows=ledger.db.execute("SELECT status,count(*) FROM runs WHERE phase='evaluation' GROUP BY status").fetchall()
            coverage={r[0]:r[1] for r in rows}
            lines=['# Memory architecture task examples and tradeoffs', '',
                   'Updated 2026-10-19. This is a source-bound review of observed implementation behavior, '
                   'not the completed growth comparison. The live worker continues separately.', '',
                   f'Evaluation attempts by status: {coverage}. Planned evaluation cells: 448. '
                   'Task-quality conclusions require the reconciled evaluation population.', '',
                   f'Postprocessor source SHA-256: `{digest(Path(__file__).read_text())}`.']
            if not learning_input_audit(ledger)['accepted']:
                lines += ['', '**Integration qualification:** the source audit found standalone '
                          'password observations that survived learning-copy redaction. '
                          'The simulated credentials are not printed here. This owned input '
                          'defect prevents certification of a protocol-conformant quality '
                          'comparison; task actions and outcomes below remain observed evidence.']
            lines+=gepa_retention_evidence(ledger)+task_examples(ledger)+audited_integration_traces(ledger)+implementation_findings(ledger,record=False)
            (RESULTS/'REPORT.md').write_text('\n'.join(lines)+'\n')
            print(f'Interim implementation findings written to {RESULTS / "REPORT.md"}')
        finally:ledger.db.close()
        return
    if args.status:
        with sqlite3.connect(f'file:{RESULTS / "ledger.sqlite"}?mode=ro',uri=True) as db:
            db.row_factory=sqlite3.Row
            print(json.dumps({'runs':[dict(r) for r in db.execute(
                'SELECT phase,arm,status,count(*) AS count,sum(success) AS successes FROM runs GROUP BY phase,arm,status')],
                'requests':[dict(r) for r in db.execute(
                    'SELECT phase,status,count(*) AS count,sum(estimate) AS known_usd FROM calls GROUP BY phase,status')],
                'latest_run':dict(db.execute('SELECT id,phase,arm,task_id,status FROM runs ORDER BY started DESC LIMIT 1').fetchone())},indent=2))
        return
    bind()
    with serial_lock():
        ledger=Ledger()
        try:
            if args.prepare_boundaries:
                prepare_boundaries(ledger);print('Premeasurement task-state and catalogue identities retained.');return
            result=reconcile(ledger)
            if args.bundle:
                # Preserve the exact postprocessor alongside the canonical source record.
                target=RESULTS/'postprocessing.py';target.write_text(Path(__file__).read_text())
                write_json(RESULTS/'documentation.json',{name:(ROOT/'growth'/name).read_text()
                           for name in ['README.md','EXPERIMENT.md','CONTEXT.md']})
                for path in sorted((ROOT/'results').glob('growth-v*/ledger.sqlite')):
                    if path.parent==RESULTS:continue
                    snapshot=RESULTS/f'excluded-{path.parent.name}.sqlite'
                    with sqlite3.connect(f'file:{path}?mode=ro',uri=True) as original:
                        with sqlite3.connect(snapshot) as target_db:original.backup(target_db)
                bundle(ledger)
                for path in RESULTS.glob('excluded-*.sqlite'):path.unlink()
            print(json.dumps(result,indent=2))
        finally:ledger.db.close()


if __name__=='__main__':main()
