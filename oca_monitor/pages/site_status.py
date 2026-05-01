"""Unified site/observation status panel.

Replaces the legacy Ephemeris + Conditions tabs in the bottom strip of
the controlroom layout. Single panel with three themed groups:

* **NEXT EVENTS** — countdown to the two upcoming sun-altitude events
  (configurable list of altitudes for evening / morning). Big Monaco
  countdown for the imminent one, smaller line for the one after.
* **TIME** — UT / LT / CET-CEST (Warsaw) / SIDT clocks at OCM longitude.
* **SUN / MOON / WATER** — next sun rise-or-set, moon altitude + phase
  emoji + next moon event, plus the OCM water-tank level.

Async path is only the water-level NATS subscription; everything else
ticks once per second from a ``QTimer``.
"""
from __future__ import annotations

import datetime
import logging
from typing import List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from PyQt6 import QtCore, QtGui
from PyQt6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget
)
from qasync import asyncSlot

from oca_monitor.utils.ephem_ocm import (
    moon_state, next_moon_event, next_sun_alt_event, sidereal_time_str,
)

logger = logging.getLogger(__name__.rsplit('.')[-1])


_WARSAW = ZoneInfo('Europe/Warsaw')


def _format_countdown(delta: datetime.timedelta) -> str:
    s = max(0, int(delta.total_seconds()))
    if s < 60:
        return f"{s}\""
    if s < 3600:
        return f"{s // 60}'{s % 60:02d}\""
    if s < 86400:
        h = s // 3600
        m = (s % 3600) // 60
        return f"{h}h{m:02d}'"
    d = s // 86400
    h = (s % 86400) // 3600
    return f"{d}d{h:02d}h"


def _moon_emoji(phase_pct: float, waxing: bool) -> str:
    p = max(0.0, min(100.0, phase_pct))
    if p < 3:
        return '🌑'
    if p > 97:
        return '🌕'
    if waxing:
        return '🌒' if p < 25 else '🌓' if p < 45 else '🌔' if p < 75 else '🌕'
    return '🌘' if p < 25 else '🌗' if p < 45 else '🌖' if p < 75 else '🌕'


class _Group(QFrame):
    """Mini-frame that hosts a label cluster with a subtle border + caption."""

    def __init__(self, caption: str = ''):
        super().__init__()
        self.setObjectName('SiteGroup')
        self.setStyleSheet(
            "QFrame#SiteGroup { background-color: #1f1f1f; "
            "  border: 1px solid #383838; border-radius: 6px; }"
            "QLabel { background-color: transparent; }"
        )
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(10, 4, 10, 6)
        self.layout.setSpacing(2)
        if caption:
            t = QLabel(caption)
            t.setStyleSheet(
                "color: #6e6e6e; letter-spacing: 1px;")
            t.setFont(QtGui.QFont('Arial', 8, QtGui.QFont.Weight.Bold))
            self.layout.addWidget(t)


