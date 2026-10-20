Public sanitised derivative of executed live evidence. Raw observations, SDK conversations, credentials and application databases are excluded. Exported grades cannot independently regrade tasks. Local private evidence remains available separately.

# Mem0 and ACE: matched memory exposure diagnostic

These are new live attempts on known upstream cases. Memory stays frozen. Only exposure changes within each paired comparison. Native retrieval still runs in the withheld condition.

| Method | Task | Memory on | Memory withheld | Target removed |
| --- | --- | --- | --- | --- |
| mem0 | 34d9492_1 | 1/2 | 1/2 | 0/0 |
| mem0 | e85d92a_3 | 1/2 | 2/2 | 0/0 |
| mem0 | d0b1f43_1 | 1/2 | 2/2 | 0/0 |
| mem0 | aa8502b_1 | 0/2 | 1/2 | 0/0 |
| ace | 34d9492_1 | 2/2 | 2/2 | 0/0 |
| ace | e85d92a_3 | 2/2 | 2/2 | 0/0 |
| ace | d0b1f43_1 | 2/2 | 2/2 | 0/0 |
| ace | aa8502b_1 | 2/2 | 2/2 | 0/0 |

Primary cells planned: 32. All attempted cells: 32. Latest conclusive cells including conditional removals: 32.

All conclusive failures remain included. A stored or exposed memory is not evidence of benefit. A memory-on pass and withheld failure is a paired outcome difference. Repeated deterioration after removing the predeclared item set supports that set contributing, without isolating individual sentences or eliminating context-length effects.

Task selection used prior outcomes. These are known-case diagnostics, not independent held-out estimates. Earlier input-normalisation defects remain disclosed; the reused artifacts were checked for recognised authentication values but that does not certify their factual correctness. Provider and host timing, execution order, model aliases, instrumentation and two repetitions limit attribution.

## Tasks

- `34d9492_1`: Arrange my "~/photographs/vacations/" directory by organizing the photos from three vacations. The files created in February and March of this year correspond to Petra and Budapest, respectively, while the others are from Amsterdam. Move them into sub-directories named after their respective vacation spots, maintaining the original file names.
- `e85d92a_3`: What is the title of the most played song by Jasper Skye on Spotify.
- `d0b1f43_1`: How much money have I sent to my roommates on venmo since 1st Jan of this year?
- `aa8502b_1`: Follow all the artists who have sung at least one song I have liked on Spotify.

## Completion and expense

| Method | On successes | Withheld successes | Paired wins/losses/ties | On estimated USD | Withheld estimated USD |
| --- | --- | --- | --- | --- | --- |
| mem0 | 3/8 | 6/8 | 1/4/3 | 0.234550 | 0.201335 |
| ace | 8/8 | 8/8 | 0/0/8 | 0.252372 | 0.182955 |

Estimates include actual generation, embedding and token-count requests. Native lookup remains active even when exposure is withheld, so these are exposure-intervention costs, not the expense of a separately optimised no-memory implementation. No additional learning occurred.

## Repeated tool-work difference with ACE

Both ACE roommate-spending attempts passed in both conditions. With memory, the agent used 20 and 19 API calls (12 and 13 action decisions). With memory withheld it used 23 and 25 API calls (16 and 17 action decisions). This is a repeated observed reduction in tool work on a task the agent already completed without memory. It does not demonstrate a completion gain, a cost saving, or the causal contribution of an individual bullet.

## Concrete memory-quality finding

Mem0 item `990603d1-baff-4ebf-a04d-f79899c0d4e2` retained this completion template:

```python
apis.supervisor.complete_task(answer=f"Followed {followed_artists_count} new artists. Some artists were already followed.")
```

Native ADD record `72cf11e3276d41ba98e94c6d9496b29b` and consolidation `eb05652d8fe94db7a834a61817a62150` link it to failed practice run `b7d13352022d491ba2a9712ad95adc46`. It survived into the frozen checkpoint. In new memory-on run `915a16fedcd84739a84c62fbde5012db`, this exact item was exposed at decisions 1, 4 and 6. The agent later emitted the same completion wording. Its application changes passed, but the official answer requirement failed. This is source-linked evidence of problematic retained guidance and compatible subsequent behaviour, not an isolated causal estimate for that single item.

There is no general freshness or retirement controller in this integration. Native mutation mechanisms ran, but did not ensure that failed task behaviour was corrected or retired. The diagnostic froze memory throughout, so its new feedback was deliberately not used for further learning.

In normal practice, learning occurs after completed attempts. Mem0 can update/delete facts; ACE can merge bullets; Trace2Skill can patch procedure files; GEPA replaces the selected active strategy; RecMem removes consolidated raw records and replaces merged episodes. These native operations do not supply a shared expiry, tool-version invalidation, or dependable retirement rule. Historical evidence remains stored even when an item leaves active memory.

