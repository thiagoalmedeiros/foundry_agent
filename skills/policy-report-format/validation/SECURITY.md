# Security posture — skill-provided validation code

`validation/validate.py` is **executed** by the workflow: the domain-neutral
`run_skill_validation` tool imports this module and calls its `validate(...)`
entrypoint. Running skill-provided code is safe here for one reason only —
**skills ship inside this repository and are trusted**, the same stance that
lets the project disable `SkillsProvider` tool approvals for its in-repo skills.

What this relies on:

- The skill is authored and reviewed in-repo; it is never fetched at runtime
  from an untrusted source.
- `validate` is **pure** — standard library only, no I/O, no subprocess, no
  network, no global state.
- The workflow passes it plain data (a captured-values mapping and the
  discovered groups) and uses only its returned list of ids.

If this template is ever adapted to load third-party or user-supplied skills,
**replace the direct import with a sandboxed executor** (separate process,
resource limits, no filesystem/network) before trusting their `validate.py`.
Do not mount an untrusted skill and run its code in-process.
