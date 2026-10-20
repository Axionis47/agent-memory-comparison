# Memory lifecycle and API compatibility

Status: opt-in implementation and software contract checks, 2026-10-20. No live promotion experiment has run. No historical memory has been promoted, retired or rewritten by this work. The pilot, growth-v3 and diagnostic protocols/results remain frozen.

Verified command: `.venv/bin/python -m pytest -q tests growth/tests`, 51 passed with five existing dependency warnings. Thirteen checks cover the new lifecycle metadata mechanics. Successful live end-to-end promotion remains unverified.

The question for the next cohort is whether adding this policy to a fixed native memory implementation improves verified completion enough to justify selection expense and withheld useful memories. The independent variable is the complete lifecycle policy, enabled or disabled. Native consolidation still creates candidates. The gate controls their subsequent exposure.

## What is versioned

| Identity | Meaning |
| --- | --- |
| Logical memory | Tenant, owner, method, native namespace, layer and native item ID. Stable across revisions. |
| Content hash | Exact native text. A rewrite creates new content. |
| Metadata hash and revision | Task-family scope, API dependencies, source-run references, consolidation parents, agent/settings versions, expiry and index requirement. A metadata-only edit creates a new candidate revision, even if text is identical. |
| API dependency | Exact API identity, complete definition hash, and behaviour revision. Schema equality alone does not establish behaviour compatibility. |
| Index binding | Content hash, metadata hash, actual index version, embedding version, dimensions and normalizer version. It is separate from native knowledge. |
| Lifecycle decision | Append-only event ID and predecessor. Promotion, quarantine and retirement retain their reasons/evidence. Stale concurrent writes fail. |
| Gate policy | Hash of the declared acceptance rule. Acceptance under an older policy does not silently satisfy a newer policy. |
| Evaluation snapshot | Hash of exact revisions, statuses, index bindings and gate policy. Later edits do not rewrite a previous run's evidence. |

Metadata schema v1 is explicit. Unknown schema versions fail closed and require an explicit migration. A future migration must preserve original records, record old/new schemas and code versions, and create a new snapshot. No schema-v2 migration is implemented because no schema v2 is defined.

The model/settings fingerprint must include requested and resolved model identities, generation settings and prompt/source identities. A requested provider alias alone is insufficient. These fingerprints and API behaviour revisions are supplied by the pinned runtime, not guessed from memory text.

## How API changes affect memory

The owner of a memory records the APIs it depends on. Consolidated children inherit the dependency union and source references of their knowledge parents. Unknown dependency coverage stays unknown and prevents activation. A replacement revision records `supersedes` separately from consolidation ancestry, allowing a rebuilt procedure to target a new contract while preserving the old procedure as historical evidence.

| Change | Action |
| --- | --- |
| An unrelated API changes | Memories without that dependency stay eligible. |
| A depended-on definition or behaviour revision changes, or the API disappears | Quarantine affected current memories and derived memories carrying that dependency. Record before/after contracts. Read-time checks also reject mismatches in an older frozen snapshot. |
| Compatibility review finds unchanged text remains correct | Register a new metadata revision against the new contract, refresh its index binding if indexed, and collect fresh selection evidence. Prior success is not relabelled as evidence for the new version. |
| Arguments, response fields, permissions or behaviour invalidate the procedure | Obtain actual new-version practice, let the native mechanism revise/consolidate, and validate the resulting new revision. Do not invent corrected model lessons. |
| No safe applicable replacement exists | Retire exposure with evidence or an explicit owner-decision reference. Retain historical content and outcomes. |

`tool_versions()` hashes the supplied pinned API definitions. If a service has no per-API behaviour version, use the pinned upstream source revision as a conservative fallback. A new upstream revision can then invalidate many dependencies; do not claim per-API compatibility that has not been established. Descriptions are included in the definition hash, so documentation-only changes conservatively require review too. Hidden service changes without a version signal cannot be detected by this implementation.

Rebuilding memory and rebuilding an index are separate operations. Changed text requires a new content revision and new embedding. Unchanged text with changed scope/compatibility metadata can reuse an identical text vector, but its metadata/filter binding must be refreshed and versioned. An embedding-model, dimension or normalization change requires a new compatible index. This module rejects stale bindings; it does not perform Qdrant migrations or silently re-embed native stores.

