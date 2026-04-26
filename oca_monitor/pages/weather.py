"""Weather/conditions dashboard page.

A configurable stack of squeezed time-series charts sharing a single X
axis. Panel selection is driven by the ``charts`` page parameter from
``settings.toml``; permanent panels (``wind``) are forced to be present.

Defaults render three panels: wind (today + yesterday + alert bands +
windy.com-style direction arrows along the bottom), humidity+pressure
(twin-axis) and temperature. Optional panels add per-telescope
dome/wind alignment and FWHM tracking, both colour-coded by telescope
config from ``tic.config.observatory``.
"""
from __future__ import annotations

import datetime
import logging
import math
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

import ephem
import numpy as np
from PyQt6 import QtCore, QtGui  # imported before matplotlib so qt_compat picks PyQt6
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget
from astropy.time import Time as AstropyTime
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from qasync import asyncSlot
from serverish.base import dt_ensure_datetime, dt_from_array
from serverish.base.task_manager import create_task
from serverish.messenger import Messenger, get_reader

from oca_monitor.widgets import chart_kit as ck

logger = logging.getLogger(__name__.rsplit('.')[-1])


# ----------------------------------------------------------------------------
# Ephemeris helper (kept inline; used only for the header label)
# ----------------------------------------------------------------------------

def _ephemeris_text(vertical: bool = False) -> Tuple[str, float]:
    obs = ephem.Observer()
    obs.lon = '-70.201266'
    obs.lat = '-24.598616'
    obs.elev = 2800
    obs.pressure = 730
    ut = time.strftime('%Y/%m/%d %H:%M:%S', time.gmtime())
    lt = time.strftime('%H:%M:%S', time.localtime())
    obs.date = ut
    sun = ephem.Sun()
    sun.compute(obs)
    parts = str(sun.alt).split(':')
    deg = float(parts[0])
    minutes = float(parts[1]) / 60.0
    sun_alt = deg + minutes if not str(sun.alt).startswith('-') else deg - minutes
    sep = '\n' if vertical else '\t'
    return f'LT: {lt}{sep}SUN ALT: {sun_alt:.1f}', sun_alt


# ----------------------------------------------------------------------------
# Panels
# ----------------------------------------------------------------------------

class _Panel:
    """Base class for one row of the squeezed chart stack."""

    title: str = ''

    needs_weather_history: bool = False
    needs_faststat: bool = False
    needs_zdf: bool = False
    needs_zero_monitor: bool = False
    needs_dome_state: bool = False
    needs_mount_az: bool = False

    def __init__(self) -> None:
        self.ax = None  # type: Optional[Any]
        self._overlay = None

    def init_axes(self, ax) -> None:
        self.ax = ax
        ax.set_zorder(2)
        ck.inline_title(ax, self.title)

    # Live-value overlay — subclasses opt in by calling _add_overlay() in
    # init_axes and overriding format_overlay().
    def _add_overlay(self, ax, **kwargs) -> None:
        self._overlay = ck.big_overlay(ax, **kwargs)

    def format_overlay(self, msm: dict) -> Optional[str]:
        return None

    def on_live_summary(self, msm: dict, alert_color: Optional[str]) -> None:
        if self._overlay is None:
            return
        try:
            text = self.format_overlay(msm)
        except (KeyError, TypeError, ValueError):
            text = None
        if text is None:
            return
        self._overlay.set_text(text)
        if alert_color:
            self._overlay.set_color(alert_color)

    # Default no-ops; subclasses override.
    def on_weather(self, hour: float, ts: datetime.datetime, msm: dict,
                   *, is_yesterday: bool) -> None: ...

    def on_midnight_rollover(self) -> None: ...

    def on_faststat(self, tel: str, hour: float, raw: dict) -> None: ...

    def on_zdf(self, tel: str, hour: float, content: dict) -> None: ...

    def on_zero_monitor(self, tel: str, hour: float, data: dict) -> None: ...

    def on_dome_state(self, tel: str, shutter_open: Optional[bool]) -> None: ...

    def on_mount_az(self, tel: str, az_deg: float, hour: float) -> None: ...


