from __future__ import annotations

import datetime
import logging
import math as _math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PyQt6 import QtCore  # imported before matplotlib so qt_compat picks PyQt6
from PyQt6.QtWidgets import QVBoxLayout, QWidget
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from qasync import asyncSlot
from serverish.base import dt_from_array
from serverish.base.task_manager import create_task
from serverish.messenger import get_reader

from oca_monitor.utils.ephem_ocm import next_sun_alt_event
from oca_monitor.widgets import chart_kit as ck

logger = logging.getLogger(__name__.rsplit('.')[-1])

_OCM_LOCAL_NOON_UTC_HOUR = 16

def _hour_of_day(dt: datetime.datetime) -> float:
    return dt.hour + dt.minute / 60.0 + dt.second / 3600.0


def _now_utc() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _current_night_start_utc() -> datetime.datetime:
    """Most recent OCM local-noon (16:00 UTC), as a tz-aware UTC datetime."""
    now = _now_utc()
    local_noon = now.replace(hour=_OCM_LOCAL_NOON_UTC_HOUR,
                             minute=0, second=0, microsecond=0)
    if local_noon > now:
        local_noon -= datetime.timedelta(days=1)
    return local_noon


def _next_sunset_utc() -> datetime.datetime:
    now = _now_utc()
    t = next_sun_alt_event(now, 0.0, 'setting')
    if t is None:

        return now + datetime.timedelta(days=1)
    return t


def _as_utc(dt: Optional[datetime.datetime]) -> Optional[datetime.datetime]:

    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


def _dt_from_iso(iso: Optional[str]) -> Optional[datetime.datetime]:
    if not iso:
        return None
    try:
        return _as_utc(datetime.datetime.fromisoformat(iso))
    except (TypeError, ValueError):
        return None


def _dt_from_meta(meta) -> Optional[datetime.datetime]:
    try:
        return _as_utc(dt_from_array(meta['ts']))
    except (LookupError, TypeError, ValueError):
        return None


