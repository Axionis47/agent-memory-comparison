Public sanitised derivative of executed live evidence. Raw observations, SDK conversations, credentials and application databases are excluded. Exported grades cannot independently regrade tasks. Local private evidence remains available separately.

# Trace2Skill, GEPA and RecMem: repeated exposure and removal checks

One current AppWorld acting integration, three common upstream tasks, two fresh-world repetitions per condition. Full, withheld and specific-item removal conditions were all registered before new outcomes. Learning histories differ; this is a within-policy diagnostic, not an architecture ranking.

Coverage: {'planned': 54, 'attempted': 54, 'conclusive': 54, 'missing': 0, 'inconclusive': 0, 'running': 0, 'all_attempts': 54, 'completion_comparison_eligible': 53, 'operationally_inconclusive': 1}. Raw official grades remain unchanged. Operationally affected attempts remain in traces and expense totals but are excluded from completion comparisons. The request-guard check is applied to every attempt regardless of grade.

| Method | Task | Full memory | Withheld | Target removed | Excluded full/off/removed | Removal opportunities |
| --- | --- | --- | --- | --- | --- | --- |
| trace2skill | 530b157_1 | 0/2 | 0/2 | 2/2 | 0/0/0 | 29 |
| trace2skill | 6ea6792_2 | 0/2 | 1/2 | 0/2 | 0/0/0 | 18 |
| trace2skill | 68ee2c9_2 | 2/2 | 1/1 | 2/2 | 0/1/0 | 25 |
| gepa | 530b157_1 | 0/2 | 2/2 | 1/2 | 0/0/0 | 36 |
| gepa | 6ea6792_2 | 1/2 | 1/2 | 2/2 | 0/0/0 | 31 |
| gepa | 68ee2c9_2 | 2/2 | 2/2 | 2/2 | 0/0/0 | 28 |
| recmem | 530b157_1 | 0/2 | 1/2 | 1/2 | 0/0/0 | 33 |
| recmem | 6ea6792_2 | 0/2 | 1/2 | 0/2 | 0/0/0 | 30 |
| recmem | 68ee2c9_2 | 2/2 | 2/2 | 2/2 | 0/0/0 | 25 |

Each task/condition has two planned attempts. Fractions use eligible completion comparisons. Excluded attempts are operationally inconclusive, not invented task failures.


## Paired outcomes

Wins/losses/ties below compare full memory with the named condition on the same task and repetition.

| Method | Task | Full vs withheld W/L/T | Full vs removal W/L/T | Unmatched off/removal | Full target exposure decisions |
| --- | --- | --- | --- | --- | --- |
| trace2skill | 530b157_1 | 0/0/2 | 0/2/0 | 0/0 | 38 |
| trace2skill | 6ea6792_2 | 0/1/1 | 0/0/2 | 0/0 | 30 |
| trace2skill | 68ee2c9_2 | 0/0/1 | 0/0/2 | 1/0 | 22 |
| gepa | 530b157_1 | 0/2/0 | 0/1/1 | 0/0 | 36 |
| gepa | 6ea6792_2 | 1/1/0 | 0/1/1 | 0/0 | 30 |
| gepa | 68ee2c9_2 | 0/0/2 | 0/0/2 | 0/0 | 24 |
| recmem | 530b157_1 | 0/1/1 | 0/1/1 | 0/0 | 37 |
| recmem | 6ea6792_2 | 0/1/1 | 0/0/2 | 0/0 | 18 |
| recmem | 68ee2c9_2 | 0/0/2 | 0/0/2 | 0/0 | 27 |

## Operational exclusions

An official grade after a recovered request-limit error is preserved as an official observation. It cannot establish completion quality without that operational bound. No limit was increased, no failure erased and no conclusive attempt selectively rerun.

- `b1628b21b5a14bb88b993f614e33ffa9` (trace2skill, 68ee2c9_2, memory_off, repetition 0): official success `0`; [{"decision": 11, "boundary": "AppWorld per-execution request guard", "observation": "Exception: Number of requests exceeded the limit of 1000. This potentially means that you have an infinite loop in your code."}]. Excluded from paired completion estimates.

## What changed in concrete attempts

These examples describe recorded actions and outcomes. They do not infer hidden reasoning. The tables above include both repetitions, including contrary outcomes.

