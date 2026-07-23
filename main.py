"""Foundry code-deploy entrypoint (``codeConfiguration.entryPoint`` in azure.yaml).

Foundry's Python code-deploy runtime installs the locked dependencies and runs
``python main.py`` from the project root — but it does NOT pip-install this
project itself (witnessed 2026-07-22: ``ModuleNotFoundError: foundry_agent``
in the hosted session), so the ``src/`` layout must be put on ``sys.path``
here. Locally the editable install makes the insert a harmless no-op.

All serving logic lives in :func:`foundry_agent.hosting.main`, which is also
the module entrypoint used by ``task hosted:run``
(``python -m foundry_agent.hosting``). Keeping both paths routed through one
function means local and hosted serving cannot drift.
"""

import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

# Non-secret hosted config (deployment name, endpoint). Loaded here because
# agent-level env registration does not reach session containers on
# azure.ai.agents 1.0.0-beta.6; override=False keeps platform env authoritative
# whenever it does arrive.
load_dotenv(Path(__file__).resolve().parent / "hosted.env")

from foundry_agent.hosting import main  # noqa: E402  (path shim must precede)

if __name__ == "__main__":
    main()
