# Third party sources

| Component | Source | Pinned version or revision |
| --- | --- | --- |
| AppWorld | https://github.com/StonyBrookNLP/appworld | 42b5bcf3cd334fee33f0c37c02070a9f5807add5 |
| ACE | https://github.com/ace-agent/ace | 82709de050e1db6e6ef2f07bcb0393560b94992a |
| Trace2Skill | https://github.com/Qwen-Applications/Trace2Skill | 3d0b52a140f002a512930252b613c49048f7d5ac |
| RecMem | https://github.com/CaiusDai/RecMem | a84252f6e5587fd4a8caac03ec9f6c732b7a7f35 |
| Mem0 | https://github.com/mem0ai/mem0 | mem0ai 1.0.0 |
| GEPA | https://github.com/gepa-ai/gepa | gepa 0.1.4 |

Upstream repositories, benchmark datasets and installed dependencies are downloaded separately and retain their own terms. AppWorld, ACE and RecMem include license files in their pinned source trees. No root license file was found in the pinned Trace2Skill checkout during publication review; its source is fetched rather than redistributed here. This table is provenance, not a grant of rights for those projects.

The structural validator under `third_party/skill_structure_validator/` comes from the OpenAI skill-creator tooling. Its source is unmodified, SHA-256 ee6dba90f44d37171c5a6edb8095979c54919ff6822c1a907afca2e78c48738c. Its Apache License 2.0 is included alongside it. It checks skill structure and is not the Trace2Skill authors' behavioural evaluator.

Provider adapters, task-format adaptations, update scheduling and measurement code are specific to this experiment. No project-wide reuse license has been selected for the original integration code. Third-party notices are retained independently.
