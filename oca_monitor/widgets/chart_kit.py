"""Shared matplotlib styling primitives for the oca_monitor weather/quality stack.

Designed so the same visual language can be lifted into halina (Plotly)
later — colors, alert thresholds and inline-title positioning translate
1:1; only the rendering API differs.
"""
from __future__ import annotations

import logging
import math
from typing import List, Optional, Sequence, Tuple

import numpy as np
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator

logger = logging.getLogger(__name__.rsplit('.')[-1])


# ---- Alert thresholds (mirrored across halina) -----------------------------
WIND_WARN_MS = 11.0
WIND_DANGER_MS = 14.0

HUMIDITY_WARN_PCT = 70.0
HUMIDITY_DANGER_PCT = 80.0


# ---- Dark-theme palette ----------------------------------------------------
BG_FIGURE = '#181818'
BG_AXES = '#202020'
FG_TEXT = '#e0e0e0'
FG_DIM = '#9a9a9a'
GRID_MAJOR = '#3a3a3a'
GRID_MINOR = '#2a2a2a'
SPINE = '#404040'

COLOR_TODAY = '#5cc4ff'
COLOR_YESTERDAY = '#5a5a5a'  # legacy fallback; new style uses today-colour faded
YESTERDAY_ALPHA = 0.30
COLOR_WIND_ARROW = '#f5fbff'

COLOR_WARN = '#f6ce46'
COLOR_DANGER = '#ea4d3d'
COLOR_WIND_WARN = COLOR_WARN
COLOR_WIND_DANGER = COLOR_DANGER
COLOR_HUMIDITY = '#6ed0a8'
COLOR_HUMIDITY_WARN = COLOR_WARN
COLOR_HUMIDITY_DANGER = COLOR_DANGER
COLOR_PRESSURE = '#c98bd6'
COLOR_TEMPERATURE = '#ffb070'
COLOR_BATTERY = '#7eea90'
COLOR_SOLAR = '#fcb841'
COLOR_LOAD = '#ff8866'
COLOR_DOME_DANGER = COLOR_DANGER


# ---- Figure / axes setup ---------------------------------------------------

def style_figure(fig: Figure) -> None:
    fig.patch.set_facecolor(BG_FIGURE)


def style_axes(ax: Axes) -> None:
    ax.set_facecolor(BG_AXES)
    for spine in ax.spines.values():
        spine.set_color(SPINE)
    # Brighten the horizontal panel boundaries so adjacent stacked panels
    # are visually separated even with hspace=0.
    for side in ('top', 'bottom'):
        ax.spines[side].set_color('#7a7a7a')
        ax.spines[side].set_linewidth(1.2)
    ax.tick_params(colors=FG_DIM, which='both', labelsize=10)
    ax.grid(True, which='major', color=GRID_MAJOR, linewidth=0.6, alpha=0.7)
    ax.grid(True, which='minor', color=GRID_MINOR, linewidth=0.4, alpha=0.5)


def make_stacked_axes(fig: Figure, n: int) -> List[Axes]:
    """Stack N subplots vertically with shared X and zero inter-axis padding.

    Only the bottom axis displays X tick labels; intermediate axes share
    spines with their neighbours so the stack looks like one continuous
    chart. Returns the axes top-to-bottom.
    """
    fig.clear()
    style_figure(fig)
    if n <= 0:
        return []
    axes = fig.subplots(n, 1, sharex=True, gridspec_kw={'hspace': 0.0})
    if n == 1:
        axes = [axes]
    for ax in axes:
        style_axes(ax)
    for ax in axes[:-1]:
        ax.tick_params(axis='x', which='both', labelbottom=False, length=0)
    # Prune the y-tick labels that would collide across the zero-gap
    # boundary between adjacent panels.
    for i, ax in enumerate(axes):
        if len(axes) == 1:
            break
        if i == 0:
            prune = 'lower'
        elif i == len(axes) - 1:
            prune = 'upper'
        else:
            prune = 'both'
        ax.yaxis.set_major_locator(MaxNLocator(prune=prune, nbins='auto'))
    # Tight margins — both X tick labels and the right-hand twin-axis Y
    # tick labels are pulled inside the chart area by the panel code so we
    # only need a hair of breathing room.
    fig.subplots_adjust(left=0.06, right=0.985, top=0.985, bottom=0.025)
    return list(axes)


