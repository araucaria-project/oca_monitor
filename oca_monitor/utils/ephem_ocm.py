"""Site-wide ephemeris helpers for OCM, backed by pyaraucaria (≥ 2.13).

Single source of truth for sun/moon/sidereal time at Observatorio Cerro
Murphy. All UI pages should import from here so we stay numerically
consistent with toi and any other observatory tooling that uses
``pyaraucaria.ephemeris`` / ``pyaraucaria.coordinates``.

Policy: every routine here goes through pyaraucaria. If we ever need
to change the underlying algorithm, the change happens in pyaraucaria
— not here, and not in toi. Direct ``astroplan`` /
``astropy.coordinates`` imports are intentionally absent.

Performance note: pyaraucaria's spline-based event finder builds a
24 h AltAz grid per call (~200 ms on a typical workstation). UI pages
call ``next_sun_alt_event`` ≈10 times per tick (multiple twilight
altitudes × rise/set), at 1 Hz, so naive use blocks the qasync event
loop for >2 s every second — long enough to time out concurrent NATS
JetStream API requests during startup. We therefore cache results
with a short TTL: rise/set times shift by minutes per day, so a 60 s
cache is invisible to the UI; ``moon_state`` (alt/phase, drifts ~15°/h)
is cached for 5 s. Cache entries automatically invalidate when the
event passes ``now``.
"""
from __future__ import annotations

import datetime
import time as _time
from typing import Optional, Tuple, Dict

import astropy.units as u
from astropy.coordinates import EarthLocation
from astropy.time import Time

from pyaraucaria.coordinates import site_sidereal_time
from pyaraucaria.ephemeris import Moon as _PMoon, Sun as _PSun


# Coordinates: Observatorio Cerro Murphy. These match the values
# used by toi's site config and the legacy oca_monitor pages — keep
# identical when updating.
OCM_LATITUDE = -24.598616
OCM_LONGITUDE = -70.201266
OCM_ELEVATION_M = 2800.0


_LOCATION: Optional[EarthLocation] = None
_SUN: Optional[_PSun] = None
_MOON: Optional[_PMoon] = None


def location() -> EarthLocation:
    """OCM as an astropy ``EarthLocation`` — required by the pyaraucaria
    ``Sun``/``Moon`` constructors. Cached because building one is
    measurable on cold start."""
    global _LOCATION
    if _LOCATION is None:
        _LOCATION = EarthLocation(
            lat=OCM_LATITUDE * u.deg,
            lon=OCM_LONGITUDE * u.deg,
            height=OCM_ELEVATION_M * u.m,
        )
    return _LOCATION


def _sun() -> _PSun:
    global _SUN
    if _SUN is None:
        _SUN = _PSun(location())
    return _SUN


def _moon() -> _PMoon:
    global _MOON
    if _MOON is None:
        _MOON = _PMoon(location())
    return _MOON


# ---------------------------------------------------------------------------
# Sun
# ---------------------------------------------------------------------------

def sun_alt_deg(now_utc: Optional[datetime.datetime] = None) -> float:
    """Current sun altitude at OCM in degrees."""
    t = Time(now_utc) if now_utc is not None else Time.now()
    return float(_sun().get_ephemeris(t)[0]['alt'])


# TTL caches (see module docstring). Keys hold (perf_clock_at_compute,
# event_datetime_or_None). Entries are invalidated either by age or by
# the event passing ``now``.
_SUN_EVENT_TTL_S = 60.0
_MOON_EVENT_TTL_S = 60.0
_MOON_STATE_TTL_S = 5.0
_sun_event_cache: Dict[Tuple[float, str], Tuple[float, Optional[datetime.datetime]]] = {}
_moon_event_cache: Dict[str, Tuple[float, Optional[datetime.datetime]]] = {}
_moon_state_cache: Optional[Tuple[float, dict]] = None