class _SimpleSeriesPanel(_Panel):
    """Today + yesterday line panel — wind, temperature, humidity, etc."""

    needs_weather_history = True

    def __init__(self, *, measurement_key: str, y_label: str,
                 today_color: str,
                 y_min: Optional[float] = None, y_max: Optional[float] = None,
                 reject_above: Optional[float] = None,
                 reject_below: Optional[float] = None,
                 zone_drawer=None,
                 smooth_window: int = 1,
                 overlay_unit: Optional[str] = None,
                 overlay_format: str = '{:.1f}') -> None:
        super().__init__()
        self.measurement_key = measurement_key
        self.title = y_label
        self.today_color = today_color
        self.y_min = y_min
        self.y_max = y_max
        self.reject_above = reject_above
        self.reject_below = reject_below
        self.zone_drawer = zone_drawer
        self.smooth_window = max(1, int(smooth_window))
        self.overlay_unit = overlay_unit
        self.overlay_format = overlay_format
        self._today_x: List[float] = []
        self._today_y: List[float] = []
        self._yesterday_x: List[float] = []
        self._yesterday_y: List[float] = []
        self._line_today = None
        self._line_yesterday = None

    def init_axes(self, ax) -> None:
        super().init_axes(ax)
        if self.zone_drawer is not None:
            self.zone_drawer(ax)
        # Yesterday: same colour, faded, thin line — better than dots when the
        # underlying signal is slow-moving (humidity, pressure, temperature).
        self._line_yesterday, = ax.plot([], [], '-', color=self.today_color,
                                        alpha=ck.YESTERDAY_ALPHA, linewidth=1.0,
                                        zorder=2, label='Yesterday')
        self._line_today, = ax.plot([], [], '-', color=self.today_color,
                                    linewidth=1.5, zorder=4, label='Today')
        if self.y_min is not None or self.y_max is not None:
            ax.set_ylim(self.y_min if self.y_min is not None else ax.get_ylim()[0],
                        self.y_max if self.y_max is not None else ax.get_ylim()[1])
        if self.overlay_unit is not None:
            self._add_overlay(ax)

    def format_overlay(self, msm):
        if self.overlay_unit is None:
            return None
        v = float(msm[self.measurement_key])
        return f"{self.overlay_format.format(v)} {self.overlay_unit}"

    def _accepts(self, value: float) -> bool:
        if self.reject_above is not None and value > self.reject_above:
            return False
        if self.reject_below is not None and value < self.reject_below:
            return False
        return True

    def _redraw(self) -> None:
        if self._line_today is not None:
            self._line_today.set_data(
                self._today_x, ck.running_mean(self._today_y, self.smooth_window))
        if self._line_yesterday is not None:
            self._line_yesterday.set_data(
                self._yesterday_x,
                ck.running_mean(self._yesterday_y, self.smooth_window))

    def on_weather(self, hour, ts, msm, *, is_yesterday) -> None:
        try:
            value = float(msm[self.measurement_key])
        except (KeyError, TypeError, ValueError):
            return
        if not self._accepts(value):
            return
        if is_yesterday:
            self._yesterday_x.append(hour)
            self._yesterday_y.append(value)
        else:
            self._today_x.append(hour)
            self._today_y.append(value)
        self._redraw()
        self._autoscale_y()

    def _autoscale_y(self) -> None:
        ax = self.ax
        if ax is None:
            return
        if self.y_min is None and self.y_max is None:
            ax.relim()
            ax.autoscale_view(scalex=False, scaley=True)

    def on_midnight_rollover(self) -> None:
        self._yesterday_x, self._yesterday_y = self._today_x, self._today_y
        self._today_x, self._today_y = [], []
        self._redraw()


class _WindPanel(_SimpleSeriesPanel):
    """Wind speed + direction-arrow strip along the bottom."""

    def __init__(self) -> None:
        super().__init__(
            measurement_key='wind_10min_ms',
            y_label='Wind  [m/s]',
            today_color=ck.COLOR_TODAY,
            y_min=0.0, y_max=None,
            reject_above=ck.WIND_DANGER_MS * 3.0,
            reject_below=0.0,
            zone_drawer=ck.wind_zone_bands,
        )
        self._dir_x: List[float] = []
        self._dir_d: List[float] = []
        self._quiver = None

    def init_axes(self, ax) -> None:
        super().init_axes(ax)
        ax.set_ylim(0, max(15.0, ck.WIND_DANGER_MS * 1.4))
        self._add_overlay(ax)

    def format_overlay(self, msm):
        wind = float(msm['wind_10min_ms'])
        wdir = int(msm['wind_dir_deg'])
        return f"{wind:.1f} m/s   {wdir:>3d}°"

    def on_weather(self, hour, ts, msm, *, is_yesterday) -> None:
        super().on_weather(hour, ts, msm, is_yesterday=is_yesterday)
        if is_yesterday:
            return
        try:
            d = float(msm['wind_dir_deg'])
        except (KeyError, TypeError, ValueError):
            return
        if not 0.0 <= d <= 360.0:
            return
        self._dir_x.append(hour)
        self._dir_d.append(d)
        # cap memory at ~1 day's worth even if the reader replays history.
        if len(self._dir_x) > 4000:
            self._dir_x = self._dir_x[-3000:]
            self._dir_d = self._dir_d[-3000:]
        self._refresh_arrows()

    def _refresh_arrows(self) -> None:
        ax = self.ax
        if ax is None:
            return
        centers, means = ck.bin_directions(self._dir_x, self._dir_d, n_bins=12)
        if not centers:
            return
        u, v = ck.compass_to_uv(means, flow_to=True)
        # Hug the bottom of the panel — a narrow strip below the wind
        # line, where they minimally obscure the speed reading.
        y_lo, y_hi = ax.get_ylim()
        y_arrow = y_lo + 0.04 * (y_hi - y_lo)
        ys = np.full_like(u, y_arrow, dtype=float)
        if self._quiver is not None:
            try:
                self._quiver.remove()
            except (ValueError, AttributeError):
                pass
        # Bolder than the default quiver but translucent so they don't
        # dominate when wind is near zero.
        self._quiver = ax.quiver(
            centers, ys, u, v,
            angles='uv', scale_units='inches', scale=2.6,
            width=0.010, headwidth=3.4, headlength=4.2, headaxislength=3.6,
            color=ck.COLOR_WIND_ARROW, alpha=0.55, zorder=5, pivot='middle',
            linewidth=0.4, edgecolor='#1a1a1a',
        )

    def on_midnight_rollover(self) -> None:
        super().on_midnight_rollover()
        self._dir_x, self._dir_d = [], []
        if self._quiver is not None:
            try:
                self._quiver.remove()
            except (ValueError, AttributeError):
                pass
            self._quiver = None


