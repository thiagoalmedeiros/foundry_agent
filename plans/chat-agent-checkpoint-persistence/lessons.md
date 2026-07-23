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

### [2026-07-23] — Plan scope missed the existing chat-agent tests
**Context:** Batch 1 wired checkpoint storage into `WorkflowChatAgent`; the plan's DoD scope check listed only `chat_agent.py`, the new test file, and `hosting.py`'s docstring as touchable.
**Mistake:** The plan overlooked that `tests/test_chat_agent.py` drives full conversations — without isolation they write real state under the repo's `.checkpoints/chat/`, and once Batch 2's restore lands, a stale checkpoint from a prior run would make the suite history-dependent.
**Rule:** When adding persistence to a component, list every existing test that exercises it and give them isolated storage (autouse `tmp_path` fixture) in the same batch as the wiring — not in the later test batch.
**Applies to:** `tests/test_chat_agent.py`, plan DoD criterion 4 (scope check now legitimately includes this file).
