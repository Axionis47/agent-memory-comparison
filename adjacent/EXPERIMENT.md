# MA01: consolidation within one adjacent AppWorld task family

Status: proposed protocol, 2026-10-20. No practice, construction, review or evaluation model calls have run for MA01. Task IDs and teaching/test mappings below are selected from public instructions before outcomes. The old pilot, growth study and diagnostics remain separate.

## Question and controlled comparison

Does native RecMem consolidation make the same related practice experience more useful to the same AppWorld agent on separate, adjacent tasks? The independent variable is memory representation: absent, raw experience, or experience processed by native consolidation. The primary consolidation contrast is consolidated versus raw. Each memory condition is separately compared with no memory to measure the value of retaining experience at all.

Begin with one released consolidation mechanism rather than another five-way comparison. RecMem provides an explicit raw store, recurrence gate, episodic consolidation/merging and semantic refinement. This study tests that consolidation mechanism adapted to AppWorld. It does not reproduce published scores or rank memory architectures.

The three configurations are:

| Condition | Retained context |
| --- | --- |
| No memory | Empty cross-task memory slot. |
| Raw memory | All normalized experience units from the same three actual practice attempts, retained without summaries, merging, semantic extraction or deletion. |
| Consolidated memory | All remaining raw items plus native episodic and semantic items produced by RecMem from precisely the same ordered units. |

The hypothesis is that consolidation preserves a conditional procedure while reducing redundant context and execution work. Equal or worse completion, lost conditions, increased context, or no reduction in execution expense would limit or refute those proposed benefits. The preregistration seed for item sampling and diagnostic ordering is `memory-adjacent-v1`. Population selection is a deliberate public-instruction-based family choice, not a random benchmark sample.

The main comparison uses **complete frozen family-memory exposure**, not similarity search. Every stored item in that condition is supplied to both the common tool-search model and action model before each decision. This removes semantic retrieval selection as an explanation for the main contrast. Do not call whole-artifact exposure selective retrieval.

There is no memory-item clipping, top-k selection or hand-picked helpful subset in the main comparison. Count complete requests against the provider's verified context capacity before dispatch. If either frozen artifact cannot fit with the initial common task prompt, stop setup and report that limitation without dropping items. If within-task history later exceeds provider capacity, preserve the attempt as operationally inconclusive, not a task failure. Do not secretly add another summarizer.

## Exact tasks and what can transfer

All six tasks are upstream AppWorld tasks. No tasks, gold target sets or reference answers are authored here. The two scenario groups have no recorded attempts in results/ledger.sqlite or the growth-v1/v2/v3 ledgers at selection time. They are therefore unused by our runs, unlike the previously examined grocery and file cases. Public instruction inspection is part of this preregistration, not model-quality evidence.

### Shared practice, once, in this order

The upstream acting agent starts from fresh state with **no cross-task memory** for each of these three attempts. Both memory constructors later receive the complete identical corpus, including failures.

| Task | Official instruction, abbreviated | Learning opportunity, not an inserted lesson |
| --- | --- | --- |
| `afc0fce_1` | Comment “Thank you!” on payments received from coworkers in the last 5 days, including today, and like them. | Discover relationship information, resolve counterparties, inspect received transactions, apply a time window and perform two requested actions. |
| `afc0fce_2` | Comment “Thanks!” on payments received from friends in the last 7 days, including today, and like them. | Encounter the same workflow with a different relationship, time window and comment. These are task parameters, not universal constants. |
| `afc0fce_3` | Comment “Thank you so much!” on payments received from roommates in the last 10 days, including today, and like them. | A third related experience makes repetition and variation observable. It gives consolidation an opportunity to preserve a reusable procedure and its conditions. |

These are opportunities. What the source agent actually did, what succeeded and what the native consolidator actually retained must be reported separately. If it made mistakes, preserve them and their official feedback. Never replace them with the intended procedure in this table.

### Evaluation, separate scenario group

| Task | Official instruction | Earlier experience it can use | What is deliberately different |
| --- | --- | --- | --- |
| `df61dc5_1` | Like all the venmo transactions of the ongoing year to and from my roommates. | Roommate resolution from practice 3; relationship/date filtering and liking across all practice. | Both payment directions, current calendar year, and liking without commenting. |
| `df61dc5_2` | Like all the venmo transactions of the ongoing month to and from my friends. | Friend resolution from practice 2 and the repeated filtering workflow. | Both directions and current calendar month, rather than received-only over the last 7 days; no comments requested. |
| `df61dc5_3` | Like all the venmo transactions of the ongoing year to and from my coworkers. | Coworker resolution from practice 1 and the repeated workflow. | Both directions and current calendar year, rather than received-only over the last 5 days; no comments requested. |

The shared skill is **relationship-based transaction selection followed by the actions requested now**. Sharing an app name alone is not the rationale. The controlled variation tests whether memory preserves relationship, time, direction and action conditions, instead of turning earlier task constants into unconditional advice. Use AppWorld's simulated current date, not host calendar time.