def next_sun_alt_event(now_utc: datetime.datetime, alt_deg: float,
                       kind: str) -> Optional[datetime.datetime]:
    """Next time the sun's centre crosses ``alt_deg`` going down
    (``kind='setting'``) or up (``kind='rising'``) at OCM.

    Returns a timezone-aware UTC ``datetime``, or ``None`` if the sun
    never reaches that altitude within the 24 h search window. Result
    is cached for ``_SUN_EVENT_TTL_S`` seconds and auto-invalidated
    once the event passes ``now_utc`` — the UI can poll this at 1 Hz
    without re-running the spline finder each call.
    """
    key = (float(alt_deg), kind)
    cached = _sun_event_cache.get(key)
    if cached is not None:
        ts, dt = cached
        if (_time.monotonic() - ts) < _SUN_EVENT_TTL_S and (dt is None or dt > now_utc):
            return dt
    dt = _sun().get_next_event_by_altitude(
        alt_deg, kind, start_time=Time(now_utc))
    _sun_event_cache[key] = (_time.monotonic(), dt)
    return dt


def next_sunset_utc(now_utc: datetime.datetime,
                    horizon_deg: float = 0.0) -> Optional[datetime.datetime]:
    """Convenience wrapper for ``next_sun_alt_event(..., kind='setting')``."""
    return next_sun_alt_event(now_utc, horizon_deg, 'setting')


# ---------------------------------------------------------------------------
# Moon
# ---------------------------------------------------------------------------

def moon_state(now_utc: Optional[datetime.datetime] = None) -> dict:
    """Current moon altitude (deg), illumination phase (0..1) and waxing flag.

    All three values come from a single ``Moon.get_ephemeris`` call so
    the alt and phase are guaranteed self-consistent (same instant,
    same astropy/astroplan path). Waxing direction is derived from a
    1-hour-later phase sample — cheap, monotone between new/full
    extrema. Cached for ``_MOON_STATE_TTL_S`` s — moon altitude
    drifts ~15°/h so a 5 s cache is invisible to the UI.
    """
    global _moon_state_cache
    if _moon_state_cache is not None:
        ts, state = _moon_state_cache
        if (_time.monotonic() - ts) < _MOON_STATE_TTL_S:
            return state
    t = Time(now_utc) if now_utc is not None else Time.now()
    eph_now = _moon().get_ephemeris(t)[0]
    eph_later = _moon().get_ephemeris(t + 1 * u.hour)[0]
    state = {
        'alt_deg': float(eph_now['alt']),
        'phase': float(eph_now['phase']),  # 0..1
        'waxing': float(eph_later['phase']) > float(eph_now['phase']),
    }
    _moon_state_cache = (_time.monotonic(), state)
    return state


def next_moon_event(now_utc: datetime.datetime,
                    kind: str) -> Optional[datetime.datetime]:
    """Next moonrise (``kind='rising'``) or moonset (``kind='setting'``).

    Returns a timezone-aware UTC ``datetime`` of the first crossing of
    the visible horizon (0°) after ``now_utc`` in the requested
    direction, or ``None`` if no such crossing occurs in the next 24 h.
    Cached for ``_MOON_EVENT_TTL_S`` s, auto-invalidated when the event
    passes.
    """
    cached = _moon_event_cache.get(kind)
    if cached is not None:
        ts, dt = cached
        if (_time.monotonic() - ts) < _MOON_EVENT_TTL_S and (dt is None or dt > now_utc):
            return dt
    dt = _moon().get_next_event_by_altitude(
        0.0, kind, start_time=Time(now_utc))
    _moon_event_cache[kind] = (_time.monotonic(), dt)
    return dt


# ---------------------------------------------------------------------------
# Sidereal time
# ---------------------------------------------------------------------------

def sidereal_time_str(now_utc: Optional[datetime.datetime] = None) -> str:
    """Local apparent sidereal time at OCM, formatted ``HH:MM:SS``."""
    t = now_utc if now_utc is not None else datetime.datetime.now(
        datetime.timezone.utc)
    # pyaraucaria returns sidereal time in decimal degrees.
    deg = site_sidereal_time(
        longitude=OCM_LONGITUDE,
        latitude=OCM_LATITUDE,
        elevation=OCM_ELEVATION_M,
        time=t,
    )
    hours = deg / 15.0
    h = int(hours) % 24
    m_full = (hours - int(hours)) * 60.0
    m = int(m_full)
    s = int((m_full - m) * 60.0)
    return f"{h:02d}:{m:02d}:{s:02d}"