### trace2skill: 530b157_1

Across both grocery repetitions, full memory failed twice and withheld memory failed twice, while removing Best Practices passed twice. Both passing attempts searched messages for "how much was yesterday's grocery?" and paid 54. The four failing attempts paid 25. The removed section gives generic advice about variables, API parameters and response inspection; it does not contain a grocery procedure. This is a repeated response to a content-group intervention, not evidence that generic best practices are always harmful or that the remaining skill taught the exact query.

First-repetition trace identities:

- memory_on: `cb55d2c0e0c54eb39529fe4322b54022`, official success `0`.
- memory_off: `5a945f4f802c42c7a599a98f7aa91166`, official success `0`.
- target_removed: `e615ce3787274a18a4398f36ed3a3509`, official success `1`.

### trace2skill: 68ee2c9_2

In the first file-task repetition, full and section-removed memory passed. The withheld attempt failed the official file-renaming requirement, but also hit AppWorld's 1,000-request guard during a loop that kept renaming the first remaining file. It is operationally inconclusive for completion comparison, despite the later official grade. Its 1,157 recorded API calls remain charged. The second withheld attempt passed. There is no clean paired completion win here. The passing full-memory attempts used separate rename and move phases, but the remaining skill does not explicitly teach this file workflow.

First-repetition trace identities:

- memory_on: `b580eb2c739d4021a9b1d762b5fcc402`, official success `1`.
- memory_off: `b1628b21b5a14bb88b993f614e33ffa9`, official success `0`.
- target_removed: `c576ce3a25e54b10bf78d180f2131a6c`, official success `1`.

### gepa: 6ea6792_2

In the first payment-request repetition, full memory failed after issuing denials for every pending request without a phone-contact lookup. Both withheld and target-removed attempts looked up friend and roommate relationships and passed. The removed group contains tracking instructions and a prohibition on re-querying. This is a plausible scope mismatch for a strategy learned on file operations, not proof that one sentence caused the error or that GEPA generally harms payment tasks.

First-repetition trace identities:

- memory_off: `bb8c5922bb78482f80020223a2f7d3d6`, official success `1`.
- target_removed: `e20c7948acd84b0a8f1e99dbd5300eaa`, official success `1`.
- memory_on: `80a2a91e31474a2c9f9a515b84a3e8b9`, official success `0`.

### recmem: 530b157_1

In the first grocery repetition, full and target-removed memory both paid 25 and failed the amount requirement. Withheld memory paid 54 and passed. The removed point concerns an earlier coworker payment-request task, not this grocery debt. Its removal did not repair that first failure. The wrong 25 also appears in the current conversation, so the trace does not establish copying an amount from memory.

First-repetition trace identities:

- target_removed: `ebfcdcc27d1148b69bee50f9be6d9d34`, official success `0`.
- memory_on: `6d0ad1204cd1433ba6ec0e8b8d15dfec`, official success `0`.
- memory_off: `a4de9a67baf84b8f9bde2fd48b33c3bd`, official success `1`.

## Why more elapsed time is not the diagnosis

Earlier construction and practice produced persistent changed memories. In this diagnostic those stores are frozen: repeating a task does not trigger further consolidation. The unfinished growth study has not established whether a larger and more varied practice history improves these policies.

Native consolidation reorganises or summarises experience; it does not certify that a lesson is correct, applies to this task, or remains current. Retrieval similarity is not a task-applicability check. Whole-skill or whole-strategy exposure can also introduce irrelevant guidance. An action model still has to select the right live evidence and execute valid actions.

Our integration owns experience formatting, credential projection, retrieval queries, exposure scheduling and the shared discovery boundary. Historical input defects and the current actor adaptation are disclosed below. The released learning mechanisms own their native mutations. These data do not isolate architecture-wide weaknesses from every integration choice. No dependable general freshness or failed-guidance retirement controller was implemented. Diagnostic item withholding is not autonomous retirement.

The frozen pilot RecMem store used here contains 0 raw items, 6 episodic items, 123 semantic items. This shows retained episodic and semantic content already exists; it does not certify the correctness or usefulness of those items. Recurrence counts incoming pieces of experience, not necessarily independent successful tasks.

Actual RecMem native lookup result sizes before removal and packing: 5 episodic, 10 semantic on 245 lookups. Similarity-ranked results are not guaranteed to concern the current application or goal.


