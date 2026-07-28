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

### [2026-07-27] — Bare `/responses` turns carry chat-mode continuity; ids do not
**Context:** Batch 1 spike — 3 sequential bare `{model,input}` POSTs to a chat-mode (`HOSTED_AGENT_MODE=chat`) `/responses` server, verifying multi-turn elicitation before building the Teams bridge on the assumption.
**Mistake:** Nearly designed the bridge to chain `previous_response_id` like a "correct" OpenAI Responses client. That would populate the host's `get_history()`, whose messages `_extract_text` flattens into the elicitation answer — silently corrupting turn 2. Also nearly assumed continuity rode `agent_session_id`, but it changed every turn while the interview still advanced correctly.
**Rule:** The bridge MUST send bare turns — `{"model","input","stream":false}`, never `previous_response_id`/`conversation_id`. Continuity lives only in the server's in-process `WorkflowChatAgent._conversations["default"]` (all turns collapse to one `default/` checkpoint dir = one conversation per running server). Reply text is at `output[] (type=="message", role=="assistant") -> content[] (type=="output_text") -> text`.
**Applies to:** `src/foundry_agent/teams_bridge.py` (`build_request`/`extract_reply`), Batch 3; the `/responses` chat-mode transport contract.

### [2026-07-27] — Don't silence `task test` OTel noise with `OTEL_SDK_DISABLED`
**Context:** After `task otel:down`, `task test` spews `Connection refused` OTLP export retries (`.env` pins `OTEL_EXPORTER_OTLP_ENDPOINT=:4318`). Tried `OTEL_SDK_DISABLED=true` to quiet it.
**Mistake:** That made `test_observability.py::test_usage_counts_are_attached_to_the_active_span` FAIL (1 failed / 148 passed) — the test asserts usage counts land on a live span, so a disabled SDK breaks it. Looked like a regression; was self-inflicted.
**Rule:** The export noise is cosmetic — the suite is green (149 passed) with OTel enabled. To run cleanly, keep a collector up (`task otel:up`) or just ignore the retry lines; never set `OTEL_SDK_DISABLED`/unset the endpoint to quiet them.
**Applies to:** running `task test` during any batch of this plan; `tests/test_observability.py`.

### [2026-07-27] — A cross-module negative-assertion test guarded "Flow 2 off the hosted path"
**Context:** Batch 2 added `chat-functional` mode to `hosting.py` (imports `create_hybrid_workflow`). `task test` then failed `tests/test_workflow_functional.py::test_flow2_does_not_alter_flow1_or_the_hosted_path` — a test in a *different* module that grep-asserted `"create_hybrid_workflow" not in hosting.py` and `"workflow_functional" not in hosting.py`.
**Mistake:** Nearly assumed a green `test_hosting.py` meant the batch was done. The invariant this batch intentionally reverses was pinned as a negative assertion in another test file (exactly the AGENTS.md sharp edge: "tests of other modules import it as a negative-assertion prop").
**Rule:** When a change deliberately crosses a documented boundary, grep `tests/` for negative assertions about that boundary (`grep -rn "not in hosting" tests/`, module-name greps) and update them to the new intended invariant — keep the still-valid part (Flow 1 graph unchanged, Flow 1 stays the default) rather than deleting the test.
**Applies to:** `tests/test_workflow_functional.py`; any batch that changes what `hosting.py` imports/serves.

### [2026-07-27] — The Agents SDK ships `Connections` as a Protocol only — the app supplies the impl
**Context:** Batch 4 wiring `CloudAdapter` for the local Agents Playground (anonymous, no Entra token). Looked for a shipped anonymous connection manager to avoid custom plumbing (AGENTS.md: prefer framework-native).
**Mistake:** Assumed `microsoft-agents-hosting-core` shipped a concrete anonymous `Connections`. It does not — `grep -rlnE "class \w+\(.*Connections.*\)"` over the package returns **nothing**; `Connections` is a `Protocol` with 4 abstract methods, and `AnonymousTokenProvider` is the token provider it should return. Supplying a small `Connections` impl is the intended integration seam, not custom plumbing.
**Rule:** For local/anonymous hosting, implement the 4-method `Connections` returning `AnonymousTokenProvider`, and set the aiohttp app's `["agent_configuration"] = AgentAuthConfiguration()` — the JWT middleware admits token-less requests only when `CLIENT_ID` is unset (`jwt_authorization_middleware.py:25`). Verify a new SDK seam by grepping for concrete subclasses before assuming one exists.
**Applies to:** `src/foundry_agent/teams_bridge.py` (`_AnonymousConnections`); any future tenant-auth swap.

