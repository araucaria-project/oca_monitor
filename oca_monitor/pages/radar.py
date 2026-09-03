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
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.colors import to_rgba
from matplotlib.figure import Figure
from matplotlib.patches import Circle, FancyBboxPatch, Polygon, Rectangle
from qasync import asyncSlot
from serverish.base import dt_from_array
from serverish.base.task_manager import create_task
from serverish.messenger import get_reader

from oca_monitor.utils.ephem_ocm import (OCM_ELEVATION_M, OCM_LATITUDE,
                                         OCM_LONGITUDE, location,
                                         sidereal_time_deg)
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
COLOR_GRID = '#5c5c5c'
# the compass spokes carry more of the reading than the altitude rings
# do, so they are drawn a shade above them
COLOR_GRID_AZ = '#6e6e6e'
COLOR_GRID_TEXT = '#bcbcbc'
COLOR_RING_BG = '#151515'
COLOR_HORIZON = '#949494'
TWILIGHT_ALT_DEG = -18.0

COLOR_SUN = '#ffd24a'
COLOR_MOON_LIT = '#eef2f7'
COLOR_MOON_DARK = '#3a3f47'
COLOR_MOON_ZONE = '#7fa8ff'
COLOR_ICON = '#d8dde3'
# the equatorial grid: navy, kept dim on purpose - it is there to orient the
# eye, never to compete with a telescope, a target or the Moon zone
COLOR_RADEC = '#4b5c99'
COLOR_RADEC_TEXT = '#7c8cc9'
# the galactic plane: cyan, faint and dashed, so it reads as one more piece of
# scenery over the navy grid rather than as anything to be observed
COLOR_GALACTIC = '#22d3ee'
COLOR_WIND_TRACK = '#4d4d4d'
COLOR_COVER_CROSS = '#000000'


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


def _program_coords(program: str) -> Optional[Tuple[str, str, str]]:
    """(name, ra, dec) out of an ``OBJECT <name> <ra> <dec> ...`` block."""
    parts = program.split()
    if len(parts) >= 4 and parts[0] == 'OBJECT':
        return parts[1], parts[2], parts[3]
    return None


def _program_uobi(program: str) -> Optional[str]:
    """The OB id the program carries, which names its entry in the plan."""
    for part in program.split():
        if part.startswith('uobi='):
            return part[len('uobi='):] or None
    return None


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


# North galactic pole and the galactic longitude of the north celestial pole,
# J2000 (Reid & Brunthaler 2004)
GAL_POLE_RA = 192.85948
GAL_POLE_DEC = 27.12825
GAL_NCP_L = 122.93192


def _radec_from_galactic(l_deg, b_deg=0.0):
    """Galactic (l, b) to J2000 (RA, Dec), in degrees. Array-friendly.

    J2000 rather than of the date on purpose: the plane is scenery, and the
    precession since J2000 is a fraction of a pixel on the disc.
    """
    b = np.radians(np.asarray(b_deg, dtype=float))
    dl = math.radians(GAL_NCP_L) - np.radians(np.asarray(l_deg, dtype=float))
    pole = math.radians(GAL_POLE_DEC)
    sin_dec = (np.sin(b) * math.sin(pole)
               + np.cos(b) * math.cos(pole) * np.cos(dl))
    dec = np.degrees(np.arcsin(np.clip(sin_dec, -1.0, 1.0)))
    ra = GAL_POLE_RA + np.degrees(np.arctan2(
        np.cos(b) * np.sin(dl),
        np.sin(b) * math.cos(pole) - np.cos(b) * math.sin(pole) * np.cos(dl)))
    return ra % 360.0, dec


def _altaz_from_hadec(ha_deg, dec_deg, lat_deg: float):
    """Hour angle/declination to (azimuth from N through E, altitude), in
    degrees. Array-friendly: the equatorial grid pushes a few thousand points
    through it at once."""
    ha = np.radians(np.asarray(ha_deg, dtype=float))
    dec = np.radians(np.asarray(dec_deg, dtype=float))
    lat = math.radians(lat_deg)
    sin_alt = (np.sin(dec) * math.sin(lat)
               + np.cos(dec) * math.cos(lat) * np.cos(ha))
    alt = np.degrees(np.arcsin(np.clip(sin_alt, -1.0, 1.0)))
    az = np.degrees(np.arctan2(
        -np.cos(dec) * np.sin(ha),
        np.sin(dec) * math.cos(lat) - np.cos(dec) * math.sin(lat) * np.cos(ha)))
    return az % 360.0, alt


def _angular_sep(az1: float, alt1: float, az2: float, alt2: float) -> float:
    a1, a2 = math.radians(alt1), math.radians(alt2)
    d_az = math.radians(az1 - az2)
    cos_sep = math.sin(a1) * math.sin(a2) + math.cos(a1) * math.cos(a2) * math.cos(d_az)
    return math.degrees(math.acos(max(-1.0, min(1.0, cos_sep))))