## Frozen tasks

- `530b157_1`: Kristin paid for my grocery recently as my payment cards were not working at the time. Send them the owed money with a description note "Groceries" as per my phone text conversation, and then send them a phone text message, "It is done.".
- `6ea6792_2`: Reject all pending Venmo payment requests from my friends and roommates.
- `68ee2c9_2`: In my file system, add the prefix "YYYY_MM_DD-" to all file names in the ~/downloaded_files/ directory, based on their creation dates, and then move all files not from this year to ~/recycle_bin/.

## Executed money-task actions

Values come from actual API-call arguments, not inferred model intent. Each entry is a separate fresh-world attempt. Missing contact lookup does not by itself prove the first broken contract.

| Method | Task | Repetition | Condition | Payment amount arguments | Contact relationships queried | Denial API calls | Pass |
| --- | --- | --- | --- | --- | --- | --- | --- |
| trace2skill | 530b157_1 | 0 | memory_on | [25.0] | ["None"] | 0 | False |
| trace2skill | 530b157_1 | 0 | memory_off | [25.0] | ["None"] | 0 | False |
| trace2skill | 530b157_1 | 0 | target_removed | [54.0] | ["None"] | 0 | True |
| gepa | 530b157_1 | 0 | memory_off | [54.0] | ["None"] | 0 | True |
| gepa | 530b157_1 | 0 | target_removed | [50.0] | ["None"] | 0 | False |
| gepa | 530b157_1 | 0 | memory_on | [25.0] | ["None"] | 0 | False |
| recmem | 530b157_1 | 0 | target_removed | [25.0] | ["None"] | 0 | False |
| recmem | 530b157_1 | 0 | memory_on | [25.0] | ["None"] | 0 | False |
| recmem | 530b157_1 | 0 | memory_off | [54.0] | ["None"] | 0 | True |
| gepa | 6ea6792_2 | 0 | memory_off | [] | ["friend", "roommate"] | 14 | True |
| gepa | 6ea6792_2 | 0 | target_removed | [] | ["friend", "roommate"] | 14 | True |
| gepa | 6ea6792_2 | 0 | memory_on | [] | [] | 21 | False |
| recmem | 6ea6792_2 | 0 | target_removed | [] | [] | 8 | False |
| recmem | 6ea6792_2 | 0 | memory_on | [] | [] | 21 | False |
| recmem | 6ea6792_2 | 0 | memory_off | [] | ["friend", "roommate"] | 14 | True |
| trace2skill | 6ea6792_2 | 0 | memory_on | [] | [] | 21 | False |
| trace2skill | 6ea6792_2 | 0 | memory_off | [] | [] | 8 | False |
| trace2skill | 6ea6792_2 | 0 | target_removed | [] | [] | 21 | False |
| gepa | 530b157_1 | 1 | memory_on | [50.0] | ["None"] | 0 | False |
| gepa | 530b157_1 | 1 | target_removed | [54.0] | ["None"] | 0 | True |
| gepa | 530b157_1 | 1 | memory_off | [54.0] | ["None"] | 0 | True |
| recmem | 530b157_1 | 1 | memory_off | [25.0] | ["None"] | 0 | False |
| recmem | 530b157_1 | 1 | memory_on | [25.0] | ["None"] | 0 | False |
| recmem | 530b157_1 | 1 | target_removed | [54.0] | ["None"] | 0 | True |
| trace2skill | 530b157_1 | 1 | target_removed | [54.0] | ["None"] | 0 | True |
| trace2skill | 530b157_1 | 1 | memory_off | [25.0] | ["None"] | 0 | False |
| trace2skill | 530b157_1 | 1 | memory_on | [25.0] | ["None"] | 0 | False |
| recmem | 6ea6792_2 | 1 | memory_off | [] | [] | 8 | False |
| recmem | 6ea6792_2 | 1 | memory_on | [] | [] | 21 | False |
| recmem | 6ea6792_2 | 1 | target_removed | [] | ["Friend", "Roommate"] | 14 | False |
| trace2skill | 6ea6792_2 | 1 | target_removed | [] | [] | 21 | False |
| trace2skill | 6ea6792_2 | 1 | memory_off | [] | ["friend", "roommate"] | 14 | True |
| trace2skill | 6ea6792_2 | 1 | memory_on | [] | ["friend", "roommate"] | 3 | False |
| gepa | 6ea6792_2 | 1 | memory_on | [] | ["friend", "roommate"] | 14 | True |
| gepa | 6ea6792_2 | 1 | target_removed | [] | ["friend", "roommate"] | 14 | True |
| gepa | 6ea6792_2 | 1 | memory_off | [] | [] | 8 | False |

