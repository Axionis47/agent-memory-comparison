"""Validate published files and derived evidence without model or network calls."""
import ast
import hashlib
import json
from pathlib import Path
import re


def main():
    root=Path(__file__).resolve().parents[1]
    manifest=json.loads((root/'evidence/release-manifest.json').read_text())
    for name,expected in manifest['files'].items():
        actual=hashlib.sha256((root/name).read_bytes()).hexdigest()
        if actual!=expected:
            raise SystemExit('File identity differs from publication snapshot: '+name)
    published=[root/name for name in manifest['files']]
    for path in published:
        if path.suffix!='.py':continue
        ast.parse(path.read_text(),filename=str(path))
    for path in published:
        if path.suffix!='.md':continue
        for target in re.findall(r'\]\(([^)]+)\)',path.read_text()):
            if re.match(r'[a-z]+://',target) or target.startswith('#'):continue
            target=target.split('#',1)[0]
            if not (path.parent/target).exists():
                raise SystemExit('Broken local link in '+str(path.relative_to(root))+': '+target)
    cases=json.loads((root/'evidence/cases.json').read_text())['runs']
    runs={r['run_id']:r for r in cases}
    if len(runs)!=len(cases):raise SystemExit('Duplicate exported run identity')
    retained=json.loads((root/'evidence/gepa-retention.json').read_text())
    assert retained['instruction'] and retained['candidate_testing_task_attempts']==14
    assert [runs[x]['official_success'] for x in retained['follow_up_runs']]==[True,True]
    assert [runs[x]['official_success'] for x in retained['control_runs']]==[False,True]
    for path in published:
        if path.suffix in {'.sqlite','.db'} or path.name.endswith(('.tar.gz','.zip')):
            raise SystemExit('Private or bulky evidence format included: '+str(path))
        text=path.read_text()
        if re.search(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+',text):
            raise SystemExit('JWT-shaped credential found: '+str(path))
        if re.search(r'/(?:Users|var/folders)/',text):
            raise SystemExit('Host-specific personal path found: '+str(path))
    diagnostic=json.loads((root/'evidence/diagnostic-actions.json').read_text())
    rows=diagnostic['runs']
    assert len(rows)==len({r['run_id'] for r in rows})==86
    assert sum(r['diagnostic']=='memory-effect' for r in rows)==32
    later=[r for r in rows if r['diagnostic']=='three-memory-effect']
    assert len(later)==54 and sum(bool(r['comparison_eligible']) for r in later)==53
    assert all(r['classification']=='live' for r in rows)
    for row in rows:
        for decision in row['decisions']:
            assert all(ref in diagnostic['memory_items'] for ref in decision['exposed_memory_refs'])
    planned=json.loads((root/'adjacent/protocol.json').read_text())
    assert planned['status']=='planned' and not planned['execution_freeze']
    cells=planned['evaluation']['cells']
    assert len(cells)==len({c['cell_id'] for c in cells})==27
    print(f'Verified {len(manifest["files"])} file identities, {len(cases)} sanitised task records, Python syntax and local documentation links.')
    print('Also reconciled 86 later diagnostic exports, 53/54 eligible three-memory attempts, context references and 27 planned adjacent-task cells.')
    print('No model calls made. These checks do not independently verify official benchmark outcomes.')


if __name__=='__main__':main()
