import colorsys
import math
import matplotlib
matplotlib.use('Agg')
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import pytest

from oca_monitor.widgets import chart_kit as ck


@pytest.fixture
def production_cfg():
    return {
        'config': {
            'site': {
                'global': {
                    'obs_limits': {
                        'weather_restrictions': {
                            'wind': {
                                'observation_stop': 14,
                                'pointing': 11,
                                'restricted_pointing_wind_angle': 45,
                            }
                        }
                    }
                }
            },
            'telescopes': {
                'wk06': {
                    'observatory': {
                        'obs_limits': {
                            'weather_restrictions': {
                                'wind': {
                                    'observation_stop': 14,
                                    'pointing': 6,
                                }
                            }
                        }
                    }
                },
                'zb08': {
                    'observatory': {
                        'obs_limits': {
                            'weather_restrictions': {
                                'wind': {
                                    'observation_stop': 14,
                                    'pointing': 11,
                                }
                            }
                        }
                    }
                },
                'jk15': {
                    'observatory': {
                        'obs_limits': {
                            'weather_restrictions': {
                                'wind': {
                                    'observation_stop': 16,
                                    'pointing': 14,
                                }
                            }
                        }
                    }
                },
                'wg25': {
                    'observatory': {
                        'obs_limits': {
                            'weather_restrictions': {
                                'wind': {
                                    'observation_stop': 16,
                                    'pointing': 14,
                                }
                            }
                        }
                    }
                },
            }
        }
    }


def test_production_config_thresholds(production_cfg):
    thresholds = ck.wind_speed_thresholds(production_cfg)
    assert thresholds == [6.0, 11.0, 14.0, 16.0]


def test_telescope_inheritance_and_partial_override():
    cfg = {
        'config': {
            'site': {
                'global': {
                    'obs_limits': {
                        'weather_restrictions': {
                            'wind': {
                                'observation_stop': 14,
                                'pointing': 11,
                            }
                        }
                    }
                }
            },
            'telescopes': {
                # Telescope with no obs_limits inherits global
                'tel_no_limits': {
                    'observatory': {}
                },
                # Telescope with partial override (only pointing) keeps global observation_stop
                'tel_partial': {
                    'observatory': {
                        'obs_limits': {
                            'weather_restrictions': {
                                'wind': {
                                    'pointing': 7,
                                }
                            }
                        }
                    }
                },
            }
        }
    }
    thresholds = ck.wind_speed_thresholds(cfg)
    # tel_no_limits has (14, 11); tel_partial has (14, 7)
    assert thresholds == [7.0, 11.0, 14.0]


