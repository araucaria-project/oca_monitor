import asyncio
from typing import List, Dict, Any, Tuple, Iterable, Set
import numpy as np


class AsyncRangeIter:
    """
    This class represent async iterator (instead of sync).
    WARNING: Be noticed that end is included (not like in normal iterator).
    """
    def __init__(self, start: int, end: int) -> None:
        self.start = start
        self.end = end

    def __aiter__(self) -> Any:
        self.current = self.start
        return self

    async def __anext__(self) -> int:
        if self.current <= self.end:
            value = self.current
            self.current += 1
            await asyncio.sleep(0)
            return value
        else:
            raise StopAsyncIteration


class AsyncListIter:
    def __init__(self, iterable: List | Tuple | Set | np.ndarray):
        self.iterable = iterable
        self.index: int = 0

    def __aiter__(self) -> Any:
        self.index = 0
        return self

    async def __anext__(self):
        if self.index < len(self.iterable):
            value = self.iterable[self.index]
            self.index += 1
            await asyncio.sleep(0)
            return value
        else:
            raise StopAsyncIteration


class AsyncEnumerateIter:
    def __init__(self, iterable: List | Tuple | Set | np.ndarray) -> None:
        self.iterable = iterable

    def __aiter__(self):
        self.index = 0
        return self

    async def __anext__(self):
        if self.index < len(self.iterable):
            value = self.iterable[self.index]
            current_index = self.index
            self.index += 1
            await asyncio.sleep(0)
            return current_index, value
        else:
            raise StopAsyncIteration


class AsyncDictItemsIter:
    def __init__(self, data_dict: Dict) -> None:
        self.data_dict = data_dict

    def __aiter__(self) -> Any:
        self.iterator = iter(self.data_dict.items())
        return self

    async def __anext__(self) -> Tuple:
        try:
            n, m = next(self.iterator)
            await asyncio.sleep(0)
            return n, m
        except StopIteration:
            raise StopAsyncIteration