class _HumidityPressurePanel(_Panel):
    """Humidity (semi-transparent area, left axis) + pressure (line, right axis).

    Both signals are slow-moving; we apply a centred running mean to clean
    up reading noise before drawing. Yesterday is rendered as a faded line
    in the same colour as today (no scatter dots) — the variant from the
    earlier draft that the user preferred.
    """

    needs_weather_history = True

    title = 'Humidity  [%]'
    title_right = 'Pressure  [hPa]'

    HUM_SMOOTH = 11      # ~11 minutes at 1 Hz Davis cadence
    PRES_SMOOTH = 21     # ~20 minutes — pressure changes very slowly

    def __init__(self) -> None:
        super().__init__()
        self.ax_p = None
        self._h_today_x: List[float] = []
        self._h_today_y: List[float] = []
        self._h_yest_x: List[float] = []
        self._h_yest_y: List[float] = []
        self._p_today_x: List[float] = []
        self._p_today_y: List[float] = []
        self._p_yest_x: List[float] = []
        self._p_yest_y: List[float] = []
        self._line_h_today = None
        self._line_h_yest = None
        self._fill_h_today = None
        self._line_p_today = None
        self._line_p_yest = None

    def init_axes(self, ax) -> None:
        super().init_axes(ax)
        ck.humidity_zone_bands(ax)
        ax.set_ylim(0, 100)
        ax.set_yticks([0, 25, 50, 75, 100])
        # Humidity (left axis) — yesterday as faded line, today thin and clean.
        self._line_h_yest, = ax.plot([], [], '-', color=ck.COLOR_HUMIDITY,
                                     alpha=ck.YESTERDAY_ALPHA, linewidth=0.9,
                                     zorder=2)
        self._line_h_today, = ax.plot([], [], '-', color=ck.COLOR_HUMIDITY,
                                      linewidth=1.3, zorder=4)
        # Pressure twin axis — transparent face so humidity zones show through;
        # tick labels pulled INSIDE the chart so they're not clipped at the
        # right edge of the figure.
        self.ax_p = ax.twinx()
        self.ax_p.set_facecolor('none')
        self.ax_p.grid(False)
        self.ax_p.tick_params(axis='y', direction='in', length=4, pad=-4,
                              labelsize=9, colors=ck.COLOR_PRESSURE)
        for label in self.ax_p.get_yticklabels():
            label.set_horizontalalignment('right')
        for side in ('top', 'bottom', 'left'):
            self.ax_p.spines[side].set_visible(False)
        self.ax_p.spines['right'].set_color(ck.COLOR_PRESSURE)
        self._line_p_yest, = self.ax_p.plot([], [], '-', color=ck.COLOR_PRESSURE,
                                            alpha=ck.YESTERDAY_ALPHA,
                                            linewidth=0.9, zorder=2)
        self._line_p_today, = self.ax_p.plot([], [], '-', color=ck.COLOR_PRESSURE,
                                             linewidth=1.3, zorder=4)
        ck.inline_title(self.ax_p, self.title_right, side='right',
                        color=ck.COLOR_PRESSURE)
        # Live overlay split between the two metrics, both rendered in
        # the parent axes so colour/alpha logic stays unified.
        self._overlay_h = ck.big_overlay(ax, x=0.99, y=0.72, color=ck.COLOR_HUMIDITY)
        self._overlay_p = ck.big_overlay(ax, x=0.99, y=0.32, color=ck.COLOR_PRESSURE)

    def on_live_summary(self, msm, alert_color) -> None:
        try:
            hum = int(msm['humidity'])
            pres = float(msm['pressure_Pa'])
            if pres > 10000:
                pres = pres / 100.0
        except (KeyError, TypeError, ValueError):
            return
        if self._overlay_h is not None:
            self._overlay_h.set_text(f"{hum} %")
            if alert_color:
                self._overlay_h.set_color(alert_color)
        if self._overlay_p is not None:
            self._overlay_p.set_text(f"{pres:.0f} hPa")

    def _redraw_humidity_fill(self) -> None:
        if self.ax is None:
            return
        if self._fill_h_today is not None:
            try:
                self._fill_h_today.remove()
            except (ValueError, AttributeError):
                pass
        if self._h_today_x:
            smoothed = ck.running_mean(self._h_today_y, self.HUM_SMOOTH)
            self._fill_h_today = self.ax.fill_between(
                self._h_today_x, 0, smoothed,
                color=ck.COLOR_HUMIDITY, alpha=0.18, linewidth=0, zorder=3)

    def _redraw_humidity(self) -> None:
        if self._line_h_today is not None:
            self._line_h_today.set_data(
                self._h_today_x, ck.running_mean(self._h_today_y, self.HUM_SMOOTH))
        if self._line_h_yest is not None:
            self._line_h_yest.set_data(
                self._h_yest_x, ck.running_mean(self._h_yest_y, self.HUM_SMOOTH))
        self._redraw_humidity_fill()

    def _redraw_pressure(self) -> None:
        if self._line_p_today is not None:
            self._line_p_today.set_data(
                self._p_today_x, ck.running_mean(self._p_today_y, self.PRES_SMOOTH))
        if self._line_p_yest is not None:
            self._line_p_yest.set_data(
                self._p_yest_x, ck.running_mean(self._p_yest_y, self.PRES_SMOOTH))
        if self.ax_p is not None:
            self.ax_p.relim()
            self.ax_p.autoscale_view(scalex=False, scaley=True)

    def on_weather(self, hour, ts, msm, *, is_yesterday) -> None:
        try:
            hum = float(msm['humidity'])
        except (KeyError, TypeError, ValueError):
            hum = None
        try:
            pres_pa = float(msm['pressure_Pa'])
            pres = pres_pa / 100.0 if pres_pa > 10000 else pres_pa
        except (KeyError, TypeError, ValueError):
            pres = None

        if hum is not None and 0.0 <= hum <= 100.0:
            if is_yesterday:
                self._h_yest_x.append(hour); self._h_yest_y.append(hum)
            else:
                self._h_today_x.append(hour); self._h_today_y.append(hum)
            self._redraw_humidity()
        if pres is not None and 600.0 < pres < 1100.0:
            if is_yesterday:
                self._p_yest_x.append(hour); self._p_yest_y.append(pres)
            else:
                self._p_today_x.append(hour); self._p_today_y.append(pres)
            self._redraw_pressure()

    def on_midnight_rollover(self) -> None:
        self._h_yest_x, self._h_yest_y = self._h_today_x, self._h_today_y
        self._p_yest_x, self._p_yest_y = self._p_today_x, self._p_today_y
        self._h_today_x, self._h_today_y = [], []
        self._p_today_x, self._p_today_y = [], []
        self._redraw_humidity()
        self._redraw_pressure()