class QualityChartWidget(QWidget):

    STAGES: Tuple[str, ...] = ('raw', 'zdf')

    title = 'Quality qmap  [%]'

    Y_MIN = 0.0
    Y_MAX = 100.0

    GREEN_THRESHOLD = 40.0    # ratio 0.40 — warning below this
    YELLOW_THRESHOLD = 5.0    # ratio 0.05 — bad below this

    SMOOTH_SIGMA = 5.0

    MAX_SEGMENT_GAP_HOURS = 0.5

    MIN_SEGMENT_POINTS = 4

    MAX_POINTS = 4000             # ring-buffer cap, per stage
    TRIM_POINTS = 1000

    def __init__(self, main_window, tel: str, subject: str = '',
                 vertical_screen: bool = False, **kwargs) -> None:
        super().__init__()
        self.main_window = main_window
        self.tel = tel
        self.vertical = bool(vertical_screen)
        self.raw_subject = f'tic.status.{tel}.fits.pipeline.raw'
        self.zdf_subject = f'tic.status.{tel}.fits.pipeline.zdf'


        self._series: Dict[str, Tuple[List[float], List[float], List[float]]] = {
            stage: ([], [], []) for stage in self.STAGES
        }

        self._scatters: Dict[str, Any] = {}
        self._line_smoothed: Optional[Any] = None
        self._overlay: Optional[Any] = None

        self._dirty = False
        self._draw_pending = False
        self._draw_interval_ms = 100

        self._init_ui()
        QtCore.QTimer.singleShot(0, self.async_init)
        logger.info(f"QualityChartWidget {self.tel} init setup done")

    # ---- UI -----------------------------------------------------------------

    def _tel_color(self) -> str:
        return ck.telescope_color(self.main_window, self.tel)

    def _init_ui(self) -> None:
        self.layout_root = QVBoxLayout(self)
        self.layout_root.setContentsMargins(2, 2, 2, 2)
        self.layout_root.setSpacing(2)

        self.figure = Figure(constrained_layout=False)
        ck.style_figure(self.figure)
        self.canvas = FigureCanvas(self.figure)
        self.layout_root.addWidget(self.canvas, 1)

        self.ax = ck.make_stacked_axes(self.figure, 1)[0]
        self._init_axes(self.ax)
        ck.format_hour_xaxis(self.ax)
        self.canvas.draw_idle()

    def _init_axes(self, ax) -> None:
        ax.set_zorder(2)
        ax.set_ylim(self.Y_MIN, self.Y_MAX)

        ax.set_yticks([40, 70, 100])

        # Threshold zone bands — drawn behind the data so the background
        # colour itself reads as the frame-quality state.
        ax.axhspan(self.GREEN_THRESHOLD, self.Y_MAX,
                   color=ck.COLOR_OK, alpha=0.10, linewidth=0, zorder=0)
        ax.axhspan(self.YELLOW_THRESHOLD, self.GREEN_THRESHOLD,
                   color=ck.COLOR_WARN, alpha=0.15, linewidth=0, zorder=0)
        ax.axhspan(self.Y_MIN, self.YELLOW_THRESHOLD,
                   color=ck.COLOR_DANGER, alpha=0.20, linewidth=0, zorder=0)

        for stage in self.STAGES:
            heavy = stage != 'raw'
            self._scatters[stage] = ax.scatter(
                [], [], s=12 if heavy else 7,
                c=self._tel_color(),
                alpha=0.55 if heavy else 0.35,
                edgecolors='none', linewidths=0,
                zorder=5 if heavy else 4, label=stage)


        self._line_smoothed, = ax.plot([], [], '-',
                                       color=self._tel_color(),
                                       linewidth=1.6, alpha=1.0, zorder=8)

        self._overlay = ck.big_overlay(ax, x=0.5, ha='center')

        ax.text(0.5, 0.94, self.title, transform=ax.transAxes,
                color=ck.FG_TEXT, fontsize=11, fontweight='bold',
                alpha=0.55, va='top', ha='center',
                bbox=dict(facecolor='#101010', edgecolor='#383838',
                          boxstyle='round,pad=0.3', alpha=0.40),
                zorder=5)

    def restamp_telescope_colors(self) -> None:
        for stage in self.STAGES:
            if stage in self._scatters:
                self._scatters[stage].set_color(self._tel_color())
        if self._line_smoothed is not None:
            self._line_smoothed.set_color(self._tel_color())

    def _zone_color(self, value: float) -> str:
        if value >= self.GREEN_THRESHOLD:
            return ck.COLOR_OK
        if value >= self.YELLOW_THRESHOLD:
            return ck.COLOR_WARN
        return ck.COLOR_DANGER

    # ---- async init ---------------------------------------------------------

    @asyncSlot()
    async def async_init(self):
        await create_task(self._color_resolver(), f'quality_chart_color_{self.tel}')
        await create_task(self._pipeline_loop('raw', self.raw_subject),
                          f'quality_chart_raw_{self.tel}')
        await create_task(self._pipeline_loop('zdf', self.zdf_subject),
                          f'quality_chart_zdf_{self.tel}')
        self._schedule_next_sunset_reset()

    async def _color_resolver(self):

        import asyncio
        for _ in range(120):  # ~60 s of patience, then give up
            cfg = getattr(self.main_window, 'nats_cfg', None) or {}
            if cfg.get('config', {}).get('telescopes'):
                break
            await asyncio.sleep(0.5)
        else:
            logger.warning(f'nats_cfg never arrived [{self.tel}] — keeping fallback colour')
            return
        self.restamp_telescope_colors()
        self._schedule_draw()

    async def _pipeline_loop(self, stage: str, subject: str) -> None:

        try:
            r = get_reader(subject, deliver_policy='by_start_time',
                           opt_start_time=_current_night_start_utc())
            async for data, meta in r:
                content = data.get(stage) if isinstance(data, dict) else None
                if not isinstance(content, dict):
                    continue
                header = content.get('header')
                try:
                    ratio = float(content['stars_presence']['ratio_no_bkg']['1'])
                except (LookupError, TypeError, ValueError):
                    continue
                if not _math.isfinite(ratio):
                    continue
                obs_dt = (_dt_from_iso((header or {}).get('DATE-OBS'))
                          or _dt_from_meta(meta)
                          or _now_utc())
                self._append(stage, obs_dt, ratio * 100.0)
                self._schedule_draw()
        except Exception as e:
            logger.warning(f"pipeline.{stage} reader [{self.tel}] failed: {e}")

    def _append(self, stage: str, obs_dt: datetime.datetime, percent: float) -> None:
        ts, hours, values = self._series[stage]
        ts.append(obs_dt.timestamp())
        hours.append(_hour_of_day(obs_dt))
        values.append(percent)
        if len(ts) > self.MAX_POINTS:
            del ts[:self.TRIM_POINTS]
            del hours[:self.TRIM_POINTS]
            del values[:self.TRIM_POINTS]

        self._dirty = True

    # ---- rendering ----------------------------------------------------------

    def _schedule_draw(self) -> None:
        """Coalesce redraws so a flood of pipeline messages doesn't turn
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
        for stage in self.STAGES:
            _ts, hours, values = self._series[stage]
            if hours:
                self._scatters[stage].set_offsets(np.column_stack((hours, values)))
            else:
                self._scatters[stage].set_offsets(np.zeros((0, 2)))

        out_x, out_y, tip = self._trend()
        self._line_smoothed.set_data(out_x, out_y)
        if tip is None:
            tip = self._newest_value()
        if tip is None:
            self._overlay.set_text('')
        else:
            self._overlay.set_text(f"{tip:.0f} %")
            self._overlay.set_color(self._zone_color(tip))

    def _newest_value(self) -> Optional[float]:
        """Value of the most recent frame across both stages, or None."""
        best_t: Optional[float] = None
        best_v: Optional[float] = None
        for stage in self.STAGES:
            ts, _hours, values = self._series[stage]
            if not ts:
                continue
            if best_t is None or ts[-1] > best_t:
                best_t, best_v = ts[-1], values[-1]
        return best_v

    def _trend(self) -> Tuple[List[float], List[float], Optional[float]]:

        all_t: List[float] = []
        all_h: List[float] = []
        all_v: List[float] = []
        for stage in self.STAGES:
            ts, hours, values = self._series[stage]
            all_t.extend(ts)
            all_h.extend(hours)
            all_v.extend(values)
        if not all_t:
            return [], [], None

        order = np.argsort(np.asarray(all_t, dtype=float))
        t = np.asarray(all_t, dtype=float)[order]
        h = np.asarray(all_h, dtype=float)[order]
        v = np.asarray(all_v, dtype=float)[order]

        if t.size > 1:
            gap_s = self.MAX_SEGMENT_GAP_HOURS * 3600.0
            cuts = np.where((np.diff(t) > gap_s) | (np.diff(h) < 0.0))[0] + 1
            seg_h = np.split(h, cuts)
            seg_v = np.split(v, cuts)
        else:
            seg_h = [h]
            seg_v = [v]

        out_x: List[float] = []
        out_y: List[float] = []
        last_smoothed: Optional[float] = None
        for sh, sv in zip(seg_h, seg_v):

            if sh.size < self.MIN_SEGMENT_POINTS:
                continue
            sv_smooth = np.asarray(ck.gaussian_filter1d(sv, sigma=self.SMOOTH_SIGMA),
                                   dtype=float)
            if out_x:
                out_x.append(np.nan)
                out_y.append(np.nan)
            out_x.extend(sh.tolist())
            out_y.extend(sv_smooth.tolist())
            last_smoothed = float(sv_smooth[-1])
        return out_x, out_y, last_smoothed

    # ---- nightly reset ------------------------------------------------------

    def _schedule_next_sunset_reset(self) -> None:

        try:
            sunset = _next_sunset_utc()
        except Exception as e:
            logger.warning(f"Failed to compute next sunset; reset disabled: {e}")
            return
        delay_s = max(60.0, (sunset - _now_utc()).total_seconds())
        delay_ms = min(int(delay_s * 1000), 2_147_000_000)  # QTimer takes int32 ms
        logger.info(
            f"Quality chart [{self.tel}] next sunset reset at {sunset.isoformat()} "
            f"(in {delay_s/3600:.2f} h)")
        QtCore.QTimer.singleShot(delay_ms, self._do_sunset_reset)

    def _do_sunset_reset(self) -> None:
        for stage in self.STAGES:
            self._series[stage] = ([], [], [])
        self._dirty = True
        self._schedule_draw()
        self._schedule_next_sunset_reset()


widget_class = QualityChartWidget
