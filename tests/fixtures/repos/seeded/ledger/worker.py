"""Background worker."""

import asyncio


async def flush(queue: list[int]) -> None:
    await asyncio.sleep(0)
    queue.clear()


async def run_once(queue: list[int]) -> int:
    count = len(queue)
    flush(queue)
    return count