class _DomeWindAzPanel(_Panel):
    """Per-telescope dome-vs-wind alignment angle, telescope-coloured.

    Plots the smallest angular distance (0..180°) between the dome
    azimuth (currently sourced from ``mount.azimuth`` as a proxy — OCM
    has no separate dome.azimuth subject) and the wind direction. A
    danger band along the bottom marks alignments below
    ``danger_zone_deg`` (wind blowing close to the open dome face).
    """

    needs_weather_history = True
    needs_dome_state = True
    needs_mount_az = True

    def __init__(self, main_window, telescopes: Sequence[str],
                 danger_zone_deg: float = 30.0) -> None:
        super().__init__()
        self.main_window = main_window
        self.telescopes = list(telescopes)
        self.danger_zone_deg = float(danger_zone_deg)
        self.title = f'Dome ↔ Wind alignment  [°  – danger <{int(self.danger_zone_deg)}°]'
        self._latest_az: Dict[str, Optional[float]] = {t: None for t in self.telescopes}
        self._latest_open: Dict[str, Optional[bool]] = {t: None for t in self.telescopes}
        self._latest_wind_dir: Optional[float] = None
        self._lines_open: Dict[str, Any] = {}
        self._lines_closed: Dict[str, Any] = {}
        self._series: Dict[str, Tuple[List[float], List[float], List[bool]]] = {
            t: ([], [], []) for t in self.telescopes  # (hours, divergences, was_open)
        }

    def init_axes(self, ax) -> None:
        super().init_axes(ax)
        ax.set_ylim(0, 180)
        ax.set_yticks([0, 30, 60, 90, 120, 150, 180])
        ax.axhspan(0, self.danger_zone_deg, color=ck.COLOR_DOME_DANGER,
                   alpha=0.18, linewidth=0, zorder=0)
        for tel in self.telescopes:
            color = ck.telescope_color(self.main_window, tel)
            self._lines_open[tel], = ax.plot([], [], '-', color=color,
                                             linewidth=1.6, zorder=4,
                                             label=f'{tel} (open)')
            self._lines_closed[tel], = ax.plot([], [], ':', color=color,
                                               linewidth=1.4, alpha=0.7,
                                               zorder=3, label=f'{tel} (closed)')

    def restamp_telescope_colors(self) -> None:
        for tel in self.telescopes:
            color = ck.telescope_color(self.main_window, tel)
            if tel in self._lines_open:
                self._lines_open[tel].set_color(color)
            if tel in self._lines_closed:
                self._lines_closed[tel].set_color(color)

    def _maybe_append(self, tel: str, hour: float) -> None:
        az = self._latest_az.get(tel)
        wd = self._latest_wind_dir
        if az is None or wd is None:
            return
        diff = ck.circular_diff_deg(az, wd)
        is_open = bool(self._latest_open.get(tel))
        hours, diffs, opens = self._series[tel]
        if hours and abs(hours[-1] - hour) < 1e-4:
            hours[-1] = hour; diffs[-1] = diff; opens[-1] = is_open
        else:
            hours.append(hour); diffs.append(diff); opens.append(is_open)
            if len(hours) > 5000:
                del hours[:1000]; del diffs[:1000]; del opens[:1000]
        self._refresh_lines(tel)

    def _refresh_lines(self, tel: str) -> None:
        hours, diffs, opens = self._series[tel]
        # Split into segments by shutter state; mask out the off-state with NaN
        # so set_data on a single Line2D draws only the matching state.
        x_open: List[float] = []
        y_open: List[float] = []
        x_closed: List[float] = []
        y_closed: List[float] = []
        for h, d, is_open in zip(hours, diffs, opens):
            if is_open:
                x_open.append(h); y_open.append(d)
                x_closed.append(h); y_closed.append(np.nan)
            else:
                x_closed.append(h); y_closed.append(d)
                x_open.append(h); y_open.append(np.nan)
        self._lines_open[tel].set_data(x_open, y_open)
        self._lines_closed[tel].set_data(x_closed, y_closed)

    def on_weather(self, hour, ts, msm, *, is_yesterday) -> None:
        if is_yesterday:
            return
        try:
            self._latest_wind_dir = float(msm['wind_dir_deg'])
        except (KeyError, TypeError, ValueError):
            return
        for tel in self.telescopes:
            self._maybe_append(tel, hour)

    def on_dome_state(self, tel, shutter_open) -> None:
        if tel not in self._latest_open:
            return
        self._latest_open[tel] = shutter_open
        self._maybe_append(tel, _hour_now_utc())

    def on_mount_az(self, tel, az_deg, hour) -> None:
        if tel not in self._latest_az:
            return
        self._latest_az[tel] = float(az_deg) % 360.0
        self._maybe_append(tel, hour)

    def on_midnight_rollover(self) -> None:
        for tel in self.telescopes:
            self._series[tel] = ([], [], [])
            self._refresh_lines(tel)