## Exact removal targets

Trace2Skill removal withholds the learned Best Practices section, retaining the remaining skill. GEPA removal withholds strategy steps 2 and 3 about updated identifiers/paths, retaining initial listing and applicability conditions. RecMem removal withholds the single episodic point ranked first by native retrieval for the initial task query. Native retrieval continues, and no replacement item is backfilled. A selected target is not assumed relevant or useful.

### trace2skill: Best Practices section

Source version: `166264550a4405a8646ae471bd23eeab83aaca8e04b46a73eace13fa8ce6d443`. Item: `SKILL.md`. Task: `530b157_1`.

````text
## Best Practices
- **Double-check variable names**: Ensure variable names are spelled correctly, especially when referencing them after assignment. Typos can lead to `NameError`.
- **Verify API call parameters**: Always confirm that the parameters passed to API functions match the expected arguments (e.g., `access_token`, `note_id`, `content`).
- **Inspect API responses**: After making an API call, examine the response to understand its structure and confirm success or identify errors.

````

### gepa: tracking changes and subsequent updated-path operations

Source version: `55ce8a7f698def271ab666bb2e5350f76e8061d0505d7a6d39a5c5fb36b48640`. Item: `gepa-artifact`. Task: `530b157_1`.

````text
2. **Process and Track Changes:**
   - Iterate through this initial list.
   - For each item, perform the required operations (e.g., rename, modify).
   - Crucially, if an operation changes an item's identifier or path, immediately update your internal tracking of that item's *new* identifier/path. If subsequent operations depend on the updated identifier/path, ensure this updated information is stored and used.

3. **Subsequent Operations on Updated List:** When performing a second phase of operations (e.g., moving files that were renamed in the first phase), iterate through the list of *updated* identifiers/paths generated in step 2. Do not re-query the system for the items unless absolutely necessary, as this can lead to inconsistencies if the system's state has changed due to your previous actions. If the original list of items is used for subsequent operations after modifications, it will lead to errors because the original identifiers/paths may no longer exist.


````

### recmem: highest-ranked native episodic result for the initial task query

Source version: `cdddb4cf27f0b3f53f3cf7571b8dd41289796b4d794b370942952311e6e7fed6`. Item: `73117630-50b6-4602-8a06-0a3fc7db9c23`. Task: `530b157_1`.

````text
On 2026-10-19, the user requested to make Venmo payment requests to coworkers for a dinner bill they paid the day before. They had already noted individual shares and some coworkers had already paid. The assistant then accessed the Venmo API to understand how to create payment requests. Later on 2026-10-19, the assistant used the Venmo API to check which coworkers had already paid for the dinner bill from the day before, identifying Stacy, Allison, Travis, Kristin, and Kayla as having paid. Afterwards, on 2026-10-19, the assistant identified the unpaid coworkers as Stephen (33.0), Sabrina (32.0), Jamie (31.0), and Anita (32.0). The assistant then further investigated the Venmo API documentation for creating payment requests, specifically looking at the `create_payment_request` function, to understand its parameters and requirements. Later on the same day, the assistant retrieved the emails for the unpaid coworkers: Stephen ([EMAIL REDACTED]), Sabrina ([EMAIL REDACTED]), Jamie ([EMAIL REDACTED]), and Anita ([EMAIL REDACTED]). Subsequently, on 2026-10-19, the assistant successfully sent Venmo payment requests to Stephen ($33.0, payment_request_id: 6097), Sabrina ($32.0, payment_request_id: 6098), Jamie ($31.0, payment_request_id: 6099), and Anita ($32.0, payment_request_id: 6100) for "Dinner with Colleagues". Following this, on 2026-10-19, the assistant confirmed that the payment requests were sent to the unpaid coworkers. Later on 2026-10-19, the assistant received feedback indicating that the payment requests sent to unpaid coworkers failed a test asserting that the answers match, specifically that 'payment requests sent to unpaid coworkers.' was not equal to 'null'.
````