def inline_title(ax: Axes, text: str, *, side: str = 'left',
                 color: Optional[str] = None) -> None:
    """Pill-style title overlaid in the upper corner of the axes."""
    x, ha = (0.012, 'left') if side == 'left' else (0.988, 'right')
    ax.text(x, 0.94, text, transform=ax.transAxes,
            color=color or FG_TEXT, fontsize=11, fontweight='bold',
            alpha=0.55, va='top', ha=ha,
            bbox=dict(facecolor='#101010', edgecolor='#383838',
                      boxstyle='round,pad=0.3', alpha=0.40),
            zorder=5)


def big_overlay(ax: Axes, *, x: float = 0.99, y: float = 0.55,
                ha: str = 'right', va: str = 'center',
                fontsize: int = 30, alpha: float = 0.55,
                color: Optional[str] = None):
    """Create an empty translucent live-value overlay; returns the Text object.

    Drawn at a high z-order (12) so it sits on top of inline title pills
    even when those pills live on a twin axis that is otherwise rendered
    last.
    """
    return ax.text(
        x, y, '', transform=ax.transAxes,
        ha=ha, va=va, fontsize=fontsize, fontweight='bold',
        color=color or FG_TEXT, alpha=alpha, zorder=12,
    )


def format_hour_xaxis(ax: Axes, *, x_min: float = 0.0, x_max: float = 24.0) -> None:
    """Hour ticks 0–24 with labels pulled INSIDE the chart area to save vertical space."""
    ax.set_xlim(x_min, x_max)
    ax.set_xticks(range(int(x_min), int(x_max) + 1, 3))
    ax.set_xticks(range(int(x_min), int(x_max) + 1, 1), minor=True)
    ax.tick_params(axis='x', which='major', direction='in', length=5,
                   pad=-14, labelsize=10, colors=FG_DIM)
    ax.tick_params(axis='x', which='minor', direction='in', length=3,
                   colors=FG_DIM)


