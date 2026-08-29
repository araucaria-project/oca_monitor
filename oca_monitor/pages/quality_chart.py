"""Quality-log severity chart page.

One squeezed time-series panel per telescope, styled after the
``Photometric Zero`` panel of :mod:`oca_monitor.pages.weather`: fixed Y
scale with alert zone bands behind the data, a translucent scatter of
individual samples, a bright white gaussian-smoothed trend line as the
headline signal, and a big live overlay coloured by alert zone.

Data comes from the quality journal ``tic.journal.<tel>.quality`` — the
same stream (and the same three fields: ``timestamp``, ``message``,
``level``) that halina's ``TelescopeDtaCollector._read_data_from_quality_log``
reads for the nightly e-mail report. Where the log page renders those
records as scrolling text, this page plots their *severity* against
time, so a glance shows whether the night is quiet or the pipeline has
been complaining, and since when.
"""
from __future__ import annotations

import datetime
import logging
import math as _math
from typing import Any, List, Optional, Tuple

import numpy as np
from PyQt6 import QtCore  # imported before matplotlib so qt_compat picks PyQt6
from PyQt6.QtWidgets import QVBoxLayout, QWidget
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.ticker import NullLocator
from qasync import asyncSlot
from serverish.base import dt_from_array
from serverish.base.task_manager import create_task
from serverish.messenger import get_reader

from oca_monitor.utils.ephem_ocm import next_sun_alt_event
from oca_monitor.widgets import chart_kit as ck

logger = logging.getLogger(__name__.rsplit('.')[-1])


# ----------------------------------------------------------------------------
# Severity levels
# ----------------------------------------------------------------------------

# Numeric levels as published on the journal stream; mirrors halina's
# ``QualityLogMsg.LEVEL_NAMES``. The numbers are stdlib ``logging``
# levels except NOTICE (25), which is an OCA addition, and 40 which the
# quality journal labels MAJOR rather than ERROR.
LEVEL_DEBUG = 10
LEVEL_INFO = 20
LEVEL_NOTICE = 25
LEVEL_WARNING = 30
LEVEL_MAJOR = 40

LEVEL_NAMES = {
    LEVEL_DEBUG: 'DEBUG',
    LEVEL_INFO: 'INFO',
    LEVEL_NOTICE: 'NOTICE',
    LEVEL_WARNING: 'WARNING',
    LEVEL_MAJOR: 'MAJOR',
}

# Per-level marker colour. DEBUG is deliberately the dim foreground grey
# rather than a palette colour — debug chatter should recede, not compete
# with the levels an operator has to act on.
LEVEL_COLORS = {
    LEVEL_DEBUG: ck.FG_DIM,
    LEVEL_INFO: ck.COLOR_OK,
    LEVEL_NOTICE: ck.COLOR_WARN,
    LEVEL_WARNING: ck.COLOR_LOAD,   # orange — between amber and red
    LEVEL_MAJOR: ck.COLOR_DANGER,
}


def _level_name(level: float) -> str:
    """Name of the level nearest to ``level`` (smoothed values land between)."""
    nearest = min(LEVEL_NAMES, key=lambda lv: abs(lv - level))
    return LEVEL_NAMES[nearest]


def _marker_color(level: float) -> str:
    """Exact-level colour when the level is one we know, else zone colour."""
    try:
        return LEVEL_COLORS[int(level)]
    except (KeyError, TypeError, ValueError):
        return _zone_color(level)


def _zone_color(level: float) -> str:
    """Alert-zone colour for any severity, known level or not."""
    if level >= LEVEL_WARNING:
        return ck.COLOR_DANGER
    if level >= LEVEL_NOTICE:
        return ck.COLOR_WARN
    if level >= LEVEL_INFO:
        return ck.COLOR_OK
    return ck.FG_DIM


# ----------------------------------------------------------------------------
# Time helpers — kept in sync with the pipeline panels of weather.py
# ----------------------------------------------------------------------------

# OCM is at -70°W → local noon = 16:00 UTC. Journal records are replayed
# from that boundary so the chart holds exactly the current observing
# night, and resets cleanly once a day.
_OCM_LOCAL_NOON_UTC_HOUR = 16


