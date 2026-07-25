---
name: format-skill-fixture
description: >-
  A minimal domain-neutral format skill used only by the test suite to exercise
  the workflow's skill-script execution machinery (discovery, subprocess, JSON
  verdict). Carries no real document domain.
---

# Format Skill Fixture (test-only)

This skill exists solely to give the workflow's `run_skill_script` path a real
script to discover and run. Its `validation/validate.py` applies a trivial
required-presence rule — no domain content, no enums. Validating a real domain
skill's own rules is out of scope for this repo; what the flow suite proves is
that the mounted skill's script is discovered and executed and its verdict
returned. See `tests/test_skill_script.py`.
