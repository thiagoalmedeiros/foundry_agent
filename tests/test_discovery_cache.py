"""The discovery memo: one live discovery per process, reused across interviews.

These tests drive :class:`DiscoveryExecutor` directly against a stub client, so
the client's ``.calls`` counter is a faithful proxy for "did the discovery LLM
call actually run?". ``@handler`` wraps ``start`` in a pass-through coroutine, so
the executor's entry point is callable directly with a recording context double.
"""

from foundry_agent.agents import create_discovery_agent
from foundry_agent.workflow import DiscoveryCache, DiscoveryExecutor
from tests.conftest import GROUPS


class _RecordingContext:
    """A minimal WorkflowContext double that records the runs an executor emits."""

    def __init__(self) -> None:
        self.sent: list[object] = []

    async def send_message(self, message: object) -> None:
        self.sent.append(message)


def _group_ids(context: _RecordingContext) -> list[str]:
    """The group ids on the single Run the executor emitted."""
    (run,) = context.sent
    return [group["group_id"] for group in run.groups]


async def test_cache_hit_skips_the_second_discovery(make_stub_client):
    """A shared cache makes the discovery agent run once across two interviews."""
    client = make_stub_client(GROUPS)
    cache = DiscoveryCache()
    executor = DiscoveryExecutor(agent=create_discovery_agent(client), cache=cache)

    first, second = _RecordingContext(), _RecordingContext()
    await executor.start("first interview", first)
    await executor.start("second interview", second)

    assert client.calls == 1  # discovery ran on the first, reused on the second
    assert _group_ids(first) == _group_ids(second) == ["FG1", "FG2"]


async def test_shared_cache_serves_a_second_executor(make_stub_client):
    """A cache shared between fresh executors (the chat-mode shape) skips re-discovery."""
    first_client = make_stub_client(GROUPS)
    second_client = make_stub_client(GROUPS)
    cache = DiscoveryCache()

    await DiscoveryExecutor(
        agent=create_discovery_agent(first_client), cache=cache
    ).start("conversation one", _RecordingContext())
    await DiscoveryExecutor(
        agent=create_discovery_agent(second_client), cache=cache
    ).start("conversation two", _RecordingContext())

    assert first_client.calls == 1  # the first conversation discovered
    assert second_client.calls == 0  # the second reused the shared memo


async def test_fresh_cache_rediscovers(make_stub_client):
    """A distinct cache instance is a distinct memo — discovery runs again."""
    first_client = make_stub_client(GROUPS)
    second_client = make_stub_client(GROUPS)

    await DiscoveryExecutor(
        agent=create_discovery_agent(first_client), cache=DiscoveryCache()
    ).start("process one", _RecordingContext())
    await DiscoveryExecutor(
        agent=create_discovery_agent(second_client), cache=DiscoveryCache()
    ).start("process two", _RecordingContext())

    assert first_client.calls == 1
    assert second_client.calls == 1


async def test_injected_field_groups_bypasses_discovery_and_cache(make_stub_client):
    """Injected groups win over both the cache and the agent — no call, no memo write."""
    client = make_stub_client(GROUPS)
    cache = DiscoveryCache()
    executor = DiscoveryExecutor(
        agent=create_discovery_agent(client), groups=GROUPS, cache=cache
    )

    context = _RecordingContext()
    await executor.start("injected run", context)

    assert client.calls == 0  # discovery agent never driven
    assert cache.get() is None  # the injected override does not poison the cache
    assert _group_ids(context) == ["FG1", "FG2"]
