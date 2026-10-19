"""Software-only contracts using authored metadata, never fake task/model answers."""
import json
from pathlib import Path

import pytest

from mc.core import (Cell, Inconclusive, Ledger, choose_population, digest,
                     evaluation_cells, monotonic, now, protocol)
from mc.report import scorecard


def test_population_reproducible_and_disjoint_by_scenario():
    train=[f't{i}_{v}' for i in range(12) for v in range(3)]
    dev=[f'd{i}_{v}' for i in range(12) for v in range(3)]
    group=lambda x:x.split('_')[0]
    first=choose_population(train,dev,group)
    assert first==choose_population(list(reversed(train)),list(reversed(dev)),group)
    assert {group(x) for x in first['selection']}.isdisjoint(group(x) for x in first['evaluation'])
    assert {group(x) for x in first['train']}.isdisjoint(group(x) for x in first['smoke'])
    assert [len(first[x]) for x in ['train','selection','evaluation','smoke']]==[6,2,6,2]


def test_all_72_cells_unique_and_paired():
    cells=evaluation_cells({'evaluation':[f't{i}' for i in range(6)]})
    assert len(cells)==72 and len({x.key for x in cells})==72
    assert all(sum(c.arm==a for c in cells)==12 for a in protocol().arms)
    assert [c.arm for c in cells[:6]]!=[c.arm for c in cells[6:12]]
    assert [c.arm for c in cells[:6]]!=[c.arm for c in cells[36:42]]


def test_conclusive_failures_cannot_be_selectively_rerun(tmp_path):
    ledger=Ledger(tmp_path/'ledger.sqlite')
    cell=Cell(arm='baseline',phase='evaluation',task_id='metadata-case')
    ident=ledger.start(cell,{'classification':'not-a-model'})
    ledger.finish(ident,'conclusive',False,{'classification':'not-a-model'})
    with pytest.raises(ValueError,match='cannot be rerun'):
        ledger.start(cell,{})


def test_unknown_reservation_remains_fully_retained(tmp_path):
    ledger=Ledger(tmp_path/'ledger.sqlite')
    ledger.reserve('metadata-call',{},'not-a-model',protocol().estimated_cost_guard_usd,{})
    ledger.settle('metadata-call','unknown',None,{'classification':'not-a-model'})
    with pytest.raises(Inconclusive): ledger.reserve('second',{},'not-a-model',0.01,{})
    assert ledger.db.execute('SELECT estimate,reservation FROM calls').fetchone()[0] is None


def test_interrupted_run_is_not_a_behavioral_failure():
    rows=[{'arm':'baseline','task_id':'t','repetition':0,'status':'conclusive','success':True,'started':1},
          {'arm':'ace','task_id':'t','repetition':0,'status':'inconclusive','success':None,'started':2}]
    result={x['arm']:x for x in scorecard(rows,['baseline','ace'])}
    assert result['ace']['conclusive']==0 and result['ace']['losses']==0
    assert result['ace']['inconclusive']==1 and result['ace']['missing']==11
    assert result['ace']['unmatched']==12


def test_repeatability_only_uses_complete_pairs():
    rows=[{'arm':'baseline','task_id':'t','repetition':n,'status':'conclusive','success':value,'started':n}
          for n,value in enumerate([True,False])]
    r=scorecard(rows,['baseline'])[0]
    assert r['repeat_tasks']==1 and r['one_success_tasks']==1 and r['repeat_agreement']==0


def test_measurement_clocks_survive_simulated_application_time():
    from freezegun import freeze_time
    import time
    with freeze_time('2020-01-01'):
        start=monotonic(); time.sleep(.01)
        assert monotonic()-start>=.009
        assert now()>1700000000


def test_sqlalchemy_preserves_native_grading_database_identity():
    from sqlmodel import create_engine
    from appworld.apps.lib.models.db import Database
    engine=create_engine('sqlite:///file:mc01-contract/example.db?mode=memory&cache=shared&uri=true')
    try:
        details=Database._get_engine_to_details(engine)
        assert details[2]==':memory:mc01-contract'
    finally: engine.dispose()