This is narrow transfer between two scenario groups. It is not benchmark-wide generalisation, and three practice variants from one group do not estimate learning variance across independent histories.

## Construction, metadata and acting

1. Use pinned AppWorld `42b5bcf3cd334fee33f0c37c02070a9f5807add5`, task data `0.2.0`, RecMem `a84252f6e5587fd4a8caac03ec9f6c732b7a7f35`, the existing Python runtime and upstream `SimplifiedReActCodeAgent`. Freeze exact source, dependency, prompt and API-definition identities before live dispatch.
2. Keep Gemini 2.5 Flash via measured Vertex ADC, temperature 0, thinking 0 and the existing generation settings equal across conditions. Record and enforce the same actual resolved model version. Use the configured Gemini embedding model at 1536 dimensions for native construction and diagnostic indexes. All generation/embedding evidence must be live; provider failures stop dispatch.
3. Generate the three practice attempts once. Normalize public instructions, executed actions, visible observations, actual completion answers and separate official success/failed-requirement feedback. Exclude private expected values/reference solutions. Redact observed credentials, including standalone printed passwords and JWTs, in learning copies. Retain original evidence privately.
4. Form one task-start unit, one unit per distinct executed action/observation and one completion/feedback unit per completed practice attempt. Each unit has an immutable source-unit ID, source task/run/step, simulated task time and source-world identity. Do not replay arrivals, split messages to manufacture recurrence, or inject hand-written lessons. Historical people, IDs and dates retain their provenance; they are not asserted as current-world facts.
5. Raw condition: reproduce the native raw payload format and use native `SubconsciousMemory.add`, with actual measured embeddings, deterministic unit identities and no calls to the gate, episode merge, episode generation or semantic refinement. Assert every input unit is retained once and higher layers remain empty.
6. Consolidated condition: pass those exact units in order through native `RecMem.add_memory`. Preserve recurrence count 6, similarity .7, episode-merge threshold .75 and semantic refinement enabled. Capture gate hits, actual operation inputs, point IDs and every before/after change. Recurrence counts arrivals, not six independent tasks. Native raw-item deletion after consolidation is part of this condition; the original source corpus remains canonical evidence.
7. Export after practice items 1, 2 and 3. These are content/footprint checkpoints, not additional task evaluations. Record distinct source tasks and source-unit ancestry for every consolidation output, explicitly distinguishing conservative operation ancestry from claim-level support. No archived memory is restored.
8. Before evaluation, require a verified native accepted consolidation or merge and at least one derived item delivered by a read-only practice-source probe. If the mechanism never activates, report an inactive mechanism, preserve all construction evidence and do not pretend identical memories estimate consolidation. Do not lower thresholds or repeat inputs to force activation.
9. Version content, metadata, source lineage, native store and rendered context. Both memory conditions carry the same family scope and API compatibility rules. Record dependencies using API definition hashes plus pinned upstream behaviour revision, and reject mismatches. No API-change intervention is mixed into this comparison.
10. Freeze every final artifact and its full-context rendering. Render source provenance consistently; do not deduplicate, repair or selectively omit native generated content. The teaching/test map and reviewer findings never enter agent prompts as lessons.

The agent loop remains: task and current observations, complete frozen family memory, common tool-search query, current API definitions, upstream agent's executable Python, AppWorld result, then repeat or request completion. Keep all native tools/documentation available. Tool search supplies context, not execution permission.

Correct the shared observation projection in the new cohort before freezing: retrieval/tool-search inputs contain only the public task and latest action/result, excluding measured durations, host timestamps and instrumentation fields. Apply the correction identically to all conditions. Preserve the old frozen actor source; implement the new binding/adapter in the new cohort namespace without creating another agent framework.

Do not enable the separate promotion/retirement gate in this comparison. It would add another selection policy and learning expense to the question. These are explicitly unvalidated research exposures, not product activations. The lifecycle metadata/version concepts still apply. No evaluation result promotes an item or changes later memory.

## Runs and exact measurements

Three evaluation tasks × three conditions × three repetitions = **27 planned evaluation attempts**, plus three common practice attempts. Discarded training-only integration checks and maintenance/review calls are separate expenses, never extra evaluation samples. Use an already-known training task outside these two groups for discarded integration checks, with its stores discarded.

For each repetition and task, rotate the order of `[none, raw, consolidated]` by `(task_index + repetition) % 3`. Every condition occupies each position once per task across the three repetitions. Execute all requests serially. Reset AppWorld state and within-task history for every attempt, verify equal logical initial states and prompts, and keep memory immutable. Use the unchanged official evaluator in a fresh subprocess and verify saved versus actually completed state.