### recmem: highest-ranked native episodic result for the initial task query

Source version: `cdddb4cf27f0b3f53f3cf7571b8dd41289796b4d794b370942952311e6e7fed6`. Item: `73117630-50b6-4602-8a06-0a3fc7db9c23`. Task: `6ea6792_2`.

````text
On 2026-10-19, the user requested to make Venmo payment requests to coworkers for a dinner bill they paid the day before. They had already noted individual shares and some coworkers had already paid. The assistant then accessed the Venmo API to understand how to create payment requests. Later on 2026-10-19, the assistant used the Venmo API to check which coworkers had already paid for the dinner bill from the day before, identifying Stacy, Allison, Travis, Kristin, and Kayla as having paid. Afterwards, on 2026-10-19, the assistant identified the unpaid coworkers as Stephen (33.0), Sabrina (32.0), Jamie (31.0), and Anita (32.0). The assistant then further investigated the Venmo API documentation for creating payment requests, specifically looking at the `create_payment_request` function, to understand its parameters and requirements. Later on the same day, the assistant retrieved the emails for the unpaid coworkers: Stephen ([EMAIL REDACTED]), Sabrina ([EMAIL REDACTED]), Jamie ([EMAIL REDACTED]), and Anita ([EMAIL REDACTED]). Subsequently, on 2026-10-19, the assistant successfully sent Venmo payment requests to Stephen ($33.0, payment_request_id: 6097), Sabrina ($32.0, payment_request_id: 6098), Jamie ($31.0, payment_request_id: 6099), and Anita ($32.0, payment_request_id: 6100) for "Dinner with Colleagues". Following this, on 2026-10-19, the assistant confirmed that the payment requests were sent to the unpaid coworkers. Later on 2026-10-19, the assistant received feedback indicating that the payment requests sent to unpaid coworkers failed a test asserting that the answers match, specifically that 'payment requests sent to unpaid coworkers.' was not equal to 'null'.
````

### recmem: highest-ranked native episodic result for the initial task query

Source version: `cdddb4cf27f0b3f53f3cf7571b8dd41289796b4d794b370942952311e6e7fed6`. Item: `d4212623-2ebb-412a-88fb-0ede4146f924`. Task: `68ee2c9_2`.

````text
On 2026-10-19, the user initiated a task to clean up their Spotify libraries, aiming to retain only liked or downloaded songs and albums (where an album is downloaded if all its songs are downloaded). The user specified that their playlist library should remain unchanged for the time being. Prior to this, the assistant had accessed Spotify API descriptions and details for song recommendations, and also retrieved the user's Spotify password. Later on the same day, the assistant executed code to retrieve all songs in the user's Spotify library, finding a total of 20 songs. Afterwards, on 2026-10-19, the assistant executed code to retrieve all liked songs, finding a total of 11 liked songs. Later on 2026-10-19, the assistant executed code to retrieve all downloaded songs, finding a total of 21 downloaded songs. Later on 2026-10-19, the assistant executed code to identify songs that are neither liked nor downloaded, finding 12 such songs to remove from the library. Later on 2026-10-19, the assistant executed code to remove these 12 songs from the user's Spotify library. Later on 2026-10-19, the assistant executed code to retrieve all albums in the user's Spotify library, finding a total of 7 albums. Later on 2026-10-19, the assistant executed code to retrieve all liked albums, finding a total of 6 liked albums. Later on 2026-10-19, the assistant executed code to identify downloaded albums, finding 0 downloaded albums. Later on 2026-10-19, the assistant executed code to identify 5 albums to remove from the library. Finally, on 2026-10-19, the assistant executed code to remove these 5 albums from the user's Spotify library. Immediately after this, the assistant received feedback indicating that the task was not fully successful, specifically noting a failure in removing albums where one album (ID 5) that should have been removed was not, leading to an assertion error. Later on 2026-10-19, the assistant attempted to retrieve the user's Spotify playlist library but encountered an execution error because the 'spotify_access_token' was not defined.
````

## Expense and interpretation

