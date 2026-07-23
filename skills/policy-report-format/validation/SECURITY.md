# Security posture — skill-provided validation code

`validation/validate.py` is **executed** by the workflow: the Validation agent
calls the skill provider's native `run_skill_script` tool, and the project's
script runner (`_run_python_skill_script` in `src/foundry_agent/agents.py`)
runs this file as a **subprocess** (`python validate.py '<captured JSON>'
'<groups JSON>'`, working directory = this directory, hard timeout). Running
skill-provided code is safe here for one reason only — **skills ship inside
this repository and are trusted**, the same stance that lets the project
disable `SkillsProvider` tool approvals for its in-repo skills.

What this relies on:

- The skill is authored and reviewed in-repo; it is never fetched at runtime
  from an untrusted source. The runner executes only scripts discovered by
  `FileSkillsSource` inside this repository's `skills/` tree.
- `validate` is **pure** — standard library only, no I/O beyond argv/stdout,
  no subprocess, no network, no global state.
- The workflow passes it plain data (a captured-values mapping and the
  discovered groups as JSON argv) and uses only its returned list of ids.
- The subprocess boundary bounds a hung script with a hard timeout, but it is
  **not a sandbox**: the script runs with the host process's privileges.

If this template is ever adapted to load third-party or user-supplied skills,
**replace the plain subprocess runner with a sandboxed executor** (resource
limits, no filesystem/network) before trusting their `validate.py`. Do not
mount an untrusted skill and run its scripts with host privileges.
