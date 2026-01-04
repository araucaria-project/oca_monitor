import asyncio
import logging
from typing import List, Dict, Literal, Optional
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


async def get_time_ago_text(date: datetime.datetime) -> str:
    if date is None:
        return ''
    now = datetime.datetime.now(datetime.timezone.utc)
    diff = now - date,
    if diff.total_seconds() < 60:
        return f'{round(diff.total_seconds())} s ago'
    elif 3600 > diff.total_seconds() >= 60:
        return f'{round(diff.total_seconds() / 60)} min ago'
    elif diff.total_seconds() > 3600:
        return f'{round(diff.total_seconds() / 3600)} h ago'
    elif diff.total_seconds() > 86400:
        return f'{round(diff.total_seconds() / 86400)} days ago'
    else:
        return ''

