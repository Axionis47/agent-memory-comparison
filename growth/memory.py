from __future__ import annotations

import importlib
import json
import sys
from datetime import datetime

from mc import memory as legacy
from mc.core import VENDOR, Inconclusive, digest, dumps, read_json, write_json, monotonic
from mc.provider import OpenAICompatibility
from .runtime import RESULTS, ROOT, settings, flatten, change_set, mark, experience_units


MEM0_FACT_PROMPT=(
    'SOURCE-BOUND FACT EXTRACTION. Extract distinct reusable API observations from the user Input only. '
    'The system prompt and formatting instructions are not source facts. Never extract or restate them. '
    'Use observed API results or documented schemas, retaining relevant conditions. '
    'A failed guessed function or parameter establishes only that specific failure, not that the entire '
    'API lacks a capability. An instruction, grade alone, or redacted authentication result establishes '
    'no reusable API fact. Return an empty facts array for such inputs. '
    'Evaluator and measurement fields (success, passed_requirements, failed_requirements, source_run '
    'and timestamps) are harness metadata, not application API capabilities. Do not extract them as facts. '
    'Do not retain credentials, redaction placeholders, concrete task answers, user-specific identifiers '
    'or unsupported explanations as guidance. Include each distinct supported observation once. '
    'Return one JSON object with facts as an array of plain strings, or {"facts": []}.'
)

GEPA_REFLECTION_TEMPLATE='''Improve a reusable cross-task strategy for the same AppWorld acting agent.
The current task instruction and native agent loop are supplied separately and are not being optimized.
Current reusable strategy:
<curr_param>

Actual task inputs, actions, observations and evaluator feedback:
<side_info>

Propose transferable guidance supported by this experience. Preserve applicability conditions.
Do not rewrite a particular task, copy its names/paths/accounts/answers, invent APIs, or treat
evaluator descriptions as tool observations. An empty strategy is acceptable when no useful change
is supported. The native optimizer will test candidates and decide acceptance.
Return only the new reusable strategy within triple backticks.'''


def ace_inputs(exp, actual_bullets):
    return {'question':exp['instruction'],'reasoning_trace':dumps(exp['steps']),
            'predicted_answer':dumps(exp['answer']),'ground_truth':None,
            'environment_feedback':dumps(exp['feedback']),
            'bullets_used':'\n'.join(actual_bullets) or '(none)',
            'use_ground_truth':False,'use_json_mode':True}


def ace_next_global_id(state,playbook):
    utils=importlib.import_module('playbook_utils')
    return max(state.get('next_global_id',0),utils.get_next_global_id(playbook))


def learning_unit(arm, unit, exp):
    if arm=='mem0' and unit['kind']=='task_feedback':
        # A grade alone establishes no API fact. Supply its actual evidence,
        # rather than asking extraction to infer a lesson from an isolated label.
        return {**unit,'supporting_task_context':{
            'instruction':exp['instruction'],'steps':exp['steps'],'answer':exp['answer'],
            'application_datetime':exp.get('application_datetime')}}
    return unit


def mem0_ingestion_eligible(unit):
    """Validate source provenance, without generating or correcting any facts."""
    if unit['kind']=='task_start':return False
    if unit['kind']=='task_feedback':
        context=unit.get('supporting_task_context') or {}
        if not context.get('steps'):
            raise ValueError('Mem0 feedback requires its actual supporting trajectory')
    elif unit['kind']=='action_observation':
        if not isinstance(unit.get('inputs'),list) or not isinstance(unit.get('outputs'),list):
            raise ValueError('Mem0 learning requires actual action/observation arrays')
    else:raise ValueError('Unknown Mem0 experience unit')
    return True


