from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from .core import VENDOR, RESULTS, Inconclusive, digest, dumps, protocol, read_json, write_json

_vertex = None


def experience_units(corpus):
    """Actual start/actions/feedback, without repeating task labels to force recurrence."""
    for exp in corpus:
        first=exp['steps'][0]['observed_at_epoch']
        yield {'kind':'task_start','source_run':exp['run_id'],'task_id':exp['task_id'],
               'instruction':exp['instruction'],'observed_at_epoch':first}
        for step in exp['steps']:
            yield {'kind':'action_observation','source_run':exp['run_id'],**step}
        yield {'kind':'task_feedback','source_run':exp['run_id'],'feedback':exp['feedback'],
               'observed_at_epoch':exp['steps'][-1]['observed_at_epoch']}


class Mem0VertexLLM:
    def __init__(self, config=None):
        self.config = config

    def generate_response(self, messages, response_format=None, tools=None, **kwargs):
        if tools:
            raise Inconclusive('Mem0 requested unsupported function-calling transport')
        return _vertex.generate(messages, json_mode=bool(response_format), purpose='mem0-learning')['output']


class Mem0VertexEmbedding:
    def __init__(self, config=None):
        self.config = config

    def embed(self, text, memory_action=None):
        return _vertex.embed([text])[0]

    def embed_batch(self, texts, memory_action=None):
        return [self.embed(t, memory_action) for t in texts]


