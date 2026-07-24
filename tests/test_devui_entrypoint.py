"""The entrypoints assemble the live workflow and agent without network calls."""

from foundry_agent.workflow import create_policy_report_workflow

_FAKE_ENV = {
    "AZURE_OPENAI_ENDPOINT": "https://example.openai.azure.com/",
    "AZURE_OPENAI_DEPLOYMENT": "gpt-test",
    "AZURE_OPENAI_API_KEY": "test-key",
}


def test_create_policy_report_workflow_builds_all_five_stages(monkeypatch):
    for key, value in _FAKE_ENV.items():
        monkeypatch.setenv(key, value)

    workflow = create_policy_report_workflow()

    assert workflow.name == "policy-report-agent"
    assert {
        "discovery",
        "analysis",
        "elicitation",
        "validation",
        "assembler",
    } <= set(workflow.executors)


def test_devui_entrypoint_serves_the_workflow_as_a_chat_agent(monkeypatch):
    for key, value in _FAKE_ENV.items():
        monkeypatch.setenv(key, value)

    from foundry_agent import main

    agent = main.create_policy_report_agent()

    assert agent.name == "policy-report-agent"
    assert callable(main.main)
    assert main.DEVUI_PORT == 8090


def test_devui_instrumentation_is_selected_by_the_otlp_endpoint(monkeypatch):
    """OTel on exactly when a destination is configured — env-selected, like production."""
    from foundry_agent import main

    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    assert main._instrumentation_enabled() is False

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    assert main._instrumentation_enabled() is True