## Candidate, activation and retirement

1. Native observation/consolidation produces a candidate revision. Keep successful and failed source experience as evidence, not automatically as recommendations.
2. Freeze a promotion plan before its first outcomes. Use separate upstream learning, promotion-selection and evaluation scenario groups. Never use evaluation feedback for promotion or subsequent learning.
3. On selection tasks, compare the same active snapshot plus this candidate with the same active snapshot without it. A candidate may be exposed only through an explicit selection-trial gate. It cannot enter ordinary evaluation that way.
4. The provisional v1 rule requires, **per declared task-family scope**, at least four conclusive pairs spanning two scenario groups, at least two paired wins and no paired losses. Ties alone do not activate memory. All planned pairs must be available and valid; missing, interrupted, truncated or request-guard-affected evidence cannot be treated as a loss or omitted to obtain acceptance. This is a conservative pilot policy, not statistical proof or a universal threshold.
5. `promote()` checks the registered plan, exact candidate revision, real learning-source references, live request classifications, actual SDK memory exposure, model/settings consistency, paired resets/prompts, other initial memory, official grades and saved-world verification. Acceptance is an append-only event bound to the revision and policy. It does not certify universal correctness.
6. A failed selection criterion leaves the candidate unvalidated. A supported contradiction or incompatible API can quarantine an active revision for review. Retirement is explicit and terminal for that revision. A revised replacement begins as a candidate; it inherits no automatic activation.

One downstream task failure does not prove that one memory caused it. Retirement based on alleged harm needs a source-bound review or candidate-removal experiment, not an automatic deletion of everything exposed in a failed task. `hold()` records such an explicit decision; autonomous diagnosis of semantic contradictions is not implemented.

## Native units and the integration boundary

Use the native delivered item as the initial gating unit: Mem0 fact, RecMem physical point/layer, Trace2Skill file, GEPA strategy and ACE whole playbook. Do not pretend whole-playbook exposure is bullet-level selective retrieval. Any later segmentation must define immutable spans, parent revisions and separate validation before use.

`memory_lifecycle.py` implements typed metadata, registry events in the existing SQLite `records` table, compatibility filtering, selection-plan checking and a read-only `GatedMemory` wrapper for the existing `select`/`export` interface. Filtering preserves native ranking and does not fill rejected positions. Lookup records preserve offered items, accepted items and rejection reasons. Packing and exact SDK exposure remain the acting harness's responsibility.

The future driver must supply public task-family mapping, current tool/agent/model identities and actual index bindings. It must import native candidates with audited provenance/dependencies, register plans, label actual selection runs `lifecycle_selection`, bind each run's `gate_validation` metadata to its plan, and freeze after promotion. The wrapper does not infer a task family from private grades, inspect reference solutions, rebuild native memories or dispatch model calls.

Tenant/owner matching here is metadata isolation, not authentication or an authorization service. Production access revocation and deletion require separate enforcement. Quarantine and retirement withhold model context; they do not erase a native store or its sensitive evidence.

## What remains before a live comparison

Freeze new source/runtime/population identities and a separate result namespace. Preserve the former native sources. Fix the shared observation projection in the new actor so measured durations do not enter model queries, applying that correction equally to gate-on and gate-off conditions. Connect native mutation/index manifests to the registry and prove a discarded training-only gate using actual configured models.

Then compare native exposure with native exposure plus the lifecycle policy on the same held-out tasks and repetitions. Keep the native agent, tool search, metadata presentation, reset state and model settings fixed. Selection and migration are extra learning/maintenance expense. A shared gate can disadvantage native methods whose delivered units are large; measure that rather than silently splitting them.

Measure official completion and paired differences; promotion/hold/quarantine/retirement counts and reasons; exact memory exposure; API-incompatible exposures (required zero); stale-index rejection; useful context withheld; adaptation after an API change; selection/rebuild/index expense; and lost conditions in consolidated descendants. An API-change intervention must be named and versioned separately from normal task outcomes.

Software checks use temporary metadata-only ledgers and in-memory status fixtures. They contain no fabricated model answers and do not establish gate usefulness or successful live promotion. The new driver, live integration smoke, index migration and held-out comparison have not been executed. Existing results cannot answer those questions retrospectively.