| Method | Condition | Eligible successes/conclusive | Excluded | API calls (all attempts) | Generation | Embedding | Known estimated USD |
| --- | --- | --- | --- | --- | --- | --- | --- |
| trace2skill | memory_on | 2/6 | 0 | 402 | 180 | 0 | 0.258625 |
| trace2skill | memory_off | 2/5 | 1 | 1405 | 154 | 0 | 0.238989 |
| trace2skill | target_removed | 4/6 | 0 | 409 | 144 | 0 | 0.210886 |
| gepa | memory_on | 3/6 | 0 | 480 | 180 | 0 | 0.247502 |
| gepa | memory_off | 5/6 | 0 | 404 | 164 | 0 | 0.248098 |
| gepa | target_removed | 5/6 | 0 | 417 | 190 | 0 | 0.317572 |
| recmem | memory_on | 2/6 | 0 | 419 | 164 | 82 | 0.543019 |
| recmem | memory_off | 4/6 | 0 | 426 | 150 | 75 | 0.219073 |
| recmem | target_removed | 3/6 | 0 | 404 | 176 | 88 | 0.562356 |

Pre-outcome target selection: 3 provider requests; known estimated USD 0.000024. No additional learning. Native retrieval also runs in the withheld condition, so costs measure this exposure intervention, not an optimised memory-free implementation. Provider estimates are not invoices.

Full-memory pass plus withheld failure is an observed paired difference. A repeated loss after target removal supports a contribution by the removed content group only if that content was actually exposed in the full condition and the removal intervention activated. Two repetitions do not establish statistical superiority. If both full and withheld pass, removal failure alone does not establish that memory was necessary.

Each exposure intervention changes memory supplied to both tool-search generation and action generation. It does not identify which of those two channels caused a downstream difference.

Withheld conditions use the same empty-memory acting and discovery interface across policy labels. Differences among their outcomes are repeated-control variation, not evidence of different architecture quality. Two repetitions per task and condition are insufficient to distinguish small effects from that variation reliably.

The Trace2Skill/RecMem sources are original pilot memories, while the common actor now retrieves at each step and adds tool search. These outcomes are not exact reproductions of pilot scores. Original memory input defects remain disclosed. Recognised credential text in RecMem is redacted only at delivery; original frozen vectors and stores remain unchanged. No lessons are corrected or authored. Native retrieval still indexes the original text.

Known-case selection, different learning histories, context-length changes, redundant guidance, inactive removals, model variation, provider aliases, execution order, host load, cold starts, missingness, grading defects and instrumentation overhead limit inference. Supporting failures are inconclusive. No repeat-until-pass or evaluation learning is allowed.

One owned integration limitation is concrete: the shared actor serialises the previous step including its measured duration_s into retrieval and tool-search context. Therefore request strings can differ between repetitions even when the preceding action and result match. This is unnecessary timing noise and another reason not to attribute every changed action solely to memory content. The frozen actor was not edited mid-comparison.

Consolidation happened during earlier practice/construction. These repeated attempts freeze memory and deliberately exclude their feedback from learning. They test existing retained knowledge, not improvement from additional practice or long-term growth. Native consolidation does not guarantee correctness, applicability or retirement of failed guidance.

## Implementation trade-offs

| Policy | Useful property observed | Limitation exposed |
| --- | --- | --- |
| Trace2Skill | One inspectable skill allows an exact section-removal intervention. | Whole-skill exposure mixes generic and domain-specific guidance. Removing the generic section changed grocery outcomes, but does not explain why the remaining context worked. |
| GEPA | A native-selected, persisted strategy can be exposed and partially withheld exactly. | Candidate testing adds learning expense. A strategy selected on known cases can be inapplicable elsewhere; retained instructions are not a guarantee of better task completion. |
| RecMem | Layered native retrieval provides identifiable episodes and semantic items. | The highest-ranked episode can concern a different task or application. Repeated retrieval adds embedding expense; recurrence and consolidation do not certify relevance. |

These are properties of the tested integrations and frozen artifacts. They are not rankings of published architectures. The earlier Mem0 and ACE repeated checks (private source evidence) use different tasks and a separate protocol; their outcomes must not be pooled into this table.

## Traces and failures

TRACES.md (private full trace) contains every attempted action, actual delivered-memory references, observed execution errors and official failed requirement descriptions. Exact delivered content and authentication-redacted observations are deduplicated in its appendices. Raw observations, model requests and source artifacts are preserved in the local private evidence bundle. No hidden model reasoning is included.
