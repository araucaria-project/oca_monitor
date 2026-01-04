import asyncio
import logging
from typing import List, Dict, Literal, Optional, Union
import aiohttp
import aiofiles
import datetime


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


async def get_time_ago_text(date: datetime.datetime) -> Optional[Dict[str, Union[str, int, float]]]:
    if date is None:
        return None
    now = datetime.datetime.now(datetime.timezone.utc)
    diff = now - date
    tot_sec = diff.total_seconds()
    if tot_sec < 60:
        return {'total_sec': diff.total_seconds(), 'txt': f'{round(tot_sec)} s ago'}
    elif 3600 > tot_sec >= 60:
        return {'total_sec': diff.total_seconds(), 'txt': f'{round(tot_sec / 60)} min ago'}
    elif 86400 > tot_sec >= 3600:
        return {'total_sec': diff.total_seconds(), 'txt': f'{round(tot_sec / 3600)} h ago'}
    elif tot_sec >= 86400:
        return {'total_sec': diff.total_seconds(), 'txt': f'{round(tot_sec / 86400)} days ago'}
    else:
        return None

