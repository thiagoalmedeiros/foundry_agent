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

### [2026-07-23] — azd `.azure/` state was the real gitignore gap, not hosted.env
**Context:** Batch 1 pre-commit secrets check. The plan named `hosted.env` as the file to inspect before the baseline commit.
**Mistake:** `hosted.env` was clean as documented, but the untracked `.azure/foundry-agent-dev/.env` (subscription ID, resource IDs, deployed-agent state) was not covered by `.gitignore` and would have been committed.
**Rule:** In azd-managed projects, always confirm `.azure/` is git-ignored before the first commit — check the whole tree for env-state directories, not just the files a plan names.
**Applies to:** `.gitignore`, git baseline setup in azd projects

### [2026-07-23] — Cross-test references to deleted modules broke the suite
**Context:** Batch 2 deletions. The plan predicted the only surviving `field_groups_parser` reference would be a `workflow.py` docstring.
**Mistake:** `tests/test_discovery.py` (a test for a *different* module) imported the deleted parser to assert discovery never calls it — the suite failed with ModuleNotFoundError after deletion.
**Rule:** When scoping a module deletion, grep `tests/` for the module name too, not just `src/` — tests of other modules may import the dead module as a negative-assertion prop.
**Applies to:** dead-code removal planning, `tests/`

### [2026-07-23] — Stale egg-info metadata trips reference greps after deletions
**Context:** Thomas gate on Batch 2. The verify-line grep over `src/` returned hits for all three deleted modules.
**Mistake:** The hits were in `src/foundry_agent.egg-info/SOURCES.txt` — editable-install metadata frozen at install time, still listing deleted files (plus a stale `d3-initiative-poc` package from before the project rename).
**Rule:** After deleting modules, run `uv sync --reinstall-package foundry-agent` to regenerate egg-info before any grep-based verification — or scope greps to tracked files with `git grep`.
**Applies to:** `src/*.egg-info/`, verify greps, editable installs
