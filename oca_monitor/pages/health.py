"""System health panel (monitor2, 2026-11-12): the whole list, always shown, green when fine. No clicking.

CONNECTIVITY (2026-11-14) - the three big tiles on top, the things without which nothing else is reported. The checks
are in ``oca_monitor/utils/connectivity.py`` (shared with the ``message`` page, which plays the local SYSTEM ALERT):

* INTERNET - TCP connect to port 443 of a few hosts (``internet_hosts``: names test DNS too, an IP address does not);
  green when at least two answer, orange when one, red when none. Names failing while the IP answers = DNS problem.
  The uplink in use (Paranal / Starlink, wan-watchdog ``svc.publish.oca.wan.status``) is shown next to it.
* ROUTER - ICMP ping of ``router_host`` (192.168.7.1); one failed round orange, two in a row red.
* NATS - the client connection (serverish ``Messenger``) and the age of the last message received by this page
  (``svc.heartbeat.>`` arrive every 5-10 s): connected and data red / orange / green.

Below them, information only (no alarm, 2026-11-14): OVERWATCHES (alive RPC + alerts to acknowledge) and TIC / PMS -
TIC per telescope by the age of ``tic.telemetry.<tel>.>`` (TIC itself speaks ZMQ, not NATS; pms.tic bridges it), pms
units by the age of what each publishes (``PMS_UNITS``).

The other detailed sections are shown only with the page option ``details = true`` (Marek 2026-11-14: too much
information; the panel starts with the three tiles, the rest to be chosen).

Dots: green ok, orange warning, red bad, grey unknown / not applicable (e.g. allsky by day, still waiting for the first
heartbeat). Every row is judged from what arrives on NATS; the age of a message is taken from its NATS (JetStream)
timestamp, not from the payload ``ts`` (some senders, e.g. the water meter, write it in Chile local time).

* SITE DATA - freshness of the site telemetry (Davis, allsky_overwatch clouds, SMA power, water meter), temperature of
  the server room and the battery room (``telemetry.conditions.*``).
* OVERWATCHES - alive RPC ``rpc.overwatch.oca.<name>.alive`` (as TOI), alerts waiting for an acknowledgement
  (``status.overwatch.oca.self.alerts``: a problem red, only events orange).
* SERVICES - heartbeats ``svc.heartbeat.>`` (every 5-10 s; none for ``HEARTBEAT_STALE`` s = red), guider state from
  ``svc.status.guiding_svc.guider.*``.
* TELESCOPES - per telescope: any ``tic.telemetry.<tel>.>`` (pms publishes on change, so only orange when quiet),
  downloader / OFP pipeline alive RPC (``tic.rpc.<tel>.download|pipeline.alive``, as TOI), age of the last saved
  frame (``tic.status.<tel>.download``), TOI OB (``status.toi.<tel>.self.ob``: error red), plan runner error
  (``tic.planner.<tel>.status.error`` in the last ``PLANNER_ERROR_HOURS``: red when no plan was loaded after it,
  else orange), CCD temperature vs set point.
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import time
from typing import Callable, Dict, List, Optional, Tuple

from PyQt6 import QtCore, QtGui
from PyQt6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget
from qasync import asyncSlot
from serverish.base.task_manager import create_task
from serverish.messenger import request

from oca_monitor.config import settings
from oca_monitor.pages.site_status import _Group
from oca_monitor.pages.telescopes import icon
from oca_monitor.utils.connectivity import INTERNET_HOSTS, ROUTER_HOST, get_connectivity, is_ip
from oca_monitor.utils.ephem_ocm import sun_alt_deg

logger = logging.getLogger(__name__.rsplit('.')[-1])

OK, WARN, BAD, NONE = 'ok', 'warn', 'bad', 'none'
COLORS = {OK: '#6ed0a8', WARN: '#ffaa33', BAD: '#ff4d4d', NONE: '#5a5a5a'}
TEXT = '#d8d8d8'
DIM = '#808080'

TELESCOPES = ('wk06', 'zb08', 'jk15')
HEARTBEAT_STALE = 30.0          # s
RPC_PERIOD = 10.0               # s
PLANNER_ERROR_HOURS = 14.0      # an error this recent belongs to tonight
ROOM_WARN_C, ROOM_BAD_C = 30.0, 35.0
UPLINK_COLORS = {'paranal': '#6ed0a8', 'starlink': '#ffaa33'}
CCD_WARN, CCD_BAD = 2.0, 5.0    # deg from the set point

# heartbeat service ids
SERVICES: List[Tuple[str, List[Tuple[str, str]]]] = [
    ('optics', [(t, f'optics.{t}') for t in TELESCOPES]),
    ('dome follow', [(t, f'dome_follower_svc.dome_follower.{t}-dome_follower') for t in TELESCOPES]),
    ('', [('thumbnails', 'thumbnail_svc.server.services01-jk15'), ('plans sync', 'plans_sync.ocm'),
          ('sroca', 'sroca.main.dev')]),
    ('', [('Halina', 'halina_server.prod'), ('ephemeris', 'ephemeris_service.prod'),
          ('MCP', 'observatory_mcp_service.prod')]),
]
GUIDER_ID = 'guiding_svc.guider.jk15-guider_beso'
OVERWATCHES = ('conditions', 'flat', 'allsky')
# TIC / PMS (2026-11-14, information only): no direct check of TIC here (ocabox / ZMQ), so TIC per telescope = age of
# tic.telemetry.<tel>.> (pms.tic bridges TIC to NATS; mount / ccd temperature are published continuously), and every
# pms unit = age of what it publishes. (key, name, subject(s) seen under the key, ok s, warn s)
TIC_OK, TIC_WARN = 60.0, 300.0
PMS_UNITS = (
    ('pms.tic', 'tic', None, TIC_OK, TIC_WARN),                                 # any tic.telemetry.<tel>
    ('pms.rest', 'rest', 'telemetry.conditions.>', 300.0, 900.0),               # BleBox sensors
    ('pms.modbus', 'modbus', 'telemetry.power.data-manager', 60.0, 300.0),      # SMA inverter, ~5 s
    ('pms.aggregator', 'aggregator', 'svc.publish.oca.observatory.>', 60.0, 180.0),   # products every 15-30 s
)
# heartbeat / svc.status words: busy (dome follower working), idle (guider waiting) are normal
HB_OK = {'ok', 'busy', 'idle', 'running', 'startup'}
HB_BAD = {'error', 'failed', 'crashed', 'dead'}         # anything else (degraded, warning, ...) orange


def _nats_time(meta) -> float:
    try:
        return datetime.datetime(*meta['nats']['timestamp'][:6], tzinfo=datetime.timezone.utc).timestamp()
    except Exception:
        return time.time()


def _age(sec: Optional[float]) -> str:
    if sec is None:
        return '—'
    sec = max(0.0, sec)
    if sec < 90:
        return f'{sec:.0f} s'
    m = int(sec // 60)
    if m < 90:
        return f'{m} min'
    h = m // 60
    return f'{h} h' if h < 48 else f'{h // 24} d'


def _short_age(sec: Optional[float]) -> str:
    if sec is None:
        return '—'
    m = int(max(0.0, sec) // 60)
    return f'{m}m' if m < 90 else f'{m // 60}h' if m < 48 * 60 else f'{m // 1440}d'


def _fresh(age: Optional[float], ok_s: float, warn_s: float) -> str:
    if age is None:
        return BAD
    return OK if age <= ok_s else WARN if age <= warn_s else BAD


class _Dot(QLabel):
    """● + text in one rich-text label"""

    def __init__(self, font: QtGui.QFont, text: str = ''):
        super().__init__()
        self.setFont(font)
        self.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self._last = None
        self.setProperty('name', text)     # the row name, kept for set()
        self.set(NONE, text)

    def set(self, state: str, text: str = '', text_color: str = TEXT) -> None:
        html = f'<span style="color:{COLORS[state]}">●</span>' + (
            f' <span style="color:{text_color}">{text}</span>' if text else '')
        if html != self._last:      # setText only on a change
            self._last = html
            self.setText(html)


class HealthWidget(QWidget):
    """See module docstring."""

    def __init__(self, main_window, details: bool = False, router_host: str = ROUTER_HOST,
                 internet_hosts: Optional[List[str]] = None,
                 net_subject: str = 'svc.publish.oca.wan.status', **kwargs) -> None:
        super().__init__()
        self.main_window = main_window
        self.details = bool(details)
        self.conn = get_connectivity(router_host, internet_hosts or INTERNET_HOSTS)
        self.net_subject = net_subject
        self.start = time.time()
        self.seen: Dict[str, float] = {}        # subject / key -> NATS time of the last message
        self.values: Dict[str, object] = {}     # key -> last payload of interest
        self.heartbeats: Dict[str, Tuple[float, str]] = {}     # service id -> (time, status)
        self.alive: Dict[str, Optional[bool]] = {}              # rpc key -> answer (None: not asked yet)
        self._sun = (0.0, None)                 # (time, altitude) cache
        self._init_ui()
        QtCore.QTimer.singleShot(0, self.async_init)
        QtCore.QTimer.singleShot(0, self._start_checks)
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._render)
        self._timer.start(2000)

    # ---- UI -----------------------------------------------------------------

    def _init_ui(self) -> None:
        self.setStyleSheet("HealthWidget { background-color: #181818; } QLabel { color: #d8d8d8; }")
        self.f = QtGui.QFont('Arial', 13, QtGui.QFont.Weight.Bold)
        self.f_small = QtGui.QFont('Arial', 9)
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(5)

        # CONNECTIVITY: three big tiles
        self.f_big = QtGui.QFont('Arial', 22, QtGui.QFont.Weight.Bold)
        self.f_state = QtGui.QFont('Arial', 16, QtGui.QFont.Weight.Bold)
        self.f_detail = QtGui.QFont('Arial', 12)
        self.tiles = {}
        for key, ico, title in (('internet', 'icon_globe', 'INTERNET'), ('router', 'icon_router', 'ROUTER'),
                                ('nats', 'icon_network', 'NATS')):
            self.tiles[key] = self._tile(ico, title)
            root.addWidget(self.tiles[key]['box'], 3)

        # information only (no alarm): OVERWATCHES, TIC / PMS
        ow = _Group('OVERWATCHES')
        g = self._grid(ow)
        self.ow_dots = {}
        for c, name in enumerate(OVERWATCHES):
            self.ow_dots[name] = _Dot(self.f, name)
            g.addWidget(self.ow_dots[name], 0, c)
        self.alerts_dot = _Dot(self.f, 'alerts to acknowledge')
        self.alerts_n = self._label('—', right=True)
        g.addWidget(self.alerts_dot, 1, 0, 1, 2)
        g.addWidget(self.alerts_n, 1, 2)
        self._spread(g)
        root.addWidget(ow, 2)

        tp = _Group('TIC / PMS')
        g = self._grid(tp)
        g.addWidget(self._label('TIC'), 0, 0)
        self.tic_dots = {}
        for c, tel in enumerate(TELESCOPES):
            self.tic_dots[tel] = _Dot(self.f, tel)
            g.addWidget(self.tic_dots[tel], 0, c + 1)
        g.addWidget(self._label('pms'), 1, 0)
        self.pms_dots = {}
        for i, (key, name, *_) in enumerate(PMS_UNITS):
            self.pms_dots[key] = _Dot(self.f, name)
            g.addWidget(self.pms_dots[key], 1 + i // 2, 1 + (i % 2) * 2, 1, 2 if i % 2 == 0 else 1)
        g.setColumnStretch(0, 1)
        for c in range(1, 4):
            g.setColumnStretch(c, 2)
        self._spread(g)
        root.addWidget(tp, 3)

        self.detail_boxes = []
        self._init_details(root)
        for box in self.detail_boxes:
            box.setVisible(self.details)
        if not self.details:
            root.addStretch(2)

        self.updated_l = QLabel('')
        self.updated_l.setFont(self.f_small)
        self.updated_l.setStyleSheet(f"color: {DIM};")
        self.updated_l.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        root.addWidget(self.updated_l)

    def _tile(self, ico: str, title: str) -> dict:
        """[icon] TITLE   state / small detail line"""
        box = _Group('')
        row = QHBoxLayout()
        row.setSpacing(14)
        pic = QLabel()
        pic.setFixedSize(64, 64)
        row.addWidget(pic, 0, QtCore.Qt.AlignmentFlag.AlignVCenter)
        col = QVBoxLayout()
        col.setSpacing(2)
        head = QHBoxLayout()
        t = QLabel(title)
        t.setFont(self.f_big)
        head.addWidget(t)
        head.addStretch(1)
        state = QLabel('—')
        state.setFont(self.f_state)
        state.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
        head.addWidget(state)
        col.addStretch(1)
        col.addLayout(head)
        detail = QLabel('')
        detail.setFont(self.f_detail)
        detail.setTextFormat(QtCore.Qt.TextFormat.RichText)
        detail.setWordWrap(True)
        col.addWidget(detail)
        col.addStretch(1)
        row.addLayout(col, 1)
        box.layout.addLayout(row, 1)
        return {'box': box, 'icon': pic, 'ico': ico, 'title': t, 'state': state, 'detail': detail, 'last': None}

    def _set_tile(self, key: str, state: str, text: str, detail: str) -> None:
        tile = self.tiles[key]
        color = COLORS[state]
        if tile['last'] != state:        # repaint the icon / border only on a change
            tile['last'] = state
            tile['icon'].setPixmap(icon(tile['ico'], color, 64))
            tile['title'].setStyleSheet(f"color: {color if state != NONE else DIM};")
            tile['state'].setStyleSheet(f"color: {color if state != NONE else DIM};")
            tile['box'].setStyleSheet(
                f"QFrame#SiteGroup {{ background-color: #1f1f1f; border: 2px solid "
                f"{color if state in (WARN, BAD) else '#383838'}; border-radius: 8px; }}"
                "QLabel { background-color: transparent; }")
        tile['state'].setText(text)
        tile['detail'].setText(detail)

    def _init_details(self, root: QVBoxLayout) -> None:
        # SITE DATA: label + one dot each
        site = _Group('SITE DATA')
        g = self._grid(site)
        self.site_rows = {}
        for r, (key, name) in enumerate((('davis', 'Weather station (Davis)'), ('allsky', 'Allsky / clouds'),
                                         ('power', 'Power (SMA)'), ('water', 'Water meter'),
                                         ('serverroom', 'Server room'), ('batteryroom', 'Battery room'))):
            dot = _Dot(self.f, name)
            detail = self._label('—', right=True)
            g.addWidget(dot, r, 0)
            g.addWidget(detail, r, 1)
            self.site_rows[key] = (dot, detail)
        self._spread(g)
        root.addWidget(site, 6)
        self.detail_boxes.append(site)

        # SERVICES: name + several dots
        sv = _Group('SERVICES')
        g = self._grid(sv)
        self.svc_dots = {}
        r = 0
        for title, items in SERVICES:
            c0 = 0
            if title:
                g.addWidget(self._label(title), r, 0)
                c0 = 1
            for c, (name, sid) in enumerate(items):
                self.svc_dots[sid] = _Dot(self.f, name)
                g.addWidget(self.svc_dots[sid], r, c0 + c)
            r += 1
        g.addWidget(self._label('guider jk15'), r, 0)
        self.guider_dot = _Dot(self.f, '')
        g.addWidget(self.guider_dot, r, 1, 1, 3)
        self._spread(g)
        root.addWidget(sv, 5)
        self.detail_boxes.append(sv)

        # TELESCOPES: matrix
        tl = _Group('TELESCOPES')
        g = self._grid(tl)
        for c, tel in enumerate(TELESCOPES):
            h = self._label(tel)
            h.setStyleSheet(f"color: {DIM};")
            g.addWidget(h, 0, c + 1)
        self.tel_cells: Dict[str, Dict[str, _Dot]] = {}
        for r, (key, name) in enumerate((('tic', 'TIC telemetry'), ('download', 'downloader'),
                                         ('pipeline', 'OFP pipeline'), ('frame', 'last frame'),
                                         ('ob', 'TOI OB'), ('planner', 'planner error'),
                                         ('ccd', 'CCD temp')), start=1):
            g.addWidget(self._label(name), r, 0)
            self.tel_cells[key] = {}
            for c, tel in enumerate(TELESCOPES):
                d = _Dot(self.f, '')
                self.tel_cells[key][tel] = d
                g.addWidget(d, r, c + 1)
        g.setColumnStretch(0, 3)
        for c in range(1, 4):
            g.setColumnStretch(c, 2)
        self._spread(g)
        root.addWidget(tl, 8)
        self.detail_boxes.append(tl)

    def _grid(self, group: _Group) -> QGridLayout:
        g = QGridLayout()
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(2)
        group.layout.addLayout(g, 1)        # rows spread over the box (row stretch set in _spread)
        return g

    @staticmethod
    def _spread(g: QGridLayout) -> None:
        for r in range(g.rowCount()):
            g.setRowStretch(r, 1)

    def _label(self, text: str, right: bool = False) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(self.f)
        lbl.setTextFormat(QtCore.Qt.TextFormat.RichText)
        if right:
            lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
        return lbl

    # ---- NATS ---------------------------------------------------------------

    @asyncSlot()
    async def async_init(self):
        readers: List[Tuple[str, str, Callable]] = [
            ('telemetry.weather.davis', 'last', self._seen_clb('davis')),
            ('data.overwatch.oca.allsky.clouds', 'last', self._seen_clb('allsky')),
            ('telemetry.power.data-manager', 'last', self._seen_clb('power')),
            ('telemetry.water.level', 'last', self._seen_clb('water')),
            ('telemetry.conditions.serverroom-htsensor', 'last', self._seen_clb('serverroom', keep=True)),
            ('telemetry.conditions.batteryroom-tsensor', 'last', self._seen_clb('batteryroom', keep=True)),
            ('status.overwatch.oca.self.alerts', 'last', self._seen_clb('alerts', keep=True)),
            ('svc.heartbeat.>', 'last_per_subject', self._heartbeat_clb),
            (f'svc.status.{GUIDER_ID}', 'last', self._seen_clb('guider', keep=True)),
            (self.net_subject, 'last', self._uplink_clb),
        ]
        readers += [(subj, 'last_per_subject', self._seen_clb(key, latest=True))
                    for key, _, subj, *_ in PMS_UNITS if subj]
        for tel in TELESCOPES:
            readers += [
                (f'tic.telemetry.{tel}.>', 'last_per_subject', self._telemetry_clb(tel)),
                (f'tic.status.{tel}.download', 'last', self._seen_clb(f'frame.{tel}')),
                (f'status.toi.{tel}.self.ob', 'last', self._seen_clb(f'ob.{tel}', keep=True)),
                (f'tic.planner.{tel}.status.error', 'last', self._seen_clb(f'planner_error.{tel}', keep=True)),
                (f'tic.planner.{tel}.data.static', 'last', self._seen_clb(f'plan_loaded.{tel}')),
            ]
        for subject, policy, clb in readers:
            try:
                await self.main_window.run_reader(clb=clb, subject=subject, deliver_policy=policy)
            except Exception as e:
                logger.warning(f"health reader {subject} failed: {e!r}")
        await create_task(self._rpc_loop(), 'health_rpc_loop')

    @asyncSlot()
    async def _start_checks(self):
        await self.conn.start_checks(self.main_window)

    def _got_msg(self, meta) -> None:
        self.conn.got_msg(meta)

    async def _uplink_clb(self, data, meta) -> bool:
        self._got_msg(meta)
        try:
            self.conn.uplink = str(data['measurements']['route'])
        except (KeyError, TypeError):
            pass
        return True
    def _seen_clb(self, key: str, keep: bool = False, latest: bool = False):
        """latest: several subjects under one key (last_per_subject replays them in any order) - keep the newest"""
        async def clb(data, meta) -> bool:
            try:
                self._got_msg(meta)
                t = _nats_time(meta)
                self.seen[key] = max(t, self.seen.get(key, 0.0)) if latest else t
                if keep:
                    self.values[key] = data
            except Exception as e:
                logger.warning(f"health {key}: message skipped: {e!r}")
            return True
        return clb

    async def _heartbeat_clb(self, data, meta) -> bool:
        try:
            self._got_msg(meta)
            sid = data.get('service_id') or meta['nats']['subject'].removeprefix('svc.heartbeat.')
            self.heartbeats[sid] = (_nats_time(meta), str(data.get('status', 'ok')))
        except Exception as e:
            logger.warning(f"health heartbeat: message skipped: {e!r}")
        return True

    def _telemetry_clb(self, tel: str):
        async def clb(data, meta) -> bool:
            try:
                self._got_msg(meta)
                t = _nats_time(meta)
                self.seen[f'tic.{tel}'] = max(t, self.seen.get(f'tic.{tel}', 0.0))
                for k, v in (data.get('measurements') or {}).items():
                    if k.endswith('.camera.ccdtemperature'):
                        self.values[f'ccd.{tel}'] = (t, float(v))
                    elif k.endswith('.camera.setccdtemperature'):
                        self.values[f'ccdset.{tel}'] = float(v)
            except Exception as e:
                logger.warning(f"health telemetry {tel}: message skipped: {e!r}")
            return True
        return clb

    async def _rpc_loop(self):
        subjects = {f'ow.{n}': f'rpc.overwatch.oca.{n}_overwatch.alive' for n in OVERWATCHES}
        for tel in TELESCOPES:
            subjects[f'download.{tel}'] = f'tic.rpc.{tel}.download.alive'
            subjects[f'pipeline.{tel}'] = f'tic.rpc.{tel}.pipeline.alive'

        async def ask(subject):
            try:
                data, meta = await request(subject, timeout=3)
                return data.get('status') == 'ok'
            except Exception:       # no responders, timeout
                return False

        while True:
            try:
                keys = list(subjects)
                answers = await asyncio.gather(*(ask(subjects[k]) for k in keys))
                self.alive.update(zip(keys, answers))
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"health rpc loop: {e!r}")
            await asyncio.sleep(RPC_PERIOD)

    # ---- judging / drawing (plain Qt slot - must not raise) -----------------

    def _age(self, key: str) -> Optional[float]:
        t = self.seen.get(key)
        return None if t is None else time.time() - t

    def _sun_alt(self) -> Optional[float]:
        now = time.time()
        if now - self._sun[0] > 60:
            try:
                self._sun = (now, sun_alt_deg())
            except Exception as e:
                logger.warning(f"health sun altitude: {e!r}")
                self._sun = (now, None)
        return self._sun[1]

    def _render(self) -> None:
        try:
            self._render_connectivity()
            self._render_overwatches()
            self._render_tic_pms()
            if self.details:
                self._render_site()
                self._render_services()
                self._render_telescopes()
            self.updated_l.setText(f"updated {datetime.datetime.now(datetime.timezone.utc):%H:%M:%S} UT")
        except Exception as e:
            logger.warning(f"health render: {e!r}")

    def _render_connectivity(self) -> None:
        def dim(t: str) -> str:
            return f'<span style="color:{DIM}">{t}</span>' if t else ''

        checks = self.conn.all()
        # INTERNET: every host with its time, two per line, the uplink above
        c = checks['INTERNET']
        parts = [f'<span style="color:{COLORS[OK if ms is not None else BAD]}">●</span> '
                 f'{h if is_ip(h) else h.split(".")[0]} {dim(f"{ms:.0f} ms" if ms is not None else "—")}'
                 for h, ms in c.values.items()]
        detail = '<br>'.join(' &nbsp;&nbsp; '.join(parts[i:i + 2]) for i in range(0, len(parts), 2))
        if self.conn.uplink:
            uc = UPLINK_COLORS.get(self.conn.uplink.lower(), TEXT)
            detail = f'via <b style="color:{uc}">{self.conn.uplink}</b>' + (f'<br>{detail}' if detail else '')
        self._set_tile('internet', c.state, c.text, detail)
        c = checks['ROUTER']
        host, _, rest = c.detail.partition(' ')
        self._set_tile('router', c.state, c.text, f'{host} &nbsp; {dim(rest)}')
        c = checks['NATS']
        self._set_tile('nats', c.state, c.text, f'{settings.nats_host}:{settings.nats_port} &nbsp; {dim(c.detail)}')

    def _waiting(self) -> bool:
        return time.time() - self.start < HEARTBEAT_STALE

    def _render_site(self) -> None:
        limits = {'davis': (120, 300), 'allsky': (360, 900), 'power': (60, 300), 'water': (3600, 3 * 3600)}
        for key, (ok_s, warn_s) in limits.items():
            dot, detail = self.site_rows[key]
            age = self._age(key)
            state = _fresh(age, ok_s, warn_s)
            if key == 'allsky' and state != OK:
                alt = self._sun_alt()
                if alt is not None and alt > -5:     # allsky does not work by day
                    state = NONE
            if age is None and self._waiting():
                state = NONE
            dot.set(state, self._name(dot))
            detail.setText(_age(age) if age is not None else 'no data')
        for key in ('serverroom', 'batteryroom'):
            dot, detail = self.site_rows[key]
            age = self._age(key)
            msm = (self.values.get(key) or {}).get('measurements') or {}
            temp = msm.get('temperature')
            if temp is None or age is None or age > 1800:
                dot.set(NONE if age is None and self._waiting() else WARN, self._name(dot))
                detail.setText('no data' if age is None else f'— ({_age(age)})')
                continue
            temp = float(temp)
            state = OK if temp < ROOM_WARN_C else WARN if temp < ROOM_BAD_C else BAD
            dot.set(state, self._name(dot))
            hum = msm.get('humidity')
            detail.setText(f"{temp:.1f} °C" + (f"  {float(hum):.0f} %" if hum is not None else ''))

    @staticmethod
    def _name(dot: _Dot) -> str:
        return dot.property('name') or ''

    def _render_overwatches(self) -> None:
        for name, dot in self.ow_dots.items():
            a = self.alive.get(f'ow.{name}')
            dot.set(NONE if a is None else OK if a else BAD, name)
        alerts = (self.values.get('alerts') or {}).get('alerts')
        if alerts is None:
            self.alerts_dot.set(NONE, 'alerts to acknowledge')
            self.alerts_n.setText('—')
            return
        problems = [a for a in alerts if a.get('kind') != 'event']
        state = BAD if problems else WARN if alerts else OK
        self.alerts_dot.set(state, 'alerts to acknowledge')
        self.alerts_n.setText(str(len(alerts)))

    def _fresh_state(self, age: Optional[float], ok_s: float, warn_s: float) -> str:
        if age is None:
            return NONE if self._waiting() else BAD
        return _fresh(age, ok_s, warn_s)

    def _render_tic_pms(self) -> None:
        ages = [self._age(f'tic.{tel}') for tel in TELESCOPES]
        for tel, age in zip(TELESCOPES, ages):
            self.tic_dots[tel].set(self._fresh_state(age, TIC_OK, TIC_WARN),
                                   tel + (f' <span style="color:{DIM}">{_age(age)}</span>' if age and age >= 60 else ''))
        known = [a for a in ages if a is not None]
        for key, name, subj, ok_s, warn_s in PMS_UNITS:
            age = (min(known) if known else None) if key == 'pms.tic' else self._age(key)
            self.pms_dots[key].set(self._fresh_state(age, ok_s, warn_s), name)

    def _hb_state(self, sid: str) -> str:
        hb = self.heartbeats.get(sid)
        if hb is None:
            return NONE if self._waiting() else BAD
        t, status = hb
        if time.time() - t > HEARTBEAT_STALE:
            return BAD
        status = status.lower()
        return OK if status in HB_OK else BAD if status in HB_BAD else WARN

    def _render_services(self) -> None:
        for title, items in SERVICES:
            for name, sid in items:
                self.svc_dots[sid].set(self._hb_state(sid), name)
        state = self._hb_state(GUIDER_ID)
        st = self.values.get('guider') or {}
        text = str(st.get('status') or '') if state != BAD else 'no heartbeat'
        self.guider_dot.set(state, text or '—')

    def _render_telescopes(self) -> None:
        cells = self.tel_cells
        for tel in TELESCOPES:
            # TIC telemetry: pms publishes on change only - quiet is orange, never red
            age = self._age(f'tic.{tel}')
            cells['tic'][tel].set(NONE if age is None else OK if age < 900 else WARN, _short_age(age))
            for key in ('download', 'pipeline'):
                a = self.alive.get(f'{key}.{tel}')
                cells[key][tel].set(NONE if a is None else OK if a else BAD, '' if a is None else 'ok' if a else 'down')
            age = self._age(f'frame.{tel}')
            cells['frame'][tel].set(NONE, _short_age(age))
            ob = self.values.get(f'ob.{tel}') or {}
            if ob.get('error'):
                cells['ob'][tel].set(BAD, 'error')
            elif ob.get('ob_started') and not ob.get('ob_done'):
                cells['ob'][tel].set(OK, str(ob.get('status') or 'running')[:10])
            else:
                cells['ob'][tel].set(NONE, 'idle')
            age = self._age(f'planner_error.{tel}')
            if age is not None and age < PLANNER_ERROR_HOURS * 3600:
                t_err = self.seen[f'planner_error.{tel}']
                loaded = self.seen.get(f'plan_loaded.{tel}', 0.0)
                hhmm = datetime.datetime.fromtimestamp(t_err, datetime.timezone.utc).strftime('%H:%M')
                cells['planner'][tel].set(BAD if loaded < t_err else WARN, hhmm)
            else:
                cells['planner'][tel].set(OK, '—')
            ccd, sp = self.values.get(f'ccd.{tel}'), self.values.get(f'ccdset.{tel}')
            if ccd is None:
                cells['ccd'][tel].set(NONE, '—')
            else:
                t, temp = ccd
                if sp is None:
                    state = NONE
                else:
                    d = abs(temp - sp)
                    state = OK if d <= CCD_WARN else WARN if d <= CCD_BAD else BAD
                cells['ccd'][tel].set(state, f'{temp:.0f}°')


widget_class = HealthWidget
