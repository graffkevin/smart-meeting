import asyncio
import time

from smart_meeting import watchdog


def test_writes_every_stack_when_the_loop_freezes(tmp_path):
    async def freeze():
        watchdog.start(asyncio.get_running_loop(), tmp_path, stall_s=0.5)
        await asyncio.sleep(0)
        time.sleep(2.5)  # blocks the event loop, like a stuck synchronous call

    asyncio.run(freeze())
    traces = watchdog.traces_path(tmp_path).read_text()
    assert "event loop frozen" in traces
    assert "in freeze" in traces
