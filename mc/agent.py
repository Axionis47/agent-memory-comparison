from __future__ import annotations

import json
from pathlib import Path

from .core import CACHE, WORLD, VENDOR, Cell, Inconclusive, digest, monotonic, protocol, tree_identity
from .provider import PUBLIC_OUTPUT
from .grading import application_hashes, grade_saved


class ActingModel:
    def __init__(self, vertex, memory, run_id):
        self.vertex, self.memory, self.run_id = vertex, memory, run_id
        self.selected = None
        self.query = None
        self.request_number = 0

    def generate(self, messages, **kwargs):
        from appworld_agents.code.common.usage_tracker import Usage, Tokens, Cost, CostPerToken
        if self.selected is None:
            start = monotonic()
            with self.vertex.tracer.start_as_current_span('memory.select'):
                candidates=self.memory.select(self.query)
                self.selected,omitted,tokens=self.vertex.pack(candidates)
            self.vertex.ledger.record('selection', {'items': self.selected, 'tokens': tokens,
                'duration_s': monotonic()-start, 'memory_version': self.memory.version,'omitted':omitted},
                self.run_id, self.memory.arm, self.vertex.scope['phase'])
        text = '\n\n'.join(x['content'] for x in self.selected)
        slot = {'role': 'system', 'content': 'Historical memory, advisory only:\n' + (text or '(empty)')}
        supplied = [slot, *messages]
        self.request_number += 1
        data = self.vertex.generate(supplied, purpose='agent-action')
        self.vertex.ledger.record('exposure', {'call_id': data['call_id'], 'request_number': self.request_number,
            'memory_version': self.memory.version, 'items': self.selected,
            'request_hash': data['request_hash']}, self.run_id, self.memory.arm, self.vertex.scope['phase'])
        u = data['usage']
        tokens = Tokens(input_cache_miss=(u.get('prompt_token_count') or 0)-(u.get('cached_content_token_count') or 0),
            input_cache_hit=u.get('cached_content_token_count') or 0,
            output=(u.get('candidates_token_count') or 0)+(u.get('thoughts_token_count') or 0))
        prices=protocol().pricing
        rates=CostPerToken(input_cache_miss=prices['input_per_million']/1e6,
            input_cache_hit=prices['cached_input_per_million']/1e6, output=prices['output_per_million']/1e6)
        usage=Usage(tokens=tokens,cost_per_token=rates,cost=Cost.build(tokens,rates))
        return {'role': 'assistant', 'content': data['output'], 'standardized_usage': usage}


