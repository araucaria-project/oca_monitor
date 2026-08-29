"""Sky radar: telescope dots with motion trails, slew targets, Sun and Moon.

Data straight off NATS: tic.telemetry.{tel}.mount.azimuth|altitude,
tic.status.{tel}.mount.slewing|tracking|motorstatus, tic.status.{tel}.toi.ob|plan.
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import math
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple

import numpy as np
from PyQt6 import QtCore  # before matplotlib, so qt_compat picks PyQt6
from PyQt6.QtWidgets import QVBoxLayout, QWidget
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.colors import to_rgba
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
from qasync import asyncSlot
from serverish.base import dt_from_array
from serverish.base.task_manager import create_task
from serverish.messenger import get_reader

from oca_monitor.utils.ephem_ocm import location, next_moon_event, next_sun_alt_event
from oca_monitor.widgets import chart_kit as ck

logger = logging.getLogger(__name__.rsplit('.')[-1])


# r = 90 - alt; below the horizon squeezed into the band up to R_MAX
R_HORIZON = 90.0
R_MAX = 112.0
R_BELOW_SPAN = R_MAX - R_HORIZON

SKY_DAY = '#2a2317'
SKY_TWILIGHT = '#1d2130'
SKY_NIGHT = ck.BG_AXES
TWILIGHT_ALT_DEG = -18.0

COLOR_SUN = '#ffd24a'
COLOR_MOON_LIT = '#eef2f7'
COLOR_MOON_DARK = '#3a3f47'
COLOR_TARGET_LINK = '#8a8a8a'


def _radius(alt_deg: float) -> float:
    if alt_deg >= 0.0:
        return R_HORIZON - alt_deg
    return R_HORIZON + R_BELOW_SPAN * min(1.0, -alt_deg / 90.0)


def _theta(az_deg: float) -> float:
    return math.radians(az_deg % 360.0)


def _as_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ('true', '1'):
            return True
        if low in ('false', '0'):
            return False
    return None


def _as_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _meta_dt(meta) -> Optional[datetime.datetime]:
    try:
        dt = dt_from_array(meta['ts'])
    except (LookupError, TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


def _now_utc() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _hhmm(dt: Optional[datetime.datetime]) -> str:
    return dt.strftime('%H:%M') if dt is not None else '--:--'


def _program_object(program: Optional[str]) -> str:
    if not program:
        return ''
    parts = program.split()
    if not parts:
        return ''
    if parts[0] == 'OBJECT' and len(parts) > 1:
        return parts[1]
    return ' '.join(parts[:2])


def _angular_sep(az1: float, alt1: float, az2: float, alt2: float) -> float:
    a1, a2 = math.radians(alt1), math.radians(alt2)
    d_az = math.radians(az1 - az2)
    cos_sep = math.sin(a1) * math.sin(a2) + math.cos(a1) * math.cos(a2) * math.cos(d_az)
    return math.degrees(math.acos(max(-1.0, min(1.0, cos_sep))))


class RadarWidget(QWidget):

    REFRESH_S = 1.0
    ASTRO_REFRESH_S = 5.0
    ALMANAC_REFRESH_S = 60.0

    TRAIL_SECONDS = 120.0
    TRAIL_MIN_STEP_DEG = 0.03
    TRAIL_MAX_POINTS = 400

    STALE_S = 1800.0
    TARGET_MIN_SEP_DEG = 1.0

    MOUNT_TELEMETRY = {'az': 'mount.azimuth', 'alt': 'mount.altitude'}
    MOUNT_STATUS = {'slewing': 'mount.slewing',
                    'tracking': 'mount.tracking',
                    'motors': 'mount.motorstatus'}

    def __init__(self, main_window, telescopes: Optional[List[str]] = None,
                 trail_seconds: Optional[float] = None,
                 subject: str = '', vertical_screen: bool = False,
                 **kwargs) -> None:
        super().__init__()
        self.main_window = main_window
        self.vertical = bool(vertical_screen)
        self.telescopes = self._resolve_telescopes(telescopes)
        self.trail_seconds = float(trail_seconds or self.TRAIL_SECONDS)

        self._state: Dict[str, Dict[str, Any]] = {
            tel: {
                'az': None, 'alt': None, 'pos_dt': None,
                'slewing': None, 'tracking': None, 'motors': None,
                'ob': None, 'plan': None,
                'trail': deque(maxlen=self.TRAIL_MAX_POINTS),
            }
            for tel in self.telescopes
        }
        self._astro: Dict[str, Any] = {}
        self._almanac: Dict[str, Any] = {}

        self._init_ui()
        QtCore.QTimer.singleShot(0, self.async_init)
        logger.info(f"RadarWidget init setup done for {', '.join(self.telescopes)}")

    def _resolve_telescopes(self, telescopes: Optional[List[str]]) -> List[str]:
        if isinstance(telescopes, str):
            telescopes = [t.strip() for t in telescopes.split(',') if t.strip()]
        if telescopes:
            return list(telescopes)
        return list(getattr(self.main_window, 'telescope_names', []) or [])

    # ---- UI -----------------------------------------------------------------

    def _tel_color(self, tel: str) -> str:
        return ck.telescope_color(self.main_window, tel)

    def _init_ui(self) -> None:
        self.layout_root = QVBoxLayout(self)
        self.layout_root.setContentsMargins(2, 2, 2, 2)
        self.layout_root.setSpacing(2)

        self.figure = Figure(constrained_layout=False)
        ck.style_figure(self.figure)
        self.canvas = FigureCanvas(self.figure)
        self.layout_root.addWidget(self.canvas, 1)

        n = max(1, len(self.telescopes))
        gs = self.figure.add_gridspec(2, 1, height_ratios=[1.0, 0.085 * n])
        self.ax_sky = self.figure.add_subplot(gs[0], polar=True)
        self.ax_status = self.figure.add_subplot(gs[1])
        self.figure.subplots_adjust(left=0.045, right=0.955, top=0.97,
                                    bottom=0.025, hspace=0.05)
        self._draw()

    # ---- NATS readers -------------------------------------------------------

    @asyncSlot()
    async def async_init(self) -> None:
        for tel in self.telescopes:
            for key, suffix in self.MOUNT_TELEMETRY.items():
                await create_task(
                    self._measurement_reader(f'tic.telemetry.{tel}.{suffix}',
                                             tel, key, f'{tel}.{suffix}', position=True),
                    f'radar_{tel}_{key}')
            for key, suffix in self.MOUNT_STATUS.items():
                await create_task(
                    self._measurement_reader(f'tic.status.{tel}.{suffix}',
                                             tel, key, f'{tel}.{suffix}'),
                    f'radar_{tel}_{key}')
            await create_task(self._document_reader(f'tic.status.{tel}.toi.ob', tel, 'ob'),
                              f'radar_{tel}_ob')
            await create_task(self._document_reader(f'tic.status.{tel}.toi.plan', tel, 'plan'),
                              f'radar_{tel}_plan')

        await create_task(self._astro_loop(), 'radar_astro')
        await create_task(self._almanac_loop(), 'radar_almanac')
        await create_task(self._refresh_loop(), 'radar_refresh')

    async def _measurement_reader(self, subject: str, tel: str, key: str,
                                  measurement: str, position: bool = False) -> None:
        try:
            reader = get_reader(subject, deliver_policy='last')
            async for data, meta in reader:
                try:
                    value = data['measurements'][measurement]
                except (LookupError, TypeError):
                    continue
                self._state[tel][key] = _as_float(value) if position else _as_bool(value)
                if position:
                    self._state[tel]['pos_dt'] = _meta_dt(meta)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            raise
        except Exception as e:
            logger.warning(f'radar reader {subject} failed: {e}')

    async def _document_reader(self, subject: str, tel: str, key: str) -> None:
        try:
            reader = get_reader(subject, deliver_policy='last')
            async for data, meta in reader:
                self._state[tel][key] = data
        except (asyncio.CancelledError, asyncio.TimeoutError):
            raise
        except Exception as e:
            logger.warning(f'radar reader {subject} failed: {e}')

    # ---- Ephemeris ----------------------------------------------------------

    def _plan_target(self, tel: str) -> Optional[Dict[str, Any]]:
        plan = self._state[tel].get('plan') or {}
        items = plan.get('plan') or []
        if not items:
            return None
        idx = plan.get('current_i', -1)
        if not isinstance(idx, int) or not 0 <= idx < len(items):
            idx = plan.get('next_i', -1)
        if not isinstance(idx, int) or not 0 <= idx < len(items):
            return None
        entry = items[idx] or {}
        ob = entry.get('ob') or {}
        meta = entry.get('meta') or {}
        if ob.get('ra') is None or ob.get('dec') is None:
            return None
        # meta az/alt are the planned coords, they drift - fallback only
        return {
            'name': ob.get('name') or '',
            'ra': str(ob['ra']),
            'dec': str(ob['dec']),
            'plan_az': _as_float(meta.get('az')),
            'plan_alt': _as_float(meta.get('alt')),
        }

    def _compute_astro(self, targets: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        # blocking: always via asyncio.to_thread, astropy frames starve the loop
        from pyaraucaria.ephemeris import Moon, Star, Sun

        loc = location()
        now = _now_utc()
        sun = Sun(loc).get_ephemeris(now)[0]
        moon = Moon(loc).get_ephemeris(now)[0]

        resolved: Dict[str, Dict[str, Any]] = {}
        for tel, target in targets.items():
            try:
                eph = Star(loc, target['ra'], target['dec']).get_ephemeris(now)[0]
                az, alt = float(eph['az']), float(eph['alt'])
            except (ValueError, TypeError, KeyError) as e:
                logger.debug(f'radar: cannot project {tel} target: {e}')
                az, alt = target['plan_az'], target['plan_alt']
            if az is None or alt is None:
                continue
            resolved[tel] = {'name': target['name'], 'az': az, 'alt': alt}

        return {
            'sun': {'az': float(sun['az']), 'alt': float(sun['alt'])},
            'moon': {'az': float(moon['az']), 'alt': float(moon['alt']),
                     'phase': float(moon['phase'])},
            'targets': resolved,
        }

    def _compute_almanac(self) -> Dict[str, Any]:
        now = _now_utc()
        return {
            'sunset': next_sun_alt_event(now, 0.0, 'setting'),
            'sunrise': next_sun_alt_event(now, 0.0, 'rising'),
            'moonset': next_moon_event(now, 'setting'),
            'moonrise': next_moon_event(now, 'rising'),
        }

    async def _astro_loop(self) -> None:
        while True:
            targets = {}
            for tel in self.telescopes:
                target = self._plan_target(tel)
                if target is not None:
                    targets[tel] = target
            try:
                self._astro = await asyncio.to_thread(self._compute_astro, targets)
            except Exception as e:
                logger.warning(f'radar astro update failed: {e}')
            await asyncio.sleep(self.ASTRO_REFRESH_S)

    async def _almanac_loop(self) -> None:
        while True:
            try:
                self._almanac = await asyncio.to_thread(self._compute_almanac)
            except Exception as e:
                logger.warning(f'radar almanac update failed: {e}')
            await asyncio.sleep(self.ALMANAC_REFRESH_S)

    # ---- Trails -------------------------------------------------------------

    def _sample_trails(self) -> None:
        now = time.time()
        for tel in self.telescopes:
            st = self._state[tel]
            trail: Deque = st['trail']
            while trail and now - trail[0][0] > self.trail_seconds:
                trail.popleft()
            az, alt = st['az'], st['alt']
            if az is None or alt is None or self._is_stale(st):
                continue
            if trail:
                _, last_az, last_alt = trail[-1]
                if _angular_sep(az, alt, last_az, last_alt) < self.TRAIL_MIN_STEP_DEG:
                    continue
            trail.append((now, az, alt))

    def _is_stale(self, st: Dict[str, Any]) -> bool:
        pos_dt = st.get('pos_dt')
        if pos_dt is None:
            return True
        return (_now_utc() - pos_dt).total_seconds() > self.STALE_S

    async def _refresh_loop(self) -> None:
        while True:
            try:
                self._sample_trails()
                if self.isVisible():
                    self._draw()
            except Exception as e:
                logger.warning(f'radar redraw failed: {e}')
            await asyncio.sleep(self.REFRESH_S)

    # ---- Drawing ------------------------------------------------------------

    def _mount_state(self, tel: str) -> Tuple[str, str]:
        st = self._state[tel]
        if self._is_stale(st):
            return 'NO DATA', ck.FG_DIM
        if st['motors'] is False:
            return 'MOTORS OFF', ck.FG_DIM
        if st['slewing']:
            return 'SLEWING', ck.COLOR_WARN
        if st['tracking']:
            return 'TRACKING', ck.COLOR_OK
        return 'IDLE', ck.FG_DIM

    def _ob_progress(self, tel: str) -> Tuple[str, Optional[float]]:
        ob = self._state[tel].get('ob') or {}
        label = _program_object(ob.get('ob_program'))
        if not (ob.get('ob_started') and not ob.get('ob_done')):
            target = (self._astro.get('targets') or {}).get(tel)
            return (target['name'] if target else ''), None
        t0 = _as_float(ob.get('ob_start_time'))
        expected = _as_float(ob.get('ob_expected_time'))
        if not t0 or not expected:
            return label, None
        return label, max(0.0, (time.time() - t0) / expected)

    def _sky_facecolor(self) -> str:
        sun = self._astro.get('sun')
        if sun is None:
            return SKY_NIGHT
        if sun['alt'] > 0.0:
            return SKY_DAY
        if sun['alt'] > TWILIGHT_ALT_DEG:
            return SKY_TWILIGHT
        return SKY_NIGHT

    def _draw(self) -> None:
        self._draw_sky()
        self._draw_status()
        self.canvas.draw_idle()

    def _draw_sky(self) -> None:
        ax = self.ax_sky
        ax.clear()
        ax.set_facecolor(self._sky_facecolor())
        ax.set_theta_zero_location('N')
        ax.set_theta_direction(-1)
        ax.set_ylim(0.0, R_MAX)

        ax.set_xticks(np.radians(np.arange(0, 360, 45)))
        ax.set_xticklabels(['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'])
        ax.set_rticks([R_HORIZON - 60.0, R_HORIZON - 30.0])
        ax.set_yticklabels([])
        ax.tick_params(colors=ck.FG_DIM, labelsize=9, pad=-2)
        ax.grid(True, color=ck.GRID_MAJOR, linewidth=0.6, alpha=0.7)
        ax.spines['polar'].set_color(ck.SPINE)

        ax.bar(0.0, R_BELOW_SPAN, width=2 * np.pi, bottom=R_HORIZON,
               color='#0b0b0b', alpha=0.85, linewidth=0, zorder=0)
        ax.bar(0.0, 20.0, width=2 * np.pi, bottom=R_HORIZON - 20.0,
               color=ck.COLOR_DANGER, alpha=0.06, linewidth=0, zorder=0)
        ring = np.linspace(0.0, 2 * np.pi, 181)
        ax.plot(ring, np.full_like(ring, R_HORIZON), color='#7a7a7a',
                linewidth=1.0, alpha=0.8, zorder=2)

        for alt in (30, 60):
            ax.text(np.radians(22.5), R_HORIZON - alt, f'{alt}°',
                    color=ck.FG_DIM, fontsize=7, alpha=0.7,
                    ha='center', va='center', zorder=3)

        self._draw_bodies(ax)
        for tel in self.telescopes:
            self._draw_telescope(ax, tel)
        self._draw_almanac(ax)

    def _draw_bodies(self, ax) -> None:
        sun = self._astro.get('sun')
        if sun is not None:
            theta, r = _theta(sun['az']), _radius(sun['alt'])
            up = sun['alt'] > 0.0
            ax.scatter([theta], [r], s=700, c=[COLOR_SUN], linewidths=0,
                       alpha=0.16 if up else 0.06, zorder=3)
            ax.scatter([theta], [r], s=150, c=[COLOR_SUN], edgecolors='#8a6a12',
                       linewidths=0.8, alpha=1.0 if up else 0.45, zorder=7)
            ax.annotate('SUN', (theta, r), textcoords='offset points',
                        xytext=(0, -16), ha='center', color=COLOR_SUN,
                        fontsize=7.5, alpha=0.85, zorder=11)

        moon = self._astro.get('moon')
        if moon is not None:
            theta, r = _theta(moon['az']), _radius(moon['alt'])
            up = moon['alt'] > 0.0
            face = ck.blend_colors(COLOR_MOON_DARK, COLOR_MOON_LIT, moon['phase'])
            ax.scatter([theta], [r], s=120, c=[face], edgecolors=COLOR_MOON_LIT,
                       linewidths=0.8, alpha=1.0 if up else 0.4, zorder=7)
            ax.annotate('MOON', (theta, r), textcoords='offset points',
                        xytext=(0, -16), ha='center', color=COLOR_MOON_LIT,
                        fontsize=7.5, alpha=0.75, zorder=11)

    def _draw_telescope(self, ax, tel: str) -> None:
        st = self._state[tel]
        az, alt = st['az'], st['alt']
        if az is None or alt is None:
            return
        color = self._tel_color(tel)
        stale = self._is_stale(st)
        _, state_color = self._mount_state(tel)
        theta, r = _theta(az), _radius(alt)

        trail = list(st['trail'])
        if len(trail) > 1:
            now = time.time()
            fresh = np.clip([1.0 - (now - t) / self.trail_seconds for t, _, _ in trail], 0.0, 1.0)
            rgba = np.array([to_rgba(color, alpha=0.06 + 0.44 * f) for f in fresh])
            ax.scatter([_theta(a) for _, a, _ in trail],
                       [_radius(h) for _, _, h in trail],
                       s=2.0 + 11.0 * fresh ** 2, c=rgba,
                       edgecolors='none', zorder=4)

        target = (self._astro.get('targets') or {}).get(tel)
        if target is not None and not stale and st['motors'] is not False:
            if _angular_sep(az, alt, target['az'], target['alt']) > self.TARGET_MIN_SEP_DEG:
                t_theta, t_r = _theta(target['az']), _radius(target['alt'])
                ax.plot([theta, t_theta], [r, t_r], linestyle='--', linewidth=1.0,
                        color=COLOR_TARGET_LINK, alpha=0.5, zorder=5)
                ax.scatter([t_theta], [t_r], s=80, c=[color], marker='x',
                           linewidths=1.6, alpha=0.9, zorder=8)

        ax.scatter([theta], [r], s=120,
                   c=['none'] if stale else [color],
                   edgecolors=[state_color], linewidths=1.8,
                   alpha=0.4 if stale else 1.0, zorder=9)
        ax.annotate(tel, (theta, r), textcoords='offset points', xytext=(0, 11),
                    ha='center', color=color, fontsize=9, fontweight='bold',
                    alpha=0.5 if stale else 1.0, zorder=11)

        obj, _ = self._ob_progress(tel)
        if obj and not stale:
            ax.annotate(obj, (theta, r), textcoords='offset points', xytext=(0, -17),
                        ha='center', color=ck.FG_TEXT, fontsize=7.5, alpha=0.85,
                        zorder=11)

    def _draw_almanac(self, ax) -> None:
        sun = self._astro.get('sun')
        moon = self._astro.get('moon')
        alm = self._almanac

        if sun is not None:
            if sun['alt'] > 0.0:
                event = f"sunset {_hhmm(alm.get('sunset'))}"
            else:
                event = f"sunrise {_hhmm(alm.get('sunrise'))}"
            ax.text(0.0, 1.0, f"SUN {sun['alt']:+.1f}°\n{event} UT",
                    transform=ax.transAxes, color=COLOR_SUN, fontsize=8,
                    alpha=0.8, ha='left', va='top', linespacing=1.5, zorder=12)

        if moon is not None:
            if moon['alt'] > 0.0:
                event = f"moonset {_hhmm(alm.get('moonset'))}"
            else:
                event = f"moonrise {_hhmm(alm.get('moonrise'))}"
            ax.text(1.0, 1.0,
                    f"MOON {moon['phase'] * 100:.0f}%  {moon['alt']:+.0f}°\n{event} UT",
                    transform=ax.transAxes, color=COLOR_MOON_LIT, fontsize=8,
                    alpha=0.7, ha='right', va='top', linespacing=1.5, zorder=12)

        ax.text(0.0, 0.0, _now_utc().strftime('%H:%M:%S UT'),
                transform=ax.transAxes, color=ck.FG_DIM, fontsize=8,
                alpha=0.7, ha='left', va='bottom', zorder=12)

    def _draw_status(self) -> None:
        ax = self.ax_status
        ax.clear()
        ax.set_facecolor(ck.BG_AXES)
        n = max(1, len(self.telescopes))
        ax.set_xlim(0.0, 1.0)
        ax.set_ylim(0.0, float(n))
        ax.invert_yaxis()
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_color(ck.SPINE)

        bar_x, bar_w = 0.63, 0.28

        for i, tel in enumerate(self.telescopes):
            y = i + 0.5
            color = self._tel_color(tel)
            state, state_color = self._mount_state(tel)
            obj, progress = self._ob_progress(tel)

            ax.add_patch(Rectangle((0.008, i + 0.22), 0.012, 0.56,
                                   color=color, linewidth=0))
            ax.text(0.032, y, tel, color=color, fontsize=9, fontweight='bold',
                    ha='left', va='center')
            ax.text(0.135, y, state, color=state_color, fontsize=8,
                    ha='left', va='center')
            ax.text(0.30, y, obj or '—', color=ck.FG_TEXT, fontsize=8.5,
                    ha='left', va='center', alpha=0.9 if obj else 0.4)

            ax.add_patch(Rectangle((bar_x, i + 0.34), bar_w, 0.32,
                                   color='#2c2c2c', linewidth=0))
            if progress is not None:
                # over 100% the OB runs long - flag it instead of stalling at full
                fill_color = ck.COLOR_WARN if progress > 1.0 else ck.COLOR_OK
                ax.add_patch(Rectangle((bar_x, i + 0.34), bar_w * min(1.0, progress),
                                       0.32, color=fill_color, linewidth=0))
                ax.text(0.995, y, f'{progress * 100:.0f}%', color=fill_color,
                        fontsize=8, ha='right', va='center')


widget_class = RadarWidget
