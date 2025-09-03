import asyncio
import logging
import time
from typing import List, Dict, Any, Tuple, Iterable, Set, Literal, Callable

import ephem
import numpy as np
import requests
from astropy.time import Time as czas_astro
import aiofiles
from serverish.messenger import Messenger
from nats.errors import TimeoutError as NatsTimeoutError

logger = logging.getLogger(__name__.rsplit('.')[-1])


def raise_alarm(mess):
    pars = {'token': 'adcte9qacd6jhmhch8dyw4e4ykuod2', 'user': 'uacjyhka7d75k5i3gmfhdg9pc2vqyf', 'message': mess}
    requests.post('https://api.pushover.net/1/messages.json', data=pars)

    # mgorski tez tu nizej
    pars = {'token': "aw8oa41mtt3nqrtg1vu3ny67ajans1", 'user': "ugcgrfrrfn4eefnpiekgwqnxfwtrz5", 'message': mess}
    requests.post('https://api.pushover.net/1/messages.json', data=pars)


def ephemeris():
    arm = ephem.Observer()
    arm.pressure = 730
    # arm.horizon = '-0.5'
    arm.lon = '-70.201266'
    arm.lat = '-24.598616'
    arm.elev = 2800
    arm.pressure = 730
    date = time.strftime('%Y%m%d', time.gmtime())
    ut = time.strftime('%Y/%m/%d %H:%M:%S', time.gmtime())
    t = czas_astro([ut.replace('/', '-', 2).replace(' ', 'T', 1)])
    jd = str(t.jd[0])[:12]
    lt = time.strftime('%Y/%m/%d %H:%M:%S', time.localtime())
    arm.date = ut
    sunset = str(arm.next_setting(ephem.Sun()))
    sunrise = str(arm.next_rising(ephem.Sun()))
    sun = ephem.Sun()
    moon = ephem.Moon()
    sun.compute(arm)
    moon.compute(arm)
    arm.horizon = '-18'

    lst = arm.sidereal_time()
    if str(sun.alt)[0] == '-':
        text = 'UT:\t' + ut + '\nLT:\t' + lt + '\nSIDT:\t' + str(lst) + '\nJD:\t\t' + str(
            "{:.2f}".format(float(jd))) + '\nSUNRISE(UT):\t' + sunrise[-8:] + '\nSUN ALT:\t' + str(sun.alt)
    else:
        text = 'UT:\t' + ut + '\nLT:\t' + lt + '\nSIDT:\t' + str(lst) + '\nJD:\t\t' + str(
            "{:.2f}".format(float(jd))) + '\nSUNSET(UT):\t' + sunset[-8:] + '\nSUN ALT:\t' + str(sun.alt)
    return text, sun.alt


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


async def a_read_file(path: str, raise_err: bool = True, mode: Literal['r'] = 'r') -> str or None:
    try:
        async with aiofiles.open(file=path, mode=mode) as f:
            return await f.read()
    except OSError:
        logger.error(f'Can not read {path} file.')
        if raise_err:
            raise
        else:
            return False

async def run_reader(clb: Callable, subject: str, deliver_policy: str, opt_start_time = None) -> None:
    msg = Messenger()
    rdr = msg.get_reader(
        subject=subject,
        deliver_policy=deliver_policy,
        opt_start_time=opt_start_time
    )
    logger.info(f"Subscribed to {subject}")
    try:
        async for data, meta in rdr:
            try:
                await clb(data=data, meta=meta)
            except (ValueError, TypeError, LookupError, TimeoutError, NatsTimeoutError) as e:
                logger.warning(f"{subject} get error: {e}")
    except (asyncio.CancelledError, asyncio.TimeoutError, NatsTimeoutError, TimeoutError) as e:
        logger.warning(f"{subject} 2 get error: {e}")
