import asyncio

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Coroutine
import qasync

from PyQt5.QtGui import QStandardItem

class CaleToZlo(ABC):

    def __init__(self, loop: qasync.QEventLoop = None):
        self.loop: qasync.QEventLoop = loop
        self._background_tasks: List[CaleToZlo.BackgroundTask] = []

    @dataclass
    class BackgroundTask:
        coro: Coroutine
        name: str = ""
        task: asyncio.Task = None
        created: bool = False

        def __post_init__(self):
            pass

    def add_background_task(self, coro: Coroutine, name: str = ""):
        self._background_tasks.append(self.BackgroundTask(name=name, coro=coro))

    async def run_background_tasks(self):
        await self._run_all_background_task()

    async def _run_all_background_task(self):
        if self.loop is None:
            raise RuntimeError
        for bt in self._background_tasks:
            name = bt.name
            co = bt.coro
            t = self.loop.create_task(co, name=name)
            bt.task = t
            bt.created = True

    async def stop_background_tasks(self):
        await self._stop_background_tasks()

    async def _stop_background_tasks(self):
        for bt in self._background_tasks:
            t = bt.task
            if t and t in asyncio.all_tasks(self.loop) and not t.done():
                t.cancel()

        time_to_close = 0.5
        for bt in self._background_tasks:
            t = bt.task
            if t and t in asyncio.all_tasks(self.loop):
                try:
                    await wait_for_psce(t, timeout=time_to_close)  # the task should finish in less than 0.5 seconds
                except Exception as e:
                    pass

    async def on_start_app(self):
        await self.run_background_tasks()

    @qasync.asyncClose
    async def closeEvent(self, event):
        await self.stop_background_tasks()
        super().closeEvent(event)





class MetaCaleToZlo(type(QStandardItem), type(CaleToZlo)):
    pass