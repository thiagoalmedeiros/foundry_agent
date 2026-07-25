# Batch 4 — Live before/after behavior parity

Real-model runs (police skill + gpt-5-mini) driving the **same** scripted
incident interview (`scratchpad/live_driver.py`: same INITIAL + REPLIES both
runs, so the prompt is the only variable). Transcripts: `before.json` (current
verbose prompt), `after.json` (slimmed prompt). Compared via `scratchpad/compare.py`.

| DoD criterion-4 dimension | before | after | verdict |
| --- | --- | --- | --- |
| Discovery order (7 groups, in the skill's order) | FG1→…→FG7 | FG1→…→FG7 | **match** |
| Group openings using the framing line verbatim (EL12) | 6/6 | 5/6 (FG1 led with inference) | match (minor variance) |
| Honest attribution (`[Doc]` / user / inferred) | `[Doc]`×2, infer×3 | `[Doc]`×7, infer×8 | **match (stronger)** |
| Inference-confirm cadence + never-invent | infers type, asks for report #/status | same | **match** |
| `run_skill_script` call shape (not-called warnings) | 0 | 0 | **match** |
| Assembled-document structure (12 sections + appendix) | full template | full template | **match** (only title B/b casing differs) |
| Completed with a document | yes | yes | **match** |

**Verdict: behavior parity holds.** Every load-bearing behavior is preserved;
differences are improvements (more explicit attribution) or trivial model
variance (title casing, shorter body, FG1 opening order).

**Prompt reduction:** `ELICITATION_INSTRUCTIONS` 37 → 19 lines; the honest-sourcing
behavior relocated into the elicitation skill as EL15.

**Key finding:** the elicitation agent never calls `load_skill('elicitation')`
in either run (7 "did not call load_skill" warnings each) — the verbose prompt
was self-sufficient, and so is the slimmed one, because the load-bearing
directives were kept inline. The mounted elicitation skill is effectively read
only when inlined/paraphrased into the prompt; a future "fully skill-driven"
step would need to make the agent actually load it (or inline it), not just
point at it. This is why the slim kept the essentials in the prompt rather than
deleting them in favor of a pointer.
