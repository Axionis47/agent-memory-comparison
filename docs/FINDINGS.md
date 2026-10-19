# Memory learned and actions observed

These examples come from actual AppWorld task attempts with the same acting agent and different memory mechanisms. They show retained content, delivered context, observable actions and official outcomes. Most examples lack a matched memory-withheld control, so matching an action to supplied advice does not prove a causal contribution.

The [sanitised action records](../evidence/cases.json) identify each attempt by run ID. Raw observations and application databases are withheld; the exported official results cannot independently regrade the original state.

## Mem0

| Task | Learned memory supplied | Subsequent action | Official outcome and run |
| --- | --- | --- | --- |
| Find an artist's most-played song | `search_songs` can sort by descending `play_count`. | Called `search_songs(artist_id=3, sort_by='-play_count', page_limit=1)`. | Pass, `30a65c9c7b604658aadb67828054cc71` |
| Organise vacation photos | `move_file` requires `source_file_path`, `destination_file_path` and `access_token`. | Used those arguments to move classified files while preserving names. | Pass, `bcb4acf0042b4939942983bc796620ac` |
| Calculate money sent to roommates | Venmo has a `show_transactions` function. | Retrieved current roommates, paginated sent transactions since January and summed amounts. | Pass, `8cf966da93b34b1bafe7898ea19c9d27` |

Mem0 made specific API knowledge retrievable across tasks. Current documentation also informed execution, so memory was not established as the unique source of the action. In the photo example, the argument fact was supplied earlier but absent from the request generating the final move. That attempt required 12 embedding requests in addition to generation and token counting.

## ACE

| Task | Playbook lesson supplied | Subsequent action | Official outcome and run |
| --- | --- | --- | --- |
| Rank an artist's songs | Obtain the entity ID before fetching related data. | Searched for the artist, then requested songs sorted by play count. | Pass, `397da6627b474d6687edc108fe84ffad`; preceding attempt also passed. |
| Calculate roommate spending | Authenticate to relevant applications, retrieve both datasets, correlate identities, then act. | Looked up phone contacts and matched emails against Venmo transactions. | Pass, `08cc00f347674ca8ac3fcbbe3bcc80f4`; a subsequent post-update check failed. |
| Classify vacation photos | Explicitly account for classification conditions and fallback behaviour. | Defaulted to Amsterdam, overriding that for February/Petra or March/Budapest in the current year. | Earlier attempt failed; later check passed, `66824006f18444cab591ef966e7e1992`. |

ACE generated readable workflow advice. The first example demonstrates relevant guidance without an outcome improvement. The failed later spending check shows that a useful lesson does not ensure repeatable execution. The photo result improved on a repeated task, with model variability as another possible explanation. The integration supplies the whole playbook.

## Trace2Skill

Three concrete behaviours matched the evolved skill in one photo task, run `a041e1dfb5c046958e1ba2388c4cdf87`:

1. The skill identified `show_file` as the source of creation timestamps. The agent collected metadata before classifying files.
2. It said to convert `created_at` strings to datetime objects. The agent used `datetime.fromisoformat` and checked year and month.
3. It described directory creation and file moves. The agent created destinations, then moved files while retaining their names.

The task passed. These are three behaviours within one repeated task, not three independent transfer successes. The skill's API examples were schematic; current definitions supplied exact arguments. Structural validation checked format rather than procedural correctness.

## GEPA

The native optimiser selected an instruction to capture original item metadata, track changed paths and use the updated paths in later operations. It was saved, reopened and frozen before the follow-ups. The [complete instruction and selection record](../evidence/gepa-retention.json) preserve its actual text and version.

| Task | Actions with retained instruction | Matching control |
| --- | --- | --- |
| Rename files, then move older files | Captured original paths and creation years, recorded paths returned by renaming, then moved using the updated paths. Run `646cde1b87834a478070da8b8f3ac405`. | Both passed with 156 API calls. No completion or API-call advantage was observed. |
| Reject payment requests from friends and roommates | Queried phone contacts for both relationships and rejected relevant requests. Run `74192ba79bfc486f94576685fba17bfa`. | Memory-on passed with 36 API calls. Empty memory failed with 26 calls after using Venmo friends. |