def decimate_xy(x, y, max_points: int = 1500):
    """Bin (x, y) to at most ``max_points`` points by mean over equal-width index bins.

    Cheap-O(N) downsample for matplotlib lines whose underlying series is
    much denser than the rendering surface. Smoothing should happen
    BEFORE this call — decimation only controls visual point density.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = x.size
    if n <= max_points or max_points <= 0:
        return x, y
    edges = np.linspace(0, n, max_points + 1, dtype=int)
    out_x = np.empty(max_points)
    out_y = np.empty(max_points)
    for i in range(max_points):
        lo, hi = edges[i], edges[i + 1]
        if hi > lo:
            out_x[i] = x[lo:hi].mean()
            out_y[i] = y[lo:hi].mean()
        else:
            out_x[i] = x[lo]
            out_y[i] = y[lo]
    return out_x, out_y


def running_mean(values, window: int = 11):
    """Centred moving average; reflects edges to avoid ramp artefacts.

    Returns the input untouched when ``window <= 1`` or there is too little
    data to smooth meaningfully. Window is forced odd so the smoothed value
    is centred on its source sample.
    """
    a = np.asarray(values, dtype=float)
    n = a.size
    if window <= 1 or n == 0:
        return a
    w = min(window, n)
    if w % 2 == 0:
        w += 1
    if w <= 1:
        return a
    pad = w // 2
    padded = np.pad(a, pad, mode='edge')
    kernel = np.ones(w) / w
    return np.convolve(padded, kernel, mode='valid')[:n]


# ---- Zone bands ------------------------------------------------------------

def wind_zone_bands(ax: Axes, *, top: float = 35.0) -> None:
    ax.axhspan(WIND_WARN_MS, WIND_DANGER_MS,
               color=COLOR_WIND_WARN, alpha=0.18, linewidth=0, zorder=0)
    ax.axhspan(WIND_DANGER_MS, top,
               color=COLOR_WIND_DANGER, alpha=0.22, linewidth=0, zorder=0)


def humidity_zone_bands(ax: Axes) -> None:
    ax.axhspan(HUMIDITY_WARN_PCT, HUMIDITY_DANGER_PCT,
               color=COLOR_HUMIDITY_WARN, alpha=0.15, linewidth=0, zorder=0)
    ax.axhspan(HUMIDITY_DANGER_PCT, 100.0,
               color=COLOR_HUMIDITY_DANGER, alpha=0.20, linewidth=0, zorder=0)


# ---- Compass-direction utilities ------------------------------------------

def circular_diff_deg(a: float, b: float) -> float:
    """Smallest absolute angular distance between two compass headings, in [0, 180]."""
    d = abs((a - b) % 360.0)
    return d if d <= 180.0 else 360.0 - d


def vector_mean_deg(degrees: Sequence[float]) -> Optional[float]:
    """Vector-average of compass headings (handles wrap at 0/360)."""
    if not len(degrees):
        return None
    rad = np.deg2rad(degrees)
    s = float(np.sin(rad).mean())
    c = float(np.cos(rad).mean())
    if s == 0.0 and c == 0.0:
        return None
    return math.degrees(math.atan2(s, c)) % 360.0


def bin_directions(times: Sequence[float], dirs: Sequence[float],
                   *, x_min: float = 0.0, x_max: float = 24.0,
                   n_bins: int = 12) -> Tuple[List[float], List[float]]:
    """Bin (time, dir) into equal-width buckets, return (centers, mean_dirs) for non-empty bins."""
    if not len(times):
        return [], []
    edges = np.linspace(x_min, x_max, n_bins + 1)
    arr_t = np.asarray(times, dtype=float)
    arr_d = np.asarray(dirs, dtype=float)
    centers: List[float] = []
    means: List[float] = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (arr_t >= lo) & (arr_t < hi)
        if not mask.any():
            continue
        m = vector_mean_deg(arr_d[mask].tolist())
        if m is None:
            continue
        centers.append(0.5 * (lo + hi))
        means.append(m)
    return centers, means


def compass_to_uv(headings_deg: Sequence[float], *,
                  flow_to: bool = True) -> Tuple[np.ndarray, np.ndarray]:
    """Convert compass headings to (U, V) unit vectors.

    Wind direction is reported as "from" (meteorological convention). With
    ``flow_to=True`` the returned vectors point in the direction the wind is
    going to — matching the windy.com visual convention where arrowheads
    indicate flow.
    """
    arr = np.asarray(headings_deg, dtype=float)
    if flow_to:
        arr = (arr + 180.0) % 360.0
    # compass θ (0=N, clockwise) → math angle (0=E, ccw): 90 − θ
    rad = np.deg2rad(90.0 - arr)
    return np.cos(rad), np.sin(rad)


# ---- Telescope colour lookup ----------------------------------------------

# Fallbacks used only until ``tic.config.observatory`` arrives. Mirror the
# real ``style.color`` values published by the observatory config so the
# initial paint is already correct; once nats_cfg loads, panels re-stamp
# their lines with the live values via ``restamp_telescope_colors``.
_FALLBACK_TELESCOPE_COLORS = {
    'wk06': '#14AD4E',
    'zb08': '#0082E8',
    'jk15': '#67F4F5',
    'wg25': '#FF8C00',
    'iris': '#FF2F13',
    'sim':  '#808080',
    'dev':  '#FF00FF',
}


# Photometric-band marker colours (mirrors halina's ChartBuilder).
PHOT_FILTER_COLORS = {
    'V': '#22c55e',
    'B': '#3b82f6',
    'Ic': '#ef4444',
    'I': '#ef4444',
    'R': '#f97316',
    'U': '#a855f7',
    'g': '#38bdf8',
    'r': '#ef4444',
    'i': '#ec4899',
}


def telescope_color(main_window, tel: str) -> str:
    cfg = getattr(main_window, 'nats_cfg', None) or {}
    try:
        return cfg['config']['telescopes'][tel]['observatory']['style']['color']
    except (KeyError, TypeError):
        return _FALLBACK_TELESCOPE_COLORS.get(tel, '#9a9a9a')


def blend_colors(c1, c2, t: float = 0.5):
    """Linear mix of two colors. ``t=0`` → c1, ``t=1`` → c2.

    Accepts any colour matplotlib understands (hex, name, RGB tuple).
    Returned as an RGB tuple (matplotlib accepts these directly).
    """
    from matplotlib.colors import to_rgb
    r1, g1, b1 = to_rgb(c1)
    r2, g2, b2 = to_rgb(c2)
    return (r1 * (1 - t) + r2 * t,
            g1 * (1 - t) + g2 * t,
            b1 * (1 - t) + b2 * t)
