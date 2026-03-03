"""Genesis brain package — local inference backend adapters.

The primary backend is ``SakuraBrain``, which wraps the Sakura engine and loads
its weights from a ``.jadepack`` file.  All brains implement ``AbstractBrain``
so the runtime can swap backends without changing its own code.

Quick start
-----------
    from genesis.brain import SakuraBrain

    brain = SakuraBrain(jadepack_path="data/openml/jade/sakura_v1.jadepack")
    brain.load_from_jadepack(brain.jadepack_path)

    # Streaming reply
    import asyncio

    async def chat():
        from genesis.brain import BrainMessage
        msgs = [BrainMessage(role="user", content="Hello, who are you?")]
        async for event in brain.stream_reply(msgs):
            if event.type == "delta" and event.text:
                print(event.text, end="", flush=True)

    asyncio.run(chat())
"""

from .adapter_base import AbstractBrain, BrainMessage, BrainStreamEvent  # noqa: F401
from .sakura_brain import SakuraBrain  # noqa: F401

__all__ = [
    "AbstractBrain",
    "BrainMessage",
    "BrainStreamEvent",
    "SakuraBrain",
]
