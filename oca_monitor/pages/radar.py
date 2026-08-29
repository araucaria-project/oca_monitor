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
from matplotlib.patches import Circle, Rectangle
from qasync import asyncSlot
from serverish.base import dt_from_array
from serverish.base.task_manager import create_task
from serverish.messenger import get_reader

from oca_monitor.utils.ephem_ocm import location
from oca_monitor.widgets import chart_kit as ck

logger = logging.getLogger(__name__.rsplit('.')[-1])


# r = 90 - alt; 90..R_DOME_TOP holds sunk bodies and the dome lanes, the ring
# beyond it is left free for the wind arrow
R_HORIZON = 90.0
R_DOME_TOP = 97.0
R_MAX = 107.0
R_BELOW_SPAN = R_DOME_TOP - R_HORIZON

SKY_DAY = '#1f1c17'
SKY_TWILIGHT = '#1d2130'
SKY_NIGHT = ck.BG_AXES
TWILIGHT_ALT_DEG = -18.0

COLOR_SUN = '#ffd24a'
COLOR_MOON_LIT = '#eef2f7'
COLOR_MOON_DARK = '#3a3f47'
COLOR_MOON_ZONE = '#7fa8ff'
COLOR_TARGET_LINK = '#8a8a8a'
COLOR_WIND_TRACK = '#4d4d4d'


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