def solve(cell: Cell, memory, vertex, *, reuse=True):
    from appworld import AppWorld, evaluate_task
    from appworld_agents.code.simplified.react_code_agent import SimplifiedReActCodeAgent
    import freezegun
    freezegun.configure(extend_ignore_list=['google', 'httpx', 'httpcore', 'opentelemetry', 'mc'])
    ledger = vertex.ledger
    prev = ledger.latest(cell)
    if reuse and prev and prev['status'] == 'conclusive':
        return prev
    task_data = WORLD / 'data' / 'tasks' / cell.task_id
    initial = tree_identity(task_data / 'dbs')
    reset_identity = digest(initial)
    before = memory.export()
    run_id = ledger.start(cell, {'reset_identity': reset_identity, 'memory_version': memory.version})
    experiment = f'MC01/{run_id}'
    model = ActingModel(vertex, memory, run_id)
    steps = []
    state = {'completed': False}

    class InstrumentedAgent(SimplifiedReActCodeAgent):
        def initialize(self, world):
            super().initialize(world)
            if any(world.models[n].SQLModel.db.home_path!=world.models_to_db_home_path
                   for n in world.models.app_names):
                raise Inconclusive('Native database identity differs from grading metadata identity')
            loaded={}
            for name in world.models.app_names:
                connection=world.models[name].SQLModel.db.connection
                loaded[name]=digest('\n'.join(connection.iterdump()))
            state['loaded_reset_identity']=digest(loaded)
            earlier=ledger.records('loaded_reset')
            expected=[r['data']['identity'] for r in earlier if r['data']['task_id']==cell.task_id]
            if expected and any(x!=state['loaded_reset_identity'] for x in expected):
                raise Inconclusive('Loaded application database state differs from prior reset')
            ledger.record('loaded_reset',{'task_id':cell.task_id,'identity':state['loaded_reset_identity'],
                'application_hashes':loaded},run_id,cell.arm,cell.phase)
            state['instruction'] = world.task.instruction
            # Fingerprint loaded canonical input state, never substitute memory for it.
            state['task_datetime'] = str(world.task.datetime)
            model.query = world.task.instruction
            batch = world.batch_execute
            def observed_batch(inputs):
                start = monotonic()
                with vertex.tracer.start_as_current_span('tool.execute'):
                    output = batch(inputs)
                event = {'number': len(steps)+1, 'inputs': inputs, 'outputs': output,
                         'duration_s': monotonic()-start}
                steps.append(event)
                ledger.record('action_observation', event, run_id, cell.arm, cell.phase)
                state['completed'] = world.task_completed()
                if state['completed']:
                    state['final_application_hashes']=application_hashes(world.models)
                return output
            world.batch_execute = observed_batch

    agent = InstrumentedAgent(
        prompt_file_path=str(VENDOR / 'appworld/experiments/prompts/react_code_agent/instructions.txt'),
        model_config={'_injected_model': model},
        appworld_config={'random_seed': 0},
        logger_config={'verbose': False, 'color': False},
        max_steps=protocol().max_steps_watchdog, log_lm_calls=False)
    agent.logger.terminal_console.quiet=True
    start = monotonic()
    info = {'reset_identity': reset_identity, 'memory_version': memory.version,
            'experiment_name': experiment, 'steps': steps}
    success = None
    status = 'inconclusive'
    try:
        with vertex.scoped(run_id=run_id, arm=cell.arm, phase=cell.phase):
            with vertex.tracer.start_as_current_span('agent.task', attributes={
                    'run_id': run_id, 'arm': cell.arm, 'phase': cell.phase, 'task_id': cell.task_id}):
                agent.solve_tasks([cell.task_id], experiment_name=experiment)
            if not state['completed']:
                raise Inconclusive('Operational step watchdog or abnormal agent termination')
            grading_start=monotonic()
            packet=grade_saved(cell.task_id,experiment)
            info['grading_s']=monotonic()-grading_start
            ledger.record('saved_state_verification',packet,run_id,cell.arm,cell.phase)
            if packet['application_hashes']!=state['final_application_hashes']:
                raise Inconclusive('Persisted application state differs from the actual completed world')
            info['grade'] = packet['grade']
            success = packet['grade']['success']
            calls = AppWorld.parse_api_calls_log(experiment_name=experiment, task_id=cell.task_id)
            info['api_calls'] = len(calls)
            info['api_log_hash'] = digest(calls)
            if memory.export() != before:
                raise Inconclusive('Memory mutated during task execution')
            status = 'conclusive'
    except Exception as exc:
        info['error_type'] = type(exc).__name__
        info['error'] = str(exc)[:1000]
        success = None
        ledger.record('run_error', {'type': type(exc).__name__, 'message': str(exc)[:1000]},
                       run_id, cell.arm, cell.phase)
    finally:
        info.update(state)
        info['duration_s'] = monotonic()-start
        info['tool_s'] = sum(x['duration_s'] for x in steps)
        info['native_output'] = str(WORLD / 'experiments/outputs' / experiment)
        ledger.finish(run_id, status, success, info)
        if agent.logger.file_jsonl:
            agent.logger.file_jsonl.close()
        if agent.logger.file_console:
            agent.logger.file_console.file.close()
    print(f'{cell.key}: {status}, success={success}, steps={len(steps)}', flush=True)
    return dict(ledger.db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone())


def experiences(ledger) -> list[dict]:
    tasks = []
    pop = json.loads((CACHE / 'population.json').read_text())
    for task in pop['train']:
        run = ledger.latest(Cell(phase='train', arm='baseline', task_id=task))
        if not run or run['status'] != 'conclusive':
            raise Inconclusive('Shared training corpus is incomplete')
        data = json.loads(run['data'])
        observed={r['data']['number']:r['created'] for r in ledger.records('action_observation',run['id'])}
        actual_steps=[{**step,'observed_at_epoch':observed[step['number']]} for step in data['steps']]
        tasks.append({'task_id': task, 'run_id': run['id'], 'instruction': data['instruction'],
                      'steps': actual_steps, 'feedback': data['grade']})
    return tasks
