"""Software metadata checks, no fabricated model outputs or benchmark answers."""
import json
import sqlite3

import pytest

from growth.runtime import (Cell, ARMS, select_population, change_set, redact, secrets_from,
                            source_identity, RESULTS, ROOT)
from growth.tools import Catalogue, ToolQuery, discovery_messages


def test_fresh_population_and_growth_order():
    p=select_population();old=set(p['excluded_scenario_groups'])
    assert len(p['practice'])==24 and len(set(p['practice']))==24
    groups=[i.split('_')[0] for i in p['practice']]
    assert len(set(groups))==12 and groups[:12]==groups[12:]
    assert not set(groups)&old
    assert len(p['selection_train'])==len(p['selection_validation'])==3
    assert not set(p['selection_train'])&set(p['selection_validation'])
    assert len(p['evaluation'])==8
    eval_groups={i.split('_')[0] for i in p['evaluation']}
    assert not eval_groups&old
    assert not eval_groups&{i.split('_')[0] for i in p['selection_train']}
    assert p==select_population()


def test_448_unique_evaluation_cells():
    # Exact public metadata population, no simulated task outcomes.
    from growth.runtime import evaluation_cells
    cells=[c for cp in [6,12,24] for c in evaluation_cells(cp)]
    assert len(cells)==448 and len({c.key for c in cells})==448
    assert sum(c.mode=='full' for c in cells)==288
    assert sum(c.mode=='execution_off' for c in cells)==80
    assert sum(c.mode=='discovery_off' for c in cells)==80
    assert all(c.checkpoint==24 for c in cells if c.mode!='full')


def test_auth_redaction_preserves_nonsecret_observations():
    metadata=[{'access_token':'string'}, {'password':'contract-test-secret'}, {'access_token':'contract-test-token'}]
    secrets=secrets_from(metadata)
    assert 'string' not in secrets
    out=redact({'observation':'a string field, contract-test-secret','answer':54},secrets)
    assert out=={'observation':'a string field, [AUTH REDACTED]','answer':54}


def test_native_catalogue_search_and_identity():
    catalog=Catalogue()
    try:
        found=catalog.search('phone search text messages')
        assert 0<len(found)<=8
        assert all(json.loads(x['content'])==catalog.definitions[x['id']] for x in found)
        assert catalog.identity({'method':'get','url':'/api_docs/api_doc'})=='api_docs.show_api_doc'
        assert catalog.search('')==[]
        assert catalog.search('" OR * --')==catalog.search('OR')
    finally:catalog.db.close()


def test_tool_query_schema_rejects_wrong_shapes():
    with pytest.raises(ValueError):ToolQuery.model_validate({'terms':42})
    with pytest.raises(ValueError):ToolQuery.model_validate({'terms':['x'],'action':'extra'})
    with pytest.raises(ValueError):ToolQuery.model_validate({'terms':['venmo request']})
    with pytest.raises(ValueError):ToolQuery.model_validate({'terms':['metadata']*9})
    assert ToolQuery(terms=['venmo','request','venmo']).query=='venmo request'
    assert ToolQuery(terms=[]).query==''


def test_discovery_memory_is_an_explicit_separate_input():
    ordinary=discovery_messages('metadata-goal',None,[])
    memory=discovery_messages('metadata-goal',None,[{'id':'metadata-entry','content':'metadata'}])
    assert ordinary[0]==memory[0]
    assert json.loads(ordinary[1]['content'])['historical_memory']==[]
    assert json.loads(memory[1]['content'])['historical_memory'][0]['id']=='metadata-entry'


def test_changed_entry_identity_and_content():
    before={'entries':[{'id':'a','content':'old'},{'id':'b','content':'removed'}]}
    after={'entries':[{'id':'a','content':'new'},{'id':'c','content':'added'}]}
    delta=change_set(before,after)
    assert [x['id'] for x in delta['added']]==['c']
    assert [x['id'] for x in delta['removed']]==['b']
    assert delta['updated'][0]['before']['content']=='old'
    assert delta['updated'][0]['after']['content']=='new'


def test_original_pilot_paths_are_outside_growth_namespace():
    assert RESULTS==ROOT/'results/growth-v3'
    assert 'mc/memory.py' in source_identity()
    assert 'growth/memory.py' in source_identity()
    assert Cell(arm='ace',phase='post_update',task_id='metadata',sequence=1).key!=Cell(
        arm='ace',phase='practice',task_id='metadata',sequence=1).key


def test_frozen_memory_rejects_learning_without_a_model():
    from growth.memory import Memory
    # Exercise guard without constructing provider/native clients.
    policy=Memory.__new__(Memory);policy.read_only=True
    with pytest.raises(ValueError,match='Frozen'):policy.observe({},1)


def test_completion_answer_and_feedback_have_separate_adapter_fields():
    from growth.memory import ace_inputs
    exp={'instruction':'metadata-only contract','steps':[], 'answer':None,
         'feedback':{'success':False,'failed_requirements':['metadata requirement']}}
    supplied=ace_inputs(exp,[])
    assert json.loads(supplied['predicted_answer']) is None
    assert json.loads(supplied['environment_feedback'])==exp['feedback']
    assert supplied['ground_truth'] is None and supplied['use_ground_truth'] is False
    assert supplied['bullets_used']=='(none)'


