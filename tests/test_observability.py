"""Batch 6 — usage counts reach the active OTel span; managed-identity fallback.

``log_usage`` attaches each call's token counts to the current span so they
land in App Insights on the hosted path. Offline (no exporter) the current span
is non-recording and the annotation is a safe no-op; here an in-memory tracer
provides a recording span so the attributes can be read back.
"""

import os

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from foundry_agent.usage import log_usage


class _Response:
    def __init__(self, usage_details: dict | None) -> None:
        self.usage_details = usage_details


@pytest.fixture
def recorded_spans():
    """A real recording tracer whose finished spans can be inspected.

    Deliberately does NOT call ``trace.set_tracer_provider``: this provider is
    local to the fixture. ``start_as_current_span`` still attaches its span to
    the ambient context, so ``log_usage``'s ``get_current_span()`` finds a
    *recording* span — no global mutation needed. Leaving the global provider
    on its default no-op keeps two things true for the rest of the session:
    ``test_annotation_is_a_safe_no_op_without_a_recording_span`` still sees a
    non-recording current span, and nothing promotes the proxy provider into a
    real one that would activate agent-framework's span export (which otherwise
    probes Azure IMDS and writes to a closed stream at interpreter shutdown).
    """
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    try:
        yield exporter, provider.get_tracer("test")
    finally:
        provider.shutdown()
        exporter.clear()


def test_usage_counts_are_attached_to_the_active_span(recorded_spans):
    exporter, tracer = recorded_spans

    with tracer.start_as_current_span("analysis-call"):
        log_usage(
            "analysis",
            "FG2",
            _Response(
                {
                    "input_token_count": 1200,
                    "output_token_count": 300,
                    "cache_read_input_token_count": 800,
                }
            ),
        )

    (span,) = exporter.get_finished_spans()
    attrs = dict(span.attributes)
    assert attrs["foundry_agent.usage.stage"] == "analysis"
    assert attrs["foundry_agent.usage.group"] == "FG2"
    assert attrs["foundry_agent.usage.input_tokens"] == 1200
    assert attrs["foundry_agent.usage.cached_tokens"] == 800
    assert attrs["foundry_agent.usage.output_tokens"] == 300


def test_annotation_is_a_safe_no_op_without_a_recording_span():
    """Offline (default non-recording span) must not error."""
    record = log_usage("validation", None, _Response({"input_token_count": 10}))

    assert record.input_tokens == 10  # returned normally; no exception


def _capture_client_kwargs(monkeypatch):
    """Replace OpenAIChatClient + DefaultAzureCredential with capturing stubs.

    Returns the dict the (stubbed) client was constructed with, so the auth
    branch is asserted without building a real client or contacting Azure.
    """
    captured: dict[str, object] = {}

    class _StubClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        # create_chat_client reconfigures retries via ``client.client``.
        class _Inner:
            def with_options(self, **kwargs):
                return self

        client = _Inner()

        function_invocation_configuration: dict[str, object] = {}

    class _StubCredential:
        def __init__(self, *args, **kwargs):
            captured["_credential_built"] = True

    import foundry_agent.agents as agents_module

    monkeypatch.setattr(agents_module, "OpenAIChatClient", _StubClient)
    monkeypatch.setattr("azure.identity.DefaultAzureCredential", _StubCredential)
    # create_chat_client calls load_dotenv(), which would repopulate a real
    # AZURE_OPENAI_API_KEY from the repo .env and defeat the no-key branch.
    monkeypatch.setattr(agents_module, "load_dotenv", lambda *a, **k: None)
    return captured


def test_managed_identity_is_used_when_no_api_key(monkeypatch):
    """The hosted path authenticates with DefaultAzureCredential, not a key."""
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com/")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-test")
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    captured = _capture_client_kwargs(monkeypatch)

    from foundry_agent.agents import create_chat_client

    create_chat_client()

    assert captured.get("_credential_built") is True
    assert "credential" in captured
    assert "api_key" not in captured


def test_api_key_is_preferred_when_present(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com/")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-test")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "a-real-key")
    captured = _capture_client_kwargs(monkeypatch)

    from foundry_agent.agents import create_chat_client

    create_chat_client()

    assert captured.get("api_key") == "a-real-key"
    assert "credential" not in captured
    assert "_credential_built" not in captured


def test_foundry_project_endpoint_is_used_when_no_explicit_endpoint(monkeypatch):
    """Hosted path: the platform-injected FOUNDRY_PROJECT_ENDPOINT needs no azure.yaml set."""
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://injected.services.ai.azure.com/")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-test")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "a-real-key")
    captured = _capture_client_kwargs(monkeypatch)

    from foundry_agent.agents import create_chat_client

    create_chat_client()

    assert captured.get("azure_endpoint") == "https://injected.services.ai.azure.com/"


def test_explicit_endpoint_wins_over_the_injected_one(monkeypatch):
    """A local AZURE_OPENAI_ENDPOINT override always beats the platform default."""
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://explicit.openai.azure.com/")
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://injected.services.ai.azure.com/")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-test")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "a-real-key")
    captured = _capture_client_kwargs(monkeypatch)

    from foundry_agent.agents import create_chat_client

    create_chat_client()

    assert captured.get("azure_endpoint") == "https://explicit.openai.azure.com/"


# Batch 8 — local OTel dev-parity. ``_configure_local_otel_defaults`` sets the
# two environment variables the Foundry hosting SDK's own OTel distro reads
# (it — not this package — owns the TracerProvider), so local dev resolves
# the same way the real platform's injected variables already do in
# production.


def test_foundry_agent_name_defaults_when_unset(monkeypatch):
    monkeypatch.delenv("FOUNDRY_AGENT_NAME", raising=False)

    from foundry_agent.hosting import AGENT_NAME, _configure_local_otel_defaults

    _configure_local_otel_defaults()

    assert os.environ["FOUNDRY_AGENT_NAME"] == AGENT_NAME


def test_foundry_agent_name_is_not_overridden_when_the_platform_already_set_it(monkeypatch):
    """A real Foundry deployment injects this itself — setdefault must not clobber it."""
    monkeypatch.setenv("FOUNDRY_AGENT_NAME", "platform-injected-name")

    from foundry_agent.hosting import _configure_local_otel_defaults

    _configure_local_otel_defaults()

    assert os.environ["FOUNDRY_AGENT_NAME"] == "platform-injected-name"


def test_sensitive_data_capture_var_is_untouched_when_enable_sensitive_data_is_unset(monkeypatch):
    """Production-safety case: neither var is set in production today.

    Syncing from an *unset* (merely defaulted) ``ENABLE_SENSITIVE_DATA`` would
    silently flip the distro's own default (capture on) to off — this must
    stay a no-op so production behavior never changes.
    """
    monkeypatch.delenv("ENABLE_SENSITIVE_DATA", raising=False)
    monkeypatch.delenv("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", raising=False)

    from foundry_agent.hosting import _configure_local_otel_defaults

    _configure_local_otel_defaults()

    assert "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT" not in os.environ


@pytest.mark.parametrize(
    ("enable_sensitive_data", "expected"),
    [
        ("true", "true"),
        ("True", "true"),
        ("1", "true"),
        ("false", "false"),
        ("False", "false"),
        ("0", "false"),
    ],
)
def test_sensitive_data_capture_var_syncs_when_explicitly_set(
    monkeypatch, enable_sensitive_data, expected
):
    monkeypatch.setenv("ENABLE_SENSITIVE_DATA", enable_sensitive_data)

    from foundry_agent.hosting import _configure_local_otel_defaults

    _configure_local_otel_defaults()

    assert os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] == expected
