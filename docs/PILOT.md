# MC01 measured comparison

Conclusive evaluation runs: 71/72.
This is a small AppWorld development pilot. Actual invoice and provider backend timing remain unknown.

| Configuration | Success/conclusive | Planned | Missing | Inconclusive | W/L/T vs baseline |
| --- | --- | --- | --- | --- | --- |
| baseline | 6/12 | 12 | 0 | 0 | 0/0/12 |
| mem0 | 4/12 | 12 | 0 | 0 | 0/2/10 |
| ace | 4/12 | 12 | 0 | 0 | 0/2/10 |
| trace2skill | 7/11 | 12 | 0 | 1 | 2/0/9 |
| gepa | 5/12 | 12 | 0 | 0 | 0/1/11 |
| recmem | 6/12 | 12 | 0 | 0 | 2/2/8 |

Current-cell coverage above uses the latest eligible attempt. Total evaluation attempts: 77; earlier inconclusive attempts: 5. Their requests, costs and original records remain retained.

## Expense, time and retained knowledge

Known cost estimates include the actual recorded learning attempts and recovery requests. Shared trace generation and excluded integration work are separate below. Times are measured boundary totals, not isolated model inference time.

| Configuration | Learning estimate USD | Evaluation estimate USD | Graded-run wall seconds | API calls | Entries | Content bytes | Delivered memory tokens |
| --- | --- | --- | --- | --- | --- | --- | --- |
| baseline | 0.000000 | 0.108138 | 280.26 | 896 | 0 | 0 | 0 |
| mem0 | 0.303737 | 0.129341 | 282.89 | 946 | 221 | 26183 | 66598 |
| ace | 0.037016 | 0.172090 | 312.04 | 377 | 14 | 4833 | 190512 |
| trace2skill | 0.034378 | 0.520538 | 287.86 | 567 | 1 | 2766 | 110532 |
| gepa | 0.200481 | 0.123125 | 275.52 | 900 | 0 | 0 | 0 |
| recmem | 0.325503 | 0.181217 | 297.73 | 902 | 129 | 30811 | 557192 |

## Repeatability

| Configuration | Agreeing task pairs | Tasks with 0 / 1 / 2 successes |
| --- | --- | --- |
| baseline | 6/6 | 3 / 0 / 3 |
| mem0 | 6/6 | 4 / 0 / 2 |
| ace | 6/6 | 4 / 0 / 2 |
| trace2skill | 5/5 | 2 / 0 / 3 |
| gepa | 5/6 | 3 / 1 / 2 |
| recmem | 6/6 | 3 / 0 / 3 |

## Mechanisms that actually executed

- baseline: commit=1.
- mem0: commit=1, mem0_add=100.
- ace: ace_delta=6, ace_operation_detail=14, commit=1.
- trace2skill: commit=1, skill_evolution=1, skill_trace_analysis=6.
- gepa: commit=1, gepa_candidate_evaluation=11, gepa_frontier=1.
- recmem: _consolidate_memory=6, arrival_checkpoint=100, commit=1, episode_merge_decision=100, generate_semantic_memories=76, recmem_arrival=100, recurrence_gate=30.
- Mem0 returned mutation events: ADD=226, DELETE=5, UPDATE=320; arrivals returning no mutation: 45. A no-mutation return is not assumed to prove a successful native NONE decision.
- RecMem observed recurrence gates: 6/30 met the native threshold; episode merges selected: 70/100. Invocation counts describe attempted mechanisms; before/after state records show their actual effects.
- GEPA retained its empty seed strategy after actual candidate testing. Its historical memory slot is identical to the baseline. Outcome differences between these two arms describe run variation and cannot establish benefit from learned instructions. Candidate testing still incurs learning expense.

Saved final states independently matched the actual completed application databases for 71 evaluation runs. The unchanged official evaluator runs in a fresh process; grading time is separately recorded in pilot-comparison.csv.

## What was actually measured

- completion: live-measured (see per-arm coverage); collection: official grades and runs. Coverage is shown in pilot-comparison.csv.
- paired_benefit: live-measured (see per-arm coverage); collection: joined conclusive task/repetition IDs. Coverage is shown in pilot-comparison.csv.
- repeatability: live-measured (see per-arm coverage); collection: two conclusive attempts per task. Coverage is shown in pilot-comparison.csv.
- learning_cost: live-measured (see per-arm coverage); collection: generation/embedding call ledger. Coverage is shown in pilot-comparison.csv.
- execution_cost: live-measured (see per-arm coverage); collection: evaluation call ledger. Coverage is shown in pilot-comparison.csv.
- timing: live-measured (see per-arm coverage); collection: OS clocks and OpenTelemetry spans. Coverage is shown in pilot-comparison.csv.
- memory_footprint: live-measured (see per-arm coverage); collection: frozen exports and selected token counts. Coverage is shown in pilot-comparison.csv.
- exposure: live-measured (see per-arm coverage); collection: selection and exposure records. Coverage is shown in pilot-comparison.csv.
- mechanism_execution: live-measured (see per-arm coverage); collection: native proposals/deltas/frontier/recurrence events. Coverage is shown in pilot-comparison.csv.
- errors_recovery: live-measured (see per-arm coverage); collection: native action/observation and error records. Coverage is shown in pilot-comparison.csv.
- coverage: live-measured (see per-arm coverage); collection: all 72 planned cells. Coverage is shown in pilot-comparison.csv.

## Accounting and limitations

Requests settled with live status: 4156. Unsettled/unknown requests: 0. Confirmed pre-dispatch rejections: 1.
Known usage estimate: $3.296138. Retained unknown reservations: $0.000000.
Readiness and smoke are excluded from quality comparisons. Shared training traces are a separate common expense. GEPA selection is learning expense. Costs with missing usage remain unknown.
Memory lookup includes embedding/count requests; do not add overlapping request and lookup times. Host load, provider scheduling/cold starts and alias revisions can affect observed latency. No isolated inference timing is claimed.
Request and cost totals include recorded integration attempts. Construction wall time covers completed attempts; these are measured project costs, not isolated algorithmic cost estimates. Token-count requests are measurement/packing overhead and are shown separately.
Only six evaluation tasks and two attempts are planned. There is one memory construction per method, no construction-variance estimate and no statistical superiority claim. Baseline wins and conclusive failures are retained.
Exposure is observable delivery, not proof that a particular memory caused success. Failure attribution is limited to observable boundaries. Grader or instrumentation errors contaminate the affected comparison.
The independent variable is the complete adapted policy, including learning, retrieval and context selection. This comparison cannot isolate an individual internal mechanism or vector store as the cause. Embedding-provider truncation statistics are recorded; an unreported resolved embedding version remains unknown.
Unknown and missing cells prevent a complete ranking. No architecture benefit is established by missing evaluations.

## Shared and excluded work

- readiness: 0 requests; known estimate $0.000000; 0 unknown-cost requests.
- smoke: 33 requests; known estimate $0.030416; 0 unknown-cost requests.
- train: 111 requests; known estimate $0.096546; 0 unknown-cost requests.
- Contaminated v1 integration cohort, excluded: 30 runs, 1594 requests, known estimate $1.033615. SQLAlchemy 2.1.5 produced inconsistent native database/grading metadata identities. All original actions, source identities, grades and artifacts remain retained. Protocol v2 rebuilt the common traces and every memory with SQLAlchemy 2.0.44 and saved-state verification; no v1 outcome enters the primary comparison.