class SiteStatusWidget(QWidget):
    """Unified site/observation status panel — see module docstring."""

    DEFAULT_EVENING_EVENTS: Tuple[float, ...] = (5, -1, -16, -18)
    DEFAULT_MORNING_EVENTS: Tuple[float, ...] = (-18, -10, 0)

    def __init__(self, main_window,
                 evening_events: Optional[Sequence[float]] = None,
                 morning_events: Optional[Sequence[float]] = None,
                 water_subject: str = 'telemetry.water.level',
                 water_capacity_m3: float = 15.0,
                 water_warn_pct: float = 20.0,
                 water_danger_pct: float = 10.0,
                 **kwargs) -> None:
        super().__init__()
        self.main_window = main_window
        self.evening_events = list(evening_events or self.DEFAULT_EVENING_EVENTS)
        self.morning_events = list(morning_events or self.DEFAULT_MORNING_EVENTS)
        self.water_subject = water_subject
        self.water_capacity_m3 = float(water_capacity_m3)
        self.water_warn_pct = float(water_warn_pct)
        self.water_danger_pct = float(water_danger_pct)
        self.water_level_m3: Optional[float] = None
        self._init_ui()
        QtCore.QTimer.singleShot(0, self.async_init)
        self._tick_timer = QtCore.QTimer(self)
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start(1000)
        self._tick()
        logger.info("SiteStatusWidget init done")

    # ---- UI -----------------------------------------------------------------

    def _init_ui(self) -> None:
        self.setStyleSheet(
            "SiteStatusWidget { background-color: #181818; }"
            "QLabel { color: #e0e0e0; }"
        )
        root = QHBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # ---- Group A: NEXT EVENTS (the focus) -----------------------------
        self.box_events = _Group('NEXT EVENTS')
        self.lbl_event_now_label = QLabel("—")
        self.lbl_event_now_label.setStyleSheet("color: #5cc4ff;")
        self.lbl_event_now_label.setFont(
            QtGui.QFont('Arial', 14, QtGui.QFont.Weight.Bold))
        self.lbl_event_now_timer = QLabel("—")
        self.lbl_event_now_timer.setStyleSheet("color: #ffffff;")
        self.lbl_event_now_timer.setFont(
            QtGui.QFont('Monaco', 30, QtGui.QFont.Weight.Bold))
        self.lbl_event_now_when = QLabel("")
        self.lbl_event_now_when.setStyleSheet("color: #888888;")
        self.lbl_event_now_when.setFont(QtGui.QFont('Arial', 9))
        self.lbl_event_next = QLabel("")
        self.lbl_event_next.setStyleSheet("color: #c0c0c0;")
        self.lbl_event_next.setFont(QtGui.QFont('Arial', 15, QtGui.QFont.Weight.Bold))
        self.box_events.layout.addWidget(self.lbl_event_now_label)
        self.box_events.layout.addWidget(self.lbl_event_now_timer)
        self.box_events.layout.addWidget(self.lbl_event_now_when)
        self.box_events.layout.addStretch(1)
        self.box_events.layout.addWidget(self.lbl_event_next)
        root.addWidget(self.box_events, 5)

        # ---- Group B: TIME ------------------------------------------------
        self.box_clocks = _Group('TIME')
        clocks_grid = QGridLayout()
        clocks_grid.setContentsMargins(0, 0, 0, 0)
        clocks_grid.setHorizontalSpacing(8); clocks_grid.setVerticalSpacing(0)
        self.lbl_ut = QLabel("--:--:--")
        self.lbl_lt = QLabel("--:--:--")
        self.lbl_cet = QLabel("--:--:--")
        self.lbl_sidt = QLabel("--:--:--")
        clock_font = QtGui.QFont('Monaco', 17, QtGui.QFont.Weight.Bold)
        tag_font = QtGui.QFont('Arial', 11, QtGui.QFont.Weight.Bold)
        for lbl in (self.lbl_ut, self.lbl_lt, self.lbl_cet, self.lbl_sidt):
            lbl.setFont(clock_font)
        for r, (k, v, color) in enumerate([
            ('UT',   self.lbl_ut,   '#e0e0e0'),
            ('LT',   self.lbl_lt,   '#a8e0ff'),
            ('WAW',  self.lbl_cet,  '#7eea90'),
            ('SIDT', self.lbl_sidt, '#fcb841'),
        ]):
            tag = QLabel(k)
            tag.setStyleSheet("color: #6e6e6e;")
            tag.setFont(tag_font)
            v.setStyleSheet(f"color: {color};")
            clocks_grid.addWidget(tag, r, 0)
            clocks_grid.addWidget(v, r, 1)
        clocks_wrap = QWidget()
        clocks_wrap.setLayout(clocks_grid)
        self.box_clocks.layout.addWidget(clocks_wrap)
        self.box_clocks.layout.addStretch(1)
        root.addWidget(self.box_clocks, 4)

        # ---- Group C: SUN / MOON / WATER ----------------------------------
        self.box_astro = _Group('SUN · MOON · WATER')
        self.lbl_sun_next = QLabel("☀ —")
        self.lbl_sun_next.setFont(QtGui.QFont('Arial', 12))
        self.lbl_moon_state = QLabel("☽ —")
        self.lbl_moon_state.setFont(QtGui.QFont('Arial', 13, QtGui.QFont.Weight.Bold))
        self.lbl_moon_next = QLabel("")
        self.lbl_moon_next.setStyleSheet("color: #888888;")
        self.lbl_moon_next.setFont(QtGui.QFont('Arial', 10))
        self.lbl_water = QLabel("💧 —")
        self.lbl_water.setStyleSheet("color: #6ed0a8;")
        self.lbl_water.setFont(QtGui.QFont('Arial', 12, QtGui.QFont.Weight.Bold))
        self.box_astro.layout.addWidget(self.lbl_sun_next)
        self.box_astro.layout.addWidget(self.lbl_moon_state)
        self.box_astro.layout.addWidget(self.lbl_moon_next)
        self.box_astro.layout.addStretch(1)
        self.box_astro.layout.addWidget(self.lbl_water)
        root.addWidget(self.box_astro, 4)

    # ---- async (water only) -------------------------------------------------

    @asyncSlot()
    async def async_init(self):
        try:
            await self.main_window.run_reader(
                clb=self._water_callback,
                subject=self.water_subject, deliver_policy='last',
            )
        except Exception as e:
            logger.warning(f"water reader subscription failed: {e}")

    async def _water_callback(self, data, meta) -> bool:
        try:
            self.water_level_m3 = float(data['measurements']['m3'])
        except (KeyError, TypeError, ValueError):
            return True
        self._update_water_label()
        return True

    def _update_water_label(self) -> None:
        if self.water_level_m3 is None:
            self.lbl_water.setText("💧 —")
            return
        if self.water_capacity_m3 > 0:
            pct = 100.0 * self.water_level_m3 / self.water_capacity_m3
            if pct <= self.water_danger_pct:
                pct_color = '#ff4d4d'  # red
            elif pct <= self.water_warn_pct:
                pct_color = '#ffaa33'  # orange
            else:
                pct_color = '#808080'  # gray (normal)
            self.lbl_water.setText(
                f'💧 {self.water_level_m3:.1f} m³  '
                f'<span style="color:{pct_color}">{pct:.0f}%</span>')
        else:
            self.lbl_water.setText(f"💧 {self.water_level_m3:.1f} m³")

    # ---- 1 Hz tick ----------------------------------------------------------

    def _tick(self) -> None:
        now = datetime.datetime.now(datetime.timezone.utc)
        now_local = datetime.datetime.now()
        now_warsaw = datetime.datetime.now(_WARSAW)

        # Clocks
        self.lbl_ut.setText(now.strftime('%H:%M:%S'))
        self.lbl_lt.setText(now_local.strftime('%H:%M:%S'))
        self.lbl_cet.setText(now_warsaw.strftime('%H:%M:%S'))
        try:
            self.lbl_sidt.setText(sidereal_time_str(now))
        except Exception as e:
            logger.debug(f"sidereal_time failed: {e}")

        # Sun: next sunrise OR sunset (whichever is sooner)
        t_set = next_sun_alt_event(now, 0.0, 'setting')
        t_rise = next_sun_alt_event(now, 0.0, 'rising')
        if t_set is not None and (t_rise is None or t_set < t_rise):
            self.lbl_sun_next.setText(
                f"☀ ↓ {t_set.strftime('%H:%M')} UT  ({_format_countdown(t_set - now)})")
        elif t_rise is not None:
            self.lbl_sun_next.setText(
                f"☀ ↑ {t_rise.strftime('%H:%M')} UT  ({_format_countdown(t_rise - now)})")
        else:
            self.lbl_sun_next.setText("☀ —")

        # Moon: alt, phase, next event
        try:
            ms = moon_state(now)
            moon_alt_deg = ms['alt_deg']
            moon_phase_pct = ms['phase'] * 100.0
            emoji = _moon_emoji(moon_phase_pct, ms['waxing'])
            self.lbl_moon_state.setText(
                f"☽ {moon_alt_deg:+.0f}°   {emoji}  {moon_phase_pct:.0f}%")
            kind = 'setting' if moon_alt_deg > 0 else 'rising'
            t = next_moon_event(now, kind)
            if t is not None:
                label = 'moonset' if kind == 'setting' else 'moonrise'
                self.lbl_moon_next.setText(f"   {label} {t.strftime('%H:%M')} UT")
            else:
                self.lbl_moon_next.setText("")
        except Exception as e:
            logger.debug(f"moon update failed: {e}")
            self.lbl_moon_next.setText("")

        # Water level (text refresh — value comes from NATS callback)
        self._update_water_label()

        # Event timers
        self._update_event_timers(now)

    def _update_event_timers(self, now: datetime.datetime) -> None:
        events: List[Tuple[float, str, datetime.datetime]] = []
        for alt in self.evening_events:
            t = next_sun_alt_event(now, alt, 'setting')
            if t is not None:
                events.append((alt, 'setting', t))
        for alt in self.morning_events:
            t = next_sun_alt_event(now, alt, 'rising')
            if t is not None:
                events.append((alt, 'rising', t))
        events.sort(key=lambda e: e[2])
        if not events:
            self.lbl_event_now_label.setText("—")
            self.lbl_event_now_timer.setText("—")
            self.lbl_event_now_when.setText("")
            self.lbl_event_next.setText("")
            return
        ev_now = events[0]
        cd = ev_now[2] - now
        arrow = '↓' if ev_now[1] == 'setting' else '↑'
        # Visual flash when the imminent event has just fired (timer = 0)
        if cd.total_seconds() <= 0:
            self.lbl_event_now_timer.setStyleSheet("color: #ffd166;")
        else:
            self.lbl_event_now_timer.setStyleSheet("color: #ffffff;")
        self.lbl_event_now_label.setText(f"Sun  {arrow}  {ev_now[0]:+.0f}°")
        self.lbl_event_now_timer.setText(_format_countdown(cd))
        self.lbl_event_now_when.setText(f"at {ev_now[2].strftime('%H:%M:%S')} UT")
        if len(events) > 1:
            ev2 = events[1]
            arrow2 = '↓' if ev2[1] == 'setting' else '↑'
            self.lbl_event_next.setText(
                f"next: Sun {arrow2} {ev2[0]:+.0f}°   in {_format_countdown(ev2[2] - now)}")
        else:
            self.lbl_event_next.setText("")


widget_class = SiteStatusWidget