def test_canonical_final_state_ignores_row_order_but_detects_record_changes():
    import sqlite3
    from types import SimpleNamespace
    from mc.grading import application_hashes
    class Stores(dict):
        app_names=['app']
    def database(rows):
        connection=sqlite3.connect(':memory:')
        connection.execute('CREATE TABLE records (value TEXT)')
        connection.executemany('INSERT INTO records VALUES (?)',[(r,) for r in rows])
        sqlmodel=SimpleNamespace(db=SimpleNamespace(connection=connection),
            models=lambda:[SimpleNamespace(__tablename__='records')])
        return Stores(app=SimpleNamespace(SQLModel=sqlmodel))
    a=database(['storage metadata A','storage metadata B'])
    b=database(['storage metadata B','storage metadata A'])
    try:
        assert application_hashes(a)==application_hashes(b)
        b['app'].SQLModel.db.connection.execute("UPDATE records SET value='changed metadata' WHERE value='storage metadata A'")
        assert application_hashes(a)!=application_hashes(b)
    finally:
        a['app'].SQLModel.db.connection.close();b['app'].SQLModel.db.connection.close()


def test_native_mem0_constructor_uses_local_store_without_any_model_call(tmp_path,monkeypatch):
    import mc.memory as memory
    monkeypatch.setattr(memory,'RESULTS',tmp_path)
    policy=memory.MemoryPolicy('mem0',None)
    try:
        native=policy._mem0()
        assert native.llm.__class__.__name__=='Mem0VertexLLM'
        assert policy.export()['entries']==[]
    finally: policy.close()


def test_native_recmem_constructor_and_three_isolated_stores(tmp_path,monkeypatch):
    import mc.memory as memory
    monkeypatch.setattr(memory,'RESULTS',tmp_path)
    policy=memory.MemoryPolicy('recmem',None)
    try:
        policy._recmem()
        assert policy.export()['layers']=={'raw':[],'episodic':[],'semantic':[]}
        assert len({policy.directory/x for x in ['subconscious','episodic','semantic']})==3
    finally: policy.close()


def test_freeze_prevents_new_learning(tmp_path,monkeypatch):
    import mc.memory as memory
    monkeypatch.setattr(memory,'RESULTS',tmp_path)
    policy=memory.MemoryPolicy('baseline',None)
    policy.commit=lambda state: (setattr(policy,'state',state),policy.path.write_text(json.dumps(state)))
    policy.commit(policy.state)
    frozen=policy.freeze()
    assert frozen['version']==digest(policy.state)
    with pytest.raises(ValueError,match='Frozen'): policy.learn([])


def test_system_only_provider_normalization_is_not_an_answer_substitute():
    from mc.provider import normalize_messages
    original=[{'role':'system','content':'metadata schema'}]
    normalized=normalize_messages(original)
    assert normalized[0]==original[0] and len(original)==1
    assert normalized[-1]['role']=='user'
    assert normalize_messages([{'role':'user','content':'metadata'}])==[{'role':'user','content':'metadata'}]


def test_native_recmem_vector_identity_survives_reopen(tmp_path,monkeypatch):
    import mc.memory as memory
    import uuid
    monkeypatch.setattr(memory,'RESULTS',tmp_path)
    p=memory.MemoryPolicy('recmem',None)
    m=p._recmem()
    # Authored vector metadata exercises persistence, with no embedding/model call.
    m.subconscious_memory.add(embedding=[float(n%7+1) for n in range(protocol().embedding_dimension)],
        payload='not-a-model storage metadata',id=str(uuid.uuid4()),conv_id='MC01',extra_payload={'timestamp':'metadata'})
    before=p.export();p.close()
    q=memory.MemoryPolicy('recmem',None)
    try: assert q.export()==before
    finally: q.close()


def test_native_mem0_populated_store_survives_reopen(tmp_path,monkeypatch):
    import mc.memory as memory
    import uuid
    monkeypatch.setattr(memory,'RESULTS',tmp_path)
    p=memory.MemoryPolicy('mem0',None)
    p._mem0().vector_store.insert(vectors=[[float(n%3+1) for n in range(protocol().embedding_dimension)]],
        ids=[str(uuid.uuid4())],payloads=[{'data':'not-a-model storage metadata','user_id':'MC01',
        'hash':'software-metadata','created_at':'2026-10-18T00:00:00Z'}])
    before=p.export();p.close()
    q=memory.MemoryPolicy('mem0',None)
    try:
        assert len(q.export()['entries'])==1
        assert q.export()==before
    finally: q.close()


def test_common_context_packing_uses_real_tokenizer_and_skips_oversized_items():
    from google.genai.local_tokenizer import LocalTokenizer
    from mc.provider import pack_local
    tokenizer=LocalTokenizer(protocol().model)
    short='storage metadata'
    assert tokenizer.count_tokens(short).total_tokens>0
    assert tokenizer.count_tokens(short*20000).total_tokens>protocol().memory_tokens
    selected,omitted=pack_local([{'id':'oversized','content':short*20000},
        {'id':'fits','content':short}],tokenizer,protocol().memory_tokens)
    assert [x['id'] for x in selected]==['fits']
    assert [x['id'] for x in omitted]==['oversized']
