# Executed pilot method

The same AppWorld acting agent was run with baseline, Mem0, ACE, Trace2Skill, GEPA and RecMem. The memory policy changed; the model, acting loop, tasks, tools, world resets and evaluator were held fixed.

Six shared training tasks supplied actual actions, observations and official outcomes. Two separate selection tasks supported instruction selection. Six development evaluation tasks were attempted twice per configuration. The evaluator graded 71 of 72 evaluation cells, across 77 actual attempts. One cell remained inconclusive after repeated truncated outputs. Conclusive failures were retained.

Memories were frozen during evaluation. GEPA retained its empty seed in this pilot, so differences between its evaluation outcomes and baseline cannot establish learned-instruction benefit. All six configurations used live configured Vertex models; no fabricated responses were counted as experiment evidence.

The pilot measurements and limitations are in [the measured report](docs/PILOT.md). The published integration and separate task examples are in [findings](docs/FINDINGS.md). This publication describes executed work and does not claim a completed long-term growth comparison or statistical superiority.