The file code closely matches the saved procedure. The retained instruction does not explicitly name phone relationships, and both first tool searches returned the same query and definitions, so the Venmo pair does not establish why the behaviour changed.

The diagnostic made 14 candidate-testing task attempts. Its metric was `success * (1 + 1 / (2 * (1 + actual_api_calls)))`, with failure scored zero. Completion took priority over efficiency. Construction and candidate testing recorded 560 SDK requests with a known estimate of $0.469273. Training and selection used the same known cases. Earlier pass-only diagnostics retained empty strategies; their attempts remain in the original records.

| Follow-up | Generation requests | Known estimated execution USD |
| --- | --- | --- |
| Venmo with retained instruction | 30 | 0.031070 |
| Venmo with empty memory | 20 | 0.035179 |
| Files with retained instruction | 26 | 0.058348 |
| Files with empty memory | 22 | 0.027827 |

API-call count and provider expense measure different costs. More API calls did not mean higher estimated provider expense in the Venmo pair.

## RecMem

| Task | Retrieved experience | Subsequent action | Official outcome and run |
| --- | --- | --- | --- |
| Organise vacation photos | An episode describing the earlier categories and file workflow. | Read current files, parsed dates and moved photos into the correct directories. | Pass, `ddf04a52bfb948f0982f52b3d3dc799d` |
| Calculate roommate spending | Earlier use of phone contacts to identify friends and roommates. | Retrieved current roommate contacts again, then filtered and summed current Venmo transactions. | Pass, `be731037d5384d3187b5edb4164fa97e` |
| Follow artists from liked songs | An episode about an earlier album-playing task. | Used current documentation and observations to discover and execute artist following. | Pass, `a39172ec290d4f62bc24b83b9bea0518`; no useful memory contribution established. |

Episodes preserved workflow context, and the spending task refreshed current contacts rather than trusting old names. However, the photo episode also accumulated unrelated Venmo feedback. Consolidation executed while blurring task boundaries, and retrieval could supply substantial irrelevant content.

## Same photo task execution expense

Each row is one fresh-world preliminary attempt on the same photo task. All passed. Learning expense is excluded. GEPA supplied an empty strategy in this particular comparison.

| Configuration | Action decisions | Generation requests | Embedding requests | Estimated execution USD | Task seconds |
| --- | --- | --- | --- | --- | --- |
| Baseline | 7 | 14 | 0 | 0.014030 | 39.676 |
| Mem0 | 12 | 24 | 12 | 0.043369 | 78.662 |
| ACE | 9 | 18 | 0 | 0.024941 | 28.625 |
| Trace2Skill | 11 | 22 | 0 | 0.030494 | 40.368 |
| GEPA | 14 | 28 | 0 | 0.019548 | 92.268 |
| RecMem | 9 | 18 | 9 | 0.055874 | 37.057 |

Generation counts include tool search and action generation. Token-count requests are recorded separately in the original ledger. These single observations do not establish a speed or cost ranking. Execution order, provider timing, host load and instrumentation affect the measurements; estimated prices are not an invoice.

## Observed boundaries

The local source audit found 22 standalone simulated-password observations surviving the main learning-copy redactor. This was an integration defect rather than evidence against a memory architecture. The separate GEPA diagnostic added a process-local redaction repair. Original outcomes and memories were preserved; the public derivative excludes authentication values and raw observations.

The examples establish that mechanisms produced and exposed retained knowledge and that several passing tasks contained compatible actions. They do not establish two or three independent beneficial effects for every architecture. The initial pilot outcomes are reported separately in [pilot measurements](PILOT.md), with conclusive and inconclusive counts. No statistical superiority or completed long-term growth result is claimed.