class Memory(legacy.MemoryPolicy):
    def _mem0(self):
        native=super()._mem0()
        native.config.custom_fact_extraction_prompt=MEM0_FACT_PROMPT
        native.custom_fact_extraction_prompt=MEM0_FACT_PROMPT
        return native

    def __init__(self, arm, vertex, namespace=None):
        super().__init__(arm,vertex,namespace)
        self.lineage_path=self.directory/'lineage.json'
        self.lineage=read_json(self.lineage_path) if self.lineage_path.exists() else {}
        self._hits={};self._selecting=False
        # Canonical empty native stores precede the first acting-state snapshot.
        # Creating an index is infrastructure initialization, not learned content.
        if arm in {'mem0','recmem'} and not self.path.exists():
            if arm=='mem0':self._mem0()
            else:self._recmem()
            self.save(self.export())

    def select(self, query):
        if self.arm!='recmem': return super().select(query)
        native=self._recmem();self._hits={};self._selecting=True
        try:
            result=native.search_memories(query,'MC01')
        finally: self._selecting=False
        selected=[]
        for layer,entries in [('episodic',result.episodic),('semantic',result.semantic),('raw',result.subconscious)]:
            hits=self._hits.get(layer,[])
            if layer=='semantic':hits=[h for h in hits if h.score>native.semantic_memory_threshold]
            if len(hits)!=len(entries): raise Inconclusive('RecMem native identity/result lengths differ')
            for rank,(hit,(content,score)) in enumerate(zip(hits,entries)):
                if hit.content!=content or hit.score!=score:
                    raise Inconclusive('RecMem native identity/result order differs')
                selected.append({'id':str(hit.id),'layer':layer,'content':content,'score':score,'rank':rank+1})
        return selected

    def _recmem(self):
        fresh=self.native is None
        native=super()._recmem()
        if fresh:
            for name,value in settings().recmem.items(): setattr(native,name,value)
            native.gating_raw_topk=native.min_consolidation_cnt*2
            for layer,store in [('raw',native.subconscious_memory.vec_store),
                                ('episodic',native.episodic_mem.vec_store),('semantic',native.semantic_memory.vec_store)]:
                original=store.search
                def capture(*args,_layer=layer,_fn=original,**kwargs):
                    hits=_fn(*args,**kwargs)
                    if self._selecting: self._hits[_layer]=hits
                    return hits
                store.search=capture
        return native

    def save(self, state):
        self.state=state
        write_json(self.path,state)

    def observe(self, experience, sequence):
        if getattr(self,'read_only',False): raise ValueError('Frozen evaluation memory cannot learn')
        key=digest({'arm':self.arm,'source_run':experience['run_id'],'sequence':sequence})
        previous=[r for r in self.vertex.ledger.records('learning_complete') if r['data']['key']==key]
        if previous: return
        before=self.export();started=monotonic()
        mark(self.vertex.ledger,'learning_started',{'key':key,'sequence':sequence,'before':before,
             'source_run':experience['run_id']},self.arm,'learning')
        call_start=self.vertex.ledger.db.execute('SELECT coalesce(max(rowid),0) FROM calls').fetchone()[0]
        with self.vertex.scoped(arm=self.arm,phase='learning',source_run=experience['run_id'],sequence=sequence):
            if self.arm in {'mem0','recmem'}: self._observe_arrivals(experience,key)
            elif self.arm=='ace': self._observe_ace(experience,sequence)
            elif self.arm=='baseline': self.save(self.state)
            # Trace2Skill evolves the six-task pool later. GEPA uses checkpoint optimisation.
        if self.vertex.ledger.db.execute("SELECT count(*) FROM calls WHERE rowid>? AND status!='live'",(call_start,)).fetchone()[0]:
            raise Inconclusive('Native learning swallowed an interrupted provider call')
        after=self.export();self.save(after)
        self._record_change(before,after,[experience['run_id']],sequence)
        mark(self.vertex.ledger,'learning_complete',{'key':key,'sequence':sequence,
             'source_run':experience['run_id'],'version':self.version,'duration_s':monotonic()-started},self.arm,'learning')

    def _observe_arrivals(self, exp, key):
        for source_unit in experience_units(exp):
            unit=learning_unit(self.arm,source_unit,exp)
            unit_key=digest({'learning':key,'unit':unit})
            done=[r for r in self.vertex.ledger.records('arrival_complete') if r['data']['key']==unit_key]
            if done: continue
            if self.arm=='mem0' and not mem0_ingestion_eligible(unit):
                # This records an ingestion decision, never a synthetic LLM or
                # native reconciliation response. The goal still enters context.
                mark(self.vertex.ledger,'arrival_complete',{'key':unit_key,'source_run':exp['run_id'],
                    'unit_hash':digest(unit),'ingestion':'metadata-only, no extraction requested',
                    'reason':'Task request alone contains no observed application behavior'},self.arm,'learning')
                continue
            pending=[r for r in self.vertex.ledger.records('arrival_started') if r['data']['key']==unit_key]
            before=self.export()
            if pending and pending[-1]['data']['before_hash']!=digest(before):
                raise Inconclusive('Uncommitted native arrival changed persistent memory; requires reconciliation')
            mark(self.vertex.ledger,'arrival_started',{'key':unit_key,'before_hash':digest(before),
                 'source_run':exp['run_id']},self.arm,'learning')
            call_start=self.vertex.ledger.db.execute('SELECT coalesce(max(rowid),0) FROM calls').fetchone()[0]
            with self.vertex.scoped(source_step=unit.get('number'),unit_kind=unit['kind'],unit_hash=digest(unit)):
                if self.arm=='mem0':
                    result=self._mem0().add([{'role':'user','content':dumps(unit)}],user_id='MC01',
                         metadata={'source_run':exp['run_id'],'unit_hash':digest(unit)})
                else:
                    self._recmem().add_memory(dumps(unit),
                        datetime.fromisoformat(unit['application_datetime']).isoformat(),'MC01')
                    result=None
            bad=self.vertex.ledger.db.execute("SELECT count(*) FROM calls WHERE rowid>? AND status!='live'",(call_start,)).fetchone()[0]
            if bad: raise Inconclusive('Native component swallowed a failed provider call; arrival not committed')
            after=self.export();self.save(after)
            self._record_change(before,after,[exp['run_id']],self.vertex.scope.get('sequence'))
            mark(self.vertex.ledger,'arrival_complete',{'key':unit_key,'result':result,'after_hash':digest(after),
                 'source_run':exp['run_id'],'unit_hash':digest(unit)},self.arm,'learning')

    def _observe_ace(self, exp, sequence):
        import numpy as np
        sys.path.insert(0,str(VENDOR/'ace'))
        reflector_mod=importlib.import_module('ace.core.reflector')
        curator_mod=importlib.import_module('ace.core.curator')
        analyzer_mod=importlib.import_module('ace.core.bulletpoint_analyzer')
        utils=importlib.import_module('playbook_utils')
        ace_class=importlib.import_module('ace.ace').ACE
        def bridge(client,provider,model,prompt,role,call_id,**kwargs):
            d=self.vertex.generate([{'role':'user','content':prompt}],
                json_mode=kwargs.get('use_json_mode',False),purpose=f'ace-{role}')
            return d['output'],{'call_id':d['call_id'],'duration_s':d['duration_s']}
        reflector_mod.timed_llm_call=curator_mod.timed_llm_call=bridge
        curator_mod.log_curator_operation_diff=lambda parent,op,before,call_id:self.event(
            'ace_operation_detail',{'proposal':op,'before':before,'call_id':call_id})
        curator_mod.log_curator_failure=lambda *args:self.event('ace_rejection',{'details':args})
        playbook=self.state.get('text') or ace_class._initialize_empty_playbook(None)
        exposed=set(exp['exposed_ids'])
        actual_bullets=[line for line in playbook.splitlines()
                       if (p:=utils.parse_playbook_line(line)) and p['id'] in exposed]
        # Unlike the pilot, answer and feedback have distinct, correct meanings.
        reflection,tags,_=reflector_mod.Reflector(None,'mc_vertex',settings().model).reflect(**ace_inputs(exp,actual_bullets))
        admitted=[t for t in tags if (t.get('id') or t.get('bullet')) in exposed]
        playbook=utils.update_bullet_counts(playbook,admitted)
        playbook,next_id,operations,_=curator_mod.Curator(None,'mc_vertex',settings().model).curate(
            playbook,reflection,exp['instruction'],sequence,24,settings().memory_tokens,
            utils.get_playbook_stats(playbook),use_ground_truth=False,use_json_mode=True,
            next_global_id=ace_next_global_id(self.state,playbook),
            log_dir=str(self.directory))
        vertex=self.vertex
        class Analyzer(analyzer_mod.BulletpointAnalyzer):
            def _compute_embeddings(self,bullets):
                values=np.asarray(vertex.embed([b['content'] for b in bullets]),dtype=np.float64)
                norm=np.linalg.norm(values,axis=1,keepdims=True)
                return values/np.maximum(norm,1e-12)
            def _find_similar_groups(self,bullets,embeddings,threshold):
                groups=super()._find_similar_groups(bullets,embeddings,threshold)
                self_groups=[{'ids':[b['id'] for b in g['bullets']]} for g in groups]
                vertex.ledger.record('ace_similarity_groups',{'groups':self_groups,'threshold':threshold},
                    arm='ace',phase='learning')
                return groups
        # Availability now refers to the injected, real SDK embedding backend.
        # Native grouping/reconstruction/LLM merge remain unchanged; no local model is simulated.
        analyzer_mod.DEDUP_AVAILABLE=True
        before_analysis=playbook
        playbook=Analyzer(OpenAICompatibility(vertex),settings().model).analyze(
            playbook,threshold=settings().ace_similarity,merge=True)
        self.event('ace_delta',{'reflection':reflection,'answer_supplied':exp['answer'],
            'feedback_supplied':exp['feedback'],'proposed_tags':tags,'accepted_tags':admitted,
            'exposed_ids':sorted(exposed),'operations':operations,'before_analysis':before_analysis,
            'after_analysis':playbook,'source_run':exp['run_id']})
        self.save({'arm':self.arm,'text':playbook,'next_global_id':next_id,
                   'entries':[p for line in playbook.splitlines()
                   if (p:=utils.parse_playbook_line(line))]})

    def evolve_skill(self, corpus, sequence):
        marker=f'skill-{sequence}'
        if self._completed(marker): return
        before=self.export()
        # The released map/reduce/apply engine reads the existing skill folder.
        sys.path.insert(0,str(VENDOR/'trace2skill'))
        from skill_evolver.parallel_evolving_agent import ParallelSkillEvolver
        engine_module=importlib.import_module('skill_evolver.skill_evolving_agent')
        validator=ROOT/settings().structural_validator['path']
        if digest(validator.read_bytes())!=settings().structural_validator['sha256']:
            raise Inconclusive('Skill structural-validator identity changed')
        # This is a documented compatibility dependency for the native hook,
        # not an author-supplied behavioral evaluator or a substitute for one.
        engine_module.QUICK_VALIDATE_SCRIPT=validator
        folder=self.directory/'skill';folder.mkdir(exist_ok=True)
        if not (folder/'SKILL.md').exists():
            (folder/'SKILL.md').write_text('---\nname: appworld\ndescription: Learned AppWorld procedures\n---\n\n# Procedures\n')
        records=[]
        for exp in corpus:
            text=self.vertex.text('Use only observable source evidence. Return JSON '
                '{"instance_id":"...","items":[{"type":"failure_cause" or "failure_memory" or '
                '"success_memory","title":"...","description":"...","content":"reusable finding"}]}. '
                'Do not invent causes, retain authentication values or turn task-specific answers into rules. '
                'Experience:\n'+dumps(exp),json_mode=True,purpose='trace-analysis')
            record=json.loads(text);records.append(record)
            self.event('skill_trace_analysis',{'source_run':exp['run_id'],'analysis':record})
        vertex=self.vertex
        class Client:
            def chat(self,messages,settings=None):
                return vertex.generate([{'role':m.role,'content':m.content} for m in messages],
                                        purpose='trace2skill-map-reduce')['output']
        evolver=ParallelSkillEvolver(Client(),folder,max_workers=1,batch_size=1,merge_batch_size=5,
            temperature=0,max_tokens=settings().max_output_tokens,verbose=False,prompt_variant='generic',
            output_dir=None,max_verification_rounds=1)
        native_validate=evolver._evolver.validate_skill
        def observed_validation():
            valid,message=native_validate()
            self.event('skill_structure_validation',{'valid':valid,'message':message,
                'validator_hash':settings().structural_validator['sha256'],
                'scope':'structure only, not behavioral correctness'})
            return valid,message
        evolver._evolver.validate_skill=observed_validation
        result=evolver.run(records)
        self.event('skill_evolution',result)
        files={}
        for path in sorted(folder.rglob('*')):
            if not path.is_file():continue
            try:files[str(path.relative_to(folder))]=path.read_text()
            except UnicodeDecodeError as exc:
                raise Inconclusive('Generated binary skill artifact cannot be exposed as agent text') from exc
        self.save({'arm':self.arm,'files':files,'text':'\n\n'.join(files.values()),
                   'entries':[{'id':k,'content':v} for k,v in files.items()]})
        self._record_change(before,self.export(),[e['run_id'] for e in corpus],sequence)
        self._complete(marker)

    def optimize(self, corpus, sequence, solve_selection, selection_population=None, metric_target=None):
        marker=f'gepa-{sequence}'
        if self._completed(marker):return
        import gepa
        from gepa.core.adapter import EvaluationBatch
        from .runtime import population
        owner=self
        class Adapter:
            propose_new_texts=None
            def evaluate(self,batch,candidate,capture_traces=False):
                runs=[solve_selection(t,candidate['strategy']) for t in batch]
                if any(r['status']!='conclusive' for r in runs):
                    raise Inconclusive('GEPA candidate rollout inconclusive')
                traces=[]
                for r in runs:
                    from .runtime import experience
                    traces.append(experience(r,owner.vertex.ledger))
                owner.event('gepa_candidate_evaluation',{'candidate':candidate,'tasks':batch,
                    'run_ids':[r['id'] for r in runs],'scores':[float(r['success']) for r in runs]})
                return EvaluationBatch(outputs=[r['id'] for r in runs],scores=[float(r['success']) for r in runs],
                                       trajectories=traces if capture_traces else None)
            def make_reflective_dataset(self,candidate,eval_batch,components_to_update):
                return {'strategy':[{'Inputs':{'task_instruction':trajectory['instruction'],
                                              'practice_experience':corpus},
                    'Generated Outputs':{'answer':trajectory['answer'],'steps':trajectory['steps']},
                    'Feedback':{'score':score,'diagnostic_feedback':trajectory['feedback']}}
                    for trajectory,score in zip(eval_batch.trajectories,eval_batch.scores,strict=True)]}
        def reflection(messages):
            if isinstance(messages,str):messages=[{'role':'user','content':messages}]
            return owner.vertex.generate(messages,purpose='gepa-reflection')['output']
        before=self.export()
        selected=selection_population or population()
        result=gepa.optimize(seed_candidate={'strategy':self.state.get('text','')},
            trainset=selected['selection_train'],valset=selected['selection_validation'],
            adapter=Adapter(),reflection_lm=reflection,max_metric_calls=metric_target or settings().gepa_metric_calls,
            reflection_minibatch_size=1,use_merge=True,merge_val_overlap_floor=1,
            reflection_prompt_template=GEPA_REFLECTION_TEMPLATE,
            display_progress_bar=False,cache_evaluation=False,seed=0,skip_perfect_score=False,
            raise_on_exception=True,run_dir=str(self.directory/f'optimizer-{sequence}'))
        state=result.to_dict() if hasattr(result,'to_dict') else vars(result)
        text=result.best_candidate['strategy']
        self.save({'arm':self.arm,'text':text,'entries':[{'id':'strategy','content':text}] if text else [],
                   'optimizer_result':json.loads(dumps(state))})
        self.event('gepa_frontier',state)
        self._record_change(before,self.export(),[e['run_id'] for e in corpus],sequence)
        self._complete(marker)

    def _completed(self,marker):
        return any(r['data']['marker']==marker and r['data'].get('namespace')==self.directory.name
                   for r in self.vertex.ledger.records('evolution_complete') if r['arm']==self.arm)

    def _complete(self,marker):
        mark(self.vertex.ledger,'evolution_complete',{'marker':marker,'version':self.version,
             'namespace':self.directory.name},self.arm,'learning')

    def _record_change(self,before,after,sources,sequence):
        changes=change_set(before,after)
        # Native mutations may read previous memory. This is conservative
        # operation-input ancestry, explicitly not claim-level proof of support.
        ancestry=set(sources)
        for item in changes['removed']+[v['before'] for v in changes['updated']]:
            ancestry.update(self.lineage.get(item['id'],[]))
        if self.arm in {'ace','trace2skill','gepa','recmem'}:
            ancestry.update(x for values in self.lineage.values() for x in values)
        for item in changes['added']+[v['after'] for v in changes['updated']]:
            self.lineage[item['id']]=sorted(ancestry|set(self.lineage.get(item['id'],[])))
        write_json(self.lineage_path,self.lineage)
        mark(self.vertex.ledger,'consolidation',{'sequence':sequence,'changes':changes,
            'before_version':digest(before),'after_version':digest(after),'source_runs':sorted(ancestry),
            'lineage_semantics':'conservative operation-input ancestry, not claim-specific attribution',
            'before_entries':len(flatten(before)),'after_entries':len(flatten(after)),
            'before_bytes':sum(len(x['content'].encode()) for x in flatten(before)),
            'after_bytes':sum(len(x['content'].encode()) for x in flatten(after))},self.arm,'learning')

    def checkpoint(self,sequence):
        import shutil
        state=self.export();self.save(state)
        path=RESULTS/'checkpoints'/str(sequence)/f'{self.arm}.json'
        frozen=RESULTS/'memories'/f'frozen-{sequence}-{self.arm}'
        packet={'arm':self.arm,'checkpoint':sequence,'version':self.version,'artifact':state,
                'lineage':self.lineage,'entry_count':len(flatten(state)),
                'content_bytes':sum(len(x['content'].encode()) for x in flatten(state)),
                'native_namespace':f'frozen-{sequence}-{self.arm}'}
        if path.exists() and read_json(path)!=packet:
            raise Inconclusive('Immutable checkpoint already exists with different content')
        self.close();self.native=None
        if not frozen.exists():
            # Native memory versions, not copied project/report/archive trees.
            # Closing first checkpoints SQLite/WAL and releases local Qdrant locks.
            shutil.copytree(self.directory,frozen,ignore=shutil.ignore_patterns('optimizer-*','.lock'))
        write_json(path,packet)
        return packet
