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
from matplotlib.patches import Circle, FancyBboxPatch, Polygon, Rectangle
from qasync import asyncSlot
from serverish.base import dt_from_array
from serverish.base.task_manager import create_task
from serverish.messenger import get_reader

from oca_monitor.utils.ephem_ocm import location
from oca_monitor.widgets import chart_kit as ck

logger = logging.getLogger(__name__.rsplit('.')[-1])


# Radial scale, see RadarWidget._radius: the observable sky gets R_USEFUL,
# the unusable wedge under obs_min_alt only the rim up to R_HORIZON, sunk
# bodies and the dome lanes 90..R_DOME_TOP (sized to still split six ways),
# the wind label the thin ring beyond.
R_USEFUL = 72.0
R_HORIZON = 90.0
R_DOME_TOP = 97.0
R_MAX = 103.0
R_BELOW_SPAN = R_DOME_TOP - R_HORIZON

SKY_DAY = '#2b2620'
SKY_TWILIGHT = '#262b3d'
SKY_NIGHT = '#272727'
COLOR_GRID = '#4d4d4d'
COLOR_GRID_TEXT = '#bcbcbc'
COLOR_RING_BG = '#151515'
COLOR_HORIZON = '#949494'
TWILIGHT_ALT_DEG = -18.0

COLOR_SUN = '#ffd24a'
COLOR_MOON_LIT = '#eef2f7'
COLOR_MOON_DARK = '#3a3f47'
COLOR_MOON_ZONE = '#7fa8ff'
COLOR_ICON = '#d8dde3'
COLOR_WIND_TRACK = '#4d4d4d'


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


def _slerp_altaz(az0: float, alt0: float, az1: float, alt1: float,
                 f: float) -> Tuple[float, float]:
    """Point a fraction ``f`` along the great circle between two horizontal
    positions - the path a mount actually sweeps between two samples."""
    a0, h0 = math.radians(az0), math.radians(alt0)
    a1, h1 = math.radians(az1), math.radians(alt1)
    v0 = (math.cos(h0) * math.cos(a0), math.cos(h0) * math.sin(a0), math.sin(h0))
    v1 = (math.cos(h1) * math.cos(a1), math.cos(h1) * math.sin(a1), math.sin(h1))
    dot = max(-1.0, min(1.0, sum(p * q for p, q in zip(v0, v1))))
    omega = math.acos(dot)
    if omega < 1e-9:
        return az0, alt0
    s0 = math.sin((1.0 - f) * omega) / math.sin(omega)
    s1 = math.sin(f * omega) / math.sin(omega)
    x, y, z = (s0 * p + s1 * q for p, q in zip(v0, v1))
    return math.degrees(math.atan2(y, x)) % 360.0, math.degrees(math.asin(
        max(-1.0, min(1.0, z))))


def _boxes_overlap(a, b, pad: float = 2.0) -> bool:
    return not (a[2] + pad < b[0] or b[2] + pad < a[0]
                or a[3] + pad < b[1] or b[3] + pad < a[1])


def _angular_sep(az1: float, alt1: float, az2: float, alt2: float) -> float:
    a1, a2 = math.radians(alt1), math.radians(alt2)
    d_az = math.radians(az1 - az2)
    cos_sep = math.sin(a1) * math.sin(a2) + math.cos(a1) * math.cos(a2) * math.cos(d_az)
    return math.degrees(math.acos(max(-1.0, min(1.0, cos_sep))))


