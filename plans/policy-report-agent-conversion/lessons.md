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

### [2026-07-22] — Do not generalize the engine; it is hardwired by decision
**Context:** Scope definition for the D3→Policy Report conversion; grill-me surfaced that a "domain-neutral" engine with only one mounted domain is an untestable abstraction.
**Mistake:** The initial confirmed scope said "make the code/prompts/parser domain-neutral" — the user retracted this under grilling and chose policy-report-hardwired, cleanly.
**Rule:** During execution, never introduce prefix-agnostic parsing, constraint DSLs, or second fixture skills "while we're at it" — the parser stays hardcoded to `PA`, checks stay policy-report-specific; genericity means fork-per-domain.
**Applies to:** field_groups_parser.py, mechanical_checks.py, prompts.py, tests

### [2026-07-22] — Foundry project endpoint is not the OpenAI data-plane endpoint
**Context:** User updated `.env` with new Foundry credentials ahead of the Batch 7 live smoke; the endpoint was pasted as the project URL (`…services.ai.azure.com/api/projects/<name>`) with no deployment name.
**Mistake:** Nearly carried the project-path URL into `AZURE_OPENAI_ENDPOINT` — the OpenAI client appends `/openai/deployments/…` to the base, so the project path 404s; also, no deployment-free inference exists (probes confirmed `DeploymentNotFound`) and the data-plane key cannot create deployments.
**Rule:** For local runs set `AZURE_OPENAI_ENDPOINT` to the resource ROOT (`https://<res>.services.ai.azure.com`), keep the project URL only for `FOUNDRY_PROJECT_ENDPOINT`, and confirm the named deployment exists on the resource (portal/ARM) before any live verification; a 404-vs-401 probe distinguishes missing deployment from bad key.
**Applies to:** .env, agents.py create_chat_client, Batch 7 live smoke

### [2026-07-22] — Pick test models from the resource's live catalogue, not from memory
**Context:** Recommended gpt-4o-mini as the generic test deployment; the Foundry portal rejected it as deprecated (the resource's `/openai/models` catalogue confirms: preview lifecycle, inference cutoff 2026-09-30).
**Mistake:** Suggested a well-known model name from prior knowledge instead of checking what the resource actually offers today.
**Rule:** Before naming any Azure model deployment, query `GET <resource>/openai/models` with the data-plane key and pick a `generally-available` entry with a far-out inference date — current pick: `gpt-5.4-mini` (version 2026-03-17, inference until 2027-03-17).
**Applies to:** .env, azure.yaml deployments block, Batch 7 live smoke

### [2026-07-22] — Catalogue availability ≠ deployable: check quota before picking a model
**Context:** Deploying the test model via az CLI after login; `gpt-5.4-mini` is GA in the resource's `/openai/models` catalogue but the create call failed with `InsufficientQuota` (limit 0 for that model's GlobalStandard bucket on this subscription).
**Mistake:** Chose the model from the catalogue alone; the subscription's per-model quota is a separate gate, and the newest models had zero quota.
**Rule:** Before naming a deployment, cross-check `az cognitiveservices usage list -l <region>` for a bucket with `limit > 0` (here only `OpenAI.GlobalStandard.gpt-5-mini`, 500 units, among current chat models) and pick the intersection of catalogue-GA and quota>0.
**Applies to:** azure.yaml deployments block, .env, any future model swap

### [2026-07-22] — Foundry Local PoC: exact model id with :N suffix, and no usage stats
**Context:** Proving a local-model path with the user's Foundry Local CLI (service at http://127.0.0.1:54695/v1, model qwen2.5-1.5b loaded).
**Mistake:** Called the OpenAI-compatible endpoint with model id `qwen2.5-1.5b-instruct-generic-gpu` → HTTP 400; the served id is versioned (`…-gpu:4`). Also assumed `response.usage` exists — Foundry Local returns `usage: null`, which would crash this repo's `usage.py` accounting.
**Rule:** Against Foundry Local, take the model id verbatim from `GET /v1/models` (including the `:N` suffix) and guard every `usage` read for None before wiring the agent to a local endpoint.
**Applies to:** any local-model wiring (MAF OpenAIChatClient base_url), usage.py

### [2026-07-22] — Unblocking collection surfaced a second out-of-repo dependency
**Context:** Batch 3 rename/repoint made the suite collectable for the first time; 7 previously-unrunnable tests (test_workflow paste-folding, test_chat_agent uploads) then failed on `tests/conftest.py:31` — `INPUT_FILE` reads `kb/examples/initiative/ini-input-file.md` three parents above the repo, another monorepo remnant the plan's discovery missed because collection died earlier.
**Mistake:** Batch 3's expected-red definition claimed "no missing-file errors" — written from the visible failure surface, not the full latent one.
**Rule:** When a change unblocks test collection, re-inventory the failure classes before comparing against the expected-red shape; and Batch 5 MUST vendor an in-repo sample input document to replace the kb/ fixture path.
**Applies to:** tests/conftest.py, Batch 5 fixture rewrite