def _as_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
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

    OB_LABEL_DY_PX = 14
    OB_BAR_DY_PX = 13
    OB_BAR_W_PX = 46
    OB_BAR_H_PX = 5

    DOME_WEDGE_DEG = 10.0
    DOME_LANE_GAP = 0.4
    WIND_ARROW_R0 = R_MAX - 1.0
    WIND_ARROW_R1 = R_DOME_TOP + 1.0
    WIND_LABEL_R = R_HORIZON - 5.0
    MOON_AVOID_DEFAULT_DEG = 30.0
    OBS_MIN_ALT_DEFAULT_DEG = 35.0
    MOON_AVOID_CFG_PATH = ('config', 'site', 'global', 'obs_limits', 'ephem',
                           'full_moon_distance')
    WIND_CFG_PATH = ('config', 'site', 'global', 'obs_limits',
                     'weather_restrictions', 'wind')
    MOUNT_CFG_PATH = ('config', 'telescopes', '{tel}', 'observatory',
                      'components', 'mount')

    MOUNT_TELEMETRY = {'az': 'mount.azimuth', 'alt': 'mount.altitude'}
    DOME_TELEMETRY = {'dome_az': 'dome.azimuth'}
    MOUNT_STATUS = {'slewing': 'mount.slewing',
                    'tracking': 'mount.tracking',
                    'motors': 'mount.motorstatus'}
    DOME_STATUS = {'dome_shutter': 'dome.shutterstatus'}

    def __init__(self, main_window, telescopes: Optional[List[str]] = None,
                 trail_seconds: Optional[float] = None,
                 subject: str = 'telemetry.weather.davis',
                 wind_warn_ms: Optional[float] = None,
                 wind_danger_ms: Optional[float] = None,
                 moon_avoid_deg: Optional[float] = None,
                 obs_min_alt_deg: Optional[float] = None,
                 vertical_screen: bool = False, **kwargs) -> None:
        super().__init__()
        self.main_window = main_window
        self.vertical = bool(vertical_screen)
        self.telescopes = self._resolve_telescopes(telescopes)
        self.trail_seconds = float(trail_seconds or self.TRAIL_SECONDS)
        self.subject = subject
        self.wind_warn_ms = _as_float(wind_warn_ms)
        self.wind_danger_ms = _as_float(wind_danger_ms)
        self.moon_avoid_deg = _as_float(moon_avoid_deg)
        self.obs_min_alt_deg = _as_float(obs_min_alt_deg)

        self._state: Dict[str, Dict[str, Any]] = {
            tel: {
                'az': None, 'alt': None, 'pos_dt': None,
                'slewing': None, 'tracking': None, 'motors': None,
                'dome_az': None, 'dome_shutter': None,
                'ob': None, 'plan': None,
                'trail': deque(maxlen=self.TRAIL_MAX_POINTS),
            }
            for tel in self.telescopes
        }
        self._astro: Dict[str, Any] = {}
        self._wind: Dict[str, Optional[float]] = {'ms': None, 'dir': None}

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

    def _cfg(self, path, default: Any = None) -> Any:
        node = getattr(self.main_window, 'nats_cfg', None) or {}
        try:
            for key in path:
                node = node[key]
        except (LookupError, TypeError):
            return default
        return node

    def _moon_avoid(self) -> float:
        if self.moon_avoid_deg is not None:
            return self.moon_avoid_deg
        value = _as_float(self._cfg(self.MOON_AVOID_CFG_PATH))
        return self.MOON_AVOID_DEFAULT_DEG if value is None else value

    def _obs_min_alt(self) -> float:
        if self.obs_min_alt_deg is not None:
            return self.obs_min_alt_deg
        limits = []
        for tel in self.telescopes:
            path = tuple(tel if k == '{tel}' else k for k in self.MOUNT_CFG_PATH)
            value = _as_float(self._cfg(path + ('obs_min_alt',)))
            if value is not None:
                limits.append(value)
        # most restrictive mount wins, so the ring promises no unreachable sky
        return max(limits) if limits else self.OBS_MIN_ALT_DEFAULT_DEG

    def _wind_limits(self) -> Tuple[float, float]:
        cfg = self._cfg(self.WIND_CFG_PATH) or {}
        warn = self.wind_warn_ms
        if warn is None:
            warn = _as_float(cfg.get('pointing') if isinstance(cfg, dict) else None)
        danger = self.wind_danger_ms
        if danger is None:
            danger = _as_float(cfg.get('observation_stop') if isinstance(cfg, dict) else None)
        return (ck.WIND_WARN_MS if warn is None else warn,
                ck.WIND_DANGER_MS if danger is None else danger)

    def _init_ui(self) -> None:
        self.layout_root = QVBoxLayout(self)
        self.layout_root.setContentsMargins(2, 2, 2, 2)
        self.layout_root.setSpacing(2)

        self.figure = Figure(constrained_layout=False)
        ck.style_figure(self.figure)
        self.canvas = FigureCanvas(self.figure)
        self.layout_root.addWidget(self.canvas, 1)

        self.ax_sky = self.figure.add_subplot(111, polar=True)
        self.figure.subplots_adjust(left=0.005, right=0.995, top=0.995, bottom=0.005)
        self._draw()

    # ---- NATS readers -------------------------------------------------------

    @asyncSlot()
    async def async_init(self) -> None:
        for tel in self.telescopes:
            for key, suffix in self.MOUNT_TELEMETRY.items():
                await create_task(
                    self._measurement_reader(f'tic.telemetry.{tel}.{suffix}', tel, key,
                                             f'{tel}.{suffix}', _as_float, position=True),
                    f'radar_{tel}_{key}')
            for key, suffix in self.DOME_TELEMETRY.items():
                await create_task(
                    self._measurement_reader(f'tic.telemetry.{tel}.{suffix}', tel, key,
                                             f'{tel}.{suffix}', _as_float),
                    f'radar_{tel}_{key}')
            for key, suffix in self.MOUNT_STATUS.items():
                await create_task(
                    self._measurement_reader(f'tic.status.{tel}.{suffix}', tel, key,
                                             f'{tel}.{suffix}', _as_bool),
                    f'radar_{tel}_{key}')
            for key, suffix in self.DOME_STATUS.items():
                await create_task(
                    self._measurement_reader(f'tic.status.{tel}.{suffix}', tel, key,
                                             f'{tel}.{suffix}', _as_int),
                    f'radar_{tel}_{key}')
            await create_task(self._document_reader(f'tic.status.{tel}.toi.ob', tel, 'ob'),
                              f'radar_{tel}_ob')
            await create_task(self._document_reader(f'tic.status.{tel}.toi.plan', tel, 'plan'),
                              f'radar_{tel}_plan')

        await create_task(self._wind_reader(), 'radar_wind')
        await create_task(self._astro_loop(), 'radar_astro')
        await create_task(self._refresh_loop(), 'radar_refresh')

    async def _measurement_reader(self, subject: str, tel: str, key: str,
                                  measurement: str, parse, position: bool = False) -> None:
        try:
            reader = get_reader(subject, deliver_policy='last')
            async for data, meta in reader:
                try:
                    value = data['measurements'][measurement]
                except (LookupError, TypeError):
                    continue
                parsed = parse(value)
                self._state[tel][key] = parsed
                if position and parsed is not None:
                    self._state[tel]['pos_dt'] = _meta_dt(meta)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            raise
        except Exception as e:
            logger.warning(f'radar reader {subject} failed: {e}')

    async def _wind_reader(self) -> None:
        try:
            reader = get_reader(self.subject, deliver_policy='last')
            async for data, meta in reader:
                try:
                    msm = data['measurements']
                except (LookupError, TypeError):
                    continue
                speed = _as_float(msm.get('wind_ms'))
                if speed is None:
                    speed = _as_float(msm.get('wind_10min_ms'))
                self._wind = {'ms': speed, 'dir': _as_float(msm.get('wind_dir_deg'))}
        except (asyncio.CancelledError, asyncio.TimeoutError):
            raise
        except Exception as e:
            logger.warning(f'radar reader {self.subject} failed: {e}')

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

    def _ob_progress(self, tel: str) -> Tuple[str, Optional[float], bool]:
        ob = self._state[tel].get('ob') or {}
        if not (ob.get('ob_started') and not ob.get('ob_done')):
            target = (self._astro.get('targets') or {}).get(tel)
            return (target['name'] if target else ''), None, False
        label = _program_object(ob.get('ob_program'))
        t0 = _as_float(ob.get('ob_start_time'))
        expected = _as_float(ob.get('ob_expected_time'))
        if not t0 or not expected:
            return label, None, True
        return label, max(0.0, (time.time() - t0) / expected), True

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
        ax.tick_params(colors=ck.FG_DIM, labelsize=8, pad=-13)
        ax.grid(True, color=ck.GRID_MAJOR, linewidth=0.6, alpha=0.7)
        ax.spines['polar'].set_color(ck.SPINE)

        ax.bar(0.0, R_MAX - R_HORIZON, width=2 * np.pi, bottom=R_HORIZON,
               color='#0b0b0b', alpha=0.85, linewidth=0, zorder=0)
        min_alt = self._obs_min_alt()
        ax.bar(0.0, min_alt, width=2 * np.pi, bottom=R_HORIZON - min_alt,
               color=ck.COLOR_DANGER, alpha=0.07, linewidth=0, zorder=0)
        ring = np.linspace(0.0, 2 * np.pi, 181)
        ax.plot(ring, np.full_like(ring, R_HORIZON), color='#7a7a7a',
                linewidth=1.0, alpha=0.8, zorder=2)
        ax.plot(ring, np.full_like(ring, R_HORIZON - min_alt), color=ck.COLOR_DANGER,
                linewidth=0.9, linestyle='--', alpha=0.45, zorder=2)

        for alt in (30, 60):
            ax.text(np.radians(22.5), R_HORIZON - alt, f'{alt}°',
                    color=ck.FG_DIM, fontsize=7, alpha=0.7,
                    ha='center', va='center', zorder=3)

        for tel in self.telescopes:
            self._draw_dome(ax, tel)
        self._draw_bodies(ax)
        self._draw_wind(ax)
        for tel in self.telescopes:
            self._draw_telescope(ax, tel)

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
            self._draw_moon_zone(ax, moon)
            ax.scatter([theta], [r], s=120, c=[face], edgecolors=COLOR_MOON_LIT,
                       linewidths=0.8, alpha=1.0 if up else 0.4, zorder=7)
            ax.annotate(f"MOON {moon['phase'] * 100:.0f}%", (theta, r),
                        textcoords='offset points', xytext=(0, -16), ha='center',
                        color=COLOR_MOON_LIT, fontsize=8, fontweight='bold',
                        alpha=0.85 if up else 0.5, zorder=11)

    def _draw_moon_zone(self, ax, moon: Dict[str, float]) -> None:
        avoid = self._moon_avoid()
        if moon['alt'] < -avoid:
            return
        try:
            box = ax.get_window_extent()
            px, py = ax.transData.transform((_theta(moon['az']), _radius(moon['alt'])))
        except (ValueError, AttributeError, RuntimeError):
            return
        if not box.width or not box.height:
            return
        # a plain screen circle - the true small circle would come out a lens
        f = 1.0 / box.width
        radius = avoid * (box.width / 2.0) / R_MAX * f
        zone = Circle(((px - box.x0) * f, (py - box.y0) / box.height), radius,
                      transform=ax.transAxes, facecolor=COLOR_MOON_ZONE,
                      edgecolor=COLOR_MOON_ZONE, linewidth=0.8, alpha=0.14,
                      zorder=1)
        zone.set_clip_path(Circle((0.5, 0.5), 0.5 * R_HORIZON / R_MAX,
                                  transform=ax.transAxes))
        ax.add_patch(zone)

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
        if target is not None and not stale and (st['slewing'] or st['tracking']):
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

        if stale:
            return
        obj, progress, active = self._ob_progress(tel)
        if not active:
            return
        if obj:
            ax.annotate(obj, (theta, r), textcoords='offset points',
                        xytext=(0, self.OB_LABEL_DY_PX), ha='center', color=color,
                        fontsize=7.5, alpha=0.95, zorder=11)
        if progress is not None:
            self._draw_progress_bar(ax, theta, r, progress)

    def _draw_progress_bar(self, ax, theta: float, r: float, progress: float) -> None:
        # sized in px so it reads the same wherever the dot sits
        try:
            box = ax.get_window_extent()
            px, py = ax.transData.transform((theta, r))
        except (ValueError, AttributeError, RuntimeError):
            return
        if not box.width or not box.height:
            return
        fx, fy = 1.0 / box.width, 1.0 / box.height
        cx, cy = (px - box.x0) * fx, (py - box.y0) * fy
        w, h = self.OB_BAR_W_PX * fx, self.OB_BAR_H_PX * fy
        x0 = cx - w / 2.0
        y0 = cy - (self.OB_BAR_DY_PX + self.OB_BAR_H_PX) * fy

        # past 100 % the OB runs long - flag it instead of stalling at full
        fill_color = ck.COLOR_WARN if progress > 1.0 else ck.COLOR_OK
        ax.add_patch(Rectangle((x0, y0), w, h, transform=ax.transAxes,
                               color='#4d4d4d', alpha=0.75, linewidth=0, clip_on=False, zorder=10))
        ax.add_patch(Rectangle((x0, y0), w * min(1.0, progress), h,
                               transform=ax.transAxes, color=fill_color,
                               linewidth=0, clip_on=False, zorder=11))

    def _dome_lane(self, tel: str) -> Tuple[float, float]:
        n = max(1, len(self.telescopes))
        height = R_BELOW_SPAN / n
        bottom = R_HORIZON + self.telescopes.index(tel) * height
        return bottom + self.DOME_LANE_GAP / 2.0, height - self.DOME_LANE_GAP

    def _draw_dome(self, ax, tel: str) -> None:
        st = self._state[tel]
        shutter = st['dome_shutter']
        if shutter is None:
            return
        bottom, height = self._dome_lane(tel)
        # pms publishes a null dome azimuth when the encoder is unavailable, so
        # fall back to the mount and dot the outline to mark it as assumed
        az, inferred = st['dome_az'], False
        if az is None:
            az, inferred = st['az'], True
        if az is None:
            return
        color = self._tel_color(tel)
        closed = shutter == 1
        style = ':' if inferred else ('--' if shutter in (2, 3) else '-')
        alpha = (0.4 if closed else 0.55) if inferred else (0.6 if closed else 0.95)
        ax.bar(_theta(az), height, width=math.radians(self.DOME_WEDGE_DEG),
               bottom=bottom, facecolor=color if closed else 'none',
               edgecolor=color, linewidth=1.4, linestyle=style,
               alpha=alpha, zorder=2)

    def _wind_color(self, speed_ms: float) -> str:
        warn, danger = self._wind_limits()
        if speed_ms < warn:
            return ck.COLOR_OK
        if speed_ms < danger:
            return ck.COLOR_WARN
        return ck.COLOR_DANGER

    def _draw_wind(self, ax) -> None:
        speed, direction = self._wind['ms'], self._wind['dir']
        if speed is None or direction is None:
            return
        theta = _theta(direction)
        color = self._wind_color(speed)
        # blows inward from where it comes from; annotate keeps it screen-straight
        ax.annotate('', xy=(theta, self.WIND_ARROW_R1), xytext=(theta, self.WIND_ARROW_R0),
                    arrowprops=dict(arrowstyle='-|>,head_width=0.25,head_length=0.5',
                                    color=color, linewidth=2.0, shrinkA=0, shrinkB=0,
                                    alpha=0.9), zorder=6)
        ax.text(theta, self.WIND_LABEL_R, f'{speed:.1f} m/s', color=color,
                fontsize=8, fontweight='bold', ha='center', va='center',
                zorder=12)


widget_class = RadarWidget
