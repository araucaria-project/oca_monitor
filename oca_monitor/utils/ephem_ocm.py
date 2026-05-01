"""Site-wide ephemeris helpers for OCM, backed by pyaraucaria.

Single source of truth for sun/moon/sidereal time at Observatorio Cerro
Murphy. All UI pages should import from here so we stay numerically
consistent with toi and any other observatory tooling that uses
``pyaraucaria.ephemeris`` / ``pyaraucaria.coordinates``.

Policy: every routine here goes through pyaraucaria, even when
pyaraucaria itself just delegates to astroplan/astropy. If we ever
need to change the underlying algorithm, the change happens in
pyaraucaria — not here, and not in toi. Direct ``astroplan`` /
``astropy.coordinates`` imports are intentionally absent.

Known pyaraucaria gaps (to be addressed upstream, not papered over
here):
  * No moonrise/moonset convenience parallel to ``calculate_sun_rise_set``.
    Until pyaraucaria adds one, we use ``Moon.get_events_by_altitude``,
    which uses a 5-minute grid + scipy-spline root finding (different
    algorithm from sun rise/set). Numerically agrees within a few
    seconds; precise enough for a clock display.
  * ``site_sidereal_time`` is still ephem-backed inside pyaraucaria.
    Going through pyaraucaria here means we share that choice with toi
    until pyaraucaria switches to astropy.
"""
from __future__ import annotations

import datetime
from typing import Optional

import astropy.units as u
from astropy.coordinates import EarthLocation
from astropy.time import Time

from pyaraucaria.coordinates import site_sidereal_time
from pyaraucaria.ephemeris import (
    Moon as _PMoon,
    Sun as _PSun,
    calculate_sun_rise_set,
)


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


def next_sun_alt_event(now_utc: datetime.datetime, alt_deg: float,
                       kind: str) -> Optional[datetime.datetime]:
    """Next time the sun's centre crosses ``alt_deg`` going down
    (``kind='setting'``) or up (``kind='rising'``) at OCM.

    Returns timezone-aware UTC datetime, or ``None`` if the sun never
    reaches that altitude (polar geometry — not expected at OCM).
    """
    try:
        return calculate_sun_rise_set(
            date=now_utc,
            horiz_height=alt_deg,
            sunrise=(kind == 'rising'),
            latitude=OCM_LATITUDE,
            longitude=OCM_LONGITUDE,
            elevation=OCM_ELEVATION_M,
        )
    except Exception:
        return None


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
    extrema.
    """
    t = Time(now_utc) if now_utc is not None else Time.now()
    eph_now = _moon().get_ephemeris(t)[0]
    eph_later = _moon().get_ephemeris(t + 1 * u.hour)[0]
    return {
        'alt_deg': float(eph_now['alt']),
        'phase': float(eph_now['phase']),  # 0..1
        'waxing': float(eph_later['phase']) > float(eph_now['phase']),
    }


def next_moon_event(now_utc: datetime.datetime,
                    kind: str) -> Optional[datetime.datetime]:
    """Next moonrise (``kind='rising'``) or moonset (``kind='setting'``).

    Uses ``Moon.get_events_by_altitude([0.0])`` — pyaraucaria's
    spline-based finder. Returns the first crossing after ``now_utc``
    in the requested direction.
    """
    try:
        events = _moon().get_events_by_altitude(
            [0.0], start_time=Time(now_utc))
    except Exception:
        return None
    if not events:
        return None
    # Direction of each crossing isn't reported by get_events_by_altitude,
    # so derive it from current alt: each crossing flips above↔below.
    state_up = float(
        _moon().get_ephemeris(Time(now_utc))[0]['alt']) > 0.0
    want_setting = (kind == 'setting')
    for ev in events:
        ev_time = ev['time_utc']
        if ev_time <= now_utc:
            continue
        is_setting = state_up   # crossing while up → going down → setting
        if is_setting == want_setting:
            return ev_time
        state_up = not state_up
    return None


# ---------------------------------------------------------------------------
# Sidereal time
# ---------------------------------------------------------------------------

def sidereal_time_str(now_utc: Optional[datetime.datetime] = None) -> str:
    """Local apparent sidereal time at OCM, formatted ``HH:MM:SS``.

    Goes through ``pyaraucaria.coordinates.site_sidereal_time`` (which
    is currently ephem-backed inside pyaraucaria — see module
    docstring).
    """
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