class _PerTelescopeScatterPanel(_Panel):
    """Common implementation for per-telescope time-series scatter panels.

    Subclasses populate ``self._series[tel]`` with (hour, value) pairs via
    one of the ``on_*`` hooks; this base handles axis setup, line creation
    and autoscaling.
    """

    y_min: Optional[float] = 0.0
    y_max: Optional[float] = None
    marker: str = 'o'
    line_style: str = '-'

    def __init__(self, main_window, telescopes: Sequence[str]) -> None:
        super().__init__()
        self.main_window = main_window
        self.telescopes = list(telescopes)
        self._series: Dict[str, Tuple[List[float], List[float]]] = {
            t: ([], []) for t in self.telescopes}
        self._lines: Dict[str, Any] = {}

    def init_axes(self, ax) -> None:
        super().init_axes(ax)
        if self.y_min is not None and self.y_max is not None:
            ax.set_ylim(self.y_min, self.y_max)
        for tel in self.telescopes:
            color = ck.telescope_color(self.main_window, tel)
            self._lines[tel], = ax.plot(
                [], [], f'{self.marker}{self.line_style}', color=color,
                markersize=2.6, linewidth=1.0, alpha=0.45,
                markeredgewidth=0, zorder=4, label=tel)

    def restamp_telescope_colors(self) -> None:
        for tel in self.telescopes:
            if tel in self._lines:
                self._lines[tel].set_color(ck.telescope_color(self.main_window, tel))

    def _append(self, tel: str, hour: float, value: float) -> None:
        if tel not in self._series:
            return
        hours, vals = self._series[tel]
        hours.append(hour); vals.append(value)
        if len(hours) > 4000:
            del hours[:1000]; del vals[:1000]
        self._lines[tel].set_data(hours, vals)
        if self.ax is not None and (self.y_min is None or self.y_max is None):
            self.ax.relim()
            self.ax.autoscale_view(scalex=False, scaley=True)

    def on_midnight_rollover(self) -> None:
        for tel in self.telescopes:
            self._series[tel] = ([], [])
            if tel in self._lines:
                self._lines[tel].set_data([], [])


class _FwhmPanel(_PerTelescopeScatterPanel):
    """FWHM in arc-seconds, sourced from ``tic.status.<tel>.fits.pipeline.faststat``.

    Mirrors halina's data extraction: ``raw.fwhm.fwhm_x``/``fwhm_y``
    averaged, multiplied by ``raw.header.SCALE`` (arcsec/px). Restricted
    to ``IMAGETYP == 'science'`` frames as halina does.
    """

    needs_faststat = True
    title = 'FWHM  [arcsec]'
    y_min = 0.0
    y_max = 8.0
    marker = 'o'
    line_style = ''  # markers only — frames arrive irregularly

    def on_faststat(self, tel, hour, raw) -> None:
        try:
            if raw['header'].get('IMAGETYP') != 'science':
                return
            fwhm = 0.5 * (float(raw['fwhm']['fwhm_x']) + float(raw['fwhm']['fwhm_y']))
            scale = float(raw['header']['SCALE'])
        except (KeyError, TypeError, ValueError):
            return
        if fwhm <= 0 or fwhm > 30 or scale <= 0:
            return
        self._append(tel, hour, fwhm * scale)


class _QualityPanel(_PerTelescopeScatterPanel):
    """Star-presence quality ratio, sourced from ``pipeline.zdf``.

    Field path mirrors halina master:
    ``zdf.stars_presence.ratio_no_bkg["1"]`` × 100.
    """

    needs_zdf = True
    title = 'Quality  [%]'
    y_min = 0.0
    y_max = 100.0
    marker = 'o'
    line_style = ''

    def on_zdf(self, tel, hour, content) -> None:
        try:
            ratio = float(content['stars_presence']['ratio_no_bkg']['1'])
        except (KeyError, TypeError, ValueError):
            return
        self._append(tel, hour, ratio * 100.0)


