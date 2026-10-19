"""Fetch pinned public sources and prepare this project's isolated AppWorld runtime.

Run with Python 3.12 from this folder. Network access is required. No model calls.
"""
import hashlib
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parent
WORLD=Path('/private/tmp')/('basis-mc01-'+hashlib.sha256(str(ROOT).encode()).hexdigest()[:12])
SOURCES={
    'appworld':('StonyBrookNLP/appworld','42b5bcf3cd334fee33f0c37c02070a9f5807add5'),
    'ace':('ace-agent/ace','82709de050e1db6e6ef2f07bcb0393560b94992a'),
    'trace2skill':('Qwen-Applications/Trace2Skill','3d0b52a140f002a512930252b613c49048f7d5ac'),
    'recmem':('CaiusDai/RecMem','a84252f6e5587fd4a8caac03ec9f6c732b7a7f35')}


def run(*args,cwd=ROOT):
    subprocess.run(args,cwd=cwd,check=True)


def main():
    cache=ROOT/'.cache'
    (cache/'vendor').mkdir(parents=True,exist_ok=True)
    os.environ['UV_CACHE_DIR']=str(cache/'uv')
    os.environ['APPWORLD_CACHE']=str(WORLD/'.cache')
    for name,(repo,commit) in SOURCES.items():
        dest=cache/'vendor'/name
        if not dest.exists():
            run('git','-c','filter.lfs.required=false','-c','filter.lfs.process=',
                '-c','filter.lfs.smudge=','clone','--depth','1',f'https://github.com/{repo}.git',str(dest))
        actual=subprocess.check_output(['git','rev-parse','HEAD'],cwd=dest,text=True).strip()
        if actual!=commit:
            run('git','fetch','--depth','1','origin',commit,cwd=dest)
            run('git','-c','filter.lfs.required=false','-c','filter.lfs.process=',
                '-c','filter.lfs.smudge=','checkout',commit,cwd=dest)
    app=cache/'vendor/appworld'
    for rel in ['src/appworld/.source/apps.bundle','src/appworld/.source/tests.bundle',
                'generate/.source/data.bundle','generate/.source/tasks.bundle']:
        pointer=subprocess.check_output(['git','show','HEAD:'+rel],cwd=app,text=True)
        sha=re.search(r'oid sha256:(\w+)',pointer)[1]
        size=int(re.search(r'size (\d+)',pointer)[1])
        dest=app/rel
        if not dest.exists() or hashlib.sha256(dest.read_bytes()).hexdigest()!=sha:
            data=urllib.request.urlopen(f'https://media.githubusercontent.com/media/StonyBrookNLP/appworld/{SOURCES["appworld"][1]}/{rel}',timeout=120).read()
            assert len(data)==size and hashlib.sha256(data).hexdigest()==sha
            dest.write_bytes(data)
    agent=app/'experiments/code/simplified/agent.py'
    original='self.language_model = LanguageModel(**model_config)'
    patched='self.language_model = model_config.get("_injected_model") or LanguageModel(**model_config)'
    text=agent.read_text()
    if patched not in text:
        assert original in text
        agent.write_text(text.replace(original,patched))
    if not (ROOT/'.venv/bin/python').exists():
        run('uv','venv','--python',sys.executable,str(ROOT/'.venv'))
    python=str(ROOT/'.venv/bin/python')
    run('uv','pip','install','--python',python,'-r','requirements.lock')
    run(python,'-m','appworld.cli','install','--repo',cwd=app)
    if not (WORLD/'data/datasets/train.txt').exists():
        run(python,'-m','appworld.cli','download','data','--root',str(WORLD))
    run(python,'-m','mc','prepare')


if __name__=='__main__': main()
