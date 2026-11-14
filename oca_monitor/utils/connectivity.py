"""Connectivity of this computer: INTERNET, ROUTER, NATS (2026-11-14).

One checker per process (``get_connectivity``), shared by the ``health`` page (shows the three tiles) and the
``message`` page (plays the local SYSTEM ALERT when one of them goes down - it must not depend on NATS, so the
judging is done here, locally, and not sent over NATS).

* INTERNET - TCP connect to port 443 of ``internet_hosts`` every ``NET_PERIOD`` s (a name tests DNS too, an IP
  address does not). Green when at least two answer, orange when one, red when none; names failing while an IP
  answers = orange "NO DNS".
* ROUTER - one ICMP ping of ``router_host``; one failed round orange, two in a row red.
* NATS - the client connection (serverish ``Messenger``) and the age of the last live message: heartbeats
  ``svc.heartbeat.>`` arrive every 5-10 s; more than ``NATS_DATA_WARN`` s orange, ``NATS_DATA_BAD`` s red.
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import subprocess
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from serverish.base.task_manager import create_task
from serverish.messenger import Messenger

logger = logging.getLogger(__name__.rsplit('.')[-1])

OK, WARN, BAD, NONE = 'ok', 'warn', 'bad', 'none'

NET_PERIOD = 10.0               # s, internet and router checks
NET_TIMEOUT = 4.0               # s, one TCP connect / ping
NATS_DATA_WARN, NATS_DATA_BAD = 30.0, 120.0     # s without any message while connected
NATS_DISCONNECTED_BAD = 30.0    # s disconnected before red (nats-py reconnects in a few seconds)
STARTUP_GRACE = 30.0            # s after start: grey "checking" instead of red
INTERNET_HOSTS = ['google.com', 'camk.edu.pl', 'xkcd.com', '1.1.1.1']
ROUTER_HOST = '192.168.7.1'
HEARTBEAT_SUBJECT = 'svc.heartbeat.>'


@dataclass
class Check:
    """the state of one system: state OK / WARN / BAD / NONE, short text (OK, DOWN, ...), detail"""
    state: str = NONE
    text: str = 'checking…'
    detail: str = ''
    values: Dict[str, Optional[float]] = field(default_factory=dict)   # host -> ms (None: failed)


def is_ip(host: str) -> bool:
    return host.replace('.', '').isdigit()


def _nats_time(meta) -> float:
    try:
        return datetime.datetime(*meta['nats']['timestamp'][:6], tzinfo=datetime.timezone.utc).timestamp()
    except Exception:
        return time.time()


class Connectivity:
    def __init__(self, router_host: str = ROUTER_HOST, internet_hosts: Optional[List[str]] = None):
        self.router_host = router_host
        self.internet_hosts = list(internet_hosts or INTERNET_HOSTS)
        self.start = time.monotonic()
        self.last_msg: Optional[float] = None       # monotonic time of the last live NATS message
        self.inet: Optional[Dict[str, Optional[float]]] = None
        self.router_ms: Optional[float] = None
        self.router_fails: Optional[int] = None     # failed rounds in a row (None: not asked yet)
        self.disconnected_since: Optional[float] = None
        self.uplink: Optional[str] = None           # Paranal / Starlink (wan-watchdog), set by a page
        self._started = False

    # ---- start --------------------------------------------------------------

    async def start_checks(self, main_window) -> None:
        """the net loop and the heartbeat reader - once per process"""
        if self._started:
            return
        self._started = True
        await create_task(self._internet_loop(), 'connectivity_internet_loop')
        await create_task(self._router_loop(), 'connectivity_router_loop')
        try:
            await main_window.run_reader(clb=self._heartbeat_clb, subject=HEARTBEAT_SUBJECT, deliver_policy='new')
        except Exception as e:
            logger.warning(f"connectivity: heartbeat reader failed: {e!r}")

    async def _heartbeat_clb(self, data, meta) -> bool:
        self.got_msg(meta)
        return True

    def got_msg(self, meta) -> None:
        """a NATS message was received - NATS works end to end (only live ones, not old replayed values)"""
        lag = time.time() - _nats_time(meta)
        if lag < NATS_DATA_BAD:
            t = time.monotonic() - max(0.0, lag)
            self.last_msg = t if self.last_msg is None else max(t, self.last_msg)

    # ---- checks -------------------------------------------------------------

    @staticmethod
    async def _connect(host) -> Optional[float]:
        t0 = time.monotonic()
        try:
            _, w = await asyncio.wait_for(asyncio.open_connection(host, 443), NET_TIMEOUT)
            w.close()
            return (time.monotonic() - t0) * 1000
        except Exception:
            return None

    @staticmethod
    def _ping_blocking(host) -> Optional[float]:
        try:
            p = subprocess.run(['ping', '-n', '-c', '1', '-W', str(int(NET_TIMEOUT)), host],
                               capture_output=True, text=True, timeout=NET_TIMEOUT + 2)
            if p.returncode != 0:
                return None
            i = p.stdout.find('time=')
            return float(p.stdout[i + 5:].split()[0].removesuffix('ms')) if i >= 0 else 0.0
        except Exception:
            return None

    @classmethod
    async def _ping(cls, host) -> Optional[float]:
        """in a thread: asyncio subprocesses under qasync finish late (ping of 4 s seen ending after 18 s)"""
        return await asyncio.get_running_loop().run_in_executor(None, cls._ping_blocking, host)

    async def _internet_loop(self):
        while True:
            try:
                answers = await asyncio.gather(*(self._connect(h) for h in self.internet_hosts))
                self.inet = dict(zip(self.internet_hosts, answers))
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"connectivity internet loop: {e!r}")
            await asyncio.sleep(NET_PERIOD)

    async def _router_loop(self):
        while True:
            try:
                ms = await self._ping(self.router_host)
                self.router_ms = ms
                self.router_fails = 0 if ms is not None else (self.router_fails or 0) + 1
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"connectivity router loop: {e!r}")
            await asyncio.sleep(NET_PERIOD)

    # ---- judging ------------------------------------------------------------

    def _waiting(self) -> bool:
        return time.monotonic() - self.start < STARTUP_GRACE

    def internet(self) -> Check:
        if self.inet is None:
            return Check()
        ok = [h for h, ms in self.inet.items() if ms is not None]
        n = len(ok)
        state = OK if n >= 2 else WARN if n == 1 else BAD
        text = 'OK' if state == OK else 'DOWN' if state == BAD else 'POOR'
        if ok and all(is_ip(h) for h in ok):
            state, text = WARN, 'NO DNS'
        failed = [h for h, ms in self.inet.items() if ms is None]
        return Check(state, text, 'no answer from ' + ', '.join(failed) if failed else '', dict(self.inet))

    def router(self) -> Check:
        if self.router_fails is None:
            return Check(detail=self.router_host)
        if self.router_fails == 0:
            ms = f' ping {self.router_ms:.0f} ms' if self.router_ms is not None else ''
            return Check(OK, 'OK', f'{self.router_host}{ms}')
        return Check(WARN if self.router_fails == 1 else BAD, 'NO PING',
                     f'{self.router_host} {self.router_fails} failed in a row')

    def nats(self) -> Check:
        try:
            nc = Messenger().connection.nc
            connected = nc is not None and nc.is_connected
        except Exception:
            connected = False
        now = time.monotonic()
        if connected:
            self.disconnected_since = None
        elif self.disconnected_since is None:
            self.disconnected_since = now
        age = None if self.last_msg is None else now - self.last_msg
        if not connected:
            if self._waiting() or now - self.disconnected_since < NATS_DISCONNECTED_BAD:
                return Check(NONE if self._waiting() else WARN, 'connecting…', 'no connection')
            return Check(BAD, 'DISCONNECTED', 'no connection - nothing can be reported')
        if age is None or age > NATS_DATA_BAD:
            if self._waiting():
                return Check(NONE, 'waiting…', 'connected, waiting for messages')
            return Check(BAD, 'NO DATA', 'connected, but no messages arrive')
        state = OK if age <= NATS_DATA_WARN else WARN
        return Check(state, 'OK' if state == OK else 'SLOW', f'last message {age:.0f} s ago', {'age': age})

    def all(self) -> Dict[str, Check]:
        return {'INTERNET': self.internet(), 'ROUTER': self.router(), 'NATS': self.nats()}


_instance: Optional[Connectivity] = None


def get_connectivity(router_host: str = ROUTER_HOST, internet_hosts: Optional[List[str]] = None) -> Connectivity:
    """the one checker of this process (the first caller's hosts win)"""
    global _instance
    if _instance is None:
        _instance = Connectivity(router_host, internet_hosts)
    return _instance