class MemoryPolicy:
    def __init__(self, arm, vertex, namespace=None):
        global _vertex
        _vertex = vertex
        self.arm, self.vertex = arm, vertex
        self.directory = RESULTS / 'memories' / (namespace or arm)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / 'artifact.json'
        self.state = read_json(self.path) if self.path.exists() else {'arm': arm, 'text': '', 'entries': []}
        self.native = None

    @property
    def version(self):
        return digest(self.state)

    def event(self, operation, data):
        self.vertex.ledger.record('memory_event', {'operation': operation, **data},
            self.vertex.scope.get('run_id'), self.arm, self.vertex.scope.get('phase'))

    def commit(self, state):
        before = self.state
        self.state = state
        write_json(self.path, state)
        self.event('commit', {'before': before, 'after': state, 'version': self.version})

    def _mem0(self):
        if self.native is not None:
            return self.native
        from mem0 import Memory
        from mem0.utils.factory import LlmFactory, EmbedderFactory
        # Mem0 1.0.0's config validators have a fixed provider allowlist even though
        # its factories permit registration. Register under accepted Google names.
        LlmFactory.register_provider('gemini', 'mc.memory.Mem0VertexLLM')
        EmbedderFactory.provider_to_class['vertexai'] = 'mc.memory.Mem0VertexEmbedding'
        self.native = Memory.from_config({
            'version': 'v1.1',
            'llm': {'provider': 'gemini', 'config': {'model': protocol().model, 'temperature': 0}},
            'embedder': {'provider': 'vertexai', 'config': {'model': protocol().embedding_model,
                        'embedding_dims': protocol().embedding_dimension}},
            'vector_store': {'provider': 'qdrant', 'config': {
                'path': str(self.directory/'qdrant'), 'collection_name': 'MC01',
                'embedding_model_dims': protocol().embedding_dimension,'on_disk':True}},
            'history_db_path': str(self.directory/'history.sqlite'),
            'custom_fact_extraction_prompt': (
                'Extract reusable factual observations about API behavior and task execution from this '
                'training experience. A task request alone establishes no fact about API behavior. '
                'Use actual observations or execution constraints established by feedback. '
                'Do not retain task goals, account credentials, current balances, concrete '
                'task answers or user-specific record identifiers as general guidance. '
                'Return exactly {"facts": ["fact as a plain string", "another plain string"]}. '
                'Every facts entry MUST be a string, never an object. Return {"facts": []} '
                'if no reusable factual observation is established. The user message contains the experience.')})
        return self.native

    def _recmem(self):
        if self.native is not None:
            return self.native
        sys.path.insert(0, str(VENDOR/'recmem'))
        from recmem.rec_mem import RecMem, RecMemConfig
        from recmem.embedding.base import Embedding
        from recmem.llm.base import LLMClient, LLMResponse
        from recmem.vector_store.qdrant import QdrantStore
        vertex = self.vertex
        class Embedder(Embedding):
            @property
            def dim(self):
                return protocol().embedding_dimension
            def embed(self, text):
                return vertex.embed([text])[0]
            def embed_batch(self, texts):
                return [self.embed(t) for t in texts]
        class Client(LLMClient):
            def chat_completion(self, *, messages, json_mode=False, **kwargs):
                data = vertex.generate([{'role': m.role, 'content': m.content} for m in messages],
                                       json_mode=json_mode, purpose='recmem-learning')
                return LLMResponse(content=data['output'], finish_reason='stop', usage=None)
        def factory(layer, path):
            return QdrantStore(embedding_dim=protocol().embedding_dimension,
                               path=str(self.directory/layer), exact_search=True)
        config = RecMemConfig(min_consolidation_cnt=5, min_relevant_score=0.7,
            merge_with_epi_thresh=0.7, retrieve_raw_topk=10, retrieve_epi_topk=5,
            semantic_memory_topk=10, semantic_memory_threshold=0,
            semantic_store=str(self.directory/'semantic'), subconscious_store=str(self.directory/'subconscious'),
            episodic_store=str(self.directory/'episodic'))
        self.native = RecMem(config, embedder=Embedder(), llm_client=Client(), vector_store_factory=factory)
        search = self.native.subconscious_memory.search
        def observed_gate(**kwargs):
            hits = search(**kwargs)
            self.event('recurrence_gate', {'hits':[{'id':h.id, 'score':h.score} for h in hits],
                'threshold':self.native.min_relevant_score,
                'relevant_count':1+sum(h.score>self.native.min_relevant_score for h in hits),
                'required_count':self.native.min_consolidation_cnt})
            return hits
        self.native.subconscious_memory.search = observed_gate
        merge = self.native.episodic_mem.try_merge_new_memory
        def observed_merge(**kwargs):
            result = merge(**kwargs)
            self.event('episode_merge_decision', {'merged':result[0], 'episode':result[1]})
            return result
        self.native.episodic_mem.try_merge_new_memory = observed_merge
        for method in ['_consolidate_memory', 'generate_semantic_memories']:
            original = getattr(self.native, method)
            def observed(*args, _method=method, _fn=original, **kwargs):
                self.event(_method, {'args': args, 'kwargs': kwargs})
                return _fn(*args, **kwargs)
            setattr(self.native, method, observed)
        return self.native

    def export(self):
        if self.arm == 'mem0' and (self.directory/'qdrant').exists():
            m = self._mem0()
            rows = m.get_all(user_id='MC01', limit=100000)['results']
            return {'arm': self.arm, 'entries': sorted(rows, key=lambda x:x['id'])}
        if self.arm == 'recmem' and (self.directory/'subconscious').exists():
            m = self._recmem()
            layers = {}
            for name, store in [('raw',m.subconscious_memory.vec_store),
                                ('episodic',m.episodic_mem.vec_store),
                                ('semantic',m.semantic_memory.vec_store)]:
                entries = []
                for collection in store.client.get_collections().collections:
                    # Qdrant's in-memory cosine normalization may change float
                    # representation after reopen. Hash its persisted originals.
                    persisted=store.client._client.collections[collection.name].storage
                    vector_hashes={str(p.id):digest(p.vector) for p in persisted.load()}
                    offset = None
                    while True:
                        points, offset = store.client.scroll(collection.name, limit=1000,
                            offset=offset, with_payload=True, with_vectors=True)
                        entries.extend({'id': str(p.id), 'payload': p.payload,
                                        'vector_hash':vector_hashes[str(p.id)]} for p in points)
                        if offset is None:
                            break
                layers[name] = sorted(entries, key=lambda x:x['id'])
            return {'arm': self.arm, 'layers': layers}
        return self.state

    def learn(self, corpus, solve_selection=None):
        if (self.directory/'frozen.json').exists():
            raise ValueError('Frozen memory cannot learn')
        if self.path.exists():
            raise ValueError('Existing construction is not silently overwritten')
        if self.arm == 'baseline':
            self.commit(self.state)
        elif self.arm == 'ace':
            self._learn_ace(corpus)
        elif self.arm == 'mem0':
            native = self._mem0()
            for unit in experience_units(corpus):
                before=self.export()
                with self.vertex.scoped(source_run=unit['source_run'],source_step=unit.get('number'),unit_kind=unit['kind']):
                    result=native.add([{'role':'user','content':dumps(unit)}],user_id='MC01',
                                      metadata={'source_run':unit['source_run'],'unit_hash':digest(unit)})
                self.event('mem0_add',{'source_run':unit['source_run'],'unit_hash':digest(unit),
                    'result':result,'before':before,'after':self.export()})
            self.commit(self.export())
        elif self.arm == 'recmem':
            from datetime import datetime, timezone
            native = self._recmem()
            # Checkpoint actual native state, not generated/replayed model answers.
            records=[r for r in self.vertex.ledger.records('memory_event')
                     if r['arm']==self.arm and r['phase']=='learning']
            checkpoints=[r for r in records if r['data']['operation']=='arrival_checkpoint']
            completed=set(u for r in checkpoints for u in r['data']['units'])
            if checkpoints:
                if self.export()!=checkpoints[-1]['data']['after']:
                    raise Inconclusive('Native RecMem state differs from last committed checkpoint')
            elif records:
                # Migrate the initial interrupted integration: retain only arrivals
                # before the first failed request, and verify the persisted state.
                failed=self.vertex.ledger.db.execute("SELECT min(started) FROM calls WHERE arm='recmem' AND status!='live'").fetchone()[0]
                arrivals=[r for r in records if r['data']['operation']=='recmem_arrival'
                          and (failed is None or r['created']<failed)]
                if arrivals:
                    current=self.export()
                    previous=arrivals[-1]['data']['after']
                    without_vectors=lambda state: {name:[{'id':x['id'],'payload':x['payload']} for x in values]
                                                   for name,values in state['layers'].items()}
                    known=set()
                    for row in self.vertex.ledger.db.execute("SELECT id,data FROM calls WHERE arm='recmem' AND kind='embedding' AND status='live'"):
                        packet=json.loads(row['data'])
                        known.update(zip(packet['texts'],packet['embedding_hashes']))
                    if without_vectors(current)!=without_vectors(previous) or not all(
                            (x['payload']['text'],x['vector_hash']) in known
                            for layer in current['layers'].values() for x in layer):
                        raise Inconclusive('Cannot safely resume partial RecMem construction')
                    self.event('vector_identity_migration',{'old':previous,'after':current,
                        'reason':'Persisted vector originals verified against fresh embedding request hashes',
                        'classification':'not-a-model'})
                    completed={r['data']['unit_hash'] for r in arrivals}
                    self.event('arrival_checkpoint',{'units':sorted(completed),'after':self.export(),
                        'source_event_ids':[r['id'] for r in arrivals],'classification':'not-a-model'})
            for unit in experience_units(corpus):
                if digest(unit) in completed:
                    continue
                before=self.export()
                timestamp=datetime.fromtimestamp(unit['observed_at_epoch'],timezone.utc).isoformat()
                call_start=self.vertex.ledger.db.execute('SELECT coalesce(max(rowid),0) FROM calls').fetchone()[0]
                with self.vertex.scoped(source_run=unit['source_run'],unit_kind=unit['kind'],source_unit_hash=digest(unit)):
                    native.add_memory(message=dumps(unit),timestamp=timestamp,conv_id='MC01')
                if self.vertex.ledger.db.execute("SELECT count(*) FROM calls WHERE rowid>? AND status!='live'",(call_start,)).fetchone()[0]:
                    raise Inconclusive('RecMem swallowed a supporting request failure; checkpoint not advanced')
                self.event('recmem_arrival',{'source_run':unit['source_run'],'unit_hash':digest(unit),
                    'before':before,'after':self.export()})
                self.event('arrival_checkpoint',{'units':[digest(unit)],'after':self.export(),
                                                'classification':'not-a-model'})
            self.commit(self.export())
        elif self.arm == 'trace2skill':
            self._learn_skill(corpus)
        elif self.arm == 'gepa':
            self._learn_gepa(corpus, solve_selection)
        else:
            raise ValueError(self.arm)

    def _learn_ace(self, corpus):
        sys.path.insert(0, str(VENDOR/'ace'))
        reflector_mod = importlib.import_module('ace.core.reflector')
        curator_mod = importlib.import_module('ace.core.curator')
        utils = importlib.import_module('playbook_utils')
        ace_class=importlib.import_module('ace.ace').ACE
        def bridge(client, provider, model, prompt, role, call_id, **kwargs):
            data = self.vertex.generate([{'role':'user','content':prompt}],
                json_mode=kwargs.get('use_json_mode',False), purpose=f'ace-{role}')
            return data['output'], {'call_id':data['call_id'], 'duration_s':data['duration_s']}
        reflector_mod.timed_llm_call = bridge
        curator_mod.timed_llm_call = bridge
        curator_mod.log_curator_operation_diff=lambda parent,op,before,call_id: self.event(
            'ace_operation_detail',{'operation_proposal':op,'before':before,'call_id':call_id})
        curator_mod.log_curator_failure=lambda path,step,kind,response,epoch,*details: self.event(
            'ace_rejected_operation',{'step':step,'failure_type':kind,'response':response,'details':details})
        reflector = reflector_mod.Reflector(None, 'mc_vertex', protocol().model)
        curator = curator_mod.Curator(None, 'mc_vertex', protocol().model)
        playbook, next_id = ace_class._initialize_empty_playbook(None), 1
        for i, experience in enumerate(corpus):
            reflection, tags, info = reflector.reflect(experience['instruction'], dumps(experience['steps']),
                dumps(experience['feedback']), None, dumps(experience['feedback']),
                'No playbook bullets were exposed: this is a shared baseline trajectory.',
                use_ground_truth=False, use_json_mode=True)
            # Shared traces came from the baseline. Counterfactual helpfulness
            # labels cannot become usage counters for unexposed playbook bullets.
            accepted_tags=[]
            playbook = utils.update_bullet_counts(playbook, accepted_tags)
            before = playbook
            playbook, next_id, operations, _ = curator.curate(playbook, reflection,
                experience['instruction'], i+1, len(corpus), protocol().memory_tokens,
                utils.get_playbook_stats(playbook), use_ground_truth=False, use_json_mode=True,
                next_global_id=next_id,log_dir=str(self.directory))
            self.event('ace_delta', {'source_run':experience['run_id'], 'reflection':reflection,
                'proposed_tags':tags, 'accepted_tags':accepted_tags,
                'tag_admission_reason':'shared baseline had no playbook exposure',
                'operations':operations, 'before':before, 'after':playbook})
        self.commit({'arm':self.arm, 'text':playbook, 'entries':[
            utils.parse_playbook_line(line) for line in playbook.splitlines()
            if utils.parse_playbook_line(line)]})

    def _learn_skill(self, corpus):
        sys.path.insert(0, str(VENDOR/'trace2skill'))
        from skill_evolver.parallel_evolving_agent import ParallelSkillEvolver
        skill_dir = self.directory/'skill'
        skill_dir.mkdir(exist_ok=True)
        (skill_dir/'SKILL.md').write_text('---\nname: appworld\ndescription: Learned AppWorld procedures\n---\n\n# Procedures\n')
        records = []
        for exp in corpus:
            prompt = ('Analyze this actual AppWorld attempt using only its observable actions and official feedback. '
                'Return JSON {"instance_id": "...", "items": [{"type": "failure_cause" or '
                '"failure_memory" or "success_memory", "title": "...", "description": "...", '
                '"content": "concise evidence-backed reusable finding"}]}. Do not invent causes or task solutions. '
                'Do not retain credentials, current balances or concrete task answers. Experience:\n'+dumps(exp))
            record = json.loads(self.vertex.text(prompt, json_mode=True, purpose='trace-analysis'))
            records.append(record)
            self.event('skill_trace_analysis', {'source_run':exp['run_id'], 'analysis':record})
        vertex = self.vertex
        class Client:
            def chat(self, messages, settings=None):
                return vertex.generate([{'role':m.role,'content':m.content} for m in messages],
                                       purpose='trace2skill-map-reduce')['output']
        engine = ParallelSkillEvolver(Client(), skill_dir, max_workers=1, batch_size=1,
            merge_batch_size=5, temperature=0, max_tokens=protocol().max_output_tokens,
            verbose=False, prompt_variant='generic', output_dir=None, max_verification_rounds=1)
        result = engine.run(records)
        self.event('skill_evolution', result)
        files = {str(p.relative_to(skill_dir)):p.read_text() for p in sorted(skill_dir.rglob('*.md'))}
        self.commit({'arm':self.arm, 'files':files, 'text':'\n\n'.join(files.values()),
                     'entries':[{'id':k,'content':v} for k,v in files.items()]})

    def _learn_gepa(self, corpus, solve_selection):
        import gepa
        from gepa.core.adapter import EvaluationBatch
        from .core import CACHE
        selection = read_json(CACHE/'population.json')['selection']
        owner = self
        class Adapter:
            propose_new_texts = None
            def evaluate(self, batch, candidate, capture_traces=False):
                outputs, scores, traces = [], [], []
                for task in batch:
                    result = solve_selection(task, candidate['strategy'])
                    if result['status'] != 'conclusive':
                        raise Inconclusive('GEPA selection rollout is inconclusive')
                    outputs.append(result['id'])
                    scores.append(float(result['success']))
                    traces.append(json.loads(result['data']))
                owner.event('gepa_candidate_evaluation', {'candidate':candidate, 'tasks':batch,
                    'scores':scores, 'run_ids':outputs})
                return EvaluationBatch(outputs=outputs, scores=scores,
                                       trajectories=traces if capture_traces else None)
            def make_reflective_dataset(self, candidate, eval_batch, components_to_update):
                return {'strategy':[{'Inputs':corpus, 'Generated Outputs':eval_batch.trajectories,
                                     'Feedback':eval_batch.scores}]}
        def reflection(messages):
            if isinstance(messages, str):
                messages=[{'role':'user','content':messages}]
            return self.vertex.generate(messages, purpose='gepa-reflection')['output']
        result = gepa.optimize(seed_candidate={'strategy':''}, trainset=selection, valset=selection,
            adapter=Adapter(), reflection_lm=reflection, max_metric_calls=protocol().gepa_metric_calls,
            reflection_minibatch_size=1, use_merge=True, merge_val_overlap_floor=1,
            display_progress_bar=False, cache_evaluation=False, seed=0,
            skip_perfect_score=False, raise_on_exception=True,run_dir=str(self.directory/'optimizer'))
        state = result.to_dict() if hasattr(result,'to_dict') else vars(result)
        self.event('gepa_frontier', state)
        instruction = result.best_candidate['strategy']
        self.commit({'arm':self.arm, 'text':instruction,
                     'entries':[{'id':'strategy', 'content':instruction}] if instruction else [],
                     'optimizer_result':json.loads(dumps(state))})

    def select(self, query):
        if self.arm == 'baseline':
            return []
        if self.arm == 'mem0':
            result = self._mem0().search(query, user_id='MC01', limit=10)
            return [{'id':x['id'], 'content':x['memory'], 'score':x.get('score')}
                    for x in result['results']]
        if self.arm == 'recmem':
            result = self._recmem().search_memories(query, 'MC01')
            exported = self.export()['layers']
            return [{'id':next(x['id'] for x in exported[name] if x['payload'].get('text')==content),
                     'layer':name, 'content':content, 'score':score}
                    for name, entries in [('episodic',result.episodic),('semantic',result.semantic),
                                          ('raw',result.subconscious)] for content,score in entries]
        if self.arm == 'trace2skill':
            return self.state.get('entries',[])
        return [{'id':self.arm+'-artifact', 'content':self.state['text']}] if self.state.get('text') else []

    def freeze(self):
        if not self.path.exists():
            raise Inconclusive(f'{self.arm} construction is missing')
        exported = self.export()
        if exported != self.state:
            raise Inconclusive(f'{self.arm} native store differs from saved artifact')
        if self.arm=='trace2skill':
            import re,yaml
            files=exported['files']
            skill=files.get('SKILL.md','')
            if not skill.startswith('---\n'):
                raise Inconclusive('Learned skill is missing YAML metadata')
            header=yaml.safe_load(skill.split('---',2)[1])
            if not isinstance(header,dict) or not all(isinstance(header.get(k),str) and header[k] for k in ['name','description']):
                raise Inconclusive('Learned skill metadata contract failed')
            for content in files.values():
                if any(path not in files for path in re.findall(r'references/[\w.\-]+\.md',content)):
                    raise Inconclusive('Learned skill references a missing procedure file')
        if 'layers' in exported:
            content_bytes=sum(len(p['payload'].get('text','').encode()) for layer in exported['layers'].values() for p in layer)
        elif 'files' in exported:
            content_bytes=sum(len(v.encode()) for v in exported['files'].values())
        elif exported.get('text'):
            content_bytes=len(exported['text'].encode())
        else:
            content_bytes=sum(len(x.get('memory',x.get('content','')).encode()) for x in exported.get('entries',[]))
        frozen = {'version': self.version, 'bytes':len(dumps(exported).encode()),'content_bytes':content_bytes,
                  'storage_bytes':sum(p.stat().st_size for p in self.directory.rglob('*')
                      if p.is_file() and p.name not in {'.lock','frozen.json'}),
                  'artifact_ref':str(self.path.relative_to(RESULTS)),
                  'artifact_sha256':digest(self.path.read_bytes()),
                  'entry_count':len(exported.get('entries',[])) if 'layers' not in exported
                  else sum(len(x) for x in exported['layers'].values())}
        write_json(self.directory/'frozen.json', frozen)
        return frozen

    def close(self):
        if self.native is None:
            return
        if self.arm == 'mem0':
            self.native.vector_store.client.close()
            self.native._telemetry_vector_store.client.close()
            self.native.db.close()
        if self.arm == 'recmem':
            for layer in [self.native.subconscious_memory, self.native.episodic_mem, self.native.semantic_memory]:
                layer.vec_store.client.close()