class _PhotZeroPanel(_Panel):
    """Photometric zero point, sourced from ``tic.status.<tel>.zero_monitor.lc``.

    Markers carry telescope colour as fill and filter colour as edge —
    halina convention.
    """

    needs_zero_monitor = True
    title = 'Photometric Zero  [mag]'

    def __init__(self, main_window, telescopes: Sequence[str]) -> None:
        super().__init__()
        self.main_window = main_window
        self.telescopes = list(telescopes)
        self._series: Dict[str, Tuple[List[float], List[float], List[str]]] = {
            t: ([], [], []) for t in self.telescopes
        }
        self._scatters: Dict[str, Any] = {}

    def init_axes(self, ax) -> None:
        super().init_axes(ax)
        for tel in self.telescopes:
            color = ck.telescope_color(self.main_window, tel)
            self._scatters[tel] = ax.scatter([], [], s=10, c=color,
                                             alpha=0.50, edgecolors='none',
                                             linewidths=0, zorder=4, label=tel)

    def restamp_telescope_colors(self) -> None:
        for tel in self.telescopes:
            if tel in self._scatters:
                self._scatters[tel].set_color(
                    ck.telescope_color(self.main_window, tel))

    def on_zero_monitor(self, tel, hour, data) -> None:
        if tel not in self._series:
            return
        try:
            zp = float(data['zero_value'])
        except (KeyError, TypeError, ValueError):
            return
        if not math.isfinite(zp):
            return
        flt = str(data.get('filter', '') or '')
        hours, zps, fls = self._series[tel]
        hours.append(hour); zps.append(zp); fls.append(flt)
        if len(hours) > 4000:
            del hours[:1000]; del zps[:1000]; del fls[:1000]
        edge = [ck.PHOT_FILTER_COLORS.get(f, '#888888') for f in fls]
        self._scatters[tel].set_offsets(np.column_stack((hours, zps)))
        self._scatters[tel].set_edgecolors(edge)
        self._rescale_y()

    def _rescale_y(self) -> None:
        if self.ax is None:
            return
        all_zps: List[float] = []
        for hours, zps, _ in self._series.values():
            all_zps.extend(zps)
        if not all_zps:
            return
        lo, hi = min(all_zps), max(all_zps)
        pad = max(0.2, 0.1 * (hi - lo))
        self.ax.set_ylim(lo - pad, hi + pad)

    def on_midnight_rollover(self) -> None:
        for tel in self.telescopes:
            self._series[tel] = ([], [], [])
            if tel in self._scatters:
                self._scatters[tel].set_offsets(np.zeros((0, 2)))


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _hour_now_utc() -> float:
    n = datetime.datetime.now(datetime.timezone.utc)
    return n.hour + n.minute / 60.0 + n.second / 3600.0


def _today_midnight_utc() -> datetime.datetime:
    n = datetime.datetime.now(datetime.timezone.utc)
    return datetime.datetime(n.year, n.month, n.day, tzinfo=datetime.timezone.utc)


# ----------------------------------------------------------------------------
# Main page widget
# ----------------------------------------------------------------------------

