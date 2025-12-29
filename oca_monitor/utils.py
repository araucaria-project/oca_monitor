import asyncio
import logging
import time
from typing import List, Dict, Any, Tuple, Iterable, Set, Literal, Callable, Optional
import aiohttp
import ephem
import requests
from astropy.time import Time as czas_astro
import aiofiles


logger = logging.getLogger(__name__.rsplit('.')[-1])


async def send_http(
        name: str, url: str, data: Optional[Dict] = None, json: Optional[Dict] = None, timeout: float = 5) -> None:

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            await session.post(
                url,
                json=json,
                data=data
            )
            logger.info(f'{name} sent to {url}')
    except (aiohttp.ClientError, asyncio.TimeoutError):
        logger.error(f'{name} can not be send')


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


async def a_read_file(path: str, raise_err: bool = True, mode: Literal['r'] = 'r') -> Optional[str]:
    try:
        async with aiofiles.open(file=path, mode=mode) as f:
            return await f.read()
    except OSError:
        logger.error(f'Can not read {path} file.')
        if raise_err:
            raise
        else:
            return None