### [2026-07-22] — OTEL_*_EXPORTER=none does not silence the hosting SDK's exporter
**Context:** Batch 5 tried to silence the suite's OTel connection-refused retry noise (no collector on :4318 during tests) with the standard `OTEL_TRACES_EXPORTER=none` env vars in conftest.
**Mistake:** Assumed the SDK honors the standard exporter env switches; `agent-framework-foundry-hosting`'s OTel distro wires its OTLP exporter programmatically and ignored them — noise unchanged, so the dead config was reverted.
**Rule:** To silence test-time OTel noise here, the exporter must be disabled at the hosting-SDK level (or a throwaway collector run); don't re-try the standard env vars. The noise is cosmetic — suite time is unaffected.
**Applies to:** tests, hosting.py OTel wiring, task otel:up

### [2026-07-22] — Inherited constants can contradict the new domain while every test passes
**Context:** Post-plan code review of the conversion. The D3-era `_PLACEHOLDERS` set (containing "none") was carried into the policy domain, whose skill explicitly declares "None" a VALID value for PA9/PA15 — so the mechanical pre-check blocked a documented answer. All 149 tests were green because no test encoded the new skill's None-is-valid clause.
**Mistake:** Batch 4 rewrote the checks' citations and enums but kept the placeholder token set without re-deriving it from the new skill's own placeholder definition ("none — where a substantive value is required").
**Rule:** When porting rule-enforcing code to a new domain, re-derive every constant from the new domain's source of record and write a test per sanctioned exception — do not assume a domain-neutral-looking set is actually neutral.
**Applies to:** mechanical_checks.py, any future domain fork of this template

### [2026-07-22] — Foundry code-deploy installs dependencies, not the project
**Context:** First cloud deploy: session crashed with `ModuleNotFoundError: foundry_agent` despite the predecessor's azure.yaml comment claiming the runtime pip-installs the package.
**Mistake:** Trusted the inherited comment; the remote builder only installs uv.lock dependencies and runs `python main.py` — the src/ layout never reaches sys.path.
**Rule:** The entrypoint shim must insert `<root>/src` into sys.path itself; never rely on the hosted builder installing the project.
**Applies to:** main.py, azure.yaml codeConfiguration

### [2026-07-22] — Hosted runtime python_3_13 pulls hyperlight with no compatible wheel
**Context:** First deploy failed remote build: `hyperlight-sandbox-backend-wasm` 0.4.0 has no manylinux_2_31 wheel; the dep only exists under the `python < 3.14` marker via agent-framework-hyperlight.
**Mistake:** Kept the inherited `runtime: python_3_13` while all local testing ran 3.14.
**Rule:** Set the hosted runtime to the interpreter actually tested locally (`python_3_14`) — it also drops the hyperlight branch entirely; deploy what you test.
**Applies to:** azure.yaml codeConfiguration.runtime, uv.lock

### [2026-07-22] — Agent-level env registration does not reach session containers (beta.6)
**Context:** azure.yaml `env:` values (even literals) were registered at deploy ("Registering agent environment variables") but sessions booted without them, crashing create_chat_client.
**Mistake:** Assumed the registered env reaches the container like App Service settings.
**Rule:** Ship non-secret runtime config in a committed `hosted.env` loaded by main.py with override=False (platform env wins if it ever arrives); never ship the real `.env` — keep `.agentignore` excluding it.
**Applies to:** main.py, hosted.env, .agentignore, azure.ai.agents 1.0.0-beta.6

### [2026-07-22] — The agent's instance identity needs the OpenAI role, and propagation is slow
**Context:** With config fixed, the cloud workflow got 401 `PermissionDenied … OpenAI/responses/write` — the ejected bicep grants the agent identity nothing on the account's OpenAI data plane.
**Mistake:** Expected provision to wire the role; also nearly mis-diagnosed the post-assignment 401 (generic "no access") as a wrong role when it was ~4 minutes of RBAC propagation.
**Rule:** After deploy, grant "Cognitive Services OpenAI User" (its dataActions include `OpenAI/responses/*`) to the agent's Instance Identity principal on the target account, then allow 5–10 minutes before judging the assignment failed.
**Applies to:** azd deploy flow, infra/ bicep, az role assignment create

### [2026-07-23] — The playground renders text, not request_info function calls
**Context:** User reported "the agent is not replaying my message on Foundry." A raw streaming call to the same endpoint showed the response carries only `response.function_call_arguments.*` events for `request_info` — zero `output_text` deltas. Chat-first clients (Foundry playground, `azd ai agent invoke`) render assistant text only, so every turn looked empty/silent even though the workflow was answering correctly.
**Mistake:** Deployed only the `WorkflowAgent` (`request_info` function-call protocol) to production; that protocol is correct for a machine client driving `function_call_output` + `previous_response_id`, but the playground has no such driver.
**Rule:** For a chat-first serving surface, host `WorkflowChatAgent` (plain-text turns) instead of the raw `WorkflowAgent` — added a `HOSTED_AGENT_MODE=chat|workflow` switch in hosting.py, defaulting `hosted.env` to `chat` for the Foundry deployment. Existing hosted sessions keep running their old container image after an env-only deploy; verifying a behavior change requires a genuinely NEW session (old session IDs are stale evidence).
**Applies to:** hosting.py, hosted.env, chat_agent.py, any future chat-facing serving surface

