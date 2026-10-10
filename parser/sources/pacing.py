"""Темп запросов на весь процесс, а не на одну задачу (техспека §6).

Пауза между запросами и не больше N запросов в скользящий час. Задачи воркера
идут по очереди, поэтому одного замка на процесс достаточно.
"""

import asyncio
import random
import time
from collections import deque


class Pacer:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._last = 0.0
        self._sent: deque[float] = deque()

    async def wait(self, min_pause_s: float, per_hour: int) -> None:
        await self._lock.acquire()
        now = time.monotonic()
        pause = min_pause_s - (now - self._last)
        while self._sent and now - self._sent[0] > 3600:
            self._sent.popleft()
        if len(self._sent) >= per_hour:
            pause = max(pause, 3600 - (now - self._sent[0]))
        if pause > 0:
            await asyncio.sleep(pause * random.uniform(1.0, 1.25))
        self._sent.append(time.monotonic())

    def done(self) -> None:
        self._last = time.monotonic()
        self._lock.release()


PACER = Pacer()
