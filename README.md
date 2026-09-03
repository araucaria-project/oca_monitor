# oca_monitor

Program with GUI to monitor different systems (telescopes, weather, environement, electricity, etc.) at Observatorio
Cerro Murphy.

Requirements:
* python 3
* PyQt6
* astropy
* matplotlib

# Running

```bash
poetry run ocam --env <envname>
```

where `<envname>` is the name of the settings section (e.g. `kitchen`)

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

# Adding/modifying tabs

Edit oca_monit_tabs.py and add new tab name to the "tabList" (the and of the file)

# Adding/modifying telescopes

Edit oca_monit_telescopes.py and add new telescope name to the "telescopesList" (the and of the file)

# Installing on Raspberry PI

Raspberry Pi OS **Bookworm** has glibc 2.36, but the ARM64 PyQt6 wheels on PyPI
are tagged `manylinux_2_39` (glibc >= 2.39), so poetry cannot install PyQt6 there
-- it falls back to the source distribution and tries to build Qt, which never
finishes. Instead, take the Qt bindings from the distro and let poetry handle
everything else (all the remaining dependencies do have aarch64 wheels).

`pyproject.toml` skips pyqt6 on ARM via a platform marker, so no flags or extras
are needed -- `poetry install` does the right thing on both ARM and x86.

1. Install the system bindings. The `qtsvg` package is **not** optional:
   matplotlib imports `PyQt6.QtSvg` when it picks up the PyQt6 binding, and
   Debian ships QtSvg separately from `python3-pyqt6` (which only carries
   QtCore, QtGui, QtWidgets and QtNetwork).

   ```bash
   sudo apt install python3-pyqt6 python3-pyqt6.qtsvg python3-pyqt6.sip
   python3 -c "from PyQt6 import QtCore, QtGui, QtWidgets, QtSvg, sip; print(QtCore.QT_VERSION_STR, QtCore.PYQT_VERSION_STR)"
   ```

   Bookworm ships PyQt6 6.4.2, which covers every Qt class this app uses.

2. Let the project venv see those system packages. Keep this in the machine-wide
   poetry config rather than `poetry config --local`, because `poetry.toml` is
   tracked in git and the setting is only wanted on the Pi:

   ```bash
   poetry config virtualenvs.options.system-site-packages true
   poetry env remove --all   # only if a .venv already exists
   poetry install
   ```

3. Check that the charts can start:

   ```bash
   poetry run python -c "from PyQt6 import QtWidgets; from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg; print('OK')"
   ```

Do not use `poetry install --sync` on the Pi: with `system-site-packages` enabled
it may try to remove distro-managed packages.

On Raspberry Pi OS **Trixie** (glibc 2.41) none of this is needed -- the PyPI
wheels install normally, so a plain `poetry install` is enough.

If you would rather not install anything, it is still possible to copy the SD
card of a working RPi. A copy is available on a pendrive; insert both the
pendrive and the target SD card into a PC, find their `/dev/sd...` names (list
`/dev/` with the device disconnected, then connected, and compare), then:

```
dd bs=4M if=/dev/pendrive_name of=/dev/sd_name status=progress
```

Wait about 10 minutes. When it is ready you can insert SD card to RPi and boot. Now you just have to change the host
name (in Raspberry Menu>Preferences>Raspberry Pi Configuration). Then make sure that the mac address of the new RPi is
different from already existing in the network (it has to be different, but make sure :)). Now your RPi is configured
and you can run oca monitor.

# Adding application icon to the menu

To add application icon to the menu you have to symlink the desktop file to the `~/.local/share/applications/`
directory.
The desktop files are located in the `desktop` directory of the project.
The command to do this is e.g:

```bash
ln -s /src/oca_monitor/desktop/tvroom.desktop ~/.local/share/applications/ocam.desktop
```