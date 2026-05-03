"""Site-wide ephemeris helpers for OCM, backed by pyaraucaria (≥ 2.13).

Single source of truth for sun/moon/sidereal time at Observatorio Cerro
Murphy. All UI pages should import from here so we stay numerically
consistent with toi and any other observatory tooling that uses
``pyaraucaria.ephemeris`` / ``pyaraucaria.coordinates``.

Policy: every routine here goes through pyaraucaria. If we ever need
to change the underlying algorithm, the change happens in pyaraucaria
— not here, and not in toi. Direct ``astroplan`` /
``astropy.coordinates`` imports are intentionally absent.
"""
from __future__ import annotations

import datetime
from typing import Optional

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


def next_sun_alt_event(now_utc: datetime.datetime, alt_deg: float,
                       kind: str) -> Optional[datetime.datetime]:
    """Next time the sun's centre crosses ``alt_deg`` going down
    (``kind='setting'``) or up (``kind='rising'``) at OCM.

    Returns a timezone-aware UTC ``datetime``, or ``None`` if the sun
    never reaches that altitude within the 24 h search window.
    """
    return _sun().get_next_event_by_altitude(
        alt_deg, kind, start_time=Time(now_utc))


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

    Returns a timezone-aware UTC ``datetime`` of the first crossing of
    the visible horizon (0°) after ``now_utc`` in the requested
    direction, or ``None`` if no such crossing occurs in the next 24 h.
    """
    return _moon().get_next_event_by_altitude(
        0.0, kind, start_time=Time(now_utc))


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