def test_restricted_pointing_wind_angle_never_collected():
    cfg = {
        'config': {
            'site': {
                'global': {
                    'obs_limits': {
                        'weather_restrictions': {
                            'wind': {
                                'observation_stop': 14,
                                'pointing': 11,
                                'restricted_pointing_wind_angle': 45,
                            }
                        }
                    }
                }
            },
            'telescopes': {
                'tel1': {
                    'observatory': {
                        'obs_limits': {
                            'weather_restrictions': {
                                'wind': {
                                    'restricted_pointing_wind_angle': 90,
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    thresholds = ck.wind_speed_thresholds(cfg)
    assert 45 not in thresholds
    assert 45.0 not in thresholds
    assert 90 not in thresholds
    assert 90.0 not in thresholds
    assert thresholds == [11.0, 14.0]


def test_bad_values_skipped(caplog):
    cfg = {
        'config': {
            'site': {
                'global': {
                    'obs_limits': {
                        'weather_restrictions': {
                            'wind': {
                                'observation_stop': 14,
                                'pointing': 'abc',
                            }
                        }
                    }
                }
            },
            'telescopes': {
                'tel_bad': {
                    'observatory': {
                        'obs_limits': {
                            'weather_restrictions': {
                                'wind': {
                                    'observation_stop': -5,
                                    'pointing': None,
                                }
                            }
                        }
                    }
                },
                'tel_nan': {
                    'observatory': {
                        'obs_limits': {
                            'weather_restrictions': {
                                'wind': {
                                    'observation_stop': float('nan'),
                                    'pointing': 0,
                                }
                            }
                        }
                    }
                },
                'tel_bool': {
                    'observatory': {
                        'obs_limits': {
                            'weather_restrictions': {
                                'wind': {
                                    'observation_stop': True,
                                    'pointing': False,
                                }
                            }
                        }
                    }
                },
                'tel_good': {
                    'observatory': {
                        'obs_limits': {
                            'weather_restrictions': {
                                'wind': {
                                    'pointing': 8,
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    with caplog.at_level('WARNING'):
        thresholds = ck.wind_speed_thresholds(cfg)
    # Only valid values: tel_good has pointing: 8 and inherits observation_stop: 14
    assert thresholds == [8.0, 14.0]
    # Check that warnings were logged naming telescopes and keys
    warnings = [r.message for r in caplog.records if r.levelname == 'WARNING']
    assert any('tel_bad' in w for w in warnings)
    assert any('tel_nan' in w for w in warnings)
    assert any('tel_bool' in w for w in warnings)


def test_empty_or_missing_config_fallback():
    assert ck.wind_speed_thresholds({}) == [ck.WIND_WARN_MS, ck.WIND_DANGER_MS]
    assert ck.wind_speed_thresholds(None) == [ck.WIND_WARN_MS, ck.WIND_DANGER_MS]
    assert ck.wind_speed_thresholds({'config': {}}) == [ck.WIND_WARN_MS, ck.WIND_DANGER_MS]
    assert ck.wind_speed_thresholds('invalid') == [ck.WIND_WARN_MS, ck.WIND_DANGER_MS]


def test_duplicates_across_telescopes_collapse():
    cfg = {
        'config': {
            'site': {
                'global': {
                    'obs_limits': {
                        'weather_restrictions': {
                            'wind': {
                                'observation_stop': 14.004,
                                'pointing': 10.0,
                            }
                        }
                    }
                }
            },
            'telescopes': {
                't1': {
                    'observatory': {
                        'obs_limits': {
                            'weather_restrictions': {
                                'wind': {
                                    'observation_stop': 14.001,
                                    'pointing': 10.0,
                                }
                            }
                        }
                    }
                },
                't2': {
                    'observatory': {
                        'obs_limits': {
                            'weather_restrictions': {
                                'wind': {
                                    'observation_stop': 14.0,
                                    'pointing': 10.002,
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    thresholds = ck.wind_speed_thresholds(cfg)
    # 14.004 and 14.001 and 14.0 round to 14.00; 10.0 and 10.002 round to 10.00
    assert thresholds == [10.0, 14.0]


def test_no_telescopes_uses_global_dict_alone():
    cfg = {
        'config': {
            'site': {
                'global': {
                    'obs_limits': {
                        'weather_restrictions': {
                            'wind': {
                                'observation_stop': 15.0,
                                'pointing': 9.0,
                            }
                        }
                    }
                }
            }
        }
    }
    thresholds = ck.wind_speed_thresholds(cfg)
    assert thresholds == [9.0, 15.0]


def test_wind_zone_colors():
    assert ck.wind_zone_colors(0) == []

    # n = 1: green and red
    cols_1 = ck.wind_zone_colors(1)
    assert len(cols_1) == 2
    assert cols_1[0] == ck.COLOR_OK
    assert cols_1[-1] == ck.COLOR_DANGER

    # n = 2: green, orange, red
    cols_2 = ck.wind_zone_colors(2)
    assert len(cols_2) == 3
    assert cols_2[0] == ck.COLOR_OK
    assert cols_2[1] == ck.COLOR_WIND_ORANGE
    assert cols_2[2] == ck.COLOR_DANGER

    # n = 4: 5 colours
    cols_4 = ck.wind_zone_colors(4)
    assert len(cols_4) == 5
    assert cols_4[0] == ck.COLOR_OK
    assert cols_4[2] == ck.COLOR_WIND_ORANGE
    assert cols_4[4] == ck.COLOR_DANGER

    # General n
    for n in (3, 5, 10):
        cols = ck.wind_zone_colors(n)
        assert len(cols) == n + 1
        assert cols[0] == ck.COLOR_OK
        assert cols[-1] == ck.COLOR_DANGER


def test_zone_boundary_color():
    for test_color in [ck.COLOR_OK, ck.COLOR_WIND_ORANGE, ck.COLOR_DANGER, '#8cb134', '#ef7524']:
        r1, g1, b1 = mcolors.to_rgb(test_color)
        h1, l1, s1 = colorsys.rgb_to_hls(r1, g1, b1)

        bcol = ck.zone_boundary_color(test_color)
        h2, l2, s2 = colorsys.rgb_to_hls(*bcol)

        # Hue is preserved within float tolerance
        diff_h = abs(h1 - h2)
        # account for wrap around at 0/1
        assert diff_h < 1e-5 or abs(diff_h - 1.0) < 1e-5

        # Lightness or saturation changed
        assert l2 != l1 or s2 != s1
        assert l2 >= l1
        assert s2 >= min(s1, 0.85)


def test_wind_zone_bands():
    fig, ax = plt.subplots()

    # Empty thresholds
    assert ck.wind_zone_bands(ax, []) == []

    # 4 thresholds: 5 bands + 4 lines = 9 artists
    thresholds = [6.0, 11.0, 14.0, 16.0]
    artists = ck.wind_zone_bands(ax, thresholds)
    assert len(artists) == 9

    # Check top scaling if threshold is high
    high_thresholds = [20.0, 30.0]
    artists_high = ck.wind_zone_bands(ax, high_thresholds, top=35.0)
    # top should be max(35.0, 2 * 30.0) = 60.0
    assert len(artists_high) == 5
    # The last band (red) is index 2 among bands (artists_high[2])
    # Its y-range should extend to 60.0
    last_band = artists_high[2]
    # axhspan creates a Polygon whose y-extent top is y + height
    max_y = last_band.get_y() + last_band.get_height()
    assert max_y == 60.0

    plt.close(fig)