class WeatherDataWidget(QWidget):

    DEFAULT_CHARTS: Tuple[str, ...] = ('wind', 'humidity_pressure', 'temperature')
    KNOWN_CHARTS = frozenset({
        'wind', 'humidity_pressure', 'temperature',
        'dome_wind_az', 'fwhm', 'quality', 'phot_zero',
    })

    def __init__(self, main_window, subject: str = 'telemetry.weather.davis',
                 vertical_screen: bool = False,
                 charts: Optional[Sequence[str]] = None,
                 dome_danger_zone_deg: float = 30.0,
                 **kwargs) -> None:
        super().__init__()
        self.main_window = main_window
        self.weather_subject = subject
        self.vertical = bool(vertical_screen)
        self.dome_danger_zone_deg = float(dome_danger_zone_deg)
        self.chart_keys = self._resolve_charts(charts)
        self.panels: List[_Panel] = self._build_panels()
        self._init_ui()
        QtCore.QTimer.singleShot(0, self.async_init)
        logger.info(f"WeatherDataWidget init done — charts={self.chart_keys}")

    # ---- chart selection ----------------------------------------------------

    def _resolve_charts(self, requested: Optional[Sequence[str]]) -> List[str]:
        if not requested:
            return list(self.DEFAULT_CHARTS)
        out: List[str] = []
        for key in requested:
            if key in self.KNOWN_CHARTS:
                if key not in out:
                    out.append(key)
            else:
                logger.warning(f"Unknown weather chart '{key}' — skipped.")
        if 'wind' not in out:
            out.insert(0, 'wind')  # wind is permanent
        return out

    def _build_panels(self) -> List[_Panel]:
        telescopes = list(getattr(self.main_window, 'telescope_names', []))
        panels: List[_Panel] = []
        for key in self.chart_keys:
            if key == 'wind':
                panels.append(_WindPanel())
            elif key == 'humidity_pressure':
                panels.append(_HumidityPressurePanel())
            elif key == 'temperature':
                panels.append(_SimpleSeriesPanel(
                    measurement_key='temperature_C',
                    y_label='Temperature  [°C]',
                    today_color=ck.COLOR_TEMPERATURE,
                    reject_above=60.0, reject_below=-30.0,
                    smooth_window=5,  # 5 min — temp can swing faster than humid/pres
                    overlay_unit='°C',
                ))
            elif key == 'dome_wind_az' and telescopes:
                panels.append(_DomeWindAzPanel(self.main_window, telescopes,
                                               self.dome_danger_zone_deg))
            elif key == 'fwhm' and telescopes:
                panels.append(_FwhmPanel(self.main_window, telescopes))
            elif key == 'quality' and telescopes:
                panels.append(_QualityPanel(self.main_window, telescopes))
            elif key == 'phot_zero' and telescopes:
                panels.append(_PhotZeroPanel(self.main_window, telescopes))
        return panels

    # ---- UI -----------------------------------------------------------------

    def _init_ui(self) -> None:
        self.layout_root = QVBoxLayout(self)
        self.layout_root.setContentsMargins(2, 2, 2, 2)
        self.layout_root.setSpacing(2)

        # Compact single-line astronomical context. The wind/T/hum readout
        # that used to live on a sibling QLabel is now rendered as
        # translucent overlays directly on the matching chart panels.
        label_font = QtGui.QFont('Arial', 14 if self.vertical else 13)
        self.label_ephem = QLabel('ephem')
        self.label_ephem.setStyleSheet(
            "background-color: #2a2a2a; color: #e0e0e0; padding: 2px 8px; border-radius: 4px;"
        )
        self.label_ephem.setFont(label_font)
        self.label_ephem.setMaximumHeight(28)

        self.figure = Figure(constrained_layout=False)
        ck.style_figure(self.figure)
        self.canvas = FigureCanvas(self.figure)

        if self.vertical:
            hbox = QHBoxLayout()
            hbox.addWidget(self.label_ephem, 1)
            hbox.addWidget(self.canvas, 9)
            self.layout_root.addLayout(hbox)
        else:
            self.layout_root.addWidget(self.label_ephem)
            self.layout_root.addWidget(self.canvas, 1)

        # Build axes
        axes = ck.make_stacked_axes(self.figure, len(self.panels))
        for panel, ax in zip(self.panels, axes):
            panel.init_axes(ax)
        if axes:
            ck.format_hour_xaxis(axes[-1])
        self.canvas.draw_idle()

        self._update_ephem()

    # ---- async init ---------------------------------------------------------

    @asyncSlot()
    async def async_init(self):
        await create_task(self._color_resolver(), 'weather_color_resolver')
        await create_task(self._weather_history_loop(), 'weather_history_reader')
        try:
            await self.main_window.run_reader(
                clb=self._weather_status_callback,
                subject=self.weather_subject, deliver_policy='last',
            )
        except Exception as e:
            logger.warning(f"Failed to register weather status reader: {e}")

        telescopes = list(getattr(self.main_window, 'telescope_names', []))
        if any(p.needs_dome_state for p in self.panels) and telescopes:
            for tel in telescopes:
                await create_task(self._dome_status_loop(tel), f'weather_dome_{tel}')
        if any(p.needs_mount_az for p in self.panels) and telescopes:
            for tel in telescopes:
                await create_task(self._mount_az_loop(tel), f'weather_mount_az_{tel}')
        if any(p.needs_faststat for p in self.panels) and telescopes:
            for tel in telescopes:
                await create_task(self._pipeline_faststat_loop(tel),
                                  f'weather_faststat_{tel}')
        if any(p.needs_zdf for p in self.panels) and telescopes:
            for tel in telescopes:
                await create_task(self._pipeline_zdf_loop(tel),
                                  f'weather_zdf_{tel}')
        if any(p.needs_zero_monitor for p in self.panels) and telescopes:
            for tel in telescopes:
                await create_task(self._zero_monitor_loop(tel),
                                  f'weather_zerolc_{tel}')

    # ---- readers ------------------------------------------------------------

    async def _color_resolver(self):
        """One-shot watcher: re-stamp telescope colours once nats_cfg arrives.

        Panels are constructed synchronously during MainWindow.__init__ —
        before MainWindow.async_init has finished its single_read on
        ``tic.config.observatory`` — so the first paint uses
        chart_kit fallback colours. This task polls until the live config
        is available, then re-applies the published ``style.color`` to
        every per-telescope artist exactly once.
        """
        import asyncio
        for _ in range(120):  # ~60 s of patience, then give up
            cfg = getattr(self.main_window, 'nats_cfg', None) or {}
            if cfg.get('config', {}).get('telescopes'):
                break
            await asyncio.sleep(0.5)
        else:
            logger.warning('nats_cfg never arrived — sticking with fallback colours')
            return
        restamped = 0
        for p in self.panels:
            fn = getattr(p, 'restamp_telescope_colors', None)
            if callable(fn):
                fn()
                restamped += 1
        if restamped:
            self.canvas.draw_idle()
            logger.info(f'Restamped telescope colours on {restamped} panel(s)')

    async def _weather_history_loop(self):
        msg = Messenger()
        today_midnight = _today_midnight_utc()
        yesterday_midnight = today_midnight - datetime.timedelta(days=1)
        rdr = msg.get_reader(self.weather_subject, deliver_policy='all')
        logger.info(f"Subscribed to {self.weather_subject} (history)")
        async for data, meta in rdr:
            try:
                ts_meta = dt_from_array(meta['ts'])
                if ts_meta is not None and ts_meta < yesterday_midnight:
                    continue
            except (LookupError, ValueError, TypeError):
                pass
            try:
                now = datetime.datetime.now(datetime.timezone.utc)
                if now.date() > today_midnight.date():
                    today_midnight = _today_midnight_utc()
                    yesterday_midnight = today_midnight - datetime.timedelta(days=1)
                    for p in self.panels:
                        p.on_midnight_rollover()
                ts = dt_ensure_datetime(data['ts'])
                msm = data['measurements']
                hour = ts.hour + ts.minute / 60.0 + ts.second / 3600.0
                is_yesterday = ts < today_midnight
                for p in self.panels:
                    p.on_weather(hour, ts, msm, is_yesterday=is_yesterday)
                self.canvas.draw_idle()
            except (LookupError, TypeError, ValueError):
                continue

    async def _weather_status_callback(self, data, meta) -> bool:
        try:
            msm = data['measurements']
            wind = float(msm['wind_10min_ms'])
            temp = float(msm['temperature_C'])
            hum = int(msm['humidity'])
        except (KeyError, TypeError, ValueError):
            return True
        if (ck.WIND_WARN_MS <= wind < ck.WIND_DANGER_MS) or hum > 70:
            alert = '#f6ce46'
        elif wind >= ck.WIND_DANGER_MS or hum > 75 or temp < 0:
            alert = '#ea4d3d'
        else:
            alert = ck.FG_TEXT
        for p in self.panels:
            p.on_live_summary(msm, alert)
        self.canvas.draw_idle()
        return True

    async def _dome_status_loop(self, tel: str):
        try:
            r = get_reader(f'tic.status.{tel}.dome.shutterstatus', deliver_policy='last')
            async for data, meta in r:
                try:
                    val = data['measurements'][f'{tel}.dome.shutterstatus']
                except (KeyError, TypeError):
                    continue
                # 0 = OPEN per pages/telescopes.py — anything else is "not open"
                shutter_open = (val == 0) if val is not None else None
                for p in self.panels:
                    p.on_dome_state(tel, shutter_open)
                self.canvas.draw_idle()
        except Exception as e:
            logger.warning(f"dome status reader [{tel}] failed: {e}")

    async def _mount_az_loop(self, tel: str):
        try:
            r = get_reader(f'tic.telemetry.{tel}.mount.azimuth', deliver_policy='last')
            async for data, meta in r:
                try:
                    msm = data['measurements']
                    az = float(next(iter(msm.values())))
                except (KeyError, TypeError, ValueError, StopIteration):
                    continue
                hour = _hour_now_utc()
                for p in self.panels:
                    p.on_mount_az(tel, az, hour)
                self.canvas.draw_idle()
        except Exception as e:
            logger.warning(f"mount.azimuth reader [{tel}] failed: {e}")

    async def _pipeline_faststat_loop(self, tel: str):
        try:
            r = get_reader(f'tic.status.{tel}.fits.pipeline.faststat',
                           deliver_policy='all')
            async for data, meta in r:
                raw = data.get('raw') if isinstance(data, dict) else None
                if not raw:
                    continue
                hour = (_hour_from_iso((raw.get('header') or {}).get('DATE-OBS'))
                        or _hour_from_meta(meta)
                        or _hour_now_utc())
                for p in self.panels:
                    p.on_faststat(tel, hour, raw)
                self.canvas.draw_idle()
        except Exception as e:
            logger.warning(f"pipeline.faststat reader [{tel}] failed: {e}")

    async def _pipeline_zdf_loop(self, tel: str):
        try:
            r = get_reader(f'tic.status.{tel}.fits.pipeline.zdf',
                           deliver_policy='all')
            async for data, meta in r:
                content = data.get('zdf') if isinstance(data, dict) else None
                if not content:
                    continue
                hour = (_hour_from_iso((content.get('header') or {}).get('DATE-OBS'))
                        or _hour_from_meta(meta)
                        or _hour_now_utc())
                for p in self.panels:
                    p.on_zdf(tel, hour, content)
                self.canvas.draw_idle()
        except Exception as e:
            logger.warning(f"pipeline.zdf reader [{tel}] failed: {e}")

    async def _zero_monitor_loop(self, tel: str):
        try:
            r = get_reader(f'tic.status.{tel}.zero_monitor.lc',
                           deliver_policy='all')
            async for data, meta in r:
                if not isinstance(data, dict):
                    continue
                hour = (_hour_from_oca_jd(data.get('oca_jd'))
                        or _hour_from_meta(meta)
                        or _hour_now_utc())
                for p in self.panels:
                    p.on_zero_monitor(tel, hour, data)
                self.canvas.draw_idle()
        except Exception as e:
            logger.warning(f"zero_monitor.lc reader [{tel}] failed: {e}")

    # ---- ephemeris label ----------------------------------------------------

    def _update_ephem(self):
        text, sun_alt = _ephemeris_text(self.vertical)
        if sun_alt > -2.0:
            colour = '#7a3a3a'
        elif sun_alt > -18.0:
            colour = '#7a6a20'
        else:
            colour = '#2a4a30'
        self.label_ephem.setStyleSheet(
            f"background-color: {colour}; color: #f0f0f0; "
            "padding: 4px 8px; border-radius: 4px;"
        )
        self.label_ephem.setText(text)
        QtCore.QTimer.singleShot(1000, self._update_ephem)


