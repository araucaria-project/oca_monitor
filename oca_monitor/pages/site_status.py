"""Unified site/observation status panel.

Replaces the legacy Ephemeris + Conditions tabs in the bottom strip of
the controlroom layout. Single panel with three themed groups:

* **NEXT EVENTS** — countdown to the two upcoming sun-altitude events
  (configurable list of altitudes for evening / morning). Big Monaco
  countdown for the imminent one, smaller line for the one after.
* **TIME** — UT / LT / CET-CEST (Warsaw) / SIDT clocks at OCM longitude.
* **SUN / MOON / WATER** — next sunset and sunrise (closer one bright,
  the other dimmed), moon altitude + phase emoji, next moonset and
  moonrise in the same paired format, plus the OCM water-tank level.

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


_BRIGHT_COLOR = '#e8e8e8'   # imminent event
_DIM_COLOR = '#7a7a7a'      # the one after
_LABEL_COLOR = '#7a7a7a'    # gray "alt" / "phase" tags before bright values


def _decide_bright(t_set: Optional[datetime.datetime],
                   t_rise: Optional[datetime.datetime]) -> str:
    """Return ``'set'`` or ``'rise'`` — whichever event is sooner.

    With one of them ``None`` the other wins by default. With both
    ``None`` we still return ``'set'`` (the renderer handles that
    side specifically; the value is harmless).
    """
    if t_set is None and t_rise is None:
        return 'set'
    if t_set is not None and (t_rise is None or t_set <= t_rise):
        return 'set'
    return 'rise'


def _event_line(arrow: str, t: Optional[datetime.datetime],
                is_bright: bool) -> str:
    """Single-line HTML for one rise-or-set event. ``↓ HH:MM UT`` only —
    the parenthetical countdown is gone (the prominent NEXT EVENTS
    panel already provides that signal)."""
    color = _BRIGHT_COLOR if is_bright else _DIM_COLOR
    if t is None:
        return f'<span style="color:{color}">{arrow} —</span>'
    return (
        f'<span style="color:{color}">'
        f'{arrow} {t.strftime("%H:%M")} UT'
        f'</span>'
    )


def _format_utc_offset(td: Optional[datetime.timedelta]) -> str:
    """``timedelta`` → compact ``±Nh`` (or ``±NhMM`` if not whole-hour)
    suitable for the TIME panel's offset column."""
    if td is None:
        return ''
    secs = int(td.total_seconds())
    if secs == 0:
        return '+0h'
    sign = '+' if secs > 0 else '-'
    secs = abs(secs)
    h, m = divmod(secs // 60, 60)
    return f'{sign}{h}h' if m == 0 else f'{sign}{h}h{m:02d}'


def _moon_alt_phase(alt_deg: float, phase_pct: float) -> str:
    """``alt`` + ``phase`` line: gray tags, bright values, no emoji."""
    return (
        f'<span style="color:{_LABEL_COLOR}">alt</span> '
        f'<span style="color:{_BRIGHT_COLOR}">{alt_deg:+.0f}°</span>'
        f'&nbsp;&nbsp;&nbsp;'
        f'<span style="color:{_LABEL_COLOR}">phase</span> '
        f'<span style="color:{_BRIGHT_COLOR}">{phase_pct:.0f}%</span>'
    )


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
        # Second event mirrors the main event's label/timer/when triple
        # but at smaller size and uniformly dimmed grey, so it reads as
        # a subordinate "after this one" footer at the bottom of the
        # column instead of a wide single line stretching the panel.
        self.lbl_event_next_label = QLabel("")
        self.lbl_event_next_label.setStyleSheet("color: #7a7a7a;")
        self.lbl_event_next_label.setFont(
            QtGui.QFont('Arial', 10, QtGui.QFont.Weight.Bold))
        self.lbl_event_next_timer = QLabel("")
        self.lbl_event_next_timer.setStyleSheet("color: #888888;")
        self.lbl_event_next_timer.setFont(
            QtGui.QFont('Monaco', 18, QtGui.QFont.Weight.Bold))
        self.lbl_event_next_when = QLabel("")
        self.lbl_event_next_when.setStyleSheet("color: #6e6e6e;")
        self.lbl_event_next_when.setFont(QtGui.QFont('Arial', 8))
        self.box_events.layout.addWidget(self.lbl_event_now_label)
        self.box_events.layout.addWidget(self.lbl_event_now_timer)
        self.box_events.layout.addWidget(self.lbl_event_now_when)
        self.box_events.layout.addStretch(1)
        self.box_events.layout.addWidget(self.lbl_event_next_label)
        self.box_events.layout.addWidget(self.lbl_event_next_timer)
        self.box_events.layout.addWidget(self.lbl_event_next_when)
        root.addWidget(self.box_events, 1)

        # ---- Group B: TIME ------------------------------------------------
        self.box_clocks = _Group('TIME')
        clocks_grid = QGridLayout()
        clocks_grid.setContentsMargins(0, 0, 0, 0)
        clocks_grid.setHorizontalSpacing(8); clocks_grid.setVerticalSpacing(0)
        self.lbl_ut = QLabel("--:--:--")
        self.lbl_lt = QLabel("--:--:--")
        self.lbl_cet = QLabel("--:--:--")
        self.lbl_sidt = QLabel("--:--:--")
        # UTC-offset suffixes for LT and WAW (e.g. "-4h", "+2h"). Same
        # colour as the time itself, tag-sized font — a quick visual
        # for "how far is this clock from UT". Updated each tick so
        # DST transitions reflect automatically.
        self.lbl_lt_off = QLabel("")
        self.lbl_cet_off = QLabel("")
        clock_font = QtGui.QFont('Monaco', 17, QtGui.QFont.Weight.Bold)
        tag_font = QtGui.QFont('Arial', 11, QtGui.QFont.Weight.Bold)
        off_font = QtGui.QFont('Arial', 11, QtGui.QFont.Weight.Bold)
        for lbl in (self.lbl_ut, self.lbl_lt, self.lbl_cet, self.lbl_sidt):
            lbl.setFont(clock_font)
        rows = [
            ('UT',   self.lbl_ut,   '#e0e0e0', None),
            ('LT',   self.lbl_lt,   '#a8e0ff', self.lbl_lt_off),
            ('WAW',  self.lbl_cet,  '#7eea90', self.lbl_cet_off),
            ('SIDT', self.lbl_sidt, '#fcb841', None),
        ]
        for r, (k, v, color, off) in enumerate(rows):
            tag = QLabel(k)
            tag.setStyleSheet("color: #6e6e6e;")
            tag.setFont(tag_font)
            v.setStyleSheet(f"color: {color};")
            clocks_grid.addWidget(tag, r, 0)
            clocks_grid.addWidget(v, r, 1)
            if off is not None:
                off.setStyleSheet(f"color: {color};")
                off.setFont(off_font)
                clocks_grid.addWidget(off, r, 2)
        clocks_wrap = QWidget()
        clocks_wrap.setLayout(clocks_grid)
        self.box_clocks.layout.addWidget(clocks_wrap)
        self.box_clocks.layout.addStretch(1)

        # WATER — lives at the bottom of column 2 (under TIME). Kept
        # at its natural compact size; the clocks above absorb any
        # spare vertical space.
        self.box_water = _Group('WATER')
        self.lbl_water = QLabel("—")
        self.lbl_water.setStyleSheet("color: #6ed0a8;")
        self.lbl_water.setFont(QtGui.QFont('Arial', 14, QtGui.QFont.Weight.Bold))
        self.lbl_water.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.box_water.layout.addWidget(self.lbl_water)

        clocks_col = QWidget()
        clocks_col_layout = QVBoxLayout(clocks_col)
        clocks_col_layout.setContentsMargins(0, 0, 0, 0)
        clocks_col_layout.setSpacing(4)
        clocks_col_layout.addWidget(self.box_clocks, 1)  # eats spare height
        clocks_col_layout.addWidget(self.box_water, 0)   # natural size
        root.addWidget(clocks_col, 1)

        # ---- Column 3: SUN + MOON --------------------------------------
        # Two boxed sub-panels filling the full column height. Stretch
        # factors mirror the content row counts (sun=2 rows, moon=3
        # rows, ignoring captions) so each box's pixels-per-row stays
        # roughly equal. Inside each box, content rows are padded with
        # stretches so they distribute evenly down the available space
        # instead of clumping under the caption.
        astro_col = QWidget()
        astro_layout = QVBoxLayout(astro_col)
        astro_layout.setContentsMargins(0, 0, 0, 0)
        astro_layout.setSpacing(4)
        astro_event_font = QtGui.QFont('Arial', 14, QtGui.QFont.Weight.Bold)
        # SUN — title + ↓ set + ↑ rise.
        self.box_sun = _Group('SUN')
        self.lbl_sun_set = QLabel("↓ —")
        self.lbl_sun_set.setFont(astro_event_font)
        self.lbl_sun_set.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.lbl_sun_rise = QLabel("↑ —")
        self.lbl_sun_rise.setFont(astro_event_font)
        self.lbl_sun_rise.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.box_sun.layout.addStretch(1)
        self.box_sun.layout.addWidget(self.lbl_sun_set)
        self.box_sun.layout.addStretch(1)
        self.box_sun.layout.addWidget(self.lbl_sun_rise)
        self.box_sun.layout.addStretch(1)
        astro_layout.addWidget(self.box_sun, 2)
        # MOON — title + alt/phase + ↓ set + ↑ rise.
        self.box_moon = _Group('MOON')
        self.lbl_moon_state = QLabel("alt —  phase —")
        self.lbl_moon_state.setFont(astro_event_font)
        self.lbl_moon_state.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.lbl_moon_set = QLabel("↓ —")
        self.lbl_moon_set.setFont(astro_event_font)
        self.lbl_moon_set.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.lbl_moon_rise = QLabel("↑ —")
        self.lbl_moon_rise.setFont(astro_event_font)
        self.lbl_moon_rise.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.box_moon.layout.addStretch(1)
        self.box_moon.layout.addWidget(self.lbl_moon_state)
        self.box_moon.layout.addStretch(1)
        self.box_moon.layout.addWidget(self.lbl_moon_set)
        self.box_moon.layout.addStretch(1)
        self.box_moon.layout.addWidget(self.lbl_moon_rise)
        self.box_moon.layout.addStretch(1)
        astro_layout.addWidget(self.box_moon, 3)
        root.addWidget(astro_col, 1)

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
            self.lbl_water.setText("—")
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
                f'{self.water_level_m3:.1f} m³  '
                f'<span style="color:{pct_color}">{pct:.0f}%</span>')
        else:
            self.lbl_water.setText(f"{self.water_level_m3:.1f} m³")

    # ---- 1 Hz tick ----------------------------------------------------------

    def _tick(self) -> None:
        now = datetime.datetime.now(datetime.timezone.utc)
        # tz-aware local datetime so we can read .utcoffset() for the
        # LT offset suffix; format as HH:MM:SS for display.
        now_local = datetime.datetime.now().astimezone()
        now_warsaw = datetime.datetime.now(_WARSAW)

        # Clocks
        self.lbl_ut.setText(now.strftime('%H:%M:%S'))
        self.lbl_lt.setText(now_local.strftime('%H:%M:%S'))
        self.lbl_cet.setText(now_warsaw.strftime('%H:%M:%S'))
        # UTC offsets — recomputed each tick so DST transitions appear
        # without a restart. Cheap (timedelta arithmetic + format).
        self.lbl_lt_off.setText(_format_utc_offset(now_local.utcoffset()))
        self.lbl_cet_off.setText(_format_utc_offset(now_warsaw.utcoffset()))
        try:
            self.lbl_sidt.setText(sidereal_time_str(now))
        except Exception as e:
            logger.debug(f"sidereal_time failed: {e}")

        # Sun: show both next sunset (↓) and next sunrise (↑) — closer
        # one bright, the other dim. No countdowns next to the times;
        # NEXT EVENTS already provides that signal at much higher
        # prominence.
        t_set = next_sun_alt_event(now, 0.0, 'setting')
        t_rise = next_sun_alt_event(now, 0.0, 'rising')
        bright = _decide_bright(t_set, t_rise)
        self.lbl_sun_set.setText(_event_line('↓', t_set, bright == 'set'))
        self.lbl_sun_rise.setText(_event_line('↑', t_rise, bright == 'rise'))

        # Moon: alt + phase on the top line (gray tags, bright values,
        # no emoji), then the same paired set/rise format as the sun.
        try:
            ms = moon_state(now)
            self.lbl_moon_state.setText(
                _moon_alt_phase(ms['alt_deg'], ms['phase'] * 100.0))
            t_moonset = next_moon_event(now, 'setting')
            t_moonrise = next_moon_event(now, 'rising')
            mbright = _decide_bright(t_moonset, t_moonrise)
            self.lbl_moon_set.setText(
                _event_line('↓', t_moonset, mbright == 'set'))
            self.lbl_moon_rise.setText(
                _event_line('↑', t_moonrise, mbright == 'rise'))
        except Exception as e:
            logger.debug(f"moon update failed: {e}")
            self.lbl_moon_state.setText("alt —  phase —")
            self.lbl_moon_set.setText(_event_line('↓', None, True))
            self.lbl_moon_rise.setText(_event_line('↑', None, False))

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
            self.lbl_event_next_label.setText("")
            self.lbl_event_next_timer.setText("")
            self.lbl_event_next_when.setText("")
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
        # Second event: same label/timer/when triple, smaller, all dim.
        if len(events) > 1:
            ev2 = events[1]
            arrow2 = '↓' if ev2[1] == 'setting' else '↑'
            self.lbl_event_next_label.setText(f"Sun  {arrow2}  {ev2[0]:+.0f}°")
            self.lbl_event_next_timer.setText(_format_countdown(ev2[2] - now))
            self.lbl_event_next_when.setText(
                f"at {ev2[2].strftime('%H:%M:%S')} UT")
        else:
            self.lbl_event_next_label.setText("")
            self.lbl_event_next_timer.setText("")
            self.lbl_event_next_when.setText("")


widget_class = SiteStatusWidget