No predeclared item-removal checks were triggered: no method/task pair had two memory-on passes and two withheld failures. The isolated-item benefit claim therefore remains unestablished.

## Correct sorting knowledge, incorrect entity scope

In repeated song task `e85d92a_3`, Mem0-on run `7369a4af8b57434da7b7dbc8a0a204e2` called `search_songs(query="Jasper Skye", sort_by="-play_count", page_limit=1)` and failed. The paired withheld run `395d8cb1f0b34161945204533c6e2805` first resolved the artist, then called `search_songs(artist_id=3, sort_by="-play_count", page_limit=1)` and passed. A correct sorting fact did not ensure correct entity selection. The observable error was global text search instead of filtering by the resolved artist. This does not isolate a particular fact as the cause of that decision.

## Run identities

| Method | Task | Repetition | Exposure | Official pass | Run |
| --- | --- | --- | --- | --- | --- |
| mem0 | 34d9492_1 | 0 | memory_on | False | 1126c9817e0b41aeb440ae6dfb24a3a5 |
| mem0 | 34d9492_1 | 0 | memory_off | True | 222c1d1927664454ac18e01b1fde83ea |
| ace | 34d9492_1 | 0 | memory_on | True | 758e771e053e4e899026077681683c94 |
| ace | 34d9492_1 | 0 | memory_off | True | dab1aafcbbf841249bb57b292051baa1 |
| ace | e85d92a_3 | 0 | memory_off | True | e3e5bd11221d4036bdec8d925317f117 |
| ace | e85d92a_3 | 0 | memory_on | True | 4dc70ccd99ac4c3cb7288de5d6a958a7 |
| mem0 | e85d92a_3 | 0 | memory_off | True | 829aefe6f39d45479f20af9155cb2446 |
| mem0 | e85d92a_3 | 0 | memory_on | True | c12e1287197f4ff2a0c34f4545ef8af2 |
| mem0 | d0b1f43_1 | 0 | memory_on | False | 3bae2b0ff4bb4226909148631a9fc1a7 |
| mem0 | d0b1f43_1 | 0 | memory_off | True | ff1ae94b0f08409280a1d9465fd2e07d |
| ace | d0b1f43_1 | 0 | memory_on | True | b796d67c522243a6ae0264f4f0e372fe |
| ace | d0b1f43_1 | 0 | memory_off | True | 38fea19f9fcb4286a23710f8312e210d |
| ace | aa8502b_1 | 0 | memory_off | True | 19d36be10dfa47478ed6f101b98c4623 |
| ace | aa8502b_1 | 0 | memory_on | True | 6ebbd56de38d40f1bb0e54350900574d |
| mem0 | aa8502b_1 | 0 | memory_off | False | f60843eb7acf4d9d821150f3ad8ed9c5 |
| mem0 | aa8502b_1 | 0 | memory_on | False | 915a16fedcd84739a84c62fbde5012db |
| ace | 34d9492_1 | 1 | memory_off | True | e5ea64add37a44f9a7d92c924e664a5c |
| ace | 34d9492_1 | 1 | memory_on | True | 9e3ef5f0c3e444c792c57483f7ab6a06 |
| mem0 | 34d9492_1 | 1 | memory_off | False | dc8ad28c7fed446eba2623daeadb9b9d |
| mem0 | 34d9492_1 | 1 | memory_on | True | f6a725639ddf4f988ddd8233c98d2e07 |
| mem0 | e85d92a_3 | 1 | memory_on | False | 7369a4af8b57434da7b7dbc8a0a204e2 |
| mem0 | e85d92a_3 | 1 | memory_off | True | 395d8cb1f0b34161945204533c6e2805 |
| ace | e85d92a_3 | 1 | memory_on | True | bedc2bc99d7c4bbe80c8a77ec6395b3c |
| ace | e85d92a_3 | 1 | memory_off | True | e16c7672dc8d46aa9c5eda1af9c5492d |
| ace | d0b1f43_1 | 1 | memory_off | True | a4f0189ff8be43d3a01eafc59296b290 |
| ace | d0b1f43_1 | 1 | memory_on | True | 84b901b3a285429f9701aab626cbfa1e |
| mem0 | d0b1f43_1 | 1 | memory_off | True | b8280a3ba0e044bab6ae78c612a03a39 |
| mem0 | d0b1f43_1 | 1 | memory_on | True | 8b946ffca99549e59ea017253e5749a4 |
| mem0 | aa8502b_1 | 1 | memory_on | False | e0a257488e674baca181cacc76e25022 |
| mem0 | aa8502b_1 | 1 | memory_off | True | 533f2c86b57b49d38360753d31bb7282 |
| ace | aa8502b_1 | 1 | memory_on | True | 083f00a023434f92a41630253043db72 |
| ace | aa8502b_1 | 1 | memory_off | True | e9eceb7eaa534e8fbd4b08555d0bd412 |