def _hour_now_utc() -> float:
    n = datetime.datetime.now(datetime.timezone.utc)
    return n.hour + n.minute / 60.0 + n.second / 3600.0


def _current_night_start_utc() -> datetime.datetime:
    """Most recent OCM local-noon (16:00 UTC), as a tz-aware UTC datetime."""
    now = datetime.datetime.now(datetime.timezone.utc)
    local_noon = now.replace(hour=_OCM_LOCAL_NOON_UTC_HOUR,
                             minute=0, second=0, microsecond=0)
    if local_noon > now:
        local_noon -= datetime.timedelta(days=1)
    return local_noon


def _next_sunset_utc() -> datetime.datetime:
    now = datetime.datetime.now(datetime.timezone.utc)
    t = next_sun_alt_event(now, 0.0, 'setting')
    if t is None:
        # Degenerate geometry (never reached at OCM); push to "tomorrow"
        # so the reset scheduler still ticks.
        return now + datetime.timedelta(days=1)
    return t


def _hour_from_dt(dt: Optional[datetime.datetime]) -> Optional[float]:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(datetime.timezone.utc)
    return dt.hour + dt.minute / 60.0 + dt.second / 3600.0


def _hour_from_meta(meta) -> Optional[float]:
    try:
        return _hour_from_dt(dt_from_array(meta['ts']))
    except (LookupError, TypeError, ValueError):
        return None


# ----------------------------------------------------------------------------
# Page widget
# ----------------------------------------------------------------------------