### [2026-07-27] — A 120s per-turn timeout is too short for Flow 2; the client giving up resets the interview
**Context:** Batch 5 DoD smoke, Flow 2 (`chat-functional`) through the bridge. Turn 7 replied "The bridge could not reach the workflow: " and the next turn reported the workflow was reset.
**Mistake:** Set `DEFAULT_TIMEOUT_SECONDS = 120` in Batch 3 by extrapolating from the Batch-1 **Flow 1** measurement (~30s/turn). A Flow 2 turn can run the deterministic `validate.py` gate *and* re-elicitation in one turn, exceeding 120s → `httpx.ReadTimeout`. Worse, the *server* keeps working after the client gives up, so the next message hits "Workflow is already running" and the error path resets the conversation — one slow turn destroys the interview.
**Rule:** Size the bridge timeout for the **slowest** flow, not the one you measured (now 300s, env-tunable). When a client-side timeout can leave the server mid-turn, treat the timeout as interview-destroying, not cosmetic — never tune it from a single-flow sample.
**Applies to:** `src/foundry_agent/teams_bridge.py` (`DEFAULT_TIMEOUT_SECONDS`), `.env.example`.

### [2026-07-27] — `str(httpx.ReadTimeout)` is empty, so error-as-text degraded to a bare prefix
**Context:** Same failure — the user-visible reply was literally "The bridge could not reach the workflow: " with nothing after the colon.
**Mistake:** Built the error reply as `f"{ERROR_REPLY_PREFIX}{exc}"`, assuming every exception stringifies to something useful. Several httpx timeout exceptions carry an **empty** message, so the reply named no failure at all — the opposite of the "never an empty bubble" intent.
**Rule:** When rendering an exception into user-visible text, never interpolate `{exc}` alone — fall back to `type(exc).__name__` when `str(exc)` is blank (`_describe`). Assert it with a test using a message-less exception.
**Applies to:** `src/foundry_agent/teams_bridge.py` (`_describe`, `handle_message_turn`); any error-as-text path.

### [2026-07-27] — Flow 1 and Flow 2 ask field groups in different orders
**Context:** Writing the DoD smoke harness. A fixed answer script (tuned to Flow 1's order) desynchronized on Flow 2: the time/location answer arrived while Flow 2 was asking "who's involved".
**Mistake:** Assumed both flows walk the field groups in the same sequence. They do not — and once answers desynchronize, Flow 2's gate correctly re-opens the still-empty groups on every cycle, which reads like an infinite loop but is the documented design (capped by `FLOW2_MAX_CYCLES`).
**Rule:** Never script a multi-turn interview test with positional answers. Send an order-independent complete fact sheet each turn (or match the answer to the question text); a "loop" in Flow 2 usually means the required attributes were never actually captured.
**Applies to:** any end-to-end interview smoke against Flow 1 vs Flow 2.

### [2026-07-27] — Changing a constant left its module docstring contradicting the code
**Context:** Final Thomas full-plan pass. After raising `DEFAULT_TIMEOUT_SECONDS` 120 → 300 → 600, Thomas found the module docstring still documented "default ``120`` … measured at ~30s".
**Mistake:** Updated the constant, its inline comment, and `.env.example`, but not the module docstring's environment list — three of four places. A reader of the docstring would have gotten the pre-fix number.
**Rule:** A tunable's value is usually written in several places here (constant, inline comment, module docstring env list, `.env.example`). After changing one, `grep -n "<old value>"` the module and the repo before calling it done.
**Applies to:** `src/foundry_agent/teams_bridge.py`; any env-tunable default in this repo.

### [2026-07-28] — A lock keyed by the wrong id is not a guard
**Context:** Code review of the bridge. `_ConversationLocks` serialized turns per **Teams conversation id**, to stop a second turn colliding with an in-flight one.
**Mistake:** The protected resource is not per-conversation. Chat mode keys every turn to the server's single in-process `"default"` conversation, so two Teams conversation ids drive one workflow. A reloaded Playground mints a fresh id → fresh lock → concurrent turn → "Workflow is already running" → interview reset. The guard failed in exactly the scenario it existed for.
**Rule:** Key a mutex by the identity of the **resource it protects**, not by the identity of the request. When they differ, write the mismatch down — here the fix was one process-wide `asyncio.Lock`, which also deleted the unbounded-dict question.
**Applies to:** `src/foundry_agent/teams_bridge.py` (`handle_message_turn`).

### [2026-07-28] — A test that pre-acquires the lock does not test the locking
**Context:** Reviewer mutation-tested the bridge: replacing `async with lock:` with `if True:` (removing serialization entirely) still passed all 12 tests.
**Mistake:** The serialization test pre-acquired the lock externally, so it only exercised the `lock.locked()` early-return branch — never the handler actually *holding* the lock. Then my first replacement test polled `while not lock.locked()`, which **hung forever** under the mutation instead of failing: a hanging test is worse than a missing one.
**Rule:** Prove a concurrency guarantee with genuinely concurrent tasks (a stub that signals it has started and blocks on an `asyncio.Event`), and bound every wait with `asyncio.wait_for` so a regression fails fast instead of hanging. Confirm coverage by mutating the guarantee away and watching the test fail — restore the file in a `finally`.
**Applies to:** `tests/test_teams_bridge.py`; any lock/serialization test.
