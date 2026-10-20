# Local workspace and historical evidence

The canonical Git checkout is `agent-memory-comparison/`. New source and experiment plans belong here. It replaces the publication checkout that previously lived inside the historical runtime's cache. There is one Git remote for this study: `Axionis47/agent-memory-comparison`.

The original `memory-comparison/` directory remains a private historical runtime and evidence anchor. Moving its measured files, rewriting its paths or running new dispatchers against its ledgers could invalidate frozen source and reset identities. It is not a second Git repository. Keep it unchanged except for navigation notices.

On the original machine, these ignored links provide access without copying the data:

| Local path | Responsibility |
| --- | --- |
| `local/legacy` | Original measured source, private ledgers, snapshots, reports and evidence bundles. |
| `.venv` | Existing installed Python runtime. |
| `.cache/vendor` | Existing downloaded upstream implementations. |

These links are not committed. The repository's own results directory is reserved for new cohorts, including results/adjacent-v1. Historical results are reached through local/legacy/results. A fresh clone contains source, sanitised evidence and plans, and requires its own configured runtime and upstream downloads. The historical drivers and tests requiring private snapshots are retained for inspection; their original freezes require the original runtime. The MA01 implementation must bind its own results namespace and freeze rather than reuse historical identities.

The public code snapshot has documented configuration and redaction adaptations. Public export hashes identify these files; they do not turn the snapshot into an exact historical runtime or independently regrade exported outcomes. Private provider conversations, credentials, application databases and raw archive bundles stay outside Git. The task instructions in adjacent/ are prospective inputs, not completed results.
