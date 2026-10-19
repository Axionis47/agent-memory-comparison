"""Run the unchanged official evaluator in a fresh process against saved state."""
from __future__ import annotations

import json
import subprocess
import sys

from .core import WORLD, ROOT, Inconclusive, digest, dumps


def application_hashes(models):
    # SQLite FTS shadow pages and row iteration order are derived storage details.
    # Compare every canonical ORM table, column and row, in a stable order.
    result={}
    for name in models.app_names:
        sqlmodel=models[name].SQLModel
        connection=sqlmodel.db.connection
        tables={}
        for model in sqlmodel.models():
            table=model.__tablename__
            quoted='"'+table.replace('"','""')+'"'
            columns=list(connection.execute('PRAGMA table_info('+quoted+')'))
            rows=sorted((list(row) for row in connection.execute('SELECT * FROM '+quoted)),key=dumps)
            tables[table]=digest({'columns':columns,'rows':rows})
        result[name]=tables
    return result


def grade_saved(task_id, experiment_name):
    result=subprocess.run([sys.executable,'-m','mc.grading',task_id,experiment_name],
                          cwd=ROOT,capture_output=True,text=True)
    if result.returncode:
        raise Inconclusive('Isolated official grading failed: '+result.stderr[-1200:])
    packets=[line.removeprefix('MC01_GRADE:') for line in result.stdout.splitlines()
             if line.startswith('MC01_GRADE:')]
    if len(packets)!=1:
        raise Inconclusive('Isolated official grading did not return one evidence packet')
    return json.loads(packets[0])


def main():
    from appworld import evaluate_task
    from appworld.task import Task
    from appworld.collections.models import ModelCollection
    from appworld.apps.lib.models.db import get_db_home_path
    task_id,experiment=sys.argv[1:]
    grade=evaluate_task(task_id,experiment_name=experiment,suppress_errors=True).to_dict()
    task=Task.load(task_id=task_id)
    directory=WORLD/'experiments/outputs'/experiment/'tasks'/task_id/'dbs'
    models=ModelCollection.load(
        to_db_home_path=get_db_home_path(storage_type='memory',type='task_output',task_id=task_id),
        from_db_home_path=str(directory),load_apps=task.allowed_apps)
    packet={'grade':grade,'application_hashes':application_hashes(models),
            'state_hash_method':'canonical ORM tables, columns and sorted rows; SQLite search-index internals excluded',
            'model_hashes_sha256':digest((directory/'model_hashes.json').read_bytes()),
            'model_hashes':json.loads((directory/'model_hashes.json').read_text()),
            'classification':'not-a-model','evaluator':'official AppWorld evaluate_task',
            'isolation':'fresh subprocess'}
    print('MC01_GRADE:'+json.dumps(packet))


if __name__=='__main__': main()
