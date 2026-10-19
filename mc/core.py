from __future__ import annotations

import contextlib
import hashlib
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / '.cache'
RESULTS = ROOT / 'results'
VENDOR = CACHE / 'vendor'
# Upstream treats any DB path containing the substring "memory" as in-memory.
# Keep the official world outside this project's necessarily descriptive path.
WORLD = Path('/private/tmp') / ('basis-mc01-' + hashlib.sha256(str(ROOT).encode()).hexdigest()[:12])
os.environ['APPWORLD_ROOT'] = str(WORLD)
os.environ['APPWORLD_CACHE'] = str(WORLD / '.cache')
os.environ['MEM0_DIR'] = str(CACHE / 'mem0')
os.environ['MEM0_TELEMETRY'] = 'false'
os.environ['IPYTHONDIR'] = str(CACHE / 'ipython')


def now() -> float:
    # AppWorld deliberately freezes application time. Measurement uses OS clocks.
    return time.clock_gettime(time.CLOCK_REALTIME)


def monotonic() -> float:
    return time.clock_gettime(time.CLOCK_MONOTONIC)


def dumps(x: Any) -> str:
    return json.dumps(x, sort_keys=True, ensure_ascii=False, default=str)


def digest(x: Any) -> str:
    return hashlib.sha256((x if isinstance(x, bytes) else dumps(x).encode())).hexdigest()


def read_json(p: Path) -> Any:
    return json.loads(p.read_text())


