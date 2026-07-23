"""Error recovery: transient-error retry on the model client.

Batch 3 of the production-readiness plan. The client factory raises the
openai SDK's built-in retry count (it already backs off on 429/5xx/connection
errors) via the SDK's own ``with_options`` — no bespoke retry loop — and keeps
it env-tunable. These tests pin the configured value and its env override; the
SDK's backoff behaviour itself is the SDK's own tested contract.

The other failure mode surfaced this batch — a client disconnect mid-run
wedging the shared workflow instance — is a host/framework limitation with no
POC-side reset (``Workflow.status`` is read-only, no rebuild hook). It is
witnessed and analysed in
the predecessor project's error-recovery record with an
upstream ask, not patched with a fragile local hack.
"""

from foundry_agent.agents import create_chat_client

_FAKE_ENV = {
    "AZURE_OPENAI_ENDPOINT": "https://example.openai.azure.com/",
    "AZURE_OPENAI_DEPLOYMENT": "gpt-test",
    "AZURE_OPENAI_API_KEY": "test-key",
}


def _with_env(monkeypatch, **extra):
    for key, value in {**_FAKE_ENV, **extra}.items():
        monkeypatch.setenv(key, value)


def test_default_retry_count_is_raised_above_the_sdk_default(monkeypatch):
    """~58 model calls per interview — the SDK default of 2 is too thin."""
    _with_env(monkeypatch)

    client = create_chat_client()

    assert client.client.max_retries == 6


def test_retry_count_is_env_tunable(monkeypatch):
    _with_env(monkeypatch, AZURE_OPENAI_MAX_RETRIES="10")

    client = create_chat_client()

    assert client.client.max_retries == 10


def test_request_timeout_is_env_tunable(monkeypatch):
    _with_env(monkeypatch, AZURE_OPENAI_TIMEOUT_SECONDS="45")

    client = create_chat_client()

    assert client.client.timeout == 45.0


def test_the_framework_api_version_default_is_preserved(monkeypatch):
    """Reconfiguring retries must not disturb the api_version the client needs.

    The factory deliberately does not read AZURE_OPENAI_API_VERSION (the
    repo-wide value breaks this API surface); ``with_options`` must keep the
    framework's own default rather than reset it.
    """
    _with_env(monkeypatch)

    client = create_chat_client()

    assert client.client._api_version == "preview"
