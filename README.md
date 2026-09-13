# oca_monitor

Program with GUI to monitor different systems (telescopes, weather, environment, electricity, etc.) at Observatorio
Cerro Murphy.

Requirements:
* python 3.11 - 3.13
* poetry
* PyQt6 (from PyPI on x86, from the distro on Raspberry Pi -- see below)

Everything else (astropy, matplotlib, numpy, opencv, serverish, ...) is installed by `poetry install`.

# Running

```bash
poetry run ocam --env kitchen
```

`--env` selects a section of `settings.toml` (`kitchen`, `tvroom`, `aux`, `touch_controlroom`, ...); it can also be
given as the `OCAMONITOR_ENV` environment variable. Without it, `[default]` is used. `--log-level DEBUG` raises the
logging level.

# Chart overlays — FWHM and Photometric Zero

The weather/conditions page (`pages/weather.py`) renders a stack of squeezed
charts. Two of them carry a large in-chart overlay value with non-obvious
semantics:

**FWHM (`fwhm` chart) — round-robin overlay.** The overlay does not show
"the most recent FWHM regardless of telescope". Instead it cycles through
telescopes every 3 s (`OVERLAY_ROTATE_SEC`), showing each telescope's last
FWHM in turn, coloured by that telescope. A telescope is included in the
rotation only while its last sample arrived within 15 minutes
(`OVERLAY_FRESH_WINDOW_SEC`) of the most recent sample on *any*
telescope — the gate is inter-telescope arrival skew, not wall-clock,
so when all telescopes stop together at the end of the night they all
keep cycling (showing the seeing at end-of-night), while a single
telescope that stalls or is taken offline mid-night drops out about
15 minutes later so observers aren't misled by stale seeing.

**Photometric Zero (`phot_zero` chart) — site-wide trend overlay.** The
overlay tracks the *trend line's* tip (the bright white smoothed mean
across all telescopes), not any single telescope's last frame, so it
conveys current site-wide photometric quality. Its colour follows the
alert zones: green when the site is photometric, amber when degraded,
red when poor. The white trend line itself sits above the per-telescope
scatter at high opacity so it reads as the headline signal of the panel
without being thick enough to obscure individual points.

# Adding/modifying panels and tabs

The window is a grid of panels, each panel a stack of tabs, all of it driven by `settings.toml` -- no code change is
needed to rearrange a screen. Grid size comes from `panel_rows` / `panel_columns`, and each tab is one section:

```toml
[kitchen.panels.10.Weather]     # row 1, column 0, tab labelled "Weather"
source = "weather"              # the page class lives in oca_monitor/pages/weather.py
auto_interval = 10              # seconds before auto-switching to the next tab in this panel
```

`source` is imported as `oca_monitor.pages.<source>`, which must define `widget_class`; every other key in the section
is passed to its constructor as a keyword argument. Existing pages are in `oca_monitor/pages/`, `pages/example.py`
being the minimal template.

(The top-level `oca_monit*.py` files are the old, pre-`oca_monitor/` application, still reachable as `ocam_old`. Tabs
and telescopes there are listed at the end of `oca_monit_tabs.py` and `oca_monit_telescopes.py`.)

# Installing on Raspberry PI

Poetry does not install PyQt6 on ARM: the ARM64 wheels on PyPI require glibc >= 2.39 and Raspberry Pi OS Bookworm has
2.36, so pip would fall back to the source distribution and try to build Qt. `pyproject.toml` therefore skips `pyqt6`
on ARM via a platform marker -- take the bindings from the distro instead. No extras or flags needed.

1. System Qt bindings. `qtsvg` is **required** (matplotlib imports `PyQt6.QtSvg`, and Debian ships it separately from
   `python3-pyqt6`):

   ```bash
   sudo apt install python3-pyqt6 python3-pyqt6.qtsvg python3-pyqt6.sip
   ```

2. Let the project venv see them, then install the rest:

   ```bash
   poetry config virtualenvs.options.system-site-packages true
   poetry env remove --all   # only if a .venv already exists
   poetry install
   ```

3. Check and run:

   ```bash
   poetry run python -c "from PyQt6 import QtWidgets, QtSvg; from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg; print('OK')"
   poetry run ocam --env kitchen
   ```

Notes:
* Bookworm ships PyQt6 6.4.2, which covers every Qt class this app uses.
* Do not run `poetry install --sync` here -- with `system-site-packages` it may try to remove distro packages.
* `poetry config` is used without `--local` on purpose: `poetry.toml` is tracked in git and this setting is wanted
  only on the Pi.
* On Raspberry Pi OS **Trixie** (glibc 2.41) none of this applies -- a plain `poetry install` pulls PyQt6 from PyPI.
* Last resort: clone the SD card of a working RPi (a copy is on a pendrive) with
  `dd bs=4M if=/dev/pendrive_name of=/dev/sd_name status=progress`, then change the hostname in
  Raspberry Menu > Preferences > Raspberry Pi Configuration and make sure the MAC address is unique in the network.

# Adding application icon to the menu

To add application icon to the menu you have to symlink the desktop file to the `~/.local/share/applications/`
directory.
The desktop files are located in the `desktop` directory of the project.
The command to do this is e.g:

```bash
ln -s ~/src/oca_monitor/desktop/tvroom.desktop ~/.local/share/applications/ocam.desktop
```