def test_grading_feedback_keeps_its_observable_support_without_changing_recurrence_arrivals():
    from growth.memory import learning_unit
    exp={'instruction':'metadata contract','steps':[{'number':1,'inputs':[],'outputs':[]}],'answer':None}
    feedback={'kind':'task_feedback','feedback':{'success':True}}
    supplied=learning_unit('mem0',feedback,exp)
    assert supplied['supporting_task_context']['steps']==exp['steps']
    assert supplied['feedback']==feedback['feedback']
    assert learning_unit('recmem',feedback,exp)==feedback
    assert 'supporting_task_context' not in feedback


def test_spending_guard_includes_all_retained_project_ledgers():
    from growth.runtime import spend_breakdown
    spending=spend_breakdown()
    assert 'results/ledger.sqlite' in spending
    assert 'results/growth-v1/ledger.sqlite' in spending
    assert 'results/growth-v2/ledger.sqlite' in spending
    assert all(value>=0 for value in spending.values())


@pytest.mark.parametrize('arm',['mem0','recmem'])
def test_empty_native_state_and_populated_store_reopen_identity_without_model_calls(tmp_path,monkeypatch,arm):
    from growth.runtime import bind
    from mc import memory as native_adapter
    from growth.memory import Memory
    bind()
    monkeypatch.setattr(native_adapter,'RESULTS',tmp_path)
    # No provider is constructed or substituted. Only empty-store metadata is exercised.
    policy=Memory(arm,None)
    before=policy.export();policy.close();policy.native=None
    assert before==policy.export()
    if arm=='mem0':assert before=={'arm':'mem0','entries':[]}
    else:
        assert before=={'arm':'recmem','layers':{'raw':[],'episodic':[],'semantic':[]}}
        assert policy.native.min_consolidation_cnt==6
        assert policy.native.gating_raw_topk==12
        assert policy.native.merge_with_epi_thresh==.75
    policy.close()


def test_common_learning_clock_uses_simulated_application_time():
    from growth.runtime import experience_units
    exp={'run_id':'metadata-run','task_id':'metadata-task','instruction':'metadata',
         'application_datetime':'2023-05-18 12:00:00',
         'steps':[{'number':1,'inputs':[],'outputs':[],
                   'application_datetime':'2023-05-18 12:00:00'}], 'feedback':{}}
    units=list(experience_units(exp))
    assert [u['kind'] for u in units]==['task_start','action_observation','task_feedback']
    assert all(u['application_datetime']==exp['application_datetime'] for u in units)
    assert all('observed_at_epoch' not in u for u in units)


def test_mem0_rejects_unaccompanied_feedback_before_model_dispatch():
    from growth.memory import mem0_ingestion_eligible
    assert mem0_ingestion_eligible({'kind':'task_start'}) is False
    with pytest.raises(ValueError,match='supporting trajectory'):
        mem0_ingestion_eligible({'kind':'task_feedback','feedback':{}})
    assert mem0_ingestion_eligible({'kind':'action_observation','inputs':[],'outputs':[]})


def test_structured_discovery_contract_and_fact_extraction_have_measured_schemas():
    from growth.provider import response_schema
    from growth.memory import MEM0_FACT_PROMPT
    query=response_schema([],'tool-search-query')
    assert query['properties']['terms']['maxItems']==8
    assert query['properties']['terms']['items']['type']=='string'
    fact=response_schema([{'role':'system','content':MEM0_FACT_PROMPT}],'mem0-learning')
    assert fact['required']==['facts']
    assert response_schema([],'agent-action') is None
    assert response_schema([{'role':'system','content':'metadata reconciliation'}],'mem0-learning') is None


def test_ace_id_counter_survives_removed_highest_bullet():
    import sys
    from mc.core import VENDOR
    sys.path.insert(0,str(VENDOR/'ace'))
    from growth.memory import ace_next_global_id
    # Metadata models a merge that removed the highest-numbered bullet.
    remaining='[ph-00002] helpful=0 harmful=0 :: metadata'
    assert ace_next_global_id({'next_global_id':10},remaining)==10
    assert ace_next_global_id({},remaining)==3


def test_pinned_structural_validator_runs_on_real_metadata_files(tmp_path):
    import subprocess,sys
    from growth.runtime import settings
    from mc.core import digest
    validator=ROOT/settings().structural_validator['path']
    assert digest(validator.read_bytes())==settings().structural_validator['sha256']
    (tmp_path/'SKILL.md').write_text('---\nname: metadata\ndescription: Metadata contract check.\n---\n\n# Metadata\n')
    good=subprocess.run([sys.executable,str(validator),str(tmp_path)],capture_output=True,text=True)
    assert good.returncode==0
    (tmp_path/'SKILL.md').write_text('# Missing frontmatter\n')
    bad=subprocess.run([sys.executable,str(validator),str(tmp_path)],capture_output=True,text=True)
    assert bad.returncode!=0
