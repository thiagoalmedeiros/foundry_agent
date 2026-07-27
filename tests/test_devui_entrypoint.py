"""The entrypoints assemble the live workflow and agent without network calls."""

import os

from foundry_agent.workflow import create_report_workflow

_FAKE_ENV = {
    "AZURE_OPENAI_ENDPOINT": "https://example.openai.azure.com/",
    "AZURE_OPENAI_DEPLOYMENT": "gpt-test",
    "AZURE_OPENAI_API_KEY": "test-key",
}


def test_create_report_workflow_builds_all_stages(monkeypatch):
    for key, value in _FAKE_ENV.items():
        monkeypatch.setenv(key, value)

    workflow = create_report_workflow()

    assert workflow.name == "report-interview-agent"
    # No gap-analysis stage: discovery hands straight to elicitation.
    assert {
        "discovery",
        "elicitation",
        "validation",
        "assembler",
    } <= set(workflow.executors)
    assert "analysis" not in set(workflow.executors)


def test_devui_entrypoint_serves_the_workflow_as_a_chat_agent(monkeypatch):
    for key, value in _FAKE_ENV.items():
        monkeypatch.setenv(key, value)

    from foundry_agent import main

    agent = main.create_report_agent()

    assert agent.name == "report-interview-agent"
    assert callable(main.main)
    assert main.DEVUI_PORT == 8090


def test_devui_entrypoint_serves_flow2_as_a_chat_agent(monkeypatch):
    """The --functional switch builds Flow 2 as a chat agent (no approval panel), offline."""
    for key, value in _FAKE_ENV.items():
        monkeypatch.setenv(key, value)

    from foundry_agent import main

    agent = main.create_hybrid_agent()

    assert agent.name == "report-interview-functional"
    assert type(agent).__name__ == "FunctionalWorkflowChatAgent"
    # The default (no-flag) entrypoint is unchanged — still the Flow 1 chat agent.
    assert main.create_report_agent().name == "report-interview-agent"


def test_devui_entrypoint_binds_one_shared_discovery_cache(monkeypatch):
    """DevUI rebuilds the workflow per conversation, so it binds one cache above
    the factory — the discovery memo must span conversations, not reset each one."""
    from foundry_agent import main

    seen: list[object] = []

    def _recording_factory(discovery_cache=None):
        seen.append(discovery_cache)
        return object()  # a stand-in workflow; the wrapper only stores the factory

    monkeypatch.setattr(main, "create_report_workflow", _recording_factory)

    factory = main.create_report_agent()._workflow_factory
    factory()
    factory()

    assert seen[0] is not None, "the factory must receive a DiscoveryCache, not None"
    assert seen[0] is seen[1], "both conversations must share the same cache instance"


def test_devui_instrumentation_requires_a_listening_collector(monkeypatch):
    """OTel on only when a destination is configured AND answering.

    ``.env`` keeps the endpoint set permanently, so a configured-but-absent
    collector must disable instrumentation AND unset the endpoint — DevUI's
    own executor builds exporters from that env var regardless of the serve
    flag, so leaving it set would spam the trace/metric/log exporters against
    a closed port forever.
    """
    import socket

    from foundry_agent import main

    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    assert main._prepare_instrumentation() is False, "unset endpoint means OFF"

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    try:
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", f"http://127.0.0.1:{port}")
        assert main._prepare_instrumentation() is True, "listening collector means ON"
        assert os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") == f"http://127.0.0.1:{port}", (
            "a live collector's endpoint must be left in place for the exporters"
        )
    finally:
        listener.close()

    # Port now closed: OFF, and the endpoint must be removed so DevUI's
    # configure_otel_providers() creates no exporters against the dead port.
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", f"http://127.0.0.1:{port}")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf")
    assert main._prepare_instrumentation() is False, "closed port means OFF, not retry spam"
    assert "OTEL_EXPORTER_OTLP_ENDPOINT" not in os.environ, "dead endpoint must be unset"
    assert "OTEL_EXPORTER_OTLP_PROTOCOL" not in os.environ