def _hour_from_iso(iso: Optional[str]) -> Optional[float]:
    if not iso:
        return None
    try:
        dt = datetime.datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return None
    return dt.hour + dt.minute / 60.0 + dt.second / 3600.0


def _hour_from_meta(meta) -> Optional[float]:
    try:
        ts = dt_from_array(meta['ts'])
    except (LookupError, TypeError, ValueError):
        return None
    if ts is None:
        return None
    return ts.hour + ts.minute / 60.0 + ts.second / 3600.0


def _hour_from_oca_jd(oca_jd) -> Optional[float]:
    """Convert oca_jd (pyaraucaria-internal) → fractional UTC hour, if possible.

    Uses pyaraucaria when available (matches halina's exact conversion); else
    returns None and the caller falls back to ``meta.ts``.
    """
    if oca_jd is None:
        return None
    try:
        from pyaraucaria.date import get_jd_from_oca_jd  # type: ignore
    except ImportError:
        return None
    try:
        jd = float(get_jd_from_oca_jd(oca_jd=oca_jd))
        dt = AstropyTime(jd, format='jd', scale='utc').to_datetime()
    except (ValueError, TypeError):
        return None
    return dt.hour + dt.minute / 60.0 + dt.second / 3600.0


widget_class = WeatherDataWidget