class RadarWidget(QWidget):

    REFRESH_S = 0.5
    ASTRO_REFRESH_S = 5.0
    ALMANAC_REFRESH_S = 60.0

    TRAIL_SECONDS = 5.0
    TRAIL_MIN_STEP_DEG = 0.03
    TRAIL_MAX_POINTS = 400
    TRAIL_DOT_SEP_PX = 13.0
    TRAIL_ARC_STEP_DEG = 0.25
    TRAIL_ARC_MAX_STEPS = 60

    STALE_S = 1800.0
    TARGET_MIN_SEP_DEG = 1.0

    OB_LABEL_DY_PX = 40
    OB_BAR_DY_PX = 31
    TEL_LABEL_DY_PX = -14
    OB_BAR_W_PX = 30
    OB_BAR_H_PX = 3
    OB_WARN_FACTOR = 1.0
    OB_DANGER_FACTOR = 1.25

    PING_PERIOD_S = 2.0
    PING_RINGS = 3
    PING_R0_PX = 8.0
    PING_GROW_PX = 24.0

    PARKED_ALPHA = 0.6
    PARKED_LABEL_DY_PX = 14
    PARK_TOL_DEG = 1.0
    LABEL_STEP_PX = 16.0
    LABEL_MAX_STEPS = 6
    CAM_DY_PX = 15.0
    CAM_W_PX = 17.0
    CAM_H_PX = 12.0
    RETICLE_R_PX = 7.0
    COVER_X_SIZE = 85.0

    DOME_WEDGE_DEG = 16.0
    DOME_LANE_GAP = 0.25
    WIND_ARROW_R0 = R_DOME_TOP + 1.6
    WIND_ARROW_R1 = R_HORIZON + 1.0
    WIND_LABEL_R = R_MAX - 2.0
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
    INT_STATUS = {'dome_shutter': 'dome.shutterstatus',
                  'cover_state': 'covercalibrator.coverstate',
                  'camera_state': 'camera.camerastate',
                  'fw_position': 'filterwheel.position'}
    CAMERA_EXPOSING = 2
    COVER_CLOSED = 1
    DOME_OPEN = 0

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
                'camera_state': None, 'fw_position': None, 'cover_state': None,
                'ob': None, 'plan': None,
                'trail': deque(maxlen=self.TRAIL_MAX_POINTS),
            }
            for tel in self.telescopes
        }
        self._astro: Dict[str, Any] = {}
        self._label_boxes: List[Any] = []
        self._min_alt: Optional[float] = None
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

    def _radius(self, alt_deg: float) -> float:
        """Altitude to plot radius - the single projection used everywhere.

        Deliberately non-linear: sky above ``obs_min_alt`` is what the
        telescopes can actually use, so it gets ``R_USEFUL`` of the disc,
        while the unusable wedge under it is squeezed into the rim and
        everything below the horizon into the dome band. Altitude rings
        therefore come out unevenly spaced.
        """
        min_alt = self._obs_min_alt()
        if alt_deg >= min_alt:
            return R_USEFUL * (90.0 - alt_deg) / max(1.0, 90.0 - min_alt)
        if alt_deg >= 0.0:
            return R_USEFUL + (R_HORIZON - R_USEFUL) * (min_alt - alt_deg) / max(1.0, min_alt)
        return R_HORIZON + R_BELOW_SPAN * min(1.0, -alt_deg / 90.0)

    def _deg_scale(self) -> float:
        """Plot radius units per degree in the observable part of the sky."""
        return R_USEFUL / max(1.0, 90.0 - self._obs_min_alt())

    def _obs_min_alt(self) -> float:
        if self.obs_min_alt_deg is not None:
            return self.obs_min_alt_deg
        if self._min_alt is not None:
            return self._min_alt
        limits = []
        for tel in self.telescopes:
            path = tuple(tel if k == '{tel}' else k for k in self.MOUNT_CFG_PATH)
            value = _as_float(self._cfg(path + ('obs_min_alt',)))
            if value is not None:
                limits.append(value)
        # most restrictive mount wins, so the ring promises no unreachable sky
        value = max(limits) if limits else self.OBS_MIN_ALT_DEFAULT_DEG
        if getattr(self.main_window, 'nats_cfg', None):
            self._min_alt = value
        return value

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
            for key, suffix in self.INT_STATUS.items():
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
                # the 10 min mean is what the limits are set against, gusts
                # would flip the arrow colour on every squall
                speed = _as_float(msm.get('wind_10min_ms'))
                if speed is None:
                    speed = _as_float(msm.get('wind_ms'))
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
        self._label_boxes = []
        ax.set_facecolor(self._sky_facecolor())
        ax.set_theta_zero_location('N')
        ax.set_theta_direction(-1)
        ax.set_ylim(0.0, R_MAX)

        ax.set_xticks(np.radians(np.arange(0, 360, 45)))
        ax.set_xticklabels(['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'])
        rings = [a for a in (30, 45, 60, 75) if a > self._obs_min_alt() + 3.0][-3:]
        ax.set_rticks([self._radius(a) for a in reversed(rings)])
        ax.set_yticklabels([])
        ax.tick_params(colors=COLOR_GRID_TEXT, labelsize=9, pad=-13)
        ax.grid(True, color=COLOR_GRID, linewidth=0.7, alpha=0.85)
        ax.spines['polar'].set_color(ck.SPINE)

        ax.bar(0.0, R_MAX - R_HORIZON, width=2 * np.pi, bottom=R_HORIZON,
               color=COLOR_RING_BG, alpha=0.9, linewidth=0, zorder=0)
        r_min = self._radius(self._obs_min_alt())
        ax.bar(0.0, R_HORIZON - r_min, width=2 * np.pi, bottom=r_min,
               color=ck.COLOR_DANGER, alpha=0.09, linewidth=0, zorder=0)
        ring = np.linspace(0.0, 2 * np.pi, 181)
        ax.plot(ring, np.full_like(ring, R_HORIZON), color=COLOR_HORIZON,
                linewidth=1.1, alpha=0.9, zorder=2)
        ax.plot(ring, np.full_like(ring, r_min), color=ck.COLOR_DANGER,
                linewidth=1.0, linestyle='--', alpha=0.6, zorder=2)

        for alt in rings:
            ax.text(np.radians(22.5), self._radius(alt), f'{alt}°',
                    color=COLOR_GRID_TEXT, fontsize=8, alpha=0.85,
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
            theta, r = _theta(sun['az']), self._radius(sun['alt'])
            up = sun['alt'] > 0.0
            ax.scatter([theta], [r], s=700, c=[COLOR_SUN], linewidths=0,
                       alpha=0.16 if up else 0.06, zorder=3)
            ax.scatter([theta], [r], s=150, c=[COLOR_SUN], edgecolors='#8a6a12',
                       linewidths=0.8, alpha=1.0 if up else 0.45, zorder=7)
            self._place_label(ax, (theta, r), 'SUN', (0, -24), ha='center',
                              color=COLOR_SUN, fontsize=8.5, alpha=0.95, zorder=11)

        moon = self._astro.get('moon')
        if moon is not None:
            theta, r = _theta(moon['az']), self._radius(moon['alt'])
            up = moon['alt'] > 0.0
            face = ck.blend_colors(COLOR_MOON_DARK, COLOR_MOON_LIT, moon['phase'])
            self._draw_moon_zone(ax, moon)
            ax.scatter([theta], [r], s=120, c=[face], edgecolors=COLOR_MOON_LIT,
                       linewidths=0.8, alpha=1.0 if up else 0.4, zorder=7)
            self._place_label(ax, (theta, r), f"MOON {moon['phase'] * 100:.0f}%",
                              (0, -24), ha='center', color=COLOR_MOON_LIT,
                              fontsize=9, fontweight='bold',
                              alpha=0.95 if up else 0.6, zorder=11)

    def _draw_moon_zone(self, ax, moon: Dict[str, float]) -> None:
        avoid = self._moon_avoid()
        if moon['alt'] < -avoid:
            return
        try:
            box = ax.get_window_extent()
            px, py = ax.transData.transform((_theta(moon['az']), self._radius(moon['alt'])))
        except (ValueError, AttributeError, RuntimeError):
            return
        if not box.width or not box.height:
            return
        # a plain screen circle - the true small circle would come out a lens
        f = 1.0 / box.width
        radius = avoid * self._deg_scale() * (box.width / 2.0) / R_MAX * f
        zone = Circle(((px - box.x0) * f, (py - box.y0) / box.height), radius,
                      transform=ax.transAxes, facecolor=COLOR_MOON_ZONE,
                      edgecolor=COLOR_MOON_ZONE, linewidth=0.8, alpha=0.18,
                      zorder=1)
        zone.set_clip_path(Circle((0.5, 0.5), 0.5 * R_HORIZON / R_MAX,
                                  transform=ax.transAxes))
        ax.add_patch(zone)

    def _pt(self, px: float) -> float:
        """Pixels to points - annotation offsets are in points, every glyph
        size in this page is in pixels."""
        return px * 0.72

    def _place_label(self, ax, xy, text: str, offset, **kwargs):
        """Annotation that steps away from the anchor until it stops colliding
        with the labels already placed in this frame."""
        ann = ax.annotate(text, xy, textcoords='offset points',
                          xytext=(self._pt(offset[0]), self._pt(offset[1])), **kwargs)
        try:
            renderer = self.canvas.get_renderer()
        except (AttributeError, RuntimeError):
            return ann
        dx, dy = offset
        away = 1.0 if dy >= 0 else -1.0
        box = None
        for step in range(self.LABEL_MAX_STEPS):
            ann.set_position((self._pt(dx),
                              self._pt(dy + away * step * self.LABEL_STEP_PX)))
            try:
                bb = ann.get_window_extent(renderer)
            except (RuntimeError, ValueError):
                return ann
            box = (bb.x0, bb.y0, bb.x1, bb.y1)
            if not any(_boxes_overlap(box, taken) for taken in self._label_boxes):
                break
        if box is not None:
            self._label_boxes.append(box)
        return ann

    def _is_parked(self, tel: str) -> bool:
        st = self._state[tel]
        if st['tracking'] or st['slewing'] or st['alt'] is None:
            return False
        mount = tuple(tel if k == '{tel}' else k for k in self.MOUNT_CFG_PATH)
        park_alt = _as_float(self._cfg(mount + ('park_alt',)))
        if park_alt is None or abs(st['alt'] - park_alt) > self.PARK_TOL_DEG:
            return False
        park_az = _as_float(self._cfg(mount + ('park_az',)))
        if park_az is None or st['az'] is None:
            return True
        return abs((st['az'] - park_az + 180.0) % 360.0 - 180.0) <= self.PARK_TOL_DEG

    def _screen_pos(self, ax, theta: float, r: float):
        """Sky point as (x, y, x-scale, y-scale) in axes fractions, so glyphs
        can be sized in pixels instead of degrees."""
        try:
            box = ax.get_window_extent()
            px, py = ax.transData.transform((theta, r))
        except (ValueError, AttributeError, RuntimeError):
            return None
        if not box.width or not box.height:
            return None
        scale = self.figure.dpi / 100.0
        fx, fy = 1.0 / box.width, 1.0 / box.height
        return ((px - box.x0) * fx, (py - box.y0) * fy,
                fx * scale, fy * scale)

    def _draw_telescope(self, ax, tel: str) -> None:
        st = self._state[tel]
        az, alt = st['az'], st['alt']
        if az is None or alt is None:
            return
        color = self._tel_color(tel)
        stale = self._is_stale(st)
        theta, r = _theta(az), self._radius(alt)

        trail = list(st['trail'])
        if len(trail) > 1:
            thetas, radii, ages = self._arc_trail(trail)
            keep = self._thin_by_screen(ax, thetas, radii)
            fresh = np.clip(1.0 - ages[keep] / self.trail_seconds, 0.0, 1.0)
            rgba = np.array([to_rgba(color, alpha=0.60 * f ** 2.0) for f in fresh])
            ax.scatter(thetas[keep], radii[keep], s=1.0 + 42.0 * fresh ** 2.4,
                       c=rgba, edgecolors='none', zorder=4)

        target = (self._astro.get('targets') or {}).get(tel)
        label_theta, label_r = theta, r
        if target is not None and not stale:
            t_theta, t_r = _theta(target['az']), self._radius(target['alt'])
            label_theta, label_r = t_theta, t_r
            if _angular_sep(az, alt, target['az'],
                            target['alt']) > self.TARGET_MIN_SEP_DEG:
                self._draw_reticle(ax, t_theta, t_r, color)

        if st['tracking'] and not stale:
            self._draw_ping(ax, theta, r, color)

        parked = self._is_parked(tel)
        dim = self.PARKED_ALPHA if parked else 1.0
        ax.scatter([theta], [r], s=120, c=['none'] if stale else [color],
                   edgecolors=[color], linewidths=1.8,
                   alpha=0.4 if stale else dim, zorder=9)

        if st['cover_state'] == self.COVER_CLOSED and not stale:
            self._draw_cover_cross(ax, theta, r, dim, color)

        self._place_label(ax, (theta, r), tel, (0, self.TEL_LABEL_DY_PX),
                          ha='center', va='top', color=color, fontsize=8.5,
                          fontweight='bold',
                          alpha=0.45 if stale else dim, zorder=11)

        if stale:
            return
        if parked:
            self._place_label(ax, (theta, r), 'PARKED',
                              (0, self.PARKED_LABEL_DY_PX), ha='center',
                              va='bottom', color=color, fontsize=8.5,
                              fontweight='bold', alpha=dim, zorder=11)

        obj, progress, active = self._ob_progress(tel)
        if active and obj:
            self._place_label(ax, (label_theta, label_r), obj,
                              (0, self.OB_LABEL_DY_PX), ha='center', color=color,
                              fontsize=8.5, alpha=dim, zorder=11)
        if active and progress is not None:
            self._draw_progress_bar(ax, label_theta, label_r, progress, color)
        if st['camera_state'] == self.CAMERA_EXPOSING:
            self._draw_camera(ax, label_theta, label_r, dim,
                              self._filter_name(tel))

    def _arc_trail(self, trail):
        """Sampled positions densified along great-circle arcs. The mount only
        reports about once a second, so the raw samples alone would leave a few
        scattered dots instead of a tail curving the way the mount swept."""
        now = time.time()
        thetas, radii, ages = [], [], []
        for (t0, az0, alt0), (t1, az1, alt1) in zip(trail, trail[1:]):
            sep = _angular_sep(az0, alt0, az1, alt1)
            steps = max(1, min(self.TRAIL_ARC_MAX_STEPS,
                               int(sep / self.TRAIL_ARC_STEP_DEG)))
            for i in range(steps):
                f = i / steps
                az, alt = _slerp_altaz(az0, alt0, az1, alt1, f)
                thetas.append(_theta(az))
                radii.append(self._radius(alt))
                ages.append(now - (t0 + (t1 - t0) * f))
        t, az, alt = trail[-1]
        thetas.append(_theta(az))
        radii.append(self._radius(alt))
        ages.append(now - t)
        return np.array(thetas), np.array(radii), np.array(ages)

    def _thin_by_screen(self, ax, thetas, radii):
        """Indices of trail points at least ``TRAIL_DOT_SEP_PX`` apart on
        screen, newest first, so a fast slew leaves separate dots instead of
        one smeared stripe."""
        try:
            pts = ax.transData.transform(np.column_stack([thetas, radii]))
        except (ValueError, AttributeError, RuntimeError):
            return np.arange(len(thetas))
        sep = self.TRAIL_DOT_SEP_PX * self.figure.dpi / 100.0
        keep, last = [], None
        for i in range(len(pts) - 1, -1, -1):
            if last is None or math.hypot(pts[i][0] - last[0],
                                          pts[i][1] - last[1]) >= sep:
                keep.append(i)
                last = pts[i]
        return np.array(keep[::-1], dtype=int)

    def _draw_reticle(self, ax, theta: float, r: float, color: str) -> None:
        pos = self._screen_pos(ax, theta, r)
        if pos is None:
            return
        cx, cy, fx, fy = pos
        rad = self.RETICLE_R_PX
        ax.add_patch(Circle((cx, cy), rad * fx, transform=ax.transAxes,
                            facecolor='none', edgecolor=color, linewidth=1.3,
                            alpha=0.9, zorder=8, clip_on=False))
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ax.plot([cx + dx * 0.4 * rad * fx, cx + dx * 1.8 * rad * fx],
                    [cy + dy * 0.4 * rad * fy, cy + dy * 1.8 * rad * fy],
                    transform=ax.transAxes, color=color, linewidth=1.3,
                    alpha=0.9, zorder=8, clip_on=False)

    def _draw_cover_cross(self, ax, theta: float, r: float, dim: float,
                          color: str) -> None:
        """Closed mirror cover - the same thin cross marker the target
        reticle used to use, darkened so it reads on the filled dot."""
        ax.scatter([theta], [r], marker='x', s=self.COVER_X_SIZE,
                   c=[ck.blend_colors(color, '#000000', 0.45)],
                   linewidths=1.9, alpha=dim, zorder=10, clip_on=False)

    def _draw_ping(self, ax, theta: float, r: float, color: str) -> None:
        pos = self._screen_pos(ax, theta, r)
        if pos is None:
            return
        cx, cy, fx, _ = pos
        phase = (time.time() % self.PING_PERIOD_S) / self.PING_PERIOD_S
        for k in range(self.PING_RINGS):
            grow = (phase + k / self.PING_RINGS) % 1.0
            ax.add_patch(Circle(
                (cx, cy), (self.PING_R0_PX + self.PING_GROW_PX * grow) * fx,
                transform=ax.transAxes, facecolor='none', edgecolor=color,
                linewidth=1.3, alpha=0.50 * (1.0 - grow), zorder=3, clip_on=False))

    def _draw_camera(self, ax, theta: float, r: float, dim: float,
                     filter_name: Optional[str]) -> None:
        pos = self._screen_pos(ax, theta, r)
        if pos is None:
            return
        cx, cy, fx, fy = pos
        w, h = self.CAM_W_PX, self.CAM_H_PX
        gap, text_w = 3.0, (9.0 if filter_name else -3.0)
        total = w + gap + text_w
        x0 = cx - (total / 2.0) * fx
        y0 = cy + self.CAM_DY_PX * fy
        alpha = 0.9 * dim
        hole = ck.BG_FIGURE
        ax.add_patch(FancyBboxPatch(
            (x0 + 0.22 * w * fx, y0 + 0.98 * h * fy), 0.32 * w * fx, 0.20 * h * fy,
            boxstyle=f'round,pad=0,rounding_size={0.9 * fx}',
            transform=ax.transAxes, facecolor=COLOR_ICON, edgecolor='none',
            alpha=alpha, zorder=10, clip_on=False))
        ax.add_patch(FancyBboxPatch(
            (x0, y0), w * fx, h * fy,
            boxstyle=f'round,pad=0,rounding_size={2.2 * fx}',
            transform=ax.transAxes, facecolor=COLOR_ICON, edgecolor='none',
            alpha=alpha, zorder=10, clip_on=False))
        ax.add_patch(Circle((x0 + 0.5 * w * fx, y0 + 0.48 * h * fy), 0.27 * w * fx,
                            transform=ax.transAxes, facecolor=hole,
                            edgecolor='none', alpha=alpha, zorder=11, clip_on=False))
        ax.add_patch(Circle((x0 + 0.5 * w * fx, y0 + 0.48 * h * fy), 0.13 * w * fx,
                            transform=ax.transAxes, facecolor=COLOR_ICON,
                            edgecolor='none', alpha=alpha, zorder=12, clip_on=False))
        ax.add_patch(Circle((x0 + 0.83 * w * fx, y0 + 0.76 * h * fy), 0.06 * w * fx,
                            transform=ax.transAxes, facecolor=hole,
                            edgecolor='none', alpha=alpha, zorder=11, clip_on=False))
        if filter_name:
            # in axes fractions like the icon itself, so the two stay aligned
            ax.text(x0 + (w + gap) * fx, y0 + 0.5 * h * fy, filter_name,
                    transform=ax.transAxes, ha='left', va='center',
                    color=COLOR_ICON, fontsize=8.5, fontweight='bold',
                    alpha=alpha, zorder=11, clip_on=False)

    def _filter_name(self, tel: str) -> Optional[str]:
        pos = self._state[tel]['fw_position']
        if pos is None or pos < 0:
            return None
        filters = self._cfg(('config', 'telescopes', tel, 'observatory',
                             'components', 'filterwheel', 'filters'))
        try:
            names = [f['name'] for f in sorted(filters, key=lambda x: x['position'])]
            return names[pos]
        except (LookupError, TypeError, ValueError):
            return None

    def _draw_progress_bar(self, ax, theta: float, r: float, progress: float,
                           color: str) -> None:
        pos = self._screen_pos(ax, theta, r)
        if pos is None:
            return
        cx, cy, fx, fy = pos
        w, h = self.OB_BAR_W_PX * fx, self.OB_BAR_H_PX * fy
        x0 = cx - w / 2.0
        y0 = cy + self.OB_BAR_DY_PX * fy

        # past its expected time the OB runs long - amber, then red, instead
        # of the bar quietly stalling at full
        if progress > self.OB_DANGER_FACTOR:
            fill_color = ck.COLOR_DANGER
        elif progress > self.OB_WARN_FACTOR:
            fill_color = ck.COLOR_WARN
        else:
            fill_color = color
        ax.add_patch(Rectangle((x0, y0), w, h, transform=ax.transAxes,
                               color='#5e5e5e', alpha=0.85, linewidth=0,
                               clip_on=False, zorder=10))
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
        az = st['dome_az']
        if az is None:
            return
        bottom, height = self._dome_lane(tel)
        color = self._tel_color(tel)
        shut = shutter != self.DOME_OPEN
        ax.bar(_theta(az), height, width=math.radians(self.DOME_WEDGE_DEG),
               bottom=bottom, facecolor=color if shut else 'none',
               edgecolor=color, linewidth=1.5,
               alpha=0.75 if shut else 1.0, zorder=2)

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
        # hung off the outer end of the arrow; the plate keeps it legible
        # wherever it lands
        ax.text(theta, self.WIND_LABEL_R, f'{speed:.1f} m/s', color=color,
                fontsize=9, fontweight='bold', ha='center', va='center',
                bbox=dict(facecolor=ck.BG_FIGURE, edgecolor='none',
                          boxstyle='round,pad=0.2', alpha=0.65),
                zorder=12)


widget_class = RadarWidget