| Measure | Exact comparison and intended improvement |
| --- | --- |
| Task completion, primary | Official success / eligible attempts, alongside nine planned evaluations per condition. Consolidated versus raw isolates the complete consolidation treatment; raw/consolidated versus none measures retained-experience effects. Report paired wins/losses/ties and unmatched cells on task/repetition identities. Aim: more correctly completed tasks, without promising a gain. |
| Correct scope and actions | Preserve official requirement failures. Separately audit calls to `venmo.create_transaction_comment` and new comment records in evaluation, where no comments were requested. Distinguish attempted calls from persisted effects. Aim: avoid carrying over old action requirements. Do not invent expected transaction sets or infer an incorrect direction/time boundary from a generic failed assertion. |
| Execution efficiency | Actual API-call counts, model requests and input/output tokens per attempt. Compare differences on matched pairs where both passed, with their denominator. Aim: fewer repeated documentation lookups, corrections and decisions while maintaining completion. |
| Total expense | Shared practice separately; native construction, embeddings, reviews, execution and maintenance separately. Report measured requests/tokens, estimates and unknown cost. Aim: execution savings that can be assessed against consolidation expense. Token compression alone is not task improvement. |
| Repeatability | For each task/condition, 0/1/2/3 passes and whether all three agree. Small samples and one source history cannot establish statistical superiority. |
| Consolidation footprint | Raw/episodic/semantic counts and content bytes at source checkpoints 1/2/3; serialized/native-index overhead separately. Full-context tokens actually delivered to each search/action request. Consolidation may increase total stored content; record that. |
| Fidelity | Source-bound live review of up to ten final changed consolidated items, chosen by SHA-256(seed + item version) before evaluation outcomes. Classify supported, contradicted, unsupported or ambiguous; record lost relationship/time/direction/action conditions. Reviewer labels are not benchmark truth and never rewrite memory. |
| Consolidation mechanics | Trigger counts, similarity scores, raw consumption/deletion, episode creation/merges, semantic refinement and exact lineage, including units consumed without accepted retained knowledge. Report no activation or no cross-task ancestry explicitly. |
| Errors and stopping | Observable invalid arguments, API/model-format errors, repeated calls, recovery, completion request and official outcome. Locate the earliest observable broken boundary without inventing hidden reasoning. |
| Integrity | Planned, attempted, eligible, failed, missing, operationally inconclusive and excluded counts; model/prompt/API/reset/native/context versions; exact SDK exposures; unchanged frozen memory and no evaluation feedback entering learning. |

If no-memory already succeeds on all cases, report the ceiling and expense trade-off. Do not swap tasks or rerun failures to manufacture a quality improvement. Provider truncation, context overflow, unresolved requests, watchdogs and AppWorld request guards are operationally inconclusive for completion comparison. Preserve any official grade, all calls and costs. Resume only missing or inconclusive work after reconciling uncertainty; never selectively repeat a conclusive failure.

## Separate retrieval audit, without changing the main task comparison

The earlier RecMem diagnostics retrieved an old dinner-payment episode for groceries and a Spotify episode for files. Verified delivery did not establish semantic relevance. This plan does not attribute that problem to consolidation by letting similarity search choose the main task context.

At each source checkpoint, query each condition with every already-seen practice instruction plus the first actual observed execution error for that task, if any. At the final freeze, also probe the three public evaluation instructions before evaluation begins. These probes never use evaluation answers or grades, never change memory, and never inject reviewer advice into the agent. For an apples-to-apples diagnostic, build one derived exact-cosine Qdrant view per condition from its canonical export, with the same embedding configuration. Retrieve all scores, sort by descending score and immutable item ID, retain ten whole items, and record queries, ranks, scores, identities, content and index versions. This is a common diagnostic retriever, not RecMem's released layered search.

Also run the released `RecMem.search_memories` read-only on both stores for those same queries. Preserve its layer-specific retrieval settings: up to ten raw, five episodic and ten semantic results, with semantic threshold 0. Record native identities, scores and actual layer results, including empty results. This native-path audit diagnoses the integration the user asked about; it is separate from the common flat-index diagnostic and neither chooses main task context. Verify stores remain byte/content-equivalent at the canonical export boundary after each audit.

Measure whether an item with ancestry to the queried source experience is reachable. Also perform a source-bound live review of the returned query/item pairs for task applicability: applicable procedure, historical fact needing fresh lookup, conflicting condition, unrelated, or ambiguous. Record relationship, time-window, payment-direction and requested-action mismatches separately. Report counts and denominators by query and layer, without inventing a complete gold relevant-item set or treating every item from the same app as relevant. Source-linked hit rate is not universal relevance recall or proof of usefulness. These probe results do not select the main memory subset or tune construction. No-memory has no index. Charge probe/index/review work separately.

A subsequent behavioral retrieval experiment can compare full-context exposure with ranked retrieval on the same frozen memory. It is not part of the 27 evaluations here. API-version changes, automatic retirement, growth across unrelated families and the five-way architecture comparison are also separate questions.

Keep one ledger, report, comparison table and private compressed evidence bundle under the new MA01 results namespace. Reuse installed dependencies and benchmark data. Do not duplicate archive trees or per-call report files. Threats include source-history variance, public task inspection, close-family selection, consolidation/generation variance, provider aliases, execution order, host load, cold starts, missingness, grading defects, full-context feasibility and measurement overhead. Completion is reconciled evidence and a conditional explanation, including regression, no gain or an inactive mechanism.
