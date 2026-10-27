import colorsys
import logging

import matplotlib
matplotlib.use('Agg')
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import pytest

from oca_monitor.widgets import chart_kit as ck

FALLBACK = [ck.WIND_WARN_MS, ck.WIND_DANGER_MS]


def _limits(**wind) -> dict:
    return {'obs_limits': {'weather_restrictions': {'wind': wind}}}


def _cfg(global_wind: dict = None, **telescopes: dict) -> dict:
    """``tic.config.observatory`` payload: ``global_wind`` plus ``tel=wind dict`` (``None`` = no obs_limits)."""
    site = {'global': _limits(**global_wind)} if global_wind is not None else {}
    tels = {tel: {'observatory': _limits(**wind) if wind is not None else {}}
            for tel, wind in telescopes.items()}
    return {'config': {'site': site, 'telescopes': tels}}


@pytest.fixture
def production_cfg() -> dict:
    """Shape and values published since 2026-10-24 (oca-problems#273)."""
    angle = {'restricted_pointing_wind_angle': 30.0}
    cfg = _cfg(
        {'observation_stop': 14.0, 'pointing': 11.0, **angle},
        wk06={'observation_stop': 14.0, 'pointing': 6.0, **angle},
        zb08={'observation_stop': 14.0, 'pointing': 11.0, **angle},
        jk15={'observation_stop': 16.0, 'pointing': 14.0, **angle},
        wg25={'observation_stop': 16.0, 'pointing': 14.0, **angle},
        iris=None, sim=None, dev=None,
    )
    # service-tree entries that ride along in `telescopes` without being telescopes
    cfg['config']['telescopes']['global'] = {'services': ['ephemeris']}
    cfg['config']['telescopes']['tmmt'] = {'services': ['executor'], 'observatory': {'protocol': 'nats'}}
    return cfg


# ---- wind_speed_thresholds -------------------------------------------------

def test_production_config(production_cfg):
    assert ck.wind_speed_thresholds(production_cfg) == [6.0, 11.0, 14.0, 16.0]


def test_telescope_without_limits_inherits_global():
    cfg = _cfg({'observation_stop': 15, 'pointing': 9}, plain=None)
    assert ck.wind_speed_thresholds(cfg) == [9.0, 15.0]


def test_partial_override_keeps_other_global_keys():
    cfg = _cfg({'observation_stop': 14, 'pointing': 11}, tel={'pointing': 8})
    assert ck.wind_speed_thresholds(cfg) == [8.0, 14.0]


def test_global_value_overridden_everywhere_is_dropped():
    cfg = _cfg({'observation_stop': 14, 'pointing': 11}, a={'observation_stop': 16, 'pointing': 12})
    assert ck.wind_speed_thresholds(cfg) == [12.0, 16.0]


def test_no_telescopes_uses_global_alone():
    assert ck.wind_speed_thresholds(_cfg({'observation_stop': 14, 'pointing': 11})) == [11.0, 14.0]


def test_angle_is_never_collected():
    cfg = _cfg({'observation_stop': 14, 'pointing': 11, 'restricted_pointing_wind_angle': 45},
               tel={'restricted_pointing_wind_angle': 90})
    assert ck.wind_speed_thresholds(cfg) == [11.0, 14.0]


def test_duplicates_collapse_after_rounding():
    cfg = _cfg({'observation_stop': 14.004, 'pointing': 10.0},
               a={'observation_stop': 14.0}, b={'pointing': 10.001})
    assert ck.wind_speed_thresholds(cfg) == [10.0, 14.0]


def test_bad_values_skipped_with_warning(caplog):
    cfg = _cfg({'observation_stop': 14, 'pointing': 'abc'},
               tel_bad={'observation_stop': -5, 'pointing': None},
               tel_nan={'observation_stop': float('nan'), 'pointing': 0},
               tel_bool={'observation_stop': True, 'pointing': False},
               tel_good={'pointing': 8})
    with caplog.at_level(logging.WARNING):
        assert ck.wind_speed_thresholds(cfg) == [8.0, 14.0]
    warned = ' '.join(r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)
    for tel in ('tel_bad', 'tel_nan', 'tel_bool'):
        assert tel in warned


@pytest.mark.parametrize('nats_cfg', [None, {}, 'invalid', {'config': {}}, {'config': {'telescopes': []}},
                                      _cfg(None, a=None), _cfg({'pointing': -1})])
def test_missing_or_unusable_config_falls_back(nats_cfg):
    assert ck.wind_speed_thresholds(nats_cfg) == FALLBACK


# ---- colours and zones -----------------------------------------------------

def test_wind_zone_colors_ends_and_orange():
    assert ck.wind_zone_colors(0) == []
    assert ck.wind_zone_colors(1) == [ck.COLOR_OK, ck.COLOR_DANGER]
    assert ck.wind_zone_colors(2) == [ck.COLOR_OK, ck.COLOR_WIND_ORANGE, ck.COLOR_DANGER]
    assert ck.wind_zone_colors(4)[2] == ck.COLOR_WIND_ORANGE
    for n in (3, 5, 10):
        cols = ck.wind_zone_colors(n)
        assert len(cols) == n + 1
        assert (cols[0], cols[-1]) == (ck.COLOR_OK, ck.COLOR_DANGER)
        assert len(set(cols)) == n + 1  # inner bands never repeat the outer zones


@pytest.mark.parametrize('speed, zone', [(0.0, 0), (5.9, 0), (6.0, 1), (10.9, 1), (11.0, 2),
                                         (14.0, 3), (15.9, 3), (16.0, 4), (40.0, 4)])
def test_wind_zone_index(speed, zone):
    assert ck.wind_zone_index([6.0, 11.0, 14.0, 16.0], speed) == zone


@pytest.mark.parametrize('band', [ck.COLOR_OK, ck.COLOR_WIND_ORANGE, ck.COLOR_DANGER, '#8cb134', '#ef7524'])
def test_zone_boundary_color_keeps_hue(band):
    h1, l1, s1 = colorsys.rgb_to_hls(*mcolors.to_rgb(band))
    h2, l2, s2 = colorsys.rgb_to_hls(*ck.zone_boundary_color(band))
    assert min(abs(h1 - h2), 1.0 - abs(h1 - h2)) < 1e-5
    assert (l2, s2) != (l1, s1)
    assert l2 >= l1 and s2 >= min(s1, 0.85)


def test_wind_zone_bands():
    fig, ax = plt.subplots()
    try:
        assert ck.wind_zone_bands(ax, []) == []

        artists = ck.wind_zone_bands(ax, [16.0, 6.0, 14.0, 11.0])  # unsorted on purpose
        bands, lines = artists[:5], artists[5:]
        assert len(lines) == 4
        assert [b.get_y() for b in bands] == [0.0, 6.0, 11.0, 14.0, 16.0]
        assert [ln.get_ydata()[0] for ln in lines] == [6.0, 11.0, 14.0, 16.0]
        assert bands[0].get_alpha() == ck.WIND_ZONE_CALM_ALPHA
        assert {b.get_alpha() for b in bands[1:]} == {ck.WIND_ZONE_ALPHA}

        red = ck.wind_zone_bands(ax, [20.0, 30.0], top=35.0)[2]
        assert red.get_y() + red.get_height() == 60.0  # top grows to 2 × the highest limit
    finally:
        plt.close(fig)
