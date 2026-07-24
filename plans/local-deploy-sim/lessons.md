# Lessons Learned

_Append an entry whenever the user corrects an approach, something fails
in a non-obvious way, or a pattern worth remembering is discovered. Read
this file at the start of every working session._

## Format

Each lesson follows this structure:

### [YYYY-MM-DD] — [Short Title]
**Context:** What was happening when this was discovered
**Mistake:** What went wrong (or what was nearly missed)
**Rule:** The rule to prevent recurrence
**Applies to:** [file, area, or task]

---

### [2026-07-23] — Deploy parity means the platform's default mechanism, not a parallel backend
**Context:** Define phase. The draft plan wired a custom BlobCheckpointStorage against Azurite as "deploy simulation fidelity."
**Mistake:** Production Foundry persistence is env-selected and platform-owned (`FoundryStorageProvider` from injected env, host-managed file checkpoints on platform-preserved containers) — the agent never calls Azure Storage/Cosmos, so a custom backend would have simulated a mechanism that doesn't exist in prod. The user caught it: "seamless with the default mechanism."
**Rule:** Before planning persistence code for a hosted agent, trace how the platform provisions that concern in the installed host package (e.g. `_routing.py` store selection); if it's platform-owned and env-selected, simulate it with configuration, never with a parallel storage implementation.
**Applies to:** hosting/persistence plans, `azure.ai.agentserver` integration, infra/local sim

### [2026-07-23] — Error-path checkpoint pruning turns a concurrency race into data loss
**Context:** Batch 3 demo. A readiness probe POST started a real run; the demo's turn 1 arrived while it was in flight and hit "Workflow is already running; concurrent runs are not allowed."
**Mistake:** The generic error path (drop conversation + now prune checkpoints) treats this benign race as fatal — since Batch 2, that reset also destroys the interview's durable state, so a concurrent duplicate message can wipe a resumable conversation.
**Rule:** When adding durable state to an error-reset path, audit which exceptions actually warrant destroying it; surface "already running" as "still busy — try again" without resetting. (Filed as a follow-up, out of this plan's scope.)
**Applies to:** `chat_agent.py` `_advance` error path, concurrency handling
