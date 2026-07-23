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

### [2026-07-23] — Discovered skill scripts are named by skill-relative path
**Context:** Wiring the Validation agent onto the native `run_skill_script` tool; the runner e2e test asked for the script by file name.
**Mistake:** `get_script("validate.py")` returned None — `FileSkillsSource` names discovered scripts by their skill-relative path, so the real name is `validation/validate.py`. Had the prompt used the bare file name, every model call would have failed at runtime with "script not found".
**Rule:** When naming a skill script in prompts or lookups, use its skill-relative path (`validation/validate.py`), and pin that name with a discovery-based test, never an assumed one.
**Applies to:** `prompts.py` VALIDATION_INSTRUCTIONS, `FileSkillsSource` script lookups, `tests/test_skill_script.py`

