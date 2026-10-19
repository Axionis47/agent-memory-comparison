# Agent memory comparison

Five released memory mechanisms connected to the same AppWorld acting agent: Mem0, ACE, Trace2Skill, GEPA and RecMem, alongside a no-memory baseline.

The agent executes Python actions against applications, reads results and decides what to do next. Memory supplies knowledge learned from earlier experience. This project records what each mechanism learned, what reached the agent, the actions that followed, official task outcomes and execution expense.

## Start with the code study

Read the [code study and executed findings](docs/CODE-STUDY.md) for the implementation walkthrough: what the released algorithms do, what the adapters change, how learning reaches actions, which defects were repaired, and what the executed evidence supports. It is the main explanation of the project. The [task examples](docs/FINDINGS.md) supply the concrete cases and costs.

## Measured work

- **Pilot comparison:** 71 official grades across 72 evaluation cells and 77 actual attempts. One cell remained inconclusive. GEPA retained an empty strategy in this pilot.
- **Concrete mechanism examples:** fact retrieval, playbook lessons, evolved procedures and consolidated experiences supplied during real tasks, including irrelevant retrieval and failed attempts.
- **GEPA retention case:** 14 candidate-testing task attempts produced a selected instruction that was saved, reopened and supplied during two fresh attempts. Matching empty-memory controls were also executed.

| GEPA follow-up task | Retained instruction | Empty memory |
| --- | --- | --- |
| Reject payment requests from friends and roommates | Pass, 36 API calls | Fail, 26 API calls |
| Rename and move files using creation dates | Pass, 156 API calls | Pass, 156 API calls |

These are known-case observations. They do not establish consistent improvement, generalisation or a winning architecture. A memory being supplied is not proof that it caused success.

Read the [concrete examples and trade-offs](docs/FINDINGS.md), [pilot measurements](docs/PILOT.md), [recorded actions](evidence/cases.json) and [actual retained instruction](evidence/gepa-retention.json).

## Integration

```text
Task and latest observation
  -> native memory selection or whole-artifact exposure
  -> tool-search query and current API definitions
  -> same agent chooses Python actions
  -> AppWorld executes and returns observations
  -> official evaluation after completion
  -> scheduled learning from practice experience
```

The executed integration is in [growth/memory.py](growth/memory.py) and [growth/agent.py](growth/agent.py). The earlier pilot source is under [mc/](mc/). Released components, pinned revisions and adaptations are documented in [FIDELITY.md](FIDELITY.md) and [THIRD_PARTY.md](THIRD_PARTY.md).

## Inspect and verify

```sh
python3 tools/verify_release.py
```

This checks published file identities, recorded outcome consistency, Python syntax and local links without network or model calls. The original local source passed 35 software checks; the publication copy also passed its 16 pilot contract tests using the installed local dependencies. These checks are separate from live-model evidence.

The code snapshot used Python 3.12.8 and pinned dependencies with Gemini through Vertex application default credentials. The original experiment commands require local configuration, upstream downloads and private historical ledgers. A clean-machine installation has not been verified. This source snapshot is not a turnkey replay of the original runs.

## Evidence scope

Public action records and reports are sanitised derivatives of executed live runs. Raw observations, SDK conversations, application databases, credentials and downloaded dependencies are excluded. Original task outcomes are exported from the recorded official grades; the public action export alone cannot independently regrade them.

The findings include failures, integration defects and counterexamples. Single attempts, repeated known tasks, execution order, provider timing, host load, model alias changes, missing outcomes and instrumentation overhead limit interpretation. No completed long-term memory-growth result is claimed.

No project-wide reuse license has been selected for the original integration code. Third-party notices and the bundled validator's Apache-2.0 license are retained.
