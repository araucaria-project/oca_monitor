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
import math as _math
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

import ephem
import numpy as np
from PyQt6 import QtCore, QtGui  # imported before matplotlib so qt_compat picks PyQt6
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget
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

def _ephemeris_parts() -> Tuple[str, float, str]:
    """Return ``(local_time_hms, sun_alt_deg, utc_hms)`` for the OCM site."""
    obs = ephem.Observer()
    obs.lon = '-70.201266'
    obs.lat = '-24.598616'
    obs.elev = 2800
    obs.pressure = 730
    ut_full = time.strftime('%Y/%m/%d %H:%M:%S', time.gmtime())
    ut = time.strftime('%H:%M:%S', time.gmtime())
    lt = time.strftime('%H:%M:%S', time.localtime())
    obs.date = ut_full
    sun = ephem.Sun()
    sun.compute(obs)
    parts = str(sun.alt).split(':')
    deg = float(parts[0])
    minutes = float(parts[1]) / 60.0
    sun_alt = deg + minutes if not str(sun.alt).startswith('-') else deg - minutes
    return lt, sun_alt, ut


# ----------------------------------------------------------------------------
# Panels
# ----------------------------------------------------------------------------

class _Panel:
    """Base class for one row of the squeezed chart stack."""

    title: str = ''
    title_side: str = 'left'   # ``'left'`` or ``'right'`` — pin the inline title pill

    needs_weather_history: bool = False
    needs_power_history: bool = False
    needs_faststat: bool = False
    needs_zdf: bool = False
    needs_zero_monitor: bool = False
    needs_dome_state: bool = False
    needs_mount_az: bool = False

    # Which 'last'-callback feed this panel reads its overlay from:
    # ``'weather'`` → ``telemetry.weather.davis``;
    # ``'power'`` → ``telemetry.power.data-manager``;
    # ``None`` → no live overlay.
    live_subject_kind: Optional[str] = None

    def __init__(self) -> None:
        self.ax = None  # type: Optional[Any]
        self._overlay = None
        self._dirty = False

    def init_axes(self, ax) -> None:
        self.ax = ax
        ax.set_zorder(2)
        if self.title:
            ck.inline_title(ax, self.title, side=self.title_side)

    def render(self) -> None:
        """Pull data → smooth → set_data → autoscale.

        Subclasses doing heavy per-sample work override this and only
        flip ``self._dirty`` from their data hooks. The widget calls
        ``render()`` on dirty panels at the throttled redraw rate, so
        even a flood of NATS history replays costs O(N) per render
        rather than O(N²) cumulative."""
        pass

    # Live-value overlay — subclasses opt in by calling _add_overlay() in
    # init_axes and overriding format_overlay().
    def _add_overlay(self, ax, **kwargs) -> None:
        self._overlay = ck.big_overlay(ax, **kwargs)

    def format_overlay(self, msm: dict) -> Optional[str]:
        return None

    def alert_color(self, msm: dict) -> Optional[str]:
        """Return ``COLOR_WARN`` / ``COLOR_DANGER`` if an alert applies, else ``None``."""
        return None

    def on_live_summary(self, msm: dict) -> None:
        if self._overlay is None:
            return
        try:
            text = self.format_overlay(msm)
        except (KeyError, TypeError, ValueError):
            text = None
        if text is None:
            return
        self._overlay.set_text(text)
        self._overlay.set_color(self.alert_color(msm) or ck.FG_TEXT)

    # Default no-ops; subclasses override.
    def on_weather(self, hour: float, ts: datetime.datetime, msm: dict,
                   *, is_yesterday: bool) -> None: ...

    def on_power(self, hour: float, ts: datetime.datetime, msm: dict,
                 *, is_yesterday: bool) -> None: ...

    def on_midnight_rollover(self) -> None:
        """Today→yesterday at UTC midnight. Override on weather/power panels."""
        ...

    def on_session_reset(self) -> None:
        """Wipe panel state for a new observing session. Override on
        pipeline-driven panels (FWHM, Quality, PhotZero); the widget
        invokes this at OCM sunset so each night starts fresh."""
        ...

    def on_faststat(self, tel: str, hour: float, raw: dict) -> None: ...

    def on_zdf(self, tel: str, hour: float, content: dict) -> None: ...

    def on_zero_monitor(self, tel: str, hour: float, data: dict) -> None: ...

    def on_dome_state(self, tel: str, shutter_open: Optional[bool]) -> None: ...

    def on_mount_az(self, tel: str, az_deg: float, hour: float) -> None: ...


class _SimpleSeriesPanel(_Panel):
    """Today + yesterday line panel — wind, temperature, humidity, etc."""

    needs_weather_history = True

    live_subject_kind = 'weather'

    def __init__(self, *, measurement_key: str, y_label: str,
                 today_color: str,
                 y_min: Optional[float] = None, y_max: Optional[float] = None,
                 reject_above: Optional[float] = None,
                 reject_below: Optional[float] = None,
                 zone_drawer=None,
                 smooth_window: int = 1,
                 overlay_unit: Optional[str] = None,
                 overlay_format: str = '{:.1f}',
                 warn_above: Optional[float] = None,
                 danger_above: Optional[float] = None,
                 warn_below: Optional[float] = None,
                 danger_below: Optional[float] = None) -> None:
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
        self.warn_above = warn_above
        self.danger_above = danger_above
        self.warn_below = warn_below
        self.danger_below = danger_below
        self._today_x: List[float] = []
        self._today_y: List[float] = []
        self._yesterday_x: List[float] = []
        self._yesterday_y: List[float] = []
        self._line_today = None
        self._line_yesterday = None

    def alert_color(self, msm):
        try:
            v = float(msm[self.measurement_key])
        except (KeyError, TypeError, ValueError):
            return None
        if self.danger_above is not None and v >= self.danger_above:
            return ck.COLOR_DANGER
        if self.danger_below is not None and v <= self.danger_below:
            return ck.COLOR_DANGER
        if self.warn_above is not None and v >= self.warn_above:
            return ck.COLOR_WARN
        if self.warn_below is not None and v <= self.warn_below:
            return ck.COLOR_WARN
        return None

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

    def render(self) -> None:
        if not self._dirty:
            return
        max_pts = 400
        if self._line_today is not None and self._today_x:
            x, y = ck.decimate_xy(self._today_x, self._today_y, max_points=max_pts)
            self._line_today.set_data(x, y)
        if self._line_yesterday is not None and self._yesterday_x:
            x, y = ck.decimate_xy(self._yesterday_x, self._yesterday_y,
                                  max_points=max_pts)
            self._line_yesterday.set_data(x, y)
        if self.y_min is None and self.y_max is None and self.ax is not None:
            self.ax.relim()
            self.ax.autoscale_view(scalex=False, scaley=True)
        self._dirty = False

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
        self._dirty = True

    def on_midnight_rollover(self) -> None:
        self._yesterday_x, self._yesterday_y = self._today_x, self._today_y
        self._today_x, self._today_y = [], []
        self._dirty = True


