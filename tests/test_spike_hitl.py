"""In-process proof of the HITL pause/resume contract used by the spike."""

from foundry_agent.spike_hitl import SpikeQuestion, build_spike_workflow


async def test_spike_run_pauses_with_one_request():
    workflow = build_spike_workflow()

    result = await workflow.run("hello")

    requests = result.get_request_info_events()
    assert len(requests) == 1
    assert isinstance(requests[0].data, SpikeQuestion)
    assert "hello" in requests[0].data.prompt
    assert result.get_outputs() == []


async def test_spike_resumes_with_answer_and_yields_output():
    workflow = build_spike_workflow()

    paused = await workflow.run("hello")
    request_id = paused.get_request_info_events()[0].request_id

    resumed = await workflow.run(responses={request_id: "world"})

    assert resumed.get_outputs() == ["input='hello' answer='world'"]
