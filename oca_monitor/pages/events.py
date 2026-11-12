"""Events of conditions_overwatch (monitor3, 2026-11-12) - the engine TOI uses (Aux -> Events), shown like NEXT EVENTS.

* Top: the nearest timed event - big countdown, its trigger (``Sun ↓ -18°``, ``UT``) and message, the time in UT.
* Below: a table of the next ones (time UT, countdown, trigger, message); events at the next save of the observers
  (no time) at the end.
* When an event fires (an ``EVENT`` notice on ``message.overwatch.oca.self.notice``, not a ``test``) the top block
  shows it highlighted for ``highlight_s`` (60 s).

Source: ``status.overwatch.oca.self.events`` (``{"events": [...]}``, ``next`` ISO UT or an observers date / "next").
Secret events (``"secret": true``, surprises from TOI admin mode) are not listed; when one fires, its notice is shown
like any other - the surprise is out then anyway.
"""
from __future__ import annotations

import datetime
import logging
import time
from typing import List, Optional

from PyQt6 import QtCore, QtGui
from PyQt6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget
from qasync import asyncSlot

from oca_monitor.pages.site_status import _Group, _format_countdown

logger = logging.getLogger(__name__.rsplit('.')[-1])

LABEL_C = '#5cc4ff'     # trigger / message of the nearest event (as NEXT EVENTS)
TIMER_C = '#ffffff'
SOON_C = '#ffd166'      # last 5 minutes
DIM_C = '#8a8a8a'
ROW_C = '#c8c8c8'
NOW_BG = '#1d4f7a'      # an event that has just fired
SOON_S = 300


def trigger(ev: dict) -> str:
    """``Sun ↓ -18°`` / ``UT`` / ``observers`` - what fires the event (as TOI's obs window)"""
    spec = ev.get('spec') or {}
    kind = spec.get('kind')
    if kind in ('sun_set', 'sun_rise'):
        return f"Sun {'↓' if kind == 'sun_set' else '↑'} {float(spec.get('alt', 0)):+g}°"
    if kind == 'ut':
        return 'UT'
    if kind == 'observers':
        return 'observers'
    return str(ev.get('when', '?'))


def next_time(ev: dict) -> Optional[datetime.datetime]:
    nxt = ev.get('next') or ''
    if 'T' not in nxt:
        return None
    try:
        t = datetime.datetime.fromisoformat(nxt)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc)


