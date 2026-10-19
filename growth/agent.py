from __future__ import annotations

import json

from mc.core import WORLD, VENDOR, Inconclusive, digest, dumps, monotonic, tree_identity
from mc.grading import application_hashes, grade_saved
from .runtime import settings, mark, secrets_from, source_identity
from .tools import Catalogue, ToolQuery, discovery_messages


class ActingModel:
    def __init__(self, vertex, memory, cell, run_id, state, catalogue):
        self.vertex,self.memory,self.cell,self.run_id=vertex,memory,cell,run_id
        self.state,self.catalogue=state,catalogue
        self.number=0

    def generate(self, messages, **kwargs):
        from appworld_agents.code.common.usage_tracker import Usage, Tokens, Cost, CostPerToken
        self.number+=1
        start=monotonic()
        last=self.state['steps'][-1] if self.state['steps'] else None
        query=dumps({'task':self.state['instruction'],'latest_action_observation':last})
        with self.vertex.tracer.start_as_current_span('memory.select'):
            candidates=self.memory.select(query)
            selected,omitted,tokens=self.vertex.pack(candidates)
        self.state['exposed_memory_ids'].update(x['id'] for x in selected)
        if self.memory.arm=='ace':
            import re
            self.state['exposed_memory_ids'].update(re.findall(r'^\[([^\]]+)\] helpful=',
                '\n'.join(x['content'] for x in selected),flags=re.MULTILINE))
        selection={'decision':self.number,'query':query,'items':selected,'omitted':omitted,
                   'tokens':tokens,'memory_version':self.memory.version,'duration_s':monotonic()-start,
                   'selection_mode':'native-search' if self.memory.arm in {'mem0','recmem'} else 'whole-artifact',
                   'cell':self.cell.model_dump()}
        mark(self.vertex.ledger,'selection',selection,self.cell.arm,self.cell.phase,self.run_id)
        discovery_memory=[] if self.cell.mode=='discovery_off' else selected
        discovery=discovery_messages(self.state['instruction'],last,discovery_memory)
        search_start=monotonic();definitions=[];error=None
        try:
            packet=self.vertex.generate(discovery,json_mode=True,purpose='tool-search-query')
            parsed=ToolQuery.model_validate_json(packet['output'])
            definitions=self.catalogue.search(parsed.query)
            query_text=parsed.query
        except (ValueError,TypeError) as exc:
            error=f'{type(exc).__name__}: malformed tool query'
            query_text=None
        # Operational provider errors propagate. Malformed model output leaves
        # native documentation discovery available to the unchanged acting agent.
        definitions,tool_omitted,tool_tokens=self.vertex.pack(definitions)
        self.state['exposed_tool_ids'].update(x['id'] for x in definitions)
        mark(self.vertex.ledger,'tool_discovery',{'decision':self.number,'query':query_text,'error':error,
            'items':definitions,'omitted':tool_omitted,'tokens':tool_tokens,
            'duration_s':monotonic()-search_start,'catalogue_version':self.catalogue.version,
            'memory_exposed':discovery_memory,'call_id':packet['call_id']},
            self.cell.arm,self.cell.phase,self.run_id)
        execution_memory=[] if self.cell.mode=='execution_off' else selected
        slots=[{'role':'system','content':'Historical memory, advisory only:\n'+
                ('\n\n'.join(x['content'] for x in execution_memory) or '(empty)')},
               {'role':'system','content':'Current tool definitions from catalogue search:\n'+
                ('\n\n'.join(x['content'] for x in definitions) or '(none; native API documentation remains available)')}]
        supplied=[*slots,*messages]
        # Save the exposure BEFORE dispatch, so MAX_TOKENS still has complete evidence.
        mark(self.vertex.ledger,'exposure_intent',{'decision':self.number,'memory_version':self.memory.version,
             'items':execution_memory,'tools':definitions,'request_hash':digest(supplied),
             'native_prompt_hash':digest(messages),'cell':self.cell.model_dump()},
             self.cell.arm,self.cell.phase,self.run_id)
        data=self.vertex.generate(supplied,purpose='agent-action')
        mark(self.vertex.ledger,'exposure',{'decision':self.number,'call_id':data['call_id'],
             'items':execution_memory,'tools':definitions,'request_hash':data['request_hash']},
             self.cell.arm,self.cell.phase,self.run_id)
        u=data['usage'];prices=settings().pricing
        counts=Tokens(input_cache_miss=(u.get('prompt_token_count') or 0)-(u.get('cached_content_token_count') or 0),
            input_cache_hit=u.get('cached_content_token_count') or 0,
            output=(u.get('candidates_token_count') or 0)+(u.get('thoughts_token_count') or 0))
        rates=CostPerToken(input_cache_miss=prices['input_per_million']/1e6,
            input_cache_hit=prices['cached_input_per_million']/1e6,output=prices['output_per_million']/1e6)
        return {'role':'assistant','content':data['output'],
                'standardized_usage':Usage(tokens=counts,cost_per_token=rates,cost=Cost.build(counts,rates))}