class RadarWidget(QWidget):

    REFRESH_S = 0.5
    ASTRO_REFRESH_S = 5.0
    ALMANAC_REFRESH_S = 60.0

    TRAIL_SECONDS = 20.0  # how long a mount leaves a fading trail behind it
    TRAIL_MIN_STEP_DEG = 0.03
    TRAIL_MAX_POINTS = 400
    TRAIL_DOT_SEP_PX = 13.0
    TRAIL_ARC_STEP_DEG = 0.25
    TRAIL_ARC_MAX_STEPS = 60
    TRAIL_HEAD_D_PX = 10.0
    TRAIL_TAIL_D_PX = 1.4
    TRAIL_HEAD_ALPHA = 0.80
    TRAIL_TAIL_ALPHA = 0.15
    TRAIL_SIZE_POW = 2.2
    TRAIL_ALPHA_POW = 3.0
    TRAIL_FADE_SHRINK_POW = 2.0

    STALE_S = 1800.0
    TARGET_MIN_SEP_DEG = 1.0
    BODY_HIDE_ALT_DEG = -10.0

    OB_LABEL_DY_PX = 40
    OB_BAR_DY_PX = 31
    TEL_LABEL_DY_PX = -18
    OB_BAR_W_PX = 30
    OB_BAR_H_PX = 3
    OB_WARN_FACTOR = 1.0
    OB_DANGER_FACTOR = 1.25

    PING_PERIOD_S = 2.0
    PING_RINGS = 3
    PING_R0_PX = 8.0
    PING_GROW_PX = 24.0
    PING_LW_PX = 1.7
    PING_ALPHA = 0.68
    # a ring at full brightness the moment it appears pops out of the marker,
    # so it swells in over the first slice of its life and then fades on a
    # square root, which holds it visible for most of the way out
    PING_FADE_IN = 0.18

    PARKED_ALPHA = 0.6
    PARKED_LABEL_DY_PX = 14
    # Mounts standing on the same spot cannot all show their marks at once, so
    # the overlapping ones take turns, TEL_SHARE_PERIOD_S each. The separation
    # is the width of the widest mark, the camera glyph: closer than that and
    # one telescope's readings are drawn over another's.
    TEL_SHARE_PERIOD_S = 3.0
    TEL_SHARE_SEP_PX = 16.5
    LABEL_STEP_PX = 16.0
    LABEL_MAX_STEPS = 6
    # the telescope name, PARKED, the observed object and the filter are one
    # family of readings around a mount's mark, so they share one size; SUN
    # and MOON follow it too, the Moon a shade larger for its phase reading
    MARK_FONTSIZE = 7.5
    CAM_DY_PX = 15.0
    CAM_W_PX = 15.0
    CAM_H_PX = 10.6
    RETICLE_R_PX = 7.0
    COVER_X_SIZE = 85.0

    DOME_WEDGE_DEG = 16.0
    DOME_LANE_GAP = 0.25
    WIND_ARROW_R0 = R_DOME_TOP + 1.6
    WIND_ARROW_R1 = R_HORIZON + 1.0
    WIND_LABEL_R = R_MAX - 2.0
    # calm, over the warn limit, over the danger limit: the reading grows with
    # the risk, so a dangerous wind is legible from across the control room
    WIND_LABEL_FONTSIZES = (9.0, 11.0, 13.0)
    MOON_AVOID_DEFAULT_DEG = 30.0
    MOON_ZONE_POINTS = 181
    OBS_MIN_ALT_DEFAULT_DEG = 35.0

    # Equatorial grid. Sparse on purpose - hour circles every 3 h and
    # parallels every 30 deg say which way the sky turns without turning the
    # disc into graph paper. Rebuilt every RADEC_REFRESH_S: the sky drifts
    # 0.25 deg/min, so a 10 s old grid is under 0.05 deg stale.
    RADEC_RA_STEP_H = 3.0
    RADEC_DEC_STEP_DEG = 30.0
    # compass labels: (text, azimuth, dx px, dy px) measured from the rim.
    # all four sit the same distance inside it, each slid sideways off its own
    # spoke so no letter straddles a line
    COMPASS_LABELS = (('N', 0.0, 7, -13), ('E', 90.0, -13, 7),
                      ('S', 180.0, 7, 13), ('W', 270.0, 13, 7))

    RADEC_SAMPLE_DEG = 1.0
    RADEC_REFRESH_S = 10.0
    # hour numbers ride the Dec -60 parallel, a compact RA scale around the
    # pole; the Dec numbers sit out in the unusable band, east of the meridian
    RADEC_RA_LABEL_DEC = -60.0
    RADEC_RA_LABEL_MIN_ALT = 3.0
    RADEC_LABEL_SEP = 6.0

    # the galactic plane rides along with that grid, on the same cache
    GALACTIC_SAMPLE_DEG = 1.0
    GALACTIC_LABEL = 'galactic plane'
    # a two-word name is far wider than an hour number, so it keeps its own,
    # roomier distance from whatever is already written on the disc
    GALACTIC_LABEL_SEP = 16.0
    # how far up from the lowest point of the line the name may be slid to
    # dodge a grid number and still count as lying at the bottom of the disc
    GALACTIC_LABEL_SPAN = 12.0

    MOON_AVOID_CFG_PATH = ('config', 'site', 'global', 'obs_limits', 'ephem',
                           'full_moon_distance')
    SITE_GEO_CFG_PATH = ('config', 'site', 'global', 'geo_location')
    WIND_CFG_PATH = ('config', 'site', 'global', 'obs_limits',
                     'weather_restrictions', 'wind')
    MOUNT_CFG_PATH = ('config', 'telescopes', '{tel}', 'observatory',
                      'components', 'mount')
    TELESCOPES_CFG_PATH = ('config', 'telescopes')
    # observatory config flag that tells a real, observing telescope from a
    # simulator or a decommissioned one ('dev', 'disabled')
    PRODUCTION_FLAG = 'production'

    MOUNT_TELEMETRY = {'az': 'mount.azimuth', 'alt': 'mount.altitude'}
    DOME_TELEMETRY = {'dome_az': 'dome.azimuth'}
    MOUNT_STATUS = {'slewing': 'mount.slewing',
                    'tracking': 'mount.tracking',
                    'motors': 'mount.motorstatus',
                    # not published today; read anyway, so the park state stops
                    # being guessed the moment TIC starts forwarding it
                    'atpark': 'mount.atpark'}
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
        # an explicit list in settings.toml wins; with none, the observatory
        # config decides once it arrives - see _resolve_telescopes_from_config
        self._telescopes_pinned = bool(telescopes)
        self.trail_seconds = float(trail_seconds or self.TRAIL_SECONDS)
        self.subject = subject
        self.wind_warn_ms = _as_float(wind_warn_ms)
        self.wind_danger_ms = _as_float(wind_danger_ms)
        self.moon_avoid_deg = _as_float(moon_avoid_deg)
        self.obs_min_alt_deg = _as_float(obs_min_alt_deg)

        self._state: Dict[str, Dict[str, Any]] = {
            tel: self._blank_state() for tel in self.telescopes}
        self._astro: Dict[str, Any] = {}
        self._label_boxes: List[Any] = []
        self._min_alt: Optional[float] = None
        self._wind: Dict[str, Optional[float]] = {'ms': None, 'dir': None}
        self._radec_cache: Optional[Tuple[float, Tuple[List, List, List, List]]] = None

        self._init_ui()
        QtCore.QTimer.singleShot(0, self.async_init)
        logger.info(f"RadarWidget init setup done for {', '.join(self.telescopes)}")

    def _blank_state(self) -> Dict[str, Any]:
        return {
            'az': None, 'alt': None, 'pos_dt': None,
            'slewing': None, 'tracking': None, 'motors': None,
            'atpark': None,
            'dome_az': None, 'dome_shutter': None,
            'camera_state': None, 'fw_position': None, 'cover_state': None,
            'ob': None, 'plan': None,
            'trail': deque(maxlen=self.TRAIL_MAX_POINTS),
            'trail_done_t': None,
        }

    def _resolve_telescopes(self, telescopes: Optional[List[str]]) -> List[str]:
        if isinstance(telescopes, str):
            telescopes = [t.strip() for t in telescopes.split(',') if t.strip()]
        if telescopes:
            return list(telescopes)
        return list(getattr(self.main_window, 'telescope_names', []) or [])

    async def _resolve_telescopes_from_config(self) -> None:
        """Draw whatever the observatory config flags as ``production``.

        The radar should not carry its own telescope list: mounts come and go
        (wg25 is 'disabled', sim and dev are simulators) and the observatory
        config is the one place that says which are real. Panels are built
        during MainWindow.__init__, before its single_read on
        ``tic.config.observatory`` returns, so the list cannot be known at
        construction time - wait for the config here, the same way the charts
        wait for their colours. Until then (or if it never arrives) the
        fallback from _resolve_telescopes stands.
        """
        if self._telescopes_pinned:
            return
        for _ in range(120):  # ~60 s of patience, then give up
            telescopes = self._cfg(self.TELESCOPES_CFG_PATH)
            if isinstance(telescopes, dict) and telescopes:
                break
            await asyncio.sleep(0.5)
        else:
            logger.warning(f'radar: observatory config never arrived, keeping '
                           f'{", ".join(self.telescopes) or "no telescopes"}')
            return
        production = [tel for tel, cfg in telescopes.items()
                      if self.PRODUCTION_FLAG in
                      ((cfg or {}).get('observatory') or {}).get('flags', ())]
        if not production:
            logger.warning(f'radar: no telescope flagged '
                           f'{self.PRODUCTION_FLAG!r} in the observatory '
                           f'config, keeping {", ".join(self.telescopes)}')
            return
        self.telescopes = production
        self._state = {tel: self._blank_state() for tel in self.telescopes}
        logger.info(f'radar: telescopes from observatory config '
                    f'({self.PRODUCTION_FLAG}): {", ".join(self.telescopes)}')

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

    def _site_geo(self) -> Tuple[float, float, float]:
        """(latitude, longitude, elevation) of the site, straight from the
        observatory config - ``site.global.geo_location``. Falls back to the
        OCM constants in ephem_ocm while the config has not arrived yet."""
        geo = self._cfg(self.SITE_GEO_CFG_PATH)
        geo = geo if isinstance(geo, dict) else {}
        lat = _as_float(geo.get('lat'))
        lon = _as_float(geo.get('lon'))
        elev = _as_float(geo.get('elev'))
        if lat is None or lon is None:
            return OCM_LATITUDE, OCM_LONGITUDE, OCM_ELEVATION_M
        return lat, lon, OCM_ELEVATION_M if elev is None else elev

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

    def _radius_arr(self, alt_deg):
        """``_radius`` over a numpy array - same projection, one pass, for the
        few thousand grid samples rebuilt on every grid refresh."""
        alt = np.asarray(alt_deg, dtype=float)
        min_alt = self._obs_min_alt()
        above = R_USEFUL * (90.0 - alt) / max(1.0, 90.0 - min_alt)
        wedge = R_USEFUL + (R_HORIZON - R_USEFUL) * (min_alt - alt) / max(1.0, min_alt)
        below = R_HORIZON + R_BELOW_SPAN * np.minimum(1.0, -alt / 90.0)
        return np.where(alt >= min_alt, above, np.where(alt >= 0.0, wedge, below))

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
        await self._resolve_telescopes_from_config()
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
                if parsed is None:
                    # an empty reading means the source had nothing to say, not
                    # that the value became unknown: the domes publish null
                    # between reports and would otherwise blank their own
                    # position every quarter of an hour
                    continue
                self._state[tel][key] = parsed
                if position:
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

    def _plan_entry(self, tel: str,
                    uobi: Optional[str]) -> Optional[Dict[str, Any]]:
        """The plan entry a running program refers to, by its OB id.

        ``current_i`` is -1 whenever the queue is idle, and the old ``next_i``
        fallback is what put a reticle on a target nobody was observing yet, so
        it is not consulted here."""
        plan = self._state[tel].get('plan') or {}
        items = plan.get('plan') or []
        if not items:
            return None
        if uobi:
            for entry in items:
                if ((entry or {}).get('ob') or {}).get('uobi') == uobi:
                    return entry
        idx = plan.get('current_i', -1)
        if isinstance(idx, int) and 0 <= idx < len(items):
            return items[idx]
        return None

    def _program_target(self, tel: str) -> Optional[Dict[str, Any]]:
        """Where the running program points, or None when none is running.

        Same source as the telescopes page's Program column,
        tic.status.{tel}.toi.ob: no program entry, no target, so no reticle.
        Coordinates come out of the program block itself when it carries them
        and from the plan entry it names otherwise."""
        ob = self._state[tel].get('ob') or {}
        if not (ob.get('ob_started') and not ob.get('ob_done')):
            return None
        program = ob.get('ob_program') or ''
        coords = _program_coords(program)
        if coords is not None:
            name, ra, dec = coords
            return {'name': name, 'ra': ra, 'dec': dec,
                    'plan_az': None, 'plan_alt': None}
        entry = self._plan_entry(tel, _program_uobi(program)) or {}
        entry_ob = entry.get('ob') or {}
        meta = entry.get('meta') or {}
        if entry_ob.get('ra') is None or entry_ob.get('dec') is None:
            return None
        # meta az/alt are the planned coords, they drift - fallback only
        return {
            'name': entry_ob.get('name') or '',
            'ra': str(entry_ob['ra']),
            'dec': str(entry_ob['dec']),
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
                target = self._program_target(tel)
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
            az, alt = st['az'], st['alt']
            if az is None or alt is None or self._is_stale(st):
                continue
            if not trail:
                # anchor, so the next sample can tell moving from standing still
                trail.append((now, az, alt))
                st['trail_done_t'] = now
                continue
            step = _angular_sep(az, alt, trail[-1][1], trail[-1][2])
            slewing = st['slewing']
            moving = step >= self.TRAIL_MIN_STEP_DEG if slewing is None else slewing
            if moving:
                if st['trail_done_t'] is not None:
                    # a fresh slew: drop the fading one, keep where it sets off
                    start = trail[-1]
                    trail.clear()
                    trail.append(start)
                    st['trail_done_t'] = None
                if step >= self.TRAIL_MIN_STEP_DEG:
                    trail.append((now, az, alt))
            elif st['trail_done_t'] is None:
                st['trail_done_t'] = now
            elif now - st['trail_done_t'] > self.trail_seconds:
                trail.clear()

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
            return '', None, False
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

        # only the four cardinal spokes are drawn: the diagonals added lines
        # without adding orientation, so the labels are placed by hand instead
        # of as tick text, each nudged clear of its own spoke
        ax.set_xticks(np.radians(np.arange(0, 360, 90)))
        ax.set_xticklabels([])
        rings = [a for a in (30, 45, 60, 75) if a > self._obs_min_alt() + 3.0][-3:]
        ax.set_rticks([self._radius(a) for a in reversed(rings)])
        ax.set_yticklabels([])
        ax.tick_params(colors=COLOR_GRID_TEXT, labelsize=9, pad=-13)
        ax.grid(True, axis='y', color=COLOR_GRID, linewidth=0.7, alpha=0.85)
        ax.grid(True, axis='x', color=COLOR_GRID_AZ, linewidth=0.9, alpha=1.0)
        ax.spines['polar'].set_color(ck.SPINE)
        for text, az, dx, dy in self.COMPASS_LABELS:
            ax.annotate(text, xy=(np.radians(az), R_MAX), xycoords='data',
                        xytext=(dx, dy), textcoords='offset points',
                        color=COLOR_GRID_TEXT, fontsize=9,
                        ha='center', va='center', zorder=3)

        ax.bar(0.0, R_MAX - R_HORIZON, width=2 * np.pi, bottom=R_HORIZON,
               color=COLOR_RING_BG, alpha=0.9, linewidth=0, zorder=0)
        r_min = self._radius(self._obs_min_alt())
        ax.bar(0.0, R_HORIZON - r_min, width=2 * np.pi, bottom=r_min,
               color=ck.COLOR_DANGER, alpha=0.09, linewidth=0, zorder=0)
        self._draw_radec_grid(ax)
        ring = np.linspace(0.0, 2 * np.pi, 181)
        ax.plot(ring, np.full_like(ring, R_HORIZON), color=COLOR_HORIZON,
                linewidth=1.1, alpha=0.9, zorder=2)
        ax.plot(ring, np.full_like(ring, r_min), color=ck.COLOR_DANGER,
                linewidth=1.0, linestyle='--', alpha=0.6, zorder=2)

        for alt in rings:
            ax.text(np.radians(22.5), self._radius(alt), f'{alt}°',
                    color=COLOR_GRID_TEXT, fontsize=8, alpha=0.85,
                    ha='center', va='center', zorder=3)
        # the observing limit is the one ring that moves with the config, so it
        # says which altitude it stands for rather than leaving it to be guessed
        ax.text(np.radians(22.5), r_min, f'{self._obs_min_alt():g}°',
                color=ck.COLOR_DANGER, fontsize=8, alpha=0.95,
                ha='center', va='center', zorder=3)

        for tel in self.telescopes:
            self._draw_dome(ax, tel)
        self._draw_bodies(ax)
        self._draw_wind(ax)
        covered = self._share_covered(ax)
        for tel in self.telescopes:
            self._draw_telescope(ax, tel, tel in covered)

    def _draw_bodies(self, ax) -> None:
        # well below the horizon they say nothing worth the room they take in
        # the ring, where everything sunk that far piles up together anyway
        sun = self._astro.get('sun')
        if sun is not None and sun['alt'] >= self.BODY_HIDE_ALT_DEG:
            theta, r = _theta(sun['az']), self._radius(sun['alt'])
            up = sun['alt'] > 0.0
            ax.scatter([theta], [r], s=700, c=[COLOR_SUN], linewidths=0,
                       alpha=0.16 if up else 0.06, zorder=3)
            ax.scatter([theta], [r], s=150, c=[COLOR_SUN], edgecolors='#8a6a12',
                       linewidths=0.8, alpha=1.0 if up else 0.45, zorder=7)
            self._place_label(ax, (theta, r), 'SUN', (0, -24), ha='center',
                              color=COLOR_SUN, fontsize=self.MARK_FONTSIZE,
                              alpha=0.95, zorder=11)

        moon = self._astro.get('moon')
        if moon is not None and moon['alt'] >= self.BODY_HIDE_ALT_DEG:
            theta, r = _theta(moon['az']), self._radius(moon['alt'])
            up = moon['alt'] > 0.0
            face = ck.blend_colors(COLOR_MOON_DARK, COLOR_MOON_LIT, moon['phase'])
            self._draw_moon_zone(ax, moon)
            ax.scatter([theta], [r], s=120, c=[face], edgecolors=COLOR_MOON_LIT,
                       linewidths=0.8, alpha=1.0 if up else 0.4, zorder=7)
            self._place_label(ax, (theta, r), f"MOON {moon['phase'] * 100:.0f}%",
                              (0, -24), ha='center', color=COLOR_MOON_LIT,
                              fontsize=self.MARK_FONTSIZE + 0.4,
                              fontweight='bold',
                              alpha=0.95 if up else 0.6, zorder=11)

    def _draw_moon_zone(self, ax, moon: Dict[str, float]) -> None:
        """The avoidance zone as the small circle it really is.

        A screen circle would lie: the radial scale is non-linear and the
        azimuth spacing shrinks towards the zenith, so the true ``avoid``
        degrees around the Moon project to a lens that widens as the Moon
        sinks. Sampled on the sky, then pushed through the same
        ``_theta``/``_radius`` used by every other mark on this page.
        """
        avoid = self._moon_avoid()
        if moon['alt'] < -avoid:
            return
        alt0, az0 = math.radians(moon['alt']), math.radians(moon['az'])
        sep = math.radians(avoid)
        # bearing around the Moon, walked once to close the ring
        bearing = np.linspace(0.0, 2.0 * np.pi, self.MOON_ZONE_POINTS)
        alt = np.arcsin(math.sin(alt0) * math.cos(sep)
                        + math.cos(alt0) * math.sin(sep) * np.cos(bearing))
        az = az0 + np.arctan2(
            np.sin(bearing) * math.sin(sep) * math.cos(alt0),
            math.cos(sep) - math.sin(alt0) * np.sin(alt))
        # the part under the horizon is nobody's business: fold it onto the ring
        r = np.minimum([self._radius(a) for a in np.degrees(alt)], R_HORIZON)
        ax.add_patch(Polygon(np.column_stack((az, r)), closed=True,
                             facecolor=COLOR_MOON_ZONE, edgecolor=COLOR_MOON_ZONE,
                             linewidth=0.8, alpha=0.18, zorder=1))

    # ---- Equatorial grid ----------------------------------------------------

    def _radec_grid(self) -> Tuple[List, List, List, List]:
        """(polylines, labels, galactic polylines, galactic label) in plot
        coordinates.

        Cached for ``RADEC_REFRESH_S`` - the sky turns slowly, and the cache
        also lets the grid pick up a latitude or an obs limit that only
        arrives with the config, a few seconds after the first paint.
        """
        now = time.monotonic()
        if self._radec_cache is not None and now - self._radec_cache[0] < self.RADEC_REFRESH_S:
            return self._radec_cache[1]
        lat, lon, elev = self._site_geo()
        try:
            lst = sidereal_time_deg(_now_utc(), latitude=lat, longitude=lon,
                                    elevation=elev)
        except Exception as e:
            logger.warning(f'radar: no sidereal time, RA/Dec grid skipped: {e}')
            return [], [], [], []
        lines, labels = self._build_radec_grid(lst, lat)
        gal_lines, gal_labels = self._build_galactic_plane(lst, lat, labels)
        grid = (lines, labels, gal_lines, gal_labels)
        self._radec_cache = (now, grid)
        return grid

    def _build_radec_grid(self, lst_deg: float, lat_deg: float) -> Tuple[List, List]:
        lines: List = []
        labels: List = []
        step = self.RADEC_SAMPLE_DEG

        # parallels: a full turn in hour angle at fixed Dec. They do not move
        # with time at all - a parallel is a fixed circle in the horizon frame.
        # Numbered first, so a moving hour number is the one that gives way.
        ha_full = np.arange(0.0, 360.0 + 2 * step, 2 * step)
        d = self.RADEC_DEC_STEP_DEG
        for dec_v in np.arange(-90.0 + d, 90.0, d):
            lines.extend(self._grid_polylines(
                *_altaz_from_hadec(ha_full, np.full_like(ha_full, dec_v), lat_deg)))
            labels.extend(self._dec_label(
                dec_v, lat_deg, f'{dec_v:+.0f}°' if dec_v else '0°'))

        # hour circles: pole to pole at fixed RA, numbered where they cross
        # the RADEC_RA_LABEL_DEC parallel - on the plot that ring is wide
        # enough to hold every number, and it keeps the scale in one place
        dec = np.arange(-90.0, 90.0 + step, step)
        for hour in np.arange(0.0, 24.0, self.RADEC_RA_STEP_H):
            ha = lst_deg - hour * 15.0
            lines.extend(self._grid_polylines(*_altaz_from_hadec(ha, dec, lat_deg)))
            for label in self._grid_label(ha, self.RADEC_RA_LABEL_DEC, lat_deg,
                                          f'{hour:g}h',
                                          self.RADEC_RA_LABEL_MIN_ALT):
                # the hour numbers ride the Dec parallel that carries a number
                # of its own, so the two meet sooner or later - drop the hour,
                # the scale still reads by counting the gap
                if self._label_clear(labels, label[0], label[1]):
                    labels.append(label)
        return lines, labels

    def _build_galactic_plane(self, lst_deg: float, lat_deg: float,
                              labels: List) -> Tuple[List, List]:
        """The b = 0 great circle, sampled in galactic longitude and put
        through the same visibility split as the grid curves."""
        lon = np.arange(0.0, 360.0 + self.GALACTIC_SAMPLE_DEG,
                        self.GALACTIC_SAMPLE_DEG)
        ra, dec = _radec_from_galactic(lon)
        # only down to the obs limit: under that ring nothing is observable,
        # so the plane there would be scenery over scenery
        lines = self._grid_polylines(
            *_altaz_from_hadec(lst_deg - ra, dec, lat_deg),
            min_alt=self._obs_min_alt())
        return lines, self._galactic_label(lines, labels)

    def _galactic_label(self, lines: List, labels: List) -> List:
        """(theta, r, text, rotation) for the name, lying along its own line
        near the bottom of the disc.

        Bottom of the plot rather than any fixed sky coordinate: the plane
        swings right round in a day, and the low edge is the one place a
        two-word name is never across the observable middle. Rotation is taken
        from the local tangent, in plot cartesian coordinates - the polar axes
        are equal-aspect, so that angle is the display angle too.
        """
        cands: List = []
        for theta, r in lines:
            th, rr = np.asarray(theta), np.asarray(r)
            x, y = rr * np.sin(th), rr * np.cos(th)
            rot = np.degrees(np.arctan2(np.gradient(y), np.gradient(x)))
            # keep the words reading left to right whichever way the line runs
            rot = np.where(rot > 90.0, rot - 180.0, rot)
            rot = np.where(rot < -90.0, rot + 180.0, rot)
            cands.extend(zip(y.tolist(), th.tolist(), rr.tolist(), rot.tolist()))
        if not cands:
            return []
        cands.sort(key=lambda c: c[0])
        # anywhere in the lowest stretch of the line will do, so spend that
        # freedom on the flattest spot in it - at the very end of the line the
        # tangent stands the words nearly upright, which reads badly - and take
        # the first one there that is clear of a grid number
        floor = cands[0][0] + self.GALACTIC_LABEL_SPAN
        low = [c for c in cands if c[0] <= floor]
        low.sort(key=lambda c: abs(c[3]))
        for y, theta, r, rot in low:
            if self._label_clear(labels, theta, r, self.GALACTIC_LABEL_SEP):
                return [(theta, r, self.GALACTIC_LABEL, rot)]
        # nothing clear: the flattest low spot anyway, the plane outranks a number
        y, theta, r, rot = low[0]
        return [(theta, r, self.GALACTIC_LABEL, rot)]

    def _label_clear(self, labels: List, theta: float, r: float,
                     sep: Optional[float] = None) -> bool:
        """True when nothing already numbered sits within ``sep`` (by default
        ``RADEC_LABEL_SEP``) of this spot - measured across the plot, not in
        polar coordinates, where the same angle means very different
        distances."""
        sep = self.RADEC_LABEL_SEP if sep is None else sep
        x, y = r * math.sin(theta), r * math.cos(theta)
        return all(math.hypot(x - rr * math.sin(th), y - rr * math.cos(th))
                   >= sep for th, rr, _ in labels)

    def _grid_polylines(self, az, alt, min_alt: float = 0.0) -> List:
        """A sampled sky curve as the runs of it that stay above ``min_alt`` -
        the horizon for the grid, the observing limit for the galactic plane.

        Split rather than clipped: a curve that dips below the floor and comes
        back would otherwise get a chord drawn straight across the disc.
        Azimuth is unwrapped first, or a curve crossing north would be drawn
        the long way round.
        """
        r = self._radius_arr(alt)
        theta = np.unwrap(np.radians(az))
        visible = np.asarray(alt) >= min_alt
        out: List = []
        start: Optional[int] = None
        for i, up in enumerate(visible):
            if up and start is None:
                start = i
            elif not up and start is not None:
                if i - start > 1:
                    out.append((theta[start:i], r[start:i]))
                start = None
        if start is not None and len(visible) - start > 1:
            out.append((theta[start:], r[start:]))
        return out

    def _dec_label(self, dec_deg: float, lat_deg: float, text: str) -> List:
        """A parallel is numbered where it crosses the unusable band, east of
        the meridian.

        Out of the busy middle of the disc, and self-spreading: every parallel
        meets that altitude at an azimuth of its own, so the numbers walk round
        the band instead of stacking up on the meridian.
        """
        alt = math.radians(self._obs_min_alt() / 2.0)  # mid of the band
        lat, dec = math.radians(lat_deg), math.radians(dec_deg)
        denom = math.cos(dec) * math.cos(lat)
        if abs(denom) < 1e-9:
            return []
        cos_ha = (math.sin(alt) - math.sin(dec) * math.sin(lat)) / denom
        if abs(cos_ha) > 1.0:
            return []  # this parallel never reaches that altitude
        # negative hour angle: east of the meridian, the right half of the disc
        return self._grid_label(-math.degrees(math.acos(cos_ha)), dec_deg,
                                lat_deg, text, -90.0)

    def _grid_label(self, ha_deg: float, dec_deg: float, lat_deg: float,
                    text: str, min_alt: float) -> List:
        az, alt = _altaz_from_hadec(ha_deg, dec_deg, lat_deg)
        if float(alt) < min_alt:
            return []
        return [(_theta(float(az)), float(self._radius_arr(alt)), text)]

    def _draw_radec_grid(self, ax) -> None:
        lines, labels, gal_lines, gal_labels = self._radec_grid()
        for theta, r in lines:
            ax.plot(theta, r, color=COLOR_RADEC, linewidth=0.7, alpha=0.30,
                    zorder=0.5)
        for theta, r in gal_lines:
            ax.plot(theta, r, color=COLOR_GALACTIC, linewidth=0.6,
                    linestyle=(0, (5, 4)), alpha=0.40, zorder=0.55)
        for theta, r, text, rot in gal_labels:
            # rotation_mode='anchor' turns the text about the anchor after
            # aligning it, so va='bottom' leaves the words sitting on the line
            ax.annotate(text, (theta, r), textcoords='offset points',
                        xytext=(0, 2), color=COLOR_GALACTIC, fontsize=6,
                        alpha=0.45, ha='center', va='bottom', rotation=rot,
                        rotation_mode='anchor', zorder=0.6)
        for theta, r, text in labels:
            # plain annotate, not _place_label: grid labels are scenery and
            # must not shove a telescope or OB label out of its place
            ax.annotate(text, (theta, r), textcoords='offset points',
                        xytext=(0, 3), color=COLOR_RADEC_TEXT, fontsize=7,
                        alpha=0.55, ha='center', va='bottom', zorder=0.6)

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
        """The mount's own park flag from PMS, and nothing else.

        A mount that does not publish mount.atpark simply reads as not parked:
        guessing it from the resting position gets it wrong either way, since
        park_az in the observatory config does not match where every mount
        actually stands."""
        return bool(self._state[tel]['atpark'])

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

    def _share_covered(self, ax) -> set:
        """The telescopes whose marks are another telescope's turn to show.

        Labels can dodge each other, a dot cannot: two mounts on the same spot
        would draw dot over dot, camera over camera, bar over bar, and the top
        one would simply win. So an overlapping group shows one member at a
        time, ``TEL_SHARE_PERIOD_S`` each, in a cycle keyed to the clock rather
        than to the frame - every mount gets its seconds, and the order does
        not change under the eye.

        Overlap is judged in pixels: the radial scale is non-linear, so equal
        angles on the sky are nothing like equal distances on the disc.
        """
        spots: Dict[str, Any] = {}
        for tel in self.telescopes:
            st = self._state[tel]
            if st['az'] is None or st['alt'] is None:
                continue
            try:
                spots[tel] = ax.transData.transform(
                    (_theta(st['az']), self._radius(st['alt'])))
            except (ValueError, AttributeError, RuntimeError):
                return set()  # no usable transform yet: draw everything

        groups: List[List[str]] = []
        for tel, xy in spots.items():
            for group in groups:
                if any(math.hypot(*(xy - spots[other])) <= self.TEL_SHARE_SEP_PX
                       for other in group):
                    group.append(tel)
                    break
            else:
                groups.append([tel])

        slot = int(time.monotonic() / self.TEL_SHARE_PERIOD_S)
        covered = set()
        for group in groups:
            if len(group) < 2:
                continue
            group.sort(key=self.telescopes.index)  # a fixed turn order
            showing = group[slot % len(group)]
            covered.update(tel for tel in group if tel != showing)
        return covered

    def _draw_telescope(self, ax, tel: str, covered: bool = False) -> None:
        st = self._state[tel]
        az, alt = st['az'], st['alt']
        if az is None or alt is None:
            return
        color = self._tel_color(tel)
        stale = self._is_stale(st)
        theta, r = _theta(az), self._radius(alt)

        trail = list(st['trail'])
        if len(trail) > 1:
            thetas, radii = self._arc_trail(trail)
            # the newest arc point sits under the telescope marker itself, so
            # the head of the taper belongs to the first dot behind it
            keep = self._thin_by_screen(ax, thetas, radii)[:-1]
            fade = self._trail_fade(st)
            if len(keep) and fade > 0.0:
                sizes, alphas = self._trail_taper(len(keep))
                rgba = np.array([to_rgba(color, alpha=a * fade)
                                 for a in alphas])
                # squared: the fade scales the dot's diameter, not its area,
                # so an ageing trail visibly shrinks as well as dims
                ax.scatter(thetas[keep],
                           radii[keep],
                           s=sizes * fade ** self.TRAIL_FADE_SHRINK_POW,
                           c=rgba, edgecolors='none', zorder=4)

        target = (self._astro.get('targets') or {}).get(tel)
        label_theta, label_r = theta, r
        if target is not None and not stale:
            t_theta, t_r = _theta(target['az']), self._radius(target['alt'])
            label_theta, label_r = t_theta, t_r
            if _angular_sep(az, alt, target['az'],
                            target['alt']) > self.TARGET_MIN_SEP_DEG:
                self._draw_reticle(ax, t_theta, t_r, color)

        if st['tracking'] and not stale and not covered:
            self._draw_ping(ax, theta, r, color)

        parked = self._is_parked(tel)
        dim = self.PARKED_ALPHA if parked else 1.0
        # the dot and everything drawn onto it belong to whichever mount holds
        # this spot right now; the label stays either way, it can step aside
        if not covered:
            ax.scatter([theta], [r], s=120, c=['none'] if stale else [color],
                       edgecolors=[color], linewidths=1.8,
                       alpha=0.4 if stale else dim, zorder=9)

            if st['cover_state'] == self.COVER_CLOSED and not stale:
                self._draw_cover_cross(ax, theta, r, dim)

        self._place_label(ax, (theta, r), tel, (0, self.TEL_LABEL_DY_PX),
                          ha='center', va='top', color=color,
                          fontsize=self.MARK_FONTSIZE, fontweight='bold',
                          alpha=0.45 if stale else dim, zorder=11)

        if stale:
            return
        if parked:
            self._place_label(ax, (theta, r), 'PARKED',
                              (0, self.PARKED_LABEL_DY_PX), ha='center',
                              va='bottom', color=color,
                              fontsize=self.MARK_FONTSIZE,
                              fontweight='bold', alpha=dim, zorder=11)

        obj, progress, active = self._ob_progress(tel)
        if active and obj:
            self._place_label(ax, (label_theta, label_r), obj,
                              (0, self.OB_LABEL_DY_PX), ha='center', color=color,
                              fontsize=self.MARK_FONTSIZE, alpha=dim, zorder=11)
        if active and progress is not None and not covered:
            self._draw_progress_bar(ax, label_theta, label_r, progress, color)
        if st['camera_state'] == self.CAMERA_EXPOSING and not covered:
            self._draw_camera(ax, label_theta, label_r, dim,
                              self._filter_name(tel))

    def _arc_trail(self, trail):
        """Sampled positions densified along great-circle arcs. The mount only
        reports about once a second, so the raw samples alone would leave a few
        scattered dots instead of a tail curving the way the mount swept."""
        thetas, radii = [], []
        for (t0, az0, alt0), (t1, az1, alt1) in zip(trail, trail[1:]):
            sep = _angular_sep(az0, alt0, az1, alt1)
            steps = max(1, min(self.TRAIL_ARC_MAX_STEPS,
                               int(sep / self.TRAIL_ARC_STEP_DEG)))
            for i in range(steps):
                az, alt = _slerp_altaz(az0, alt0, az1, alt1, i / steps)
                thetas.append(_theta(az))
                radii.append(self._radius(alt))
        _, az, alt = trail[-1]
        thetas.append(_theta(az))
        radii.append(self._radius(alt))
        return np.array(thetas), np.array(radii)

    def _trail_fade(self, st: Dict[str, Any]) -> float:
        """How much of the trail is left, from how long ago the slew ended.

        The clock only starts once the mount stops: while it is slewing the
        whole path stays lit, so the small faint end of it still marks where
        the slew set off from rather than where the mount was a few seconds
        ago. Then the lot shrinks and dims away over ``trail_seconds``."""
        done = st['trail_done_t']
        if done is None:
            return 1.0
        return float(np.clip(1.0 - (time.time() - done) / self.trail_seconds,
                             0.0, 1.0))

    def _trail_taper(self, n: int):
        """Marker areas and alphas for ``n`` trail dots ordered oldest first.

        The taper runs over the dots themselves, not their age: a two-second
        slew has to fade from head to tail just as visibly as a long one, so
        the dot next to the telescope is always the big bright one and the far
        end of the path always the tiny faint one."""
        if n <= 0:
            return np.empty(0), np.empty(0)
        u = np.linspace(0.0, 1.0, n) if n > 1 else np.ones(1)
        d = (self.TRAIL_TAIL_D_PX + (self.TRAIL_HEAD_D_PX - self.TRAIL_TAIL_D_PX)
             * u ** self.TRAIL_SIZE_POW)
        alphas = (self.TRAIL_TAIL_ALPHA
                  + (self.TRAIL_HEAD_ALPHA - self.TRAIL_TAIL_ALPHA)
                  * u ** self.TRAIL_ALPHA_POW)
        return d ** 2, alphas

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

    def _draw_cover_cross(self, ax, theta: float, r: float,
                          dim: float) -> None:
        """Closed mirror cover - a thin cross over the dot, in grey rather
        than the telescope's own colour so it reads as a state and not as
        part of the marker."""
        ax.scatter([theta], [r], marker='x', s=self.COVER_X_SIZE,
                   c=[COLOR_COVER_CROSS],
                   linewidths=1.9, alpha=dim, zorder=10, clip_on=False)

    def _draw_ping(self, ax, theta: float, r: float, color: str) -> None:
        pos = self._screen_pos(ax, theta, r)
        if pos is None:
            return
        cx, cy, fx, _ = pos
        phase = (time.time() % self.PING_PERIOD_S) / self.PING_PERIOD_S
        for k in range(self.PING_RINGS):
            grow = (phase + k / self.PING_RINGS) % 1.0
            fade = min(1.0, grow / self.PING_FADE_IN) * math.sqrt(1.0 - grow)
            ax.add_patch(Circle(
                (cx, cy), (self.PING_R0_PX + self.PING_GROW_PX * grow) * fx,
                transform=ax.transAxes, facecolor='none', edgecolor=color,
                linewidth=self.PING_LW_PX * (0.6 + 0.4 * fade),
                alpha=self.PING_ALPHA * fade, zorder=3, clip_on=False))

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
            boxstyle=f'round,pad=0,rounding_size={0.79 * fx}',
            transform=ax.transAxes, facecolor=COLOR_ICON, edgecolor='none',
            alpha=alpha, zorder=10, clip_on=False))
        ax.add_patch(FancyBboxPatch(
            (x0, y0), w * fx, h * fy,
            boxstyle=f'round,pad=0,rounding_size={1.94 * fx}',
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
                    color=COLOR_ICON, fontsize=self.MARK_FONTSIZE,
                    fontweight='bold', alpha=alpha, zorder=11, clip_on=False)

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

    def _wind_level(self, speed_ms: float) -> int:
        """0 calm, 1 over the warn limit, 2 over the danger limit."""
        warn, danger = self._wind_limits()
        if speed_ms < warn:
            return 0
        return 1 if speed_ms < danger else 2

    def _wind_color(self, speed_ms: float) -> str:
        return (ck.COLOR_OK, ck.COLOR_WARN,
                ck.COLOR_DANGER)[self._wind_level(speed_ms)]

    def _draw_wind(self, ax) -> None:
        speed, direction = self._wind['ms'], self._wind['dir']
        if speed is None or direction is None:
            return
        theta = _theta(direction)
        level = self._wind_level(speed)
        color = (ck.COLOR_OK, ck.COLOR_WARN, ck.COLOR_DANGER)[level]
        # blows inward from where it comes from; annotate keeps it screen-straight
        ax.annotate('', xy=(theta, self.WIND_ARROW_R1), xytext=(theta, self.WIND_ARROW_R0),
                    arrowprops=dict(arrowstyle='-|>,head_width=0.25,head_length=0.5',
                                    color=color, linewidth=2.0, shrinkA=0, shrinkB=0,
                                    alpha=0.9), zorder=6)
        # hung off the outer end of the arrow; the plate keeps it legible
        # wherever it lands
        ax.text(theta, self.WIND_LABEL_R, f'{speed:.1f} m/s', color=color,
                fontsize=self.WIND_LABEL_FONTSIZES[level],
                fontweight='bold', ha='center', va='center',
                bbox=dict(facecolor=ck.BG_FIGURE, edgecolor='none',
                          boxstyle='round,pad=0.2', alpha=0.65),
                zorder=12)


widget_class = RadarWidget