class _WindPanel(_SimpleSeriesPanel):
    """Wind speed + direction-arrow strip along the bottom."""

    def __init__(self, *, warn_ms: float = ck.WIND_WARN_MS,
                 danger_ms: float = ck.WIND_DANGER_MS) -> None:
        super().__init__(
            measurement_key='wind_10min_ms',
            y_label='Wind  [m/s]',
            today_color=ck.COLOR_TODAY,
            y_min=0.0, y_max=None,
            reject_above=danger_ms * 3.0,
            reject_below=0.0,
            zone_drawer=ck.wind_zone_bands,
            warn_above=warn_ms,
            danger_above=danger_ms,
        )
        self._dir_x: List[float] = []
        self._dir_d: List[float] = []
        self._quiver = None

    def init_axes(self, ax) -> None:
        super().init_axes(ax)
        ax.set_ylim(0, max(15.0, self.danger_above * 1.4))
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
        centers, means = ck.bin_directions(self._dir_x, self._dir_d, n_bins=24)
        if not centers:
            return
        u, v = ck.compass_to_uv(means, flow_to=True)
        # Slightly higher than the panel floor; short shaft + chunky head
        # reads cleanly even on top of the wind speed line.
        y_lo, y_hi = ax.get_ylim()
        y_arrow = y_lo + 0.10 * (y_hi - y_lo)
        ys = np.full_like(u, y_arrow, dtype=float)
        if self._quiver is not None:
            try:
                self._quiver.remove()
            except (ValueError, AttributeError):
                pass
        # Narrow elongated triangle so the heading reads at a glance
        # (headlength > headwidth ⇒ pointy, not isoceles-blunt).
        self._quiver = ax.quiver(
            centers, ys, u, v,
            angles='uv', scale_units='inches', scale=5.0,
            width=0.0085, headwidth=3.2, headlength=5.5, headaxislength=4.8,
            color=ck.COLOR_WIND_ARROW, alpha=0.65, zorder=5, pivot='middle',
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
    live_subject_kind = 'weather'

    title = 'Humidity  [%]'
    title_right = 'Pressure  [hPa]'

    HUM_SMOOTH = 11      # ~11 minutes at 1 Hz Davis cadence
    PRES_SMOOTH = 21     # ~20 minutes — pressure changes very slowly

    def __init__(self, *, warn_pct: float = 70.0,
                 danger_pct: float = 75.0) -> None:
        super().__init__()
        self.warn_pct = float(warn_pct)
        self.danger_pct = float(danger_pct)
        self.draw_max_points = 400
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
        # Right-hand title pill on parent axes so live overlays paint over it.
        ck.inline_title(ax, self.title_right, side='right',
                        color=ck.COLOR_PRESSURE)
        # Live overlay split between the two metrics, both rendered in
        # the parent axes so colour/alpha logic stays unified.
        self._overlay_h = ck.big_overlay(ax, x=0.99, y=0.72, color=ck.COLOR_HUMIDITY)
        self._overlay_p = ck.big_overlay(ax, x=0.99, y=0.32, color=ck.COLOR_PRESSURE)

    def alert_color(self, msm):
        try:
            hum = float(msm['humidity'])
        except (KeyError, TypeError, ValueError):
            return None
        if hum >= self.danger_pct:
            return ck.COLOR_DANGER
        if hum >= self.warn_pct:
            return ck.COLOR_WARN
        return None

    def on_live_summary(self, msm) -> None:
        try:
            hum = int(msm['humidity'])
            pres = float(msm['pressure_Pa'])
            if pres > 10000:
                pres = pres / 100.0
        except (KeyError, TypeError, ValueError):
            return
        col_h = self.alert_color(msm) or ck.COLOR_HUMIDITY
        if self._overlay_h is not None:
            self._overlay_h.set_text(f"{hum} %")
            self._overlay_h.set_color(col_h)
        if self._overlay_p is not None:
            self._overlay_p.set_text(f"{pres:.0f} hPa")

    def _bin(self, x, y, max_pts: int):
        if not x:
            return [], []
        return ck.decimate_xy(x, y, max_points=max_pts)

    def render(self) -> None:
        if not self._dirty or self.ax is None:
            return
        max_pts = self.draw_max_points
        # Humidity (left axis)
        if self._line_h_today is not None:
            x, y = self._bin(self._h_today_x, self._h_today_y, max_pts)
            self._line_h_today.set_data(x, y)
        if self._line_h_yest is not None:
            x, y = self._bin(self._h_yest_x, self._h_yest_y, max_pts)
            self._line_h_yest.set_data(x, y)
        # Humidity fill (recreated each render — fill_between has no set_data)
        if self._fill_h_today is not None:
            try:
                self._fill_h_today.remove()
            except (ValueError, AttributeError):
                pass
            self._fill_h_today = None
        if self._h_today_x:
            x, y = self._bin(self._h_today_x, self._h_today_y, max_pts)
            self._fill_h_today = self.ax.fill_between(
                x, 0, y, color=ck.COLOR_HUMIDITY, alpha=0.18, linewidth=0, zorder=3)
        # Pressure (right axis)
        if self._line_p_today is not None:
            x, y = self._bin(self._p_today_x, self._p_today_y, max_pts)
            self._line_p_today.set_data(x, y)
        if self._line_p_yest is not None:
            x, y = self._bin(self._p_yest_x, self._p_yest_y, max_pts)
            self._line_p_yest.set_data(x, y)
        if self.ax_p is not None:
            self.ax_p.relim()
            self.ax_p.autoscale_view(scalex=False, scaley=True)
        self._dirty = False

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
            self._dirty = True
        if pres is not None and 600.0 < pres < 1100.0:
            if is_yesterday:
                self._p_yest_x.append(hour); self._p_yest_y.append(pres)
            else:
                self._p_today_x.append(hour); self._p_today_y.append(pres)
            self._dirty = True

    def on_midnight_rollover(self) -> None:
        self._h_yest_x, self._h_yest_y = self._h_today_x, self._h_today_y
        self._p_yest_x, self._p_yest_y = self._p_today_x, self._p_today_y
        self._h_today_x, self._h_today_y = [], []
        self._p_today_x, self._p_today_y = [], []
        self._dirty = True


class _PowerPanel(_Panel):
    """Battery SOC (area, left axis) + Solar / Load (right axis).

    Stream: ``telemetry.power.data-manager``
    Fields read:
      - ``state_of_charge`` (% 0-100) — battery
      - ``pv_power`` (W) — solar generation; ``-2147483648`` is the
        modbus int32-min sentinel meaning "no reading"
      - ``battery_charge`` (W) — power flowing INTO the battery
      - ``battery_discharge`` (W) — power flowing OUT of the battery

    Site load (consumption) is derived from the power balance:
      ``load = pv + battery_discharge − battery_charge``
    Plotted as a negative number on the right axis so the chart reads
    like a balance sheet (sources above zero, sinks below).
    """

    needs_power_history = True
    live_subject_kind = 'power'

    title = 'Battery  [%]'
    title_right = 'Solar / Load  [W]'

    # ``telemetry.power.data-manager`` ticks at ~5 s/sample (~12/min); window
    # sized so the chart breathes at minutes-scale, not flickers per sample.
    SOC_SMOOTH = 60   # ~5 min
    KW_SMOOTH = 60    # ~5 min

    # ``pv_power`` / battery flow sanity bounds; anything outside is treated
    # as a sentinel/garbage reading and dropped.
    _POWER_W_MIN = -1_000_000.0
    _POWER_W_MAX = 1_000_000.0
    _SENTINEL_INT32_MIN = -2_147_483_648

    def __init__(self, *, soc_warn_pct: float = 30.0,
                 soc_danger_pct: float = 15.0) -> None:
        super().__init__()
        self.soc_warn_pct = float(soc_warn_pct)
        self.soc_danger_pct = float(soc_danger_pct)
        self.draw_max_points = 400
        self.ax_p = None
        self._soc_today_x: List[float] = []
        self._soc_today_y: List[float] = []
        self._soc_yest_x: List[float] = []
        self._soc_yest_y: List[float] = []
        self._pv_today_x: List[float] = []
        self._pv_today_y: List[float] = []
        self._pv_yest_x: List[float] = []
        self._pv_yest_y: List[float] = []
        self._load_today_x: List[float] = []
        self._load_today_y: List[float] = []
        self._load_yest_x: List[float] = []
        self._load_yest_y: List[float] = []
        self._line_soc_today = None
        self._line_soc_yest = None
        self._fill_soc_today = None
        self._line_pv_today = None
        self._line_pv_yest = None
        self._line_load_today = None
        self._line_load_yest = None
        self._overlay_soc = None
        self._overlay_kw = None

    def init_axes(self, ax) -> None:
        super().init_axes(ax)
        ax.set_ylim(0, 100)
        ax.set_yticks([0, 25, 50, 75, 100])
        ax.axhspan(0, self.soc_danger_pct, color=ck.COLOR_DANGER,
                   alpha=0.20, linewidth=0, zorder=0)
        ax.axhspan(self.soc_danger_pct, self.soc_warn_pct,
                   color=ck.COLOR_WARN, alpha=0.15, linewidth=0, zorder=0)
        self._line_soc_yest, = ax.plot([], [], '-', color=ck.COLOR_BATTERY,
                                       alpha=ck.YESTERDAY_ALPHA, linewidth=0.9,
                                       zorder=2)
        self._line_soc_today, = ax.plot([], [], '-', color=ck.COLOR_BATTERY,
                                        linewidth=1.3, zorder=4)

        # Twin axis: solar + load. Solar is plotted positive, load is
        # plotted as a negative number (so source/sink reads visually).
        self.ax_p = ax.twinx()
        self.ax_p.set_facecolor('none')
        self.ax_p.grid(False)
        self.ax_p.tick_params(axis='y', direction='in', length=4, pad=-4,
                              labelsize=9, colors=ck.COLOR_SOLAR)
        for label in self.ax_p.get_yticklabels():
            label.set_horizontalalignment('right')
        for side in ('top', 'bottom', 'left'):
            self.ax_p.spines[side].set_visible(False)
        self.ax_p.spines['right'].set_color(ck.COLOR_SOLAR)
        # Both PV and Load are plotted positive — y_min anchored at 0
        # so autoscale doesn't shift the baseline as data flows in.
        self.ax_p.set_ylim(bottom=0)
        self._line_pv_yest, = self.ax_p.plot([], [], '-', color=ck.COLOR_SOLAR,
                                             alpha=ck.YESTERDAY_ALPHA,
                                             linewidth=0.9, zorder=2)
        self._line_pv_today, = self.ax_p.plot([], [], '-', color=ck.COLOR_SOLAR,
                                              linewidth=1.3, zorder=4)
        self._line_load_yest, = self.ax_p.plot([], [], '-', color=ck.COLOR_LOAD,
                                               alpha=ck.YESTERDAY_ALPHA,
                                               linewidth=0.9, zorder=2)
        self._line_load_today, = self.ax_p.plot([], [], '-', color=ck.COLOR_LOAD,
                                                linewidth=1.3, zorder=4)
        # Right-hand title pill on parent axes (see _HumidityPressurePanel).
        ck.inline_title(ax, self.title_right, side='right',
                        color=ck.COLOR_SOLAR)
        self._overlay_soc = ck.big_overlay(ax, x=0.99, y=0.72, color=ck.COLOR_BATTERY)
        self._overlay_kw = ck.big_overlay(ax, x=0.99, y=0.32, color=ck.COLOR_SOLAR)

    # ---- helpers ----

    @classmethod
    def _valid_w(cls, v) -> Optional[float]:
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        if f == cls._SENTINEL_INT32_MIN or not (cls._POWER_W_MIN < f < cls._POWER_W_MAX):
            return None
        return f

    def _compute_balance(self, msm: dict):
        """Return ``(pv_w, load_w)`` (either may be None if missing)."""
        pv = self._valid_w(msm.get('pv_power'))
        bc = self._valid_w(msm.get('battery_charge'))
        bd = self._valid_w(msm.get('battery_discharge'))
        if bc is not None and bd is not None:
            load = (pv if pv is not None else 0.0) + bd - bc
        else:
            load = None
        return pv, load

    @staticmethod
    def _fmt_kw(w: Optional[float]) -> str:
        if w is None:
            return '—'
        kw = w / 1000.0
        return f"{kw:.1f}"

    # ---- alerts ----

    def alert_color(self, msm):
        try:
            soc = float(msm['state_of_charge'])
        except (KeyError, TypeError, ValueError):
            return None
        if soc <= self.soc_danger_pct:
            return ck.COLOR_DANGER
        if soc <= self.soc_warn_pct:
            return ck.COLOR_WARN
        return None

    # ---- redraws ----

    def _bin(self, x, y):
        if not x:
            return [], []
        return ck.decimate_xy(x, y, max_points=self.draw_max_points)

    def render(self) -> None:
        if not self._dirty or self.ax is None:
            return
        # SOC line + fill
        if self._line_soc_today is not None:
            x, y = self._bin(self._soc_today_x, self._soc_today_y)
            self._line_soc_today.set_data(x, y)
        if self._line_soc_yest is not None:
            x, y = self._bin(self._soc_yest_x, self._soc_yest_y)
            self._line_soc_yest.set_data(x, y)
        if self._fill_soc_today is not None:
            try:
                self._fill_soc_today.remove()
            except (ValueError, AttributeError):
                pass
            self._fill_soc_today = None
        if self._soc_today_x:
            x, y = self._bin(self._soc_today_x, self._soc_today_y)
            self._fill_soc_today = self.ax.fill_between(
                x, 0, y, color=ck.COLOR_BATTERY, alpha=0.18, linewidth=0, zorder=3)
        # Solar/Load lines
        for line, x_list, y_list in (
            (self._line_pv_today, self._pv_today_x, self._pv_today_y),
            (self._line_pv_yest, self._pv_yest_x, self._pv_yest_y),
            (self._line_load_today, self._load_today_x, self._load_today_y),
            (self._line_load_yest, self._load_yest_x, self._load_yest_y),
        ):
            if line is not None:
                x, y = self._bin(x_list, y_list)
                line.set_data(x, y)
        if self.ax_p is not None:
            # Compute the y range manually — ``set_ylim(bottom=0)`` in
            # init_axes disables the autoscaler on this axis, so neither
            # ``relim`` nor ``autoscale_view`` reliably re-bounds it as
            # data flows in.
            all_y: List[float] = []
            for ys in (self._pv_today_y, self._pv_yest_y,
                       self._load_today_y, self._load_yest_y):
                all_y.extend(ys)
            if all_y:
                top = max(all_y)
                if top <= 0:
                    top = 100.0
                self.ax_p.set_ylim(0, top * 1.10)
        self._dirty = False

    # ---- data hooks ----

    def on_power(self, hour, ts, msm, *, is_yesterday) -> None:
        try:
            soc = float(msm['state_of_charge'])
        except (KeyError, TypeError, ValueError):
            soc = None
        pv, load = self._compute_balance(msm)

        if soc is not None and 0.0 <= soc <= 100.0:
            (self._soc_yest_x if is_yesterday else self._soc_today_x).append(hour)
            (self._soc_yest_y if is_yesterday else self._soc_today_y).append(soc)
            self._dirty = True
        if pv is not None:
            (self._pv_yest_x if is_yesterday else self._pv_today_x).append(hour)
            (self._pv_yest_y if is_yesterday else self._pv_today_y).append(pv)
            self._dirty = True
        if load is not None:
            # Plot load as POSITIVE so it overlaps PV in the same region —
            # the chart stays compact and "consumption above zero" reads
            # naturally. The overlay text still negates the load value
            # for the source/sink convention.
            (self._load_yest_x if is_yesterday else self._load_today_x).append(hour)
            (self._load_yest_y if is_yesterday else self._load_today_y).append(load)
            self._dirty = True

    def on_live_summary(self, msm) -> None:
        try:
            soc = float(msm['state_of_charge'])
        except (KeyError, TypeError, ValueError):
            soc = None
        pv, load = self._compute_balance(msm)
        if self._overlay_soc is not None and soc is not None:
            self._overlay_soc.set_text(f"{soc:.0f} %")
            self._overlay_soc.set_color(self.alert_color(msm) or ck.COLOR_BATTERY)
        if self._overlay_kw is not None:
            # Format: "Solar / -Load kW" — load shown negative for the
            # source/sink convention.
            load_neg = (-load) if load is not None else None
            self._overlay_kw.set_text(
                f"{self._fmt_kw(pv)} / {self._fmt_kw(load_neg)} kW")

    def on_midnight_rollover(self) -> None:
        self._soc_yest_x, self._soc_yest_y = self._soc_today_x, self._soc_today_y
        self._pv_yest_x, self._pv_yest_y = self._pv_today_x, self._pv_today_y
        self._load_yest_x, self._load_yest_y = self._load_today_x, self._load_today_y
        self._soc_today_x, self._soc_today_y = [], []
        self._pv_today_x, self._pv_today_y = [], []
        self._load_today_x, self._load_today_y = [], []
        self._dirty = True


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

    def on_session_reset(self) -> None:
        for tel in self.telescopes:
            self._series[tel] = ([], [])
            if tel in self._lines:
                self._lines[tel].set_data([], [])


class _FwhmPanel(_PerTelescopeScatterPanel):
    """FWHM in arc-seconds, sourced from ``tic.status.<tel>.fits.pipeline.faststat``.

    Mirrors halina's data extraction: ``raw.fwhm.fwhm_x``/``fwhm_y``
    averaged, multiplied by ``raw.header.SCALE`` (arcsec/px). Restricted
    to ``IMAGETYP == 'science'`` frames as halina does.

    Has a live overlay that shows the most recent FWHM value regardless
    of which telescope produced it; the overlay text colour is the
    contributing telescope's ``style.color`` blended toward neutral
    text grey for legibility.
    """

    needs_faststat = True
    title = 'FWHM  [arcsec]'
    y_min = 0.5   # sub-arcsec is exceptional; tighten the floor so 1–3" reads clearly
    y_max = 3.0   # frames above 3" are exceptional — don't waste vertical space
    marker = 'o'
    line_style = ''  # markers only — frames arrive irregularly

    def __init__(self, main_window, telescopes: Sequence[str]) -> None:
        super().__init__(main_window, telescopes)
        self._latest_fwhm: Optional[float] = None
        self._latest_tel: Optional[str] = None

    title_side = 'right'   # title pinned where there's daytime gap, no data

    def init_axes(self, ax) -> None:
        super().init_axes(ax)
        self._overlay = ck.big_overlay(ax)

    def restamp_telescope_colors(self) -> None:
        super().restamp_telescope_colors()
        # Re-apply the blended colour to the overlay for whichever telescope
        # produced the latest sample, in case nats_cfg arrived afterwards.
        self._refresh_overlay()

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
        arcsec = fwhm * scale
        self._append(tel, hour, arcsec)
        self._latest_fwhm = arcsec
        self._latest_tel = tel
        self._refresh_overlay()

    def _refresh_overlay(self) -> None:
        if self._overlay is None or self._latest_fwhm is None:
            return
        self._overlay.set_text(f"{self._latest_fwhm:.2f} \"")
        if self._latest_tel is not None:
            tel_color = ck.telescope_color(self.main_window, self._latest_tel)
            # 30% blend toward neutral grey so the colour reads identifiably
            # but doesn't clash with the dark theme on saturated values.
            self._overlay.set_color(ck.blend_colors(tel_color, ck.FG_TEXT, 0.30))

    def on_session_reset(self) -> None:
        super().on_session_reset()
        self._latest_fwhm = None
        self._latest_tel = None
        if self._overlay is not None:
            self._overlay.set_text('')


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

    Each telescope's points are plotted as a translucent scatter (fill
    by telescope colour, edge by filter colour). On top of that, a
    bold gaussian-smoothed (sigma=3) curve combining points from ALL
    telescopes gives the "site-wide photometric quality" trend; its
    most-recent value is shown as a big translucent overlay coloured
    against the alert-band thresholds.

    Alert bands (zone shading on the panel background):
      * value ≥ ``GREEN_THRESHOLD`` (-0.05): photometric quality OK
      * ``YELLOW_THRESHOLD`` ≤ value < green: degraded
      * value < ``YELLOW_THRESHOLD`` (-0.10): poor / non-photometric
    """

    needs_zero_monitor = True
    title = 'Photometric Zero  [mag]'
    title_side = 'right'   # falls into the daytime gap, doesn't cover data

    GREEN_THRESHOLD = -0.05
    YELLOW_THRESHOLD = -0.10
    SMOOTH_SIGMA = 3.0
    Y_MAX = 0.05    # fixed scale top
    Y_MIN = -0.125  # fixed scale bottom — outliers clip rather than rescaling

    def __init__(self, main_window, telescopes: Sequence[str]) -> None:
        super().__init__()
        self.main_window = main_window
        self.telescopes = list(telescopes)
        self._series: Dict[str, Tuple[List[float], List[float], List[str]]] = {
            t: ([], [], []) for t in self.telescopes
        }
        self._scatters: Dict[str, Any] = {}
        self._line_smoothed = None
        self._overlay_avg = None

    def init_axes(self, ax) -> None:
        super().init_axes(ax)
        ax.set_ylim(self.Y_MIN, self.Y_MAX)
        # Threshold zone bands — drawn behind data so colour shifts read
        # as background quality state.
        ax.axhspan(self.GREEN_THRESHOLD, 1.0,
                   color=ck.COLOR_OK, alpha=0.10, linewidth=0, zorder=0)
        ax.axhspan(self.YELLOW_THRESHOLD, self.GREEN_THRESHOLD,
                   color=ck.COLOR_WARN, alpha=0.15, linewidth=0, zorder=0)
        ax.axhspan(-100.0, self.YELLOW_THRESHOLD,
                   color=ck.COLOR_DANGER, alpha=0.20, linewidth=0, zorder=0)
        for tel in self.telescopes:
            color = ck.telescope_color(self.main_window, tel)
            self._scatters[tel] = ax.scatter([], [], s=10, c=color,
                                             alpha=0.50, edgecolors='none',
                                             linewidths=0, zorder=4, label=tel)
        # Combined smoothed trend across all telescopes — kept translucent
        # so it reads as a "trend overlay" rather than competing visually
        # with the per-telescope scatter.
        self._line_smoothed, = ax.plot([], [], '-', color=ck.FG_TEXT,
                                       linewidth=1.4, alpha=0.45, zorder=6)
        self._overlay_avg = ck.big_overlay(ax)

    def restamp_telescope_colors(self) -> None:
        for tel in self.telescopes:
            if tel in self._scatters:
                self._scatters[tel].set_color(
                    ck.telescope_color(self.main_window, tel))

    def _color_for(self, value: float) -> str:
        if value >= self.GREEN_THRESHOLD:
            return ck.COLOR_OK
        if value >= self.YELLOW_THRESHOLD:
            return ck.COLOR_WARN
        return ck.COLOR_DANGER

    def on_zero_monitor(self, tel, hour, data) -> None:
        if tel not in self._series:
            return
        try:
            zp = float(data['zero_value'])
        except (KeyError, TypeError, ValueError):
            return
        if not _math.isfinite(zp):
            return
        flt = str(data.get('filter', '') or '')
        hours, zps, fls = self._series[tel]
        hours.append(hour); zps.append(zp); fls.append(flt)
        if len(hours) > 4000:
            del hours[:1000]; del zps[:1000]; del fls[:1000]
        edge = [ck.PHOT_FILTER_COLORS.get(f, '#888888') for f in fls]
        self._scatters[tel].set_offsets(np.column_stack((hours, zps)))
        self._scatters[tel].set_edgecolors(edge)
        self._refresh_smoothed_and_scale()

    def _refresh_smoothed_and_scale(self) -> None:
        all_x: List[float] = []
        all_y: List[float] = []
        for tel, (xs, ys, _) in self._series.items():
            all_x.extend(xs)
            all_y.extend(ys)
        if not all_x:
            return
        idx = np.argsort(np.asarray(all_x))
        x_sorted = np.asarray(all_x, dtype=float)[idx]
        y_sorted = np.asarray(all_y, dtype=float)[idx]
        y_smooth = ck.gaussian_filter1d(y_sorted, sigma=self.SMOOTH_SIGMA)
        if self._line_smoothed is not None:
            self._line_smoothed.set_data(x_sorted, y_smooth)
        if self._overlay_avg is not None and y_smooth.size:
            latest = float(y_smooth[-1])
            self._overlay_avg.set_text(f"{latest:+.3f} mag")
            self._overlay_avg.set_color(self._color_for(latest))

    def on_session_reset(self) -> None:
        for tel in self.telescopes:
            self._series[tel] = ([], [], [])
            if tel in self._scatters:
                self._scatters[tel].set_offsets(np.zeros((0, 2)))
        if self._line_smoothed is not None:
            self._line_smoothed.set_data([], [])
        if self._overlay_avg is not None:
            self._overlay_avg.set_text('')


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _hour_now_utc() -> float:
    n = datetime.datetime.now(datetime.timezone.utc)
    return n.hour + n.minute / 60.0 + n.second / 3600.0


def _today_midnight_utc() -> datetime.datetime:
    n = datetime.datetime.now(datetime.timezone.utc)
    return datetime.datetime(n.year, n.month, n.day, tzinfo=datetime.timezone.utc)


# OCM is at -70°W → local noon = 16:00 UTC. Use that as the night boundary
# for pipeline-derived panels (FWHM, Quality, Phot Zero) so they only show
# the current observing night and reset cleanly at local noon each day.
_OCM_LOCAL_NOON_UTC_HOUR = 16


def _current_night_start_utc() -> datetime.datetime:
    """Most recent OCM local-noon (16:00 UTC), as a tz-aware UTC datetime."""
    now = datetime.datetime.now(datetime.timezone.utc)
    local_noon = now.replace(hour=_OCM_LOCAL_NOON_UTC_HOUR,
                             minute=0, second=0, microsecond=0)
    if local_noon > now:
        local_noon -= datetime.timedelta(days=1)
    return local_noon


def _next_sunset_utc() -> datetime.datetime:
    """Next OCM sunset event, as a UTC datetime."""
    obs = ephem.Observer()
    obs.lon = '-70.201266'
    obs.lat = '-24.598616'
    obs.elev = 2800
    obs.pressure = 730
    obs.date = time.strftime('%Y/%m/%d %H:%M:%S', time.gmtime())
    return obs.next_setting(ephem.Sun()).datetime().replace(
        tzinfo=datetime.timezone.utc)


# ----------------------------------------------------------------------------
# Main page widget
# ----------------------------------------------------------------------------

class WeatherDataWidget(QWidget):

    DEFAULT_CHARTS: Tuple[str, ...] = ('wind', 'temperature', 'humidity_pressure', 'power')
    KNOWN_CHARTS = frozenset({
        'wind', 'humidity_pressure', 'temperature', 'power',
        'dome_wind_az', 'fwhm', 'quality', 'phot_zero',
    })

    def __init__(self, main_window, subject: str = 'telemetry.weather.davis',
                 power_subject: str = 'telemetry.power.data-manager',
                 vertical_screen: bool = False,
                 charts: Optional[Sequence[str]] = None,
                 dome_danger_zone_deg: float = 30.0,
                 wind_warn_ms: float = ck.WIND_WARN_MS,
                 wind_danger_ms: float = ck.WIND_DANGER_MS,
                 humidity_warn_pct: float = 70.0,
                 humidity_danger_pct: float = 75.0,
                 temperature_danger_c: float = 0.0,
                 soc_warn_pct: float = 30.0,
                 soc_danger_pct: float = 15.0,
                 **kwargs) -> None:
        super().__init__()
        self.main_window = main_window
        self.weather_subject = subject
        self.power_subject = power_subject
        self.vertical = bool(vertical_screen)
        self.dome_danger_zone_deg = float(dome_danger_zone_deg)
        self.wind_warn_ms = float(wind_warn_ms)
        self.wind_danger_ms = float(wind_danger_ms)
        self.humidity_warn_pct = float(humidity_warn_pct)
        self.humidity_danger_pct = float(humidity_danger_pct)
        self.temperature_danger_c = float(temperature_danger_c)
        self.soc_warn_pct = float(soc_warn_pct)
        self.soc_danger_pct = float(soc_danger_pct)
        self._draw_pending = False
        self._draw_interval_ms = 100
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
                panels.append(_WindPanel(warn_ms=self.wind_warn_ms,
                                         danger_ms=self.wind_danger_ms))
            elif key == 'humidity_pressure':
                panels.append(_HumidityPressurePanel(
                    warn_pct=self.humidity_warn_pct,
                    danger_pct=self.humidity_danger_pct))
            elif key == 'temperature':
                panels.append(_SimpleSeriesPanel(
                    measurement_key='temperature_C',
                    y_label='Temperature  [°C]',
                    today_color=ck.COLOR_TEMPERATURE,
                    reject_above=60.0, reject_below=-30.0,
                    smooth_window=5,  # 5 min — temp can swing faster than humid/pres
                    overlay_unit='°C',
                    danger_below=self.temperature_danger_c,
                ))
            elif key == 'power':
                panels.append(_PowerPanel(soc_warn_pct=self.soc_warn_pct,
                                          soc_danger_pct=self.soc_danger_pct))
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

        # Astronomical context strip — three independent labels, justified
        # left (LT) / centre (Sun alt) / right (UT). Background colour
        # encodes sun-altitude phase (day / twilight / night).
        label_font = QtGui.QFont('Arial', 22 if self.vertical else 19)
        label_font.setBold(True)
        self.label_ephem = QFrame()  # parent frame holds the alert colour
        self.label_ephem.setStyleSheet(
            "QFrame { background-color: #2a2a2a; border-radius: 4px; }"
            "QLabel { background-color: transparent; color: #e0e0e0; }"
        )
        self.label_lt = QLabel('LT'); self.label_lt.setFont(label_font)
        self.label_sun = QLabel('Sun'); self.label_sun.setFont(label_font)
        self.label_sun.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.label_ut = QLabel('UT'); self.label_ut.setFont(label_font)
        if self.vertical:
            ephem_layout = QVBoxLayout(self.label_ephem)
            for lbl in (self.label_lt, self.label_sun, self.label_ut):
                lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
                ephem_layout.addWidget(lbl)
        else:
            ephem_layout = QHBoxLayout(self.label_ephem)
            ephem_layout.setContentsMargins(10, 4, 10, 4)
            ephem_layout.addWidget(self.label_lt)
            ephem_layout.addStretch(1)
            ephem_layout.addWidget(self.label_sun)
            ephem_layout.addStretch(1)
            ephem_layout.addWidget(self.label_ut)

        self.figure = Figure(constrained_layout=False)
        ck.style_figure(self.figure)
        self.canvas = FigureCanvas(self.figure)

        if self.vertical:
            hbox = QHBoxLayout()
            hbox.addWidget(self.label_ephem, 1)
            hbox.addWidget(self.canvas, 9)
            # stretch=1 so the hbox (and thus the canvas) fills the panel
            # row that ``MainWindow`` allocates via ``panel_rows`` —
            # without this the row stretch is wasted because the widget
            # only claims its content's minimum height.
            self.layout_root.addLayout(hbox, 1)
        else:
            self.layout_root.addWidget(self.label_ephem)
            self.layout_root.addWidget(self.canvas, 1)

        self._build_panel_axes()
        self.canvas.draw_idle()

        self._update_ephem()

    # ---- async init ---------------------------------------------------------

    def _build_panel_axes(self) -> None:
        """Lay out panels: vertical-screen → 2-column grid (column-major
        stacks); horizontal → single column squeezed stack."""
        n = len(self.panels)
        if n == 0:
            return
        if self.vertical:
            n_cols = 2
            n_rows = max(1, _math.ceil(n / n_cols))
            raw = ck.make_grid_axes(self.figure, n_rows, n_cols)
            # Walk column-major so each column reads as its own
            # top-to-bottom stack of related charts.
            ordered = [raw[r * n_cols + c]
                       for c in range(n_cols)
                       for r in range(n_rows)]
            for panel, ax in zip(self.panels, ordered):
                panel.init_axes(ax)
            # Format the hour x-axis on the bottom of each column.
            for c in range(n_cols):
                idx = c * n_rows + (n_rows - 1)
                if idx < len(ordered):
                    ck.format_hour_xaxis(ordered[idx])
        else:
            axes = ck.make_stacked_axes(self.figure, n)
            for panel, ax in zip(self.panels, axes):
                panel.init_axes(ax)
            if axes:
                ck.format_hour_xaxis(axes[-1])

    def _schedule_draw(self) -> None:
        """Coalesce canvas redraws so a flood of NATS messages doesn't
        translate to a flood of repaints. Caps draws at ~10 Hz."""
        if self._draw_pending:
            return
        self._draw_pending = True
        QtCore.QTimer.singleShot(self._draw_interval_ms, self._do_draw)

    def _do_draw(self) -> None:
        self._draw_pending = False
        for p in self.panels:
            try:
                p.render()
            except Exception as e:
                logger.warning(f"panel render failed for {type(p).__name__}: {e}")
        self.canvas.draw_idle()

    def _schedule_next_sunset_reset(self) -> None:
        """Arm a one-shot timer for the next OCM sunset, at which point
        pipeline-driven panels (FWHM, Quality, PhotZero) wipe their
        buffers so each observing night starts fresh."""
        try:
            sunset = _next_sunset_utc()
        except Exception as e:
            logger.warning(f"Failed to compute next sunset; reset disabled: {e}")
            return
        now = datetime.datetime.now(datetime.timezone.utc)
        delay_s = max(60.0, (sunset - now).total_seconds())
        delay_ms = min(int(delay_s * 1000), 2_147_000_000)  # QTimer takes int32 ms
        logger.info(
            f"Next sunset reset scheduled at {sunset.isoformat()} "
            f"(in {delay_s/3600:.2f} h)")
        QtCore.QTimer.singleShot(delay_ms, self._do_sunset_reset)

    def _do_sunset_reset(self) -> None:
        n = 0
        for p in self.panels:
            # Only panels driven by per-night pipeline streams.
            if p.needs_faststat or p.needs_zdf or p.needs_zero_monitor:
                try:
                    p.on_session_reset()
                    n += 1
                except Exception as e:
                    logger.warning(
                        f"on_session_reset failed for {type(p).__name__}: {e}")
        if n:
            logger.info(f"Sunset reset: cleared {n} pipeline panel(s)")
            self._schedule_draw()
        # Re-arm for tomorrow.
        self._schedule_next_sunset_reset()

    @asyncSlot()
    async def async_init(self):
        await create_task(self._color_resolver(), 'weather_color_resolver')
        if any(p.needs_weather_history for p in self.panels):
            await create_task(self._weather_history_loop(), 'weather_history_reader')
        if any(p.needs_power_history for p in self.panels):
            await create_task(self._power_history_loop(), 'weather_power_reader')
        if any(p.live_subject_kind == 'weather' for p in self.panels):
            try:
                await self.main_window.run_reader(
                    clb=self._weather_status_callback,
                    subject=self.weather_subject, deliver_policy='last',
                )
            except Exception as e:
                logger.warning(f"Failed to register weather status reader: {e}")
        if any(p.live_subject_kind == 'power' for p in self.panels):
            try:
                await self.main_window.run_reader(
                    clb=self._power_status_callback,
                    subject=self.power_subject, deliver_policy='last',
                )
            except Exception as e:
                logger.warning(f"Failed to register power status reader: {e}")

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
        if any(p.needs_faststat or p.needs_zdf or p.needs_zero_monitor
               for p in self.panels):
            self._schedule_next_sunset_reset()

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
            self._schedule_draw()
            logger.info(f'Restamped telescope colours on {restamped} panel(s)')

    async def _weather_history_loop(self):
        await self._dual_day_history_loop(
            subject=self.weather_subject,
            hook=lambda p, hour, ts, msm, is_yesterday:
                p.on_weather(hour, ts, msm, is_yesterday=is_yesterday),
            panel_filter=lambda p: p.needs_weather_history,
        )

    async def _power_history_loop(self):
        await self._dual_day_history_loop(
            subject=self.power_subject,
            hook=lambda p, hour, ts, msm, is_yesterday:
                p.on_power(hour, ts, msm, is_yesterday=is_yesterday),
            panel_filter=lambda p: p.needs_power_history,
        )

    async def _dual_day_history_loop(self, subject: str, hook,
                                     panel_filter) -> None:
        """Stream today + yesterday history for a ``measurements`` subject.

        Replays from yesterday-midnight via ``by_start_time``; rolls
        panels over at UTC midnight. ``hook`` is called as
        ``hook(panel, hour, ts, msm, is_yesterday)``.

        Both data dispatch and the midnight rollover are filtered to
        panels that opt into THIS subject's history (``panel_filter``).
        That is critical: with two history loops (weather + power) both
        observing the UTC midnight crossing, an unfiltered rollover
        would fire twice, the second one wiping the just-saved
        yesterday-data with the new (still-empty) today-data and
        explaining the "no yesterday-shadow curves" symptom on
        long-running deployments.
        """
        msg = Messenger()
        today_midnight = _today_midnight_utc()
        yesterday_midnight = today_midnight - datetime.timedelta(days=1)
        rdr = msg.get_reader(subject,
                             deliver_policy='by_start_time',
                             opt_start_time=yesterday_midnight)
        logger.info(f"Subscribed to {subject} (history from {yesterday_midnight.isoformat()})")
        async for data, meta in rdr:
            try:
                now = datetime.datetime.now(datetime.timezone.utc)
                if now.date() > today_midnight.date():
                    today_midnight = _today_midnight_utc()
                    yesterday_midnight = today_midnight - datetime.timedelta(days=1)
                    for p in self.panels:
                        if panel_filter(p):
                            p.on_midnight_rollover()
                    logger.info(f"Midnight rollover triggered by {subject}")
                ts = dt_ensure_datetime(data['ts'])
                msm = data['measurements']
                hour = ts.hour + ts.minute / 60.0 + ts.second / 3600.0
                is_yesterday = ts < today_midnight
                for p in self.panels:
                    if panel_filter(p):
                        hook(p, hour, ts, msm, is_yesterday)
                self._schedule_draw()
            except (LookupError, TypeError, ValueError):
                continue

    async def _weather_status_callback(self, data, meta) -> bool:
        try:
            msm = data['measurements']
        except (KeyError, TypeError):
            return True
        for p in self.panels:
            if p.live_subject_kind == 'weather':
                p.on_live_summary(msm)
        self._schedule_draw()
        return True

    async def _power_status_callback(self, data, meta) -> bool:
        try:
            msm = data['measurements']
        except (KeyError, TypeError):
            return True
        for p in self.panels:
            if p.live_subject_kind == 'power':
                p.on_live_summary(msm)
        self._schedule_draw()
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
                self._schedule_draw()
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
                self._schedule_draw()
        except Exception as e:
            logger.warning(f"mount.azimuth reader [{tel}] failed: {e}")

    async def _pipeline_faststat_loop(self, tel: str):
        try:
            r = get_reader(f'tic.status.{tel}.fits.pipeline.faststat',
                           deliver_policy='by_start_time',
                           opt_start_time=_current_night_start_utc())
            async for data, meta in r:
                raw = data.get('raw') if isinstance(data, dict) else None
                if not raw:
                    continue
                hour = (_hour_from_iso((raw.get('header') or {}).get('DATE-OBS'))
                        or _hour_from_meta(meta)
                        or _hour_now_utc())
                for p in self.panels:
                    p.on_faststat(tel, hour, raw)
                self._schedule_draw()
        except Exception as e:
            logger.warning(f"pipeline.faststat reader [{tel}] failed: {e}")

    async def _pipeline_zdf_loop(self, tel: str):
        try:
            r = get_reader(f'tic.status.{tel}.fits.pipeline.zdf',
                           deliver_policy='by_start_time',
                           opt_start_time=_current_night_start_utc())
            async for data, meta in r:
                content = data.get('zdf') if isinstance(data, dict) else None
                if not content:
                    continue
                hour = (_hour_from_iso((content.get('header') or {}).get('DATE-OBS'))
                        or _hour_from_meta(meta)
                        or _hour_now_utc())
                for p in self.panels:
                    p.on_zdf(tel, hour, content)
                self._schedule_draw()
        except Exception as e:
            logger.warning(f"pipeline.zdf reader [{tel}] failed: {e}")

    async def _zero_monitor_loop(self, tel: str):
        try:
            r = get_reader(f'tic.status.{tel}.zero_monitor.lc',
                           deliver_policy='by_start_time',
                           opt_start_time=_current_night_start_utc())
            async for data, meta in r:
                if not isinstance(data, dict):
                    continue
                hour = (_hour_from_oca_jd(data.get('oca_jd'))
                        or _hour_from_meta(meta)
                        or _hour_now_utc())
                for p in self.panels:
                    p.on_zero_monitor(tel, hour, data)
                self._schedule_draw()
        except Exception as e:
            logger.warning(f"zero_monitor.lc reader [{tel}] failed: {e}")

    # ---- ephemeris label ----------------------------------------------------

    def _update_ephem(self):
        lt, sun_alt, ut = _ephemeris_parts()
        if sun_alt > -2.0:
            colour = '#7a3a3a'
        elif sun_alt > -18.0:
            colour = '#7a6a20'
        else:
            colour = '#2a4a30'
        self.label_ephem.setStyleSheet(
            f"QFrame {{ background-color: {colour}; border-radius: 4px; }}"
            "QLabel { background-color: transparent; color: #f0f0f0; }"
        )
        self.label_lt.setText(f"LT: {lt}")
        self.label_sun.setText(f"Sun: {sun_alt:.1f}°")
        self.label_ut.setText(f"UT: {ut}")
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