def write_json(p: Path, x: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    temp = p.with_suffix(p.suffix + '.tmp')
    temp.write_text(json.dumps(x, indent=2, ensure_ascii=False, default=str) + '\n')
    temp.replace(p)


class Protocol(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str
    version: int
    seed: str
    arms: list[str]
    train_tasks: int
    selection_tasks: int
    evaluation_tasks: int
    repetitions: int
    project: str
    location: str
    model: str
    embedding_model: str
    embedding_dimension: int
    temperature: float
    thinking_budget: int
    max_output_tokens: int
    max_steps_watchdog: int
    gepa_metric_calls: int
    memory_tokens: int
    estimated_cost_guard_usd: float
    pricing: dict


def protocol() -> Protocol:
    return Protocol.model_validate(read_json(ROOT / 'protocol.json'))


class Cell(BaseModel):
    model_config = ConfigDict(extra='forbid')
    arm: str
    task_id: str
    repetition: int = 0
    phase: Literal['smoke', 'train', 'selection', 'evaluation']

    @property
    def key(self) -> str:
        return f'{self.phase}-{self.arm}-{self.task_id}-r{self.repetition}'


def choose_population(train: list[str], dev: list[str], group) -> dict:
    p = protocol()
    def ranked(ids):
        return sorted(ids, key=lambda x: digest(p.seed + x))
    def distinct(ids):
        seen = set()
        out = []
        for task in ranked(ids):
            if group(task) not in seen:
                out.append(task)
                seen.add(group(task))
        return out
    t, d = distinct(train), distinct(dev)
    if len(t) < p.train_tasks + 2 or len(d) < p.selection_tasks + p.evaluation_tasks:
        raise ValueError('Insufficient distinct upstream scenario groups')
    return {'train': t[:p.train_tasks], 'smoke': t[p.train_tasks:p.train_tasks+2],
            'selection': d[:p.selection_tasks],
            'evaluation': d[p.selection_tasks:p.selection_tasks+p.evaluation_tasks]}


def evaluation_cells(pop: dict) -> list[Cell]:
    p = protocol()
    out = []
    for rep in range(p.repetitions):
        for n, task in enumerate(pop['evaluation']):
            offset = (rep + n) % len(p.arms)
            arms = p.arms[offset:] + p.arms[:offset]
            out.extend(Cell(phase='evaluation', arm=a, task_id=task, repetition=rep) for a in arms)
    return out


class Inconclusive(RuntimeError):
    """Operational/supporting failure, never a behavioral zero."""


class Ledger:
    def __init__(self, path: Path = RESULTS / 'ledger.sqlite'):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS records (
          id TEXT PRIMARY KEY, kind TEXT NOT NULL, run_id TEXT, arm TEXT, phase TEXT,
          created REAL NOT NULL, data TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS records_kind_run ON records(kind, run_id);
        CREATE TABLE IF NOT EXISTS runs (
          id TEXT PRIMARY KEY, cell_key TEXT NOT NULL, arm TEXT NOT NULL,
          phase TEXT NOT NULL, task_id TEXT NOT NULL, repetition INTEGER NOT NULL,
          status TEXT NOT NULL, success INTEGER, started REAL NOT NULL,
          ended REAL, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS calls (
          id TEXT PRIMARY KEY, run_id TEXT, arm TEXT, phase TEXT, kind TEXT,
          status TEXT, estimate REAL, reservation REAL, started REAL,
          ended REAL, data TEXT NOT NULL);
        ''')
        self.db.commit()

    def record(self, kind: str, data: Any, run_id=None, arm=None, phase=None) -> str:
        ident = uuid.uuid4().hex
        self.db.execute('INSERT INTO records VALUES (?,?,?,?,?,?,?)',
                        (ident, kind, run_id, arm, phase, now(), dumps(data)))
        self.db.commit()
        return ident

    def records(self, kind: str, run_id=None) -> list[dict]:
        rows = self.db.execute('SELECT * FROM records WHERE kind=?' +
                               (' AND run_id=?' if run_id else '') + ' ORDER BY created',
                               (kind, run_id) if run_id else (kind,)).fetchall()
        return [{**dict(r), 'data': json.loads(r['data'])} for r in rows]

    def latest(self, cell: Cell):
        r = self.db.execute('SELECT * FROM runs WHERE cell_key=? ORDER BY started DESC LIMIT 1',
                            (cell.key,)).fetchone()
        return dict(r) if r else None

    def start(self, cell: Cell, data: dict) -> str:
        previous = self.latest(cell)
        if previous and previous['status'] == 'conclusive':
            raise ValueError('Conclusive cell cannot be rerun')
        if previous and previous['status'] == 'running':
            raise Inconclusive('Unresolved prior attempt: reconcile before resuming')
        ident = uuid.uuid4().hex
        self.db.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                        (ident, cell.key, cell.arm, cell.phase, cell.task_id, cell.repetition,
                         'running', None, now(), None, dumps(data)))
        self.db.commit()
        return ident

    def finish(self, ident: str, status: str, success: bool | None, data: dict):
        assert status in {'conclusive', 'inconclusive'}
        assert (success is not None) == (status == 'conclusive')
        self.db.execute('UPDATE runs SET status=?,success=?,ended=?,data=? WHERE id=?',
                        (status, success, now(), dumps(data), ident))
        self.db.commit()

    def reserve(self, ident: str, scope: dict, kind: str, amount: float, data: dict):
        total = self.db.execute('SELECT coalesce(sum(coalesce(estimate,reservation)),0) FROM calls').fetchone()[0]
        if total + amount > protocol().estimated_cost_guard_usd:
            raise Inconclusive('Operational estimated-cost guard reached')
        self.db.execute('INSERT INTO calls VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                        (ident, scope.get('run_id'), scope.get('arm'), scope.get('phase'), kind,
                         'pending', None, amount, now(), None, dumps(data)))
        self.db.commit()

    def settle(self, ident: str, status: str, estimate: float | None, data: dict):
        self.db.execute('UPDATE calls SET status=?,estimate=?,ended=?,data=? WHERE id=?',
                        (status, estimate, now(), dumps(data), ident))
        self.db.commit()


class SQLiteSpanExporter(SpanExporter):
    def __init__(self, ledger: Ledger):
        self.ledger = ledger

    def export(self, spans):
        for s in spans:
            self.ledger.record('span', {'name': s.name, 'trace_id': format(s.context.trace_id, '032x'),
                'span_id': format(s.context.span_id, '016x'), 'parent': format(s.parent.span_id, '016x') if s.parent else None,
                'start_ns': s.start_time, 'end_ns': s.end_time, 'attributes': dict(s.attributes or {})})
        return SpanExportResult.SUCCESS

    def shutdown(self):
        pass


def tracer(ledger: Ledger):
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(SQLiteSpanExporter(ledger)))
    return provider.get_tracer('MC01')


def tree_identity(path: Path) -> dict:
    return {str(p.relative_to(path)): digest(p.read_bytes()) for p in sorted(path.rglob('*'))
            if p.is_file() and not p.is_symlink() and '__pycache__' not in p.parts
            and p.suffix not in {'.pyc', '.lock'} and '.lock' != p.name}


@contextlib.contextmanager
def serial_lock():
    import fcntl
    CACHE.mkdir(exist_ok=True)
    with (CACHE / 'run.lock').open('w') as file:
        try:
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Inconclusive('Another MC01 process owns serial execution')
        yield