class EventsWidget(QWidget):
    """See module docstring."""

    def __init__(self, main_window,
                 events_subject: str = 'status.overwatch.oca.self.events',
                 notice_subject: str = 'message.overwatch.oca.self.notice',
                 rows: int = 4,
                 highlight_s: float = 60.0,
                 **kwargs) -> None:
        super().__init__()
        self.main_window = main_window
        self.events_subject, self.notice_subject = events_subject, notice_subject
        self.n_rows = int(rows)
        self.highlight_s = float(highlight_s)
        self.events: List[dict] = []
        self.fired: Optional[tuple] = None      # (time.time(), info) of the last EVENT notice
        self._init_ui()
        QtCore.QTimer.singleShot(0, self.async_init)
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)

    # ---- UI -----------------------------------------------------------------

    def _init_ui(self) -> None:
        self.setStyleSheet("EventsWidget { background-color: #181818; } QLabel { color: #e0e0e0; }")
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        self.box = _Group('NEXT EVENTS')
        root.addWidget(self.box)

        # nearest event: countdown | trigger + message / time
        self.top = QWidget()
        self.top.setObjectName('EventsTop')
        top = QHBoxLayout(self.top)
        top.setContentsMargins(6, 0, 6, 0)
        top.setSpacing(12)
        self.lbl_timer = QLabel('—')
        self.lbl_timer.setFont(QtGui.QFont('Monaco', 28, QtGui.QFont.Weight.Bold))
        self.lbl_label = QLabel('—')
        self.lbl_label.setFont(QtGui.QFont('Arial', 14, QtGui.QFont.Weight.Bold))
        self.lbl_label.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.lbl_when = QLabel('')
        self.lbl_when.setFont(QtGui.QFont('Arial', 10))
        self.lbl_when.setStyleSheet(f"color: {DIM_C};")
        text = QVBoxLayout()
        text.setSpacing(0)
        text.addWidget(self.lbl_label)
        text.addWidget(self.lbl_when)
        top.addWidget(self.lbl_timer)
        top.addLayout(text, 1)
        self.box.layout.addWidget(self.top)

        # the following ones
        grid = QGridLayout()
        grid.setContentsMargins(6, 2, 6, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(0)
        f = QtGui.QFont('Arial', 11, QtGui.QFont.Weight.Bold)
        fm = QtGui.QFont('Monaco', 11, QtGui.QFont.Weight.Bold)
        self.rows = []
        for r in range(self.n_rows):
            cells = []
            for c, font in enumerate((fm, fm, f, f)):
                lbl = QLabel('')
                lbl.setFont(font)
                lbl.setStyleSheet(f"color: {ROW_C if c != 1 else DIM_C};")
                grid.addWidget(lbl, r, c)
                cells.append(lbl)
            self.rows.append(cells)
        grid.setColumnStretch(3, 1)
        self.box.layout.addLayout(grid)
        self.box.layout.addStretch(1)
        self._set_highlight(False)

    def _set_highlight(self, on: bool) -> None:
        style = (f"QWidget#EventsTop {{ background-color: {NOW_BG}; border-radius: 4px; }}" if on
                 else "QWidget#EventsTop { background-color: transparent; }")
        if self.top.styleSheet() != style:
            self.top.setStyleSheet(style)

    # ---- NATS ---------------------------------------------------------------

    @asyncSlot()
    async def async_init(self):
        for clb, subject, policy in ((self._events_clb, self.events_subject, 'last'),
                                     (self._notice_clb, self.notice_subject, 'new')):
            try:
                await self.main_window.run_reader(clb=clb, subject=subject, deliver_policy=policy)
            except Exception as e:
                logger.warning(f"events reader {subject} failed: {e!r}")

    async def _events_clb(self, data, meta) -> bool:
        try:
            self.events = [ev for ev in (data.get('events') or []) if not ev.get('secret')]
            self._tick()
        except Exception as e:
            logger.warning(f"events status skipped: {e!r}")
        return True

    async def _notice_clb(self, data, meta) -> bool:
        try:
            if data.get('label') == 'EVENT' and not data.get('test'):
                self.fired = (time.time(), str(data.get('info') or 'event'))
                self._tick()
        except Exception as e:
            logger.warning(f"events notice skipped: {e!r}")
        return True

    # ---- drawing (plain Qt slot - must not raise) ---------------------------

    def _tick(self) -> None:
        try:
            self._draw()
        except Exception as e:
            logger.warning(f"events draw: {e!r}")

    def _draw(self) -> None:
        now = datetime.datetime.now(datetime.timezone.utc)
        timed = sorted(((t, ev) for ev in self.events if (t := next_time(ev)) is not None and t > now),
                       key=lambda x: x[0])
        untimed = [ev for ev in self.events if next_time(ev) is None]

        if self.fired is not None and time.time() - self.fired[0] < self.highlight_s:
            self._set_highlight(True)
            self.lbl_timer.setText('NOW')
            self.lbl_timer.setStyleSheet(f"color: {SOON_C};")
            self.lbl_label.setText(f'<span style="color:#ffffff">{self.fired[1]}</span>')
            self.lbl_when.setText(f"at {datetime.datetime.fromtimestamp(self.fired[0], datetime.timezone.utc):%H:%M} UT")
            following = timed
        else:
            self._set_highlight(False)
            if timed:
                t, ev = timed[0]
                delta = t - now
                self.lbl_timer.setText(_format_countdown(delta))
                self.lbl_timer.setStyleSheet(f"color: {SOON_C if delta.total_seconds() < SOON_S else TIMER_C};")
                self.lbl_label.setText(f'<span style="color:{LABEL_C}">{trigger(ev)}</span>'
                                       f'&nbsp;&nbsp;{ev.get("info", "")}')
                self.lbl_when.setText(f"at {t:%H:%M} UT" + ("" if ev.get('repeat') else "  (once)"))
                following = timed[1:]
            else:
                self.lbl_timer.setText('—')
                self.lbl_timer.setStyleSheet(f"color: {DIM_C};")
                self.lbl_label.setText('no timed event')
                self.lbl_when.setText('')
                following = []

        lines = [(f"{t:%H:%M}", _format_countdown(t - now), trigger(ev), ev.get('info', '')) for t, ev in following]
        lines += [('', '', trigger(ev), ev.get('info', '')) for ev in untimed]
        for r, cells in enumerate(self.rows):
            values = lines[r] if r < len(lines) else ('', '', '', '')
            for lbl, v in zip(cells, values):
                if lbl.text() != v:
                    lbl.setText(v)


widget_class = EventsWidget