def solve(cell, memory, vertex):
    from appworld import AppWorld
    from appworld_agents.code.simplified.react_code_agent import SimplifiedReActCodeAgent
    import freezegun
    freezegun.configure(extend_ignore_list=['google','httpx','httpcore','opentelemetry','mc','growth'])
    ledger=vertex.ledger
    previous=ledger.latest(cell)
    if previous and previous['status']=='conclusive': return previous
    before=memory.export()
    initial=digest(tree_identity(WORLD/'data/tasks'/cell.task_id/'dbs'))
    run_id=ledger.start(cell,{'cell':cell.model_dump(),'memory_version':memory.version,'reset_identity':initial})
    experiment=f'MC02/{run_id}'
    catalogue=Catalogue()
    state={'steps':[],'completed':False,'exposed_memory_ids':set(), 'exposed_tool_ids':set(),
           'authentication_values':set(),'cell':cell.model_dump(),'reset_identity':initial,
           'memory_version':memory.version,'catalogue_version':catalogue.version}
    state['executed_source_identity']=source_identity()
    model=ActingModel(vertex,memory,cell,run_id,state,catalogue)
    class InstrumentedAgent(SimplifiedReActCodeAgent):
        def initialize(self,world):
            super().initialize(world)
            if any(world.models[n].SQLModel.db.home_path!=world.models_to_db_home_path
                   for n in world.models.app_names):
                raise Inconclusive('Native database identity differs from grading metadata identity')
            state['loaded_reset_identity']=digest(application_hashes(world.models))
            for r in ledger.records('loaded_reset'):
                if r['data']['task_id']==cell.task_id and r['data']['identity']!=state['loaded_reset_identity']:
                    raise Inconclusive('Loaded world differs from prior identical task reset')
            mark(ledger,'loaded_reset',{'task_id':cell.task_id,'identity':state['loaded_reset_identity']},
                 cell.arm,cell.phase,run_id)
            state['instruction']=world.task.instruction
            state['task_datetime']=str(world.task.datetime)
            batch=world.batch_execute
            def observed_batch(inputs):
                started=monotonic()
                with vertex.tracer.start_as_current_span('tool.execute'):
                    outputs=batch(inputs)
                event={'number':len(state['steps'])+1,'inputs':inputs,'outputs':outputs,
                       'duration_s':monotonic()-started}
                state['steps'].append(event)
                state['authentication_values'].update(secrets_from(outputs))
                mark(ledger,'action_observation',event,cell.arm,cell.phase,run_id)
                # Incremental native API log: documentation exposure and guessed calls.
                calls=AppWorld.parse_api_calls_log(experiment_name=experiment,task_id=cell.task_id)
                for call in calls[state.get('api_count',0):]:
                    identity=catalogue.identity(call)
                    mark(ledger,'tool_call',{'decision':len(state['steps']), 'identity':identity,
                        'definition_previously_exposed':identity in state['exposed_tool_ids'],
                        'call':call},cell.arm,cell.phase,run_id)
                    if identity=='api_docs.show_api_doc':
                        state['exposed_tool_ids'].add(call['data']['app_name']+'.'+call['data']['api_name'])
                    if identity=='supervisor.complete_task':
                        state['completion_answer']=call['data'].get('answer')
                state['api_count']=len(calls)
                state['completed']=world.task_completed()
                if state['completed']: state['final_application_hashes']=application_hashes(world.models)
                return outputs
            world.batch_execute=observed_batch
    agent=InstrumentedAgent(
        prompt_file_path=str(VENDOR/'appworld/experiments/prompts/react_code_agent/instructions.txt'),
        model_config={'_injected_model':model},appworld_config={'random_seed':0},
        logger_config={'verbose':False,'color':False},max_steps=settings().max_steps_watchdog,log_lm_calls=False)
    agent.logger.terminal_console.quiet=True
    start=monotonic();status='inconclusive';success=None
    try:
        with vertex.scoped(run_id=run_id,arm=cell.arm,phase=cell.phase,checkpoint=cell.checkpoint,
                           mode=cell.mode,cell_key=cell.key):
            with vertex.tracer.start_as_current_span('agent.task',attributes={'run_id':run_id}):
                agent.solve_tasks([cell.task_id],experiment_name=experiment)
            if not state['completed']: raise Inconclusive('Operational watchdog or abnormal termination')
            grading_start=monotonic();packet=grade_saved(cell.task_id,experiment)
            state['grading_s']=monotonic()-grading_start
            mark(ledger,'saved_state_verification',packet,cell.arm,cell.phase,run_id)
            if packet['application_hashes']!=state['final_application_hashes']:
                raise Inconclusive('Saved final state differs from actual completed world')
            if memory.export()!=before: raise Inconclusive('Memory changed during acting')
            state['grade']=packet['grade'];success=packet['grade']['success'];status='conclusive'
            calls=AppWorld.parse_api_calls_log(experiment_name=experiment,task_id=cell.task_id)
            state['api_calls']=len(calls);state['api_log_hash']=digest(calls)
    except Exception as exc:
        state['error_type']=type(exc).__name__;state['error']=str(exc)[:1800]
        mark(ledger,'run_error',{'type':type(exc).__name__,'message':str(exc)[:1800]},cell.arm,cell.phase,run_id)
    finally:
        for field in ['exposed_memory_ids','exposed_tool_ids','authentication_values']:
            state[field]=sorted(state[field])
        state['duration_s']=monotonic()-start
        state['tool_s']=sum(s['duration_s'] for s in state['steps'])
        state['native_output']=str(WORLD/'experiments/outputs'/experiment)
        ledger.finish(run_id,status,success,state)
        if agent.logger.file_jsonl: agent.logger.file_jsonl.close()
        if agent.logger.file_console: agent.logger.file_console.file.close()
        catalogue.db.close()
    print(f'{cell.key}: {status}, success={success}, steps={len(state["steps"])}',flush=True)
    return dict(ledger.db.execute('SELECT * FROM runs WHERE id=?',(run_id,)).fetchone())