class QualityChartWidget(QWidget):
    """Severity-vs-time chart of one telescope's quality journal."""

    # Fixed scale — padded half a step beyond DEBUG/MAJOR so extreme
    # markers are not clipped by the axes frame.
    Y_MIN = LEVEL_DEBUG - 5.0
    Y_MAX = LEVEL_MAJOR + 5.0

    SMOOTH_SIGMA = 5.0
    # Maximum hour-of-day gap between consecutive records that still
    # counts as "the same segment" of the trend curve. Anything wider
    # gets a NaN break so the line doesn't connect islands of messages
    # across hours of silence.
    MAX_SEGMENT_GAP_HOURS = 0.5
    # Minimum records in a segment before smoothing is applied — a curve
    # through 1–3 samples is more misleading than helpful, and the
    # scatter already shows those raw points.
    MIN_SEGMENT_POINTS = 4

    MEAN_LINE_COLOR = '#ffffff'   # unused elsewhere in the palette

    MAX_POINTS = 6000             # ring-buffer cap; journals can be chatty
    TRIM_POINTS = 1500

    def __init__(self, main_window, tel: str, subject: str = '',
                 vertical_screen: bool = False, **kwargs) -> None:
        super().__init__()
        self.main_window = main_window
        self.tel = tel
        self.vertical = bool(vertical_screen)
        self.subject = subject or f'tic.journal.{tel}.quality'

        self._hours: List[float] = []
        self._levels: List[float] = []

        self._scatter: Optional[Any] = None
        self._line_smoothed: Optional[Any] = None
        self._overlay: Optional[Any] = None

        self._dirty = False
        self._draw_pending = False
        self._draw_interval_ms = 100

        self._init_ui()
        QtCore.QTimer.singleShot(0, self.async_init)
        logger.info(f"QualityChartWidget {self.tel} init setup done")

    # ---- UI -----------------------------------------------------------------

    def _init_ui(self) -> None:
        self.layout_root = QVBoxLayout(self)
        self.layout_root.setContentsMargins(2, 2, 2, 2)
        self.layout_root.setSpacing(2)

        self.figure = Figure(constrained_layout=False)
        ck.style_figure(self.figure)
        self.canvas = FigureCanvas(self.figure)
        self.layout_root.addWidget(self.canvas, 1)

        self.ax = ck.make_stacked_axes(self.figure, 1)[0]
        # Widen the left margin over the chart_kit default: this panel's
        # Y ticks are level NAMES, not 2-3 digit numbers, and 'WARNING'
        # gets clipped at the stock 0.06.
        self.figure.subplots_adjust(left=0.095)
        self._init_axes(self.ax)
        ck.format_hour_xaxis(self.ax)
        self.canvas.draw_idle()

    def _init_axes(self, ax) -> None:
        ax.set_zorder(2)
        ax.set_ylim(self.Y_MIN, self.Y_MAX)

        # Alert zone bands, drawn behind the data so the background
        # colour itself reads as "how bad is it up here". Unlike the
        # photometric-zero panel the danger zone is at the TOP, because
        # severity grows upwards.
        ax.axhspan(self.Y_MIN, LEVEL_NOTICE,
                   color=ck.COLOR_OK, alpha=0.10, linewidth=0, zorder=0)
        ax.axhspan(LEVEL_NOTICE, LEVEL_WARNING,
                   color=ck.COLOR_WARN, alpha=0.15, linewidth=0, zorder=0)
        ax.axhspan(LEVEL_WARNING, self.Y_MAX,
                   color=ck.COLOR_DANGER, alpha=0.20, linewidth=0, zorder=0)

        # Named Y ticks — the raw logging numbers mean nothing on a wall
        # display, the level names do.
        ax.set_yticks(list(LEVEL_NAMES))
        ax.set_yticklabels([LEVEL_NAMES[lv] for lv in LEVEL_NAMES], fontsize=9)
        for tick, lv in zip(ax.get_yticklabels(), LEVEL_NAMES):
            tick.set_color(LEVEL_COLORS[lv])
        # style_axes turns on the minor grid for both axes; on a
        # categorical severity scale minor Y ticks are just noise, so
        # drop them while the hour axis keeps its own.
        ax.yaxis.set_minor_locator(NullLocator())

        self._scatter = ax.scatter([], [], s=14, alpha=0.55, edgecolors='none',
                                   linewidths=0, zorder=4)
        # Combined smoothed trend — the headline signal: "how noisy is
        # the pipeline right now". Bright constant white at high alpha
        # and elevated zorder so it dominates, kept thin so the scatter
        # underneath stays legible.
        self._line_smoothed, = ax.plot([], [], '-', color=self.MEAN_LINE_COLOR,
                                       linewidth=1.6, alpha=0.95, zorder=8)
        # Centred, unlike the weather panels' right-aligned overlays: an
        # OCM night occupies 18-24 h and 0-6 h on this axis, so the
        # middle of the chart is the daytime gap and the only spot that
        # never covers data.
        self._overlay = ck.big_overlay(ax, x=0.5, ha='center')
        ck.inline_title(ax, f'Quality Log  [{self.tel}]', side='left')

    # ---- async init ---------------------------------------------------------

    @asyncSlot()
    async def async_init(self):
        await create_task(self._journal_loop(), f'quality_chart_{self.tel}')
        self._schedule_next_sunset_reset()

    async def _journal_loop(self) -> None:
        """Replay the current night's journal, then follow it live."""
        try:
            r = get_reader(self.subject, deliver_policy='by_start_time',
                           opt_start_time=_current_night_start_utc())
            async for data, meta in r:
                if not isinstance(data, dict):
                    continue
                try:
                    level = float(data['level'])
                except (LookupError, TypeError, ValueError):
                    continue
                if not _math.isfinite(level):
                    continue
                try:
                    hour = _hour_from_dt(dt_from_array(data['timestamp']))
                except (LookupError, TypeError, ValueError):
                    hour = None
                if hour is None:
                    hour = _hour_from_meta(meta) or _hour_now_utc()
                self._append(hour, level)
                self._schedule_draw()
        except Exception as e:
            logger.warning(f"quality journal reader [{self.tel}] failed: {e}")

    def _append(self, hour: float, level: float) -> None:
        self._hours.append(hour)
        self._levels.append(level)
        if len(self._hours) > self.MAX_POINTS:
            del self._hours[:self.TRIM_POINTS]
            del self._levels[:self.TRIM_POINTS]
        # Only flag; the actual O(N) rebuild happens once per throttled
        # redraw, so a history replay of thousands of records costs O(N)
        # rather than O(N²).
        self._dirty = True

    # ---- rendering ----------------------------------------------------------

    def _schedule_draw(self) -> None:
        """Coalesce redraws so a flood of journal records doesn't turn
        into a flood of repaints. Caps draws at ~10 Hz."""
        if self._draw_pending:
            return
        self._draw_pending = True
        QtCore.QTimer.singleShot(self._draw_interval_ms, self._do_draw)

    def _do_draw(self) -> None:
        self._draw_pending = False
        if self._dirty:
            self._dirty = False
            try:
                self._render()
            except Exception as e:
                logger.warning(f"quality chart render failed [{self.tel}]: {e}")
        self.canvas.draw_idle()

    def _render(self) -> None:
        if not self._hours:
            self._scatter.set_offsets(np.zeros((0, 2)))
            self._line_smoothed.set_data([], [])
            self._overlay.set_text('')
            return

        # Kept in arrival order, which is the journal's chronological
        # order. NOT sorted by hour-of-day: an observing night crosses
        # midnight, so sorting would put the morning tail before the
        # evening head and the trend's "tip" would stop being now.
        x = np.asarray(self._hours, dtype=float)
        y = np.asarray(self._levels, dtype=float)

        self._scatter.set_offsets(np.column_stack((x, y)))
        self._scatter.set_color([_marker_color(v) for v in y])

        out_x, out_y, tip = self._smoothed_segments(x, y)
        self._line_smoothed.set_data(out_x, out_y)
        if tip is None:
            # No segment long enough to trend — show the newest record's
            # own level rather than nothing.
            tip = float(y[-1])
        self._overlay.set_text(_level_name(tip))
        self._overlay.set_color(_zone_color(tip))

    def _smoothed_segments(self, x: np.ndarray, y: np.ndarray
                           ) -> Tuple[List[float], List[float], Optional[float]]:
        """Gaussian-smooth each contiguous run of records separately.

        Returns ``(xs, ys, last_smoothed)`` with NaN separators between
        segments — matplotlib breaks the line at NaN, so the trend never
        connects across hours of silence.

        ``x`` is chronological but plotted on an hour-of-day axis, so a
        run is cut both where the gap is too wide AND where the hour
        goes backwards (UTC midnight). Every segment is therefore
        monotonic in x, and the LAST one is the current one.
        """
        if x.size > 1:
            d = np.diff(x)
            cuts = np.where((d > self.MAX_SEGMENT_GAP_HOURS) | (d < 0.0))[0] + 1
            seg_x = np.split(x, cuts)
            seg_y = np.split(y, cuts)
        else:
            seg_x = [x]
            seg_y = [y]

        out_x: List[float] = []
        out_y: List[float] = []
        last_smoothed: Optional[float] = None
        for sx, sy in zip(seg_x, seg_y):
            if sx.size < self.MIN_SEGMENT_POINTS:
                continue
            sy_smooth = ck.gaussian_filter1d(sy, sigma=self.SMOOTH_SIGMA)
            if out_x:
                out_x.append(np.nan)
                out_y.append(np.nan)
            out_x.extend(sx.tolist())
            out_y.extend(np.asarray(sy_smooth, dtype=float).tolist())
            last_smoothed = float(sy_smooth[-1])
        return out_x, out_y, last_smoothed

    # ---- nightly reset ------------------------------------------------------

    def _schedule_next_sunset_reset(self) -> None:
        """Arm a one-shot timer for the next OCM sunset, at which point
        the chart wipes its buffer so each observing night starts fresh."""
        try:
            sunset = _next_sunset_utc()
        except Exception as e:
            logger.warning(f"Failed to compute next sunset; reset disabled: {e}")
            return
        now = datetime.datetime.now(datetime.timezone.utc)
        delay_s = max(60.0, (sunset - now).total_seconds())
        delay_ms = min(int(delay_s * 1000), 2_147_000_000)  # QTimer takes int32 ms
        logger.info(
            f"Quality chart [{self.tel}] next sunset reset at {sunset.isoformat()} "
            f"(in {delay_s/3600:.2f} h)")
        QtCore.QTimer.singleShot(delay_ms, self._do_sunset_reset)

    def _do_sunset_reset(self) -> None:
        self._hours.clear()
        self._levels.clear()
        self._dirty = True
        self._schedule_draw()
        self._schedule_next_sunset_reset()


widget_class = QualityChartWidget
